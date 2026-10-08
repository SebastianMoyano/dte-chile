// Captura web v3 — SIN depurador: nada que Chrome pueda soltar. Observa la red con webRequest,
// recibe de la página su HTML, su texto visible y las respuestas AJAX, y persiste cada entrada
// en storage al instante (el service worker puede dormirse; la grabación no). Solo se detiene
// con el botón.
//
// Dos modos: "sii" (solo sii.cl, permiso fijo) y "todo" (cualquier sitio; pide el permiso
// <all_urls> al activarlo y registra los scripts de contenido para todas las páginas). El JSON
// que sale es "lo que vería un agente": cada página con su HTML y su texto, cada llamada con
// su respuesta, en orden.

const ES_SII = url => { try { return /(^|\.)sii\.cl$/i.test(new URL(url).hostname); } catch { return false; } };
const RUIDO = /\.(png|jpe?g|gif|svg|ico|webp|avif|woff2?|ttf|otf|css|map)(\?|$)|\/JS\/|qualtrics|google-analytics|googletagmanager|doubleclick|facebook\.net|hotjar|sentry\.io|\/TSbd\/|AutTknData/i;
const MAX_HTML = 2_000_000, MAX_TEXTO = 300_000, MAX_RESP = 1_000_000;

importScripts("tachar.js", "pii.js");
const { tachar: tacharBase, sobre: tacharValores, auditar, esNombreSensible } = self.CapturaTachar;
function tachar(texto) {
  if (texto == null) return texto;
  let s = String(texto);
  if (s.length > MAX_RESP) s = s.slice(0, MAX_RESP) + `\n…(recortado, ${texto.length} caracteres)`;
  return tacharBase(s);
}
const SECRETO = { test: n => esNombreSensible(n) };
function cabecerasLimpias(lista) {
  const out = {};
  for (const h of lista || []) out[h.name] = (/^(cookie|set-cookie|authorization)$/i.test(h.name) || esNombreSensible(h.name)) ? "(omitida)" : tachar(h.value ?? "(binario)");
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
    const dec = new TextDecoder("utf-8"); let txt = "";
    for (const p of requestBody.raw) if (p.bytes) txt += dec.decode(p.bytes);
    return { forma: "raw", texto: tachar(txt) };
  }
  return null;
}

// ---- estado persistente ----
const E = chrome.storage.local;
async function estado() { return (await E.get("cap"))?.cap || null; }
async function modo() { return (await E.get("modo")).modo || "sii"; }
// Reemplazo de datos personales: por defecto ON en "cualquier sitio" y OFF en sii.cl (ahí las
// capturas se comparan campo a campo con el módulo y los RUT deben ser los reales).
async function piiActivo(m) { const v = (await E.get("pii")).pii; return v === undefined ? m === "todo" : !!v; }
let piiCache = null;   // { semilla, sobre } de la grabación en curso
async function piiDe(cap) {
  if (!cap.pii) return null;
  if (!piiCache || piiCache.semilla !== cap.piiSemilla) piiCache = { semilla: cap.piiSemilla, ...self.CapturaPII.crear(cap.piiSemilla) };
  return piiCache;
}
let cola = Promise.resolve();
function agregar(entrada) {
  cola = cola.then(async () => {
    const cap = await estado(); if (!cap) return;
    const n = (cap.n || 0) + 1; entrada.n = n;
    const pii = await piiDe(cap);
    if (pii) entrada = pii.sobre(entrada);
    await E.set({ cap: { ...cap, n }, ["e" + String(n).padStart(6, "0")]: entrada });
  }).catch(() => {});
  return cola;
}
const pendientes = new Map();   // requestId → entrada parcial (vive solo mientras el SW está despierto)

// ---- modo "todo": permiso y scripts de contenido para cualquier sitio ----
const SCRIPTS_TODO = [
  { id: "hook-todo", matches: ["<all_urls>"], js: ["hook.js"], runAt: "document_start", world: "MAIN", allFrames: true },
  { id: "content-todo", matches: ["<all_urls>"], js: ["content.js"], runAt: "document_start", allFrames: true },
];
async function activarTodo() {
  const ok = await chrome.permissions.request({ origins: ["<all_urls>"] });
  if (!ok) return { ok: false, error: "no se concedió el permiso para todos los sitios" };
  try { await chrome.scripting.unregisterContentScripts({ ids: SCRIPTS_TODO.map(s => s.id) }); } catch {}
  await chrome.scripting.registerContentScripts(SCRIPTS_TODO);
  await E.set({ modo: "todo" });
  return { ok: true };
}
async function desactivarTodo() {
  try { await chrome.scripting.unregisterContentScripts({ ids: SCRIPTS_TODO.map(s => s.id) }); } catch {}
  try { await chrome.permissions.remove({ origins: ["<all_urls>"] }); } catch {}
  await E.set({ modo: "sii" });
  return { ok: true };
}
// Si el navegador reinició con el modo "todo" ya concedido, los scripts registrados persisten;
// si no están (p. ej. tras recargar la extensión), se vuelven a registrar.
chrome.runtime.onStartup?.addListener(async () => { if (await modo() === "todo") { try { await chrome.scripting.registerContentScripts(SCRIPTS_TODO); } catch {} } });
chrome.runtime.onInstalled.addListener(async () => { if (await modo() === "todo" && await chrome.permissions.contains({ origins: ["<all_urls>"] })) { try { await chrome.scripting.registerContentScripts(SCRIPTS_TODO); } catch {} } });

