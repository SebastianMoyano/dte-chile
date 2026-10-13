// Puente Tauri ↔ interfaz. La misma interfaz corre en tres envases: la app Wails (Go define
// window.go con los bindings), la app Tauri (este archivo define los mismos bindings sobre los
// comandos de app-rs) y el navegador (puente.js, por HTTP). Si no hay Tauri, no hace nada.
(() => {
  const T = window.__TAURI__;
  if (!T || !T.core) return;
  const inv = (cmd, args) => T.core.invoke(cmd, args || {});
  const s = (x) => (x == null ? "" : String(x));
  window.go = { main: { App: {
    Estado: () => inv("estado"),
    API: (metodo, ruta, cuerpo) => inv("api", { metodo, ruta, cuerpo: s(cuerpo) }),
    Guardar: (ruta, nombre) => inv("guardar", { ruta, nombreSugerido: s(nombre) }),
    Bytes: (ruta) => inv("bytes", { ruta }),
    EmitirNucleo: (negocioId, docJson) => inv("emitir_nucleo", { negocioId: Number(negocioId), docJson }),
    AbrirURL: (u) => { inv("abrir_url", { u }); },
    AbrirPanel: (pagina) => { inv("abrir_panel", { pagina: s(pagina) }); },
    Conectores: () => inv("conectores"),
    ConectarIA: (id, quitar) => inv("conectar_ia", { id, quitar: !!quitar }),
    SIIEngineSincronizar: (rutEmpresa, rutUsuario, trib, cert, recordar) =>
      inv("sii_engine_sincronizar", { rutEmpresa, rutUsuario: s(rutUsuario), claveTributaria: s(trib), claveCertificado: s(cert), recordar: !!recordar }),
    SIIEngineFactura: (rutEmpresa, rutUsuario, trib, cert, recordar, docJson, emitir) =>
      inv("sii_engine_factura", { rutEmpresa, rutUsuario: s(rutUsuario), claveTributaria: s(trib), claveCertificado: s(cert), recordar: !!recordar, docJson, emitir: !!emitir }),
    ElegirArchivo: (titulo, extensiones) => inv("elegir_archivo", { titulo: s(titulo), extensiones: s(extensiones) }),
    Formulario: (ruta, camposJson, rutaArchivo) => inv("formulario", { ruta, camposJson: s(camposJson), rutaArchivo: s(rutaArchivo) }),
    PedirFolios: (negocioId, tipo, cantidad) => inv("pedir_folios", { negocioId: Number(negocioId), tipo: Number(tipo), cantidad: Number(cantidad) }),
    SIIEngineNotaCredito: (rutEmpresa, rutUsuario, trib, cert, recordar, dteId, emitir) =>
      inv("sii_engine_nota_credito", { rutEmpresa, rutUsuario: s(rutUsuario), claveTributaria: s(trib), claveCertificado: s(cert), recordar: !!recordar, dteId: Number(dteId), emitir: !!emitir }),
    SIIEngineNotaDebito: (rutEmpresa, rutUsuario, trib, cert, recordar, dteId, emitir) =>
      inv("sii_engine_nota_debito", { rutEmpresa, rutUsuario: s(rutUsuario), claveTributaria: s(trib), claveCertificado: s(cert), recordar: !!recordar, dteId: Number(dteId), emitir: !!emitir }),
  } } };
  window.runtime = { EventsOn: (nombre, cb) => { T.event.listen(nombre, (ev) => cb(ev.payload)); } };
  document.documentElement.classList.add("tauri");
})();
