//! Historial de emitidos (mipeAdminDocsEmi.cgi): tabla paginada "Página N de M"; cada fila
//! trae un enlace con `CODIGO=<DHDR>` y las celdas [RUT receptor, razón social, tipo (texto),
//! folio, fecha, monto, estado]. OJO: el monto del listado es la LÍNEA, no el total firmado.

use super::html::{
    codificar_latin1, codificar_utf8, parsear_filas, parsear_form_ordenado, Form, Par,
};
use super::{Cliente, Error, Opciones, RespuestaPortal, Resultado, BASE, COMENTARIO_FIRMA};
use crate::htmlent::unescape;
use regex::Regex;
use serde_json::Value;
use std::sync::OnceLock;

fn re(cache: &'static OnceLock<Regex>, pat: &str) -> &'static Regex {
    cache.get_or_init(|| Regex::new(pat).expect("regex"))
}

/// Una fila del historial (mismos nombres JSON que el dataclass Python).
#[derive(Debug, Clone, Default, PartialEq, Eq, serde::Serialize)]
pub struct DocumentoEmitido {
    pub dhdr: String,
    pub tipo_texto: String,
    pub folio: i32,
    /// YYYY-MM-DD
    pub fecha: String,
    pub monto: i64,
    pub estado: String,
    pub receptor_rut: String,
    pub receptor_razon: String,
}

impl DocumentoEmitido {
    /// `tipo_desde_texto` sobre la celda de tipo; 0 si no se reconoce.
    pub fn tipo(&self) -> i32 {
        tipo_desde_texto(&self.tipo_texto)
    }
}

static RE_TIPO_NUM: OnceLock<Regex> = OnceLock::new();
static RE_NO_DIGITO: OnceLock<Regex> = OnceLock::new();
static RE_FECHA_CL: OnceLock<Regex> = OnceLock::new();
static RE_FECHA_ISO: OnceLock<Regex> = OnceLock::new();
static RE_ESPACIOS: OnceLock<Regex> = OnceLock::new();
static RE_CODIGO: OnceLock<Regex> = OnceLock::new();
static RE_PAGINA_DE: OnceLock<Regex> = OnceLock::new();
static RE_TEXTAREA: OnceLock<Regex> = OnceLock::new();
static RE_XML_INICIO: OnceLock<Regex> = OnceLock::new();
static RE_WHILE1: OnceLock<Regex> = OnceLock::new();
static RE_OBJ_JS: OnceLock<Regex> = OnceLock::new();
static RE_STATUS_JS: OnceLock<Regex> = OnceLock::new();
static RE_TEXT_JS: OnceLock<Regex> = OnceLock::new();

pub(crate) fn re_no_digito() -> &'static Regex {
    re(&RE_NO_DIGITO, r"[^\d]")
}

/// El listado muestra el tipo como texto ("FACTURA NO AFECTA O EXENTA ELECTRONICA").
pub fn tipo_desde_texto(texto: &str) -> i32 {
    let t = texto.to_uppercase();
    if let Some(m) = re(&RE_TIPO_NUM, r"\b(33|34|39|41|46|52|56|61)\b").captures(&t) {
        return m[1].parse().unwrap_or(0);
    }
    const TIPOS: [(&str, i32); 6] = [
        (r"NOTA\s+DE\s+CR[EÉ]DITO", 61),
        (r"NOTA\s+DE\s+D[EÉ]BITO", 56),
        (r"GU[IÍ]A\s+DE\s+DESPACHO", 52),
        (r"FACTURA\s+DE\s+COMPRA", 46),
        (r"EXENTA|NO\s+AFECTA", 34),
        (r"FACTURA", 33),
    ];
    for (pat, tipo) in TIPOS {
        if Regex::new(pat).expect("regex").is_match(&t) {
            return tipo;
        }
    }
    0
}

fn monto_desde_texto(texto: &str) -> i64 {
    let d = re_no_digito().replace_all(texto.split(',').next().unwrap_or(""), "");
    d.parse().unwrap_or(0)
}

fn fecha_iso(texto: &str) -> String {
    let t = texto.trim();
    if let Some(m) = re(&RE_FECHA_CL, r"^(\d{1,2})[/-](\d{1,2})[/-](\d{4})").captures(t) {
        let (dia, mes): (u32, u32) = (m[1].parse().unwrap_or(0), m[2].parse().unwrap_or(0));
        return format!("{}-{mes:02}-{dia:02}", &m[3]);
    }
    if let Some(m) = re(&RE_FECHA_ISO, r"^(\d{4})-(\d{2})-(\d{2})").find(t) {
        return m.as_str().to_string();
    }
    t.to_string()
}

