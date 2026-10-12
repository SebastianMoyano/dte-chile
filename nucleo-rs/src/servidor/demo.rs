//! El mundo de práctica (EMPRESA DEMO SPA), réplica de core/simulacion.py: emisor ficticio
//! (RUT 77.777.777-7, ley L14), CAF de mentira por tipo (clave RSA real para el timbre, firma
//! del SII placeholder), certificado demo (el fijo del corpus dorado si existe; si no, uno
//! autofirmado en memoria con el RUT en el SAN), resolución fija. Nada sale del computador.

use super::Servidor;
use crate::firma::Certificado;
use base64::Engine;
use rsa::pkcs1::EncodeRsaPrivateKey;
use rsa::traits::PublicKeyParts;
use rsa::RsaPrivateKey;
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::path::Path;

pub const RUT_DEMO: &str = "77777777-7";
pub const RUT_PERSONA_DEMO: &str = "12345678-5";
pub const RUT_CLIENTE_DEMO: &str = "76111111-6";
pub const RUT_CONSUMIDOR_FINAL: &str = "66666666-6";
pub const AMBIENTE_DEMO: &str = "simulacion";
pub const ESTADO_DEMO: &str = "simulado";
pub const FOLIOS_POR_TIPO: i32 = 100;
pub const TIPOS_DEMO: [i32; 6] = [33, 34, 39, 41, 56, 61];

/// `EMISOR_DEMO.model_dump()` (todos los campos, también los por defecto).
pub fn emisor_demo() -> Value {
    json!({
        "rut": RUT_DEMO, "razon_social": "EMPRESA DEMO SPA", "giro": "Cafetería", "codigo_actividad": 561000,
        "direccion": "Calle Ficticia 123", "comuna": "Santiago", "ciudad": "Santiago", "telefono": null,
        "email": "hola@empresademo.cl", "es_receptor_boleta": true,
    })
}

pub fn cliente_demo() -> Value {
    json!({"rut": RUT_CLIENTE_DEMO, "razon_social": "CLIENTE DEMO SPA", "giro": "Oficina",
        "direccion": "Avenida Imaginaria 456", "comuna": "Providencia", "ciudad": "Santiago"})
}

pub fn hoy_iso() -> String {
    crate::almacen::ahora_iso()[..10].to_string()
}

/// `time.Parse("2006-01-02", f)`.
pub fn fecha_valida(f: &str) -> bool {
    let b = f.as_bytes();
    if b.len() != 10 || b[4] != b'-' || b[7] != b'-' {
        return false;
    }
    let (Ok(a), Ok(m), Ok(d)) = (
        f[..4].parse::<i32>(),
        f[5..7].parse::<u32>(),
        f[8..].parse::<u32>(),
    ) else {
        return false;
    };
    if !(1..=12).contains(&m) || d == 0 {
        return false;
    }
    let dias = [
        31,
        if (a % 4 == 0 && a % 100 != 0) || a % 400 == 0 {
            29
        } else {
            28
        },
        31,
        30,
        31,
        30,
        31,
        31,
        30,
        31,
        30,
        31,
    ];
    d <= dias[(m - 1) as usize]
}

/// `_caf_ficticio`: XML de CAF con clave RSA 1024 real y FRMA de mentira.
pub fn caf_ficticio(tipo: i32, desde: i32, hasta: i32) -> Result<String, String> {
    let key = RsaPrivateKey::new(&mut rand::rngs::OsRng, 1024).map_err(|e| e.to_string())?;
    let pem_key = key
        .to_pkcs1_pem(rsa::pkcs1::LineEnding::LF)
        .map_err(|e| e.to_string())?
        .to_string();
    let b64 = base64::engine::general_purpose::STANDARD;
    let m = b64.encode(key.n().to_bytes_be());
    let e = b64.encode(key.e().to_bytes_be());
    Ok(format!(
        "<?xml version=\"1.0\" encoding=\"ISO-8859-1\"?>\n<AUTORIZACION>\n  <CAF version=\"1.0\">\n    <DA>\n      <RE>{RUT_DEMO}</RE>\n      <RS>EMPRESA DEMO SPA</RS>\n      <TD>{tipo}</TD>\n      <RNG><D>{desde}</D><H>{hasta}</H></RNG>\n      <FA>{}</FA>\n      <RSAPK><M>{m}</M><E>{e}</E></RSAPK>\n      <IDK>100</IDK>\n    </DA>\n    <FRMA algoritmo=\"SHA1withRSA\">U0lNVUxBQ0lPTi1OTy1FUy1VTkEtRklSTUEtREVMLVNJSQ==</FRMA>\n  </CAF>\n  <RSASK>\n{pem_key}  </RSASK>\n</AUTORIZACION>\n",
        hoy_iso()
    ))
}

