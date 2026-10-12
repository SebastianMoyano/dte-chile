//! POST /api/v1/dte/validar-xml de api/routes/dte.py, con `crate::xsd` en vez de lxml (mismo
//! veredicto; los textos de los errores son los de este validador).

use super::errores::{ok, ErrorHTTP, Res};
use super::http::Peticion;
use super::{Json, Prot, Servidor};
use base64::Engine;
use serde_json::json;

pub fn rutas(s: &mut Servidor) {
    s.ruta("POST /api/v1/dte/validar-xml", Prot::Protegida, validar_xml);
}

fn validar_xml(_s: &Servidor, p: &mut Peticion) -> Res {
    let j = Json::leer(p)?;
    let Some(b64) = j.texto("xml_b64")? else {
        return Err(ErrorHTTP::faltan(&["xml_b64"]));
    };
    let raw = base64::engine::general_purpose::STANDARD
        .decode(&b64)
        .map_err(|e| ErrorHTTP::validacion(format!("El XML no es Base64 válido: {e}")))?;
    let res = crate::xsd::validar(&raw);
    let mensaje = if res.valido {
        "XML válido según esquema XSD del SII.".to_string()
    } else {
        format!("XML inválido: {} error(es).", res.errores.len())
    };
    ok(
        json!({"valido": res.valido, "tipo_xml": res.tipo_xml, "errores": res.mensajes(), "mensaje": mensaje}),
    )
}
