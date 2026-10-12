//! Rutas del motor propio (api/routes/dte.py y status.py): emitir, previsualizar, enviar y
//! consultar estado; más el REST de boletas, que Python solo tenía en core (sin ruta).

use super::errores::{ok, ErrorHTTP, Res};
use super::http::Peticion;
use super::{bytes_latin1, log, texto, Json, Prot, Servidor};
use crate::emision;
use crate::firma::{self, Certificado};
use crate::pdf;
use crate::sii;
use crate::ted;
use crate::xsd;
use base64::Engine;
use regex::Regex;
use serde_json::{json, Value};
use std::sync::OnceLock;

pub fn rutas(s: &mut Servidor) {
    s.ruta("POST /api/v1/dte/emitir", Prot::Protegida, emitir_dte);
    s.ruta(
        "POST /api/v1/dte/previsualizar",
        Prot::Protegida,
        previsualizar_dte,
    );
    s.ruta("POST /api/v1/dte/enviar", Prot::Protegida, enviar_dte);
    s.ruta("POST /api/v1/estado/track", Prot::Protegida, estado_track);
    s.ruta("POST /api/v1/estado/dte", Prot::Protegida, estado_dte);
    s.ruta(
        "POST /api/v1/boletas/enviar",
        Prot::Protegida,
        enviar_boletas,
    );
    s.ruta(
        "POST /api/v1/boletas/estado",
        Prot::Protegida,
        estado_boletas,
    );
}

const B64: base64::engine::GeneralPurpose = base64::engine::general_purpose::STANDARD;

pub fn falta_campo(campo: &str) -> ErrorHTTP {
    ErrorHTTP::faltan(&[campo])
}

/// `responderDominio`: un error de emisión con su código y status (o 500 si no es de dominio).
pub fn de_dominio(e: emision::Error) -> ErrorHTTP {
    if e.status == 500 {
        return ErrorHTTP::interno();
    }
    let mut h = ErrorHTTP::nuevo(e.status, &e.codigo, e.mensaje);
    h.detalle = e.detalle;
    h
}

/// `_cargar_cert`: p12 en base64 + clave → 422 validacion/certificado.
pub fn certificado_desde_b64(p12b64: &str, clave: &str) -> Result<Certificado, ErrorHTTP> {
    let raw = B64
        .decode(p12b64)
        .map_err(|e| ErrorHTTP::validacion(format!("El certificado no es Base64 válido: {e}")))?;
    firma::cargar_p12(&raw, clave)
        .map_err(|e| ErrorHTTP::certificado(format!("No se pudo cargar el certificado: {e}")))
}

impl Servidor {
    /// `OrquestadorDTE._obtener_certificado`: el de la petición; si no, el del .env; si no,
    /// firma.pfx (DTE_CERT_PATH) con la clave del setup; si no, 422 certificado.
    pub fn certificado_emision(&self, p12b64: &str, clave: &str) -> Result<Certificado, ErrorHTTP> {
        if !p12b64.is_empty() && !clave.is_empty() {
            return certificado_desde_b64(p12b64, clave);
        }
        if !self.cfg.certificado_path.is_empty() && !self.cfg.certificado_password.is_empty() {
            if let Ok(raw) = std::fs::read(&self.cfg.certificado_path) {
                if let Ok(c) = firma::cargar_p12(&raw, &self.cfg.certificado_password) {
                    return Ok(c);
                }
            }
            return Err(ErrorHTTP::certificado(format!(
                "Error al cargar el certificado digital desde el archivo configurado [{}]",
                self.cfg.certificado_path
            )));
        }
        let ruta = std::env::var("DTE_CERT_PATH").unwrap_or_else(|_| "firma.pfx".into());
        if let Ok(raw) = std::fs::read(&ruta) {
            if let Ok(c) = firma::cargar_p12(&raw, "12345678") {
                return Ok(c);
            }
        }
        Err(ErrorHTTP::certificado("Certificado digital no provisto en la petición y tampoco configurado en .env (CERTIFICADO_PATH y CERTIFICADO_PASSWORD son requeridos)."))
    }