// ---------------------------------------------------------------- DER mínimo

fn tlv(tag: u8, c: &[u8]) -> Vec<u8> {
    let mut out = vec![tag];
    let n = c.len();
    if n < 128 {
        out.push(n as u8);
    } else {
        let mut be = Vec::new();
        let mut x = n;
        while x > 0 {
            be.insert(0, (x & 0xff) as u8);
            x >>= 8;
        }
        out.push(0x80 | be.len() as u8);
        out.extend(be);
    }
    out.extend_from_slice(c);
    out
}
fn seq(partes: &[Vec<u8>]) -> Vec<u8> {
    tlv(0x30, &partes.concat())
}
fn set(partes: &[Vec<u8>]) -> Vec<u8> {
    tlv(0x31, &partes.concat())
}
fn int(b: &[u8]) -> Vec<u8> {
    let mut v = b.to_vec();
    while v.len() > 1 && v[0] == 0 && v[1] & 0x80 == 0 {
        v.remove(0);
    }
    if v.is_empty() || v[0] & 0x80 != 0 {
        v.insert(0, 0);
    }
    tlv(0x02, &v)
}
fn oid(b: &[u8]) -> Vec<u8> {
    tlv(0x06, b)
}
fn utf8(s: &str) -> Vec<u8> {
    tlv(0x0C, s.as_bytes())
}
fn printable(s: &str) -> Vec<u8> {
    tlv(0x13, s.as_bytes())
}
fn ia5(s: &str) -> Vec<u8> {
    tlv(0x16, s.as_bytes())
}
fn utctime(s: &str) -> Vec<u8> {
    tlv(0x17, s.as_bytes())
}
fn bitstring(c: &[u8]) -> Vec<u8> {
    let mut v = vec![0u8];
    v.extend_from_slice(c);
    tlv(0x03, &v)
}
fn octet(c: &[u8]) -> Vec<u8> {
    tlv(0x04, c)
}
fn ctx(n: u8, c: &[u8]) -> Vec<u8> {
    tlv(0xA0 | n, c)
}
const OID_C: &[u8] = &[0x55, 0x04, 0x06];
const OID_O: &[u8] = &[0x55, 0x04, 0x0A];
const OID_CN: &[u8] = &[0x55, 0x04, 0x03];
const OID_SAN: &[u8] = &[0x55, 0x1D, 0x11];
const OID_RSA: &[u8] = &[0x2A, 0x86, 0x48, 0x86, 0xF7, 0x0D, 0x01, 0x01, 0x01];
const OID_SHA256_RSA: &[u8] = &[0x2A, 0x86, 0x48, 0x86, 0xF7, 0x0D, 0x01, 0x01, 0x0B];
/// 1.3.6.1.4.1.8321.1 (el otherName chileno con el RUT)
const OID_RUT_CL: &[u8] = &[0x2B, 0x06, 0x01, 0x04, 0x01, 0xC1, 0x01, 0x01];

fn utc_yymmdd(segundos: i64) -> String {
    let t = super::fecha_hora_utc(segundos);
    format!(
        "{}{}{}{}{}{}Z",
        &t[2..4],
        &t[5..7],
        &t[8..10],
        &t[11..13],
        &t[14..16],
        &t[17..19]
    )
}

