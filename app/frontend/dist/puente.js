// Puente navegador ↔ motor. La misma interfaz corre en dos envases: la app instalada (Wails
// define window.go con los bindings del cascarón) y el navegador, servida por el propio motor
// en /app. Si no hay cascarón, este archivo define los mismos bindings sobre HTTP, con inicio
// de sesión por usuario y clave del motor (JWT en sessionStorage: muere al cerrar la pestaña).
// Lo que solo existe en la app (firmar con el núcleo Go, operar el SII engine en el propio
// proceso, guardar archivos en una carpeta elegida) avisa que hace falta la app instalada.
(() => {
  if (window.go?.main?.App) return;   // estamos dentro de la app: nada que hacer
  const origen = location.origin;
  let token = "";
  try { token = sessionStorage.getItem("dte.jwt") || ""; } catch {}

  async function pedirLogin() {
    return new Promise((resolve) => {
      const m = document.createElement("div");
      m.className = "modal";
      m.innerHTML = `<div class="card" style="max-width:420px;width:92%">
        <h2 style="margin-top:0">Entrar al motor</h2>
        <p class="mut">Estás usando DTE Chile en el navegador. Entra con el usuario y la clave del motor (los mismos del panel web).</p>
        <label>Usuario</label><input id="l_u" value="admin" autocomplete="username">
        <label>Clave</label><input id="l_p" type="password" autocomplete="current-password">
        <p class="no" id="l_err" style="display:none;margin:8px 0 0"></p>
        <div class="row"><button id="l_ok">Entrar</button></div></div>`;
      document.body.appendChild(m);
      const intentar = async () => {
        const r = await fetch(origen + "/api/v1/auth/login", { method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ username: m.querySelector("#l_u").value.trim(), password: m.querySelector("#l_p").value }) });
        if (!r.ok) { const e = m.querySelector("#l_err"); e.textContent = "Usuario o clave incorrectos."; e.style.display = "block"; return; }
        const d = await r.json();
        token = d.access_token;
        try { sessionStorage.setItem("dte.jwt", token); } catch {}
        m.remove(); resolve(token);
      };
      m.querySelector("#l_ok").onclick = intentar;
      m.querySelector("#l_p").addEventListener("keydown", (e) => { if (e.key === "Enter") intentar(); });
      setTimeout(() => m.querySelector("#l_p").focus(), 50);
    });
  }

  async function llamar(metodo, ruta, cuerpo) {
    if (!token) await pedirLogin();
    const r = await fetch(origen + ruta, { method: metodo, headers: { Authorization: "Bearer " + token, ...(cuerpo ? { "Content-Type": "application/json" } : {}), Accept: "application/json" }, body: cuerpo || undefined });
    if (r.status === 401) { token = ""; try { sessionStorage.removeItem("dte.jwt"); } catch {} await pedirLogin(); return llamar(metodo, ruta, cuerpo); }
    return r;
  }
  const soloApp = (que) => { throw new Error(`${que} solo está disponible en la app instalada (DTE Chile.app). En el navegador puedes practicar, ver documentos, Mi mes, Valores y Aprender.`); };

  window.go = { main: { App: {
    async Estado() {
      let version = "", ambiente = "";
      try { const r = await fetch(origen + "/"); const d = await r.json(); version = d.version || ""; ambiente = d.ambiente_sii || ""; } catch {}
      return { listo: true, error: "", url: origen, ambiente, version, externo: true, empaquetado: false, clave_admin: "", raiz: "", log: "" };
    },
    async API(metodo, ruta, cuerpo) { const r = await llamar(metodo, ruta, cuerpo); return { status: r.status, cuerpo: await r.text() }; },
    async Bytes(ruta) {
      const r = await llamar("GET", ruta, "");
      if (!r.ok) throw new Error("No se pudo leer " + ruta);
      const buf = new Uint8Array(await r.arrayBuffer());
      let s = ""; for (let i = 0; i < buf.length; i += 0x8000) s += String.fromCharCode.apply(null, buf.subarray(i, i + 0x8000));
      return btoa(s);
    },
    async Guardar(ruta, nombre) {
      const r = await llamar("GET", ruta, "");
      if (!r.ok) throw new Error("No se pudo descargar " + ruta);
      const url = URL.createObjectURL(await r.blob());
      const a = Object.assign(document.createElement("a"), { href: url, download: nombre || "archivo" });
      document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(url), 2000);
      return nombre || "archivo";
    },
    AbrirPanel(pagina) { window.open(origen + "/" + (pagina || ""), "_blank"); },
    AbrirURL(u) { window.open(u, "_blank"); },
    async EmitirNucleo() { soloApp("Emitir con el motor propio"); },
    async SIIEngineSincronizar(rutEmpresa, rutUsuario, trib, cert, recordar) {
      // En el navegador lo hace el motor (Python), mismo resultado.
      const r = await llamar("POST", "/api/v1/mipyme/sincronizar", JSON.stringify({ rut_empresa: rutEmpresa, rut_usuario: rutUsuario, clave_tributaria: trib,
        clave_certificado: cert, con_xml: !!cert, con_pdf: true, recordar: !!recordar }));
      const t = await r.text();
      if (!r.ok) { let m = t; try { const d = JSON.parse(t); m = d.error?.mensaje || d.detail || t; } catch {} throw new Error(typeof m === "string" ? m : JSON.stringify(m)); }
      return t;
    },
    async SIIEngineFactura() { soloApp("Cobrar por el SII engine"); },
    async SIIEngineNotaCredito() { soloApp("Anular por el SII engine"); },
  } } };
  window.runtime = window.runtime || { EventsOn() {} };
  document.documentElement.classList.add("navegador");
})();
