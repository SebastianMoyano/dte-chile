// Corre en cada página de sii.cl: manda al fondo (a) el HTML de la página cuando termina de
// cargar (eso es la "respuesta" de las navegaciones y formularios) y (b) lo que el hook del
// mundo MAIN ve en las llamadas AJAX. El fondo decide si está grabando esa pestaña.
const enviar = d => { try { chrome.runtime.sendMessage(d); } catch {} };
window.addEventListener("message", ev => { if (ev.source === window && ev.data && ev.data.__capturaSII) enviar(ev.data.__capturaSII); });
const foto = momento => enviar({ tipo: "pagina", momento, url: location.href, titulo: document.title,
                                 html: document.documentElement ? document.documentElement.outerHTML : "", t: Date.now(), marco: window === window.top ? "top" : "iframe" });
window.addEventListener("DOMContentLoaded", () => foto("domcontentloaded"));
window.addEventListener("load", () => setTimeout(() => foto("load"), 300));
chrome.runtime.onMessage.addListener(msg => { if (msg && msg.tipo === "foto_ahora" && window === window.top) foto("inicio_grabacion"); });
