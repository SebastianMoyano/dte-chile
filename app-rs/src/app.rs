//! Los comandos que la interfaz llama (los 12 bindings de `app/app.go`, `ia.go` y
//! `siiengine.go`, con los mismos nombres en `app/frontend/dist/tauri.js`): estado del motor,
//! llamadas firmadas a la API, guardar y leer archivos del motor, emitir con el núcleo, abrir el
//! panel, conectar la IA y operar el SII engine. Nunca devuelven la clave de la app.

use crate::motor::Motor;
use dtechile::almacen::Almacen;
use dtechile::emision;
use dtechile::pdf;
use serde::Serialize;
use std::path::Path;
use std::sync::{Arc, Mutex, RwLock};
use std::time::Duration;
use tauri::{AppHandle, Emitter, Manager, State};

/// Lo que la interfaz necesita saber del motor. Nunca incluye la clave.
#[derive(Debug, Clone, Default, Serialize)]
pub struct Estado {
    pub listo: bool,
    pub error: String,
    pub url: String,
    pub ambiente: String,
    pub version: String,
    pub externo: bool,
    pub empaquetado: bool,
    /// el motor corre dentro de la app (sin Python)
    #[serde(rename = "go")]
    pub en_proceso: bool,
    pub clave_admin: String,
    pub raiz: String,
    pub log: String,
}

/// Respuesta de una llamada al motor: status HTTP y cuerpo tal cual (normalmente JSON).
#[derive(Debug, Clone, Serialize)]
pub struct Respuesta {
    pub status: u16,
    pub cuerpo: String,
}

pub struct Compartido {
    pub motor: Mutex<Motor>,
    pub estado: RwLock<Estado>,
}

pub type Estado_ = Arc<Compartido>;

impl Compartido {
    /// `API`: llama al motor con la clave de la app. `ruta` es absoluta ("/api/v1/..."),
    /// `cuerpo` es JSON o vacío. Devuelve status y cuerpo sin interpretar.
    pub fn api(&self, metodo: &str, ruta: &str, cuerpo: &str) -> Result<Respuesta, String> {
        let m = self.motor.lock().unwrap_or_else(|e| e.into_inner());
        if m.url.is_empty() {
            return Err("el motor todavía no está listo".into());
        }
        if let Some(s) = &m.srv {
            let (st, b) = s.llamar(
                metodo,
                ruta,
                (!cuerpo.is_empty()).then_some(cuerpo.as_bytes()),
            );
            return Ok(Respuesta {
                status: st,
                cuerpo: String::from_utf8_lossy(&b).into_owned(),
            });
        }
        // motor externo: por red, con su API key
        let ag = dtechile::sii::http::agente(Duration::from_secs(180), false);
        let url = format!("{}{ruta}", m.url);
        let auth = format!("Bearer {}", m.clave);
        let r = match metodo {
            "GET" | "DELETE" => {
                let mut req = if metodo == "GET" {
                    ag.get(&url)
                } else {
                    ag.delete(&url)
                };
                req = req.header("Accept", "application/json");
                if !m.clave.is_empty() {
                    req = req.header("Authorization", &auth);
                }
                dtechile::sii::http::ejecutar_get(req)?
            }
            _ => {
                let mut req = if metodo == "PUT" {
                    ag.put(&url)
                } else {
                    ag.post(&url)
                };
                req = req.header("Accept", "application/json");
                if !cuerpo.is_empty() {
                    req = req.header("Content-Type", "application/json");
                }
                if !m.clave.is_empty() {
                    req = req.header("Authorization", &auth);
                }
                dtechile::sii::http::ejecutar(req, cuerpo.as_bytes())?
            }
        };
        Ok(Respuesta {
            status: r.status,
            cuerpo: String::from_utf8_lossy(&r.cuerpo).into_owned(),
        })
    }

