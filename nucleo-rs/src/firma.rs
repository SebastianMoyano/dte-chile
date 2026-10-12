//! Certificado PKCS#12 y firma XMLDSig enveloped (RSA-SHA1 + C14N 1.0) del DTE standalone y
//! del sobre, como `core/crypto.py::firmar_xml_sii`, `core/sobre.py` y `nucleo/firma` (Go).

use crate::c14n::{self, Alcance};
use crate::ted::{firmar_sha1, pem_a_der};
use base64::Engine;
use p12_keystore::{KeyStore, Pkcs12ImportPolicy};
use regex::Regex;
use rsa::pkcs1::DecodeRsaPrivateKey;
use rsa::pkcs8::DecodePrivateKey;
use rsa::traits::PublicKeyParts;
use rsa::RsaPrivateKey;
use sha1::{Digest, Sha1};
use std::collections::BTreeMap;
use std::sync::OnceLock;
use x509_cert::der::Decode;
use x509_cert::Certificate as CertX509;

pub const NS_DSIG: &str = "http://www.w3.org/2000/09/xmldsig#";
pub const NS_XSI: &str = "http://www.w3.org/2001/XMLSchema-instance";
pub const NS_SII: &str = "http://www.sii.cl/SiiDte";
pub const RUT_SII: &str = "60803000-K";

#[derive(Clone)]
pub struct Certificado {
    pub clave: RsaPrivateKey,
    /// El certificado X.509 en DER, tal cual (va en `<X509Certificate>`).
    pub cert_der: Vec<u8>,
    cert: CertX509,
}

fn b64(b: &[u8]) -> String {
    base64::engine::general_purpose::STANDARD.encode(b)
}

/// Carga el `.p12`/`.pfx` en memoria (PBES2/AES o PBES1/3DES, lo que traiga).
pub fn cargar_p12(datos: &[u8], clave: &str) -> Result<Certificado, String> {
    let ks = KeyStore::from_pkcs12(datos, clave, Pkcs12ImportPolicy::Relaxed)
        .map_err(|e| format!("no se pudo cargar el certificado: {e}"))?;
    let (_, cadena) = ks
        .private_key_chain()
        .ok_or("el archivo no trae una clave privada")?;
    let rk = RsaPrivateKey::from_pkcs8_der(cadena.key().as_der())
        .map_err(|e| format!("la clave del certificado no es RSA: {e}"))?;
    let cert_der = cadena
        .certs()
        .first()
        .ok_or("el archivo no trae el certificado")?
        .as_der()
        .to_vec();
    let cert = CertX509::from_der(&cert_der).map_err(|e| format!("certificado: {e}"))?;
    Ok(Certificado {
        clave: rk,
        cert_der,
        cert,
    })
}

/// Arma el certificado desde el par cert/clave en PEM (lo que entrega el keystore del motor
/// por `contexto-emision`). La clave puede venir PKCS#1 ("RSA PRIVATE KEY") o PKCS#8.
pub fn cargar_pem(cert_pem: &str, key_pem: &str) -> Result<Certificado, String> {
    let cert_der = pem_a_der(cert_pem).ok_or("cert_pem no es PEM")?;
    let cert = CertX509::from_der(&cert_der).map_err(|e| format!("certificado: {e}"))?;
    let kder = pem_a_der(key_pem).ok_or("key_pem no es PEM")?;
    let clave = match RsaPrivateKey::from_pkcs1_der(&kder) {
        Ok(k) => k,
        Err(e1) => RsaPrivateKey::from_pkcs8_der(&kder)
            .map_err(|e2| format!("clave privada ilegible: {e1} / {e2}"))?,
    };
    Ok(Certificado {
        clave,
        cert_der,
        cert,
    })
}

static RE_RUT: OnceLock<Regex> = OnceLock::new();
fn re_rut() -> &'static Regex {
    RE_RUT.get_or_init(|| Regex::new(r"(\d{7,8}-[\dkK])").expect("regex"))
}

/// OID chileno del RUT en el SAN: 1.3.6.1.4.1.8321.1
const OID_RUT_CL: [u8; 8] = [0x2B, 0x06, 0x01, 0x04, 0x01, 0xC1, 0x01, 0x01];