/// `parsear_listado`: `(documentos, última_página)` de una página del historial.
pub fn parsear_listado(doc: &str) -> (Vec<DocumentoEmitido>, i32) {
    let mut docs = Vec::new();
    let rcod = re(&RE_CODIGO, r"[?&]CODIGO=(\d+)");
    let resp = re(&RE_ESPACIOS, r"\s+");
    for f in parsear_filas(doc) {
        let dhdr = f
            .hrefs
            .iter()
            .find_map(|h| rcod.captures(h).map(|m| m[1].to_string()))
            .unwrap_or_default();
        let celdas: Vec<String> = f
            .celdas
            .iter()
            .map(|c| resp.replace_all(c, " ").trim().to_string())
            .filter(|c| !c.is_empty())
            .collect();
        if dhdr.is_empty() || celdas.len() < 7 {
            continue;
        }
        let Ok(folio) = re_no_digito().replace_all(&celdas[3], "").parse::<i32>() else {
            continue;
        };
        docs.push(DocumentoEmitido {
            dhdr,
            tipo_texto: celdas[2].clone(),
            folio,
            fecha: fecha_iso(&celdas[4]),
            monto: monto_desde_texto(&celdas[5]),
            estado: celdas[6].clone(),
            receptor_rut: celdas[0].replace('.', ""),
            receptor_razon: celdas[1].clone(),
        });
    }
    let ultima = re(&RE_PAGINA_DE, r"[Pp][áa]gina\s+\d+\s+(?:de|/)\s+(\d+)")
        .captures(doc)
        .and_then(|m| m[1].parse().ok())
        .unwrap_or(1);
    (docs, ultima)
}

/// `preparar_dato_firma`: el comentario que el JS del portal inserta antes de `<Documento` (o
/// `<Liquidacion`/`<Exportaciones`) antes de mandar a firmar. Idempotente.
pub fn preparar_dato_firma(xml: &str) -> String {
    if xml.contains("<!-- O ") {
        return xml.to_string();
    }
    for tag in ["<Documento ", "<Liquidacion ", "<Exportaciones "] {
        if xml.contains(tag) {
            return xml.replacen(tag, &format!("{COMENTARIO_FIRMA}\n{tag}"), 1);
        }
    }
    xml.to_string()
}

/// `parsear_respuesta_firma`: `postFirmaDigital` responde JSON `{"status"|"statusCode": n,
/// "text": "<xml>"}` (a veces con prefijo `while(1);`), un objeto estilo JS, o el XML directo.
/// Devuelve (status, xml); 0 = OK, 2 = clave del certificado incorrecta, -1 = formato
/// desconocido.
pub fn parsear_respuesta_firma(cruda: &str) -> (i32, String) {
    let t = cruda.trim();
    let t = re(&RE_WHILE1, r"^while\s*\(\s*1\s*\)\s*;?").replace(t, "");
    let t = t.trim();
    if re(&RE_XML_INICIO, r"(?i)^\s*<\?xml|^\s*<DTE\b").is_match(t) {
        return (0, t.to_string());
    }
    if let Some(r) = json_firma(t) {
        return r;
    }
    if let Some(bloque) = re(&RE_OBJ_JS, r"(?s)\{.*\}").find(t).map(|m| m.as_str()) {
        if let Some(r) = json_firma(bloque) {
            return r;
        }
        let ms = re(&RE_STATUS_JS, r"(?i)\b(?:statusCode|status)\b\s*:\s*(\d+)").captures(bloque);
        let mt = re(
            &RE_TEXT_JS,
            r#"(?is)\btext\b\s*:\s*["']([\s\S]*?)["']\s*(?:,|\})"#,
        )
        .captures(bloque);
        if let (Some(ms), Some(mt)) = (ms, mt) {
            return (ms[1].parse().unwrap_or(0), mt[1].to_string());
        }
    }
    (-1, String::new())
}

fn json_firma(t: &str) -> Option<(i32, String)> {
    let obj: Value = serde_json::from_str(t).ok()?;
    let v = obj.get("statusCode").or_else(|| obj.get("status"))?;
    let st = match v {
        Value::Number(n) => n.as_f64().unwrap_or(0.0) as i32,
        Value::String(s) => s.parse().unwrap_or(0),
        _ => 0,
    };
    let txt = obj
        .get("text")
        .and_then(|x| x.as_str())
        .unwrap_or("")
        .to_string();
    Some((st, txt))
}

