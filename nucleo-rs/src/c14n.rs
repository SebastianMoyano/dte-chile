//! Canonical XML 1.0 (inclusiva, sin comentarios) sobre el subconjunto que usan los
//! documentos del SII, reproduciendo lo que hace `core/crypto.py::_c14n_reparse` y
//! `nucleo/c14n` (Go): el subárbol se canonicaliza como documento independiente con los
//! namespaces heredados de sus ancestros declarados en su ápice.

use quick_xml::events::Event;
use quick_xml::Reader;
use std::collections::BTreeMap;

/// prefijo ("" = default) → URI
pub type Alcance = BTreeMap<String, String>;

/// `subarbol`: XML del subárbol (UTF-8, sin declaración). `heredados`: namespaces de los
/// ancestros (como los renderiza lxml en el ápice al serializar el subárbol). Devuelve los
/// bytes C14N (UTF-8).
pub fn canonicalizar(subarbol: &str, heredados: &Alcance) -> Result<Vec<u8>, String> {
    let mut lector = Reader::from_str(subarbol);
    lector.config_mut().expand_empty_elements = true; // <X/> → <X></X>, como pide C14N
    let mut out = String::with_capacity(subarbol.len() + 64);
    let mut pila: Vec<Alcance> = vec![Alcance::new()];
    let mut profundidad = 0usize;
    loop {
        match lector.read_event().map_err(|e| format!("XML: {e}"))? {
            Event::Start(e) => {
                let padre = pila.last().cloned().unwrap_or_default();
                let mut propio = padre.clone();
                let mut declarados: Alcance = Alcance::new();
                if profundidad == 0 {
                    for (p, u) in heredados {
                        declarados.insert(p.clone(), u.clone());
                    }
                }
                let mut attrs: Vec<(String, String)> = Vec::new();
                for a in e.attributes() {
                    let a = a.map_err(|e| format!("atributo: {e}"))?;
                    let clave = String::from_utf8_lossy(a.key.as_ref()).into_owned();
                    let valor = a
                        .unescape_value()
                        .map_err(|e| format!("atributo: {e}"))?
                        .into_owned();
                    if clave == "xmlns" {
                        declarados.insert(String::new(), valor);
                    } else if let Some(p) = clave.strip_prefix("xmlns:") {
                        declarados.insert(p.to_string(), valor);
                    } else {
                        attrs.push((clave, valor));
                    }
                }
                // Namespaces que cambian respecto del alcance del padre, ordenados por prefijo
                // (el default, prefijo vacío, va primero: BTreeMap ya ordena así).
                let mut cambios: Vec<(&String, &String)> = Vec::new();
                for (p, u) in &declarados {
                    if padre.get(p) != Some(u) {
                        cambios.push((p, u));
                    }
                    propio.insert(p.clone(), u.clone());
                }
                out.push('<');
                out.push_str(&String::from_utf8_lossy(e.name().as_ref()));
                for (p, u) in cambios {
                    if p.is_empty() {
                        out.push_str(&format!(" xmlns=\"{}\"", esc_attr(u)));
                    } else {
                        out.push_str(&format!(" xmlns:{}=\"{}\"", p, esc_attr(u)));
                    }
                }
                // Atributos ordenados por (URI del namespace, nombre local); los sin prefijo
                // no tienen namespace y van primero.
                let uri_de = |nombre: &str| -> (String, String) {
                    match nombre.split_once(':') {
                        Some((p, local)) => (
                            propio.get(p).cloned().unwrap_or_default(),
                            local.to_string(),
                        ),
                        None => (String::new(), nombre.to_string()),
                    }
                };
                attrs.sort_by_key(|a| uri_de(&a.0));
                for (k, v) in &attrs {
                    out.push_str(&format!(" {}=\"{}\"", k, esc_attr(v)));
                }
                out.push('>');
                pila.push(propio);
                profundidad += 1;
            }
            Event::End(e) => {
                out.push_str("</");
                out.push_str(&String::from_utf8_lossy(e.name().as_ref()));
                out.push('>');
                pila.pop();
                profundidad = profundidad.saturating_sub(1);
            }
            Event::Text(t) => {
                let texto = t.unescape().map_err(|e| format!("texto: {e}"))?;
                out.push_str(&esc_texto(&texto));
            }
            Event::CData(c) => {
                out.push_str(&esc_texto(&String::from_utf8_lossy(c.as_ref())));
            }
            Event::Eof => break,
            // sin comentarios; no hay PI ni DTD en estos documentos
            Event::Comment(_)
            | Event::PI(_)
            | Event::Decl(_)
            | Event::DocType(_)
            | Event::Empty(_) => {}
        }
    }
    Ok(out.into_bytes())
}

fn esc_texto(s: &str) -> String {
    let mut b = String::with_capacity(s.len());
    for c in s.chars() {
        match c {
            '&' => b.push_str("&amp;"),
            '<' => b.push_str("&lt;"),
            '>' => b.push_str("&gt;"),
            '\r' => b.push_str("&#xD;"),
            _ => b.push(c),
        }
    }
    b
}

fn esc_attr(s: &str) -> String {
    let mut b = String::with_capacity(s.len());
    for c in s.chars() {
        match c {
            '&' => b.push_str("&amp;"),
            '<' => b.push_str("&lt;"),
            '"' => b.push_str("&quot;"),
            '\t' => b.push_str("&#x9;"),
            '\n' => b.push_str("&#xA;"),
            '\r' => b.push_str("&#xD;"),
            _ => b.push(c),
        }
    }
    b
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn apex_hereda_namespaces_y_expande_vacios() {
        let mut h = Alcance::new();
        h.insert(String::new(), "http://www.sii.cl/SiiDte".into());
        let c = canonicalizar(
            r#"<Documento ID="T39F1"><A/><B b="2" a="1">x &amp; y</B></Documento>"#,
            &h,
        )
        .unwrap();
        assert_eq!(
            String::from_utf8(c).unwrap(),
            r#"<Documento xmlns="http://www.sii.cl/SiiDte" ID="T39F1"><A></A><B a="1" b="2">x &amp; y</B></Documento>"#
        );
    }

    #[test]
    fn namespaces_en_orden_y_sin_repetir() {
        let mut h = Alcance::new();
        h.insert(
            "xsi".into(),
            "http://www.w3.org/2001/XMLSchema-instance".into(),
        );
        let c = canonicalizar(r#"<S xmlns="http://www.w3.org/2000/09/xmldsig#"><I xmlns="http://www.w3.org/2000/09/xmldsig#"/></S>"#, &h).unwrap();
        assert_eq!(
            String::from_utf8(c).unwrap(),
            r#"<S xmlns="http://www.w3.org/2000/09/xmldsig#" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><I></I></S>"#
        );
    }
}