/// Un TLV DER: (tag, contenido, resto).
fn tlv(b: &[u8]) -> Option<(u8, &[u8], &[u8])> {
    if b.len() < 2 {
        return None;
    }
    let tag = b[0];
    let (len, ini) = if b[1] & 0x80 == 0 {
        (b[1] as usize, 2)
    } else {
        let n = (b[1] & 0x7F) as usize;
        if n == 0 || n > 4 || b.len() < 2 + n {
            return None;
        }
        let mut l = 0usize;
        for i in 0..n {
            l = (l << 8) | b[2 + i] as usize;
        }
        (l, 2 + n)
    };
    if b.len() < ini + len {
        return None;
    }
    Some((tag, &b[ini..ini + len], &b[ini + len..]))
}

/// PEM de un DER con el formato de `encoding/pem` de Go y de `cryptography`: líneas de 64.
pub fn pem(tipo: &str, der: &[u8]) -> String {
    let b = b64(der);
    let mut out = format!("-----BEGIN {tipo}-----\n");
    for ch in b.as_bytes().chunks(64) {
        out.push_str(std::str::from_utf8(ch).unwrap_or(""));
        out.push('\n');
    }
    out.push_str(&format!("-----END {tipo}-----\n"));
    out
}

fn fecha_x509(t: &x509_cert::time::Time) -> String {
    let d = t
        .to_system_time()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs() as i64;
    let dias = d.div_euclid(86400);
    let s = d.rem_euclid(86400);
    let (a, m, dd) = crate::almacen::civil_desde_dias(dias);
    format!(
        "{a:04}-{m:02}-{dd:02}T{:02}:{:02}:{:02}",
        s / 3600,
        (s % 3600) / 60,
        s % 60
    )
}

impl Certificado {
    /// Arma el certificado desde la clave y el DER (certificado autofirmado de la práctica).
    pub fn desde_der(clave: RsaPrivateKey, cert_der: Vec<u8>) -> Result<Certificado, String> {
        let cert = CertX509::from_der(&cert_der).map_err(|e| format!("certificado: {e}"))?;
        Ok(Certificado {
            clave,
            cert_der,
            cert,
        })
    }

    /// `NotAfter` en UTC: "YYYY-MM-DDTHH:MM:SS".
    pub fn not_after(&self) -> String {
        fecha_x509(&self.cert.tbs_certificate.validity.not_after)
    }

    pub fn not_before(&self) -> String {
        fecha_x509(&self.cert.tbs_certificate.validity.not_before)
    }

    pub fn subject(&self) -> String {
        self.cert.tbs_certificate.subject.to_string()
    }

    pub fn issuer(&self) -> String {
        self.cert.tbs_certificate.issuer.to_string()
    }

    /// El certificado en PEM (`CERTIFICATE`).
    pub fn cert_pem(&self) -> String {
        pem("CERTIFICATE", &self.cert_der)
    }

    /// La clave en PEM PKCS#1 (`RSA PRIVATE KEY`), como `x509.MarshalPKCS1PrivateKey` y
    /// `TraditionalOpenSSL` de cryptography.
    pub fn key_pem(&self) -> Result<String, String> {
        use rsa::pkcs1::EncodeRsaPrivateKey;
        let der = self
            .clave
            .to_pkcs1_der()
            .map_err(|e| format!("clave PKCS#1: {e}"))?;
        Ok(pem("RSA PRIVATE KEY", der.as_bytes()))
    }

    /// `CertificadoDigital.rut_emisor`: primero el CN, luego el SAN con el OID chileno.
    pub fn rut_emisor(&self) -> Result<String, String> {
        for rdn in self.cert.tbs_certificate.subject.0.iter() {
            for atv in rdn.0.iter() {
                if atv.oid.to_string() == "2.5.4.3" {
                    let cn = String::from_utf8_lossy(atv.value.value());
                    if let Some(m) = re_rut().find(&cn) {
                        return Ok(m.as_str().to_string());
                    }
                }
            }
        }
        if let Some(exts) = &self.cert.tbs_certificate.extensions {
            for ext in exts {
                if ext.extn_id.to_string() != "2.5.29.17" {
                    continue;
                }
                let Some((_, mut rest, _)) = tlv(ext.extn_value.as_bytes()) else {
                    continue;
                };
                while let Some((tag, gn, sig)) = tlv(rest) {
                    rest = sig;
                    if tag != 0xA0 {
                        continue; // otherName es [0] context-specific, constructed
                    }
                    let Some((otag, oid, after)) = tlv(gn) else {
                        continue;
                    };
                    if otag != 0x06 || oid != OID_RUT_CL {
                        continue;
                    }
                    let texto: String = after.iter().map(|&c| c as char).collect();
                    if let Some(m) = re_rut().find(&texto) {
                        return Ok(m.as_str().to_string());
                    }
                }
            }
        }
        Err("el certificado no trae el RUT ni en el CN ni en el SAN".into())
    }

