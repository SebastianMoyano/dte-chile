// DTE Chile — interfaz de la app de escritorio. Sin framework: una función por vista.
// Todo lo que toca al motor pasa por `api()`, que llama a Go (App.API) y Go firma la petición.
// La clave del motor nunca llega aquí.
//
// La empresa activa (selector de arriba) decide "en qué mundo estás":
//   demo (EMPRESA DEMO SPA)      → SIMULACIÓN: nada sale del computador (core/simulacion.py)
//   negocio en certificación     → PRUEBAS DEL SII: responde el SII, sin efecto tributario
//   negocio en producción        → REAL: cada documento cuenta

const $ = (id) => document.getElementById(id);
// Tema: automático (el del sistema), claro u oscuro. Se recuerda en este equipo.
const TEMAS = { "": "Automático", light: "Claro", dark: "Oscuro" };
function aplicarTema(t) { if (t) document.documentElement.dataset.theme = t; else delete document.documentElement.dataset.theme; try { localStorage.setItem("tema", t); } catch {} }
try { aplicarTema(localStorage.getItem("tema") || ""); } catch {}
const clp = (n) => (n == null ? "—" : "$ " + Math.round(n).toLocaleString("es-CL"));
// Fechas en castellano: la persona lee "1 de octubre de 2026", no "2026-10-01".
const MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"];
const fechaLarga = (iso) => { const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || ""); return m ? `${Number(m[3])} de ${MESES[Number(m[2]) - 1]} de ${m[1]}` : (iso || "—"); };
const fechaCorta = (iso) => { const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || ""); return m ? `${m[3]}/${m[2]}/${m[1]}` : (iso || ""); };
const mesLargo = (ym) => { const m = /^(\d{4})-(\d{2})/.exec(ym || ""); return m ? `${MESES[Number(m[2]) - 1]} de ${m[1]}` : (ym || ""); };
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const TIPOS = { 33: "Factura", 34: "Factura exenta", 39: "Boleta", 41: "Boleta exenta", 52: "Guía de despacho", 56: "Nota de débito", 61: "Nota de crédito" };
const IVA = 0.19;
// Íconos propios (trazo, 24×24): los mismos en Mac, Windows y Linux. En index.html el dock lleva los suyos inline.
const ICONOS = {
  inicio: '<path d="M3 11l9-8 9 8v9a2 2 0 0 1-2 2h-4v-6H9v6H5a2 2 0 0 1-2-2z"/>',
  cobrar: '<path d="M6 2h12v20l-3-2-3 2-3-2-3 2z"/><path d="M9 8h6M9 12h6M9 16h4"/>',
  documentos: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/>',
  aprender: '<path d="M2 9l10-5 10 5-10 5z"/><path d="M6 11.5v4.5c0 1.5 3 3 6 3s6-1.5 6-3v-4.5"/><path d="M22 9v5"/>',
  ajustes: '<path d="M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3"/><path d="M1 14h6M9 8h6M17 16h6"/>',
  mes: '<rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/>',
  ia: '<rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="6" height="6"/><path d="M9 1v3M15 1v3M9 20v3M15 20v3M1 9h3M1 15h3M20 9h3M20 15h3"/>',
  valores: '<path d="M23 6l-9.5 9.5-5-5L1 18"/><path d="M17 6h6v6"/>',
  panel: '<rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>',
  sincronizar: '<path d="M23 4v6h-6"/><path d="M1 20v-6h6"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/>',
  vacio: '<path d="M22 12h-6l-2 3h-4l-2-3H2"/><path d="M5.45 5.11L2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/>',
};
const icono = (k) => `<div class="ico"><svg viewBox="0 0 24 24" aria-hidden="true">${ICONOS[k]}</svg></div>`;
const RUT_DEMO = "77777777-7";
const DEMO = { rut: RUT_DEMO, razon_social: "EMPRESA DEMO SPA", demo: true, ambiente: "simulacion", estado_etiqueta: "Empresa de práctica", usa_sw_propio: 1 };

let estado = { listo: false };
let negocios = [];          // reales, del motor
let empresaRut = (() => { try { return localStorage.getItem("empresa") || RUT_DEMO; } catch { return RUT_DEMO; } })();

