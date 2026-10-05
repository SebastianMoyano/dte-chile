// DTE Chile — interfaz de la app de escritorio. Sin framework: una función por vista.
// Todo lo que toca al motor pasa por `api()`, que llama a Go (App.API) y Go firma la petición.
// La clave del motor nunca llega aquí.

const $ = (id) => document.getElementById(id);
const clp = (n) => (n == null ? "—" : "$ " + Math.round(n).toLocaleString("es-CL"));
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const TIPOS = { 33: "Factura", 34: "Factura exenta", 39: "Boleta", 41: "Boleta exenta", 52: "Guía de despacho", 56: "Nota de débito", 61: "Nota de crédito" };
const IVA = 0.19;

let estado = { listo: false };
let negocios = [];

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

function pintarMundo() {
  const m = $("mundo");
  if (!estado.listo) { m.className = "mundo " + (estado.error ? "m-error" : "m-cargando"); m.textContent = estado.error ? "motor con error" : "arrancando motor…"; return; }
  if (estado.ambiente === "produccion") { m.className = "mundo m-real"; m.textContent = "REAL · cada documento cuenta"; }
  else { m.className = "mundo m-pruebas"; m.textContent = "PRUEBAS DEL SII · sin efecto tributario"; }
}

async function cargarNegocios() {
  try { negocios = await api("GET", "/api/v1/keystore/negocios"); } catch (e) { negocios = []; }
  return negocios;
}

// ---------- router ----------
const vistas = {};
function ir(v) { location.hash = "#" + v; }
async function render() {
  const v = (location.hash || "#inicio").slice(1).split("?")[0];
  document.querySelectorAll("nav a").forEach((a) => a.classList.toggle("on", a.dataset.v === v));
  const f = vistas[v] || vistas.inicio;
  $("vista").innerHTML = '<p class="mut">Cargando…</p>';
  try { await f($("vista")); } catch (e) { $("vista").innerHTML = `<div class="banner rojo">${esc(e.message)}</div>`; }
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
  const emp = negocios.length
    ? negocios.map((n) => `<div class="card"><b>${esc(n.razon_social || n.rut)}</b> <span class="mut">${esc(n.rut)}</span><br>
        <span class="pill ${n.usa_sw_propio ? "p-ok" : "p-mut"}">${esc(n.estado_etiqueta || "sin diagnóstico")}</span>
        <span class="pill ${n.ambiente === "produccion" ? "p-no" : "p-warn"}">${n.ambiente === "produccion" ? "real" : "pruebas"}</span></div>`).join("")
    : `<div class="card"><b>Todavía no hay ninguna empresa.</b><p class="mut">Agrega la primera desde el panel del motor (certificado + RUT). Después aparece aquí y en todas las pantallas.</p>
        <button class="sec" onclick="window.go.main.App.AbrirPanel('certificados')">Abrir el panel</button></div>`;
  el.innerHTML = `
    <h1>¿Qué quieres hacer?</h1>
    <p class="sub">Tres cosas cubren casi todo. Lo demás está arriba.</p>
    <div class="grid">
      <div class="card accion" onclick="ir('cobrar')"><div class="ico">🧾</div><h3>Cobrarle a alguien</h3><p>Una boleta o una factura. Te muestro el neto, el IVA y el total antes de emitir.</p></div>
      <div class="card accion" onclick="ir('mes')"><div class="ico">📅</div><h3>Mi mes</h3><p>Cuánto vendiste, cuánto IVA cobraste y qué va a pedir el F29.</p></div>
      <div class="card accion" onclick="ir('corregir')"><div class="ico">↩️</div><h3>Corregir</h3><p>Nada se borra. Una nota de crédito arregla lo que salió mal.</p></div>
    </div>
    <h2>Tus empresas</h2>
    ${emp}
    <p class="mut">Motor v${esc(estado.version)} en <code>${esc(estado.url)}</code>${estado.externo ? " (externo)" : ""}.</p>`;
};