    /// Produce el elemento `<Signature>` para un nodo referenciado.
    ///
    /// - `referenciado`: XML del elemento al que apunta la URI (serializado sin los xmlns
    ///   heredados; se le pasan en `ns_ref`, como lxml los renderiza al serializar el subárbol).
    /// - `ns_signed_info`: namespaces heredados por el `<SignedInfo>` en su posición final
    ///   (además del default xmldsig#): en el DTE ninguno; en el sobre, xsi.
    pub fn signature(
        &self,
        uri: &str,
        referenciado: &str,
        ns_ref: &Alcance,
        ns_signed_info: &Alcance,
    ) -> Result<String, String> {
        let can = c14n::canonicalizar(referenciado, ns_ref)
            .map_err(|e| format!("C14N del elemento referenciado: {e}"))?;
        let dig = Sha1::digest(&can);
        let signed_info = format!(
            "<SignedInfo><CanonicalizationMethod Algorithm=\"http://www.w3.org/TR/2001/REC-xml-c14n-20010315\"/><SignatureMethod Algorithm=\"http://www.w3.org/2000/09/xmldsig#rsa-sha1\"/><Reference URI=\"{}\"><Transforms><Transform Algorithm=\"http://www.w3.org/TR/2001/REC-xml-c14n-20010315\"/></Transforms><DigestMethod Algorithm=\"http://www.w3.org/2000/09/xmldsig#sha1\"/><DigestValue>{}</DigestValue></Reference></SignedInfo>",
            uri,
            b64(&dig)
        );
        let mut ns = Alcance::new();
        ns.insert(String::new(), NS_DSIG.to_string());
        for (k, v) in ns_signed_info {
            ns.insert(k.clone(), v.clone());
        }
        let can_si = c14n::canonicalizar(&signed_info, &ns)
            .map_err(|e| format!("C14N del SignedInfo: {e}"))?;
        let sig = firmar_sha1(&self.clave, &can_si)?;
        let modulo = b64(&self.clave.n().to_bytes_be());
        let exp = b64(&self.clave.e().to_bytes_be());
        let cert = b64(&self.cert_der);
        Ok(format!(
            "<Signature xmlns=\"{}\">{}<SignatureValue>{}</SignatureValue><KeyInfo><KeyValue><RSAKeyValue><Modulus>{}</Modulus><Exponent>{}</Exponent></RSAKeyValue></KeyValue><X509Data><X509Certificate>{}</X509Certificate></X509Data></KeyInfo></Signature>",
            NS_DSIG,
            signed_info,
            b64(&sig),
            envolver64(&modulo),
            envolver64(&exp),
            envolver64(&cert)
        ))
    }

    /// Recibe el `<DTE>` sin firmar serializado (con su xmlns) y el XML del `<Documento>` (sin
    /// xmlns) y devuelve el DTE firmado (`core/sobre.py::firmar_documento_standalone`).
    pub fn firmar_dte(
        &self,
        dte_sin_firma: &str,
        documento: &str,
        tipo: i32,
        folio: i32,
    ) -> Result<String, String> {
        let mut ns_ref = Alcance::new();
        ns_ref.insert(String::new(), NS_SII.to_string());
        let sig = self.signature(
            &format!("#T{tipo}F{folio}"),
            documento,
            &ns_ref,
            &Alcance::new(),
        )?;
        let cierre = "</DTE>";
        let cuerpo = dte_sin_firma
            .strip_suffix(cierre)
            .ok_or("el DTE no termina en </DTE>")?;
        Ok(format!("{cuerpo}{sig}{cierre}"))
    }

