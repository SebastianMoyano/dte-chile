//! Reconstruye el documento desde el XML firmado (`core/dte_xml.py`, `nucleo/pdf/desdexml.go`).
//! El TED se devuelve verbatim, sin el xmlns heredado, para que el PDF417 lleve exactamente lo
//! que se firmó.

use crate::xmlgen::{Documento, Emisor, Item, Receptor, Referencia};
use crate::xsd::arbol::{parsear_arbol, Nodo};
use regex::Regex;
use std::sync::OnceLock;

static RE_DOCUMENTO: OnceLock<Regex> = OnceLock::new();
static RE_TED: OnceLock<Regex> = OnceLock::new();
static RE_DECL: OnceLock<Regex> = OnceLock::new();

fn re(cache: &'static OnceLock<Regex>, pat: &str) -> &'static Regex {
    cache.get_or_init(|| Regex::new(pat).expect("regex"))
}

fn latin1(b: &[u8]) -> String {
    b.iter().map(|&c| c as char).collect()
}

fn numero(s: &str, def: f64) -> f64 {
    let s = s.trim();
    if s.is_empty() {
        return def;
    }
    s.parse().unwrap_or(def)
}

fn entero(s: &str, def: i64) -> i64 {
    let s = s.trim();
    if s.is_empty() {
        return def;
    }
    s.parse().unwrap_or(def)
}

fn hijo<'a>(n: &'a Nodo, local: &str) -> Option<&'a Nodo> {
    n.hijos.iter().find(|h| h.nombre.local == local)
}

fn texto(n: Option<&Nodo>, local: &str) -> String {
    n.and_then(|n| hijo(n, local))
        .map(|h| h.texto.clone())
        .unwrap_or_default()
}

/// `documento_desde_xml`: `(Documento, TED)` desde el `<DTE>` firmado (o el sobre que lo
/// contiene; toma el primero). El XML puede venir como bytes ISO-8859-1 sin declaración (lo que
/// guarda la base) o como texto con declaración.
pub fn desde_xml(raw: &[u8]) -> Result<(Documento, String), String> {
    let texto_xml =
        if re(&RE_DECL, r"(?s)^\s*<\?xml[^>]*\?>").is_match(&latin1(&raw[..raw.len().min(200)])) {
            let cabeza = latin1(&raw[..raw.len().min(80)]).to_uppercase();
            if cabeza.contains("ISO-8859-1") {
                latin1(raw)
            } else {
                String::from_utf8_lossy(raw).into_owned()
            }
        } else {
            latin1(raw)
        };
    let m = re(&RE_DOCUMENTO, r"(?s)<Documento\b.*?</Documento>")
        .find(&texto_xml)
        .ok_or("El XML no contiene un <Documento> del SII")?
        .as_str();
    let raiz = parsear_arbol(m.as_bytes())?;
    let enc = hijo(&raiz, "Encabezado");
    let id = enc.and_then(|e| hijo(e, "IdDoc"));
    let e = enc.and_then(|e| hijo(e, "Emisor"));
    let r = enc.and_then(|e| hijo(e, "Receptor"));
    let tipo = entero(&texto(id, "TipoDTE"), 0) as i32;
    let es_boleta = tipo == 39 || tipo == 41;
    let razon = match texto(e, "RznSoc") {
        s if s.is_empty() => texto(e, "RznSocEmisor"),
        s => s,
    };
    let giro = match texto(e, "GiroEmis") {
        s if s.is_empty() => texto(e, "GiroEmisor"),
        s => s,
    };
    let rzn_recep = match texto(r, "RznSocRecep") {
        s if s.is_empty() => "CONSUMIDOR FINAL".to_string(),
        s => s,
    };
    let mut d = Documento {
        tipo_dte: tipo,
        folio: entero(&texto(id, "Folio"), 0) as i32,
        fecha_emision: texto(id, "FchEmis"),
        forma_pago: entero(&texto(id, "FmaPago"), 1) as i32,
        fecha_vencimiento: texto(id, "FchVenc"),
        indicador_servicio: entero(&texto(id, "IndServicio"), 0) as i32,
        emisor: Emisor {
            rut: texto(e, "RUTEmisor"),
            razon_social: razon,
            giro,
            codigo_actividad: entero(&texto(e, "Acteco"), 0),
            direccion: texto(e, "DirOrigen"),
            comuna: texto(e, "CmnaOrigen"),
            ciudad: texto(e, "CiudadOrigen"),
            telefono: texto(e, "Telefono"),
            email: texto(e, "CorreoEmisor"),
        },
        receptor: Receptor {
            rut: texto(r, "RUTRecep"),
            razon_social: rzn_recep,
            giro: texto(r, "GiroRecep"),
            direccion: texto(r, "DirRecep"),
            comuna: texto(r, "CmnaRecep"),
            ciudad: texto(r, "CiudadRecep"),
            email: texto(r, "CorreoRecep"),
        },
        ..Default::default()
    };
    for (i, det) in raiz
        .hijos
        .iter()
        .filter(|h| h.nombre.local == "Detalle")
        .enumerate()
    {
        let det = Some(det);
        let cant = if es_boleta { 0.0 } else { 1.0 };
        let mut it = Item {
            numero_linea: entero(&texto(det, "NroLinDet"), i as i64 + 1) as i32,
            nombre: texto(det, "NmbItem"),
            descripcion: texto(det, "DscItem"),
            cantidad: numero(&texto(det, "QtyItem"), cant),
            unidad_medida: texto(det, "UnmdItem"),
            precio_unitario: numero(&texto(det, "PrcItem"), 0.0),
            descuento_pct: numero(&texto(det, "DescuentoPct"), 0.0),
            descuento_monto: numero(&texto(det, "DescuentoMonto"), 0.0),
            exento: texto(det, "IndExe").trim() == "1",
            codigo_producto: String::new(),
        };
        if let Some(c) = det.and_then(|d| hijo(d, "CdgItem")) {
            it.codigo_producto = texto(Some(c), "VlrCodigo");
        }
        d.items.push(it);
    }
    for rf in raiz.hijos.iter().filter(|h| h.nombre.local == "Referencia") {
        let rf = Some(rf);
        let t = texto(rf, "TpoDocRef").trim().to_string();
        let fch = texto(rf, "FchRef");
        if t.is_empty() || fch.is_empty() || t.parse::<i64>().is_err() {
            continue;
        }
        d.referencias.push(Referencia {
            numero_linea: entero(&texto(rf, "NroLinRef"), 1) as i32,
            tipo_doc_ref: entero(&t, 0) as i32,
            folio_ref: entero(&texto(rf, "FolioRef"), 0),
            fecha_doc_ref: fch,
            codigo_ref: entero(&texto(rf, "CodRef"), 1) as i32,
            razon_ref: texto(rf, "RazonRef"),
        });
    }
    let ted = re(&RE_TED, r"(?s)<TED\b.*?</TED>")
        .find(m)
        .map(|x| x.as_str())
        .unwrap_or("");
    let ted = ted.replacen(r#" xmlns="http://www.sii.cl/SiiDte""#, "", 1);
    Ok((d, ted))
}