// ---------- cobrar ----------
vistas.cobrar = async (el) => {
  await cargarNegocios();
  if (!negocios.length) { el.innerHTML = `<h1>Cobrarle a alguien</h1><div class="banner">Primero agrega una empresa en <span class="lnk" onclick="ir('inicio')">Inicio</span>.</div>`; return; }
  el.innerHTML = `
    <h1>Cobrarle a alguien</h1>
    <p class="sub">Llena lo mínimo. Abajo ves cómo queda el documento antes de emitirlo.</p>
    <div class="card">
      <label>Desde qué empresa</label>
      <select id="c_emp">${negocios.map((n) => `<option value="${esc(n.rut)}">${esc(n.razon_social || n.rut)}</option>`).join("")}</select>
      <label>A quién</label>
      <div class="radio">
        <label><input type="radio" name="c_quien" value="persona" checked> Una persona (boleta)</label>
        <label><input type="radio" name="c_quien" value="empresa"> Una empresa (factura)</label>
      </div>
      <div id="c_datos_emp" style="display:none">
        <div class="row"><div><label>RUT del cliente</label><input id="c_rut" placeholder="76111111-6"></div><div><label>Nombre o razón social</label><input id="c_nombre" placeholder="CLIENTE DEMO SPA"></div></div>
      </div>
      <label>Qué le vendes</label><input id="c_que" placeholder="Café para reunión">
      <div class="row"><div><label>Monto</label><input id="c_monto" type="number" min="0" step="1" placeholder="23800"></div>
        <div><label>Ese monto es…</label><select id="c_modo"><option value="total">con IVA incluido (lo que paga)</option><option value="neto">neto (sin IVA)</option></select></div></div>
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
    const empresa = document.querySelector('input[name="c_quien"]:checked').value === "empresa";
    $("c_datos_emp").style.display = empresa ? "block" : "none";
    const tipo = empresa ? (ex ? 34 : 33) : (ex ? 41 : 39);
    $("c_tipo").textContent = `Documento: ${TIPOS[tipo]} (tipo ${tipo}).`;
    const neg = negocios.find((n) => n.rut === $("c_emp").value);
    $("c_aviso").innerHTML = neg?.ambiente === "produccion"
      ? `<div class="banner rojo"><b>Esto es real.</b> Un folio gastado no vuelve. Revisa el RUT, el monto y el tipo antes de emitir.</div>`
      : `<div class="banner">Esta empresa está en el <b>ambiente de pruebas del SII</b>: el documento no tiene efecto tributario.</div>`;
    return { neto, iva, tipo, empresa, ex };
  };
  el.querySelectorAll("input,select").forEach((i) => i.addEventListener("input", rec));
  rec();
  window.emitir = async () => {
    const { neto, tipo, empresa, ex } = rec();
    const rut = $("c_emp").value, neg = negocios.find((n) => n.rut === rut);
    if (!neto) return aviso("Falta el monto.");
    if (empresa && !$("c_rut").value) return aviso("Falta el RUT del cliente.");
    if (!neg?.usa_sw_propio) {
      $("c_aviso").innerHTML += `<div class="banner"><b>${esc(neg?.razon_social || rut)}</b> emite hoy con <b>${neg?.estado_etiqueta?.toLowerCase().includes("gratuito") ? "el sistema gratuito del SII" : "otro software"}</b>, no con el motor propio.
        La emisión por el gratuito desde esta app llega en la próxima versión; mientras tanto el panel web ya importa lo emitido. <span class="lnk" onclick="window.go.main.App.AbrirPanel('certificados')">Abrir el panel</span>.</div>`;
      return;
    }
    const body = {
      dte: {
        tipo_dte: tipo, folio: 0,
        emisor: await emisorDe(rut),
        receptor: empresa ? { rut: $("c_rut").value.trim(), razon_social: $("c_nombre").value.trim() || "CLIENTE", es_contribuyente: true }
                          : { rut: "66666666-6", razon_social: "CONSUMIDOR FINAL", es_contribuyente: false },
        items: [{ numero_linea: 1, nombre: $("c_que").value.trim() || "Venta", cantidad: 1, precio_unitario: neto, exento: ex }],
        forma_pago: 1,
      },
    };
    if (!confirm(`Emitir ${TIPOS[tipo]} por ${clp(neto + (ex ? 0 : Math.round(neto * IVA)))}?`)) return;
    $("c_btn").disabled = true;
    try {
      const r = await api("POST", "/api/v1/dte/emitir", body);
      aviso(`Listo: ${TIPOS[r.tipo_dte]} folio ${r.folio}, ${clp(r.monto_total)}.`, 6000);
      ir("documentos");
    } catch (e) { $("c_aviso").innerHTML += `<div class="banner rojo">${esc(e.message)}</div>`; }
    finally { $("c_btn").disabled = false; }
  };
};

// Datos del emisor: el motor guarda la empresa configurada en .env (EMPRESA_*). Hasta que cada
// negocio tenga sus datos completos en BD, se usa esa y se exige que el RUT coincida.
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

// ---------- mi mes ----------
vistas.mes = async (el) => {
  await cargarNegocios();
  const hoy = new Date(), per = `${hoy.getFullYear()}-${String(hoy.getMonth() + 1).padStart(2, "0")}`;
  el.innerHTML = `
    <h1>Mi mes</h1>
    <p class="sub">Lo que esta app tiene registrado. El SII arma su propio registro con lo que le llegó; si no coinciden, falta algo de un lado.</p>
    <div class="card"><div class="row">
      <div><label>Empresa</label><select id="m_emp"><option value="">Todas</option>${negocios.map((n) => `<option value="${esc(n.rut)}">${esc(n.razon_social || n.rut)}</option>`).join("")}</select></div>
      <div><label>Mes</label><input id="m_per" type="month" value="${per}"></div>
      <div><button class="sec" onclick="calcMes()">Ver</button></div></div>
      <div id="m_res"></div></div>`;
  window.calcMes = async () => {
    const rut = $("m_emp").value, p = $("m_per").value;
    const q = new URLSearchParams({ limite: 200 }); if (rut) q.set("rut_emisor", rut);
    const r = await api("GET", "/api/v1/dte/documentos?" + q);
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
  const r = await api("GET", "/api/v1/dte/documentos?limite=50");
  el.innerHTML = `
    <h1>Corregir</h1>
    <p class="sub">Un documento emitido no se borra. Se corrige con otro: la nota de crédito resta, la nota de débito suma.</p>
    <div class="banner">Elige el documento que salió mal. La nota de crédito se arma por el <b>total registrado</b> de ese documento, para que quede en cero.</div>
    <div class="card">${tabla(r.documentos.filter((d) => ![56, 61].includes(d.tipo_dte)), true)}</div>
    <p class="mut">La emisión de la nota de crédito desde esta app llega en la próxima versión. Hoy se hace desde el panel web del motor o, si la empresa usa el gratuito, desde el portal del SII con la guía del repo (docs/MIPYME.md).</p>`;
};

// ---------- documentos ----------
vistas.documentos = async (el) => {
  const [r, em] = await Promise.all([api("GET", "/api/v1/dte/documentos?limite=100"), api("GET", "/api/v1/dte/documentos/emisores")]);
  el.innerHTML = `
    <h1>Documentos</h1>
    <p class="sub">Boletas, facturas y notas de todas tus empresas, tanto las del motor como las del gratuito del SII.</p>
    <div class="card"><label>Empresa</label><select id="d_emp" onchange="filtrarDocs()"><option value="">Todas</option>${em.emisores.map((e) => `<option value="${esc(e.rut)}">${esc(e.razon_social || e.rut)} (${e.documentos})</option>`).join("")}</select>
    <div id="d_tabla">${tabla(r.documentos)}</div></div>`;
  window._docs = r.documentos;
  window.filtrarDocs = () => { const rut = $("d_emp").value; $("d_tabla").innerHTML = tabla(window._docs.filter((d) => !rut || d.rut_emisor === rut)); };
};

function tabla(docs, elegir = false) {
  if (!docs.length) return `<p class="mut">No hay documentos.</p>`;
  const est = (e) => { e = e || ""; const c = e.includes("acept") || e.includes("emitido") ? "p-ok" : e.includes("rechaz") ? "p-no" : e.includes("envi") ? "p-warn" : "p-mut"; return `<span class="pill ${c}">${esc(e.replace("_mipyme", " · gratuito SII"))}</span>`; };
  return `<div class="tablewrap"><table><tr><th>Fecha</th><th>Documento</th><th>Folio</th><th>Para</th><th class="num">Total</th><th>Estado</th><th></th></tr>
    ${docs.map((d) => `<tr><td>${esc((d.fecha_emision || "").slice(0, 10))}</td><td>${esc(TIPOS[d.tipo_dte] || d.tipo_dte)}</td><td>${d.folio}</td>
      <td>${esc(d.razon_social_receptor || d.rut_receptor || "")}</td><td class="num">${clp(d.monto_total)}</td><td>${est(d.estado)}</td>
      <td>${elegir ? `<span class="lnk" onclick="aviso('Anular desde la app: próxima versión.')">corregir</span>` :
        `${d.tiene_pdf ? `<span class="lnk" onclick="bajar(${d.id},'pdf',${d.tipo_dte},${d.folio})">PDF</span>` : ""} ${d.tiene_xml ? `<span class="lnk" onclick="bajar(${d.id},'xml',${d.tipo_dte},${d.folio})">XML</span>` : ""}`}</td></tr>`).join("")}
    </table></div>`;
}
window.bajar = async (id, que, tipo, folio) => {
  try { const p = await window.go.main.App.Guardar(`/api/v1/dte/documentos/${id}/${que}`, `T${tipo}_F${folio}.${que}`); if (p) aviso("Guardado en " + p, 5000); }
  catch (e) { aviso("No se pudo guardar: " + e, 6000); }
};

// ---------- aprender ----------
vistas.aprender = async (el) => {
  el.innerHTML = `
    <h1>Aprender</h1>
    <p class="sub">Para quien no sabe nada de finanzas. Cinco tramos, en el orden en que pasan en la vida real.</p>
    <div class="grid">
      ${[["1. Entender", "Qué es una boleta, el IVA, el folio, el SII, declarar. Simulación, sin riesgo.", "sim"],
         ["2. Crear la empresa", "Persona natural o empresa, Empresa en un Día, el RUT propio.", "sim"],
         ["3. Iniciar actividades", "Giro, clave tributaria, certificado digital, inscribirse como emisor.", "sim"],
         ["4. Usar lo gratis del SII", "El emisor gratuito de facturas y boletas, con esta app como complemento. Real desde el primer clic.", "real"],
         ["5. El motor propio", "CAF, firma, certificación. Primero en el ambiente de pruebas del SII.", "pruebas"]]
        .map(([t, d, m]) => `<div class="card"><span class="pill ${m === "real" ? "p-no" : m === "pruebas" ? "p-warn" : "p-ok"}">${m === "real" ? "real" : m === "pruebas" ? "pruebas del SII" : "simulación"}</span><h3 style="margin:8px 0 4px">${t}</h3><p class="mut" style="margin:0">${d}</p></div>`).join("")}
    </div>
    <p class="mut">Las lecciones, el quiz y los videos del tramo 1 están en el repo (<code>docs/aprender/</code>). En esta pantalla se van a cargar en la próxima versión.</p>`;
};

// ---------- arranque ----------
(async () => {
  estado = await window.go.main.App.Estado();
  pintarMundo();
  window.runtime.EventsOn("motor", (e) => { estado = e; pintarMundo(); render(); });
  render();
})();