    /// `Formulario`: POST multipart al motor (campos de texto y, opcionalmente, un archivo del
    /// disco bajo el campo `archivo`). Es lo que usa "Mi empresa" para subir el certificado y
    /// para agregar la empresa; el archivo se lee aquí y nunca pasa por la interfaz.
    pub fn formulario(&self, ruta: &str, campos: &[(String, String)], archivo: Option<&Path>) -> Result<Respuesta, String> {
        let limite = format!("----faro{}", dtechile::almacen::ahora_iso().replace([':', '-', 'T'], ""));
        let mut cuerpo: Vec<u8> = Vec::new();
        for (k, v) in campos {
            cuerpo.extend_from_slice(format!("--{limite}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n").as_bytes());
        }
        if let Some(p) = archivo {
            let datos = std::fs::read(p).map_err(|e| format!("no pude leer el archivo: {e}"))?;
            let nombre = p.file_name().map(|n| n.to_string_lossy().into_owned()).unwrap_or_else(|| "archivo".into());
            cuerpo.extend_from_slice(format!("--{limite}\r\nContent-Disposition: form-data; name=\"archivo\"; filename=\"{nombre}\"\r\nContent-Type: application/octet-stream\r\n\r\n").as_bytes());
            cuerpo.extend_from_slice(&datos);
            cuerpo.extend_from_slice(b"\r\n");
        }
        cuerpo.extend_from_slice(format!("--{limite}--\r\n").as_bytes());
        let ct = format!("multipart/form-data; boundary={limite}");
        let m = self.motor.lock().unwrap_or_else(|e| e.into_inner());
        if m.url.is_empty() {
            return Err("el motor todavía no está listo".into());
        }
        if let Some(s) = &m.srv {
            let (st, b) = s.llamar_con("POST", ruta, &ct, &cuerpo);
            return Ok(Respuesta { status: st, cuerpo: String::from_utf8_lossy(&b).into_owned() });
        }
        let ag = dtechile::sii::http::agente(Duration::from_secs(180), false);
        let mut req = ag.post(&format!("{}{ruta}", m.url)).header("Accept", "application/json").header("Content-Type", &ct);
        if !m.clave.is_empty() {
            req = req.header("Authorization", &format!("Bearer {}", m.clave));
        }
        let r = dtechile::sii::http::ejecutar(req, &cuerpo)?;
        Ok(Respuesta { status: r.status, cuerpo: String::from_utf8_lossy(&r.cuerpo).into_owned() })
    }

    /// Baja un recurso del motor (bytes crudos).
    fn bajar(&self, ruta: &str) -> Result<Vec<u8>, String> {
        let m = self.motor.lock().unwrap_or_else(|e| e.into_inner());
        if let Some(s) = &m.srv {
            let (st, b) = s.llamar("GET", ruta, None);
            if st != 200 {
                return Err(format!(
                    "el motor respondió {st}: {:.4096}",
                    String::from_utf8_lossy(&b)
                ));
            }
            return Ok(b);
        }
        let ag = dtechile::sii::http::agente(Duration::from_secs(180), false);
        let mut req = ag.get(format!("{}{ruta}", m.url));
        if !m.clave.is_empty() {
            req = req.header("Authorization", &format!("Bearer {}", m.clave));
        }
        let r = dtechile::sii::http::ejecutar_get(req)?;
        if r.status != 200 {
            return Err(format!(
                "el motor respondió {}: {:.4096}",
                r.status,
                String::from_utf8_lossy(&r.cuerpo)
            ));
        }
        Ok(r.cuerpo)
    }
}

/// `arrancar`: levanta el motor en un hilo y avisa a la interfaz con el evento "motor".
fn arrancar(app: AppHandle, c: Arc<Compartido>) {
    let recursos = app.path().resource_dir().ok().map(|r| r.join("frontend"));
    let r = c
        .motor
        .lock()
        .unwrap_or_else(|e| e.into_inner())
        .iniciar(recursos);
    let mut e = {
        let m = c.motor.lock().unwrap_or_else(|e| e.into_inner());
        Estado {
            url: m.url.clone(),
            externo: m.externo,
            empaquetado: m.empaquetado,
            en_proceso: m.srv.is_some(),
            clave_admin: m.clave_admin.clone(),
            raiz: m.raiz.clone(),
            log: m.log_path.clone(),
            ..Default::default()
        }
    };
    match r {
        Err(err) => e.error = err,
        Ok(()) => {
            e.listo = true;
            if let Ok(r) = c.api("GET", "/", "") {
                if r.status == 200 {
                    if let Ok(v) = serde_json::from_str::<serde_json::Value>(&r.cuerpo) {
                        e.ambiente = v["ambiente_sii"].as_str().unwrap_or("").into();
                        e.version = v["version"].as_str().unwrap_or("").into();
                    }
                }
            }
        }
    }
    *c.estado.write().unwrap_or_else(|x| x.into_inner()) = e.clone();
    let _ = app.emit("motor", e.clone());
    if e.listo && !e.externo {
        let raiz = e.raiz.clone();
        std::thread::spawn(move || refrescar_valores(&raiz));
    }
}

