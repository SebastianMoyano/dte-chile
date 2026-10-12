//! Cliente de los web services del SII (semilla → token → envío → estado), réplica de
//! `core/sii.py` vía `nucleo/sii` (Go). La semilla se firma con XMLDSig "enveloped" (el formato
//! de `core/crypto.py::firmar_documento_xml`, distinto del de los DTE): se prueba byte a byte
//! contra `tests/dorado/sii/semilla_firmada.xml`.

pub mod boleta;
pub mod http;

use crate::c14n::{self, Alcance};
use crate::firma::Certificado;
use crate::ted::firmar_sha1;
use base64::Engine;
use regex::Regex;
use rsa::traits::PublicKeyParts;
use sha1::{Digest, Sha1};

pub const CERTIFICACION: &str = "certificacion";
pub const PRODUCCION: &str = "produccion";
/// Lo que el SII valida en el User-Agent es el token "PROG 1.0" (core/config.py).
pub const USER_AGENT: &str =
    "Mozilla/5.0 (compatible; PROG 1.0; +https://github.com/SebastianMoyano/dte-chile)";
const NS_DSIG: &str = "http://www.w3.org/2000/09/xmldsig#";

pub fn host(ambiente: &str) -> Option<&'static str> {
    match ambiente {
        CERTIFICACION => Some("https://maullin.sii.cl"),
        PRODUCCION => Some("https://palena.sii.cl"),
        _ => None,
    }
}

fn b64(b: &[u8]) -> String {
    base64::engine::general_purpose::STANDARD.encode(b)
}

/// `_firmar_semilla` + `firmar_documento_xml`: el `<getToken>` con la semilla, digest del
/// elemento canonicalizado (con sus saltos de línea), SignedInfo con transform
/// enveloped-signature, firma RSA-SHA1, KeyInfo sin envolver a 64.
pub fn firmar_semilla(cert: &Certificado, semilla: &str) -> Result<String, String> {
    let doc = format!("<getToken>\n<item>\n<Semilla>{semilla}</Semilla>\n</item>\n</getToken>");
    let firma_xml = firma_get_token(cert, &doc)?;
    // lxml anexa la firma tras el último hijo: el "\n" (cola de <item>) queda antes de <Signature>
    // y no hay nada entre </Signature> y </getToken>.
    Ok(format!("<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<getToken>\n<item>\n<Semilla>{semilla}</Semilla>\n</item>\n{firma_xml}</getToken>"))
}

/// `firmar_documento_xml` sobre un `<getToken>`: digest del documento canonicalizado (tal
/// cual, con o sin saltos de línea), SignedInfo con transform enveloped-signature, firma
/// RSA-SHA1, KeyInfo sin envolver a 64. Devuelve solo el `<Signature>`.
pub fn firma_get_token(cert: &Certificado, doc: &str) -> Result<String, String> {
    let can = c14n::canonicalizar(doc, &Alcance::new())?;
    let dig = Sha1::digest(&can);
    let signed_info = format!(
        "<SignedInfo xmlns=\"{NS_DSIG}\">\n<CanonicalizationMethod Algorithm=\"http://www.w3.org/TR/2001/REC-xml-c14n-20010315\"/>\n<SignatureMethod Algorithm=\"http://www.w3.org/2000/09/xmldsig#rsa-sha1\"/>\n<Reference URI=\"\">\n<Transforms>\n<Transform Algorithm=\"http://www.w3.org/2000/09/xmldsig#enveloped-signature\"/>\n</Transforms>\n<DigestMethod Algorithm=\"http://www.w3.org/2000/09/xmldsig#sha1\"/>\n<DigestValue>{}</DigestValue>\n</Reference>\n</SignedInfo>",
        b64(&dig)
    );
    let can_si = c14n::canonicalizar(&signed_info, &Alcance::new())?;
    let sig = firmar_sha1(&cert.clave, &can_si)?;
    let modulo = b64(&cert.clave.n().to_bytes_be());
    let exp = b64(&cert.clave.e().to_bytes_be());
    // Dentro de <Signature> el xmlns del SignedInfo es redundante y lxml no lo serializa (sí
    // está en lo canonicalizado y firmado, arriba).
    let signed_info_embebido = signed_info.replacen(&format!(" xmlns=\"{NS_DSIG}\""), "", 1);
    Ok(format!(
        "<Signature xmlns=\"{NS_DSIG}\">\n{signed_info_embebido}\n<SignatureValue>{}</SignatureValue>\n<KeyInfo>\n<KeyValue>\n<RSAKeyValue>\n<Modulus>{modulo}</Modulus>\n<Exponent>{exp}</Exponent>\n</RSAKeyValue>\n</KeyValue>\n<X509Data>\n<X509Certificate>{}</X509Certificate>\n</X509Data>\n</KeyInfo>\n</Signature>",
        b64(&sig),
        b64(&cert.cert_der)
    ))
}

