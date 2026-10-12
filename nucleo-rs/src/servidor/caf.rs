//! Rutas de api/routes/caf.py y certificado.py: utilidades sin estado sobre un CAF o un .p12.

use super::errores::{ok, ErrorHTTP, Res};
use super::http::{parsear_formulario, Formulario, Peticion};
use super::{Json, Prot, Servidor};
use crate::firma;
use crate::ted;
use base64::Engine;
use serde_json::json;

pub fn rutas(s: &mut Servidor) {
    s.ruta("POST /api/v1/caf/info", Prot::Protegida, caf_info);
    s.ruta(
        "POST /api/v1/caf/validar-folio",
        Prot::Protegida,
        caf_validar_folio,
    );
    s.ruta(
        "POST /api/v1/certificado/validar",
        Prot::Protegida,
        certificado_validar,
    );
    s.ruta(
        "POST /api/v1/certificado/firmar-datos",
        Prot::Protegida,
        certificado_firmar_datos,
    );
}

pub const MAX_UPLOAD_FORM: usize = 10 << 20;
const B64: base64::engine::GeneralPurpose = base64::engine::general_purpose::STANDARD;

/// `leerArchivoForm` (api/util.leer_upload): el formulario y el archivo del campo.
/// Sin el campo → 422 "Field required" (como FastAPI).
pub fn leer_archivo_form(
    p: &Peticion,
    campo: &str,
) -> Result<(Formulario, Vec<u8>, String), ErrorHTTP> {
    let Some(f) = parsear_formulario(p) else {
        return Err(ErrorHTTP::faltan(&[campo]));
    };
    let Some(a) = f.archivo(campo) else {
        return Err(ErrorHTTP::faltan(&[campo]));
    };
    if a.datos.len() > MAX_UPLOAD_FORM {
        return Err(ErrorHTTP::validacion(format!(
            "Archivo demasiado grande (máximo {} MB).",
            MAX_UPLOAD_FORM >> 20
        )));
    }
    let (datos, nombre) = (a.datos.clone(), a.nombre.clone());
    Ok((f, datos, nombre))
}

fn caf_info(_s: &Servidor, p: &mut Peticion) -> Res {
    let (_, contenido, nombre) = leer_archivo_form(p, "archivo")?;
    if nombre.is_empty() || !nombre.to_ascii_lowercase().ends_with(".xml") {
        return Err(ErrorHTTP::validacion(
            "El archivo debe ser un CAF en formato XML.",
        ));
    }
    let caf = ted::parsear_caf(&String::from_utf8_lossy(&contenido))
        .map_err(|e| ErrorHTTP::caf(format!("No se pudo parsear el CAF: {e}")))?;
    let total = caf.folio_hasta - caf.folio_desde + 1;
    ok(
        json!({"tipo_dte": caf.tipo_dte, "rut_emisor": caf.rut_emisor, "folio_desde": caf.folio_desde, "folio_hasta": caf.folio_hasta,
        "fecha_autorizacion": caf.fecha_autorizacion, "total_folios": total,
        "mensaje": format!("CAF válido para {total} folios del tipo DTE {}.", caf.tipo_dte)}),
    )
}

fn caf_validar_folio(_s: &Servidor, p: &mut Peticion) -> Res {
    let j = Json::leer(p)?;
    let Some(caf_b64) = j.texto("caf_xml_b64")? else {
        return Err(ErrorHTTP::faltan(&["caf_xml_b64"]));
    };
    let Some(folio) = j.entero("folio")? else {
        return Err(ErrorHTTP::faltan(&["folio"]));
    };
    let raw = B64
        .decode(&caf_b64)
        .map_err(|e| ErrorHTTP::caf(format!("No se pudo procesar el CAF: {e}")))?;
    let caf = ted::parsear_caf(&String::from_utf8_lossy(&raw))
        .map_err(|e| ErrorHTTP::caf(format!("No se pudo procesar el CAF: {e}")))?;
    let valido = folio >= caf.folio_desde as i64 && folio <= caf.folio_hasta as i64;
    let msg = if valido {
        format!("El folio {folio} está autorizado en el CAF.")
    } else {
        format!(
            "El folio {folio} está FUERA del rango [{}-{}] del CAF.",
            caf.folio_desde, caf.folio_hasta
        )
    };
    ok(json!({"folio": folio, "valido": valido, "mensaje": msg}))
}

fn certificado_validar(_s: &Servidor, p: &mut Peticion) -> Res {
    let (f, contenido, nombre) = leer_archivo_form(p, "archivo")?;
    if !f.tiene("password") {
        return Err(ErrorHTTP::faltan(&["password"]));
    }
    let n = nombre.to_ascii_lowercase();
    if nombre.is_empty() || !(n.ends_with(".p12") || n.ends_with(".pfx")) {
        return Err(ErrorHTTP::validacion(
            "El archivo debe ser un certificado digital .p12 o .pfx",
        ));
    }
    if contenido.is_empty() {
        return Err(ErrorHTTP::validacion("El archivo está vacío."));
    }
    let cert = firma::cargar_p12(&contenido, &f.valor("password"))
        .map_err(|e| ErrorHTTP::certificado(format!("No se pudo cargar el certificado: {e}")))?;
    let rut = super::local::rut_del_certificado(&cert);
    let mut b64 = B64.encode(&cert.cert_der);
    if b64.len() > 80 {
        b64.truncate(80);
    }
    ok(
        json!({"rut_emisor": rut, "certificado_b64": format!("{b64}..."), "mensaje": format!("Certificado cargado correctamente para el emisor {rut}.")}),
    )
}

fn certificado_firmar_datos(_s: &Servidor, p: &mut Peticion) -> Res {
    let j = Json::leer(p)?;
    let mut vals = Vec::new();
    for c in ["datos_b64", "password", "certificado_p12_b64"] {
        match j.texto(c)? {
            Some(v) => vals.push(v),
            None => return Err(ErrorHTTP::faltan(&[c])),
        }
    }
    let p12 = B64
        .decode(&vals[2])
        .map_err(|e| ErrorHTTP::certificado(format!("No se pudo cargar el certificado: {e}")))?;
    let cert = firma::cargar_p12(&p12, &vals[1])
        .map_err(|e| ErrorHTTP::certificado(format!("No se pudo cargar el certificado: {e}")))?;
    let datos = B64
        .decode(&vals[0])
        .map_err(|e| ErrorHTTP::validacion(format!("Los datos no son Base64 válido: {e}")))?;
    let sig = ted::firmar_sha1(&cert.clave, &datos).map_err(|_| ErrorHTTP::interno())?;
    ok(json!({"firma_b64": B64.encode(sig), "algoritmo": "RSA-SHA1"}))
}