impl Cliente {
    /// `listar_emitidos`: todas las páginas del historial (hasta 20). `tipo`, `desde` y `hasta`
    /// son los filtros del portal (vacío = todos). Solo lectura.
    pub fn listar_emitidos(
        &mut self,
        tipo: &str,
        desde: &str,
        hasta: &str,
    ) -> Resultado<Vec<DocumentoEmitido>> {
        self.requiere_empresa()?;
        const PAG_MAX: i32 = 20;
        let mut orden: Vec<String> = Vec::new();
        let mut todos: std::collections::HashMap<String, DocumentoEmitido> =
            std::collections::HashMap::new();
        let mut pag = 1;
        while pag <= PAG_MAX {
            let params = [
                Par::new("RUT_RECP", ""),
                Par::new("FOLIO", ""),
                Par::new("RZN_SOC", ""),
                Par::new("FEC_DESDE", desde),
                Par::new("FEC_HASTA", hasta),
                Par::new("TPO_DOC", tipo),
                Par::new("ESTADO", ""),
                Par::new("ORDEN", ""),
                Par::new("NUM_PAG", pag.to_string()),
            ];
            let r = self.req(
                "GET",
                &format!("{BASE}/mipeAdminDocsEmi.cgi"),
                Opciones {
                    navegacion: true,
                    referer: &format!("{BASE}/mipeSelEmpresa.cgi"),
                    params: Some(&params),
                    ..Default::default()
                },
            )?;
            if r.rechazado() {
                return Err(Error::Rechazo(format!(
                    "el portal no entregó el historial de emitidos (http {}, página {pag})",
                    r.status
                )));
            }
            let (docs, ultima) = parsear_listado(&r.texto());
            let mut nuevos = 0;
            for d in docs {
                if !todos.contains_key(&d.dhdr) {
                    orden.push(d.dhdr.clone());
                    todos.insert(d.dhdr.clone(), d);
                    nuevos += 1;
                }
            }
            if pag >= ultima.max(1) || nuevos == 0 {
                break;
            }
            std::thread::sleep(self.pausa);
            pag += 1;
        }
        Ok(orden.into_iter().filter_map(|k| todos.remove(&k)).collect())
    }

    /// `leer_form`: el formulario de emisión pre-llenado "igual al último emitido". De aquí
    /// salen los datos del emisor según el portal. NO gasta folio.
    pub fn leer_form(&mut self, tipo: i32) -> Resultado<Form> {
        self.requiere_empresa()?;
        let params = [
            Par::new("IGUAL", "ULT_FAC"),
            Par::new("PTDC_CODIGO", tipo.to_string()),
            Par::new("ES_BORR", "FALSE"),
            Par::new("esCRED_EC", "FALSE"),
            Par::new("esFACT_TUR", "FALSE"),
        ];
        let r = self.req(
            "GET",
            &format!("{BASE}/mipeGenFacEx.cgi"),
            Opciones {
                navegacion: true,
                referer: &format!("{BASE}/mipeSelEmpresa.cgi"),
                params: Some(&params),
                ..Default::default()
            },
        )?;
        if r.rechazado() || r.cuerpo.len() < 5000 {
            return Err(Error::Rechazo(format!("el portal no entregó el formulario de emisión (¿sesión expirada, empresa sin documentos previos?; http {})", r.status)));
        }
        let doc = r.texto();
        self.traza(&format!("form_{tipo}.html"), &doc);
        Ok(parsear_form_ordenado(&doc))
    }

    /// `descargar_pdf`: el PDF que el portal genera para un DHDR.
    pub fn descargar_pdf(&mut self, dhdr: &str) -> Resultado<Vec<u8>> {
        let params = [Par::new("DHDR_CODIGO", dhdr)];
        let r = self.req(
            "GET",
            &format!("{BASE}/mipeDisplayPDF.cgi"),
            Opciones {
                navegacion: true,
                referer: &format!("{BASE}/mipeGesDocEmi.cgi?ALL_PAGE_ANT=2&CODIGO={dhdr}"),
                params: Some(&params),
                ..Default::default()
            },
        )?;
        if !r.cuerpo.starts_with(b"%PDF") {
            return Err(Error::Sii(format!(
                "el portal no devolvió un PDF (dhdr {dhdr}, http {})",
                r.status
            )));
        }
        Ok(r.cuerpo)
    }

