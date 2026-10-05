// Corre en cada página grabable: manda al fondo (a) el HTML y el TEXTO VISIBLE de la página
// cuando termina de cargar (la "respuesta" de navegaciones y formularios, y lo que un agente
// leería) y (b) lo que el hook del mundo MAIN ve en las llamadas AJAX/fetch. El fondo decide
// si está grabando esa pestaña.
const enviar = d => { try { chrome.runtime.sendMessage(d); } catch {} };
window.addEventListener("message", ev => { if (ev.source === window && ev.data && ev.data.__capturaSII) enviar(ev.data.__capturaSII); });
const foto = momento => enviar({ tipo: "pagina", momento, url: location.href, titulo: document.title,
                                 html: document.documentElement ? document.documentElement.outerHTML : "",
                                 texto: document.body ? document.body.innerText : "",
                                 t: Date.now(), marco: window === window.top ? "top" : "iframe" });
window.addEventListener("DOMContentLoaded", () => foto("domcontentloaded"));
window.addEventListener("load", () => setTimeout(() => foto("load"), 300));
// Páginas que cambian sin navegar (SPA): una foto por cada cambio de URL en el historial.
let ultimaUrl = location.href;
setInterval(() => { if (location.href !== ultimaUrl) { ultimaUrl = location.href; setTimeout(() => foto("cambio_de_ruta"), 500); } }, 500);
chrome.runtime.onMessage.addListener(msg => { if (msg && msg.tipo === "foto_ahora" && window === window.top) foto("inicio_grabacion"); });
