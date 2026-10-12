//! POST /api/v1/estado/lote: varios TrackID con el certificado del keystore y un resumen
//! accionable (core/seguimiento.py). Un envío que falle no tumba el lote.

use super::errores::{ok, ErrorHTTP, Res};
use super::http::Peticion;
use super::{Json, Servidor};
use crate::firma;
use crate::sii;
use regex::Regex;
use serde_json::{json, Value};

/// Estados de envío FINALES.
const ESTADOS_RECHAZO: [&str; 5] = ["RCH", "RSC", "RFR", "RCT", "RLV"];

/// `seguimiento._campo`: int si es número, texto si no, null si falta.
fn campo(texto: &str, tag: &str) -> Value {
    let re = Regex::new(&format!("<{tag}>([^<]*)</{tag}>")).expect("re");
    match re.captures(texto) {
        None => Value::Null,
        Some(c) => {
            let v = c[1].trim().to_string();
            match v.parse::<i64>() {
                Ok(n) => json!(n),
                Err(_) => Value::String(v),
            }
        }
    }
}

/// `seguimiento.estado_detallado`: estado de UN envío con el desglose por DTE.
fn estado_detallado(
    cli: &mut sii::http::Cliente,
    track: i64,
    rut: &str,
    dv: &str,
) -> Result<Value, String> {
    let e = cli
        .estado_track(track, rut, dv)
        .map_err(|e| e.to_string())?;
    let des = crate::htmlent::unescape(&e.crudo);
    let tiene_body = des.contains("<TIPO_DOCTO>");
    Ok(json!({
        "track_id": track, "estado": e.estado, "glosa": e.glosa,
        "informados": campo(&des, "INFORMADOS"), "aceptados": campo(&des, "ACEPTADOS"),
        "rechazados": campo(&des, "RECHAZADOS"), "reparos": campo(&des, "REPAROS"),
        "resuelto": tiene_body || ESTADOS_RECHAZO.contains(&e.estado.as_str()),
    }))
}

pub fn estado_lote(s: &Servidor, p: &mut Peticion) -> Res {
    let j = Json::leer(p)?;
    let tracks: Vec<i64> = match j.get("track_ids") {
        None => return Err(ErrorHTTP::faltan(&["track_ids"])),
        Some(Value::Array(a)) => a.iter().map(super::entero).collect(),
        Some(_) => return Err(ErrorHTTP::json_invalido()),
    };
    let Some(rut) = j.texto("rut_empresa")? else {
        return Err(ErrorHTTP::faltan(&["rut_empresa"]));
    };
    let Some(cert_id) = j.entero("cert_id")? else {
        return Err(ErrorHTTP::faltan(&["cert_id"]));
    };
    let mut ambiente = j.texto_o("ambiente", "")?;
    if ambiente.is_empty() {
        ambiente = "certificacion".into();
    }
    let cuenta = s.cuenta_id(p);
    let (p12, clave) = s
        .descifrar_certificado(cert_id, cuenta)
        .map_err(|_| ErrorHTTP::no_encontrado(format!("Certificado {cert_id} no encontrado")))?;
    let cert = firma::cargar_p12(&p12, &clave)
        .map_err(|e| ErrorHTTP::certificado(format!("No se pudo cargar el certificado: {e}")))?;
    let (num, dv) = rut
        .split_once('-')
        .map(|(a, b)| (a.to_string(), b.to_string()))
        .unwrap_or((rut.clone(), String::new()));
    let mut cli = sii::http::Cliente::nuevo(&ambiente, cert).map_err(ErrorHTTP::validacion)?;
    let detalles: Vec<Value> = tracks
        .iter()
        .map(|t| {
            estado_detallado(&mut cli, *t, &num, &dv)
                .unwrap_or_else(|e| json!({"track_id": t, "error": e, "resuelto": false}))
        })
        .collect();
    let suma = |campo: &str| -> i64 {
        detalles
            .iter()
            .filter_map(|d| d.get(campo).and_then(Value::as_i64))
            .sum()
    };
    let resueltos = detalles
        .iter()
        .filter(|d| d.get("resuelto").and_then(Value::as_bool).unwrap_or(false))
        .count();
    ok(
        json!({"total": detalles.len(), "resueltos": resueltos, "pendientes": detalles.len() - resueltos,
        "aceptados": suma("aceptados"), "rechazados": suma("rechazados"), "reparos": suma("reparos"),
        "todos_resueltos": resueltos == detalles.len() && !detalles.is_empty(), "detalles": detalles}),
    )
}
