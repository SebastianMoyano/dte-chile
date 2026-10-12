//! api/routes/consulta.py — buscador PÚBLICO de boletas para el receptor (sin login). Exige los
//! 5 datos de la boleta (RUT emisor, tipo, folio, fecha y monto total) para no permitir
//! enumeración; solo lee la base local. Y las páginas del panel + favicon de main.py.

use super::errores::{json, ErrorHTTP, Res};
use super::http::{parsear_formulario, query_encode, Peticion, Respuesta};
use super::{bytes_latin1, entero, texto, Prot, Servidor};
use crate::pdf;
use serde_json::{json as j, Map, Value};

/// Copias byte a byte de static/*.html del repo: las páginas del panel web.
const PAGINAS: [(&str, &[u8]); 4] = [
    (
        "certificados",
        include_bytes!("../../../static/certificados.html"),
    ),
    (
        "onboarding",
        include_bytes!("../../../static/onboarding.html"),
    ),
    ("apikeys", include_bytes!("../../../static/apikeys.html")),
    (
        "documentos",
        include_bytes!("../../../static/documentos.html"),
    ),
];

pub fn rutas(s: &mut Servidor) {
    s.ruta("GET /consulta", Prot::Publica, formulario);
    s.ruta("GET /consulta/{$}", Prot::Publica, formulario);
    s.ruta("POST /consulta", Prot::Publica, consulta_post);
    s.ruta("POST /consulta/{$}", Prot::Publica, consulta_post);
    s.ruta("GET /consulta/api", Prot::Publica, consulta_api);
    s.ruta("GET /consulta/xml", Prot::Publica, consulta_xml);
    s.ruta("GET /consulta/pdf", Prot::Publica, consulta_pdf);
    s.ruta("GET /certificados", Prot::Publica, pagina);
    s.ruta("GET /onboarding", Prot::Publica, pagina);
    s.ruta("GET /apikeys", Prot::Publica, pagina);
    s.ruta("GET /documentos", Prot::Publica, pagina);
    s.ruta("GET /static/{archivo}", Prot::Publica, estatico);
    s.ruta("GET /favicon.ico", Prot::Publica, favicon);
}

fn pagina_de(nombre: &str) -> Option<&'static [u8]> {
    PAGINAS.iter().find(|(n, _)| *n == nombre).map(|(_, b)| *b)
}

fn no_encontrado() -> Res {
    Ok(Respuesta::texto(
        404,
        "text/plain; charset=utf-8",
        "404 page not found\n",
    ))
}

fn pagina(_s: &Servidor, p: &mut Peticion) -> Res {
    match pagina_de(p.ruta.trim_start_matches('/')) {
        Some(b) => Ok(
            Respuesta::binario(200, "text/html; charset=utf-8", b.to_vec())
                .con("Cache-Control", "no-cache"),
        ),
        None => no_encontrado(),
    }
}

fn estatico(_s: &Servidor, p: &mut Peticion) -> Res {
    match pagina_de(p.param("archivo").trim_end_matches(".html")) {
        Some(b) if p.param("archivo").ends_with(".html") => Ok(Respuesta::binario(
            200,
            "text/html; charset=utf-8",
            b.to_vec(),
        )),
        _ => no_encontrado(),
    }
}

fn favicon(_s: &Servidor, _p: &mut Peticion) -> Res {
    Ok(Respuesta::texto(200, "image/svg+xml", r##"<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#2563eb" stroke-width="2" stroke-linejoin="round"><path d="M12 2l7 3v6c0 4.4-3 8.3-7 9-4-.7-7-4.6-7-9V5l7-3z"/><path d="M9 12l2 2 4-4" stroke-linecap="round"/></svg>"##)
        .con("Cache-Control", "public, max-age=86400"))
}

const TIPOS: [(i64, &str); 2] = [
    (39, "Boleta Electrónica"),
    (41, "Boleta Exenta Electrónica"),
];

fn nombre_tipo(t: i64) -> &'static str {
    TIPOS
        .iter()
        .find(|(c, _)| *c == t)
        .map(|(_, n)| *n)
        .unwrap_or("")
}

fn norm_rut(rut: &str) -> String {
    rut.replace('.', "").trim().to_uppercase()
}

/// `html.EscapeString` de Go.
pub fn html_escape(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    for c in s.chars() {
        match c {
            '<' => out.push_str("&lt;"),
            '>' => out.push_str("&gt;"),
            '&' => out.push_str("&amp;"),
            '\'' => out.push_str("&#39;"),
            '"' => out.push_str("&#34;"),
            _ => out.push(c),
        }
    }
    out
}

