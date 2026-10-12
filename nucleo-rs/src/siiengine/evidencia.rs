//! `_guardar_evidencia`: deja en `<raiz_storage>/mipyme_fallidos/<rut>/T<tipo>_F<folio>_<ts>/`
//! lo necesario para diagnosticar un fallo DESPUÉS de gastar el folio: respuesta del portal,
//! XML firmado (vale oro: es el documento con la firma del SII) y el body enviado, con las
//! claves reemplazadas por `***` (L6). Best-effort: nunca falla; devuelve la carpeta o "".

use super::html::{a_bytes_latin1, codificar_latin1, codificar_utf8, quote_plus, Par};
use std::collections::BTreeMap;
use std::path::PathBuf;

/// `urllib.parse.quote(s)` (safe="/"): como quote_plus pero el espacio va %20 y '/' queda.
pub fn quote_utf8(s: &str) -> String {
    const HEX: &[u8; 16] = b"0123456789ABCDEF";
    let mut sb = String::with_capacity(s.len());
    for &c in s.as_bytes() {
        match c {
            b'a'..=b'z' | b'A'..=b'Z' | b'0'..=b'9' | b'_' | b'.' | b'-' | b'~' | b'/' => {
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

/// `html.escape(s, quote=True)`: &, <, >, " y ' (este último como &#x27;).
pub fn escape_html_python(s: &str) -> String {
    s.replace('&', "&amp;")
        .replace('<', "&lt;")
        .replace('>', "&gt;")
        .replace('"', "&quot;")
        .replace('\'', "&#x27;")
}

/// El secreto tal cual, url-encoded (quote y quote_plus, UTF-8 y latin-1) y html-escapado,
/// como en Python.
pub fn variantes_secreto(sec: &str) -> Vec<String> {
    let mut out = vec![
        sec.to_string(),
        quote_utf8(sec),
        String::from_utf8_lossy(&codificar_utf8(&[Par::new("", sec)])[1..]).into_owned(),
        escape_html_python(sec),
    ];
    if let Ok(b) = a_bytes_latin1(sec) {
        out.push(quote_plus(&b));
    }
    out
}

/// Codifica ISO-8859-1 reemplazando lo que no cabe con '?' (errors="replace").
pub fn a_latin1_reemplazo(s: &str) -> Vec<u8> {
    s.chars()
        .map(|c| {
            if (c as u32) > 0xFF {
                b'?'
            } else {
                c as u32 as u8
            }
        })
        .collect()
}

#[allow(clippy::too_many_arguments)]
pub(super) fn guardar_evidencia(
    raiz: &str,
    empresa: &str,
    secretos: &[&str],
    tipo: i32,
    folio: i32,
    paso: &str,
    respuesta: &str,
    xml_firmado: &str,
    pares: &[Par],
    extras: &BTreeMap<String, String>,
) -> String {
    let limpiar = |t: &str| -> String {
        let mut t = t.to_string();
        for sec in secretos {
            if sec.len() < 4 {
                continue;
            }
            for v in variantes_secreto(sec) {
                t = t.replace(&v, "***");
            }
        }
        t
    };
    let rut = if empresa.is_empty() {
        "sin_rut"
    } else {
        empresa
    };
    let raiz = if raiz.is_empty() { "storage" } else { raiz };
    let ts = crate::almacen::ahora_iso();
    let ts = ts[..19].replace(['-', ':'], "");
    let carpeta: PathBuf = [
        raiz,
        "mipyme_fallidos",
        &rut.replace('-', ""),
        &format!("T{tipo}_F{folio}_{ts}"),
    ]
    .iter()
    .collect();
    if std::fs::create_dir_all(&carpeta).is_err() {
        return String::new();
    }
    let escribir = |nombre: &str, contenido: &str| {
        let _ = std::fs::write(carpeta.join(nombre), a_latin1_reemplazo(contenido));
    };
    escribir(&format!("respuesta_{paso}.html"), &limpiar(respuesta));
    if !xml_firmado.is_empty() {
        escribir("dte_firmado.xml", xml_firmado);
    }
    // Una sola línea x-www-form-urlencoded (como viaja), parseable con parse_qsl.
    let limpios: Vec<Par> = pares
        .iter()
        .map(|p| Par::new(p.nombre.clone(), limpiar(&p.valor)))
        .collect();
    if let Ok(b) = codificar_latin1(&limpios) {
        let _ = std::fs::write(carpeta.join(format!("body_{paso}.txt")), b);
    }
    for (nombre, contenido) in extras {
        escribir(nombre, &limpiar(contenido));
    }
    carpeta.to_string_lossy().into_owned()
}