    /// `_firma_central`: `postFirmaDigital` exactamente como el XHR del navegador (form UTF-8
    /// con charset declarado, X-Requested-With, Accept text/plain). Responde el XML firmado en
    /// texto plano ISO-8859-1.
    pub(crate) fn firma_central(
        &mut self,
        dato: &str,
        nodo: &str,
        nodo_id: &str,
        referer: &str,
    ) -> Resultado<(RespuestaPortal, String)> {
        let (n, dv) = super::separar_rut(&self.rut_usuario);
        let cuerpo = codificar_utf8(&[
            Par::new("nombre", "1"),
            Par::new("dato", dato),
            Par::new("rut", n),
            Par::new("dv", dv),
            Par::new("clave", self.clave_cert.clone()),
            Par::new("nodo", nodo),
            Par::new("nodoId", nodo_id),
            Par::new("nameSpace", "http://www.sii.cl/SiiDte"),
        ]);
        let extra = [
            ("X-Requested-With", "XMLHttpRequest"),
            ("Accept", "text/plain, */*; q=0.01"),
            (
                "Content-Type",
                "application/x-www-form-urlencoded; charset=UTF-8",
            ),
        ];
        let r = self.req(
            "POST",
            &format!("{BASE}/postFirmaDigital.cgi"),
            Opciones {
                navegacion: false,
                content: Some(&cuerpo),
                referer,
                origin: "https://www1.sii.cl",
                extra: Some(&extra),
                ..Default::default()
            },
        )?;
        let texto = r.texto();
        Ok((r, texto))
    }