/// UF, UTM y dólar de las páginas oficiales del SII a la tabla `valores`, al arrancar y cada
/// 24 h (el "demonio" de nucleo-valores, dentro de la app).
fn refrescar_valores(raiz: &str) {
    loop {
        if !raiz.is_empty() {
            let db = Path::new(raiz).join("dte_database.db");
            if let Ok(c) = dtechile::valores::Cache::abrir(&db.to_string_lossy()) {
                let anio: i32 = dtechile::almacen::ahora_iso()[..4].parse().unwrap_or(2026);
                let min = c.anio_minimo("uf").unwrap_or(0);
                if min == 0 || min > 2015 {
                    dtechile::valores::cargar_historico(&c, 2015, anio - 1, &|_| {});
                }
                for ind in ["uf", "utm", "dolar"] {
                    if let Ok((vs, _)) = dtechile::valores::fetch(ind, anio) {
                        let _ = c.guardar(&vs);
                    }
                }
            }
        }
        std::thread::sleep(Duration::from_secs(24 * 3600));
    }
}

#[tauri::command]
async fn estado(c: State<'_, Estado_>) -> Result<Estado, String> {
    Ok(c.estado.read().unwrap_or_else(|e| e.into_inner()).clone())
}

#[tauri::command]
async fn api(
    c: State<'_, Estado_>,
    metodo: String,
    ruta: String,
    cuerpo: String,
) -> Result<Respuesta, String> {
    c.api(&metodo, &ruta, &cuerpo)
}

/// `Guardar`: baja un archivo del motor (PDF/XML) y lo guarda donde el usuario elija.
/// Devuelve la ruta elegida, o "" si canceló.
#[tauri::command]
async fn guardar(
    app: AppHandle,
    c: State<'_, Estado_>,
    ruta: String,
    nombre_sugerido: String,
) -> Result<String, String> {
    use tauri_plugin_dialog::DialogExt;
    let datos = c.bajar(&ruta)?;
    let Some(destino) = app
        .dialog()
        .file()
        .set_title("Guardar")
        .set_file_name(&nombre_sugerido)
        .blocking_save_file()
    else {
        return Ok(String::new());
    };
    let p = destino.into_path().map_err(|e| e.to_string())?;
    std::fs::write(&p, datos).map_err(|e| e.to_string())?;
    Ok(p.to_string_lossy().into_owned())
}

/// `ElegirArchivo`: diálogo del sistema para elegir un archivo (p. ej. el certificado .p12).
/// Devuelve la ruta, o "" si canceló. `extensiones` va separado por comas ("p12,pfx").
#[tauri::command]
async fn elegir_archivo(app: AppHandle, titulo: String, extensiones: String) -> Result<String, String> {
    use tauri_plugin_dialog::DialogExt;
    let exts: Vec<&str> = extensiones.split(',').map(|e| e.trim()).filter(|e| !e.is_empty()).collect();
    let mut d = app.dialog().file().set_title(&titulo);
    if !exts.is_empty() {
        d = d.add_filter("Archivo", &exts);
    }
    let Some(f) = d.blocking_pick_file() else {
        return Ok(String::new());
    };
    Ok(f.into_path().map_err(|e| e.to_string())?.to_string_lossy().into_owned())
}

