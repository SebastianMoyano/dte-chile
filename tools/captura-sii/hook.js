// Corre DENTRO de la página (world MAIN): intercepta XMLHttpRequest y fetch para ver el cuerpo
// de las respuestas AJAX (p.ej. postFirmaDigital), que la API de red de la extensión no entrega.
(() => {
  if (window.__capturaSIIHook) return; window.__capturaSIIHook = true;
  const avisar = d => { try { window.postMessage({ __capturaSII: d }, "*"); } catch {} };
  const XO = XMLHttpRequest.prototype.open, XS = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function (m, u) { this.__cap = { metodo: m, url: String(u) }; return XO.apply(this, arguments); };
  XMLHttpRequest.prototype.send = function (body) {
    const c = this.__cap || {}; c.cuerpo = body == null ? null : (typeof body === "string" ? body : "(cuerpo no textual)");
    this.addEventListener("loadend", () => {
      let resp = null; try { resp = this.responseType === "" || this.responseType === "text" ? this.responseText : "(respuesta no textual)"; } catch {}
      avisar({ tipo: "xhr", metodo: c.metodo, url: c.url, cuerpo: c.cuerpo, estado: this.status, respuesta: resp, pagina: location.href, t: Date.now() });
    });
    return XS.apply(this, arguments);
  };
  const F = window.fetch;
  if (F) window.fetch = async function (entrada, init) {
    const url = typeof entrada === "string" ? entrada : (entrada && entrada.url) || "";
    const metodo = (init && init.method) || (entrada && entrada.method) || "GET";
    const cuerpo = init && typeof init.body === "string" ? init.body : null;
    const r = await F.apply(this, arguments);
    try { const cl = r.clone(); cl.text().then(txt => avisar({ tipo: "xhr", metodo, url: String(url), cuerpo, estado: r.status, respuesta: txt, pagina: location.href, t: Date.now() })); } catch {}
    return r;
  };
})();