// ---------- motor ----------
async function api(metodo, ruta, cuerpo) {
  const r = await window.go.main.App.API(metodo, ruta, cuerpo ? JSON.stringify(cuerpo) : "");
  let datos = null;
  try { datos = JSON.parse(r.cuerpo); } catch { datos = r.cuerpo; }
  if (r.status >= 400) {
    const msg = (datos && (datos.error?.mensaje || datos.detail || datos.mensaje)) || `Error ${r.status}`;
    throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return datos;
}
// Diálogo propio (en vez del confirm() del sistema): título, cuerpo en HTML y botones con su
// valor. Resuelve con el valor del botón apretado; Esc o "Volver" resuelven false.
function dialogo({ titulo, cuerpo, botones, ancho = 520 }) {
  if (window.Tour) window.Tour.cerrar();   // un diálogo es un momento de atención: ninguna pista encima
  return new Promise((resolve) => {
    const m = document.createElement("div");
    m.className = "modal";
    m.innerHTML = `<div class="card" style="max-width:${ancho}px;width:92%"><h2 style="margin-top:0">${titulo}</h2>${cuerpo}
      <div class="row" style="justify-content:flex-end">${botones.map((b, i) => `<button class="${b.clase || ""}" data-i="${i}" style="flex:none">${b.texto}</button>`).join("")}</div></div>`;
    const fin = (v) => { document.removeEventListener("keydown", tecla); m.remove(); resolve(v); };
    const tecla = (ev) => { if (ev.key === "Escape") { ev.preventDefault(); fin(false); } };
    document.addEventListener("keydown", tecla);
    document.body.appendChild(m);
    m.querySelectorAll("button[data-i]").forEach((b) => (b.onclick = () => fin(botones[Number(b.dataset.i)].valor)));
    setTimeout(() => m.querySelector("button[data-i]:last-child")?.focus(), 30);
  });
}
// La revisión antes de emitir: quién, a quién, qué, los tres números y en qué mundo. Es la
// pantalla que promete el botón "Revisar y emitir".
function revisar({ tipo, de, para, que, neto, iva, total, w, extra = "" }) {
  const mundoTxt = w === "real" ? `<div class="banner rojo"><b>Esto es real.</b> Un folio gastado no vuelve: revisa el RUT, el monto y el tipo.</div>`
    : w === "pruebas" ? `<div class="banner">Ambiente de <b>pruebas del SII</b>: el documento no tiene efecto tributario.</div>`
    : `<div class="banner verde"><b>Práctica.</b> Se arma, se firma y se timbra como uno real, pero no sale de tu computador.</div>`;
  const filas = [["Documento", TIPOS[tipo] || tipo], ["De", de], ["Para", para], ["Qué", que]]
    .map(([k, v]) => `<div class="rev"><span>${k}</span><b>${esc(v)}</b></div>`).join("");
  const totales = `<div class="totales"><div><span>Neto</span><b>${clp(neto)}</b></div><div><span>IVA</span><b>${clp(iva)}</b></div><div><span>Total</span><b>${clp(total)}</b></div></div>`;
  return dialogo({ titulo: "Revisa antes de emitir", cuerpo: filas + totales + extra + mundoTxt,
    botones: [{ texto: "Volver", clase: "sec", valor: false }, { texto: `Emitir ${(TIPOS[tipo] || "").toLowerCase()} por ${clp(total)}`, clase: w === "real" ? "peligro" : "", valor: true }] });
}
function aviso(txt, ms = 3500) { const a = $("aviso"); a.textContent = txt; a.style.display = "block"; clearTimeout(a._t); a._t = setTimeout(() => (a.style.display = "none"), ms); }

// ---------- empresa activa y mundo ----------
const todas = () => [DEMO, ...negocios];
const empresa = () => todas().find((n) => n.rut === empresaRut) || DEMO;
const mundo = () => { const e = empresa(); return e.demo ? "sim" : e.ambiente === "produccion" ? "real" : "pruebas"; };

function pintarMundo() {
  const m = $("mundo");
  if (!estado.listo) { m.className = "mundo " + (estado.error ? "m-error" : "m-cargando"); m.textContent = estado.error ? "motor con error" : "arrancando motor…"; return; }
  const w = mundo();
  m.className = "mundo m-" + w;
  m.textContent = w === "sim" ? "Práctica · nada sale de aquí" : w === "real" ? "Real · cada documento cuenta" : "Pruebas del SII · sin efecto";
}
function pintarSelector() {
  const s = $("empresa");
  // Con una sola empresa (la de práctica) no hay nada que elegir: el selector aparece recién con la primera real.
  const w = s.closest(".sel-wrap"); if (w) w.style.display = negocios.length ? "" : "none";
  s.innerHTML = todas().map((n) => `<option value="${esc(n.rut)}" ${n.rut === empresaRut ? "selected" : ""}>${esc(n.razon_social || n.rut)}${n.demo ? " (práctica)" : ""}</option>`).join("");
  s.onchange = () => { empresaRut = s.value; try { localStorage.setItem("empresa", empresaRut); } catch {} pintarMundo(); render(); };
}
async function cargarNegocios() {
  try { negocios = await api("GET", "/api/v1/keystore/negocios"); } catch { negocios = []; }
  if (!todas().some((n) => n.rut === empresaRut)) empresaRut = RUT_DEMO;
  pintarSelector(); pintarMundo();
  return negocios;
}

// ---------- router ----------
const vistas = {};
function ir(v) { location.hash = "#" + v; }
function param(k) { const q = (location.hash.split("?")[1] || ""); return new URLSearchParams(q).get(k); }
async function render() {
  const v = (location.hash || "#inicio").slice(1).split("?")[0];
  const grupo = { ver: "documentos", mes: "documentos", corregir: "documentos", ia: "ajustes", valores: "ajustes" }[v] || v;
  document.querySelectorAll("[data-v]").forEach((a) => a.classList.toggle("on", a.dataset.v === grupo));
  const f = vistas[v] || vistas.inicio;
  window.scrollTo(0, 0);
  $("vista").innerHTML = '<p class="mut">Cargando…</p>';
  try { await f($("vista")); } catch (e) { $("vista").innerHTML = `<div class="banner rojo">${esc(e.message)}</div>`; }
  document.dispatchEvent(new CustomEvent("vista", { detail: v }));   // el tour escucha (tour.js)
}
window.addEventListener("hashchange", render);

// ---------- inicio ----------
vistas.inicio = async (el) => {
  if (!estado.listo) {
    el.innerHTML = `<h1>Hola</h1><p class="sub">${estado.error ? "El motor no pudo arrancar." : "Arrancando el motor de facturación…"}</p>` +
      (estado.error ? `<div class="banner rojo">${esc(estado.error)}${estado.log ? `<br><span class="mut">Registro: <code>${esc(estado.log)}</code></span>` : ""}</div>` : "");
    return;
  }
  await cargarNegocios();
  const e = empresa();
  let cab;
  if (e.demo) {
    const st = await api("GET", "/api/v1/simulacion/estado");
    cab = `<div class="banner verde"><b>Estás practicando con EMPRESA DEMO SPA.</b> Lo que emitas aquí es idéntico a un documento real, pero nunca sale de tu computador.
      Llevas <b>${st.documentos}</b> documento(s); la próxima boleta es la <b>N° ${st.folios["39"]?.siguiente ?? 1}</b>.
      <br><span class="lnk" onclick="reiniciarDemo()">Empezar de nuevo</span> <span class="mut">(solo existe en la práctica: en el mundo real nada se borra)</span></div>`;
  } else {
    cab = `<div class="banner ${mundo() === "real" ? "rojo" : ""}"><b>${esc(e.razon_social || e.rut)}</b> · ${esc(e.rut)} · <span class="pill ${e.usa_sw_propio ? "p-ok" : "p-mut"}">${esc(e.estado_etiqueta || "sin diagnóstico")}</span>
      ${mundo() === "real" ? "<br>Esta empresa está en <b>producción</b>: lo que emitas cuenta ante el SII." : "<br>Esta empresa está en el <b>ambiente de pruebas</b> del SII: el SII responde, pero sin efecto tributario."}</div>`;
  }
  const sinc = (!e.demo && !e.usa_sw_propio) ? `<div class="card accion" data-tour="sincronizar" onclick="sincronizarGratuito()">${icono("sincronizar")}<h3>Traer lo emitido en el SII</h3><p>Esta empresa emite en el sistema del SII. La app entra como tú, lista lo emitido y guarda PDF y XML aquí. Solo lectura.</p></div>` : "";
  const hora = new Date().getHours(), saludo = hora < 12 ? "Buenos días" : hora < 20 ? "Buenas tardes" : "Buenas noches";
  el.innerHTML = `
    <h1>${saludo}</h1>
    <p class="sub">${e.demo ? "Estás en la empresa de práctica: prueba todo sin miedo." : `Trabajando por <b>${esc(e.razon_social || e.rut)}</b>.`} ¿Qué quieres hacer?</p>
    <p class="mut" id="valores_hoy"></p>
    ${cab}
    <div class="grid">
      ${sinc}
      <div class="card accion" data-tour="cobrar" onclick="ir('cobrar')">${icono("cobrar")}<h3>Cobrarle a alguien</h3><p>Una boleta o una factura. Ves neto, IVA y total antes de emitir.</p></div>
      <div class="card accion" onclick="ir('documentos')">${icono("documentos")}<h3>Mis documentos</h3><p>Todo lo emitido. Para corregir, se anula con una nota de crédito: nada se borra.</p></div>
      <div class="card accion" onclick="ir('documentos?tab=mes')">${icono("mes")}<h3>Mi mes</h3><p>Cuánto vendiste, cuánto IVA cobraste y qué va a pedir el F29.</p></div>
    </div>
    ${negocios.length ? "" : `<div class="card"><b>Todavía no hay ninguna empresa real.</b><p class="mut">Practica con la demo todo lo que quieras. Cuando tengas tu certificado digital, agrégalo en el panel del motor y tu empresa aparecerá arriba.</p>
      <button class="sec" data-tour="panel" onclick="abrirPanel('certificados')">Abrir el panel</button></div>`}`;
  pintarValores();
};
// Ajustes: lo que no es trabajo diario (conectar la IA, los valores del día, el panel del motor,
// los detalles técnicos). Cuelga del engranaje de la cabecera, no de la barra.
vistas.ajustes = async (el) => {
  el.innerHTML = `
    <h1>Ajustes</h1>
    <p class="sub">Lo que no es trabajo de todos los días.</p>
    <div class="grid">
      <div class="card accion" onclick="ir('ia')">${icono("ia")}<h3>Tu IA</h3><p>Conecta el asistente de IA de este computador para que trabaje con tu facturación.</p></div>
      <div class="card accion" onclick="ir('valores')">${icono("valores")}<h3>Valores</h3><p>UF, UTM y dólar de cualquier día, y el histórico mensual.</p></div>
      <div class="card accion" onclick="abrirPanel('certificados')">${icono("panel")}<h3>Panel del motor</h3><p>Certificados, folios, usuarios y claves de API, en el navegador.</p></div>
    </div>
    <div class="card"><h3>Apariencia</h3><p class="mut">Si el fondo oscuro te cansa la vista, elige Claro. Automático sigue al sistema.</p>
      <div class="segmento" id="tema_sel">${Object.entries(TEMAS).map(([k, v]) => `<button class="${(localStorage.getItem("tema") || "") === k ? "on" : ""}" onclick="aplicarTema('${k}'); render()">${v}</button>`).join("")}</div></div>
    <details class="tecnico"><summary>Detalles técnicos</summary>
      <p class="mut">Motor v${esc(estado.version)} en <code>${esc(estado.url)}</code>${estado.externo ? " (externo)" : estado.empaquetado ? " (dentro de la app)" : " (datos del repo)"}.
      ${estado.empaquetado ? `Tus datos están en <code>${esc(estado.raiz)}</code>.` : ""} La clave del panel web se muestra al pulsar "Panel del motor".</p></details>`;
};
// El panel web pide usuario y clave; se muestran recién cuando hacen falta, no en Inicio.
window.abrirPanel = async (pagina) => {
  if (estado.clave_admin) {
    const ok = await dialogo({ titulo: "Abrir el panel del motor", ancho: 460,
      cuerpo: `<p class="mut">Se abre en tu navegador. Para entrar usa:</p>
        <div class="rev"><span>Usuario</span><b><code>admin</code></b></div><div class="rev"><span>Clave</span><b><code>${esc(estado.clave_admin)}</code></b></div>
        <p class="mut">La clave se puede copiar; también está en el archivo <code>.env</code> de tus datos.</p>`,
      botones: [{ texto: "Volver", clase: "sec", valor: false }, { texto: "Copiar clave y abrir", valor: true }] });
    if (!ok) return;
    try { await navigator.clipboard.writeText(estado.clave_admin); aviso("Clave copiada."); } catch {}
  }
  window.go.main.App.AbrirPanel(pagina);
};
// UF, UTM y dólar del día (los trae el núcleo Go a la base; Python los lee).
async function pintarValores() {
  try {
    const v = await api("GET", "/api/v1/valores");
    const f = (x, dec) => (x ? x.valor.toLocaleString("es-CL", { minimumFractionDigits: dec, maximumFractionDigits: dec }) + (x.rezago_dias > 2 ? ` <span class="mut">(del ${fechaLarga(x.fecha_valor)})</span>` : "") : "—");
    const el = $("valores_hoy"); if (el) el.innerHTML = `Hoy: UF ${f(v.uf, 2)} · UTM ${f(v.utm, 0)} · dólar ${f(v.dolar, 2)} · <span class="lnk" onclick="ir('valores')">otros días</span>`;
  } catch {}
}
window.reiniciarDemo = async () => {
  const ok = await dialogo({ titulo: "Empezar de nuevo", cuerpo: `<p class="mut">Se borran todos los documentos de práctica y la próxima boleta vuelve a ser la N° 1. Solo pasa en la práctica.</p>`,
    botones: [{ texto: "Volver", clase: "sec", valor: false }, { texto: "Borrar la práctica", clase: "peligro", valor: true }] });
  if (!ok) return;
  const r = await api("POST", "/api/v1/simulacion/reiniciar");
  aviso(`Listo: ${r.documentos_borrados} documento(s) de práctica borrados.`); render();
};

// ---------- claves del SII (canal gratuito) ----------
// Viven en memoria del proceso mientras la app está abierta. Solo se recuerdan (cifradas en
// el keystore del motor) si la persona marca la casilla. Nunca van a logs ni a URLs.
const clavesSesion = {};
async function pedirClaves(rut, necesitaCert) {
  const est = await api("GET", `/api/v1/keystore/claves-sii/${encodeURIComponent(rut)}`).catch(() => ({}));
  const ya = clavesSesion[rut] || {};
  const tieneTrib = ya.tributaria || est.tiene_tributaria, tieneCert = ya.certificado || est.tiene_certificado;
  if (tieneTrib && (!necesitaCert || tieneCert) && (ya.rut_usuario || est.rut_usuario)) return { ...ya, rut_usuario: ya.rut_usuario || est.rut_usuario, recordar: false };
  return new Promise((resolve) => {
    const m = document.createElement("div");
    m.className = "modal";
    m.innerHTML = `<div class="card" style="max-width:460px;width:92%">
      <h2 style="margin-top:0">Claves del SII</h2>
      <p class="mut">Para operar el sistema gratuito del SII por <b>${esc(rut)}</b>, la app entra al SII <b>como tú</b>. Las claves se usan solo para eso y se borran al cerrar la app, salvo que marques recordarlas.</p>
      <label>Tu RUT (persona autorizada en el SII)</label><input id="k_rut" value="${esc(ya.rut_usuario || est.rut_usuario || "")}" placeholder="12345678-5">
      <label>Clave tributaria ${tieneTrib ? '<span class="mut">(ya recordada; deja vacío para usarla)</span>' : ""}</label><input id="k_trib" type="password" autocomplete="off">
      ${necesitaCert ? `<label>Clave del certificado digital (para firmar) ${tieneCert ? '<span class="mut">(ya recordada; deja vacío para usarla)</span>' : ""}</label><input id="k_cert" type="password" autocomplete="off">` : ""}
      <div class="chk"><input type="checkbox" id="k_rec"><label for="k_rec" style="margin:0;font-weight:500">Recordar en este equipo (cifradas con la clave maestra del motor)</label></div>
      <div class="row"><button class="sec" id="k_no">Cancelar</button><button id="k_ok">Continuar</button></div></div>`;
    document.body.appendChild(m);
    m.querySelector("#k_no").onclick = () => { m.remove(); resolve(null); };
    m.querySelector("#k_ok").onclick = () => {
      const r = { rut_usuario: m.querySelector("#k_rut").value.trim(), tributaria: m.querySelector("#k_trib").value,
                  certificado: necesitaCert ? m.querySelector("#k_cert").value : "", recordar: m.querySelector("#k_rec").checked };
      if (!r.rut_usuario) return aviso("Falta tu RUT.");
      if (!r.tributaria && !tieneTrib) return aviso("Falta la clave tributaria.");
      clavesSesion[rut] = { rut_usuario: r.rut_usuario, tributaria: r.tributaria || ya.tributaria || "", certificado: r.certificado || ya.certificado || "" };
      m.remove(); resolve(r);
    };
  });
}
window.sincronizarGratuito = async () => {
  const e = empresa();
  const k = await pedirClaves(e.rut, true);
  if (!k) return;
  aviso("Entrando al SII y listando lo emitido… puede tardar un minuto.", 8000);
  try {
    // El SII engine corre en el propio cascarón (nucleo/siiengine, Go); el motor Python queda de respaldo.
    const enGo = window.go?.main?.App?.SIIEngineSincronizar;
    const r = enGo
      ? JSON.parse(await enGo(e.rut, k.rut_usuario, k.tributaria || "", k.certificado || "", !!k.recordar))
      : await api("POST", "/api/v1/mipyme/sincronizar", { rut_empresa: e.rut, rut_usuario: k.rut_usuario, clave_tributaria: k.tributaria,
          clave_certificado: k.certificado, con_xml: !!k.certificado, con_pdf: true, recordar: !!k.recordar });
    aviso(`Listo: ${r.listados ?? 0} listados, ${r.importados ?? 0} nuevos, ${r.ya_existian ?? 0} ya estaban, ${r.pdf_ok ?? 0} PDF${r.xml_ok ? `, ${r.xml_ok} XML` : ""}${r.motor === "go" ? " (núcleo Go)" : ""}.`, 8000);
    ir("documentos");
  } catch (err) { aviso("No se pudo: " + err.message, 9000); }
};

// ---------- cobrar ----------
vistas.cobrar = async (el) => {
  await cargarNegocios();
  const e = empresa();
  el.innerHTML = `
    <h1>Cobrarle a alguien</h1>
    <p class="sub">Llena lo mínimo. Abajo ves cómo queda el documento antes de emitirlo.</p>
    <div class="card">
      <p class="mut">Desde <b>${esc(e.razon_social || e.rut)}</b>${negocios.length ? " (cambia la empresa arriba)" : ""}.</p>
      <label>A quién</label>
      <div class="radio">
        <label><input type="radio" name="c_quien" value="persona" checked> Una persona (boleta)</label>
        <label><input type="radio" name="c_quien" value="empresa"> Una empresa (factura)</label>
      </div>
      <div id="c_datos_emp" style="display:none">
        <div class="row"><div><label>RUT del cliente</label><input id="c_rut" placeholder="${e.demo ? "76111111-6" : "12345678-5"}" value="${e.demo ? "76111111-6" : ""}"></div>
        <div><label>Nombre o razón social</label><input id="c_nombre" placeholder="CLIENTE DEMO SPA" value="${e.demo ? "CLIENTE DEMO SPA" : ""}"></div></div>
        <div id="c_datos_sii" style="display:${!e.demo && !e.usa_sw_propio ? "block" : "none"}">
          <p class="mut">El sistema del SII pide también el giro y la dirección del cliente (como están en el SII; el giro se corta a 40 letras).</p>
          <div class="row"><div><label>Giro del cliente</label><input id="c_giro" placeholder="Comercio"></div><div><label>Dirección</label><input id="c_dir" placeholder="Calle 123"></div></div>
          <div class="row"><div><label>Comuna</label><input id="c_comuna" placeholder="SANTIAGO"></div><div><label>Ciudad</label><input id="c_ciudad" placeholder="Santiago"></div></div>
        </div>
      </div>
      <label>Qué le vendes</label><input id="c_que" placeholder="${e.demo ? "Ej.: Café" : "Ej.: Servicio"}">
      <div class="row"><div><label>Monto</label><input id="c_monto" type="number" inputmode="numeric" min="0" step="1" placeholder="${e.demo ? "Ej.: 1190" : ""}"></div>
        <div><label>Ese monto es…</label><select id="c_modo"><option value="total">con IVA incluido (lo que paga)</option><option value="neto">neto (sin IVA)</option></select></div></div>
      <details class="mas" id="c_mas" ${!e.demo && !e.usa_sw_propio ? "open" : ""}><summary>Más opciones: sin IVA, monto en UF</summary>
        <div class="chk"><input type="checkbox" id="c_exento"><label for="c_exento" style="margin:0;font-weight:500">No lleva IVA (educación, salud, arriendo sin muebles…)</label></div>
        <label>Monto en UF (se convierte con la UF de hoy y se escribe arriba)</label><input id="c_uf" type="number" min="0" step="0.01" placeholder="80">
        <p class="mut" id="c_uf_nota"></p>
      </details>
      <div class="totales"><div><span>Neto</span><b id="t_neto">—</b></div><div><span>IVA 19%</span><b id="t_iva">—</b></div><div><span>Total</span><b id="t_total">—</b></div></div>
      <p class="mut" style="margin-top:10px">El total es lo que paga la persona. El IVA (19%) no es tuyo: lo cobras y después se lo pasas al Estado. Lo tuyo es el neto.</p>
      <div class="accion-fija"><p class="mut" id="c_tipo" style="margin:0"></p><button id="c_btn" style="margin:0;flex:none" onclick="emitir()">Revisar y emitir</button></div>
      <div id="c_aviso"></div>
    </div>`;
  const rec = () => {
    const monto = Number($("c_monto").value || 0), modo = $("c_modo").value, ex = $("c_exento").checked;
    let neto = modo === "neto" ? monto : Math.round(monto / (1 + IVA));
    if (ex) neto = monto;
    const iva = ex ? 0 : Math.round(neto * IVA);
    $("t_neto").textContent = clp(neto); $("t_iva").textContent = clp(iva); $("t_total").textContent = clp(neto + iva);
    const aEmpresa = document.querySelector('input[name="c_quien"]:checked').value === "empresa";
    $("c_datos_emp").style.display = aEmpresa ? "block" : "none";
    const tipo = aEmpresa ? (ex ? 34 : 33) : (ex ? 41 : 39);
    $("c_tipo").innerHTML = `Vas a emitir una <b>${TIPOS[tipo].toLowerCase()}</b>.`;
    const w = mundo();
    $("c_aviso").innerHTML = w === "real"
      ? `<div class="banner rojo"><b>Esto es real.</b> Un folio gastado no vuelve. Revisa el RUT, el monto y el tipo antes de emitir.</div>`
      : w === "pruebas" ? `<div class="banner">Ambiente de <b>pruebas del SII</b>: el documento no tiene efecto tributario.</div>`
      : `<div class="banner verde"><b>Práctica.</b> El documento se arma, se firma y se timbra igual que uno real, pero no sale de aquí.</div>`;
    return { neto, iva, tipo, aEmpresa, ex };
  };
  el.querySelectorAll("input,select").forEach((i) => i.addEventListener("input", rec));
  // Monto en UF: se convierte con la UF vigente a la fecha de emisión (hoy) y se escribe en Monto.
  let ufHoy = null;
  api("GET", "/api/v1/valores/uf").then((v) => { ufHoy = v; $("c_uf_nota").textContent = `UF de hoy: ${num(v.valor, 2)}${v.rezago_dias > 0 ? " (del " + fechaLarga(v.fecha_valor) + ")" : ""}`; }).catch(() => { $("c_uf_nota").textContent = "Todavía no hay UF guardada: abre Valores para traerla."; });
  $("c_uf").addEventListener("input", () => {
    const uf = Number($("c_uf").value || 0);
    if (!uf || !ufHoy) return;
    const pesos = Math.round(uf * ufHoy.valor);
    $("c_monto").value = pesos; $("c_modo").value = "neto";
    $("c_uf_nota").textContent = `${num(uf, 2)} UF × ${num(ufHoy.valor, 2)} (UF del ${fechaLarga(ufHoy.fecha_valor)}) = $ ${num(pesos, 0)}`;
    rec();
  });
  rec();
  window.emitir = async () => {
    const { neto, iva, tipo, aEmpresa, ex } = rec();
    if (!neto) return aviso("Falta el monto.");
    if (aEmpresa && !$("c_rut").value.trim()) return aviso("Falta el RUT del cliente.");
    const que = $("c_que").value.trim() || "Venta";
    const total = neto + iva;
    const para = aEmpresa ? `${$("c_nombre").value.trim() || "CLIENTE"} (${$("c_rut").value.trim()})` : "Consumidor final (una persona, sin nombre)";
    // La revisión va antes de emitir con el motor propio o en práctica; con el sistema del SII
    // la revisión es lo que el propio SII valida, más abajo.
    if ((e.demo || e.usa_sw_propio) && !(await revisar({ tipo, de: e.razon_social || e.rut, para, que, neto, iva, total, w: mundo() }))) return;
    $("c_btn").disabled = true;
    try {
      if (e.demo) {
        // En boletas el precio va CON IVA incluido (así las exige el SII); en facturas, neto.
        const precio = tipo === 39 ? total : neto;
        const body = { tipo_dte: tipo, items: [{ nombre: que, precio_unitario: precio, exento: ex }] };
        if (aEmpresa) body.receptor = { rut: $("c_rut").value.trim(), razon_social: $("c_nombre").value.trim() || "CLIENTE", es_contribuyente: true };
        const r = await api("POST", "/api/v1/simulacion/emitir", body);
        aviso(`Listo: ${TIPOS[r.tipo_dte].toLowerCase()} N° ${r.folio} emitida. Así quedó.`, 6000);
        ir(`ver?id=${r.dte_id}`);
        return;
      }
      if (!e.usa_sw_propio) {
        // SII engine: la app opera el sistema de facturación del SII por la empresa (nucleo/siiengine, Go).
        // Hoy cubre la factura exenta; las boletas van por eboleta (sin captura todavía).
        if (tipo !== 34) {
          $("c_aviso").innerHTML += `<div class="banner"><b>${esc(e.razon_social || e.rut)}</b> emite en el sistema del SII, no con el motor propio. Desde esta app, por ahora, solo la <b>factura exenta</b> (marca "No lleva IVA" y "Una empresa"). Las boletas siguen en eboleta.sii.cl.</div>`;
          return;
        }
        const enGo = window.go?.main?.App?.SIIEngineFactura;
        if (!enGo) { $("c_aviso").innerHTML += `<div class="banner">Esta versión del cascarón no trae el SII engine.</div>`; return; }
        const faltan = [["c_giro", "giro"], ["c_dir", "dirección"], ["c_comuna", "comuna"], ["c_ciudad", "ciudad"]].filter(([id]) => !$(id).value.trim()).map(([, n]) => n);
        if (faltan.length) return aviso("Faltan datos del cliente para el SII: " + faltan.join(", ") + ".");
        const k = await pedirClaves(e.rut, true);
        if (!k) return;
        const doc = { receptor: { rut: $("c_rut").value.trim(), razon_social: $("c_nombre").value.trim() || "CLIENTE", giro: $("c_giro").value.trim(),
                                  direccion: $("c_dir").value.trim(), comuna: $("c_comuna").value.trim(), ciudad: $("c_ciudad").value.trim() },
                      item: { nombre: que, precio: neto, descripcion: "" }, fecha: new Date().toISOString().slice(0, 10), forma_pago: "1" };
        aviso("Validando en el SII (sin gastar folio)…", 6000);
        const v = JSON.parse(await enGo(e.rut, k.rut_usuario, k.tributaria || "", k.certificado || "", !!k.recordar, JSON.stringify(doc), false));
        const nuevos = v.campos_nuevos?.length ? `<p class="mut">⚠️ El formulario del SII trae campos nuevos: ${esc(v.campos_nuevos.join(", "))}.</p>` : "";
        $("c_aviso").innerHTML += `<div class="banner"><b>El SII validó el documento:</b> factura exenta de <b>${clp(v.monto_total)}</b> a <b>${esc(v.receptor.razon_social)}</b> (${esc(v.receptor.rut)}), ${esc(v.receptor.direccion)}, ${esc(v.receptor.comuna)}; fecha ${esc(v.fecha)}, contado. Emisor según el SII: ${esc(v.emisor.razon_social)}.${nuevos}
          ${v.cadena_verificada
            ? `<button id="c_sii_ok">Emitir de verdad en el SII (gasta un folio)</button>`
            : `<p class="mut"><b>Todavía no se emite desde aquí:</b> la cadena de emisión desde el núcleo Go espera su primera corrida real verificada. Hasta entonces se emite con el comando <code>nucleo-siiengine factura</code> (docs/PLAN-PORT.md, fase 6).</p>`}</div>`;
        const b = $("c_sii_ok");
        if (b) b.onclick = async () => {
          if (!(await revisar({ tipo: 34, de: v.emisor.razon_social, para: `${v.receptor.razon_social} (${v.receptor.rut})`, que, neto: v.monto_total, iva: 0, total: v.monto_total, w: "real",
            extra: `<p class="mut">Validado por el SII el ${fechaLarga(v.fecha)}, contado.</p>` }))) return;
          b.disabled = true;
          try {
            const r = JSON.parse(await enGo(e.rut, k.rut_usuario, k.tributaria || "", k.certificado || "", false, JSON.stringify(doc), true));
            aviso(`Emitida en el SII: factura exenta folio ${r.folio} (${clp(r.monto_total)}).`, 8000);
            ir(`ver?id=${r.dte_id}`);
          } catch (err) { $("c_aviso").innerHTML += `<div class="banner rojo">${esc(err.message)}</div>`; b.disabled = false; }
        };
        return;
      }
      // Empresa real con motor propio: firma y persiste el NÚCLEO EN GO (fase 4 del port);
      // Python dibuja el PDF. Misma base, mismas rutas, mismos bytes que el motor Python.
      const doc = { tipo_dte: tipo, folio: 0, fecha_emision: new Date().toISOString().slice(0, 10), emisor: await emisorDe(e.rut),
        receptor: aEmpresa ? { rut: $("c_rut").value.trim(), razon_social: $("c_nombre").value.trim() || "CLIENTE" }
                           : { rut: "66666666-6", razon_social: "CONSUMIDOR FINAL" },
        items: [{ numero_linea: 1, nombre: que, cantidad: 1, precio_unitario: tipo === 39 ? total : neto, exento: ex }], forma_pago: 1 };
      const r = JSON.parse(await window.go.main.App.EmitirNucleo(e.id, JSON.stringify(doc)));
      aviso(`Listo: ${TIPOS[r.tipo_dte]} folio ${r.folio}, ${clp(r.monto_total)} (núcleo Go).`, 6000);
      ir(`ver?id=${r.dte_id}`);
    } catch (err) { $("c_aviso").innerHTML += `<div class="banner rojo">${esc(err.message)}</div>`; }
    finally { $("c_btn").disabled = false; }
  };
};

// Datos del emisor real: el motor guarda la empresa configurada en .env (EMPRESA_*). Hasta que
// cada negocio tenga sus datos completos en BD, se usa esa y se exige que el RUT coincida.
async function emisorDe(rut) {
  const neg = negocios.find((n) => n.rut === rut);
  const e = await api("GET", "/api/v1/dte/emisor");
  if (!e.configurada) throw new Error("El motor no tiene configurada la empresa (EMPRESA_RUT, EMPRESA_RAZON_SOCIAL, giro, dirección en .env).");
  const faltan = ["giro", "codigo_actividad", "direccion", "comuna", "ciudad"].filter((k) => !e[k]);
  if (faltan.length) throw new Error(`Faltan datos del emisor en el .env del motor: ${faltan.map((k) => "EMPRESA_" + k.toUpperCase()).join(", ")}. Sin eso el SII rechaza el documento.`);
  if (e.rut !== rut) throw new Error(`El motor está configurado para ${e.rut}, no para ${rut}. Por ahora solo puede emitir con el motor propio la empresa del .env.`);
  return { rut, razon_social: e.razon_social || neg?.razon_social || "", giro: e.giro, codigo_actividad: e.codigo_actividad,
           direccion: e.direccion, comuna: e.comuna, ciudad: e.ciudad, email: e.email, telefono: e.telefono };
}

// ---------- ver (visor de PDF embebido) ----------
vistas.ver = async (el) => {
  let id = param("id");
  if (!id) { try { id = localStorage.getItem("ultimo_dte"); } catch {} }   // sin id: el último documento visto
  const docs = (await api("GET", "/api/v1/dte/documentos?limite=200")).documentos;
  const d = docs.find((x) => String(x.id) === String(id));
  if (!d) {
    el.innerHTML = `<h1>Documento</h1><p class="sub">Aquí se ve un documento emitido: sus partes, el PDF y las acciones.</p>
      <div class="card"><div class="vacio">${icono("vacio")}Todavía no hay ninguno que mostrar.<br><span class="lnk" onclick="ir('cobrar')">Emitir el primero</span></div></div>`;
    return;
  }
  try { localStorage.setItem("ultimo_dte", String(d.id)); } catch {}
  const b64 = d.tiene_pdf ? await window.go.main.App.Bytes(`/api/v1/dte/documentos/${d.id}/pdf`) : null;
  const sim = d.ambiente === "simulacion";
  el.innerHTML = `
    <h1>${esc(TIPOS[d.tipo_dte] || d.tipo_dte)} N° ${d.folio}</h1>
    <p class="sub">${esc(d.razon_social_receptor || d.rut_receptor)} · ${esc(fechaLarga(d.fecha_emision))} · ${clp(d.monto_total)}
      ${sim ? '<span class="pill p-ok">práctica</span>' : ""} ${d.estado === "anulado_simulado" ? '<span class="pill p-no">anulada</span>' : ""}</p>
    <div class="banner ${sim ? "verde" : ""}">Mira las partes: quién vende y su RUT, el <b>folio</b>, la fecha, el detalle, <b>neto, IVA y total</b>, y abajo el <b>timbre</b> (el código de barras cuadrado). ${sim ? "Es idéntico a uno real; solo que este no salió de tu computador." : ""}</div>
    ${b64 ? `<iframe style="width:100%;height:70vh;border:1px solid var(--bd);border-radius:12px;background:#fff" src="data:application/pdf;base64,${b64}"></iframe>` : '<p class="mut">Este documento no tiene PDF.</p>'}
    <div class="row" style="margin-top:12px">
      ${b64 ? `<button class="sec" onclick="bajar(${d.id},'pdf',${d.tipo_dte},${d.folio})">Guardar PDF</button>` : ""}
      ${d.tiene_xml ? `<button class="sec" onclick="bajar(${d.id},'xml',${d.tipo_dte},${d.folio})">Guardar XML</button>` : ""}
      ${sim && ![56, 61].includes(d.tipo_dte) && d.estado !== "anulado_simulado" ? `<button class="peligro" onclick="anularDemo(${d.id})">Anular con nota de crédito</button>` : ""}
      <button class="sec" onclick="ir('documentos')">Mis documentos</button>
      <button onclick="ir('cobrar')">Emitir otro</button>
    </div>`;
};
window.anularDemo = async (id) => {
  const ok = await dialogo({ titulo: "Anular con nota de crédito", cuerpo: `<p class="mut">Se emite una nota de crédito por el total de este documento. El original no se borra: queda anulado.</p>`,
    botones: [{ texto: "Volver", clase: "sec", valor: false }, { texto: "Anular este documento", clase: "peligro", valor: true }] });
  if (!ok) return;
  try { const nc = await api("POST", `/api/v1/simulacion/anular/${id}`, { motivo: "Anula documento" }); aviso(`Nota de crédito N° ${nc.folio} emitida.`); ir(`ver?id=${nc.dte_id}`); }
  catch (e) { aviso(e.message, 6000); }
};

// ---------- mi mes ----------
// Las rutas viejas siguen llegando al mismo lugar.
vistas.mes = async () => ir("documentos?tab=mes");
vistas.corregir = async () => ir("documentos");
function pintarMes(el, e) {
  const hoy = new Date(), meses = [];
  for (let i = 0; i < 24; i++) { const d = new Date(hoy.getFullYear(), hoy.getMonth() - i, 1); meses.push(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`); }
  el.innerHTML = `
    <p class="mut">Lo que esta app tiene registrado. El SII arma su propio registro con lo que le llegó; si no coinciden, falta algo de un lado.</p>
    <div class="card"><div class="row">
      <div><label>Mes</label><select id="m_per" onchange="calcMes()">${meses.map((p) => `<option value="${p}">${mesLargo(p)}</option>`).join("")}</select></div></div>
      <div id="m_res"></div></div>`;
  window.calcMes = async () => {
    const p = $("m_per").value;
    const r = await api("GET", "/api/v1/dte/documentos?" + new URLSearchParams({ limite: 200, rut_emisor: e.rut }));
    const docs = r.documentos.filter((d) => (d.fecha_emision || "").startsWith(p));
    const signo = (d) => (d.tipo_dte === 61 ? -1 : 1);
    const sum = (k) => docs.reduce((a, d) => a + signo(d) * (d[k] || 0), 0);
    const neto = sum("monto_neto") + sum("monto_exento"), iva = sum("iva"), total = sum("monto_total");
    $("m_res").innerHTML = `
      <div class="totales"><div><span>Vendido (sin IVA)</span><b>${clp(neto)}</b></div><div><span>IVA cobrado</span><b>${clp(iva)}</b></div><div><span>Total con IVA</span><b>${clp(total)}</b></div></div>
      <p class="mut">${docs.length} documento(s) en ${mesLargo(p)}. Las notas de crédito restan. El IVA de tus <b>compras</b> con factura (crédito) se descuenta de este débito en el F29; eso lo trae el SII, no esta lista.</p>
      <div class="banner verde">Aunque no haya nada, el F29 se presenta igual: <b>sin movimiento</b>.</div>
      ${docs.length ? tabla(docs) : ""}`;
  };
  calcMes();
}

// Anular por el SII engine: el portal pre-construye la NC del documento (receptor e ítems tal
// cual), el SII la valida en seco, y solo se emite con la cadena verificada desde Go.
window.anularSII = async (id) => {
  const e = empresa();
  const enGo = window.go?.main?.App?.SIIEngineNotaCredito;
  if (!enGo) return aviso("Esta versión del cascarón no trae el SII engine.");
  const k = await pedirClaves(e.rut, true);
  if (!k) return;
  if (!k.certificado && !k.rut_usuario) return;
  aviso("Pidiendo al SII la nota de crédito de anulación (sin gastar folio)…", 6000);
  try {
    const v = JSON.parse(await enGo(e.rut, k.rut_usuario, k.tributaria || "", k.certificado || "", !!k.recordar, id, false));
    const lineas = (v.items || []).map((i) => `${esc(i.Nombre)} × ${i.Cantidad} = ${clp(i.Precio * i.Cantidad)}`).join("; ");
    $("cor_aviso").innerHTML = `<div class="banner"><b>El SII validó la nota de crédito:</b> anula ${esc(TIPOS[v.anula.tipo] || v.anula.tipo)} N° ${v.anula.folio} del ${esc(v.anula.fecha)} a <b>${esc(v.receptor.razon_social)}</b> por <b>${clp(v.monto_total)}</b> (${lineas}).
      ${v.cadena_verificada
        ? `<button id="cor_ok">Emitir la nota de crédito en el SII (gasta un folio)</button>`
        : `<p class="mut"><b>Todavía no se emite desde aquí:</b> la cadena de la nota de crédito desde el núcleo Go espera su primera corrida real verificada. Hasta entonces: <code>nucleo-siiengine nc-anular</code> (docs/PLAN-PORT.md, fase 6).</p>`}</div>`;
    const b = $("cor_ok");
    if (b) b.onclick = async () => {
      const ok = await dialogo({ titulo: "Emitir la nota de crédito en el SII", cuerpo: `<div class="rev"><span>Anula</span><b>${esc(TIPOS[v.anula.tipo] || v.anula.tipo)} N° ${v.anula.folio}</b></div><div class="rev"><span>Para</span><b>${esc(v.receptor.razon_social)}</b></div><div class="rev"><span>Total</span><b>${clp(v.monto_total)}</b></div>
          <div class="banner rojo"><b>Esto es real.</b> Un folio gastado no vuelve.</div>`,
        botones: [{ texto: "Volver", clase: "sec", valor: false }, { texto: `Anular en el SII por ${clp(v.monto_total)}`, clase: "peligro", valor: true }] });
      if (!ok) return;
      b.disabled = true;
      try {
        const r = JSON.parse(await enGo(e.rut, k.rut_usuario, k.tributaria || "", k.certificado || "", false, id, true));
        aviso(`Nota de crédito folio ${r.folio} emitida en el SII.`, 8000);
        ir(`ver?id=${r.dte_id}`);
      } catch (err) { $("cor_aviso").innerHTML += `<div class="banner rojo">${esc(err.message)}</div>`; b.disabled = false; }
    };
  } catch (err) { $("cor_aviso").innerHTML = `<div class="banner rojo">${esc(err.message)}</div>`; }
};

// ---------- documentos ----------
vistas.documentos = async (el) => {
  await cargarNegocios();
  const e = empresa();
  const tab = param("tab") === "mes" ? "mes" : "todos";
  el.innerHTML = `
    <h1>Documentos</h1>
    <p class="sub">Boletas, facturas y notas de <b>${esc(e.razon_social || e.rut)}</b>${e.demo ? " (práctica)" : ", tanto las del motor como las del gratuito del SII"}.</p>
    <div class="tabs"><a class="${tab === "todos" ? "on" : ""}" href="#documentos">Todos</a><a class="${tab === "mes" ? "on" : ""}" href="#documentos?tab=mes">Mi mes</a></div>
    <div id="doc_cuerpo"></div>`;
  if (tab === "mes") { pintarMes($("doc_cuerpo"), e); return; }
  const r = await api("GET", "/api/v1/dte/documentos?" + new URLSearchParams({ limite: 100, rut_emisor: e.rut }));
  $("doc_cuerpo").innerHTML = `
    <div class="card">${tabla(r.documentos)}</div>
    <div id="cor_aviso"></div>
    <p class="mut">Un documento emitido no se borra. Si salió mal, pulsa <b>anular</b> en su fila: una nota de crédito por el total lo deja en cero.${e.demo ? "" : " Los del sistema del SII se anulan con el propio SII; los del motor propio, por ahora, desde el panel del motor."}</p>`;
};

function tabla(docs) {
  if (!docs.length) return `<div class="vacio">${icono("vacio")}No hay documentos todavía.<br><span class="lnk" onclick="ir('cobrar')">Emitir el primero</span></div>`;
  const est = (e) => { e = e || ""; const c = e.includes("acept") || e.includes("emitido") || e === "simulado" ? "p-ok" : e.includes("rechaz") || e.includes("anulado") ? "p-no" : e.includes("envi") ? "p-warn" : "p-mut";
    const t = e === "simulado" ? "práctica" : e === "anulado_simulado" ? "anulada" : e.replace("_mipyme", " · gratuito SII"); return `<span class="pill ${c}">${esc(t)}</span>`; };
  return `<div class="tablewrap"><table><tr><th>Fecha</th><th>Documento</th><th>N°</th><th>Para</th><th class="num">Total</th><th>Estado</th><th></th></tr>
    ${docs.map((d) => `<tr><td>${esc(fechaCorta(d.fecha_emision))}</td><td>${esc(TIPOS[d.tipo_dte] || d.tipo_dte)}</td><td>${d.folio}</td>
      <td>${esc(d.razon_social_receptor || d.rut_receptor || "")}</td><td class="num">${clp(d.monto_total)}</td><td>${est(d.estado)}</td>
      <td>${d.tiene_pdf ? `<span class="lnk" onclick="ir('ver?id=${d.id}')">ver</span> <span class="lnk" onclick="bajar(${d.id},'pdf',${d.tipo_dte},${d.folio})">PDF</span>` : ""} ${d.tiene_xml ? `<span class="lnk" onclick="bajar(${d.id},'xml',${d.tipo_dte},${d.folio})">XML</span>` : ""}
        ${![56, 61].includes(d.tipo_dte) && d.estado !== "anulado_simulado" ? `<span class="lnk no" data-tour="anular" onclick="${d.ambiente === "simulacion" ? `anularDemo(${d.id})` : d.canal === "mipyme" ? `anularSII(${d.id})` : `aviso('Anular documentos del motor propio desde la app: próxima versión.')`}">anular</span>` : ""}</td></tr>`).join("")}
    </table></div>`;
}
window.bajar = async (id, que, tipo, folio) => {
  try { const p = await window.go.main.App.Guardar(`/api/v1/dte/documentos/${id}/${que}`, `T${tipo}_F${folio}.${que}`); if (p) aviso("Guardado en " + p, 5000); }
  catch (e) { aviso("No se pudo guardar: " + e, 6000); }
};

// ---------- valores (UF, UTM, dólar): del día, a una fecha, y el histórico mensual ----------
const num = (x, dec) => (x == null ? "—" : Number(x).toLocaleString("es-CL", { minimumFractionDigits: dec, maximumFractionDigits: dec }));
vistas.valores = async (el) => {
  const hoy = new Date().toISOString().slice(0, 10);
  el.innerHTML = `
    <h1>Valores</h1>
    <p class="sub">UF, UTM y dólar de las páginas oficiales del SII. El histórico se cargó una vez; el año en curso se refresca cada día.</p>
    <div class="card"><div class="row">
      <div><label>¿Cuánto valía el…?</label><input id="v_fecha" type="date" value="${hoy}" max="${hoy}" onchange="valoresFecha()"></div></div>
      <div class="totales" id="v_tres"></div>
      <p class="mut" id="v_nota"></p></div>
    <div class="card"><div class="row">
      <div><label>Histórico mensual</label><select id="v_anio" onchange="valoresAnio()"></select></div></div>
      <div id="v_tabla"></div></div>`;
  window.valoresFecha = async () => {
    try {
      const v = await api("GET", "/api/v1/valores?fecha=" + $("v_fecha").value);
      const c = (x, dec) => `<div><span>${x ? "" : ""}</span><b>${x ? num(x.valor, dec) : "—"}</b><span>${x && x.rezago_dias > 0 ? "del " + x.fecha_valor : ""}</span></div>`;
      $("v_tres").innerHTML = `<div><span>UF</span><b>${v.uf ? num(v.uf.valor, 2) : "—"}</b><span>${v.uf && v.uf.rezago_dias > 0 ? "del " + fechaLarga(v.uf.fecha_valor) : ""}</span></div>
        <div><span>UTM</span><b>${v.utm ? num(v.utm.valor, 0) : "—"}</b><span>${v.utm ? mesLargo(v.utm.fecha_valor) : ""}</span></div>
        <div><span>Dólar</span><b>${v.dolar ? num(v.dolar.valor, 2) : "—"}</b><span>${v.dolar && v.dolar.rezago_dias > 0 ? "del " + fechaLarga(v.dolar.fecha_valor) : ""}</span></div>`;
      $("v_nota").textContent = (v.dolar && v.dolar.rezago_dias > 3) ? "El dólar de la página oficial del SII llega con rezago: se muestra el último publicado y su fecha." : "";
    } catch (e) { $("v_tres").innerHTML = `<div><span>${esc(e.message)}</span></div>`; }
  };
  window.valoresAnio = async () => {
    const a = $("v_anio").value || hoy.slice(0, 4);
    const h = await api("GET", "/api/v1/valores/historico?anio=" + a);
    if (!$("v_anio").options.length) {
      $("v_anio").innerHTML = h.anios_disponibles.slice().reverse().map((x) => `<option value="${x}" ${x === a ? "selected" : ""}>${x}</option>`).join("");
    }
    $("v_tabla").innerHTML = `<div class="tablewrap"><table><tr><th>Mes</th><th class="num">UF día 1</th><th class="num">UF fin de mes</th><th class="num">UTM</th><th class="num">Dólar día 1</th><th class="num">Dólar fin de mes</th></tr>
      ${h.meses.map((m) => `<tr><td>${mesLargo(m.mes)}</td><td class="num">${num(m.uf, 2)}</td><td class="num">${num(m.uf_fin, 2)}</td><td class="num">${num(m.utm, 0)}</td><td class="num">${num(m.dolar, 2)}</td><td class="num">${num(m.dolar_fin, 2)}</td></tr>`).join("")}</table></div>`;
  };
  valoresFecha(); valoresAnio();
};

// ---------- aprender ----------
vistas.aprender = async (el) => {
  const T = window.Tour, et = T ? T.etapas : [], st = T ? T.estado() : { vistos: {}, etapa: 0, checks: {} };
  const hecha = (e) => e.pasos.every((_, i) => st.vistos[`${e.id}:${i}`]);
  const prog = (e) => e.pasos.filter((_, i) => st.vistos[`${e.id}:${i}`]).length;
  const LISTAS = {
    crear: ["Decidí si emito como persona natural (mi RUT) o creo una empresa (SpA, EIRL, Ltda.).",
            "Si es empresa: la constituí en Empresa en un Día (registroempresasysociedades.cl) y tengo el RUT y la escritura.",
            "Sé quién es el representante legal: es quien firma por la empresa ante el SII."],
    iniciar: ["Hice el inicio de actividades en sii.cl y elegí el giro (actividad económica).",
              "Tengo clave tributaria de la persona y, si corresponde, de la empresa.",
              "Compré un certificado digital (.p12) a nombre de una persona autorizada por la empresa.",
              "Cargué el certificado en el panel del motor: la empresa aparece en el selector de arriba.",
              "Decidí por cuál vía emito: con lo que el SII da (etapa 4) o con motor propio (etapa 5)."],
    motor: ["Entiendo qué es un CAF (los folios que el SII me entrega) y que mi certificado firma cada documento.",
            "Probé emitir en el ambiente de pruebas del SII (semáforo amarillo).",
            "Pasé la certificación del SII (set de pruebas + declaración de cumplimiento) para los tipos que voy a emitir."],
  };
  const lista = (e) => LISTAS[e.id] ? `<ul class="lista-check">${LISTAS[e.id].map((t, i) => { const id = e.id + ":" + i; return `<li><input type="checkbox" ${st.checks?.[id] ? "checked" : ""} onchange="Tour.check('${id}', this.checked)"><span>${t}</span></li>`; }).join("")}</ul>` : "";
  el.innerHTML = `
    <h1>Aprender</h1>
    <p class="sub">Para quien no sabe nada de finanzas. Cinco etapas en el orden en que pasan en la vida real; cada una se recorre dentro de la app, paso a paso.</p>
    ${et.map((e, i) => `<div class="card" data-tour="etapa-${e.n}" id="etapa-${e.n}" style="${i === st.etapa ? "border-color:var(--acc)" : ""}">
      <div style="display:flex;align-items:center;gap:12px">
        <span class="pill ${hecha(e) ? "p-ok" : i === st.etapa ? "p-warn" : "p-mut"}">${hecha(e) ? "completa" : i === st.etapa ? "en curso" : "pendiente"}</span>
        <span class="pill ${e.mundo === "real" ? "p-no" : e.mundo === "pruebas" ? "p-warn" : "p-ok"}">${e.mundo === "real" ? "real" : e.mundo === "pruebas" ? "pruebas del SII" : "práctica"}</span>
        <span class="mut" style="margin-left:auto">${prog(e)}/${e.pasos.length} pasos</span></div>
      <h3 style="margin:10px 0 4px">${e.n}. ${e.titulo}</h3>
      <p class="mut" style="margin:0 0 6px">${e.resumen}</p>
      ${lista(e)}
      <button class="${hecha(e) ? "sec" : ""}" onclick="Tour.etapa(${i})">${hecha(e) ? "Repetir el recorrido" : prog(e) ? "Seguir el recorrido" : "Empezar el recorrido"}</button>
    </div>`).join("")}
    <p class="mut">Las lecciones largas, el quiz y los videos del tramo 1 están en el repo (<code>docs/aprender/</code>).</p>`;
  const n = param("etapa");
  if (n) document.getElementById("etapa-" + n)?.scrollIntoView({ block: "start", behavior: "smooth" });
};

// ---------- tu IA (clientes MCP del computador) ----------
vistas.ia = async (el) => {
  if (estado.externo) {
    // En el navegador no hay cascarón que escriba la configuración de la IA del computador.
    el.innerHTML = `
      <h1>Tu IA</h1>
      <p class="sub">Si usas un asistente de IA en tu computador, puede trabajar con tu facturación: ver tus documentos, revisar tus folios, preparar una boleta y pedirte que la apruebes.</p>
      <div class="banner"><b>Desde el navegador no puedo conectarla por ti.</b> Conectar una IA escribe en la configuración de ese programa, y eso solo lo hace la app instalada (pestaña «Tu IA») o el binario <code>nucleo-mcp</code> en la terminal.</div>
      <div class="card"><h3>En la terminal</h3>
        <pre style="white-space:pre-wrap">nucleo-mcp clientes                     # qué asistentes hay en este computador
nucleo-mcp instalar --en claude-code    # o claude-desktop, cursor, vscode, windsurf, gemini, codex, todos</pre>
        <p class="mut">Después, cierra y vuelve a abrir ese programa y pídele, por ejemplo: <i>«muéstrame mis últimos documentos»</i>. Guía completa: <code>docs/CONECTAR.md</code>.</p>
      </div>`;
    return;
  }
  let lista;
  try { lista = await window.go.main.App.Conectores(); } catch (e) { el.innerHTML = `<div class="banner rojo">${esc(e.message || e)}</div>`; return; }
  const detectados = lista.filter((c) => c.presente);
  const fila = (c) => `<li>
      <div style="flex:1"><b>${esc(c.nombre)}</b><br><span class="mut">${c.instalado ? "Conectado: ya puede trabajar con tu facturación." : c.presente ? "Está en este computador." : "No lo encontré en este computador."}</span></div>
      ${c.instalado
        ? `<button class="sec" style="margin:0" onclick="conectarIA('${c.id}', true)">Desconectar</button>`
        : `<button class="${c.presente ? "" : "sec"}" style="margin:0" onclick="conectarIA('${c.id}', false)">Conectar</button>`}
    </li>`;
  el.innerHTML = `
    <h1>Tu IA</h1>
    <p class="sub">Si usas un asistente de IA en este computador, puede trabajar con tu facturación: ver tus documentos, revisar tus folios, preparar una boleta y pedirte que la apruebes.</p>
    <div class="banner"><b>Todo queda en este computador.</b> La IA le habla a esta app directamente, sin pasar por internet y sin claves que copiar. Tú sigues decidiendo: lo que gasta folios o cuenta ante el SII te lo muestra antes.</div>
    <div class="card"><h3>Encontré en este computador</h3>
      ${detectados.length ? "" : `<p class="mut">Ningún asistente conocido todavía. Cuando instales Claude, Cursor, VS Code, Windsurf, Gemini CLI o Codex, vuelve aquí.</p>`}
      <ul class="lista-check">${detectados.map(fila).join("")}</ul>
      ${detectados.length ? `<p class="mut">Después de conectar, cierra y vuelve a abrir ese programa y pídele, por ejemplo: <i>«muéstrame mis últimos documentos»</i>.</p>` : ""}
    </div>
    <details class="card"><summary>Otros asistentes</summary>
      <ul class="lista-check">${lista.filter((c) => !c.presente).map(fila).join("")}</ul>
      <p class="mut">Claude, ChatGPT o Gemini <b>en el navegador o en el celular</b> no se conectan así: sus conexiones salen desde la nube de cada empresa, no desde tu computador. Para eso hace falta publicar la app en internet con una dirección propia; está previsto, pero no es esto.</p>
    </details>`;
};
async function conectarIA(id, quitar) {
  try {
    const archivo = await window.go.main.App.ConectarIA(id, quitar);
    aviso(quitar ? "Desconectado." : "Conectado. Reinicia ese programa para que vea la app.", 5000);
    render();
    if (!quitar) console.log("MCP escrito en", archivo);
  } catch (e) { aviso("No pude: " + (e.message || e), 7000); }
}

// ---------- arranque ----------
(async () => {
  estado = await window.go.main.App.Estado();
  pintarSelector(); pintarMundo();
  window.runtime.EventsOn("motor", (e) => { estado = e; pintarMundo(); render(); });
  render();
})();
