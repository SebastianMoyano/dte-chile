const $ = id => document.getElementById(id);
async function refrescar() {
  const r = await chrome.runtime.sendMessage({ tipo: "estado" });
  const grabando = !!(r && r.grabando);
  $("start").disabled = grabando; $("stop").disabled = !grabando;
  $("todo").checked = !!(r && r.modo === "todo"); $("todo").disabled = grabando;
  $("pii").checked = !!(r && r.pii); $("pii").disabled = grabando;
  $("st").innerHTML = grabando
    ? `<span class="rec">● Grabando</span> · ${r.n} entradas${r.modo === "todo" ? " (cualquier sitio)" : " (sii.cl)"}<br>${(r.titulo||"pestaña "+r.tabId).replace(/</g,"&lt;")}`
    : (r && r.ultimo ? `Última captura: ${r.ultimo}` : "Sin grabar.");
}
$("start").onclick = async () => {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  const r = await chrome.runtime.sendMessage({ tipo: "start", tabId: tab.id, url: tab.url });
  if (r && r.error) $("st").textContent = "No se pudo grabar: " + r.error;
  $("pii").onchange = async () => { await chrome.runtime.sendMessage({ tipo: "pii", valor: $("pii").checked }); refrescar(); };
refrescar();
};
$("stop").onclick = async () => { await chrome.runtime.sendMessage({ tipo: "stop" }); refrescar(); };
$("todo").onchange = async () => {
  const r = await chrome.runtime.sendMessage({ tipo: "modo", valor: $("todo").checked ? "todo" : "sii" });
  if (r && r.error) $("st").textContent = r.error;
  refrescar();
};
refrescar();
