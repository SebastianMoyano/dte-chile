const $ = id => document.getElementById(id);
async function refrescar() {
  const r = await chrome.runtime.sendMessage({ tipo: "estado" });
  const grabando = !!(r && r.grabando);
  $("start").disabled = grabando; $("stop").disabled = !grabando;
  $("st").innerHTML = grabando
    ? `<span class="rec">● Grabando</span> · ${r.n} peticiones a sii.cl${r.reconexiones?` · ${r.reconexiones} reconexión(es)`:""}<br>${(r.titulo||"pestaña "+r.tabId).replace(/</g,"&lt;")}`
    : (r && r.ultimo ? `Última captura: ${r.ultimo}` : "Sin grabar.");
}
$("start").onclick = async () => {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  const r = await chrome.runtime.sendMessage({ tipo: "start", tabId: tab.id });
  if (r && r.error) $("st").textContent = "No se pudo grabar: " + r.error;
  refrescar();
};
$("stop").onclick = async () => { await chrome.runtime.sendMessage({ tipo: "stop" }); refrescar(); };
refrescar();