/// `Formulario`: POST multipart al motor con campos (JSON objeto de strings) y un archivo opcional.
#[tauri::command]
async fn formulario(c: State<'_, Estado_>, ruta: String, campos_json: String, ruta_archivo: String) -> Result<Respuesta, String> {
    let v: serde_json::Value = if campos_json.trim().is_empty() { serde_json::json!({}) } else { serde_json::from_str(&campos_json).map_err(|e| e.to_string())? };
    let campos: Vec<(String, String)> = v.as_object().map(|o| o.iter().map(|(k, x)| (k.clone(), x.as_str().map(|s| s.to_string()).unwrap_or_else(|| x.to_string()))).collect()).unwrap_or_default();
    let archivo = (!ruta_archivo.is_empty()).then(|| Path::new(&ruta_archivo));
    c.formulario(&ruta, &campos, archivo)
}

/// `PedirFolios`: pide al SII un rango de folios (CAF) para la empresa, con su certificado y
/// en su ambiente, lo guarda en storage/cafs y lo registra en la base: lo mismo que
/// `nucleo-portal solicitar … --db`. Respeta los guardarraíles anti-acaparamiento del portal.
#[tauri::command]
async fn pedir_folios(c: State<'_, Estado_>, negocio_id: i64, tipo: i32, cantidad: i64) -> Result<String, String> {
    let r = c.api("GET", &format!("/api/v1/keystore/negocios/{negocio_id}/contexto-emision"), "")?;
    if r.status != 200 {
        return Err(format!("no pude leer el certificado de la empresa: {}", r.cuerpo));
    }
    let v: serde_json::Value = serde_json::from_str(&r.cuerpo).map_err(|e| e.to_string())?;
    let g = |k: &str| v[k].as_str().unwrap_or("").to_string();
    let (rut, ambiente, cert_pem, key_pem, db, storage) = (g("rut"), g("ambiente"), g("cert_pem"), g("key_pem"), g("database_path"), g("storage_path"));
    let mut cli = dtechile::portal::Cliente::nuevo(cert_pem.as_bytes(), key_pem.as_bytes(), dtechile::portal::base_de(&ambiente))?;
    cli.autenticar("")?;
    let (caf, info) = cli.solicitar_folios(&rut, tipo, cantidad, true, false)?;
    let mut out = serde_json::to_value(&info).map_err(|e| e.to_string())?;
    if let Some(caf) = caf {
        let dir = Path::new(&storage).join("cafs");
        let _ = std::fs::create_dir_all(&dir);
        let hoy = dtechile::almacen::ahora_iso()[..10].replace('-', "");
        let nombre = dir.join(format!("CAF_{}_T{tipo}_{}-{}_{hoy}.xml", rut.replace('-', ""), info.folio_desde, info.folio_hasta));
        std::fs::write(&nombre, &caf).map_err(|e| e.to_string())?;
        let txt = String::from_utf8_lossy(&caf).into_owned();
        let cf = dtechile::ted::parsear_caf(&txt)?;
        let alm = Almacen::abrir_y_migrar(&db).map_err(|e| e.to_string())?;
        let id = alm.registrar_caf(cf.tipo_dte, &cf.rut_emisor, cf.folio_desde, cf.folio_hasta, &cf.fecha_autorizacion, &txt).map_err(|e| e.to_string())?;
        out["caf_id"] = serde_json::json!(id);
        out["archivo"] = serde_json::json!(nombre.to_string_lossy());
    }
    Ok(out.to_string())
}

/// `Bytes`: un recurso del motor (p. ej. un PDF) en base64 para mostrarlo dentro de la app.
#[tauri::command]
async fn bytes(c: State<'_, Estado_>, ruta: String) -> Result<String, String> {
    use base64::Engine;
    Ok(base64::engine::general_purpose::STANDARD.encode(c.bajar(&ruta)?))
}