    pub fn contexto_de<'a>(&'a self, cert: &'a Certificado, rut: &str) -> emision::Contexto<'a> {
        let (fecha, num) = self.resolucion_emisor(rut, &self.cfg.sii_ambiente);
        emision::Contexto {
            almacen: &self.alm,
            cert,
            storage_base: self.cfg.storage_path.clone(),
            ambiente: self.cfg.sii_ambiente.clone(),
            fecha_resolucion: fecha,
            numero_resolucion: num,
            marca: self.marca(),
            validar: true,
        }
    }

    /// `marcarEnviadosPorXML` (core/models.py::marcar_enviados_por_xml): los (TipoDTE, Folio)
    /// del sobre recién enviado quedan `enviado` con su TrackID. Best-effort.
    pub fn marcar_enviados_por_xml(&self, xml_envio: &[u8], track_id: &str, ambiente: &str) -> i64 {
        static RE_TF: OnceLock<Regex> = OnceLock::new();
        static RE_RUT: OnceLock<Regex> = OnceLock::new();
        let re_tf = RE_TF.get_or_init(|| {
            Regex::new(r"<TipoDTE>(\d+)</TipoDTE>\s*<Folio>(\d+)</Folio>").expect("re")
        });
        let re_rut =
            RE_RUT.get_or_init(|| Regex::new(r"<RutEmisor>([^<]+)</RutEmisor>").expect("re"));
        let t = String::from_utf8_lossy(xml_envio);
        let Some(m) = re_rut.captures(&t) else {
            return 0;
        };
        let rut = m[1].trim().to_string();
        let ahora = super::ahora_python();
        let mut filas = 0i64;
        let mut vistos = std::collections::BTreeSet::new();
        for c in re_tf.captures_iter(&t) {
            let k = format!("{}/{}", &c[1], &c[2]);
            if !vistos.insert(k) {
                continue;
            }
            let mut q = "UPDATE dtes SET estado = CASE WHEN estado='generado' THEN 'enviado' ELSE estado END, track_id = COALESCE(track_id, ?), actualizado_en=? WHERE rut_emisor=? AND tipo_dte=? AND folio=?".to_string();
            let mut args: Vec<rusqlite::types::Value> = sql![
                track_id,
                ahora.clone(),
                rut.clone(),
                c[1].to_string(),
                c[2].to_string()
            ]
            .to_vec();
            if !ambiente.is_empty() {
                q.push_str(" AND ambiente=?");
                args.push(ambiente.to_string().into());
            }
            if let Ok(n) = self.ejecutar(&q, &args) {
                filas += n as i64;
            }
        }
        filas
    }
}

fn ambiente_valido(a: &str) -> bool {
    a == "certificacion" || a == "produccion"
}

/// `emitirDTE`: folio → TED → firma → sobre → XSD → disco → BD → PDF.
fn emitir_dte(s: &Servidor, p: &mut Peticion) -> Res {
    let j = Json::leer(p)?;
    let Some(dte) = j.get("dte") else {
        return Err(falta_campo("dte"));
    };
    let doc = emision::documento_desde_valor(dte)
        .map_err(|e| ErrorHTTP::pydantic("body", "dte", &e, "value_error"))?;
    let cert = match j.entero("cert_id")? {
        Some(id) => {
            let cuenta = s.cuenta_id(p);
            s.certificado_del_keystore(id, cuenta)
                .map_err(ErrorHTTP::no_encontrado)?
        }
        None => s.certificado_emision(
            &j.texto_o("certificado_p12_b64", "")?,
            &j.texto_o("password_certificado", "")?,
        )?,
    };
    let res = emision::emitir(&s.contexto_de(&cert, &doc.emisor.rut), doc).map_err(de_dominio)?;
    let mut pdf_path = String::new();
    if let Ok(Some(d)) = s.dte_por_id(res.dte_id) {
        match s.regenerar_pdf(&d) {
            Ok(r) => pdf_path = r,
            Err(e) => log(&format!(
                "emitir: PDF del documento {} no generado: {e}",
                res.dte_id
            )),
        }
    }
    ok(json!({
        "dte_id": res.dte_id, "folio": res.folio, "tipo_dte": res.tipo_dte, "monto_total": res.monto_total,
        "xml_dte_path": res.xml_dte_path, "pdf_path": pdf_path, "xml_envio_path": res.xml_envio_path,
        "xml_envio_b64": B64.encode(&res.envio), "ambiente": res.ambiente, "mensaje": res.mensaje,
    }))
}

