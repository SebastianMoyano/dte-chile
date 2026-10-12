//! Rutas solo-Go/Rust del portal con el certificado del keystore (lo que el MCP de Python hacía
//! con core/ directamente): timbrajes, situación, software, empresas del certificado,
//! anulables, anular y solicitar folios. Todas POST con JSON {cert_id, rut, …, ambiente}.

use super::errores::{ok, ErrorHTTP, Res};
use super::http::Peticion;
use super::{Json, Prot, Servidor};
use crate::portal::{self, Cliente};
use crate::sii;
use crate::xsd;
use base64::Engine;
use serde_json::{json, Value};

pub fn rutas(s: &mut Servidor) {
    s.ruta("POST /api/v1/portal/timbrajes", Prot::Protegida, timbrajes);
    s.ruta("POST /api/v1/portal/situacion", Prot::Protegida, situacion);
    s.ruta("POST /api/v1/portal/software", Prot::Protegida, software);
    s.ruta("POST /api/v1/portal/empresas", Prot::Protegida, empresas);
    s.ruta("POST /api/v1/portal/anulables", Prot::Protegida, anulables);
    s.ruta("POST /api/v1/portal/anular", Prot::Protegida, anular);
    s.ruta("POST /api/v1/portal/solicitar", Prot::Protegida, solicitar);
    s.ruta(
        "POST /api/v1/dte/enviar-keystore",
        Prot::Protegida,
        enviar_dte_keystore,
    );
}

struct Entrada {
    rut: String,
    tipo_dte: i64,
    tipos: Vec<i32>,
    ambiente: String,
    folio_desde: i64,
    folio_hasta: i64,
    motivo: String,
    cantidad: i64,
    forzar: bool,
}

/// Lee el cuerpo, saca el certificado del keystore y abre sesión en el portal.
fn abierto(s: &Servidor, p: &Peticion, exige_rut: bool) -> Result<(Entrada, Cliente), ErrorHTTP> {
    let j = Json::leer(p)?;
    let Some(cert_id) = j.entero("cert_id")? else {
        return Err(ErrorHTTP::faltan(&["cert_id"]));
    };
    let rut = j.texto_o("rut", "")?;
    if exige_rut && rut.is_empty() {
        return Err(ErrorHTTP::faltan(&["rut"]));
    }
    let mut ambiente = j.texto_o("ambiente", "")?;
    if ambiente.is_empty() {
        ambiente = s.cfg.sii_ambiente.clone();
    }
    let tipos: Vec<i32> = match j.get("tipos") {
        Some(Value::Array(a)) => a.iter().map(|v| super::entero(v) as i32).collect(),
        _ => Vec::new(),
    };
    let e = Entrada {
        rut,
        tipo_dte: j.entero_o("tipo_dte", 0)?,
        tipos,
        ambiente,
        folio_desde: j.entero_o("folio_desde", 0)?,
        folio_hasta: j.entero_o("folio_hasta", 0)?,
        motivo: j.texto_o("motivo", "")?,
        cantidad: j.entero_o("cantidad", 0)?,
        forzar: j.logico_o("forzar", false)?,
    };
    let cuenta = s.cuenta_id(p);
    let (cert_pem, key_pem) = s
        .pem_del_keystore(cert_id, cuenta)
        .map_err(ErrorHTTP::no_encontrado)?;
    let abrir = || -> Result<Cliente, String> {
        let mut c = Cliente::nuevo(
            cert_pem.as_bytes(),
            key_pem.as_bytes(),
            portal::base_de(&e.ambiente),
        )?;
        c.autenticar("")?;
        Ok(c)
    };
    let cli = abrir().map_err(|er| {
        ErrorHTTP::sii_comunicacion(format!("No se pudo abrir sesión en el SII: {er}"))
    })?;
    Ok((e, cli))
}

fn responder<T: serde::Serialize>(r: Result<T, String>) -> Res {
    match r {
        Ok(v) => ok(serde_json::to_value(v).unwrap_or(Value::Null)),
        Err(e) => Err(ErrorHTTP::sii_comunicacion(format!(
            "No se pudo consultar el SII: {e}"
        ))),
    }
}

fn timbrajes(s: &Servidor, p: &mut Peticion) -> Res {
    let (e, mut c) = abierto(s, p, true)?;
    responder(c.consultar_timbrajes(&e.rut, e.tipo_dte as i32))
}

fn situacion(s: &Servidor, p: &mut Peticion) -> Res {
    let (e, mut c) = abierto(s, p, true)?;
    responder(c.situacion_folios(&e.rut, &e.tipos))
}

fn software(s: &Servidor, p: &mut Peticion) -> Res {
    let (e, mut c) = abierto(s, p, true)?;
    responder(c.datos_software_de(&e.rut, portal::base_de(&e.ambiente)))
}

