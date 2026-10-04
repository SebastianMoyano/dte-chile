// Captura SII v2 — SIN depurador: nada que Chrome pueda soltar. Observa la red con webRequest,
// recibe de la página su HTML y las respuestas AJAX, y persiste cada entrada en storage al
// instante (el service worker puede dormirse; la grabación no). Solo se detiene con el botón.

const ES_SII = url => { try { return /(^|\.)sii\.cl$/i.test(new URL(url).hostname); } catch { return false; } };
const RUIDO = /\.(png|jpe?g|gif|svg|ico|woff2?|ttf|css|js)(\?|$)|\/JS\/|qualtrics|google-analytics|googletagmanager|\/TSbd\/|AutTknData/i;

function tachar(texto) {
  if (texto == null) return texto;
  return String(texto)
    .replace(/((?:^|[&?])(?:clave|password|passwd|pwd|pass|myPass|SII_PASSWORD|SII_CERT_PASS)=)[^&\s]*/gi, "$1***")
    .replace(/("(?:clave|password|passwd|pwd|pass)"\s*:\s*")[^"]*(")/gi, "$1***$2")
    .replace(/(name=["'](?:clave|myPass)["'][^>]*value=["'])[^"']*(["'])/gi, "$1***$2")
    .replace(/(NETSCAPE_LIVEWIRE\.mac=)[^;\s"]*/g, "$1***")
    .replace(/((?:TOKEN|CSESSIONID)=)[^;\s"]*/g, "$1***");
}
const SECRETO = /^(clave|password|passwd|pwd|pass|myPass)$/i;
function cabecerasLimpias(lista) {
  const out = {};
  for (const h of lista || []) out[h.name] = /^(cookie|set-cookie|authorization)$/i.test(h.name) ? "(omitida)" : (h.value ?? "(binario)");
  return out;
}
function cuerpoDe(requestBody) {
  if (!requestBody) return null;
  if (requestBody.formData) {
    const partes = [];
    for (const [k, vs] of Object.entries(requestBody.formData)) for (const v of vs) partes.push(`${k}=${SECRETO.test(k) ? "***" : v}`);
    return { forma: "formData", campos: Object.keys(requestBody.formData), texto: partes.join("&") };
  }
  if (requestBody.raw) {
    const dec = new TextDecoder("iso-8859-1"); let txt = "";
    for (const p of requestBody.raw) if (p.bytes) txt += dec.decode(p.bytes);
    return { forma: "raw", texto: tachar(txt) };
  }
  return null;
}

// ---- estado persistente ----
const E = chrome.storage.local;
async function estado() { return (await E.get("cap"))?.cap || null; }
let cola = Promise.resolve();
function agregar(entrada) {
  cola = cola.then(async () => {
    const cap = await estado(); if (!cap) return;
    const n = (cap.n || 0) + 1; entrada.n = n;
    await E.set({ cap: { ...cap, n }, ["e" + String(n).padStart(6, "0")]: entrada });
  }).catch(() => {});
  return cola;
}
const pendientes = new Map();   // requestId → entrada parcial (vive solo mientras el SW está despierto)

// ---- red ----
const FILTRO = { urls: ["*://*.sii.cl/*"] };
// Se anota SIN esperar (await) para que onCompleted no llegue antes de que exista la entrada;
// el filtro de "¿estamos grabando esta pestaña?" se aplica al guardar.
chrome.webRequest.onBeforeRequest.addListener(d => {
  if (d.tabId < 0 || RUIDO.test(d.url)) return;
  pendientes.set(d.requestId, { tipo: "red", tabId: d.tabId, metodo: d.method, url: d.url, marco: d.frameId === 0 ? "top" : "iframe",
                                recurso: d.type, t: d.timeStamp, cuerpo: cuerpoDe(d.requestBody) });
}, FILTRO, ["requestBody"]);
async function cerrar(d, extra) {
  const e = pendientes.get(d.requestId); if (!e) return;
  pendientes.delete(d.requestId);
  const cap = await estado(); if (!cap || e.tabId !== cap.tabId) return;
  delete e.tabId; Object.assign(e, extra); await agregar(e);
}
chrome.webRequest.onSendHeaders.addListener(d => {
  const e = pendientes.get(d.requestId); if (e) e.cabeceras = cabecerasLimpias(d.requestHeaders);
}, FILTRO, ["requestHeaders"]);
chrome.webRequest.onCompleted.addListener(d => cerrar(d, { estado: d.statusCode, cabeceras_respuesta: cabecerasLimpias(d.responseHeaders), desde_cache: d.fromCache }), FILTRO, ["responseHeaders"]);
chrome.webRequest.onBeforeRedirect.addListener(d => cerrar(d, { estado: d.statusCode, redirige_a: d.redirectUrl, cabeceras_respuesta: cabecerasLimpias(d.responseHeaders) }), FILTRO, ["responseHeaders"]);
chrome.webRequest.onErrorOccurred.addListener(d => cerrar(d, { error: d.error }), FILTRO);

// ---- lo que manda la página (HTML y AJAX) ----
chrome.runtime.onMessage.addListener((msg, remitente, responder) => {
  (async () => {
    if (msg.tipo === "pagina" || msg.tipo === "xhr") {
      const cap = await estado(); const tabId = remitente.tab && remitente.tab.id;
      if (!cap || tabId !== cap.tabId) return;
      if (msg.tipo === "pagina") {
        if (msg.momento === "domcontentloaded" && msg.marco === "iframe") return;   // con el load basta
        await agregar({ tipo: "pagina", momento: msg.momento, marco: msg.marco, url: msg.url, titulo: msg.titulo, t: msg.t, html: tachar(msg.html) });
      } else {
        if (!ES_SII(msg.url) && !msg.url.startsWith("/")) return;
        await agregar({ tipo: "xhr", metodo: msg.metodo, url: msg.url, pagina: msg.pagina, t: msg.t, cuerpo: tachar(msg.cuerpo),
                        estado: msg.estado, respuesta: tachar(msg.respuesta) });
      }
      return;
    }
    if (msg.tipo === "estado") {
      const cap = await estado(); let titulo = null;
      if (cap) { try { const t = await chrome.tabs.get(cap.tabId); titulo = t.title || t.url; } catch {} }
      responder({ grabando: !!cap, n: cap ? cap.n || 0 : 0, tabId: cap ? cap.tabId : null, titulo, ultimo: (await E.get("ultimo")).ultimo || null });
    } else if (msg.tipo === "start") {
      if (await estado()) { responder({ error: "ya hay una grabación en curso" }); return; }
      await E.set({ cap: { tabId: msg.tabId, inicio: new Date().toISOString(), n: 0 } });
      // Fotografía de la página actual: la grabación suele empezar con la página ya cargada.
      try { await chrome.tabs.sendMessage(msg.tabId, { tipo: "foto_ahora" }); } catch {}
      responder({ ok: true });
    } else if (msg.tipo === "stop") {
      responder(await detener());
    }
  })();
  return true;
});

async function detener() {
  const cap = await estado(); if (!cap) return { ok: false };
  await cola;
  const todo = await E.get(null);
  const entradas = Object.keys(todo).filter(k => /^e\d{6}$/.test(k)).sort().map(k => todo[k]);
  const indice = entradas.map(e => e.tipo === "pagina" ? `${String(e.n).padStart(3)} [página ${e.momento}${e.marco === "iframe" ? " iframe" : ""}] ${e.url}`
    : e.tipo === "xhr" ? `${String(e.n).padStart(3)} [ajax] ${e.metodo} ${e.estado} ${e.url}`
    : `${String(e.n).padStart(3)} ${(e.metodo || "").padEnd(4)} ${e.estado ?? e.error ?? "---"} ${e.url}`);
  const salida = { herramienta: "captura-sii/2.0", inicio: cap.inicio, fin: new Date().toISOString(), pestaña: cap.tabId,
                   nota: "Solo sii.cl. Claves tachadas (***), cookies omitidas. 'red' = petición vista por la extensión; 'pagina' = HTML resultante; 'xhr' = llamada AJAX con su respuesta.",
                   indice, entradas };
  const json = JSON.stringify(salida, null, 1);
  const nombre = `sii_captura_${cap.inicio.replace(/[:.]/g, "-")}.json`;
  const url = "data:application/json;base64," + btoa(unescape(encodeURIComponent(json)));
  await chrome.downloads.download({ url, filename: nombre, saveAs: false });
  await E.remove(["cap", ...Object.keys(todo).filter(k => /^e\d{6}$/.test(k))]);
  await E.set({ ultimo: `${nombre} (${entradas.length} entradas)` });
  return { ok: true, nombre };
}