/// `EmitirNucleo`: emite con el NÚCLEO en Rust: pide al motor el contexto del negocio
/// (certificado en PEM, resolución, rutas), firma y persiste con `emision` sobre la misma base
/// y storage, y dibuja el PDF. La clave privada vive solo en memoria mientras dura la llamada.
#[tauri::command]
async fn emitir_nucleo(
    c: State<'_, Estado_>,
    negocio_id: i64,
    doc_json: String,
) -> Result<String, String> {
    let r = c.api(
        "GET",
        &format!("/api/v1/keystore/negocios/{negocio_id}/contexto-emision"),
        "",
    )?;
    if r.status != 200 {
        return Err(format!("contexto de emisión: {}", r.cuerpo));
    }
    let ctx = emision::contexto_desde_json(r.cuerpo.as_bytes())?;
    let doc = emision::documento_desde_json(doc_json.as_bytes())?;
    if !doc.emisor.rut.is_empty() && doc.emisor.rut != ctx.rut {
        return Err(format!(
            "el emisor del documento ({}) no es el negocio elegido ({})",
            doc.emisor.rut, ctx.rut
        ));
    }
    let alm = Almacen::abrir(&ctx.database_path).map_err(|e| e.to_string())?;
    let marca = std::env::var("RELOJ_FIJO")
        .ok()
        .filter(|m| !m.is_empty())
        .unwrap_or_else(|| dtechile::almacen::ahora_iso()[..19].to_string());
    let mut res = emision::emitir(
        &emision::Contexto {
            almacen: &alm,
            cert: &ctx.cert,
            storage_base: ctx.storage_path.clone(),
            ambiente: ctx.ambiente.clone(),
            fecha_resolucion: ctx.fecha_resolucion.clone(),
            numero_resolucion: ctx.numero_resolucion,
            marca,
            validar: true,
        },
        doc,
    )
    .map_err(|e| e.mensaje)?;
    match dibujar_pdf(
        &alm,
        res.dte_id,
        &ctx.storage_path,
        &ctx.ambiente,
        &ctx.fecha_resolucion,
        ctx.numero_resolucion,
    ) {
        Ok(ruta) => res.pdf_path = ruta,
        Err(_) => {
            if let Ok(p) = c.api(
                "POST",
                &format!("/api/v1/dte/documentos/{}/pdf", res.dte_id),
                "",
            ) {
                if p.status == 200 {
                    if let Ok(v) = serde_json::from_str::<serde_json::Value>(&p.cuerpo) {
                        res.pdf_path = v["pdf_path"].as_str().unwrap_or("").into();
                    }
                }
            }
        }
    }
    res.mensaje.push_str(" (núcleo Rust)");
    serde_json::to_string(&res).map_err(|e| e.to_string())
}

/// El PDF de un documento recién emitido por el núcleo, con la ruta que guarda el orquestador
/// Python: storage[/simulacion]/pdfs/DTE_<t>_<f>.pdf.
fn dibujar_pdf(
    alm: &Almacen,
    id: i64,
    storage: &str,
    ambiente: &str,
    fecha_res: &str,
    num_res: i64,
) -> Result<String, String> {
    let (xml, tipo, folio) = alm.xml_de(id).map_err(|e| e.to_string())?;
    let raw = dtechile::servidor::bytes_latin1(&xml);
    let (doc, ted) = pdf::desde_xml(&raw)?;
    let mut base = Path::new(storage).to_path_buf();
    if ambiente == "simulacion" {
        base = base.join("simulacion");
    }
    std::fs::create_dir_all(base.join("pdfs")).map_err(|e| e.to_string())?;
    let (ruta, b) = if tipo == 39 || tipo == 41 {
        (
            base.join("pdfs").join(format!("BOLETA_{tipo}_{folio}.pdf")),
            pdf::boleta_80mm(&doc, &ted)?,
        )
    } else {
        (
            base.join("pdfs").join(format!("DTE_{tipo}_{folio}.pdf")),
            pdf::carta(
                &doc,
                &ted,
                &pdf::Opciones {
                    ambiente: ambiente.into(),
                    resolucion_fecha: fecha_res.into(),
                    resolucion_num: num_res,
                    hoy: String::new(),
                },
            )?,
        )
    };
    std::fs::write(&ruta, b).map_err(|e| e.to_string())?;
    let rel = match Path::new(storage)
        .parent()
        .and_then(|p| ruta.strip_prefix(p).ok())
    {
        Some(r) => r.to_string_lossy().into_owned(),
        None => ruta.to_string_lossy().into_owned(),
    };
    alm.guardar_pdf(id, &rel).map_err(|e| e.to_string())?;
    Ok(rel)
}

