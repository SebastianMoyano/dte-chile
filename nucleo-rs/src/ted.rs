//! Timbre Electrónico (TED): construcción y firma con la clave del CAF, exactamente como
//! `core/caf.py::ManejadorCAF.generar_ted` y `nucleo/ted` (Go). `docs/DORADO.md` §2.

use base64::Engine;
use regex::Regex;
use rsa::pkcs1::DecodeRsaPrivateKey;
use rsa::pkcs8::DecodePrivateKey;
use rsa::{Pkcs1v15Sign, RsaPrivateKey};
use sha1::{Digest, Sha1};
use std::sync::OnceLock;

/// Lo mínimo que el TED necesita del archivo de autorización de folios.
pub struct Caf {
    /// Elemento `<CAF …>…</CAF>` tal cual aparece en el archivo, MÁS el texto que lo sigue
    /// hasta el siguiente `<` (lxml serializa el elemento con su "tail").
    pub serializado: String,
    pub folio_desde: i32,
    pub folio_hasta: i32,
    pub clave: RsaPrivateKey,
    pub tipo_dte: i32,
    pub rut_emisor: String,
    pub fecha_autorizacion: String,
}

fn re(cache: &'static OnceLock<Regex>, pat: &str) -> &'static Regex {
    cache.get_or_init(|| Regex::new(pat).expect("regex"))
}

static RE_DA: OnceLock<Regex> = OnceLock::new();
static RE_RE: OnceLock<Regex> = OnceLock::new();
static RE_TD: OnceLock<Regex> = OnceLock::new();
static RE_FA: OnceLock<Regex> = OnceLock::new();
static RE_RNG: OnceLock<Regex> = OnceLock::new();
static RE_RSASK: OnceLock<Regex> = OnceLock::new();
static RE_BLANCO: OnceLock<Regex> = OnceLock::new();

/// Decodifica un bloque PEM sin exigir el ancho de línea de RFC 7468 (los CAF del SII traen
/// líneas de cualquier largo). Devuelve el DER.
pub fn pem_a_der(pem: &str) -> Option<Vec<u8>> {
    let mut b64 = String::new();
    let mut dentro = false;
    for linea in pem.lines() {
        let l = linea.trim();
        if l.starts_with("-----BEGIN") {
            dentro = true;
            continue;
        }
        if l.starts_with("-----END") {
            break;
        }
        if dentro {
            b64.push_str(l);
        }
    }
    if !dentro {
        return None;
    }
    base64::engine::general_purpose::STANDARD
        .decode(b64.as_bytes())
        .ok()
}

/// Clave RSA desde PEM/DER PKCS#1 ("RSA PRIVATE KEY") o PKCS#8 ("PRIVATE KEY").
pub fn clave_rsa_desde_pem(pem: &str) -> Result<RsaPrivateKey, String> {
    let der = pem_a_der(pem).ok_or_else(|| "no es PEM".to_string())?;
    if let Ok(k) = RsaPrivateKey::from_pkcs1_der(&der) {
        return Ok(k);
    }
    RsaPrivateKey::from_pkcs8_der(&der).map_err(|e| format!("clave privada ilegible: {e}"))
}

/// Parsea el archivo CAF decodificado a `String` (ISO-8859-1 → chars).
pub fn parsear_caf(contenido: &str) -> Result<Caf, String> {
    let ini = contenido
        .find("<CAF")
        .ok_or("el archivo no tiene un elemento <CAF>")?;
    let fin = contenido
        .find("</CAF>")
        .ok_or("el archivo no tiene un elemento <CAF>")?
        + "</CAF>".len();
    let mut cola = &contenido[fin..];
    if let Some(k) = cola.find('<') {
        cola = &cola[..k];
    }
    let serializado = format!("{}{}", &contenido[ini..fin], cola);
    let da = re(&RE_DA, r"(?s)<DA>(.*?)</DA>")
        .captures(contenido)
        .ok_or("El XML no parece ser un CAF válido: falta el elemento <DA>")?;
    let da = da.get(1).map(|m| m.as_str()).unwrap_or("");
    let rng = re(&RE_RNG, r"<RNG>\s*<D>(\d+)</D>\s*<H>(\d+)</H>\s*</RNG>").captures(da);
    let re_ = re(&RE_RE, r"<RE>([^<]*)</RE>").captures(da);
    let td = re(&RE_TD, r"<TD>([^<]*)</TD>").captures(da);
    let fa = re(&RE_FA, r"<FA>([^<]*)</FA>").captures(da);
    let (Some(rng), Some(re_), Some(td), Some(fa)) = (rng, re_, td, fa) else {
        return Err("El CAF está incompleto o tiene una estructura incorrecta.".into());
    };
    let folio_desde = rng[1].parse().unwrap_or(0);
    let folio_hasta = rng[2].parse().unwrap_or(0);
    let tipo_dte = td[1].trim().parse().unwrap_or(0);
    let rut_emisor = re_[1].trim().to_string();
    let fecha_autorizacion = fa[1].trim().to_string();
    if !fecha_iso_valida(&fecha_autorizacion) {
        return Err(format!("Invalid isoformat string: '{fecha_autorizacion}'"));
    }
    let k = re(&RE_RSASK, r"(?s)<RSASK>(.*?)</RSASK>").captures(contenido);
    let Some(k) = k.filter(|c| !c[1].trim().is_empty()) else {
        return Err("El CAF no contiene la clave privada RSASK.".into());
    };
    let clave = clave_rsa_desde_pem(k[1].trim())?;
    Ok(Caf {
        serializado,
        folio_desde,
        folio_hasta,
        clave,
        tipo_dte,
        rut_emisor,
        fecha_autorizacion,
    })
}

fn fecha_iso_valida(s: &str) -> bool {
    let b = s.as_bytes();
    if b.len() != 10 || b[4] != b'-' || b[7] != b'-' {
        return false;
    }
    let num = |r: std::ops::Range<usize>| s[r].parse::<u32>().ok();
    let (Some(_a), Some(m), Some(d)) = (num(0..4), num(5..7), num(8..10)) else {
        return false;
    };
    (1..=12).contains(&m) && (1..=31).contains(&d)
}

/// Escape de texto XML que aplican lxml y la C14N: `& < >`.
pub fn escapar_texto(s: &str) -> String {
    s.replace('&', "&amp;")
        .replace('<', "&lt;")
        .replace('>', "&gt;")
}

/// Codifica un `&str` a bytes ISO-8859-1. Falla si hay un carácter > U+00FF.
pub fn latin1(s: &str) -> Result<Vec<u8>, String> {
    let mut out = Vec::with_capacity(s.len());
    for c in s.chars() {
        let n = c as u32;
        if n > 0xFF {
            return Err(format!("carácter {c:?} no representable en ISO-8859-1"));
        }
        out.push(n as u8);
    }
    Ok(out)
}

/// Decodifica bytes ISO-8859-1 a `String` (cada byte, un char).
pub fn desde_latin1(b: &[u8]) -> String {
    b.iter().map(|&c| c as char).collect()
}

pub fn recortar(s: &str, n: usize) -> String {
    s.chars().take(n).collect()
}

#[derive(Debug, Clone, Default)]
pub struct Datos {
    pub folio: i32,
    pub rut_emisor: String,
    pub rut_receptor: String,
    pub tipo_dte: i32,
    pub fecha_emision: String,
    pub monto_total: i64,
    pub razon_social_receptor: String,
    pub primer_item: String,
    /// Hora del reloj, `YYYY-MM-DDTHH:MM:SS`.
    pub marca: String,
    /// `primer_item` ya viene escapado (como lo manda certificacion_sii.py, que escapa ANTES
    /// de recortar a 40): se recorta y no se vuelve a escapar.
    pub primer_item_literal: bool,
}

/// Firma SHA1withRSA (PKCS#1 v1.5) de `datos` con la clave dada.
pub fn firmar_sha1(clave: &RsaPrivateKey, datos: &[u8]) -> Result<Vec<u8>, String> {
    let h = Sha1::digest(datos);
    clave
        .sign(Pkcs1v15Sign::new::<Sha1>(), &h)
        .map_err(|e| format!("firma RSA: {e}"))
}

/// Devuelve el TED como `String` (el archivo se escribe en ISO-8859-1).
pub fn generar(c: &Caf, d: &Datos) -> Result<String, String> {
    if d.folio < c.folio_desde || d.folio > c.folio_hasta {
        return Err(format!(
            "el folio {} no está en el rango del CAF [{}-{}]",
            d.folio, c.folio_desde, c.folio_hasta
        ));
    }
    let dd = format!(
        "<DD>\n<RE>{}</RE>\n<TD>{}</TD>\n<F>{}</F>\n<FE>{}</FE>\n<RR>{}</RR>\n<RSR>{}</RSR>\n<MNT>{}</MNT>\n<IT1>{}</IT1>\n{}\n<TSTED>{}</TSTED>\n</DD>",
        d.rut_emisor,
        d.tipo_dte,
        d.folio,
        d.fecha_emision,
        d.rut_receptor,
        escapar_texto(&recortar(&d.razon_social_receptor, 40)),
        d.monto_total,
        it1(d),
        c.serializado,
        d.marca
    );
    // Lo firmado: C14N del DD (para este DD sin namespaces equivale al propio string),
    // aplanado (>\s+< → ><) y en ISO-8859-1.
    let plano = latin1(&re(&RE_BLANCO, r">\s+<").replace_all(&dd, "><"))?;
    let firma = firmar_sha1(&c.clave, &plano)?;
    Ok(format!(
        "<TED version=\"1.0\">\n{}\n<FRMT algoritmo=\"SHA1withRSA\">{}</FRMT>\n</TED>",
        dd,
        base64::engine::general_purpose::STANDARD.encode(firma)
    ))
}

/// Texto del IT1. En modo literal viene pre-escapado por el script (& < > " ') y recortado
/// DESPUÉS de escapar; Python luego parsea el DD y firma su C14N, que escribe las comillas
/// sin escapar (&apos; → ', &quot; → "), así que eso es lo que se firma y lo que sale.
fn it1(d: &Datos) -> String {
    if d.primer_item_literal {
        recortar(&d.primer_item, 40)
            .replace("&apos;", "'")
            .replace("&quot;", "\"")
    } else {
        escapar_texto(&recortar(&d.primer_item, 40))
    }
}