/// `previsualizarDTE`: firmado + timbrado + XSD + PDF sin enviar ni consumir folios;
/// certificado del keystore (cert_id) y CAF activo de la BD.
fn previsualizar_dte(s: &Servidor, p: &mut Peticion) -> Res {
    let j = Json::leer(p)?;
    let (dte, cert_raw) = (j.get("dte"), j.get("cert_id"));
    if dte.is_none() || cert_raw.is_none() {
        return Err(falta_campo(if dte.is_none() { "dte" } else { "cert_id" }));
    }
    // pydantic acepta el entero como número o como texto de dígitos
    let cert_id: i64 = match cert_raw.expect("cert_id") {
        Value::Number(n) => n.as_i64(),
        Value::String(t) => t.trim().parse().ok(),
        _ => None,
    }
    .ok_or_else(|| {
        ErrorHTTP::pydantic(
            "body",
            "cert_id",
            "Input should be a valid integer",
            "int_parsing",
        )
    })?;
    let doc = emision::documento_desde_valor(dte.expect("dte"))
        .map_err(|e| ErrorHTTP::pydantic("body", "dte", &e, "value_error"))?;
    let cuenta = s.cuenta_id(p);
    let (p12, clave) = s
        .descifrar_certificado(cert_id, cuenta)
        .map_err(|_| ErrorHTTP::no_encontrado(format!("Certificado {cert_id} no encontrado")))?;
    let cert = firma::cargar_p12(&p12, &clave)
        .map_err(|e| ErrorHTTP::certificado(format!("No se pudo cargar el certificado: {e}")))?;
    let Some(caf_db) = s.alm.caf_activo(&doc.emisor.rut, doc.tipo_dte)? else {
        return Err(ErrorHTTP::folio(format!(
            "No hay CAF activo para {} tipo {}. Carga un CAF primero.",
            doc.emisor.rut, doc.tipo_dte
        )));
    };
    let caf = ted::parsear_caf(&caf_db.xml)
        .map_err(|e| ErrorHTTP::caf(format!("No se pudo procesar el CAF: {e}")))?;
    let mut ctx = s.contexto_de(&cert, &doc.emisor.rut);
    ctx.validar = false;
    let tipo = doc.tipo_dte;
    let pr = emision::previsualizar(&ctx, doc, &caf).map_err(de_dominio)?;
    let val = xsd::validar(&pr.envio);
    let mut pdf_b64 = String::new();
    match pdf::desde_xml(&bytes_latin1(&pr.dte_firmado)).and_then(|(d, t)| {
        if tipo == 39 || tipo == 41 {
            pdf::boleta_80mm(&d, &t)
        } else {
            pdf::carta(
                &d,
                &t,
                &pdf::Opciones {
                    ambiente: s.cfg.sii_ambiente.clone(),
                    resolucion_fecha: ctx.fecha_resolucion.clone(),
                    resolucion_num: ctx.numero_resolucion,
                    hoy: String::new(),
                },
            )
        }
    }) {
        Ok(b) => pdf_b64 = B64.encode(b),
        Err(e) => log(&format!("previsualizar: PDF no generado: {e}")),
    }
    ok(json!({
        "es_preview": true, "aviso": "Previsualización — NO enviada al SII, no consume folios.",
        "folio": pr.documento.folio, "tipo_dte": tipo, "monto_neto": pr.monto_neto, "monto_exento": pr.monto_exento,
        "iva": pr.iva, "monto_total": pr.monto_total, "valido_xsd": val.valido, "errores_xsd": val.mensajes(),
        "xml_b64": B64.encode(bytes_latin1(&pr.dte_firmado)), "pdf_b64": pdf_b64,
    }))
}

fn exigir(j: &Json, campos: &[&str]) -> Result<Vec<String>, ErrorHTTP> {
    let mut out = Vec::new();
    for c in campos {
        match j.texto(c)? {
            Some(v) => out.push(v),
            None => return Err(falta_campo(c)),
        }
    }
    Ok(out)
}

