// Visuales de la mini academia: uno por lección, interactivo cuando se puede tocar un número.
// Todo es HTML + SVG propio, con los colores de la app (sin librerías). Cada visual es una
// función VIS[id](contenedor, ctx) que pinta y conecta sus controles. ctx.valores() entrega la
// UF y la UTM del día (desde el motor) para que los ejemplos usen cifras reales. ctx.cambio(valores) avisa a la
// lección cada vez que el alumno mueve algo (la lección escribe esos números dentro del texto), y data-parte="x"
// marca las partes que un paso puede enfocar (foco) para guiar la mirada.
window.AcademiaVis = (() => {
  const clp = (n) => "$ " + Math.round(n).toLocaleString("es-CL");
  const num = (n, d = 0) => Number(n).toLocaleString("es-CL", { minimumFractionDigits: d, maximumFractionDigits: d });
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"];
  const IVA = 0.19;

  // ---- piezas reutilizables ----
  const apilada = (segs) => `<div class="vis-apilada">${segs.filter((s) => s.v > 0).map((s) => `<div class="${s.c}" style="flex:${s.v}" ${s.k ? `data-parte="${s.k}"` : ""}><b>${s.t}</b><span>${s.s || ""}</span></div>`).join("")}</div>`;
  const slider = (id, et, min, max, val, step = 1) => `<label class="vis-sl"><span>${et} <output id="${id}_o"></output></span><input type="range" id="${id}" min="${min}" max="${max}" step="${step}" value="${val}"></label>`;
  const cifras = (items) => `<div class="vis-cifras">${items.map((i) => `<div class="${i.c || ""}" ${i.k ? `data-parte="${i.k}"` : ""}><span>${i.t}</span><b id="${i.id || ""}">${i.v}</b></div>`).join("")}</div>`;
  const toggle = (id, ops, sel = 0) => `<div class="segmento vis-tog" id="${id}">${ops.map((o, i) => `<button class="${i === sel ? "on" : ""}" data-i="${i}">${o}</button>`).join("")}</div>`;
  const onToggle = (c, id, f) => c.querySelectorAll(`#${id} button`).forEach((b) => (b.onclick = () => { c.querySelectorAll(`#${id} button`).forEach((x) => x.classList.toggle("on", x === b)); f(Number(b.dataset.i)); }));
  const onSlider = (c, id, f) => { const i = c.querySelector("#" + id); const go = () => { c.querySelector("#" + id + "_o").textContent = f(Number(i.value)); }; i.oninput = go; go(); };
  const flecha = (t = "") => `<div class="vis-flecha"><svg viewBox="0 0 24 24" width="22" height="22"><path d="M12 4v14m0 0l-6-6m6 6l6-6" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>${t ? `<span>${t}</span>` : ""}</div>`;
  const caja = (t, cuerpo, c = "") => `<div class="vis-caja ${c}"><b>${t}</b>${cuerpo ? `<div>${cuerpo}</div>` : ""}</div>`;
  const doc = ({ tipo, folio, cliente, lineas, totales, nota }) => `<div class="vis-doc"><div class="vis-doc-cab"><span>${tipo}</span><span>N° ${folio}</span></div>
    <div class="vis-doc-de">De: EMPRESA DEMO SPA · 77.777.777-7</div><div class="vis-doc-de ${cliente ? "res" : "mut"}">${cliente ? "Para: " + cliente : "Para: (sin nombre, es una boleta)"}</div>
    <table>${lineas.map((l) => `<tr><td>${l[0]}</td><td>${l[1]}</td></tr>`).join("")}</table>
    <div class="vis-doc-tot">${totales.map((t) => `<div class="${t[2] || ""}"><span>${t[0]}</span><b>${t[1]}</b></div>`).join("")}</div>${nota ? `<div class="vis-doc-nota">${nota}</div>` : ""}</div>`;

  const VIS = {};

  // 1. ¿Qué es un impuesto? — a dónde va cada peso
  VIS.impuesto = (c, ctx) => {
    c.innerHTML = `${slider("p", "Precio del jugo, sin IVA:", 500, 50000, 1000, 500)}<div id="b"></div>${flecha("el IVA no se queda en el negocio")}
      <div class="vis-fila"><div class="vis-caja neg" data-parte="neg"><b>El negocio (Sofía)</b><div>se queda con <span id="n"></span></div></div><div class="vis-caja est" data-parte="iva"><b>El Estado</b><div>recibe <span id="i"></span> para colegios · hospitales · calles · pensiones</div></div></div>`;
    onSlider(c, "p", (p) => { const i = Math.round(p * IVA); c.querySelector("#b").innerHTML = apilada([{ v: p, c: "neto", k: "neg", t: "neto " + clp(p), s: "del negocio" }, { v: i, c: "iva", k: "iva", t: "IVA " + clp(i), s: "del Estado" }]); c.querySelector("#n").textContent = clp(p); c.querySelector("#i").textContent = clp(i); ctx?.cambio?.({ neto: p, iva: i, total: p + i }); return clp(p); });
  };

  // 2. El SII y el RUT — el dígito verificador paso a paso
  VIS.sii = (c) => {
    c.innerHTML = `<label class="vis-sl"><span>Escribe un RUT (sin puntos) y mira cómo se revisa el último dígito</span><input id="r" value="12345678-5" maxlength="12" autocomplete="off" spellcheck="false"></label><div id="out"></div>`;
    const calc = (cuerpo) => { let s = 0, m = 2; for (const d of cuerpo.split("").reverse()) { s += Number(d) * m; m = m === 7 ? 2 : m + 1; } const r = 11 - (s % 11); return { s, dv: r === 11 ? "0" : r === 10 ? "K" : String(r) }; };
    const go = () => {
      const t = c.querySelector("#r").value.replace(/\./g, "").toUpperCase().trim(); const [cuerpo, dv] = t.split("-");
      if (!/^\d{7,8}$/.test(cuerpo || "")) { c.querySelector("#out").innerHTML = `<p class="mut">Escribe 7 u 8 números, un guion y el dígito final. Ejemplo: 12345678-5.</p>`; return; }
      const { s, dv: ok } = calc(cuerpo); let m = 2;
      const pasos = cuerpo.split("").reverse().map((d) => { const x = `${d}×${m}`; m = m === 7 ? 2 : m + 1; return x; });
      c.querySelector("#out").innerHTML = `<div class="vis-pasos"><div><span>1. Cada número, de derecha a izquierda, se multiplica por 2, 3, 4, 5, 6, 7 y de nuevo 2…</span><b>${pasos.join(" + ")}</b></div>
        <div><span>2. Se suman</span><b>${s}</b></div><div><span>3. Se divide por 11 y se mira el resto</span><b>resto ${s % 11}</b></div>
        <div><span>4. 11 menos el resto (11 → 0, 10 → K)</span><b>dígito verificador = ${ok}</b></div></div>
        ${dv === undefined ? `<div class="banner">Te falta el dígito al final: debería ser <b>${ok}</b>.</div>` : dv === ok ? `<div class="banner verde"><b>RUT válido.</b> El ${ok} del final calza con los números de adelante.</div>` : `<div class="banner rojo"><b>Hay un error de tipeo.</b> Con esos números, el dígito debería ser <b>${ok}</b>, no ${esc(dv)}.</div>`}`;
    };
    c.querySelector("#r").oninput = go; go();
  };

  // 3 y 6. La calculadora del IVA (desde el neto o desde el total)
  const calculadora = (c, modo, ctx) => {
    c.innerHTML = `${toggle("m", ["Sé el precio sin IVA (neto)", "Sé el precio con IVA (total)"], modo)}<div id="s"></div><div id="b"></div><div id="k"></div>`;
    const pinta = (m) => {
      c.querySelector("#s").innerHTML = m === 0 ? slider("v", "Neto:", 1000, 100000, 10000, 500) : slider("v", "Total que paga el cliente:", 1190, 119000, 11900, 100);
      onSlider(c, "v", (v) => { const neto = m === 0 ? v : Math.round(v / (1 + IVA)); const iva = m === 0 ? Math.round(neto * IVA) : v - neto; const total = neto + iva;
        c.querySelector("#b").innerHTML = apilada([{ v: neto, c: "neto", k: "neto", t: "neto", s: clp(neto) }, { v: iva, c: "iva", k: "iva", t: "IVA 19 %", s: clp(iva) }]);
        c.querySelector("#k").innerHTML = cifras([{ t: "Neto", v: clp(neto), k: "neto" }, { t: "IVA", v: clp(iva), c: "iva", k: "iva" }, { t: "Total", v: clp(total), c: "tot", k: "total" }]);
        ctx?.cambio?.({ neto, iva, total });
        c.querySelector("#k").innerHTML += `<p class="mut">${m === 0 ? `IVA = ${num(neto)} × 0,19 = ${num(iva)}. Total = ${num(neto)} + ${num(iva)} = ${num(total)}.` : `Neto = ${num(v)} ÷ 1,19 = ${num(neto)}. IVA = ${num(v)} − ${num(neto)} = ${num(iva)}.`}</p>`;
        return clp(v); });
    };
    onToggle(c, "m", pinta); pinta(modo);
  };
  VIS.iva = (c, ctx) => calculadora(c, 0, ctx);
  VIS["neto-total"] = (c, ctx) => calculadora(c, 1, ctx);

  // 4. Boleta o factura — el mismo café, dos documentos
  VIS["boleta-factura"] = (c) => {
    c.innerHTML = `${toggle("q", ["Compra una persona", "Compra una empresa"])}<div id="d"></div>`;
    c.querySelectorAll("#q button").forEach((b, i) => b.setAttribute("data-parte", i === 0 ? "boleta" : "factura"));
    const pinta = (i) => { c.querySelector("#d").setAttribute("data-parte", i === 0 ? "boleta" : "factura"); c.querySelector("#d").innerHTML = i === 0
      ? doc({ tipo: "BOLETA ELECTRÓNICA", folio: 12, cliente: "", lineas: [["10 jugos", clp(11900)]], totales: [["Total", clp(11900), "tot"]], nota: "La boleta no lleva el nombre de quien compra y muestra solo el total (el IVA va incluido)." })
      : doc({ tipo: "FACTURA ELECTRÓNICA", folio: 12, cliente: "CLIENTE DEMO SPA · 76.111.111-6", lineas: [["10 jugos", clp(10000)]], totales: [["Neto", clp(10000)], ["IVA 19 %", clp(1900), "iva"], ["Total", clp(11900), "tot"]], nota: "<b>La empresa que compra podrá descontar los $ 1.900 de IVA</b> de lo que ella cobró a sus clientes. Por eso la factura lleva su RUT y el IVA aparte." }); };
    onToggle(c, "q", pinta); pinta(0);
  };

  // 5. Con IVA o sin IVA — toca cada cosa
  VIS.exento = (c) => {
    const items = [["Cuaderno", 1], ["Clase de guitarra", 0], ["Café", 1], ["Consulta médica", 0], ["Polera", 1], ["Arriendo de una casa", 0], ["Entrada al cine", 1], ["Pasaje en bus", 0]];
    c.innerHTML = `<p class="mut">Toca cada cosa. Todas valen $ 10.000 antes de impuestos.</p><div class="vis-chips">${items.map((x, i) => `<button data-i="${i}">${x[0]}</button>`).join("")}</div><div id="d"></div>`;
    const pinta = (i) => { const [n, af] = items[i]; c.querySelectorAll(".vis-chips button").forEach((b, j) => b.classList.toggle("on", j === i));
      c.querySelector("#d").innerHTML = `<div class="vis-fila"><div class="vis-caja ${af ? "iva" : "ok"}"><b>${n}: ${af ? "afecto a IVA" : "exento de IVA"}</b><div>${af ? "Lleva el 19 %. Es la regla general: casi todo lo que se vende." : "No lleva IVA. La ley exime educación, salud, arriendo de viviendas, transporte de pasajeros, entre otros."}</div></div>
        <div>${doc({ tipo: af ? "BOLETA ELECTRÓNICA" : "BOLETA EXENTA", folio: 3, lineas: [[n, clp(10000)]], totales: af ? [["Neto", clp(10000)], ["IVA", clp(1900), "iva"], ["Total", clp(11900), "tot"]] : [["Exento", clp(10000)], ["IVA", clp(0)], ["Total", clp(10000), "tot"]] })}</div></div>`; };
    c.querySelectorAll(".vis-chips button").forEach((b) => (b.onclick = () => pinta(Number(b.dataset.i)))); pinta(0);
  };

  // 7. UF y UTM — convertidor con los valores de hoy
  VIS["uf-utm"] = async (c, ctx) => {
    let v = { uf: 41000, utm: 70000, hoy: false }; try { const r = await ctx.valores(); const n = (x) => Number(x && typeof x === "object" ? x.valor : x); if (r && n(r.uf) > 0 && n(r.utm) > 0) v = { uf: n(r.uf), utm: n(r.utm), hoy: true }; } catch {}
    c.innerHTML = `<div class="vis-cifras"><div><span>UF ${v.hoy ? "hoy" : "(aprox.)"}</span><b>${clp(v.uf)}</b><small>cambia todos los días</small></div><div><span>UTM ${v.hoy ? "este mes" : "(aprox.)"}</span><b>${clp(v.utm)}</b><small>cambia una vez al mes</small></div></div>
      ${slider("u", "Un arriendo de", 1, 100, 10)}<p class="mut" id="ut"></p>${slider("t", "Una multa de", 1, 20, 1, 0.5)}<p class="mut" id="tt"></p>
      <svg viewBox="0 0 320 110" class="vis-svg"><path d="M10 95 C 60 90, 90 80, 130 70 S 220 45, 310 20" fill="none" stroke="var(--acc)" stroke-width="3" stroke-linecap="round"/><path d="M10 95 L310 95" stroke="var(--bd-2)"/><text x="12" y="108" fill="currentColor" font-size="10">hace 10 años</text><text x="262" y="108" fill="currentColor" font-size="10">hoy</text><text x="150" y="40" fill="currentColor" font-size="11">la UF sube con la inflación (esquema)</text></svg>`;
    onSlider(c, "u", (n) => { c.querySelector("#ut").textContent = `${num(n)} UF = ${clp(n * v.uf)} hoy. El próximo año serán más pesos, pero las mismas ${num(n)} UF.`; return num(n) + " UF"; });
    onSlider(c, "t", (n) => { c.querySelector("#tt").textContent = `${num(n, 1)} UTM = ${clp(n * v.utm)} este mes.`; return num(n, 1) + " UTM"; });
  };

  // 8. Lo que cobras y lo que pagas — la balanza
  VIS["debito-credito"] = (c) => {
    c.innerHTML = `${slider("v", "Vendiste (neto) por", 0, 2000000, 500000, 50000)}${slider("k", "Compraste con factura (neto) por", 0, 2000000, 300000, 50000)}<svg viewBox="0 0 320 130" class="vis-svg" id="bal"></svg><div id="r"></div>`;
    let V = 500000, K = 300000;
    const pinta = () => { const d = V * IVA, k = K * IVA, dif = d - k, ang = Math.max(-12, Math.min(12, (dif / 100000) * 2));
      c.querySelector("#bal").innerHTML = `<g transform="translate(160 60) rotate(${-ang})"><rect x="-130" y="-3" width="260" height="6" rx="3" fill="var(--bd-2)"/><g transform="translate(-110 0)"><rect x="-38" y="6" width="76" height="40" rx="8" fill="var(--warn-soft)"/><text x="0" y="24" text-anchor="middle" font-size="10" fill="currentColor">IVA cobrado</text><text x="0" y="39" text-anchor="middle" font-size="11" font-weight="700" fill="currentColor">${clp(d)}</text></g><g transform="translate(110 0)"><rect x="-38" y="6" width="76" height="40" rx="8" fill="var(--ok-soft)"/><text x="0" y="24" text-anchor="middle" font-size="10" fill="currentColor">IVA pagado</text><text x="0" y="39" text-anchor="middle" font-size="11" font-weight="700" fill="currentColor">${clp(k)}</text></g></g><path d="M160 60 L140 120 L180 120 Z" fill="var(--bd-2)"/>`;
      c.querySelector("#r").innerHTML = dif >= 0 ? `<div class="banner"><b>Pagas ${clp(dif)}</b> en el F29: ${num(d)} cobrados − ${num(k)} pagados.</div>` : `<div class="banner verde"><b>Remanente de ${clp(-dif)} a tu favor:</b> pagaste más IVA del que cobraste; se descuenta el mes siguiente.</div>`; };
    onSlider(c, "v", (x) => { V = x; pinta(); return clp(x); }); onSlider(c, "k", (x) => { K = x; pinta(); return clp(x); });
  };

  // 9. El F29 — elige un mes y mira cuándo se declara
  VIS.f29 = (c) => {
    c.innerHTML = `<p class="mut">Toca el mes en que vendiste:</p><div class="vis-chips" id="m">${MESES.map((x, i) => `<button data-i="${i}">${x}</button>`).join("")}</div><div id="d"></div>`;
    const pinta = (i) => { const s = (i + 1) % 12; c.querySelectorAll("#m button").forEach((b, j) => b.classList.toggle("on", j === i));
      c.querySelector("#d").innerHTML = `<div class="vis-linea"><div class="vis-caja"><b>${MESES[i]}</b><div>vendes y compras; cada documento va al SII</div></div>${flecha()}<div class="vis-cal"><b>${MESES[s]}</b><div class="vis-dias">${Array.from({ length: 30 }, (_, k) => `<span class="${k + 1 === 12 ? "d12" : k + 1 === 20 ? "d20" : ""}">${k + 1}</span>`).join("")}</div><p class="mut"><span class="pill p-warn">12</span> plazo general · <span class="pill p-ok">20</span> por internet con pago, quien emite electrónicamente</p></div></div>
        <div class="banner">El F29 de <b>${MESES[i]}</b> se presenta en <b>${MESES[s]}</b>. Si no vendiste nada, igual: "sin movimiento".</div>`; };
    c.querySelectorAll("#m button").forEach((b) => (b.onclick = () => pinta(Number(b.dataset.i)))); pinta(new Date().getMonth());
  };

  // 10. El PPM — doce frascos y el ajuste de abril
  VIS.ppm = (c) => {
    c.innerHTML = `${slider("v", "Ventas netas de cada mes:", 0, 5000000, 1000000, 100000)}<div id="f" class="vis-frascos"></div>${slider("a", "Impuesto a la renta que resultó en abril:", 0, 200000, 20000, 5000)}<div id="r"></div>`;
    let V = 1000000, A = 20000; const tasa = 0.0025;
    const pinta = () => { const m = Math.round(V * tasa), an = m * 12;
      c.querySelector("#f").innerHTML = MESES.map((x) => `<div><div class="vis-frasco"><div style="height:${Math.min(100, (m / 12500) * 100)}%"></div></div><small>${x.slice(0, 3)}</small></div>`).join("") + `<div class="vis-frasco-t">PPM: <b>${clp(m)}</b> al mes (0,25 % de las ventas) → <b>${clp(an)}</b> en el año</div>`;
      const dif = an - A; c.querySelector("#r").innerHTML = dif >= 0 ? `<div class="banner verde">En abril el impuesto fue ${clp(A)} y ya adelantaste ${clp(an)}: <b>te devuelven ${clp(dif)}</b>.</div>` : `<div class="banner">En abril el impuesto fue ${clp(A)} y adelantaste ${clp(an)}: <b>pagas la diferencia, ${clp(-dif)}</b>.</div>`; };
    onSlider(c, "v", (x) => { V = x; pinta(); return clp(x); }); onSlider(c, "a", (x) => { A = x; pinta(); return clp(x); });
  };

  // 11. La renta — ventas, gastos y ganancia
  VIS.renta = (c) => {
    c.innerHTML = `${slider("v", "Vendiste en el año:", 0, 30000000, 12000000, 500000)}${slider("g", "Gastaste en el negocio (mercadería, arriendo, sueldos):", 0, 30000000, 10000000, 500000)}<svg viewBox="0 0 320 150" class="vis-svg" id="w"></svg><div id="r"></div>`;
    let V = 12000000, G = 10000000;
    const pinta = () => { const gan = V - G, max = Math.max(V, G, 1), h = (x) => (x / max) * 100;
      c.querySelector("#w").innerHTML = `<g font-size="10" fill="currentColor"><rect x="30" y="${120 - h(V)}" width="60" height="${h(V)}" rx="6" fill="var(--acc-soft)" stroke="var(--acc)"/><text x="60" y="135" text-anchor="middle">ventas</text><text x="60" y="${115 - h(V)}" text-anchor="middle" font-weight="700">${num(V / 1e6, 1)} M</text>
        <rect x="130" y="${120 - h(Math.min(G, V))}" width="60" height="${h(Math.min(G, V))}" rx="6" fill="var(--no-soft)" stroke="var(--no)"/><text x="160" y="135" text-anchor="middle">gastos</text><text x="160" y="${115 - h(Math.min(G, V))}" text-anchor="middle" font-weight="700">−${num(G / 1e6, 1)} M</text>
        <rect x="230" y="${120 - h(Math.max(gan, 0))}" width="60" height="${h(Math.max(gan, 0))}" rx="6" fill="var(--ok-soft)" stroke="var(--ok)"/><text x="260" y="135" text-anchor="middle">ganancia</text><text x="260" y="${115 - h(Math.max(gan, 0))}" text-anchor="middle" font-weight="700">${gan > 0 ? num(gan / 1e6, 1) + " M" : "0"}</text></g>`;
      c.querySelector("#r").innerHTML = gan > 0 ? `<div class="banner">El impuesto a la renta se calcula sobre la <b>ganancia de ${clp(gan)}</b>, no sobre los ${clp(V)} vendidos.</div>` : `<div class="banner verde"><b>No hubo ganancia:</b> no se paga impuesto a la renta ese año (el IVA del mes sí se declara igual).</div>`; };
    onSlider(c, "v", (x) => { V = x; pinta(); return clp(x); }); onSlider(c, "g", (x) => { G = x; pinta(); return clp(x); });
  };

  // 12. ¿Persona natural o empresa? — la pared entre tú y el negocio
  VIS["persona-o-empresa"] = (c) => {
    c.innerHTML = `${toggle("t", ["Emito con mi RUT", "Creo una empresa"])}<div id="d"></div>`;
    const pinta = (i) => { c.querySelector("#d").innerHTML = i === 0
      ? `<div class="vis-fila"><div class="vis-caja per grande"><b>Tú · 12.345.678-5</b><div class="vis-cosas"><span>el negocio</span><span>tu casa</span><span>tus ahorros</span><span>las deudas del negocio</span></div><div class="mut">Todo en una sola persona: lo que gana el negocio es tuyo y lo que debe, también.</div></div></div>`
      : `<div class="vis-fila pared"><div class="vis-caja per"><b>Tú · 12.345.678-5</b><div class="vis-cosas"><span>tu casa</span><span>tus ahorros</span></div></div><div class="vis-pared"></div><div class="vis-caja emp"><b>EMPRESA DEMO SPA · 77.777.777-7</b><div class="vis-cosas"><span>el negocio</span><span>sus deudas</span><span>sus socios</span></div></div></div><p class="mut">La empresa es otra persona ante la ley, con su propio RUT. Lo suyo y lo tuyo quedan separados (con límites que la ley fija).</p>`; };
    onToggle(c, "t", pinta); pinta(0);
  };

  // 13. SpA, EIRL, Ltda., S.A. — dos preguntas y una recomendación
  VIS["tipos-empresa"] = (c) => {
    c.innerHTML = `<p class="mut">Dos preguntas:</p>${toggle("d", ["Un solo dueño", "Dos o más"])}${toggle("s", ["Podrían entrar socios después", "No va a cambiar"])}<div id="r"></div>
      <table class="vis-tabla"><tr><th></th><th>EIRL</th><th>SpA</th><th>Ltda.</th><th>S.A.</th></tr><tr><td>Dueños</td><td>1</td><td>1 o más</td><td>2 o más</td><td>muchos</td></tr><tr><td>Sumar o cambiar socios</td><td>no se puede</td><td>fácil</td><td>notario</td><td>fácil</td></tr><tr><td>Para quién</td><td>una persona sola</td><td>emprender</td><td>socios fijos</td><td>empresas grandes</td></tr></table>`;
    let D = 0, S = 0; const pinta = () => { const t = D === 0 && S === 1 ? ["EIRL o SpA", "Con un solo dueño y sin planes de socios, las dos sirven; la SpA deja la puerta abierta igual."] : D === 0 ? ["SpA", "Un solo dueño hoy, socios mañana: la SpA lo permite sin rehacer la empresa."] : S === 0 ? ["SpA", "Con varios dueños que pueden cambiar, la SpA es la más flexible."] : ["SpA o Ltda.", "Socios fijos: sirven las dos; la Ltda. exige notario para cualquier cambio, la SpA no."];
      c.querySelector("#r").innerHTML = `<div class="banner verde"><b>Lo que suele convenir: ${t[0]}.</b> ${t[1]} Es una guía, no un consejo legal: confírmalo con quien te asesore.</div>`; };
    onToggle(c, "d", (i) => { D = i; pinta(); }); onToggle(c, "s", (i) => { S = i; pinta(); }); pinta();
  };

  // 14. Regímenes — por dónde pasa el impuesto
  VIS.regimenes = (c) => {
    c.innerHTML = `${toggle("r", ["Pro-PYME General", "Pro-PYME Transparente"])}<div id="d"></div>`;
    const pinta = (i) => { c.querySelector("#d").innerHTML = i === 0
      ? `<div class="vis-linea"><div class="vis-caja emp"><b>Empresa</b><div>gana $ 10 M</div></div>${flecha("paga su impuesto")}<div class="vis-caja iva"><b>SII</b><div>impuesto de la empresa</div></div>${flecha("lo que retira")}<div class="vis-caja per"><b>Dueño</b><div>paga por lo que retiró (con lo ya pagado a favor)</div></div></div><p class="mut">Conviene si la ganancia se queda en la empresa para reinvertir.</p>`
      : `<div class="vis-linea"><div class="vis-caja emp"><b>Empresa</b><div>gana $ 10 M · no paga impuesto propio</div></div>${flecha("toda la ganancia")}<div class="vis-caja per"><b>Dueño</b><div>la declara como suya</div></div>${flecha("una sola vez")}<div class="vis-caja iva"><b>SII</b><div>impuesto de la persona, por tramos</div></div></div><p class="mut">Conviene si el dueño retira casi toda la ganancia: se declara una vez, como persona.</p>`; };
    onToggle(c, "r", pinta); pinta(0);
  };

  // 15. Inicio de actividades y giro — la línea de tiempo y el código
  VIS["inicio-actividades"] = (c) => {
    const giros = [["561000", "Restaurantes y cafés", 1, "boletas y facturas con IVA"], ["471100", "Almacenes y minimarkets", 1, "boletas con IVA"], ["854900", "Enseñanza (clases particulares)", 0, "boletas exentas"], ["741001", "Diseño y servicios profesionales", 1, "facturas con IVA (o honorarios)"], ["681011", "Arriendo de inmuebles", 0, "facturas exentas"]];
    c.innerHTML = `<div class="vis-linea"><div class="vis-caja ok"><b>Primera venta</b><div>día 0</div></div><div class="vis-plazo"><span>hasta 2 meses</span></div><div class="vis-caja iva"><b>Inicio de actividades</b><div>en sii.cl, gratis</div></div></div>
      <p class="mut" style="margin-top:12px">Toca un giro y mira su código de 6 cifras y qué documentos lleva:</p><div class="vis-chips" id="g">${giros.map((x, i) => `<button data-i="${i}">${x[1]}</button>`).join("")}</div><div id="d"></div>`;
    const pinta = (i) => { const g = giros[i]; c.querySelectorAll("#g button").forEach((b, j) => b.classList.toggle("on", j === i));
      c.querySelector("#d").innerHTML = `<div class="vis-codigo"><b>${g[0]}</b><span>código de actividad</span></div><div class="vis-fila"><div class="vis-caja ${g[2] ? "iva" : "ok"}"><b>${g[2] ? "Afecto a IVA" : "Exento de IVA"}</b><div>emite ${g[3]}</div></div></div>`; };
    c.querySelectorAll("#g button").forEach((b) => (b.onclick = () => pinta(Number(b.dataset.i)))); pinta(0);
  };

  // 16. Clave tributaria y certificado — qué abre cada llave
  VIS.claves = (c) => {
    const llave = (col) => `<svg viewBox="0 0 24 24" width="26" height="26"><circle cx="8" cy="12" r="4" fill="none" stroke="${col}" stroke-width="2"/><path d="M12 12h9m-3 0v3m-3-3v2" fill="none" stroke="${col}" stroke-width="2" stroke-linecap="round"/></svg>`;
    c.innerHTML = `<div class="vis-fila"><button class="vis-llave" data-k="0">${llave("var(--acc)")}<b>Clave tributaria</b><small>te la da el SII · es una contraseña</small></button><button class="vis-llave" data-k="1">${llave("var(--ok)")}<b>Certificado digital</b><small>lo compras · es un archivo con su clave</small></button></div><div class="vis-puertas" id="p"></div>`;
    const puertas = [["Entrar a sii.cl", 0], ["Declarar el F29 y el F22", 0], ["Usar el sistema gratuito del SII", 0], ["Pedir folios", 0], ["Firmar una boleta o factura electrónica", 1], ["Firmar el envío al SII", 1]];
    const pinta = (k) => { c.querySelectorAll(".vis-llave").forEach((b) => b.classList.toggle("on", Number(b.dataset.k) === k)); c.querySelector("#p").innerHTML = puertas.map((p) => `<div class="${p[1] === k ? "abre" : ""}">${p[1] === k ? "🔓" : "🔒"} ${p[0]}</div>`).join(""); };
    c.querySelectorAll(".vis-llave").forEach((b) => (b.onclick = () => pinta(Number(b.dataset.k)))); pinta(0);
  };

  // 17. El calendario tributario — el año de un vistazo
  VIS.calendario = (c) => {
    const items = (i) => [["F29 del mes anterior", "hasta el 12 (20 por internet)", "warn"], ...(i === 2 ? [["Declaraciones juradas", "las empresas informan sueldos, retiros y otros datos", "mut"]] : []), ...(i === 3 ? [["F22: Operación Renta", "el impuesto a la renta del año anterior", "no"]] : [])];
    c.innerHTML = `<div class="vis-anio">${MESES.map((m, i) => `<button data-i="${i}"><b>${m.slice(0, 3)}</b><span class="dots">${items(i).map((x) => `<i class="${x[2]}"></i>`).join("")}</span></button>`).join("")}</div><div id="d"></div><p class="mut"><i class="vis-dot warn"></i> cada mes: F29 · <i class="vis-dot mut"></i> marzo: declaraciones juradas · <i class="vis-dot no"></i> abril: F22</p>`;
    const pinta = (i) => { c.querySelectorAll(".vis-anio button").forEach((b, j) => b.classList.toggle("on", j === i)); c.querySelector("#d").innerHTML = `<div class="vis-caja"><b>${MESES[i][0].toUpperCase() + MESES[i].slice(1)}</b>${items(i).map((x) => `<div><span class="pill p-${x[2] === "warn" ? "warn" : x[2] === "no" ? "no" : "mut"}">${x[0]}</span> ${x[1]}</div>`).join("")}<div class="mut">Y todos los días: emitir, y el resumen de boletas que la app manda sola.</div></div>`; };
    c.querySelectorAll(".vis-anio button").forEach((b) => (b.onclick = () => pinta(Number(b.dataset.i)))); pinta(new Date().getMonth());
  };

  // 18. Honorarios — lo que te pagan y lo que queda retenido
  VIS.honorarios = (c) => {
    const tasa = 0.1525;
    c.innerHTML = `${slider("m", "Boleta de honorarios por", 50000, 2000000, 100000, 10000)}<div id="b"></div><div id="k"></div><p class="mut">La retención sube un poco cada año por ley; en 2026 es 15,25 %. Es un adelanto del impuesto anual y de tus cotizaciones, no un cobro extra.</p>`;
    onSlider(c, "m", (m) => { const r = Math.round(m * tasa), l = m - r; c.querySelector("#b").innerHTML = apilada([{ v: l, c: "neto", t: "te pagan", s: clp(l) }, { v: r, c: "iva", t: "retenido", s: clp(r) }]); c.querySelector("#k").innerHTML = cifras([{ t: "Boleta", v: clp(m) }, { t: "Retención 15,25 %", v: clp(r), c: "iva" }, { t: "Recibes", v: clp(l), c: "tot" }]); return clp(m); });
  };

  // 19. Si te atrasas — cuánto crece el problema
  VIS.multas = (c) => {
    c.innerHTML = `${slider("d", "Meses de atraso del F29:", 0, 12, 0)}<div class="vis-termo"><div id="t"></div></div><div id="r"></div>`;
    onSlider(c, "d", (m) => { const t = c.querySelector("#t"); t.style.width = `${(m / 12) * 100}%`; t.className = m === 0 ? "ok" : m <= 1 ? "warn" : m <= 3 ? "warn2" : "no";
      c.querySelector("#r").innerHTML = m === 0 ? `<div class="banner verde"><b>A tiempo.</b> Nada que pagar de más.</div>` : m <= 1 ? `<div class="banner"><b>Un mes tarde:</b> multa pequeña más un mes de intereses. Se presenta igual y listo.</div>` : m <= 3 ? `<div class="banner"><b>${m} meses:</b> la multa y los intereses crecen cada mes, y el SII ya mandó avisos.</div>` : `<div class="banner rojo"><b>${m} meses sin presentar:</b> además de multa e intereses, el SII puede bloquear la emisión de documentos. Lo primero es presentar todo lo pendiente.</div>`; return m === 0 ? "ninguno" : m === 1 ? "1 mes" : m + " meses"; });
  };

  // 20. El folio y el timbre — emite y mira cómo se gastan
  VIS.folio = (c) => {
    let desde = 1, usados = [], anuladas = new Set(), nc = 0;
    const pinta = () => { const libres = 5 - usados.filter((u) => u >= desde).length;
      c.innerHTML = `<p class="mut">El SII te autorizó los folios <b>${desde} al ${desde + 4}</b> (un CAF de 5). Emite y mira qué pasa:</p><div class="vis-slots">${Array.from({ length: 5 }, (_, k) => { const n = desde + k, u = usados.includes(n); return `<div class="${u ? (anuladas.has(n) ? "anulada" : "usado") : ""}"><b>N° ${n}</b><span>${u ? (anuladas.has(n) ? "anulada" : "emitida") : "libre"}</span></div>`; }).join("")}</div>
        <div class="row" style="margin-top:10px"><button id="e" ${libres ? "" : "disabled"}>Emitir boleta</button><button class="sec" id="a" ${usados.some((u) => !anuladas.has(u)) ? "" : "disabled"}>Me equivoqué en la última</button><button class="sec" id="p" ${libres ? "disabled" : ""}>Pedir 5 folios más</button></div>
        <div id="h" class="vis-hist">${usados.map((u) => `<div>Boleta N° ${u}${anuladas.has(u) ? ` → anulada con nota de crédito N° ${[...anuladas].indexOf(u) + 1} (otro documento, otro folio)` : ""}</div>`).join("")}</div>
        ${!libres ? `<div class="banner">Se acabaron. Un folio usado no vuelve, ni siquiera el de una boleta anulada. Pide más: el siguiente rango parte en ${desde + 5}.</div>` : ""}`;
      c.querySelector("#e").onclick = () => { const n = desde + usados.filter((u) => u >= desde).length; usados.push(n); pinta(); };
      c.querySelector("#a").onclick = () => { const u = [...usados].reverse().find((x) => !anuladas.has(x)); anuladas.add(u); nc++; pinta(); };
      c.querySelector("#p").onclick = () => { desde += 5; pinta(); }; };
    pinta();
  };

  // 21. Nota de crédito y de débito — la historia de la factura 12
  VIS.notas = (c) => {
    let docs = [["Factura N° 12", 119000, "doc"]];
    const pinta = () => { const total = docs.reduce((s, d) => s + d[1], 0);
      c.innerHTML = `<div class="vis-hist">${docs.map((d) => `<div class="${d[2]}"><span>${d[0]}</span><b>${d[1] < 0 ? "−" : "+"} ${clp(Math.abs(d[1]))}</b></div>`).join("")}<div class="tot"><span>Lo que vale la venta hoy</span><b>${clp(total)}</b></div></div>
        <div class="row" style="margin-top:10px"><button class="sec" id="nc" ${docs.length > 1 && docs[1][2] === "nc" ? "disabled" : ""}>El cliente devolvió la mitad</button><button class="sec" id="nd" ${docs.some((d) => d[0].startsWith("Nota de débito")) ? "disabled" : ""}>Faltó cobrar el despacho ($ 5.950)</button><button class="sec" id="r">Empezar de nuevo</button></div>
        <p class="mut">La factura 12 nunca se borra ni se edita. Cada corrección es otro documento que la nombra.</p>`;
      c.querySelector("#nc").onclick = () => { docs.push(["Nota de crédito N° 4 → factura 12", -59500, "nc"]); pinta(); };
      c.querySelector("#nd").onclick = () => { docs.push(["Nota de débito N° 2 → factura 12", 5950, "nd"]); pinta(); };
      c.querySelector("#r").onclick = () => { docs = [docs[0]]; pinta(); }; };
    pinta();
  };

  // 22. El Registro de Compras y Ventas — cómo se arma la propuesta
  VIS.rcv = (c) => {
    let ventas = [], compras = [];
    const pinta = () => { const d = ventas.reduce((s, v) => s + v, 0) * IVA, k = compras.reduce((s, v) => s + v, 0) * IVA;
      c.innerHTML = `<div class="row"><button id="v">Emito una venta ($ 50.000 + IVA)</button><button class="sec" id="k">Recibo una factura de compra ($ 30.000 + IVA)</button></div>
        <div class="vis-linea" style="margin-top:12px"><div class="vis-caja"><b>Tus documentos</b><div>${ventas.length} venta(s) · ${compras.length} compra(s)</div></div>${flecha("llegan solos")}<div class="vis-caja iva"><b>SII: Registro de Compras y Ventas</b><div>ventas netas ${clp(ventas.reduce((s, v) => s + v, 0))}<br>compras netas ${clp(compras.reduce((s, v) => s + v, 0))}</div></div>${flecha("de ahí sale")}<div class="vis-caja ok"><b>Propuesta de F29</b><div>IVA cobrado ${clp(d)}<br>IVA pagado ${clp(k)}<br><b>${d - k >= 0 ? "a pagar " + clp(d - k) : "remanente " + clp(k - d)}</b></div></div></div>
        <p class="mut">Tú revisas que la propuesta tenga todo. Una factura de compra que no corresponde se reclama dentro de 8 días.</p>`;
      c.querySelector("#v").onclick = () => { ventas.push(50000); pinta(); }; c.querySelector("#k").onclick = () => { compras.push(30000); pinta(); }; };
    pinta();
  };

  // 23. Gratuito o motor propio — según cuánto emites
  VIS["gratuito-propio"] = (c) => {
    c.innerHTML = `${slider("n", "Documentos que emites al mes:", 1, 500, 10)}<div class="vis-fila" id="d"></div>`;
    onSlider(c, "n", (n) => { const g = n <= 60, p = n >= 200;
      c.querySelector("#d").innerHTML = `<div class="vis-caja ${g ? "ok on" : ""}"><b>Sistema gratuito del SII</b><div>en sii.cl con la clave tributaria; Faro lo opera por ti y guarda los PDF</div><div class="mut">para pocos documentos, sin instalar nada</div></div><div class="vis-caja ${p ? "ok on" : ""}"><b>Motor propio (Faro)</b><div>pide folios, firma con tu certificado, envía; se conecta con tu caja</div><div class="mut">para mucho volumen o integración; primero certificar</div></div>` + (!g && !p ? `<p class="mut" style="width:100%">Entre medio, cualquiera de los dos sirve: parte con el gratuito y cambia cuando te quede chico.</p>` : "");
      return n === 500 ? "500 o más" : String(n); });
  };

  return { montar(id, c, ctx) { const f = VIS[id]; if (!f) { c.remove(); return; } try { f(c, ctx); } catch (e) { c.innerHTML = `<p class="mut">No se pudo mostrar este visual (${esc(e.message || e)}).</p>`; } }, ids: () => Object.keys(VIS) };
})();