    /// `obtener_envio_xml`: el EnvioDTE (con el DTE firmado adentro) de un documento emitido,
    /// botón "Obtener Envío" del portal: GET mipeGenDLNewEnvio → textarea txtPlainText → firma
    /// central del EnvioDTE (nodo dte:EnvioDTE / dte:SetDTE, clave del certificado) → POST
    /// mipeDownLoadNewEnvio → adjunto .xml (bytes ISO-8859-1). NO gasta folio.
    pub fn obtener_envio_xml(
        &mut self,
        dhdr: &str,
        tipo: i32,
        rut_receptor: &str,
    ) -> Resultado<Vec<u8>> {
        self.requiere_empresa()?;
        if self.clave_cert.is_empty() {
            return Err(Error::Validacion(
                "obtener el XML exige la clave del certificado (firma central)".into(),
            ));
        }
        let (rn, rdv) = super::separar_rut(rut_receptor);
        let params = [
            Par::new("CODIGO", dhdr),
            Par::new("TPO_DOC", tipo.to_string()),
            Par::new("RUT_RCP", rn),
            Par::new("DV_RCP", rdv),
        ];
        let r = self.req(
            "GET",
            &format!("{BASE}/mipeGenDLNewEnvio.cgi"),
            Opciones {
                navegacion: true,
                referer: &format!("{BASE}/mipeGesDocEmi.cgi?ALL_PAGE_ANT=2&CODIGO={dhdr}"),
                params: Some(&params),
                ..Default::default()
            },
        )?;
        let texto = r.texto();
        let m = re(
            &RE_TEXTAREA,
            r#"(?is)<textarea\b[^>]*id=["']txtPlainText["'][^>]*>([\s\S]*?)</textarea>"#,
        )
        .captures(&texto);
        let Some(m) = m.filter(|_| !r.rechazado()) else {
            return Err(Error::Rechazo(format!(
                "el portal no entregó el envío para firmar (dhdr {dhdr}, http {})",
                r.status
            )));
        };
        let plano = unescape(&m[1]);
        let (_, firmado_crudo) = self.firma_central(
            &preparar_dato_firma(&plano),
            "dte:EnvioDTE",
            "dte:SetDTE",
            &format!("{BASE}/mipeGenDLNewEnvio.cgi"),
        )?;
        let (estado, firmado) = parsear_respuesta_firma(&firmado_crudo);
        if estado != 0 || !firmado.contains("<Signature") {
            return Err(Error::Rechazo(format!("la firma central del envío falló (¿clave del certificado?; dhdr {dhdr}, estado {estado})")));
        }
        let cuerpo =
            codificar_latin1(&[Par::new("txtSignText", firmado)]).map_err(Error::Validacion)?;
        let r = self.req(
            "POST",
            &format!("{BASE}/mipeDownLoadNewEnvio.cgi"),
            Opciones {
                navegacion: true,
                content: Some(&cuerpo),
                referer: &format!("{BASE}/mipeGenDLNewEnvio.cgi"),
                origin: "https://www1.sii.cl",
                ..Default::default()
            },
        )?;
        if r.status != 200 || !r.cuerpo.windows(9).any(|w| w == b"<EnvioDTE") {
            return Err(Error::Rechazo(format!(
                "el portal no devolvió el XML del envío (dhdr {dhdr}, http {})",
                r.status
            )));
        }
        Ok(r.cuerpo)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    pub const HTML_LISTADO: &str = r#"
<table>
<tr><th>RUT</th><th>Razón Social</th><th>Tipo</th><th>Folio</th><th>Fecha</th><th>Monto</th><th>Estado</th><th></th></tr>
<tr><td>76.111.111-6</td><td>CLIENTE DEMO SPA</td><td>FACTURA NO AFECTA O EXENTA ELECTRONICA</td><td>59</td>
    <td>06/09/2026</td><td>3.270.323</td><td>Aceptado</td><td><a href="mipeGesDocEmi.cgi?ALL_PAGE_ANT=2&CODIGO=2850540417">ver</a></td></tr>
<tr><td>76.111.111-6</td><td>CLIENTE DEMO SPA</td><td>NOTA DE CREDITO ELECTRONICA</td><td>56</td>
    <td>2026-09-06</td><td>$3.068.005</td><td>Aceptado con Reparos</td><td><a href="mipeGesDocEmi.cgi?CODIGO=2850540999">ver</a></td></tr>
<tr><td colspan="8">Página 1 de 3</td></tr>
</table>
"#;

    #[test]
    fn listado() {
        let (docs, ultima) = parsear_listado(HTML_LISTADO);
        let want = vec![
            DocumentoEmitido {
                dhdr: "2850540417".into(),
                tipo_texto: "FACTURA NO AFECTA O EXENTA ELECTRONICA".into(),
                folio: 59,
                fecha: "2026-09-06".into(),
                monto: 3270323,
                estado: "Aceptado".into(),
                receptor_rut: "76111111-6".into(),
                receptor_razon: "CLIENTE DEMO SPA".into(),
            },
            DocumentoEmitido {
                dhdr: "2850540999".into(),
                tipo_texto: "NOTA DE CREDITO ELECTRONICA".into(),
                folio: 56,
                fecha: "2026-09-06".into(),
                monto: 3068005,
                estado: "Aceptado con Reparos".into(),
                receptor_rut: "76111111-6".into(),
                receptor_razon: "CLIENTE DEMO SPA".into(),
            },
        ];
        assert_eq!(ultima, 3);
        assert_eq!(docs, want);
        assert_eq!((docs[0].tipo(), docs[1].tipo()), (34, 61));
        assert_eq!(
            (
                tipo_desde_texto("FACTURA ELECTRONICA"),
                tipo_desde_texto("GUIA DE DESPACHO ELECTRONICA"),
                tipo_desde_texto("RARO")
            ),
            (33, 52, 0)
        );
    }

    #[test]
    fn respuesta_firma() {
        let casos: [(&str, i32, &str); 5] = [
            (
                r#"while(1);{"status":0,"text":"<DTE>x</DTE>"}"#,
                0,
                "<DTE>x</DTE>",
            ),
            (
                r#"{"statusCode":2,"text":"Clave no corresponde"}"#,
                2,
                "Clave no corresponde",
            ),
            (
                r#"<?xml version="1.0"?><DTE/>"#,
                0,
                r#"<?xml version="1.0"?><DTE/>"#,
            ),
            ("basura", -1, ""),
            (
                r#"pre {status: 0, text: "<DTE>a</DTE>"} post"#,
                0,
                "<DTE>a</DTE>",
            ),
        ];
        for (entrada, st, txt) in casos {
            assert_eq!(
                parsear_respuesta_firma(entrada),
                (st, txt.to_string()),
                "{entrada:?}"
            );
        }
        let entrada = "<?xml version=\"1.0\"?>\n<EnvioDTE><SetDTE><DTE><Documento ID=\"x\"/></DTE></SetDTE></EnvioDTE>";
        let want = format!("<?xml version=\"1.0\"?>\n<EnvioDTE><SetDTE><DTE>{COMENTARIO_FIRMA}\n<Documento ID=\"x\"/></DTE></SetDTE></EnvioDTE>");
        let got = preparar_dato_firma(entrada);
        assert_eq!(got, want);
        assert_eq!(preparar_dato_firma(&got), want);
    }
}