impl Servidor {
    /// `_buscar`: la fila si coinciden TODOS los datos, o None.
    fn buscar_boleta(
        &self,
        rut: &str,
        tipo: i64,
        folio: i64,
        monto: i64,
        fecha: &str,
    ) -> Result<Option<Map<String, Value>>, ErrorHTTP> {
        if nombre_tipo(tipo).is_empty() {
            return Ok(None);
        }
        let mut q =
            "SELECT * FROM dtes WHERE rut_emisor=? AND tipo_dte=? AND folio=? AND monto_total=?"
                .to_string();
        let mut args: Vec<rusqlite::types::Value> = vec![
            norm_rut(rut).into(),
            tipo.into(),
            folio.into(),
            monto.into(),
        ];
        if !fecha.is_empty() {
            q.push_str(" AND fecha_emision=?");
            args.push(fecha.trim().to_string().into());
        }
        Ok(self.fila(&q, &args)?)
    }
}

/// `_qs`: los 5 datos como query string (mismo candado para las descargas).
fn qs(rut: &str, tipo: i64, folio: i64, monto: i64, fecha: &str) -> String {
    let (r, t, f, m) = (
        norm_rut(rut),
        tipo.to_string(),
        folio.to_string(),
        monto.to_string(),
    );
    let mut pares = vec![
        ("rut", r.as_str()),
        ("tipo", t.as_str()),
        ("folio", f.as_str()),
        ("monto", m.as_str()),
    ];
    if !fecha.is_empty() {
        pares.push(("fecha", fecha));
    }
    query_encode(&pares)
}