// ---- red (los eventos solo llegan para los sitios con permiso) ----
const FILTRO = { urls: ["<all_urls>"] };
chrome.webRequest.onBeforeRequest.addListener(d => {
  if (d.tabId < 0 || RUIDO.test(d.url)) return;
  pendientes.set(d.requestId, { tipo: "red", tabId: d.tabId, metodo: d.method, url: tachar(d.url), marco: d.frameId === 0 ? "top" : "iframe",
                                recurso: d.type, t: d.timeStamp, cuerpo: cuerpoDe(d.requestBody) });
}, FILTRO, ["requestBody"]);
async function cerrar(d, extra) {
  const e = pendientes.get(d.requestId); if (!e) return;
  pendientes.delete(d.requestId);
  const cap = await estado(); if (!cap || e.tabId !== cap.tabId) return;
  if (cap.modo === "sii" && !ES_SII(e.url)) return;
  delete e.tabId; Object.assign(e, extra); await agregar(e);
}
chrome.webRequest.onSendHeaders.addListener(d => {
  const e = pendientes.get(d.requestId); if (e) e.cabeceras = cabecerasLimpias(d.requestHeaders);
}, FILTRO, ["requestHeaders"]);
chrome.webRequest.onCompleted.addListener(d => cerrar(d, { estado: d.statusCode, cabeceras_respuesta: cabecerasLimpias(d.responseHeaders), desde_cache: d.fromCache }), FILTRO, ["responseHeaders"]);
chrome.webRequest.onBeforeRedirect.addListener(d => cerrar(d, { estado: d.statusCode, redirige_a: tachar(d.redirectUrl), cabeceras_respuesta: cabecerasLimpias(d.responseHeaders) }), FILTRO, ["responseHeaders"]);
chrome.webRequest.onErrorOccurred.addListener(d => cerrar(d, { error: d.error }), FILTRO);

// ---- lo que manda la página (HTML, texto y AJAX) ----
chrome.runtime.onMessage.addListener((msg, remitente, responder) => {
  (async () => {
    if (msg.tipo === "pagina" || msg.tipo === "xhr") {
      const cap = await estado(); const tabId = remitente.tab && remitente.tab.id;
      if (!cap || tabId !== cap.tabId) return;
      if (msg.tipo === "pagina") {
        if (msg.momento === "domcontentloaded" && msg.marco === "iframe") return;   // con el load basta
        if (cap.modo === "sii" && !ES_SII(msg.url)) return;
        const html = (msg.html || "").length > MAX_HTML ? msg.html.slice(0, MAX_HTML) + "\n…(recortado)" : msg.html;
        await agregar({ tipo: "pagina", momento: msg.momento, marco: msg.marco, url: tachar(msg.url), titulo: msg.titulo, t: msg.t,
                        texto: tachar((msg.texto || "").slice(0, MAX_TEXTO)), html: tachar(html) });
      } else {
        if (cap.modo === "sii" && !ES_SII(msg.url) && !msg.url.startsWith("/")) return;
        await agregar({ tipo: "xhr", metodo: msg.metodo, url: tachar(msg.url), pagina: tachar(msg.pagina), t: msg.t, cuerpo: tachar(msg.cuerpo),
                        estado: msg.estado, respuesta: tachar(msg.respuesta) });
      }
      return;
    }
    if (msg.tipo === "estado") {
      const cap = await estado(); let titulo = null;
      if (cap) { try { const t = await chrome.tabs.get(cap.tabId); titulo = t.title || t.url; } catch {} }
      const m = await modo();
      responder({ grabando: !!cap, n: cap ? cap.n || 0 : 0, tabId: cap ? cap.tabId : null, titulo, modo: m, pii: await piiActivo(m),
                  ultimo: (await E.get("ultimo")).ultimo || null });
    } else if (msg.tipo === "start") {
      if (await estado()) { responder({ error: "ya hay una grabación en curso" }); return; }
      const m = await modo();
      if (m === "sii" && !ES_SII(msg.url || "")) { responder({ error: "esta pestaña no es de sii.cl; activa 'cualquier sitio' para grabarla" }); return; }
      const pii = await piiActivo(m);
      const piiSemilla = Array.from(crypto.getRandomValues(new Uint8Array(12)), b => b.toString(16).padStart(2, "0")).join("");
      await E.set({ cap: { tabId: msg.tabId, modo: m, pii, piiSemilla, inicio: new Date().toISOString(), n: 0, host: hostDe(msg.url) } });
      try { await chrome.tabs.sendMessage(msg.tabId, { tipo: "foto_ahora" }); } catch {}
      responder({ ok: true });
    } else if (msg.tipo === "stop") {
      responder(await detener());
    } else if (msg.tipo === "pii") {
      await E.set({ pii: !!msg.valor }); responder({ ok: true });
    } else if (msg.tipo === "modo") {
      responder(msg.valor === "todo" ? await activarTodo() : await desactivarTodo());
    }
  })();
  return true;
});