#[tauri::command]
async fn abrir_url(u: String) -> Result<(), String> {
    tauri_plugin_opener::open_url(u, None::<&str>).map_err(|e| e.to_string())
}

/// `AbrirPanel`: la página web del motor (panel de certificados, documentos…) en el navegador.
#[tauri::command]
async fn abrir_panel(c: State<'_, Estado_>, pagina: String) -> Result<(), String> {
    let url = c
        .motor
        .lock()
        .unwrap_or_else(|e| e.into_inner())
        .url
        .clone();
    if url.is_empty() {
        return Ok(());
    }
    tauri_plugin_opener::open_url(
        format!("{url}/{}", pagina.trim_start_matches('/')),
        None::<&str>,
    )
    .map_err(|e| e.to_string())
}

#[tauri::command]
async fn conectores() -> Result<Vec<dtechile::conectores::Cliente>, String> {
    crate::ia::conectores()
}

#[tauri::command]
async fn conectar_ia(id: String, quitar: bool) -> Result<String, String> {
    crate::ia::conectar_ia(&id, quitar)
}

#[tauri::command]
async fn sii_engine_sincronizar(
    c: State<'_, Estado_>,
    rut_empresa: String,
    rut_usuario: String,
    clave_tributaria: String,
    clave_certificado: String,
    recordar: bool,
) -> Result<String, String> {
    crate::siiengine::sincronizar(
        &c,
        &rut_empresa,
        &rut_usuario,
        &clave_tributaria,
        &clave_certificado,
        recordar,
    )
}

#[tauri::command]
#[allow(clippy::too_many_arguments)]
async fn sii_engine_factura(
    c: State<'_, Estado_>,
    rut_empresa: String,
    rut_usuario: String,
    clave_tributaria: String,
    clave_certificado: String,
    recordar: bool,
    doc_json: String,
    emitir: bool,
) -> Result<String, String> {
    crate::siiengine::factura(
        &c,
        &rut_empresa,
        &rut_usuario,
        &clave_tributaria,
        &clave_certificado,
        recordar,
        &doc_json,
        emitir,
    )
}

#[tauri::command]
#[allow(clippy::too_many_arguments)]
async fn sii_engine_nota_credito(
    c: State<'_, Estado_>,
    rut_empresa: String,
    rut_usuario: String,
    clave_tributaria: String,
    clave_certificado: String,
    recordar: bool,
    dte_id: i64,
    emitir: bool,
) -> Result<String, String> {
    crate::siiengine::nota_credito(
        &c,
        &rut_empresa,
        &rut_usuario,
        &clave_tributaria,
        &clave_certificado,
        recordar,
        dte_id,
        emitir,
    )
}

/// La ventana: arma el estado compartido, arranca el motor en un hilo y registra los comandos.
pub fn correr() {
    let compartido: Estado_ = Arc::new(Compartido {
        motor: Mutex::new(Motor::default()),
        estado: RwLock::new(Estado::default()),
    });
    let c2 = compartido.clone();
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_opener::init())
        .manage(compartido)
        .setup(move |app| {
            let h = app.handle().clone();
            std::thread::spawn(move || arrancar(h, c2));
            Ok(())
        })
        .on_window_event(|w, ev| {
            if let tauri::WindowEvent::Destroyed = ev {
                if let Some(c) = w.try_state::<Estado_>() {
                    c.motor.lock().unwrap_or_else(|e| e.into_inner()).detener();
                }
            }
        })
        .invoke_handler(tauri::generate_handler![
            estado,
            api,
            guardar,
            bytes,
            emitir_nucleo,
            abrir_url,
            abrir_panel,
            conectores,
            conectar_ia,
            sii_engine_sincronizar,
            sii_engine_factura,
            sii_engine_nota_credito,
            elegir_archivo,
            formulario,
            pedir_folios
        ])
        .run(tauri::generate_context!())
        .expect("la app no pudo arrancar");
}
