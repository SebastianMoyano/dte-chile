// DTE Chile — interfaz de la app de escritorio. Sin framework: una función por vista.
// Todo lo que toca al motor pasa por `api()`, que llama a Go (App.API) y Go firma la petición.
// La clave del motor nunca llega aquí.
//
// La empresa activa (selector de arriba) decide "en qué mundo estás":
//   demo (EMPRESA DEMO SPA)      → SIMULACIÓN: nada sale del computador (core/simulacion.py)
//   negocio en certificación     → PRUEBAS DEL SII: responde el SII, sin efecto tributario
//   negocio en producción        → REAL: cada documento cuenta

const $ = (id) => document.getElementById(id);
const clp = (n) => (n == null ? "—" : "$ " + Math.round(n).toLocaleString("es-CL"));
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const TIPOS = { 33: "Factura", 34: "Factura exenta", 39: "Boleta", 41: "Boleta exenta", 52: "Guía de despacho", 56: "Nota de débito", 61: "Nota de crédito" };
const IVA = 0.19;
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
  document.querySelectorAll("nav a").forEach((a) => a.classList.toggle("on", a.dataset.v === v));
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
    cab = `<div class="banner verde"><b>Estás practicando con EMPRESA DEMO SPA.</b> Todo lo que emitas aquí se forma, se firma y se timbra como un documento real, pero nunca sale de tu computador.
      Llevas <b>${st.documentos}</b> documento(s); la próxima boleta es la <b>N° ${st.folios["39"]?.siguiente ?? 1}</b> y la próxima factura la <b>N° ${st.folios["33"]?.siguiente ?? 1}</b>.
      <br><span class="lnk" onclick="reiniciarDemo()">Empezar de nuevo</span> <span class="mut">(solo existe en la práctica: en el mundo real nada se borra)</span></div>`;
  } else {
    cab = `<div class="banner ${mundo() === "real" ? "rojo" : ""}"><b>${esc(e.razon_social || e.rut)}</b> · ${esc(e.rut)} · <span class="pill ${e.usa_sw_propio ? "p-ok" : "p-mut"}">${esc(e.estado_etiqueta || "sin diagnóstico")}</span>
      ${mundo() === "real" ? "<br>Esta empresa está en <b>producción</b>: lo que emitas cuenta ante el SII." : "<br>Esta empresa está en el <b>ambiente de pruebas</b> del SII: el SII responde, pero sin efecto tributario."}</div>`;
  }
  const sinc = (!e.demo && !e.usa_sw_propio) ? `<div class="card accion" data-tour="sincronizar" onclick="sincronizarGratuito()"><div class="ico">🔄</div><h3>Traer lo emitido en el SII</h3><p>Esta empresa emite en el sistema del SII. La app entra como tú, lista lo emitido y guarda PDF y XML aquí. Solo lectura.</p></div>` : "";
  const hora = new Date().getHours(), saludo = hora < 12 ? "Buenos días" : hora < 20 ? "Buenas tardes" : "Buenas noches";
  el.innerHTML = `
    <h1>${saludo}</h1>
    <p class="sub">${e.demo ? "Estás en la empresa de práctica: prueba todo sin miedo." : `Trabajando por <b>${esc(e.razon_social || e.rut)}</b>.`} ¿Qué quieres hacer?</p>
    ${cab}
    <div class="grid">
      ${sinc}
      <div class="card accion" data-tour="cobrar" onclick="ir('cobrar')"><div class="ico">🧾</div><h3>Cobrarle a alguien</h3><p>Una boleta o una factura. Ves neto, IVA y total antes de emitir.</p></div>
      <div class="card accion" onclick="ir('mes')"><div class="ico">📅</div><h3>Mi mes</h3><p>Cuánto vendiste, cuánto IVA cobraste y qué va a pedir el F29.</p></div>
      <div class="card accion" onclick="ir('corregir')"><div class="ico">↩️</div><h3>Corregir</h3><p>Nada se borra. Una nota de crédito arregla lo que salió mal.</p></div>
    </div>
    ${negocios.length ? "" : `<div class="card"><b>Todavía no hay ninguna empresa real.</b><p class="mut">Practica con la demo todo lo que quieras. Cuando tengas tu certificado digital, agrégalo en el panel del motor y tu empresa aparecerá arriba.</p>
      <button class="sec" data-tour="panel" onclick="window.go.main.App.AbrirPanel('certificados')">Abrir el panel</button></div>`}
    <p class="mut" id="valores_hoy"></p>
    <p class="mut">Motor v${esc(estado.version)} en <code>${esc(estado.url)}</code>${estado.externo ? " (externo)" : estado.empaquetado ? " (dentro de la app)" : " (desde el repo)"}.
      ${estado.empaquetado ? `Tus datos están en <code>${esc(estado.raiz)}</code>. Panel web: usuario <code>admin</code>, clave <code>${esc(estado.clave_admin)}</code>.` : ""}</p>`;
  pintarValores();
};
// UF, UTM y dólar del día (los trae el núcleo Go a la base; Python los lee).
async function pintarValores() {
  try {
    const v = await api("GET", "/api/v1/valores");
    const f = (x, dec) => (x ? x.valor.toLocaleString("es-CL", { minimumFractionDigits: dec, maximumFractionDigits: dec }) + (x.rezago_dias > 2 ? ` <span class="mut">(del ${x.fecha_valor})</span>` : "") : "—");
    const el = $("valores_hoy"); if (el) el.innerHTML = `Hoy: UF ${f(v.uf, 2)} · UTM ${f(v.utm, 0)} · dólar ${f(v.dolar, 2)}`;
  } catch {}
}
window.reiniciarDemo = async () => {
  if (!confirm("¿Borrar todos los documentos de práctica y volver a la boleta N° 1?")) return;
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
      <p class="mut">Desde <b>${esc(e.razon_social || e.rut)}</b> (cambia la empresa arriba).</p>
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
      <label>Qué le vendes</label><input id="c_que" placeholder="${e.demo ? "Café" : "Servicio"}">
      <div class="row"><div><label>Monto</label><input id="c_monto" type="number" min="0" step="1" placeholder="${e.demo ? "1190" : ""}"></div>
        <div><label>Ese monto es…</label><select id="c_modo"><option value="total">con IVA incluido (lo que paga)</option><option value="neto">neto (sin IVA)</option></select></div>
        <div><label>…o en UF</label><input id="c_uf" type="number" min="0" step="0.01" placeholder="80"></div></div>
      <p class="mut" id="c_uf_nota"></p>
      <div class="chk"><input type="checkbox" id="c_exento"><label for="c_exento" style="margin:0;font-weight:500">No lleva IVA (educación, salud, arriendo sin muebles…)</label></div>
      <div class="totales"><div><span>Neto</span><b id="t_neto">—</b></div><div><span>IVA 19%</span><b id="t_iva">—</b></div><div><span>Total</span><b id="t_total">—</b></div></div>
      <p class="mut" id="c_tipo"></p>
      <div id="c_aviso"></div>
      <button id="c_btn" onclick="emitir()">Revisar y emitir</button>
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
    $("c_tipo").textContent = `Documento: ${TIPOS[tipo]} (tipo ${tipo}).`;
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
  api("GET", "/api/v1/valores/uf").then((v) => { ufHoy = v; $("c_uf_nota").textContent = `UF de hoy: ${num(v.valor, 2)}${v.rezago_dias > 0 ? " (del " + v.fecha_valor + ")" : ""}`; }).catch(() => { $("c_uf_nota").textContent = "Sin UF cacheada: abre Valores o corre nucleo-valores actualizar."; });
  $("c_uf").addEventListener("input", () => {
    const uf = Number($("c_uf").value || 0);
    if (!uf || !ufHoy) return;
    const pesos = Math.round(uf * ufHoy.valor);
    $("c_monto").value = pesos; $("c_modo").value = "neto";
    $("c_uf_nota").textContent = `${num(uf, 2)} UF × ${num(ufHoy.valor, 2)} (UF del ${ufHoy.fecha_valor}) = $ ${num(pesos, 0)}`;
    rec();
  });
  rec();
  window.emitir = async () => {
    const { neto, iva, tipo, aEmpresa, ex } = rec();
    if (!neto) return aviso("Falta el monto.");
    if (aEmpresa && !$("c_rut").value.trim()) return aviso("Falta el RUT del cliente.");
    const que = $("c_que").value.trim() || "Venta";
    const total = neto + iva;
    if (!confirm(`Emitir ${TIPOS[tipo]} por ${clp(total)}?`)) return;
    $("c_btn").disabled = true;
    try {
      if (e.demo) {
        // En boletas el precio va CON IVA incluido (así las exige el SII); en facturas, neto.
        const precio = tipo === 39 ? total : neto;
        const body = { tipo_dte: tipo, items: [{ nombre: que, precio_unitario: precio, exento: ex }] };
        if (aEmpresa) body.receptor = { rut: $("c_rut").value.trim(), razon_social: $("c_nombre").value.trim() || "CLIENTE", es_contribuyente: true };
        const r = await api("POST", "/api/v1/simulacion/emitir", body);
        aviso(`${TIPOS[r.tipo_dte]} N° ${r.folio} emitida (práctica).`, 5000);
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
          if (!confirm(`Emitir en el SII una factura exenta por ${clp(v.monto_total)} a ${v.receptor.razon_social}? Un folio gastado no vuelve.`)) return;
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
  const id = param("id");
  const docs = (await api("GET", "/api/v1/dte/documentos?limite=200")).documentos;
  const d = docs.find((x) => String(x.id) === String(id));
  if (!d) throw new Error("No encontré ese documento.");
  const b64 = d.tiene_pdf ? await window.go.main.App.Bytes(`/api/v1/dte/documentos/${d.id}/pdf`) : null;
  const sim = d.ambiente === "simulacion";
  el.innerHTML = `
    <h1>${esc(TIPOS[d.tipo_dte] || d.tipo_dte)} N° ${d.folio}</h1>
    <p class="sub">${esc(d.razon_social_receptor || d.rut_receptor)} · ${esc((d.fecha_emision || "").slice(0, 10))} · ${clp(d.monto_total)}
      ${sim ? '<span class="pill p-ok">práctica</span>' : ""} ${d.estado === "anulado_simulado" ? '<span class="pill p-no">anulada</span>' : ""}</p>
    <div class="banner ${sim ? "verde" : ""}">Mira las partes: quién vende y su RUT, el <b>folio</b>, la fecha, el detalle, <b>neto, IVA y total</b>, y abajo el <b>timbre</b> (el código de barras cuadrado). ${sim ? "Es idéntico a uno real; solo que este no salió de tu computador." : ""}</div>
    ${b64 ? `<iframe style="width:100%;height:70vh;border:1px solid var(--bd);border-radius:12px;background:#fff" src="data:application/pdf;base64,${b64}"></iframe>` : '<p class="mut">Este documento no tiene PDF.</p>'}
    <div class="row" style="margin-top:12px">
      ${b64 ? `<button class="sec" onclick="bajar(${d.id},'pdf',${d.tipo_dte},${d.folio})">Guardar PDF</button>` : ""}
      ${d.tiene_xml ? `<button class="sec" onclick="bajar(${d.id},'xml',${d.tipo_dte},${d.folio})">Guardar XML</button>` : ""}
      ${sim && ![56, 61].includes(d.tipo_dte) && d.estado !== "anulado_simulado" ? `<button class="peligro" onclick="anularDemo(${d.id})">Anular con nota de crédito</button>` : ""}
      <button onclick="ir('cobrar')">Emitir otro</button>
    </div>`;
};
window.anularDemo = async (id) => {
  if (!confirm("Se va a emitir una nota de crédito por el total de este documento. El original no se borra: queda anulado. ¿Seguir?")) return;
  try { const nc = await api("POST", `/api/v1/simulacion/anular/${id}`, { motivo: "Anula documento" }); aviso(`Nota de crédito N° ${nc.folio} emitida.`); ir(`ver?id=${nc.dte_id}`); }
  catch (e) { aviso(e.message, 6000); }
};

// ---------- mi mes ----------
vistas.mes = async (el) => {
  await cargarNegocios();
  const e = empresa();
  const hoy = new Date(), per = `${hoy.getFullYear()}-${String(hoy.getMonth() + 1).padStart(2, "0")}`;
  el.innerHTML = `
    <h1>Mi mes</h1>
    <p class="sub">Lo que esta app tiene registrado de <b>${esc(e.razon_social || e.rut)}</b>. El SII arma su propio registro con lo que le llegó; si no coinciden, falta algo de un lado.</p>
    <div class="card"><div class="row">
      <div><label>Mes</label><input id="m_per" type="month" value="${per}"></div>
      <div><button class="sec" onclick="calcMes()">Ver</button></div></div>
      <div id="m_res"></div></div>`;
  window.calcMes = async () => {
    const p = $("m_per").value;
    const r = await api("GET", "/api/v1/dte/documentos?" + new URLSearchParams({ limite: 200, rut_emisor: e.rut }));
    const docs = r.documentos.filter((d) => (d.fecha_emision || "").startsWith(p));
    const signo = (d) => (d.tipo_dte === 61 ? -1 : 1);
    const sum = (k) => docs.reduce((a, d) => a + signo(d) * (d[k] || 0), 0);
    const neto = sum("monto_neto") + sum("monto_exento"), iva = sum("iva"), total = sum("monto_total");
    $("m_res").innerHTML = `
      <div class="totales"><div><span>Vendido (neto + exento)</span><b>${clp(neto)}</b></div><div><span>IVA cobrado (débito)</span><b>${clp(iva)}</b></div><div><span>Total documentos</span><b>${clp(total)}</b></div></div>
      <p class="mut">${docs.length} documento(s) en ${p}. Las notas de crédito restan. El IVA de tus <b>compras</b> con factura (crédito) se descuenta de este débito en el F29; eso lo trae el SII, no esta lista.</p>
      <div class="banner verde">Aunque no haya nada, el F29 se presenta igual: <b>sin movimiento</b>.</div>
      ${docs.length ? tabla(docs) : ""}`;
  };
  calcMes();
};

// ---------- corregir ----------
vistas.corregir = async (el) => {
  await cargarNegocios();
  const e = empresa();
  const r = await api("GET", "/api/v1/dte/documentos?" + new URLSearchParams({ limite: 100, rut_emisor: e.rut }));
  const corregibles = r.documentos.filter((d) => ![56, 61].includes(d.tipo_dte) && d.estado !== "anulado_simulado");
  el.innerHTML = `
    <h1>Corregir</h1>
    <p class="sub">Un documento emitido no se borra. Se corrige con otro: la nota de crédito resta, la nota de débito suma.</p>
    <div class="banner ${e.demo ? "verde" : ""}">Elige el documento que salió mal. La nota de crédito se arma por el <b>total registrado</b> de ese documento, para que quede en cero.</div>
    <div class="card">${tabla(corregibles, true)}</div>
    <div id="cor_aviso"></div>
    ${e.demo ? "" : `<p class="mut">Los documentos emitidos en el sistema del SII se anulan desde aquí con el SII engine (vista previa validada por el SII; la emisión real espera la cadena verificada). Los del motor propio, por ahora, desde el panel web del motor.</p>`}`;
};
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
      if (!confirm(`Emitir en el SII la nota de crédito por ${clp(v.monto_total)} que anula el N° ${v.anula.folio}? Un folio gastado no vuelve.`)) return;
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
  const r = await api("GET", "/api/v1/dte/documentos?" + new URLSearchParams({ limite: 100, rut_emisor: e.rut }));
  el.innerHTML = `
    <h1>Documentos</h1>
    <p class="sub">Boletas, facturas y notas de <b>${esc(e.razon_social || e.rut)}</b>${e.demo ? " (práctica)" : ", tanto las del motor como las del gratuito del SII"}.</p>
    <div class="card">${tabla(r.documentos)}</div>`;
};

function tabla(docs, elegir = false) {
  if (!docs.length) return `<div class="vacio"><div class="ico">🗂️</div>No hay documentos todavía.<br><span class="lnk" onclick="ir('cobrar')">Emitir el primero</span></div>`;
  const est = (e) => { e = e || ""; const c = e.includes("acept") || e.includes("emitido") || e === "simulado" ? "p-ok" : e.includes("rechaz") || e.includes("anulado") ? "p-no" : e.includes("envi") ? "p-warn" : "p-mut";
    const t = e === "simulado" ? "práctica" : e === "anulado_simulado" ? "anulada" : e.replace("_mipyme", " · gratuito SII"); return `<span class="pill ${c}">${esc(t)}</span>`; };
  return `<div class="tablewrap"><table><tr><th>Fecha</th><th>Documento</th><th>N°</th><th>Para</th><th class="num">Total</th><th>Estado</th><th></th></tr>
    ${docs.map((d) => `<tr><td>${esc((d.fecha_emision || "").slice(0, 10))}</td><td>${esc(TIPOS[d.tipo_dte] || d.tipo_dte)}</td><td>${d.folio}</td>
      <td>${esc(d.razon_social_receptor || d.rut_receptor || "")}</td><td class="num">${clp(d.monto_total)}</td><td>${est(d.estado)}</td>
      <td>${elegir ? `<span class="lnk" onclick="${d.ambiente === "simulacion" ? `anularDemo(${d.id})` : d.canal === "mipyme" ? `anularSII(${d.id})` : `aviso('Anular documentos del motor propio desde la app: próxima versión.')`}">anular</span>` :
        `${d.tiene_pdf ? `<span class="lnk" onclick="ir('ver?id=${d.id}')">ver</span> <span class="lnk" onclick="bajar(${d.id},'pdf',${d.tipo_dte},${d.folio})">PDF</span>` : ""} ${d.tiene_xml ? `<span class="lnk" onclick="bajar(${d.id},'xml',${d.tipo_dte},${d.folio})">XML</span>` : ""}`}</td></tr>`).join("")}
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
      <div><label>¿Cuánto valía el…?</label><input id="v_fecha" type="date" value="${hoy}" max="${hoy}"></div>
      <div><button class="sec" onclick="valoresFecha()">Ver</button></div></div>
      <div class="totales" id="v_tres"></div>
      <p class="mut" id="v_nota"></p></div>
    <div class="card"><div class="row">
      <div><label>Histórico mensual</label><select id="v_anio" onchange="valoresAnio()"></select></div></div>
      <div id="v_tabla"></div></div>`;
  window.valoresFecha = async () => {
    try {
      const v = await api("GET", "/api/v1/valores?fecha=" + $("v_fecha").value);
      const c = (x, dec) => `<div><span>${x ? "" : ""}</span><b>${x ? num(x.valor, dec) : "—"}</b><span>${x && x.rezago_dias > 0 ? "del " + x.fecha_valor : ""}</span></div>`;
      $("v_tres").innerHTML = `<div><span>UF</span><b>${v.uf ? num(v.uf.valor, 2) : "—"}</b><span>${v.uf && v.uf.rezago_dias > 0 ? "del " + v.uf.fecha_valor : ""}</span></div>
        <div><span>UTM</span><b>${v.utm ? num(v.utm.valor, 0) : "—"}</b><span>${v.utm ? "mes " + v.utm.fecha_valor.slice(0, 7) : ""}</span></div>
        <div><span>Dólar</span><b>${v.dolar ? num(v.dolar.valor, 2) : "—"}</b><span>${v.dolar && v.dolar.rezago_dias > 0 ? "del " + v.dolar.fecha_valor : ""}</span></div>`;
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
      ${h.meses.map((m) => `<tr><td>${m.mes}</td><td class="num">${num(m.uf, 2)}</td><td class="num">${num(m.uf_fin, 2)}</td><td class="num">${num(m.utm, 0)}</td><td class="num">${num(m.dolar, 2)}</td><td class="num">${num(m.dolar_fin, 2)}</td></tr>`).join("")}</table></div>`;
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

// ---------- arranque ----------
(async () => {
  estado = await window.go.main.App.Estado();
  pintarSelector(); pintarMundo();
  window.runtime.EventsOn("motor", (e) => { estado = e; pintarMundo(); render(); });
  render();
})();