fn empresas(s: &Servidor, p: &mut Peticion) -> Res {
    let (_, mut c) = abierto(s, p, false)?;
    responder(c.empresas_asociadas())
}

fn anulables(s: &Servidor, p: &mut Peticion) -> Res {
    let (e, mut c) = abierto(s, p, true)?;
    responder(c.listar_anulables(&e.rut, e.tipo_dte as i32))
}

/// ACCIÓN REAL E IRREVERSIBLE sobre folios no recepcionados.
fn anular(s: &Servidor, p: &mut Peticion) -> Res {
    let (e, mut c) = abierto(s, p, true)?;
    if e.folio_desde == 0 || e.folio_hasta == 0 {
        return Err(ErrorHTTP::faltan(&["folio_desde", "folio_hasta"]));
    }
    responder(c.anular_folios(
        &e.rut,
        e.tipo_dte as i32,
        e.folio_desde,
        e.folio_hasta,
        &e.motivo,
    ))
}

/// TIMBRA folios (consume cupo). Devuelve {obtenido, info, caf_xml}.
fn solicitar(s: &Servidor, p: &mut Peticion) -> Res {
    let (e, mut c) = abierto(s, p, true)?;
    let (caf, info) = c
        .solicitar_folios(&e.rut, e.tipo_dte as i32, e.cantidad, true, e.forzar)
        .map_err(|er| ErrorHTTP::sii_comunicacion(format!("No se pudo consultar el SII: {er}")))?;
    let caf_xml = caf
        .as_ref()
        .map(|b| Value::String(String::from_utf8_lossy(b).into_owned()))
        .unwrap_or(Value::Null);
    ok(json!({"obtenido": caf.is_some(), "info": info, "caf_xml": caf_xml}))
}

/// `/dte/enviar` con el certificado del keystore (cert_id) en vez del .p12.
fn enviar_dte_keystore(s: &Servidor, p: &mut Peticion) -> Res {
    let j = Json::leer(p)?;
    let (xml_b64, rut, cert_id) = (
        j.texto("xml_envio_b64")?,
        j.texto("rut_empresa")?,
        j.entero("cert_id")?,
    );
    if xml_b64.is_none() || rut.is_none() || cert_id.is_none() {
        let mut f = Vec::new();
        if cert_id.is_none() {
            f.push("cert_id");
        }
        if rut.is_none() {
            f.push("rut_empresa");
        }
        if xml_b64.is_none() {
            f.push("xml_envio_b64");
        }
        return Err(ErrorHTTP::faltan(&f));
    }
    let (xml_b64, rut, cert_id) = (
        xml_b64.unwrap_or_default(),
        rut.unwrap_or_default(),
        cert_id.unwrap_or(0),
    );
    let tipo = j.entero_o("tipo_dte", 0)?;
    let mut ambiente = j.texto_o("ambiente", "")?;
    if ambiente.is_empty() {
        ambiente = s.cfg.sii_ambiente.clone();
    }
    let cuenta = s.cuenta_id(p);
    let cert = s
        .certificado_del_keystore(cert_id, cuenta)
        .map_err(ErrorHTTP::no_encontrado)?;
    let xml = base64::engine::general_purpose::STANDARD
        .decode(&xml_b64)
        .map_err(|e| ErrorHTTP::validacion(format!("xml_envio_b64 no es base64 válido: {e}")))?;
    xsd::validar_error(&xml).map_err(|e| {
        ErrorHTTP::validacion(format!("El XML no cumple el esquema XSD del SII: {e}"))
    })?;
    let (num, dv) = portal::separar_rut(&rut);
    if tipo == 39 || tipo == 41 {
        let mut cli =
            sii::boleta::ClienteBoleta::nuevo(&ambiente, cert).map_err(ErrorHTTP::validacion)?;
        let (track, _) = cli
            .enviar(&xml, &num, &dv)
            .map_err(|e| ErrorHTTP::sii_comunicacion(e.to_string()))?;
        s.marcar_enviados_por_xml(&xml, &track, &ambiente);
        return ok(
            json!({"track_id": track, "mensaje": format!("Envío de boletas recibido. TrackID: {track}"), "ambiente": ambiente}),
        );
    }
    let mut cli = sii::http::Cliente::nuevo(&ambiente, cert).map_err(ErrorHTTP::validacion)?;
    let (track, _) = cli.enviar_dte(&xml, &num, &dv).map_err(|e| {
        ErrorHTTP::sii_comunicacion(format!("Error de comunicación con el SII: {e}"))
    })?;
    s.marcar_enviados_por_xml(&xml, &track.to_string(), &ambiente);
    ok(
        json!({"track_id": track, "mensaje": format!("Envío exitoso. TrackID: {track}"), "ambiente": ambiente}),
    )
}
