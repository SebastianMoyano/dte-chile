//! Codificación y un tokenizador HTML mínimo. El portal es ISO-8859-1 (Ley L8): los cuerpos
//! se percent-encodean sobre los bytes latin-1 (`ñ` → %F1) y en el ORDEN dado (Python:
//! `urlencode(..., encoding="latin-1")`). Transcripción de `nucleo/siiengine/html.go`.

use crate::htmlent::unescape;
use regex::Regex;
use std::collections::BTreeMap;
use std::sync::OnceLock;

/// Decodifica ISO-8859-1: cada byte es su propio code point.
pub fn latin1(b: &[u8]) -> String {
    b.iter().map(|&c| c as char).collect()
}

/// El inverso de `latin1`. Falla con caracteres fuera de ISO-8859-1.
pub fn a_bytes_latin1(s: &str) -> Result<Vec<u8>, String> {
    let mut out = Vec::with_capacity(s.len());
    for c in s.chars() {
        let n = c as u32;
        if n > 0xFF {
            return Err(format!(
                "hay un carácter que el portal (ISO-8859-1) no admite: {c:?}"
            ));
        }
        out.push(n as u8);
    }
    Ok(out)
}

pub fn quote_plus(b: &[u8]) -> String {
    const HEX: &[u8; 16] = b"0123456789ABCDEF";
    let mut sb = String::with_capacity(b.len());
    for &c in b {
        match c {
            b' ' => sb.push('+'),
            b'a'..=b'z' | b'A'..=b'Z' | b'0'..=b'9' | b'_' | b'.' | b'-' | b'~' => {
                sb.push(c as char)
            }
            _ => {
                sb.push('%');
                sb.push(HEX[(c >> 4) as usize] as char);
                sb.push(HEX[(c & 15) as usize] as char);
            }
        }
    }
    sb
}

/// Un campo de formulario; el orden de los pares es el orden del cuerpo.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Par {
    pub nombre: String,
    pub valor: String,
}

impl Par {
    pub fn new(nombre: impl Into<String>, valor: impl Into<String>) -> Par {
        Par {
            nombre: nombre.into(),
            valor: valor.into(),
        }
    }
}

/// `core/sii_mipyme.py::_body`: x-www-form-urlencoded con quote_plus sobre bytes latin-1, sin
/// ordenar.
pub fn codificar_latin1(pares: &[Par]) -> Result<Vec<u8>, String> {
    let mut sb = String::new();
    for (i, p) in pares.iter().enumerate() {
        let n = a_bytes_latin1(&p.nombre)?;
        let v = a_bytes_latin1(&p.valor)?;
        if i > 0 {
            sb.push('&');
        }
        sb.push_str(&quote_plus(&n));
        sb.push('=');
        sb.push_str(&quote_plus(&v));
    }
    Ok(sb.into_bytes())
}

/// `urlencode(..., encoding="utf-8")`: lo usa el XHR de la firma central.
pub fn codificar_utf8(pares: &[Par]) -> Vec<u8> {
    let mut sb = String::new();
    for (i, p) in pares.iter().enumerate() {
        if i > 0 {
            sb.push('&');
        }
        sb.push_str(&quote_plus(p.nombre.as_bytes()));
        sb.push('=');
        sb.push_str(&quote_plus(p.valor.as_bytes()));
    }
    sb.into_bytes()
}

// ---------------------------------------------------------------------------
// Un tokenizador mínimo con la semántica de html.parser.HTMLParser (convert_charrefs=True):
// tags y atributos en minúscula, valores y datos des-escapados, <script>/<style> como texto
// crudo, comentarios ignorados. Suficiente para las páginas CGI del portal.
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Default)]
struct Token {
    /// "" = texto
    tag: String,
    cierre: bool,
    attrs: BTreeMap<String, String>,
    texto: String,
}

static RE_TAG: OnceLock<Regex> = OnceLock::new();
static RE_ATTR: OnceLock<Regex> = OnceLock::new();