/// `_pagina`: la página autocontenida (tema claro/oscuro, sin dependencias).
fn pagina_consulta(
    cuerpo: &str,
    rut: &str,
    folio: &str,
    monto: &str,
    tipo: i64,
    fecha: &str,
) -> String {
    let mut op = String::new();
    for (c, n) in TIPOS {
        let sel = if c == tipo { " selected" } else { "" };
        op.push_str(&format!("<option value=\"{c}\"{sel}>{n}</option>"));
    }
    format!(
        r##"<!doctype html><html lang="es"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Consulta de Boleta Electrónica</title>
<style>
  :root {{ --bg:#f4f5f7; --card:#fff; --fg:#1a1c1f; --mut:#5c636e; --acc:#1f6feb; --bd:#dfe3e8; }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --bg:#0f1216; --card:#181c22; --fg:#e8eaed; --mut:#9aa3ad; --acc:#4c8dff; --bd:#2a2f37; }} }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--fg); font:15px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif; }}
  .wrap {{ max-width:560px; margin:0 auto; padding:32px 20px; }}
  h1 {{ font-size:1.35rem; margin:0 0 4px; }}
  .sub {{ color:var(--mut); margin:0 0 24px; font-size:.92rem; }}
  .card {{ background:var(--card); border:1px solid var(--bd); border-radius:12px; padding:22px; }}
  label {{ display:block; font-weight:600; font-size:.82rem; margin:14px 0 5px; }}
  input,select {{ width:100%; padding:10px 12px; border:1px solid var(--bd); border-radius:8px;
    background:transparent; color:var(--fg); font-size:1rem; }}
  button {{ margin-top:20px; width:100%; padding:12px; border:0; border-radius:8px;
    background:var(--acc); color:#fff; font-size:1rem; font-weight:600; cursor:pointer; }}
  table {{ width:100%; border-collapse:collapse; margin-top:6px; }}
  td {{ padding:8px 4px; border-bottom:1px solid var(--bd); }}
  td:first-child {{ color:var(--mut); width:44%; }}
  td:last-child {{ text-align:right; font-variant-numeric:tabular-nums; }}
  .ok {{ color:#1a7f37; font-weight:600; }} .no {{ color:#b3261e; font-weight:600; }}
  .dl {{ display:flex; gap:10px; margin-top:18px; }}
  .dl a {{ flex:1; text-align:center; padding:11px; border:1px solid var(--acc); border-radius:8px;
    color:var(--acc); text-decoration:none; font-weight:600; font-size:.92rem; }}
  .foot {{ color:var(--mut); font-size:.82rem; margin-top:18px; text-align:center; }}
  .foot a {{ color:var(--acc); }}
</style></head><body><div class="wrap">
<h1>Consulta de Boleta Electrónica</h1>
<p class="sub">Ingrese los datos de su boleta para verificarla.</p>
<div class="card">
<form method="post" action="/consulta">
  <label>RUT del emisor</label>
  <input name="rut_emisor" placeholder="76111111-6" value="{}" required>
  <label>Tipo de documento</label>
  <select name="tipo_dte">{op}</select>
  <label>Folio</label>
  <input name="folio" inputmode="numeric" placeholder="1" value="{}" required>
  <label>Fecha de emisión</label>
  <input name="fecha_emision" type="date" value="{}" required>
  <label>Monto total ($)</label>
  <input name="monto_total" inputmode="numeric" placeholder="29800" value="{}" required>
  <button type="submit">Consultar boleta</button>
</form>
{cuerpo}
</div>
<p class="foot">Verifique también la autenticidad en <a href="https://www.sii.cl" rel="noopener">www.sii.cl</a></p>
</div></body></html>"##,
        html_escape(rut),
        html_escape(folio),
        html_escape(fecha),
        html_escape(monto)
    )
}

fn formulario(_s: &Servidor, _p: &mut Peticion) -> Res {
    Ok(Respuesta::html(&pagina_consulta("", "", "", "", 39, "")))
}

const INT_PARSING: &str = "Input should be a valid integer, unable to parse string as an integer";

/// rut, tipo, folio, monto (obligatorios) y fecha (opcional) de la query.
fn parametros(p: &Peticion) -> Result<(String, i64, i64, i64, String), ErrorHTTP> {
    for campo in ["rut", "tipo", "folio", "monto"] {
        if p.q(campo).is_empty() {
            return Err(ErrorHTTP::query(campo, "Field required", "missing"));
        }
    }
    let tipo: i64 = p
        .q("tipo")
        .parse()
        .map_err(|_| ErrorHTTP::query("tipo", INT_PARSING, "int_parsing"))?;
    let folio: i64 = p
        .q("folio")
        .parse()
        .map_err(|_| ErrorHTTP::query("folio", INT_PARSING, "int_parsing"))?;
    let monto: i64 = p
        .q("monto")
        .parse()
        .map_err(|_| ErrorHTTP::query("monto", INT_PARSING, "int_parsing"))?;
    Ok((p.q("rut"), tipo, folio, monto, p.q("fecha")))
}

/// GET /consulta/api: la consulta en JSON (integración con otra app).
fn consulta_api(s: &Servidor, p: &mut Peticion) -> Res {
    let (rut, tipo, folio, monto, fecha) = parametros(p)?;
    if nombre_tipo(tipo).is_empty() {
        return Ok(json(
            400,
            &j!({"encontrada": false, "error": "tipo_no_valido"}),
        ));
    }
    let Some(d) = s.buscar_boleta(&rut, tipo, folio, monto, &fecha)? else {
        return Ok(json(200, &j!({"encontrada": false})));
    };
    let q = qs(&rut, tipo, folio, monto, &fecha);
    Ok(json(
        200,
        &j!({"encontrada": true, "documento": {
        "tipo": tipo, "tipo_nombre": nombre_tipo(tipo), "folio": d["folio"], "rut_emisor": d["rut_emisor"], "rut_receptor": d["rut_receptor"],
        "fecha_emision": d["fecha_emision"], "monto_neto": d["monto_neto"], "monto_exento": d["monto_exento"], "iva": d["iva"],
        "monto_total": d["monto_total"], "track_id": d["track_id"]},
        "links": {"pdf": format!("/consulta/pdf?{q}"), "xml": format!("/consulta/xml?{q}")}}),
    ))
}

fn consulta_xml(s: &Servidor, p: &mut Peticion) -> Res {
    let (rut, tipo, folio, monto, fecha) = parametros(p)?;
    let d = s.buscar_boleta(&rut, tipo, folio, monto, &fecha)?;
    let Some(d) = d.filter(|d| !texto(&d["xml_firmado"]).is_empty()) else {
        return Ok(json(404, &j!({"error": "no_encontrada"})));
    };
    Ok(Respuesta::binario(
        200,
        "application/xml",
        bytes_latin1(&texto(&d["xml_firmado"])),
    )
    .con(
        "Content-Disposition",
        &format!("attachment; filename=\"boleta_{tipo}_{folio}.xml\""),
    ))
}

/// Sirve el PDF guardado o lo regenera desde el XML (TED verbatim).
fn consulta_pdf(s: &Servidor, p: &mut Peticion) -> Res {
    let (rut, tipo, folio, monto, fecha) = parametros(p)?;
    let Some(d) = s.buscar_boleta(&rut, tipo, folio, monto, &fecha)? else {
        return Ok(json(404, &j!({"error": "no_encontrada"})));
    };
    let disp = format!("inline; filename=\"boleta_{tipo}_{folio}.pdf\"");
    let pp = s.ruta_desde_bd(&texto(&d["pdf_path"]));
    if !pp.is_empty() {
        if let Ok(b) = std::fs::read(&pp) {
            return Ok(
                Respuesta::binario(200, "application/pdf", b).con("Content-Disposition", &disp)
            );
        }
    }
    let xml = texto(&d["xml_firmado"]);
    if xml.is_empty() {
        return Ok(json(404, &j!({"error": "sin_xml"})));
    }
    match pdf::desde_xml(&bytes_latin1(&xml)).and_then(|(doc, ted)| pdf::boleta_80mm(&doc, &ted)) {
        Ok(b) => {
            Ok(Respuesta::binario(200, "application/pdf", b).con("Content-Disposition", &disp))
        }
        Err(e) => Ok(json(500, &j!({"error": "pdf_no_disponible", "detalle": e}))),
    }
}

fn dinero(v: &Value) -> String {
    let n = entero(v);
    let s = n.abs().to_string();
    let mut out = String::new();
    for (i, c) in s.chars().enumerate() {
        if i > 0 && (s.len() - i).is_multiple_of(3) {
            out.push('.');
        }
        out.push(c);
    }
    if n < 0 {
        format!("$-{out}")
    } else {
        format!("${out}")
    }
}

/// El formulario: verifica contra la base y muestra el resultado.
fn consulta_post(s: &Servidor, p: &mut Peticion) -> Res {
    let Some(f) = parsear_formulario(p) else {
        return Err(ErrorHTTP::datos_invalidos());
    };
    let (rut, folio_txt, monto_txt) = (
        f.valor("rut_emisor"),
        f.valor("folio"),
        f.valor("monto_total"),
    );
    let (tipo_txt, fch) = (
        f.valor("tipo_dte"),
        f.valor("fecha_emision").trim().to_string(),
    );
    for campo in ["rut_emisor", "tipo_dte", "folio", "monto_total"] {
        if !f.tiene(campo) || (f.valor(campo).is_empty() && campo == "tipo_dte") {
            return Err(ErrorHTTP::pydantic(
                "body",
                campo,
                "Field required",
                "missing",
            ));
        }
    }
    let tipo: i64 = tipo_txt
        .trim()
        .parse()
        .map_err(|_| ErrorHTTP::pydantic("body", "tipo_dte", INT_PARSING, "int_parsing"))?;
    let folio = folio_txt.trim().parse::<i64>();
    let monto = monto_txt.replace(['.', '$'], "").trim().parse::<i64>();
    let (Ok(folio), Ok(monto)) = (folio, monto) else {
        return Ok(Respuesta::html(&pagina_consulta(
            r#"<p class="no" style="margin-top:16px">Folio y monto deben ser números.</p>"#,
            &rut,
            &folio_txt,
            &monto_txt,
            tipo,
            &fch,
        )));
    };
    if nombre_tipo(tipo).is_empty() {
        return Ok(Respuesta::html(&pagina_consulta(
            r#"<p class="no" style="margin-top:16px">Tipo de documento no válido.</p>"#,
            &rut,
            &folio_txt,
            &monto_txt,
            39,
            &fch,
        )));
    }
    let Some(d) = s.buscar_boleta(&rut, tipo, folio, monto, &fch)? else {
        return Ok(Respuesta::html(&pagina_consulta(
            r#"<p class="no" style="margin-top:16px">No se encontró una boleta con esos datos. Verifique el RUT, tipo, folio, fecha y monto.</p>"#,
            &rut,
            &folio_txt,
            &monto_txt,
            tipo,
            &fch,
        )));
    };
    let mut recep = texto(&d["rut_receptor"]);
    if recep.is_empty() {
        recep = "—".into();
    }
    let filas = [
        (
            "Documento",
            format!("{} N° {}", nombre_tipo(tipo), entero(&d["folio"])),
        ),
        ("RUT emisor", texto(&d["rut_emisor"])),
        ("RUT receptor", recep),
        ("Fecha de emisión", texto(&d["fecha_emision"])),
        ("Monto neto", dinero(&d["monto_neto"])),
        ("Monto exento", dinero(&d["monto_exento"])),
        ("IVA", dinero(&d["iva"])),
        ("Monto total", dinero(&d["monto_total"])),
    ];
    let tabla: String = filas
        .iter()
        .map(|(a, b)| {
            format!(
                "<tr><td>{}</td><td>{}</td></tr>",
                html_escape(a),
                html_escape(b)
            )
        })
        .collect();
    let q = qs(&rut, tipo, folio, monto, &fch);
    let cuerpo = format!(
        r#"<p class="ok" style="margin-top:18px">✓ Boleta encontrada y válida.</p><table>{tabla}</table><div class="dl"><a href="/consulta/pdf?{q}">Descargar PDF</a><a href="/consulta/xml?{q}">Descargar XML</a></div>"#
    );
    Ok(Respuesta::html(&pagina_consulta(
        &cuerpo, &rut, &folio_txt, &monto_txt, tipo, &fch,
    )))
}

#[cfg(test)]
mod tests {
    /// Las páginas embebidas son copias exactas de las que embebe el servidor Go (y de static/).
    #[test]
    fn static_igual() {
        let raiz =
            std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../nucleo/servidor/static");
        for (n, b) in super::PAGINAS {
            if let Ok(f) = std::fs::read(raiz.join(format!("{n}.html"))) {
                assert_eq!(f, b, "{n}.html difiere de nucleo/servidor/static");
            }
        }
    }
}