    /// Arma y firma el EnvioDTE/EnvioBOLETA por concatenación
    /// (`core/sobre.py::armar_sobre_firmado`). Devuelve los bytes finales en ISO-8859-1.
    #[allow(clippy::too_many_arguments)]
    pub fn sobre(
        &self,
        docs_firmados: &[String],
        subtotales: &BTreeMap<i32, i32>,
        rut_emisor: &str,
        rut_envia: &str,
        fecha_resol: &str,
        nro_resol: i64,
        raiz: &str,
        marca: &str,
    ) -> Result<Vec<u8>, String> {
        let xsd = match raiz {
            "EnvioDTE" => "EnvioDTE_v10.xsd",
            "EnvioBOLETA" => "EnvioBOLETA_v11.xsd",
            _ => return Err(format!("raíz desconocida {raiz:?}")),
        };
        let mut sub = String::new();
        for (t, n) in subtotales {
            sub.push_str(&format!(
                "<SubTotDTE><TpoDTE>{t}</TpoDTE><NroDTE>{n}</NroDTE></SubTotDTE>"
            ));
        }
        let caratula = format!(
            "<Caratula version=\"1.0\"><RutEmisor>{rut_emisor}</RutEmisor><RutEnvia>{rut_envia}</RutEnvia><RutReceptor>{RUT_SII}</RutReceptor><FchResol>{fecha_resol}</FchResol><NroResol>{nro_resol}</NroResol><TmstFirmaEnv>{marca}</TmstFirmaEnv>{sub}</Caratula>"
        );
        let set_dte = format!(
            "<SetDTE ID=\"SetDoc\">{}{}</SetDTE>",
            caratula,
            docs_firmados.concat()
        );
        let envio = format!(
            "<{raiz} xmlns=\"{NS_SII}\" xmlns:xsi=\"{NS_XSI}\" xsi:schemaLocation=\"{NS_SII} {xsd}\" version=\"1.0\">{set_dte}</{raiz}>"
        );
        let mut ns_ref = Alcance::new();
        ns_ref.insert(String::new(), NS_SII.to_string());
        ns_ref.insert("xsi".into(), NS_XSI.to_string());
        let mut ns_si = Alcance::new();
        ns_si.insert("xsi".into(), NS_XSI.to_string());
        let sig = self.signature("#SetDoc", &set_dte, &ns_ref, &ns_si)?;
        // lxml serializa el subárbol <Signature> para insertarlo por string, y al hacerlo le
        // renderiza en el ápice el xmlns:xsi heredado del sobre (54 bytes que el corpus detectó).
        let sig = sig.replacen(
            &format!("<Signature xmlns=\"{NS_DSIG}\">"),
            &format!("<Signature xmlns=\"{NS_DSIG}\" xmlns:xsi=\"{NS_XSI}\">"),
            1,
        );
        let cierre = format!("</{raiz}>");
        let cuerpo = envio
            .strip_suffix(cierre.as_str())
            .ok_or("sobre mal cerrado")?;
        let final_ = format!("{cuerpo}{sig}{cierre}");
        let mut out = b"<?xml version=\"1.0\" encoding=\"ISO-8859-1\"?>\n".to_vec();
        out.extend(crate::ted::latin1(&final_)?);
        Ok(out)
    }
}

fn envolver64(b64: &str) -> String {
    if b64.len() <= 64 {
        return b64.to_string();
    }
    let partes: Vec<&str> = b64
        .as_bytes()
        .chunks(64)
        .map(|c| std::str::from_utf8(c).expect("base64 es ASCII"))
        .collect();
    format!("\n{}\n", partes.join("\n"))
}

#[cfg(test)]
mod tests_pem {
    use super::*;

    /// El PEM del keystore debe ser byte a byte el de Python (contrato `contexto`): el
    /// certificado y la clave del corpus dorado tienen sus PEM como fixtures.
    #[test]
    fn pem_identico_a_python() {
        let raiz =
            std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../tests/dorado/fixtures");
        let Ok(p12) = std::fs::read(raiz.join("cert_demo.p12")) else {
            return;
        };
        let c = cargar_p12(&p12, "demo").unwrap();
        let cert_pem = std::fs::read_to_string(raiz.join("cert_demo.cert.pem")).unwrap();
        let key_pem = std::fs::read_to_string(raiz.join("cert_demo.key.pem")).unwrap();
        assert_eq!(c.cert_pem(), cert_pem);
        assert_eq!(c.key_pem().unwrap(), key_pem);
        assert_eq!(c.not_after().len(), 19);
    }
}
