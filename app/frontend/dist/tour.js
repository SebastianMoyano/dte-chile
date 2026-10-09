// Tour guiado por etapas. Las cinco etapas son los tramos de docs/aprender/00-plan.md, en el
// orden en que pasan en la vida real. Cada etapa tiene pasos; un paso apunta a algo de una
// pantalla (se ilumina) o es una explicación. El tour es PROGRESIVO: cuando la persona entra
// por primera vez a una pantalla, aparecen solo los pasos de esa pantalla de la etapa en curso;
// desde "Guía" (barra lateral) se ve el camino entero y se puede repetir cualquier etapa.
// El avance queda en localStorage de este equipo; nada sale de aquí.
(() => {
  const ETAPAS = [
    { id: "entender", n: 1, titulo: "Entender", mundo: "sim", resumen: "Qué es una boleta, el IVA, el folio y el SII. Todo en práctica: nada sale de tu computador.",
      pasos: [
        { vista: "inicio", sel: "#mundo", t: "Mira siempre este semáforo", p: "Dice en qué mundo estás. Verde: práctica, nada sale de aquí. Amarillo: pruebas del SII, sin efecto. Rojo: real, cada documento cuenta." },
        { vista: "inicio", sel: "#empresa", t: "La empresa activa", p: "Aquí eliges por quién trabajas. EMPRESA DEMO SPA es la de práctica: úsala para aprender sin riesgo." },
        { vista: "inicio", sel: "[data-tour='cobrar']", t: "Lo primero: cobrar", p: "Una boleta es lo que le das a una persona; una factura, a otra empresa. Entra aquí y emite tu primera boleta de práctica." },
        { vista: "cobrar", sel: "#c_monto", t: "El monto y el IVA", p: "Escribe 1190 con IVA incluido: verás que el neto es 1.000 y el IVA 190. El IVA es el 19% que va al Estado; tú solo lo recaudas." },
        { vista: "cobrar", sel: ".totales", t: "Neto, IVA y total", p: "Estos tres números son los que aparecen en todo documento. Si el monto es exento, el IVA es cero." },
        { vista: "cobrar", sel: "#c_btn", t: "Revisar y emitir", p: "Al emitir, la app arma el documento, lo firma y le pone el timbre, igual que uno real. En práctica no sale de tu computador." },
        { vista: "ver", sel: "iframe", t: "Las partes del documento", p: "Quién vende y su RUT, el folio (un número que nunca se repite), la fecha, el detalle, neto, IVA y total, y abajo el timbre: el código de barras cuadrado." },
        { vista: "documentos", sel: "table", t: "Todo queda registrado", p: "Un documento emitido no se borra nunca. Aquí ves todos, con su estado." },
        { vista: "corregir", sel: "table", t: "Equivocarse se arregla con otro documento", p: "Una nota de crédito resta lo que salió mal y deja el original anulado. Prueba a anular uno de práctica." },
        { vista: "mes", sel: ".totales", t: "Lo que pide el F29", p: "Cada mes declaras lo vendido y el IVA cobrado. Aunque no vendas nada, el F29 se presenta igual: sin movimiento." },
      ] },
    { id: "crear", n: 2, titulo: "Crear la empresa", mundo: "sim", resumen: "Persona natural o empresa, Empresa en un Día, el RUT propio. La app te guía; el trámite lo haces tú.",
      pasos: [
        { vista: "aprender", sel: "[data-tour='etapa-2']", t: "¿Persona natural o empresa?", p: "Puedes emitir boletas como persona con tu propio RUT. Una empresa (SpA, EIRL, Ltda.) es otra persona ante la ley, con su propio RUT y su representante legal." },
        { vista: "aprender", sel: "[data-tour='etapa-2']", t: "Empresa en un Día", p: "El portal del Estado para constituir la sociedad en línea. Sale con RUT y escritura. Esta etapa es una lista de verificación: márcala a medida que avances." },
      ] },
    { id: "iniciar", n: 3, titulo: "Iniciar actividades", mundo: "sim", resumen: "Giro, clave tributaria, certificado digital e inscripción como emisor. Solo lectura contra el SII.",
      pasos: [
        { vista: "aprender", sel: "[data-tour='etapa-3']", t: "Antes de emitir, el SII tiene que saber quién eres", p: "Inicio de actividades y giro en sii.cl, clave tributaria de la persona y de la empresa, y un certificado digital para firmar." },
        { vista: "inicio", sel: "[data-tour='panel']", t: "El certificado va al panel", p: "Cuando tengas el certificado digital (.p12), cárgalo en el panel del motor. La empresa aparecerá en el selector de arriba." },
      ] },
    { id: "sii", n: 4, titulo: "Usar lo que el SII da", mundo: "real", resumen: "El SII tiene un emisor propio. La app lo opera por ti y le agrega lo que falta. Real desde el primer clic.",
      pasos: [
        { vista: "inicio", sel: "#empresa", t: "Elige una empresa real", p: "Las empresas que emiten en el sistema del SII aparecen aquí con la etiqueta 'gratuito'. El semáforo se pone rojo: lo que hagas cuenta." },
        { vista: "inicio", sel: "[data-tour='sincronizar']", t: "Traer lo emitido en el SII", p: "La app entra al SII como tú, lista todo lo emitido y guarda aquí PDF y XML. Solo lectura, no gasta nada." },
        { vista: "cobrar", sel: "#c_btn", t: "Cobrar por el SII", p: "Con 'Una empresa' y 'No lleva IVA', la app valida la factura en el SII sin gastar folio y te la muestra antes de emitir." },
        { vista: "corregir", sel: "table", t: "Anular en el SII", p: "La nota de crédito la pre-arma el propio SII con los datos del documento; la app la valida y te la muestra." },
      ] },
    { id: "motor", n: 5, titulo: "El motor propio", mundo: "pruebas", resumen: "CAF, firma y certificación: para quien emite mucho o integra sistemas. Primero en el ambiente de pruebas del SII.",
      pasos: [
        { vista: "aprender", sel: "[data-tour='etapa-5']", t: "Folios propios y firma propia", p: "Con el motor propio el SII te entrega folios (CAF) y tú firmas con tu certificado. Antes hay que certificar: un set de pruebas que el SII revisa." },
        { vista: "cobrar", sel: "#c_btn", t: "Emitir con el núcleo", p: "Para una empresa con motor propio, cobrar firma y timbra en tu computador y envía al SII. Primero en pruebas (amarillo), luego en real (rojo)." },
      ] },
  ];

  const CLAVE = "tour.v1";
  let st = { vistos: {}, etapa: 0, checks: {}, apagado: false };
  try { st = { ...st, ...(JSON.parse(localStorage.getItem(CLAVE) || "{}")) }; } catch {}
  const guardar = () => { try { localStorage.setItem(CLAVE, JSON.stringify(st)); } catch {} };
  const idPaso = (e, i) => `${e.id}:${i}`;
  const hecha = (e) => e.pasos.every((_, i) => st.vistos[idPaso(e, i)]);
  const progreso = (e) => e.pasos.filter((_, i) => st.vistos[idPaso(e, i)]).length;
  const etapaActual = () => ETAPAS[Math.min(st.etapa, ETAPAS.length - 1)];

  let cola = [], idx = 0, modo = "contextual";
  const el = () => document.getElementById("tour");

  function pintarCamino() {
    const ol = document.getElementById("camino_lista");
    if (!ol) return;
    ol.innerHTML = ETAPAS.map((e, i) => `<li class="${hecha(e) ? "hecha" : ""} ${i === st.etapa ? "actual" : ""}" onclick="Tour.etapa(${i})" title="${e.resumen}">
      <span class="dot">${hecha(e) ? "✓" : e.n}</span><span>${e.titulo}</span></li>`).join("");
  }

  function cerrar() { el().style.display = "none"; el().innerHTML = ""; cola = []; pintarCamino(); }

  function colocar(target, card) {
    const r = target ? target.getBoundingClientRect() : null;
    const hole = el().querySelector(".tour-hole");
    if (r && r.width && r.height) {
      hole.className = "tour-hole";
      Object.assign(hole.style, { left: r.left - 8 + "px", top: r.top - 8 + "px", width: r.width + 16 + "px", height: r.height + 16 + "px" });
      const cw = Math.min(380, window.innerWidth - 32), ch = card.offsetHeight || 160;
      let top = r.bottom + 14, left = Math.min(Math.max(16, r.left), window.innerWidth - cw - 16);
      if (top + ch > window.innerHeight - 16) top = Math.max(16, r.top - ch - 14);
      if (top < 16 && r.right + cw + 16 < window.innerWidth) { top = Math.max(16, r.top); left = r.right + 14; }
      Object.assign(card.style, { left: left + "px", top: top + "px" });
    } else {
      hole.className = "tour-hole sin";
      Object.assign(card.style, { left: Math.max(16, (window.innerWidth - 380) / 2) + "px", top: "18%" });
    }
  }

  function mostrarPaso() {
    if (idx >= cola.length) { terminarEtapaSiCorresponde(); cerrar(); return; }
    const { etapa, i } = cola[idx], paso = etapa.pasos[i];
    const vista = (location.hash || "#inicio").slice(1).split("?")[0];
    if (paso.vista !== vista && modo === "guiado") { location.hash = "#" + paso.vista; setTimeout(mostrarPaso, 350); return; }
    const target = paso.sel ? document.querySelector(paso.sel) : null;
    if (paso.sel && !target && modo === "contextual") { idx++; mostrarPaso(); return; }
    if (target) target.scrollIntoView({ block: "center", behavior: "smooth" });
    const t = el();
    t.style.display = "block";
    t.innerHTML = `<div class="tour-hole sin"></div><div class="tour-card">
      <div class="etapa">Etapa ${etapa.n} · ${etapa.titulo}</div><h3>${paso.t}</h3><p>${paso.p}</p>
      <div class="acciones"><span class="paso">${i + 1} de ${etapa.pasos.length}</span>
        <button class="sec" onclick="Tour.saltar()">Saltar</button>
        ${idx > 0 ? `<button class="sec" onclick="Tour.atras()">Anterior</button>` : ""}
        <button onclick="Tour.siguiente()">${idx === cola.length - 1 ? "Listo" : "Siguiente"}</button></div></div>`;
    const card = t.querySelector(".tour-card");
    setTimeout(() => colocar(target, card), target ? 320 : 0);
    st.vistos[idPaso(etapa, i)] = true; guardar(); pintarCamino();
  }

  function terminarEtapaSiCorresponde() {
    const e = etapaActual();
    if (hecha(e) && st.etapa < ETAPAS.length - 1) {
      st.etapa++; guardar();
      aviso?.(`Etapa ${e.n} completa. Sigue con la ${st.etapa + 1}: ${ETAPAS[st.etapa].titulo}.`, 6000);
    }
  }

  // Llamado por app.js después de pintar una pantalla: pasos pendientes de esa pantalla, etapa en curso.
  function alEntrar(vista) {
    pintarCamino();
    if (st.apagado || el().style.display === "block") return;
    const e = etapaActual();
    const pendientes = e.pasos.map((p, i) => ({ etapa: e, i })).filter(({ i }) => e.pasos[i].vista === vista && !st.vistos[idPaso(e, i)]);
    if (!pendientes.length) return;
    cola = pendientes; idx = 0; modo = "contextual";
    setTimeout(mostrarPaso, 250);
  }

  function abrir() {
    const t = el();
    t.style.display = "block";
    t.innerHTML = `<div class="tour-hole sin"></div><div class="tour-panel card">
      <h2 style="margin:0 0 4px">Tu camino</h2><p class="mut" style="margin:0">De cero a emitir, en cinco etapas. Entra a una para recorrerla paso a paso; las ya vistas se pueden repetir.</p>
      <div class="etapas">${ETAPAS.map((e, i) => `<div class="et ${hecha(e) ? "hecha" : ""} ${i === st.etapa ? "actual" : ""}" onclick="Tour.etapa(${i})">
        <span class="n">${hecha(e) ? "✓" : e.n}</span><div><b>${e.titulo}</b><span>${e.resumen}</span></div>
        <span class="pill ${e.mundo === "real" ? "p-no" : e.mundo === "pruebas" ? "p-warn" : "p-ok"}">${e.mundo === "real" ? "real" : e.mundo === "pruebas" ? "pruebas" : "práctica"} · ${progreso(e)}/${e.pasos.length}</span></div>`).join("")}</div>
      <div class="acciones" style="display:flex;gap:8px;margin-top:14px;align-items:center">
        <label class="chk" style="margin:0;font-size:.86rem"><input type="checkbox" ${st.apagado ? "checked" : ""} onchange="Tour.apagar(this.checked)"> No mostrar pistas automáticas</label>
        <span style="flex:1"></span>
        <button class="sec" onclick="Tour.reiniciar()">Empezar de cero</button><button onclick="Tour.cerrar()">Cerrar</button></div></div>`;
  }

  function etapa(i) {
    const e = ETAPAS[i];
    cola = e.pasos.map((_, j) => ({ etapa: e, i: j })); idx = 0; modo = "guiado";
    st.etapa = i; guardar();
    if (e.id !== "entender" && e.id !== "sii" && e.id !== "motor") { cerrar(); location.hash = "#aprender?etapa=" + e.n; setTimeout(mostrarPaso, 350); return; }
    cerrar(); mostrarPaso();
  }

  window.Tour = {
    alEntrar, abrir, etapa, cerrar,
    siguiente() { idx++; mostrarPaso(); },
    atras() { idx = Math.max(0, idx - 1); mostrarPaso(); },
    saltar() { cola.forEach(({ etapa, i }) => { st.vistos[idPaso(etapa, i)] = true; }); guardar(); terminarEtapaSiCorresponde(); cerrar(); },
    apagar(v) { st.apagado = !!v; guardar(); },
    reiniciar() { st = { vistos: {}, etapa: 0, checks: {}, apagado: false }; guardar(); cerrar(); location.hash = "#inicio"; setTimeout(() => alEntrar("inicio"), 300); },
    etapas: ETAPAS, estado: () => st,
    check(id, v) { st.checks[id] = !!v; guardar(); },
  };
  window.addEventListener("resize", () => { if (cola.length && el().style.display === "block") mostrarPaso(); });
  // app.js avisa cada pantalla pintada; si la primera ya se pintó antes de cargar este archivo, se recoge igual.
  document.addEventListener("vista", (e) => alEntrar(e.detail));
  pintarCamino();
  const vistaActual = (location.hash || "#inicio").slice(1).split("?")[0];
  if (document.getElementById("vista")?.children.length) alEntrar(vistaActual);
})();