/// `enviarDTE`: EnvioDTE firmado → XSD → DTEUpload → TrackID.
fn enviar_dte(s: &Servidor, p: &mut Peticion) -> Res {
    let j = Json::leer(p)?;
    let v = exigir(
        &j,
        &[
            "xml_envio_b64",
            "certificado_p12_b64",
            "password_certificado",
            "rut_empresa",
            "dv_empresa",
        ],
    )?;
    let tipo = j.entero_o("tipo_dte", 0)?;
    let mut ambiente = j.texto_o("ambiente", "")?;
    if ambiente.is_empty() {
        ambiente = "certificacion".into();
    }
    if !ambiente_valido(&ambiente) {
        return Err(ErrorHTTP::pydantic(
            "body",
            "ambiente",
            "Input should be 'certificacion' or 'produccion'",
            "enum",
        ));
    }
    let cert = certificado_desde_b64(&v[1], &v[2])?;
    let xml = B64
        .decode(&v[0])
        .map_err(|e| ErrorHTTP::validacion(format!("El XML de envío no es Base64 válido: {e}")))?;
    xsd::validar_error(&xml).map_err(|e| {
        ErrorHTTP::validacion(format!("El XML no cumple el esquema XSD del SII: {e}"))
    })?;
    if tipo == 39 || tipo == 41 {
        // Python levanta ValidacionError DENTRO del try del envío y su `except Exception` lo
        // convierte en SIIError (502). Se copia tal cual para que el contrato sea idéntico.
        return Err(ErrorHTTP::sii_comunicacion(format!("Error de comunicación con el SII: El tipo {tipo} es una boleta y no se envía por este cliente. Usar core.sii_boleta.ClienteBoletaSII (REST, token propio).")));
    }
    let mut cli = sii::http::Cliente::nuevo(&ambiente, cert).map_err(ErrorHTTP::validacion)?;
    let (track, _) = cli.enviar_dte(&xml, &v[3], &v[4]).map_err(|e| match e {
        sii::Error::Respuesta(m) => {
            ErrorHTTP::sii_rechazo(format!("El SII rechazó el documento: {m}"))
        }
        sii::Error::Comunicacion(m) => {
            ErrorHTTP::sii_comunicacion(format!("Error de comunicación con el SII: {m}"))
        }
    })?;
    s.marcar_enviados_por_xml(&xml, &track.to_string(), &ambiente);
    ok(
        json!({"track_id": track, "mensaje": format!("Envío exitoso. TrackID: {track}"), "ambiente": ambiente}),
    )
}

/// `estadoTrack` (api/routes/status.py).
fn estado_track(_s: &Servidor, p: &mut Peticion) -> Res {
    let j = Json::leer(p)?;
    let Some(track) = j.entero("track_id")? else {
        return Err(falta_campo("track_id"));
    };
    let v = exigir(
        &j,
        &[
            "rut_empresa",
            "dv_empresa",
            "certificado_p12_b64",
            "password_certificado",
        ],
    )?;
    let mut ambiente = j.texto_o("ambiente", "")?;
    if ambiente.is_empty() {
        ambiente = "certificacion".into();
    }
    let cert = certificado_desde_b64(&v[2], &v[3]).map_err(|e| {
        ErrorHTTP::certificado(format!(
            "No se pudo cargar el certificado: {}",
            e.mensaje
                .trim_start_matches("No se pudo cargar el certificado: ")
        ))
    })?;
    let mut cli = sii::http::Cliente::nuevo(&ambiente, cert).map_err(ErrorHTTP::validacion)?;
    let e = cli
        .estado_track(track, &v[0], &v[1])
        .map_err(|e| ErrorHTTP::sii_comunicacion(format!("Error al consultar el SII: {e}")))?;
    ok(json!({"track_id": track, "estado": e.estado, "glosa": e.glosa, "ambiente": ambiente}))
}

