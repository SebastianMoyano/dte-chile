//! Rutas "sueltas" de api/routes/dte.py: generar un DTE firmado sin tocar la BD, y el PDF desde
//! los datos (sin pasar por la emisión).

use super::caf::leer_archivo_form;
use super::errores::{ok, ErrorHTTP, Res};
use super::http::{parsear_formulario, Peticion, Respuesta};
use super::{bytes_latin1, Prot, Servidor};
use crate::emision::{documento_desde_json, monto_total_de};
use crate::firma;
use crate::pdf;
use crate::ted;
use crate::xmlgen::{self, Documento};
use base64::Engine;
use serde_json::{json, Value};

pub fn rutas(s: &mut Servidor) {
    s.ruta("POST /api/v1/dte/generar", Prot::Protegida, generar_dte);
    s.ruta(
        "POST /api/v1/dte/generar-simple",
        Prot::Protegida,
        generar_simple,
    );
    s.ruta("POST /api/v1/dte/pdf", Prot::Protegida, pdf_desde_datos);
    s.ruta("POST /api/v1/dte/pdf-simple", Prot::Protegida, pdf_simple);
}

const B64: base64::engine::GeneralPurpose = base64::engine::general_purpose::STANDARD;

/// `_parse_dte_input` sobre el campo `dte_json` del multipart.
fn documento_desde_form(f: &super::http::Formulario) -> Result<Documento, ErrorHTTP> {
    if !f.tiene("dte_json") {
        return Err(ErrorHTTP::faltan(&["dte_json"]));
    }
    documento_desde_json(f.valor("dte_json").as_bytes())
        .map_err(|e| ErrorHTTP::validacion(format!("Datos del DTE inválidos: {e}")))
}

/// `documentoDesdeJSON`: un DTEInput del cuerpo JSON (422 pydantic-like si no sirve).
fn documento_desde_cuerpo(p: &Peticion) -> Result<Documento, ErrorHTTP> {
    let v: Value = serde_json::from_slice(&p.cuerpo).map_err(|_| ErrorHTTP::json_invalido())?;
    crate::emision::documento_desde_valor(&v)
        .map_err(|e| ErrorHTTP::pydantic("body", "", &e, "value_error"))
}

/// POST /dte/generar: multipart con dte_json, certificado_p12, password_certificado y caf_xml
/// (opcional, para el TED). Firma por core/sobre.py (standalone, #T{tipo}F{folio}).
fn generar_dte(s: &Servidor, p: &mut Peticion) -> Res {
    let (f, p12, _) = leer_archivo_form(p, "certificado_p12")?;
    let mut d = documento_desde_form(&f)?;
    if !f.tiene("password_certificado") {
        return Err(ErrorHTTP::faltan(&["password_certificado"]));
    }
    let cert = firma::cargar_p12(&p12, &f.valor("password_certificado"))
        .map_err(|e| ErrorHTTP::certificado(format!("No se pudo cargar el certificado: {e}")))?;
    d.marca = s.marca();
    if let Some(a) = f.archivo("caf_xml").filter(|a| !a.nombre.is_empty()) {
        let caf = ted::parsear_caf(&String::from_utf8_lossy(&a.datos))
            .map_err(|e| ErrorHTTP::caf(format!("No se pudo procesar el CAF: {e}")))?;
        if caf.tipo_dte != d.tipo_dte {
            return Err(ErrorHTTP::caf(format!(
                "El CAF es para el tipo {} pero el DTE es tipo {}.",
                caf.tipo_dte, d.tipo_dte
            )));
        }
        if d.folio < caf.folio_desde || d.folio > caf.folio_hasta {
            return Err(ErrorHTTP::folio(format!(
                "El folio {} no está en el rango del CAF [{}-{}].",
                d.folio, caf.folio_desde, caf.folio_hasta
            )));
        }
        let primer = d
            .items
            .first()
            .map(|i| i.nombre.clone())
            .unwrap_or_else(|| "Sin Items".into());
        d.ted = ted::generar(
            &caf,
            &ted::Datos {
                folio: d.folio,
                rut_emisor: d.emisor.rut.clone(),
                rut_receptor: d.receptor.rut.clone(),
                tipo_dte: d.tipo_dte,
                fecha_emision: d.fecha_emision.clone(),
                monto_total: monto_total_de(&d),
                razon_social_receptor: d.receptor.razon_social.clone(),
                primer_item: primer,
                marca: d.marca.clone(),
                primer_item_literal: false,
            },
        )
        .map_err(|e| ErrorHTTP::caf(format!("No se pudo generar el TED: {e}")))?;
    }
    let arbol = xmlgen::generar_dte(&d);
    let firmado = cert
        .firmar_dte(
            &arbol.string(),
            &arbol.hijos[0].string(),
            d.tipo_dte,
            d.folio,
        )
        .map_err(|e| ErrorHTTP::certificado(format!("No se pudo firmar el DTE: {e}")))?;
    ok(
        json!({"folio": d.folio, "tipo_dte": d.tipo_dte, "monto_total": monto_total_de(&d),
        "xml_b64": B64.encode(bytes_latin1(&firmado)),
        "mensaje": format!("DTE Tipo {} Folio {} generado y firmado.", d.tipo_dte, d.folio)}),
    )
}

/// POST /dte/generar-simple: el <DTE> sin firma ni TED (desarrollo).
fn generar_simple(s: &Servidor, p: &mut Peticion) -> Res {
    let mut d = documento_desde_cuerpo(p)?;
    d.marca = s.marca();
    let xml = format!(
        "<?xml version=\"1.0\" encoding=\"ISO-8859-1\"?>\n{}",
        xmlgen::generar_dte(&d).string()
    );
    ok(
        json!({"folio": d.folio, "tipo_dte": d.tipo_dte, "monto_total": monto_total_de(&d),
        "xml_b64": B64.encode(bytes_latin1(&xml)),
        "mensaje": format!("DTE Tipo {} Folio {} generado (sin firma real).", d.tipo_dte, d.folio)}),
    )
}

fn responder_pdf(s: &Servidor, d: &Documento, ted_xml: &str) -> Res {
    let (fecha, num) = s.resolucion_emisor(&d.emisor.rut, &s.cfg.sii_ambiente);
    let b = pdf::carta(
        d,
        ted_xml,
        &pdf::Opciones {
            ambiente: s.cfg.sii_ambiente.clone(),
            resolucion_fecha: fecha,
            resolucion_num: num,
            hoy: String::new(),
        },
    )
    .map_err(|e| ErrorHTTP::validacion(format!("No se pudo dibujar el PDF: {e}")))?;
    Ok(Respuesta::binario(200, "application/pdf", b).con(
        "Content-Disposition",
        &format!(
            "attachment; filename=\"DTE-{}-{}.pdf\"",
            d.tipo_dte, d.folio
        ),
    ))
}

/// POST /dte/pdf: multipart dte_json + ted_xml (opcional) → PDF carta.
fn pdf_desde_datos(s: &Servidor, p: &mut Peticion) -> Res {
    let Some(f) = parsear_formulario(p) else {
        return Err(ErrorHTTP::faltan(&["dte_json"]));
    };
    let d = documento_desde_form(&f)?;
    responder_pdf(s, &d, &f.valor("ted_xml"))
}

/// POST /dte/pdf-simple: DTEInput en JSON → PDF carta sin timbre.
fn pdf_simple(s: &Servidor, p: &mut Peticion) -> Res {
    let d = documento_desde_cuerpo(p)?;
    responder_pdf(s, &d, "")
}