/// Un certificado autofirmado (RSA 2048, SHA-256) de "ANA DEMO" con el RUT en el SAN.
pub fn certificado_autofirmado() -> Result<Certificado, String> {
    let key = RsaPrivateKey::new(&mut rand::rngs::OsRng, 2048).map_err(|e| e.to_string())?;
    let nombre = seq(&[
        set(&[seq(&[oid(OID_C), printable("CL")])]),
        set(&[seq(&[oid(OID_O), utf8("SIMULACION DTE CHILE")])]),
        set(&[seq(&[
            oid(OID_CN),
            utf8(&format!("ANA DEMO {RUT_PERSONA_DEMO}")),
        ])]),
    ]);
    let ahora = super::auth::ahora_unix();
    let validez = seq(&[
        utctime(&utc_yymmdd(ahora - 86400)),
        utctime(&utc_yymmdd(ahora + 3650 * 86400)),
    ]);
    let spki = seq(&[
        seq(&[oid(OID_RSA), vec![0x05, 0x00]]),
        bitstring(&seq(&[
            int(&key.n().to_bytes_be()),
            int(&key.e().to_bytes_be()),
        ])),
    ]);
    let other_name = ctx(
        0,
        &[oid(OID_RUT_CL), ctx(0, &ia5(RUT_PERSONA_DEMO))].concat(),
    );
    let san = seq(&[oid(OID_SAN), octet(&seq(&[other_name]))]);
    let mut serial = super::local::bytes_azar(15);
    serial[0] &= 0x7f;
    let alg = seq(&[oid(OID_SHA256_RSA), vec![0x05, 0x00]]);
    let tbs = seq(&[
        ctx(0, &int(&[2])),
        int(&serial),
        alg.clone(),
        nombre.clone(),
        validez,
        nombre,
        spki,
        ctx(3, &seq(&[san])),
    ]);
    let firma = key
        .sign(rsa::Pkcs1v15Sign::new::<Sha256>(), &Sha256::digest(&tbs))
        .map_err(|e| e.to_string())?;
    let der = seq(&[tbs, alg, bitstring(&firma)]);
    Certificado::desde_der(key, der)
}

impl Servidor {
    /// `certificado_demo()`: el fijo del corpus dorado (clave "demo") si está; si no, uno
    /// autofirmado en memoria.
    pub fn certificado_demo(&self) -> Result<Certificado, String> {
        if let Some(c) = self.cert_demo.lock().expect("cert demo").as_ref() {
            return Ok(c.clone());
        }
        let base_db = Path::new(&self.cfg.database_path)
            .parent()
            .map(|p| p.to_path_buf())
            .unwrap_or_default();
        let candidatos = [
            Path::new("tests/dorado/fixtures/cert_demo.p12").to_path_buf(),
            base_db
                .join("tests")
                .join("dorado")
                .join("fixtures")
                .join("cert_demo.p12"),
        ];
        let mut cert = None;
        for ruta in candidatos {
            if let Ok(b) = std::fs::read(&ruta) {
                if let Ok(c) = crate::firma::cargar_p12(&b, "demo") {
                    cert = Some(c);
                    break;
                }
            }
        }
        let c = match cert {
            Some(c) => c,
            None => certificado_autofirmado()?,
        };
        *self.cert_demo.lock().expect("cert demo") = Some(c.clone());
        Ok(c)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn autofirmado_trae_el_rut_en_el_san() {
        let c = certificado_autofirmado().unwrap();
        assert_eq!(c.rut_emisor().unwrap(), RUT_PERSONA_DEMO);
        assert!(c.cert_pem().starts_with("-----BEGIN CERTIFICATE-----\n"));
        let caf = caf_ficticio(39, 1, 100).unwrap();
        let p = crate::ted::parsear_caf(&caf).unwrap();
        assert_eq!((p.tipo_dte, p.folio_desde, p.folio_hasta), (39, 1, 100));
        assert!(fecha_valida("2026-02-28") && !fecha_valida("2026-02-30") && !fecha_valida("x"));
    }
}