/// Extrae `<TAG>…</TAG>` de la respuesta SOAP, que suele venir con el XML interno escapado
/// dentro de `<getSeedReturn>`/`<getTokenReturn>` (por eso se des-escapa antes).
pub fn valor(respuesta: &str, tag: &str) -> String {
    let des = crate::htmlent::unescape(respuesta);
    let re = Regex::new(&format!(
        r"(?s)<(?:[A-Za-z0-9]+:)?{tag}[^>]*>([^<]*)</(?:[A-Za-z0-9]+:)?{tag}>"
    ))
    .expect("regex");
    re.captures(&des)
        .map(|m| m[1].trim().to_string())
        .unwrap_or_default()
}

/// El SII respondió, pero sin lo esperado (sin semilla/token, STATUS distinto de 0). Es el
/// `ValueError` de core/sii.py, que la API traduce a 422 sii_rechazo; los errores de red o
/// HTTP son 502 sii_comunicacion.
#[derive(Debug)]
pub enum Error {
    Respuesta(String),
    Comunicacion(String),
}

impl std::fmt::Display for Error {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Error::Respuesta(s) | Error::Comunicacion(s) => write!(f, "{s}"),
        }
    }
}

impl std::error::Error for Error {}

/// Estado del envío por TrackID. OJO: EPR = "Envío Procesado", NO "aceptado": el veredicto son
/// Aceptados/Rechazados/Reparos.
#[derive(Debug, Clone, Default, serde::Serialize)]
pub struct Estado {
    pub track_id: i64,
    pub estado: String,
    pub glosa: String,
    pub informados: i64,
    pub aceptados: i64,
    pub rechazados: i64,
    pub reparos: i64,
    #[serde(skip)]
    pub crudo: String,
}

#[cfg(test)]
mod tests {
    use super::*;

    fn cert() -> Option<Certificado> {
        let p12 = std::fs::read(format!(
            "{}/../tests/dorado/fixtures/cert_demo.p12",
            env!("CARGO_MANIFEST_DIR")
        ))
        .ok()?;
        crate::firma::cargar_p12(&p12, "demo").ok()
    }

    fn comparar(got: &str, esperado: &str) {
        if got != esperado {
            let i = got
                .bytes()
                .zip(esperado.bytes())
                .take_while(|(a, b)| a == b)
                .count();
            let lo = i.saturating_sub(60);
            panic!(
                "difiere en el byte {i}\nesperado: …{}…\nobtenido: …{}…",
                &esperado[lo..(i + 60).min(esperado.len())],
                &got[lo..(i + 60).min(got.len())]
            );
        }
    }

    /// La semilla firmada debe ser byte a byte la de Python (tests/dorado/sii/semilla_firmada.xml).
    #[test]
    fn firmar_semilla_igual_a_python() {
        let Some(c) = cert() else { return };
        let base = format!("{}/../tests/dorado/sii", env!("CARGO_MANIFEST_DIR"));
        let sem = std::fs::read_to_string(format!("{base}/semilla.txt")).unwrap();
        let esperado = std::fs::read_to_string(format!("{base}/semilla_firmada.xml")).unwrap();
        comparar(&firmar_semilla(&c, sem.trim()).unwrap(), &esperado);
        let esperado_b =
            std::fs::read_to_string(format!("{base}/semilla_firmada_boleta.xml")).unwrap();
        comparar(
            &boleta::firmar_semilla_boleta(&c, sem.trim()).unwrap(),
            &esperado_b,
        );
    }

    #[test]
    fn extrae_valores_soap() {
        assert_eq!(valor("<ns:SEMILLA>  abc </ns:SEMILLA>", "SEMILLA"), "abc");
        assert_eq!(
            valor(
                "<getSeedReturn>&lt;SEMILLA&gt;42&lt;/SEMILLA&gt;</getSeedReturn>",
                "SEMILLA"
            ),
            "42"
        );
        assert_eq!(
            boleta::texto_de(
                "<x><ESTADO>00</ESTADO><SEMILLA> 123 </SEMILLA></x>",
                "SEMILLA"
            ),
            "123"
        );
    }
}
