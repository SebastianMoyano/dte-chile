// Tour guiado por etapas, pensado como PRIMERA introducción (alumnos de colegio): bienvenida la
// primera vez, una tarjeta con flecha que apunta al elemento iluminado, anillo que late, puntos
// de progreso, teclado (Enter/→ siguiente, ← anterior, Esc saltar) y cierre de etapa.
//
// Las cinco etapas son los tramos de docs/aprender/00-plan.md, en el orden en que pasan en la
// vida real. Cada paso apunta a algo de una pantalla o explica un concepto. Es PROGRESIVO: al
// entrar por primera vez a una pantalla aparecen solo sus pasos de la etapa en curso; desde
// "Guía" se ve el camino entero y se repite cualquier etapa. El avance queda en localStorage.
//
// Decir que no se respeta: "Ahora no" en una pista automática (o "Explorar por mi cuenta" en la
// bienvenida) apaga las pistas automáticas, y se vuelve a ellas desde Guía; "Salir" en un
// recorrido solo lo cierra. Ninguno marca pasos como vistos: el progreso cuenta lo que la
// persona recorrió de verdad.
(() => {
  const ETAPAS = [
    { id: "entender", n: 1, titulo: "Entender", mundo: "sim", resumen: "Qué es una boleta, el IVA, el folio y el SII. Todo en práctica: nada sale de tu computador.",
      pasos: [
        { vista: "inicio", sel: "#mundo", t: "Mira siempre este semáforo", p: "Dice en qué mundo estás. Verde: práctica, nada sale de aquí. Amarillo: pruebas del SII, sin efecto. Rojo: real, cada documento cuenta." },
        { vista: "inicio", sel: ".sel-wrap", t: "La empresa activa", p: "Hoy trabajas con EMPRESA DEMO SPA, la de práctica: úsala para aprender sin riesgo. Cuando agregues una empresa real, arriba aparece un selector para elegir por quién trabajas." },
        { vista: "inicio", sel: "[data-tour='cobrar']", t: "Lo primero: emitir", p: "Una boleta es lo que le das a una persona; una factura, a otra empresa. Entra aquí y emite tu primera boleta de práctica." },
        { vista: "cobrar", sel: "#c_monto", demo: "monto", t: "El monto y el IVA", p: "Escribe 1190 con IVA incluido: verás que el neto es 1.000 y el IVA 190. El IVA es el 19% que va al Estado; tú solo lo recaudas." },
        { vista: "cobrar", sel: ".totales", t: "Neto, IVA y total", p: "Estos tres números aparecen en todo documento. Si el monto es exento, el IVA es cero." },
        { vista: "cobrar", sel: "#c_btn", demo: "emitir", t: "Revisar y emitir", p: "Al emitir, la app arma el documento, lo firma y le pone el timbre, igual que uno real. En práctica no sale de tu computador." },
        { vista: "ver", hash: () => { let id = null; try { id = localStorage.getItem("ultimo_dte"); } catch {} return id ? "ver?id=" + id : null; }, sel: "iframe", t: "Las partes del documento", p: "Quién vende y su RUT, el folio (un número que nunca se repite), la fecha, el detalle, neto, IVA y total, y abajo el timbre: el código de barras cuadrado." },
        { vista: "documentos", sel: "table", t: "Todo queda registrado", p: "Un documento emitido no se borra nunca. Aquí ves todos, con su estado." },
        { vista: "documentos", sel: "[data-tour='anular']", demo: "anular", t: "Equivocarse se arregla con otro documento", p: "Pulsa «anular» en un documento de práctica: una nota de crédito resta lo que salió mal y deja el original anulado. Nada se borra." },
        { vista: "documentos", hash: "documentos?tab=mes", sel: ".totales", demo: "mes", t: "Lo que pide el F29", p: "Cada mes declaras lo vendido y el IVA cobrado. Aunque no vendas nada, el F29 se presenta igual: sin movimiento." },
      ] },
    { id: "crear", n: 2, titulo: "Crear la empresa", mundo: "sim", resumen: "Persona natural o empresa, Empresa en un Día, el RUT propio. La app te guía; el trámite lo haces tú.",
      pasos: [
        { vista: "aprender", sel: "[data-tour='etapa-2']", t: "¿Persona natural o empresa?", p: "Puedes emitir boletas como persona con tu propio RUT. Una empresa (SpA, EIRL, Ltda.) es otra persona ante la ley, con su propio RUT y su representante legal." },
        { vista: "aprender", sel: "[data-tour='etapa-2'] .lista-check", t: "Empresa en un Día", p: "El portal del Estado para constituir la sociedad en línea. Sale con RUT y escritura. Esta etapa es una lista: márcala a medida que avances." },
      ] },
    { id: "iniciar", n: 3, titulo: "Iniciar actividades", mundo: "sim", resumen: "Giro, clave tributaria, certificado digital e inscripción como emisor. Solo lectura contra el SII.",
      pasos: [
        { vista: "aprender", sel: "[data-tour='etapa-3']", t: "Antes de emitir, el SII tiene que saber quién eres", p: "Inicio de actividades y giro en sii.cl, clave tributaria de la persona y de la empresa, y un certificado digital para firmar." },
        { vista: "inicio", sel: "[data-tour='panel']", t: "El certificado va al panel", p: "Cuando tengas el certificado digital (.p12), cárgalo en el panel del motor. La empresa aparecerá en el selector de arriba." },
      ] },
    { id: "sii", n: 4, titulo: "Emitir con el SII", mundo: "real", resumen: "El SII tiene un emisor propio. La app lo opera por ti y le agrega lo que falta. Real desde el primer clic.",
      pasos: [
        { vista: "inicio", sel: "#empresa", t: "Elige una empresa real", p: "Las empresas que emiten en el sistema del SII aparecen aquí con la etiqueta 'gratuito'. El semáforo se pone rojo: lo que hagas cuenta." },
        { vista: "inicio", sel: "[data-tour='sincronizar']", t: "Traer lo emitido en el SII", p: "La app entra al SII como tú, lista todo lo emitido y guarda aquí PDF y XML. Solo lectura, no gasta nada." },
        { vista: "cobrar", sel: "#c_btn", t: "Emitir por el SII", p: "Con 'Una empresa' y 'No lleva IVA', la app valida la factura en el SII sin gastar folio y te la muestra antes de emitir." },
        { vista: "documentos", sel: "[data-tour='anular']", t: "Anular en el SII", p: "La nota de crédito la pre-arma el propio SII con los datos del documento; la app la valida y te la muestra." },
      ] },
    { id: "motor", n: 5, titulo: "Tu propio sistema", mundo: "pruebas", resumen: "CAF, firma y certificación: para quien emite mucho o integra sistemas. Primero en el ambiente de pruebas del SII.",
      pasos: [
        { vista: "aprender", sel: "[data-tour='etapa-5']", t: "Folios propios y firma propia", p: "Con el motor propio el SII te entrega folios (CAF) y tú firmas con tu certificado. Antes hay que certificar: un set de pruebas que el SII revisa." },
        { vista: "cobrar", sel: "#c_btn", t: "Emitir con el núcleo", p: "Para una empresa con motor propio, cobrar firma y timbra en tu computador y envía al SII. Primero en pruebas (amarillo), luego en real (rojo)." },
      ] },
  ];

  const CLAVE = "tour.v1";
  let st = { vistos: {}, etapa: 0, checks: {}, apagado: false, bienvenida: false };
  try { st = { ...st, ...(JSON.parse(localStorage.getItem(CLAVE) || "{}")) }; } catch {}
  const guardar = () => { try { localStorage.setItem(CLAVE, JSON.stringify(st)); } catch {} };
  const idPaso = (e, i) => `${e.id}:${i}`;
  const hecha = (e) => e.pasos.every((_, i) => st.vistos[idPaso(e, i)]);
  const progreso = (e) => e.pasos.filter((_, i) => st.vistos[idPaso(e, i)]).length;
  const etapaActual = () => ETAPAS[Math.min(st.etapa, ETAPAS.length - 1)];
  const vistaActual = () => (location.hash || "#inicio").slice(1).split("?")[0];

  let cola = [], idx = 0, modo = "contextual", primeraColocacion = true, programado = null, vistaPrevia = null;
  const el = () => document.getElementById("tour");
  const programar = (f, ms) => { clearTimeout(programado); programado = setTimeout(f, ms); };
  const avisar = (t) => { if (typeof window.aviso === "function") window.aviso(t, 5000); };

  function pintarCamino() {
    const c = document.getElementById("camino_lista");
    if (!c) return;
    const e = etapaActual(), listas = ETAPAS.filter(hecha).length;
    const pct = Math.round((ETAPAS.reduce((a, x) => a + progreso(x), 0) / ETAPAS.reduce((a, x) => a + x.pasos.length, 0)) * 100);
    c.innerHTML = `<button class="camino-res" onclick="Tour.abrir()" title="${e.resumen} · ${listas === ETAPAS.length ? "camino completo" : `${listas} de ${ETAPAS.length} etapas listas`}">
      <b>Guía</b><span>Etapa ${e.n} · ${e.titulo}</span><div class="barra"><i style="width:${pct}%"></i></div></button>`;
  }

  function cerrar() { el().style.display = "none"; el().innerHTML = ""; cola = []; pintarCamino(); }

  // Coloca el recorte sobre el elemento y la tarjeta al lado, con la flecha apuntándole.
  // La primera colocación de un recorrido es instantánea (sin "viaje" desde la esquina); entre
  // pasos seguidos, se desliza.
  function colocar(target, card) {
    const hole = el().querySelector(".tour-hole");
    const r = target ? target.getBoundingClientRect() : null;
    if (!(r && r.width && r.height)) {
      hole.className = "tour-hole sin";
      hole.removeAttribute("style");   // sin elemento no queda el recorte anterior dibujado
      card.className = "tour-card";
      Object.assign(card.style, { left: Math.max(16, (window.innerWidth - card.offsetWidth) / 2) + "px", top: "20%" });
      return;
    }
    hole.className = "tour-hole" + (primeraColocacion ? "" : " mover");
    Object.assign(hole.style, { left: r.left - 8 + "px", top: r.top - 8 + "px", width: r.width + 16 + "px", height: r.height + 16 + "px" });
    primeraColocacion = false;
    const cw = card.offsetWidth, ch = card.offsetHeight, M = 16, G = 18;
    let lado = "abajo", top, left;
    if (r.bottom + G + ch <= window.innerHeight - M) { lado = "abajo"; top = r.bottom + G; }
    else if (r.top - G - ch >= M) { lado = "arriba"; top = r.top - G - ch; }
    else if (r.right + G + cw <= window.innerWidth - M) { lado = "derecha"; top = Math.min(Math.max(M, r.top), window.innerHeight - ch - M); }
    else { lado = "abajo"; top = Math.max(M, window.innerHeight - ch - M); }
    if (lado === "derecha") { left = r.right + G; }
    else { left = Math.min(Math.max(M, r.left + r.width / 2 - cw / 2), window.innerWidth - cw - M); }
    card.className = "tour-card " + lado;
    const centro = lado === "derecha" ? Math.min(Math.max(16, r.top + r.height / 2 - top - 7), ch - 30) : Math.min(Math.max(16, r.left + r.width / 2 - left - 7), cw - 30);
    card.style.setProperty("--flecha", centro + "px");
    Object.assign(card.style, { left: left + "px", top: top + "px" });
  }

  function mostrarPaso() {
    if (idx >= cola.length) { finDeRecorrido(); return; }
    const { etapa, i } = cola[idx], paso = etapa.pasos[i];
    const hashActual = (location.hash || "#inicio").slice(1);
    const hashPaso = typeof paso.hash === "function" ? paso.hash() : paso.hash;
    if (typeof paso.hash === "function" && !hashPaso) { idx++; mostrarPaso(); return; }   // no hay a qué apuntar todavía (p. ej. ningún documento)
    if (modo === "guiado" && (paso.vista !== vistaActual() || (hashPaso && hashActual !== hashPaso))) { location.hash = "#" + (hashPaso || paso.vista); setTimeout(mostrarPaso, 400); return; }
    let target = paso.sel ? document.querySelector(paso.sel) : null;
    if (target && !target.getBoundingClientRect().width) target = null;   // oculto: se trata como ausente
    if (paso.sel && !target && modo === "contextual") { idx++; mostrarPaso(); return; }
    if (target) target.scrollIntoView({ block: "center", behavior: "instant" });
    const t = el();
    const nuevo = t.style.display !== "block" || !t.querySelector(".tour-hole");
    if (nuevo) { t.innerHTML = `<div class="tour-hole sin"></div>`; primeraColocacion = true; }
    // Al cambiar de pantalla el recorte aparece donde corresponde, sin deslizarse desde la anterior.
    if (vistaActual() !== vistaPrevia) primeraColocacion = true;
    vistaPrevia = vistaActual();
    t.style.display = "block";
    t.querySelectorAll(".tour-card,.tour-panel,.tour-centro").forEach((x) => x.remove());
    const card = document.createElement("div");
    card.className = "tour-card";
    card.style.visibility = "hidden";   // se mide y se coloca antes de mostrarse: nunca asoma en la esquina
    card.innerHTML = `<div class="etapa">Etapa ${etapa.n} · ${etapa.titulo}</div><h3>${paso.t}</h3><p>${paso.p}</p>
      <div class="acciones"><span class="puntos">${cola.map((_, k) => `<i class="${k === idx ? "on" : ""}"></i>`).join("")}</span>
        ${paso.demo && demoPosible(paso.demo) ? `<button class="sec" onclick="Tour.mostrar()">Muéstrame</button>` : ""}
        <button class="sec" onclick="Tour.saltar()">${modo === "guiado" ? "Salir" : "Ahora no"}</button>
        ${idx > 0 ? `<button class="sec" onclick="Tour.atras()">Anterior</button>` : ""}
        <button onclick="Tour.siguiente()">${idx === cola.length - 1 ? "Listo" : "Siguiente"}</button></div>
      <div class="tecla"><kbd>Enter</kbd> siguiente · <kbd>Esc</kbd> ${modo === "guiado" ? "salir" : "ahora no"}</div>`;
    t.appendChild(card);
    requestAnimationFrame(() => { colocar(target, card); card.style.visibility = ""; card.classList.add("lista"); });
    st.vistos[idPaso(etapa, i)] = true; guardar(); pintarCamino();
  }

  function finDeRecorrido() {
    const e = etapaActual();
    const completa = hecha(e);
    if (completa && st.etapa < ETAPAS.length - 1) {
      st.etapa++; guardar();
      const sig = ETAPAS[st.etapa];
      centro("🎉", `Etapa ${e.n} completa`, `Ya sabes ${e.titulo.toLowerCase()}. La siguiente es <b>${sig.titulo}</b>: ${sig.resumen}`,
        `<button onclick="Tour.etapa(${st.etapa})">Seguir con la etapa ${sig.n}</button><button class="sec" onclick="Tour.cerrar()">Más tarde</button>`);
      return;
    }
    if (completa) { centro("🏁", "Camino completo", "Recorriste las cinco etapas. Puedes repetir cualquiera desde Guía cuando quieras.", `<button onclick="Tour.cerrar()">Cerrar</button>`); return; }
    cerrar();
  }

  function centro(hero, titulo, texto, botones) {
    const t = el();
    t.style.display = "block";
    t.innerHTML = `<div class="tour-hole sin"></div><div class="tour-centro card"><div class="hero">${hero}</div><h2>${titulo}</h2><p>${texto}</p><div class="acciones">${botones}</div></div>`;
  }

  function bienvenida() {
    st.bienvenida = true; guardar();
    centro("👋", "Hola, te damos la bienvenida",
      "Aquí aprendes a cobrar con boletas y facturas, como cualquier negocio en Chile, practicando con una empresa de mentira. Te guío paso a paso, y puedes saltarte lo que quieras.",
      `<button onclick="Tour.etapa(0)">Empezar el recorrido</button><button class="sec" onclick="Tour.explorar()">Explorar por mi cuenta</button>`);
  }

  // Llamado al pintar cada pantalla: pasos pendientes de esa pantalla, etapa en curso.
  function alEntrar(vista) {
    pintarCamino();
    if (st.apagado || document.querySelector(".modal")) return;
    if (el().style.display === "block") {
      // Un consejo contextual anclado a otra vista no se queda flotando: se cierra al cambiar de vista.
      const actual = cola[idx];
      if (modo === "contextual" && actual && actual.etapa.pasos[actual.i].vista !== vista) cerrar();
      else return;
    }
    if (!st.bienvenida) { programar(bienvenida, 400); return; }
    const e = etapaActual();
    const pendientes = e.pasos.map((_, i) => ({ etapa: e, i })).filter(({ i }) => e.pasos[i].vista === vista && !st.vistos[idPaso(e, i)]);
    if (!pendientes.length) return;
    cola = pendientes; idx = 0; modo = "contextual";
    programar(mostrarPaso, 300);
  }

  function abrir() {
    const t = el();
    t.style.display = "block";
    t.innerHTML = `<div class="tour-hole sin"></div><div class="tour-panel card">
      <h2 style="margin:0 0 4px">Tu camino</h2><p class="mut" style="margin:0">De cero a emitir, en cinco etapas. Entra a una para recorrerla paso a paso; las ya vistas se pueden repetir.</p>
      <div class="etapas">${ETAPAS.map((e, i) => `<div class="et ${hecha(e) ? "hecha" : ""} ${i === st.etapa ? "actual" : ""}" onclick="Tour.etapa(${i})">
        <span class="n">${hecha(e) ? "✓" : e.n}</span><div><b>${e.titulo}</b><span>${e.resumen}</span></div>
        <span class="pill ${e.mundo === "real" ? "p-no" : e.mundo === "pruebas" ? "p-warn" : "p-ok"}">${e.mundo === "real" ? "real" : e.mundo === "pruebas" ? "pruebas" : "práctica"} · ${progreso(e)}/${e.pasos.length}</span></div>`).join("")}</div>
      <div style="display:flex;gap:8px;margin-top:14px;align-items:center">
        <label class="chk" style="margin:0;font-size:.86rem"><input type="checkbox" ${st.apagado ? "checked" : ""} onchange="Tour.apagar(this.checked)"> No mostrar pistas automáticas</label>
        <span style="flex:1"></span>
        <button class="sec" onclick="Tour.reiniciar()">Empezar de cero</button><button onclick="Tour.cerrar()">Cerrar</button></div></div>`;
  }

  function etapa(i) {
    const e = ETAPAS[i];
    cerrar();   // antes de armar la cola: cerrar() la vacía
    cola = e.pasos.map((_, j) => ({ etapa: e, i: j })); idx = 0; modo = "guiado";
    st.etapa = i; st.bienvenida = true; guardar();
    if (e.pasos[0].vista !== vistaActual()) { location.hash = "#" + e.pasos[0].vista; setTimeout(mostrarPaso, 400); return; }
    mostrarPaso();
  }

  // ---------- "Muéstrame": un cursor fantasma hace la acción sobre la interfaz real ----------
  // Cada demo es una lista de acciones sobre elementos reales. Escribe de verdad en los campos (el
  // formulario reacciona), pulsa de verdad (se abre el diálogo real) y al final deja todo como
  // estaba. Mientras corre, nadie puede pulsar nada; al terminar, vuelve la tarjeta y "ahora tú".
  const DEMOS = {
    monto:  [["escribir", "#c_que", "Café"], ["escribir", "#c_monto", "1190"], ["esperar", 1200]],
    emitir: [["asegurar", "#c_que", "Café"], ["asegurar", "#c_monto", "1190"], ["clic", "#c_btn"], ["modal", 1800], ["clic", ".modal button[data-i='0']"]],
    anular: [["clic", "[data-tour='anular']"], ["modal", 1800], ["clic", ".modal button[data-i='0']"]],
    mes:    [["elegir", "#m_per", 1], ["esperar", 1400], ["elegir", "#m_per", 0]],
  };
  let demoActiva = false;
  const q = (sel) => document.querySelector(sel);
  const demoPosible = (id) => (DEMOS[id] || []).every(([a, sel]) => a === "esperar" || a === "modal" || sel.startsWith(".modal") || q(sel));
  const dormir = (ms) => new Promise((r) => setTimeout(r, ms));
  const puntoDe = (el) => { const r = el.getBoundingClientRect(); return { x: r.left + Math.min(r.width / 2, 160), y: r.top + r.height / 2 }; };
  async function moverA(cur, el) {
    el.scrollIntoView({ block: "center", behavior: "instant" });
    await dormir(60);
    const { x, y } = puntoDe(el);
    cur.style.left = x + "px"; cur.style.top = y + "px";
    await dormir(720);
  }
  async function pulsar(cur, el) {
    cur.classList.add("clic"); await dormir(160); cur.classList.remove("clic");
    el.click(); await dormir(240);
  }
  function disparar(el, tipo) { el.dispatchEvent(new Event(tipo, { bubbles: true })); }
  async function correrDemo(id) {
    const pasos = DEMOS[id];
    if (!pasos || demoActiva) return;
    demoActiva = true;
    const t = el();
    t.style.display = "none";                           // la demo se ve sin recorte ni tarjeta encima
    const velo = document.createElement("div"); velo.className = "demo-velo";
    velo.innerHTML = `<div class="demo-pill">Mira cómo se hace…</div>`;
    document.body.appendChild(velo);
    const cur = document.createElement("div"); cur.className = "fantasma";
    cur.innerHTML = `<svg viewBox="0 0 24 24"><path d="M5 3l14 8-6 2-3 6z"/></svg>`;
    Object.assign(cur.style, { left: (window.innerWidth / 2) + "px", top: (window.innerHeight - 40) + "px" });
    document.body.appendChild(cur);
    const antes = [];                                    // valores que se restauran al final
    try {
      await dormir(350);
      for (const [accion, sel, arg] of pasos) {
        if (accion === "esperar") { await dormir(sel); continue; }
        if (accion === "modal") { for (let i = 0; i < 20 && !q(".modal"); i++) await dormir(100); if (q(".modal")) await dormir(sel); continue; }
        const e = q(sel);
        if (!e) continue;
        if (accion === "escribir" || accion === "asegurar") {
          if (accion === "asegurar" && e.value) continue;
          antes.push([e, e.value]);
          await moverA(cur, e);
          e.focus(); e.value = ""; disparar(e, "input");
          for (const ch of arg) { e.value += ch; disparar(e, "input"); await dormir(90); }
          await dormir(300);
        } else if (accion === "clic") {
          await moverA(cur, e); await pulsar(cur, e);
        } else if (accion === "elegir") {
          if (!antes.some(([x]) => x === e)) antes.push([e, e.value]);
          await moverA(cur, e);
          cur.classList.add("clic"); await dormir(160); cur.classList.remove("clic");
          e.selectedIndex = arg; disparar(e, "change"); await dormir(300);
        }
      }
    } finally {
      await dormir(400);
      for (const [e, v] of antes.reverse()) { if (document.contains(e)) { e.value = v; disparar(e, e.tagName === "SELECT" ? "change" : "input"); } }
      cur.remove(); velo.remove();
      demoActiva = false;
      t.style.display = "block"; mostrarPaso();
      avisar("Ahora tú: hazlo igual y sigue con Siguiente.");
    }
  }

  window.Tour = {
    mostrar() { const p = cola[idx]; if (p) correrDemo(p.etapa.pasos[p.i].demo); },
    enDemo: () => demoActiva,
    alEntrar, abrir, etapa, cerrar,
    siguiente() { idx++; mostrarPaso(); },
    atras() { idx = Math.max(0, idx - 1); mostrarPaso(); },
    // "Salir" (recorrido) cierra sin marcar nada; "Ahora no" (pista automática) además apaga las
    // pistas automáticas, que vuelven desde Guía.
    saltar() { clearTimeout(programado); cola = []; cerrar(); st.apagado = true; guardar(); avisar("Listo, sin pistas automáticas. Cuando quieras, están en Guía (arriba a la derecha)."); },
    explorar() { clearTimeout(programado); st.apagado = true; st.bienvenida = true; guardar(); cerrar(); avisar("Explora tranquilo. La guía queda en el botón Guía, arriba a la derecha."); },
    apagar(v) { st.apagado = !!v; guardar(); },
    reiniciar() { st = { vistos: {}, etapa: 0, checks: {}, apagado: false, bienvenida: false }; guardar(); cerrar(); location.hash = "#inicio"; setTimeout(bienvenida, 300); },
    etapas: ETAPAS, estado: () => st,
    check(id, v) { st.checks[id] = !!v; guardar(); },
  };
  document.addEventListener("keydown", (ev) => {
    if (el().style.display !== "block" || !cola.length) return;
    if (ev.key === "Enter" || ev.key === "ArrowRight") { ev.preventDefault(); Tour.siguiente(); }
    else if (ev.key === "ArrowLeft") { ev.preventDefault(); Tour.atras(); }
    else if (ev.key === "Escape") { ev.preventDefault(); Tour.saltar(); }
  });
  window.addEventListener("resize", () => { if (cola.length && el().style.display === "block") { primeraColocacion = true; mostrarPaso(); } });
  document.addEventListener("vista", (e) => alEntrar(e.detail));
  pintarCamino();
  if (document.getElementById("vista")?.children.length) alEntrar(vistaActual());
})();