fn re(cache: &'static OnceLock<Regex>, pat: &str) -> &'static Regex {
    cache.get_or_init(|| Regex::new(pat).expect("regex"))
}

fn parsear_attrs(s: &str) -> BTreeMap<String, String> {
    let rx = re(
        &RE_ATTR,
        r#"([^\s=>/]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>]+)))?"#,
    );
    rx.captures_iter(s)
        .map(|m| {
            let v = [m.get(2), m.get(3), m.get(4)]
                .into_iter()
                .flatten()
                .map(|x| x.as_str())
                .collect::<String>();
            (m[1].to_lowercase(), unescape(&v))
        })
        .collect()
}

fn tokenizar(doc: &str) -> Vec<Token> {
    let rx = re(
        &RE_TAG,
        r#"(?s)<!--.*?-->|<(/?)([a-zA-Z][a-zA-Z0-9]*)((?:\s+[^\s=>/]+(?:\s*=\s*(?:"[^"]*"|'[^']*'|[^\s"'>]+))?)*)\s*/?>"#,
    );
    let mut out = Vec::new();
    let mut pos = 0;
    while pos < doc.len() {
        let Some(m) = rx.captures(&doc[pos..]) else {
            out.push(Token {
                texto: unescape(&doc[pos..]),
                ..Default::default()
            });
            break;
        };
        let total = m.get(0).unwrap();
        if total.start() > 0 {
            out.push(Token {
                texto: unescape(&doc[pos..pos + total.start()]),
                ..Default::default()
            });
        }
        let Some(nombre) = m.get(2) else {
            // comentario
            pos += total.end();
            continue;
        };
        let cierre = m.get(1).map(|x| !x.as_str().is_empty()).unwrap_or(false);
        let tag = nombre.as_str().to_lowercase();
        let mut t = Token {
            tag: tag.clone(),
            cierre,
            ..Default::default()
        };
        if !cierre {
            t.attrs = parsear_attrs(m.get(3).map(|x| x.as_str()).unwrap_or(""));
        }
        out.push(t);
        pos += total.end();
        if !cierre && (tag == "script" || tag == "style") {
            let resto = &doc[pos..];
            let fin = resto
                .to_lowercase()
                .find(&format!("</{tag}"))
                .unwrap_or(resto.len());
            out.push(Token {
                texto: resto[..fin].to_string(),
                ..Default::default()
            });
            pos += fin;
        }
    }
    out
}

/// El resultado de parsear un formulario: los campos y su orden de primera aparición (el
/// `dict` de Python conserva ese orden, y las notas lo necesitan).
#[derive(Debug, Clone, Default)]
pub struct Form {
    pub campos: BTreeMap<String, String>,
    pub orden: Vec<String>,
}

/// `core/sii_mipyme.py::parsear_form`: `{name: value}` de todos los input/select/textarea del
/// HTML. El primer input con un nombre gana; en un select gana la opción marcada y, si ninguna
/// lo está, la primera (como el navegador); el textarea acumula su texto.
pub fn parsear_form(doc: &str) -> BTreeMap<String, String> {
    parsear_form_ordenado(doc).campos
}

/// `parsear_form` conservando el orden de aparición de los nombres.
pub fn parsear_form_ordenado(doc: &str) -> Form {
    let mut f = Form::default();
    let (mut sel, mut textarea) = (String::new(), String::new());
    let (mut sel_marcado, mut sel_vio_opcion) = (false, false);
    for t in tokenizar(doc) {
        let nombre = t.attrs.get("name").cloned().unwrap_or_default();
        if t.tag.is_empty() {
            if !textarea.is_empty() {
                f.campos
                    .entry(textarea.clone())
                    .or_default()
                    .push_str(&t.texto);
            }
            continue;
        }
        if t.cierre {
            match t.tag.as_str() {
                "select" => sel.clear(),
                "textarea" => textarea.clear(),
                _ => {}
            }
            continue;
        }
        match t.tag.as_str() {
            "input" if !nombre.is_empty() && !f.campos.contains_key(&nombre) => {
                f.campos.insert(
                    nombre.clone(),
                    t.attrs.get("value").cloned().unwrap_or_default(),
                );
                f.orden.push(nombre);
            }
            "select" if !nombre.is_empty() => {
                sel = nombre.clone();
                sel_marcado = false;
                sel_vio_opcion = false;
                if !f.campos.contains_key(&sel) {
                    f.campos.insert(sel.clone(), String::new());
                    f.orden.push(sel.clone());
                }
            }
            "option" if !sel.is_empty() => {
                let v = t.attrs.get("value").cloned().unwrap_or_default();
                if t.attrs.contains_key("selected") {
                    f.campos.insert(sel.clone(), v);
                    sel_marcado = true;
                } else if !sel_marcado && !sel_vio_opcion {
                    f.campos.insert(sel.clone(), v);
                }
                sel_vio_opcion = true;
            }
            "textarea" if !nombre.is_empty() => {
                textarea = nombre.clone();
                if !f.campos.contains_key(&textarea) {
                    f.campos.insert(textarea.clone(), String::new());
                    f.orden.push(textarea.clone());
                }
            }
            _ => {}
        }
    }
    f
}

/// Lo que `_FilasParser` junta por cada `<tr>`: celdas y hrefs.
#[derive(Debug, Clone, Default)]
pub struct Fila {
    pub celdas: Vec<String>,
    pub hrefs: Vec<String>,
}

pub fn parsear_filas(doc: &str) -> Vec<Fila> {
    let mut out = Vec::new();
    let mut cur: Option<Fila> = None;
    let mut celda: Option<usize> = None;
    for t in tokenizar(doc) {
        if t.tag.is_empty() {
            if let (Some(f), Some(c)) = (cur.as_mut(), celda) {
                f.celdas[c].push_str(&t.texto);
            }
            continue;
        }
        match (t.cierre, t.tag.as_str()) {
            (false, "tr") => {
                cur = Some(Fila::default());
                celda = None;
            }
            (false, "td" | "th") => {
                if let Some(f) = cur.as_mut() {
                    f.celdas.push(String::new());
                    celda = Some(f.celdas.len() - 1);
                }
            }
            (false, "a") => {
                if let (Some(f), Some(h)) = (cur.as_mut(), t.attrs.get("href")) {
                    if !h.is_empty() {
                        f.hrefs.push(h.clone());
                    }
                }
            }
            (true, "td" | "th") => celda = None,
            (true, "tr") => {
                if let Some(f) = cur.take() {
                    if f.celdas.iter().any(|c| !c.trim().is_empty()) {
                        out.push(f);
                    }
                }
            }
            _ => {}
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn codificar() {
        // Python: _body([...]) sobre los mismos pares.
        let b = codificar_latin1(&[
            Par::new("rut", "12345678"),
            Par::new("dv", "5"),
            Par::new("clave", "ñandú pass/&=+ ~x"),
            Par::new("referencia", "https://misiir.sii.cl/cgi_misii/siihome.cgi"),
            Par::new("411", ""),
            Par::new("rutcntr", "12.345.678-5"),
        ])
        .unwrap();
        assert_eq!(String::from_utf8(b).unwrap(), "rut=12345678&dv=5&clave=%F1and%FA+pass%2F%26%3D%2B+~x&referencia=https%3A%2F%2Fmisiir.sii.cl%2Fcgi_misii%2Fsiihome.cgi&411=&rutcntr=12.345.678-5");
        assert!(
            codificar_latin1(&[Par::new("x", "€")]).is_err(),
            "€ no es latin-1: debe fallar, como Python"
        );
        assert_eq!(
            String::from_utf8(codificar_utf8(&[Par::new("dato", "ñ x")])).unwrap(),
            "dato=%C3%B1+x"
        );
        assert_eq!(latin1(&[0xF1, 0x41]), "ñA");
    }

    #[test]
    fn formularios() {
        let html = "<form><input name=\"a\" value=\"1\"><input type=\"hidden\" name=\"b\"><select name=\"s\"><option value=\"x\">X</option><option value=\"y\" selected>Y</option></select>\n<select name=\"t\"><option value=\"p\">P</option><option value=\"q\">Q</option></select><textarea name=\"ta\">hola\nmundo</textarea><input name=\"a\" value=\"2\"></form>";
        let got = parsear_form(html);
        let want: BTreeMap<String, String> = [
            ("a", "1"),
            ("b", ""),
            ("s", "y"),
            ("t", "p"),
            ("ta", "hola\nmundo"),
        ]
        .into_iter()
        .map(|(k, v)| (k.to_string(), v.to_string()))
        .collect();
        assert_eq!(got, want);
        // Dentro de <script> no se parsean tags (CDATA, como html.parser); los valores se des-escapan.
        let got = parsear_form("<script>var s = '<input name=\"falso\" value=\"1\">';</script><INPUT NAME=\"Real\" VALUE=\"a &amp; b\">");
        assert!(!got.contains_key("falso"));
        assert_eq!(got["Real"], "a & b");
    }
}