function hostDe(url) { try { return new URL(url).hostname; } catch { return "pestaña"; } }

async function detener() {
  const cap = await estado(); if (!cap) return { ok: false };
  await cola;
  const todo = await E.get(null);
  const entradas = Object.keys(todo).filter(k => /^e\d{6}$/.test(k)).sort().map(k => todo[k]);
  const indice = entradas.map(e => e.tipo === "pagina" ? `${String(e.n).padStart(3)} [página ${e.momento}${e.marco === "iframe" ? " iframe" : ""}] ${e.url}`
    : e.tipo === "xhr" ? `${String(e.n).padStart(3)} [ajax] ${e.metodo} ${e.estado} ${e.url}`
    : `${String(e.n).padStart(3)} ${(e.metodo || "").padEnd(4)} ${e.estado ?? e.error ?? "---"} ${e.url}`);
  let salida = { herramienta: "captura-web/3.4", modo: cap.modo, sitio: cap.host, inicio: cap.inicio, fin: new Date().toISOString(), pestaña: cap.tabId,
                   nota: (cap.modo === "sii" ? "Solo sii.cl. " : "Cualquier sitio. ") + "Secretos tachados por nombre y por patrón (JWT, Bearer, hex largo, uuid junto a nombres sensibles); cookies y cabeceras de autorización omitidas; segunda pasada de tachado y reemplazo de datos personales SOBRE LOS VALORES del objeto (nunca sobre el JSON serializado) y auditoría en 'auditoria'. 'red' = petición vista por la extensión; 'pagina' = HTML y texto visible resultantes; 'xhr' = llamada AJAX/fetch con su respuesta.",
                   indice, entradas };
  // Segunda capa, SOBRE LOS VALORES del objeto (recorriéndolo), nunca sobre el JSON serializado.
  // Tanto el reemplazo de datos personales como el tachado de secretos corren así: una expresión
  // aplicada al texto serializado podía empezar en la "n" de un "\n" escapado y dejar "\persona…",
  // un escape inválido (bug de la 3.2/3.3). Al tachar valor por valor, los escapes nunca se tocan
  // y JSON.stringify queda como ÚLTIMO paso → el archivo descargado es siempre JSON válido. (El
  // tachado por campo ya corrió al capturar; esta pasada atrapa lo que se coló por un campo no previsto.)
  const pii = await piiDe(cap);
  let cuerpo = pii ? pii.sobre(salida) : salida;
  cuerpo = tacharValores(cuerpo);
  const auditoria = auditar(JSON.stringify(cuerpo));
  const personales = self.CapturaPII.auditar(JSON.stringify(cuerpo));
  cuerpo.datos_personales = pii ? { reemplazados: true, nota: "RUT, correos y celulares sustituidos por ficticios consistentes (mismo real → mismo ficticio en toda la captura). Los RUT ficticios son válidos pero no corresponden a nadie." }
                                : { reemplazados: false, presentes: personales, nota: "Sin reemplazo (modo sii.cl o desactivado): hay RUT/correos/celulares reales." };
  cuerpo.auditoria = { ...auditoria, nota: "Conteo de cadenas que aún parecen secretos tras el tachado. Si no es todo 0, revisa antes de compartir." };
  salida = cuerpo;
  // stringify es el último paso: el JSON es válido por construcción (no hay pasada de texto que
  // pueda romper escapes). La verificación queda como red de seguridad, no como salvavidas.
  const json = JSON.stringify(salida, null, 1);
  try { JSON.parse(json); } catch { salida.auditoria.nota += " ADVERTENCIA: JSON inválido pese a serializar como último paso (no debería ocurrir)."; }
  const nombre = `captura_${(cap.host || "web").replace(/[^a-z0-9.-]/gi, "_")}_${cap.inicio.replace(/[:.]/g, "-")}.json`;
  const url = "data:application/json;base64," + btoa(unescape(encodeURIComponent(json)));
  await chrome.downloads.download({ url, filename: nombre, saveAs: false });
  await E.remove(["cap", ...Object.keys(todo).filter(k => /^e\d{6}$/.test(k))]);
  const resto = auditoria.jwt_sin_tachar + auditoria.uuid_tras_nombre_sensible;
  const p = salida.datos_personales.presentes;
  const avisoPii = p && (p.ruts + p.correos + p.celulares) ? `; ${p.ruts} RUT/${p.correos} correos/${p.celulares} celulares reales` : "";
  await E.set({ ultimo: `${nombre} (${entradas.length} entradas${resto ? `; ⚠ ${resto} posible(s) secreto(s) sin tachar` : "; tachado verificado"}${avisoPii})` });
  return { ok: true, nombre, auditoria };
}