/// `estadoDTE`.
fn estado_dte(_s: &Servidor, p: &mut Peticion) -> Res {
    let j = Json::leer(p)?;
    for c in ["rut_emisor", "dv_emisor"] {
        if j.get(c).is_none() {
            return Err(falta_campo(c));
        }
    }
    let Some(tipo) = j.entero("tipo_dte")? else {
        return Err(falta_campo("tipo_dte"));
    };
    let Some(folio) = j.entero("folio")? else {
        return Err(falta_campo("folio"));
    };
    if j.get("fecha_emision").is_none() {
        return Err(falta_campo("fecha_emision"));
    }
    let Some(monto) = j.entero("monto_total")? else {
        return Err(falta_campo("monto_total"));
    };
    let v = exigir(
        &j,
        &[
            "rut_receptor",
            "dv_receptor",
            "certificado_p12_b64",
            "password_certificado",
        ],
    )?;
    let (rut_e, dv_e, fecha) = (
        j.texto_o("rut_emisor", "")?,
        j.texto_o("dv_emisor", "")?,
        j.texto_o("fecha_emision", "")?,
    );
    let mut ambiente = j.texto_o("ambiente", "")?;
    if ambiente.is_empty() {
        ambiente = "certificacion".into();
    }
    let cert = certificado_desde_b64(&v[2], &v[3]).map_err(|e| {
        ErrorHTTP::certificado(format!(
            "No se pudo cargar el certificado: {}",
            e.mensaje
                .trim_start_matches("No se pudo cargar el certificado: ")
        ))
    })?;
    let mut cli = sii::http::Cliente::nuevo(&ambiente, cert).map_err(ErrorHTTP::validacion)?;
    let e = cli
        .estado_dte(
            &rut_e,
            &dv_e,
            tipo as i32,
            folio as i32,
            &fecha,
            monto,
            &v[0],
            &v[1],
        )
        .map_err(|e| ErrorHTTP::sii_comunicacion(format!("Error al consultar el SII: {e}")))?;
    ok(
        json!({"folio": folio, "tipo_dte": tipo, "estado": e.estado, "glosa": e.glosa, "ambiente": ambiente}),
    )
}

/// `enviarBoletas` (solo Go/Rust): EnvioBOLETA firmado → REST → TrackID de 15 dígitos.
fn enviar_boletas(s: &Servidor, p: &mut Peticion) -> Res {
    let j = Json::leer(p)?;
    let v = exigir(
        &j,
        &[
            "xml_envio_b64",
            "certificado_p12_b64",
            "password_certificado",
            "rut_empresa",
            "dv_empresa",
        ],
    )?;
    let mut ambiente = j.texto_o("ambiente", "")?;
    if ambiente.is_empty() {
        ambiente = s.cfg.sii_ambiente.clone();
    }
    let cert = certificado_desde_b64(&v[1], &v[2])?;
    let xml = B64
        .decode(&v[0])
        .map_err(|e| ErrorHTTP::validacion(format!("El XML de envío no es Base64 válido: {e}")))?;
    xsd::validar_error(&xml).map_err(|e| {
        ErrorHTTP::validacion(format!("El XML no cumple el esquema XSD del SII: {e}"))
    })?;
    let mut cli =
        sii::boleta::ClienteBoleta::nuevo(&ambiente, cert).map_err(ErrorHTTP::validacion)?;
    let (track, resp) = cli.enviar(&xml, &v[3], &v[4]).map_err(|e| match e {
        sii::boleta::ErrorBoleta::Rechazo(r) => {
            let mut h = ErrorHTTP::sii_rechazo(r.to_string());
            h.detalle = Some(r.detalle.clone());
            h
        }
        otro => ErrorHTTP::sii_comunicacion(otro.to_string()),
    })?;
    let filas = s.marcar_enviados_por_xml(&xml, &track, &ambiente);
    ok(
        json!({"track_id": track, "mensaje": format!("Envío de boletas recibido. TrackID: {track}"), "ambiente": ambiente, "marcados": filas, "respuesta": resp}),
    )
}

/// `estadoBoletas`: estado del sobre y aceptados/rechazados por documento.
fn estado_boletas(s: &Servidor, p: &mut Peticion) -> Res {
    let j = Json::leer(p)?;
    let v = exigir(
        &j,
        &[
            "track_id",
            "rut_empresa",
            "dv_empresa",
            "certificado_p12_b64",
            "password_certificado",
        ],
    )?;
    let mut ambiente = j.texto_o("ambiente", "")?;
    if ambiente.is_empty() {
        ambiente = s.cfg.sii_ambiente.clone();
    }
    let cert = certificado_desde_b64(&v[3], &v[4])?;
    let mut cli =
        sii::boleta::ClienteBoleta::nuevo(&ambiente, cert).map_err(ErrorHTTP::validacion)?;
    let e = cli
        .estado(&v[0], &v[1], &v[2])
        .map_err(ErrorHTTP::sii_comunicacion)?;
    ok(serde_json::to_value(e).unwrap_or(Value::Null))
}

pub fn _texto(v: &Value) -> String {
    texto(v)
}
