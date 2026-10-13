//! Segmentos 2-4 del SII engine: armado del payload (puro), "Validar y visualizar", NC de
//! anulación y de corrección de montos, y la emisión real (GenXMLFirma → firma central →
//! mipeSendXML → PDF). Réplica de `core/sii_mipyme.py`; la vara son los cuerpos byte a byte
//! de la factura 63 y la NC 60 (`storage/mipyme_fallidos/…`).

use super::evidencia::guardar_evidencia;
use super::html::{codificar_latin1, parsear_form, parsear_form_ordenado, Form, Par};
use super::lectura::{parsear_respuesta_firma, preparar_dato_firma, re_no_digito};
use super::schema::*;
use super::{
    formatear_rut, separar_rut, validar_rut, Cliente, Error, Opciones, Resultado, BASE,
    TIPO_NOTA_CREDITO, TIPO_NOTA_DEBITO,
};
use crate::almacen::{self, Almacen};
use crate::htmlent::unescape;
use regex::Regex;
use std::collections::{BTreeMap, HashMap};
use std::sync::OnceLock;

fn re(cache: &'static OnceLock<Regex>, pat: &str) -> &'static Regex {
    cache.get_or_init(|| Regex::new(pat).expect("regex"))
}

/// `ReceptorMipyme`.
#[derive(Debug, Clone, Default, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
#[serde(default)]
pub struct Receptor {
    pub rut: String,
    pub razon_social: String,
    pub giro: String,
    pub direccion: String,
    pub ciudad: String,
    pub comuna: String,
}

impl Receptor {
    fn validar(&self) -> Resultado<()> {
        if !validar_rut(&self.rut) {
            return Err(Error::Validacion(format!(
                "RUT de receptor inválido: {}",
                self.rut
            )));
        }
        Ok(())
    }
}

/// `ItemMipyme`.
#[derive(Debug, Clone, Default, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
#[serde(default)]
pub struct Item {
    pub nombre: String,
    pub precio: i64,
    pub cantidad: i64,
    pub descripcion: String,
}

impl Item {
    /// precio × cantidad
    pub fn subtotal(&self) -> i64 {
        self.precio * self.cantidad
    }
}

fn suma_items(items: &[Item]) -> i64 {
    items.iter().map(Item::subtotal).sum()
}

/// Una referencia a otro documento (NC/ND).
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct Referencia {
    pub tipo: i32,
    pub folio: i64,
    /// YYYY-MM-DD
    pub fecha: String,
    /// "" → CODIGO_REF_ANULA
    pub codigo: String,
    /// "" → RAZON_REF_ANULA
    pub razon: String,
}

/// `PayloadMipyme`: listo para mipeGenXMLFirma, en el orden del schema (o del HTML en las
/// notas). `campos_nuevos` es el drift: inputs que el HTML trae y el schema no conoce.
#[derive(Debug, Clone, Default)]
pub struct Payload {
    pub tipo: i32,
    pub pares: Vec<Par>,
    pub campos_nuevos: Vec<String>,
    referer_emision: String,
}

impl Payload {
    /// El valor de un campo ("" si no está).
    pub fn valor(&self, nombre: &str) -> String {
        self.pares
            .iter()
            .find(|p| p.nombre == nombre)
            .map(|p| p.valor.clone())
            .unwrap_or_default()
    }

    /// EFXP_MNT_TOTAL como entero.
    pub fn monto_total(&self) -> i64 {
        self.valor("EFXP_MNT_TOTAL").parse().unwrap_or(0)
    }
}

fn hoy() -> String {
    almacen::ahora_iso()[..10].to_string()
}

/// `armar_payload`: payload = schema (orden) + valores del HTML fresco + sustituciones
/// nuestras. Los montos van SIEMPRE alineados (PRC/SUBT de cada ítem y los 3 totales salen del
/// mismo número; HED-2-220 si no). En las notas el navegador manda el form PreViewDTE tal cual
/// (orden y campos del HTML, incluidos los que el schema no conoce) con nuestras sustituciones
/// encima, y lo que el HTML no trae pero el schema exige va al final.
#[allow(clippy::too_many_arguments)]
pub fn armar_payload(
    form: &Form,
    tipo: i32,
    receptor: &Receptor,
    items: &[Item],
    fecha: &str,
    forma_pago: &str,
    referencias: &[Referencia],
    respetar_html: &[&str],
) -> Resultado<Payload> {
    if items.is_empty() {
        return Err(Error::Validacion(
            "la factura necesita al menos un ítem".into(),
        ));
    }
    if items.len() > 10 {
        return Err(Error::Validacion(
            "el form del portal admite hasta 10 ítems".into(),
        ));
    }
    receptor.validar()?;
    let fecha = if fecha.is_empty() {
        hoy()
    } else {
        fecha.to_string()
    };
    let (rut_n, dv) = separar_rut(&receptor.rut);
    let total = suma_items(items);
    let mut subs: HashMap<String, String> = HashMap::new();
    let mut poner = |k: &str, v: String| {
        subs.insert(k.to_string(), v);
    };
    poner("INDICA_PRIMERA_EJECUCION", "1".into());
    poner("ES_BORR", "FALSE".into());
    poner("PTDC_CODIGO", tipo.to_string());
    poner("EFXP_FMA_PAGO", forma_pago.into());
    poner("EFXP_FCH_EMIS", fecha.clone());
    poner("EFXP_RUT_RECEP", rut_n);
    poner("EFXP_DV_RECEP", dv);
    poner("EFXP_RZN_SOC_RECEP", receptor.razon_social.clone());
    poner("EFXP_GIRO_RECEP", receptor.giro.clone());
    poner("EFXP_DIR_RECEP", receptor.direccion.clone());
    poner("EFXP_CIUDAD_RECEP", receptor.ciudad.clone());
    poner("EFXP_CMNA_RECEP", receptor.comuna.clone());
    for i in 1..=10 {
        // limpiar los 10 ítems que el form pre-llena "igual al último"
        for c in CAMPOS_ITEM {
            poner(&format!("EFXP_{c}_{i:02}"), String::new());
        }
    }
    let es_nota = tipo == TIPO_NOTA_CREDITO || tipo == TIPO_NOTA_DEBITO;
    if !es_nota {
        for i in 1..=3 {
            // una factura nueva no hereda referencias del último documento
            for c in CAMPOS_REF {
                poner(&format!("EFXP_{c}_{i:03}"), String::new());
            }
        }
        poner("EFXP_PCT_DESC", "0".into());
        poner("EFXP_MNT_DESC", "0".into());
    }
    for (n, it) in items.iter().enumerate() {
        let k = format!("{:02}", n + 1);
        poner(&format!("EFXP_NMB_{k}"), it.nombre.clone());
        poner(&format!("EFXP_QTY_{k}"), it.cantidad.to_string());
        poner(&format!("EFXP_PRC_{k}"), it.precio.to_string());
        poner(&format!("EFXP_SUBT_{k}"), it.subtotal().to_string());
        poner(&format!("EFXP_DSC_ITEM_{k}"), it.descripcion.clone());
    }
    for c in CAMPOS_MONTO_TOTAL {
        poner(c, total.to_string());
    }
    for (n, r) in referencias.iter().enumerate() {
        let k = format!("{:03}", n + 1);
        let codigo = if r.codigo.is_empty() {
            CODIGO_REF_ANULA
        } else {
            &r.codigo
        };
        let razon = if r.razon.is_empty() {
            RAZON_REF_ANULA
        } else {
            &r.razon
        };
        poner(&format!("EFXP_TPO_DOC_REF_{k}"), r.tipo.to_string());
        poner(&format!("EFXP_FOLIO_REF_{k}"), r.folio.to_string());
        poner(&format!("EFXP_FCH_REF_{k}"), r.fecha.clone());
        poner(&format!("EFXP_CODIGO_REF_{k}"), codigo.into());
        poner(&format!("EFXP_RAZON_REF_{k}"), razon.into());
    }
    for n in respetar_html {
        // campos que NO se sobreescriben
        if let Some(v) = form.campos.get(*n) {
            poner(n, v.clone());
        }
    }
    let mut pares: Vec<Par> = Vec::new();
    if es_nota {
        for n in &form.orden {
            if n == "btnSign" || n == "btnVolver" {
                continue;
            }
            let v = subs
                .get(n)
                .cloned()
                .unwrap_or_else(|| form.campos.get(n).cloned().unwrap_or_default());
            pares.push(Par::new(n.clone(), v));
        }
        for n in schema_campos() {
            if !form.campos.contains_key(n) {
                pares.push(Par::new(
                    n.clone(),
                    subs.get(n).cloned().unwrap_or_default(),
                ));
            }
        }
    } else {
        for n in schema_campos() {
            let v = subs
                .get(n)
                .cloned()
                .unwrap_or_else(|| form.campos.get(n).cloned().unwrap_or_default());
            pares.push(Par::new(n.clone(), v));
        }
    }
    let mut nuevos: Vec<String> = form
        .campos
        .keys()
        .filter(|n| !en_schema(n) && !es_campo_helper(n))
        .cloned()
        .collect();
    nuevos.sort();
    Ok(Payload {
        tipo,
        pares,
        campos_nuevos: nuevos,
        referer_emision: String::new(),
    })
}

// ---------------------------------------------------------------------------
// La página de firma (respuesta de mipeGenXMLFirma) y el cuerpo de mipeSendXML
// ---------------------------------------------------------------------------

/// El `<form name="frmSign">` que devuelve mipeGenXMLFirma: lo que el navegador manda a
/// mipeSendXML (más txtSignText y los datos de firma). `crudos` es la lista en orden del HTML,
/// CON duplicados (el frmSign real trae EFXP_FMA_PAGO dos veces y el navegador manda las dos;
/// captura 2026-10-08, factura 62).
#[derive(Debug, Clone, Default)]
pub struct FormFirma {
    pub action: String,
    pub campos: BTreeMap<String, String>,
    pub crudos: Vec<Par>,
}

static RE_FORM_TAG: OnceLock<Regex> = OnceLock::new();
static RE_ATTR_NAME: OnceLock<Regex> = OnceLock::new();
static RE_ATTR_ACT: OnceLock<Regex> = OnceLock::new();
static RE_ATTR_VALUE: OnceLock<Regex> = OnceLock::new();
static RE_INPUT_TAG: OnceLock<Regex> = OnceLock::new();
static RE_TEXTAREA_T: OnceLock<Regex> = OnceLock::new();
static RE_XML_DTE: OnceLock<Regex> = OnceLock::new();
static RE_VAR_XML: OnceLock<Regex> = OnceLock::new();
static RE_FOLIO: OnceLock<Regex> = OnceLock::new();
static RE_TMST_FIRMA: OnceLock<Regex> = OnceLock::new();
static RE_MNT_TOTAL: OnceLock<Regex> = OnceLock::new();
static RE_CODIGO_SII: OnceLock<Regex> = OnceLock::new();
static RE_DHDR: OnceLock<Regex> = OnceLock::new();
static RE_EXITO: OnceLock<Regex> = OnceLock::new();
static RE_FIRMA_NO: OnceLock<Regex> = OnceLock::new();
static RE_CLAVE_NO: OnceLock<Regex> = OnceLock::new();

pub(crate) fn re_tmst_firma() -> &'static Regex {
    re(&RE_TMST_FIRMA, r"<TmstFirma>([^<]+)</TmstFirma>")
}

/// `extraer_form_firma`. `None` si la página no trae frmSign.
pub fn extraer_form_firma(doc: &str) -> Option<FormFirma> {
    let rform = re(&RE_FORM_TAG, r"(?is)<form\b([^>]*)>([\s\S]*?)</form>");
    let rname = re(&RE_ATTR_NAME, r#"(?i)name=["']([^"']+)"#);
    let ract = re(&RE_ATTR_ACT, r#"(?i)action=["']([^"']*)"#);
    let rvalue = re(&RE_ATTR_VALUE, r#"(?i)value=["']([^"']*)"#);
    let rinput = re(&RE_INPUT_TAG, r"(?i)<input\b([^>]*)>");
    let rtextarea = re(
        &RE_TEXTAREA_T,
        r"(?is)<textarea\b([^>]*)>([\s\S]*?)</textarea>",
    );
    for m in rform.captures_iter(doc) {
        let (attrs, inner) = (&m[1], &m[2]);
        let Some(nombre) = rname.captures(attrs) else {
            continue;
        };
        if nombre[1].to_lowercase() != "frmsign" {
            continue;
        }
        let mut f = FormFirma {
            campos: parsear_form(&format!("<form>{inner}</form>")),
            ..Default::default()
        };
        if let Some(a) = ract.captures(attrs) {
            f.action = a[1].to_string();
        }
        let mut encontrados: Vec<(usize, Par)> = Vec::new();
        for im in rinput.captures_iter(inner) {
            let attrs_in = &im[1];
            let Some(n) = rname.captures(attrs_in) else {
                continue;
            };
            let v = rvalue
                .captures(attrs_in)
                .map(|vm| unescape(&vm[1]))
                .unwrap_or_default();
            encontrados.push((im.get(0).unwrap().start(), Par::new(n[1].to_string(), v)));
        }
        for tm in rtextarea.captures_iter(inner) {
            let Some(n) = rname.captures(&tm[1]) else {
                continue;
            };
            encontrados.push((
                tm.get(0).unwrap().start(),
                Par::new(n[1].to_string(), unescape(&tm[2])),
            ));
        }
        encontrados.sort_by_key(|(pos, _)| *pos);
        f.crudos = encontrados.into_iter().map(|(_, p)| p).collect();
        return Some(f);
    }
    None
}

/// `extraer_xml_dte`: el XML del DTE embebido en la página de GenXMLFirma.
pub fn extraer_xml_dte(doc: &str) -> String {
    if let Some(m) = re(&RE_XML_DTE, r"(?s)<\?xml.*?</DTE>").find(doc) {
        return m.as_str().to_string();
    }
    if let Some(m) = re(
        &RE_VAR_XML,
        r#"(?s)var\s+\w*[Xx][Mm][Ll]\w*\s*=\s*['"](.*?)['"];"#,
    )
    .captures(doc)
    {
        return m[1].to_string();
    }
    String::new()
}

fn crlf(t: &str) -> String {
    t.replace("\r\n", "\n").replace('\n', "\r\n")
}

/// `armar_send_xml_desde_form`: el body de mipeSendXML tal como lo manda el navegador (captura
/// completa de la factura 62): TODOS los inputs del frmSign (con duplicados) más lo que el JS
/// rellena (txtSignText, nombre, clave, nodo, nodoId, nameSpace; TMST_SIGN como venga en la
/// página), los dos XML con CRLF, y el conjunto ordenado por nombre en orden ASCII (orden
/// estable: los duplicados conservan su orden relativo).
pub fn armar_send_xml_desde_form(
    f: &FormFirma,
    xml_firmado: &str,
    clave_cert: &str,
    tmst_firma: &str,
) -> Vec<Par> {
    let crudos: Vec<Par> = if f.crudos.is_empty() {
        f.campos
            .iter()
            .map(|(n, v)| Par::new(n.clone(), v.clone()))
            .collect()
    } else {
        f.crudos.clone()
    };
    const OMITIR: [&str; 8] = [
        "btnSign",
        "btnVolver",
        "txtSignText",
        "nombre",
        "clave",
        "nodo",
        "nodoId",
        "nameSpace",
    ];
    let mut pares: Vec<Par> = Vec::new();
    let mut tiene_tmst = false;
    for p in crudos {
        if OMITIR.contains(&p.nombre.as_str()) {
            continue;
        }
        if p.nombre == "TMST_SIGN" && !p.valor.is_empty() {
            tiene_tmst = true;
        }
        pares.push(p);
    }
    if !tiene_tmst {
        pares.retain(|p| p.nombre != "TMST_SIGN");
        pares.push(Par::new("TMST_SIGN", tmst_firma));
    }
    let o = |k: &str, def: &str| {
        f.campos
            .get(k)
            .filter(|v| !v.is_empty())
            .cloned()
            .unwrap_or_else(|| def.to_string())
    };
    pares.push(Par::new("txtSignText", xml_firmado));
    pares.push(Par::new("nombre", o("nombre", "1")));
    pares.push(Par::new("clave", clave_cert));
    pares.push(Par::new("nodo", o("nodo", "dte:DTE")));
    pares.push(Par::new("nodoId", o("nodoId", "dte:Documento")));
    pares.push(Par::new(
        "nameSpace",
        o("nameSpace", "http://www.sii.cl/SiiDte"),
    ));
    for p in pares.iter_mut() {
        if p.nombre == "txtPlainText" || p.nombre == "txtSignText" {
            p.valor = crlf(&p.valor);
        }
    }
    pares.sort_by(|a, b| a.nombre.cmp(&b.nombre));
    pares
}

// ---------------------------------------------------------------------------
// Dry-runs (no gastan folio: el folio se asigna recién en GenXMLFirma)
// ---------------------------------------------------------------------------

fn codigo_sii(doc: &str) -> String {
    re(&RE_CODIGO_SII, r"CODIGO:\s*([\d.]+)")
        .captures(doc)
        .map(|m| m[1].to_string())
        .unwrap_or_default()
}

/// `OpcionesEmitir`: `confirmar` es obligatorio (no hay sandbox, L1); `aceptar_riesgo_folio`
/// es obligatorio mientras el tipo no esté en `cadenas_verificadas`.
#[derive(Debug, Clone, Copy, Default)]
pub struct OpcionesEmitir {
    pub confirmar: bool,
    pub con_pdf: bool,
    pub aceptar_riesgo_folio: bool,
}

/// `ResultadoMipyme`.
#[derive(Debug, Clone, Default, serde::Serialize)]
pub struct ResultadoEmision {
    pub tipo: i32,
    pub folio: i32,
    /// id del documento en el portal (PDF y NC)
    pub dhdr: String,
    /// con la `<Signature>` puesta por el SII
    pub xml_firmado: String,
    pub monto_total: i64,
    #[serde(skip)]
    pub pdf: Vec<u8>,
}

impl Cliente {
    #[allow(clippy::too_many_arguments)]
    fn evidencia(
        &self,
        tipo: i32,
        folio: i32,
        paso: &str,
        respuesta: &str,
        xml_firmado: &str,
        pares: &[Par],
        extras: &BTreeMap<String, String>,
    ) -> String {
        let secretos = [self.clave_cert.as_str(), self.clave_trib_ref()];
        guardar_evidencia(
            &self.raiz_storage,
            &self.empresa,
            &secretos,
            tipo,
            folio,
            paso,
            respuesta,
            xml_firmado,
            pares,
            extras,
        )
    }

    /// `preparar()`: dry-run de una factura. Lee el form, hace el POST "Validar y visualizar"
    /// (mipeDisplayPreView, 54 campos, como el navegador) y arma el payload desde la página
    /// PreViewDTE que devuelve. Para una nota sin DHDR (56/61) arma el payload desde el form
    /// pre-llenado. NO gasta folio.
    pub fn preparar(
        &mut self,
        tipo: i32,
        receptor: &Receptor,
        items: &[Item],
        fecha: &str,
        forma_pago: &str,
    ) -> Resultado<Payload> {
        if tipo == TIPO_NOTA_CREDITO || tipo == TIPO_NOTA_DEBITO {
            let form = self.leer_form(tipo)?;
            return armar_payload(&form, tipo, receptor, items, fecha, forma_pago, &[], &[]);
        }
        if items.len() != 1 {
            return Err(Error::Validacion("el paso 'Validar y visualizar' de factura está calcado para 1 línea (el navegador manda EFXP_*_01); con más líneas hay que capturar ese flujo".into()));
        }
        receptor.validar()?;
        let form = self.leer_form(tipo)?;
        let base = &form.campos;
        let fecha = if fecha.is_empty() {
            hoy()
        } else {
            fecha.to_string()
        };
        let it = &items[0];
        let total = it.subtotal().to_string();
        let (rut_n, dv) = separar_rut(&receptor.rut);
        let mut dir_origen = base.get("EFXP_DIR_ORIGEN").cloned().unwrap_or_default();
        if dir_origen.is_empty() {
            dir_origen = base
                .get("EFXP_DIR_ORIGEN_DEFUALT")
                .cloned()
                .unwrap_or_default();
        }
        let b = |k: &str| base.get(k).cloned().unwrap_or_default();
        let nuestros: HashMap<&str, String> = HashMap::from([
            ("CANT_DET", "1".into()),
            ("DESCRIP_01", "DESCRIP_01".into()),
            ("EHDR_CODIGO", String::new()),
            ("ES_BORR", "FALSE".into()),
            ("PTDC_CODIGO", tipo.to_string()),
            ("esCRED_EC", "FALSE".into()),
            ("esFACT_TUR", "FALSE".into()),
            ("EFXP_ACTECO_SELECT", b("EFXP_ACTECO")),
            ("EFXP_TIPOCOMPRA_SELECT", "1".into()),
            ("EFXP_TIPOVENTA_SELECT", "1".into()),
            ("EFXP_FCH_EMIS", fecha.clone()),
            ("EFXP_FMA_PAGO", forma_pago.into()),
            ("EFXP_RUT_RECEP", rut_n),
            ("EFXP_DV_RECEP", dv),
            ("EFXP_RZN_SOC_RECEP", receptor.razon_social.clone()),
            ("EFXP_GIRO_RECEP", receptor.giro.clone()),
            ("EFXP_GIRO_RECEP_DEFUALT", receptor.giro.clone()),
            // El JS del portal copia la dirección del campo auxiliar (_DEFUALT) al real y le deja
            // cuatro espacios al final; vacío → "Debe ingresar el campo: Direccion del contribuyente emisor".
            (
                "EFXP_DIR_ORIGEN",
                format!(
                    "{}    ",
                    dir_origen.trim_end_matches([' ', '\t', '\r', '\n'])
                ),
            ),
            (
                "EFXP_DIR_RECEP",
                format!(
                    "{}    ",
                    receptor.direccion.trim_end_matches([' ', '\t', '\r', '\n'])
                ),
            ),
            ("EFXP_DIR_RECEP_DEFUALT", receptor.direccion.clone()),
            ("EFXP_CIUDAD_RECEP", receptor.ciudad.clone()),
            ("EFXP_CMNA_RECEP", receptor.comuna.clone()),
            ("EFXP_CONTACTO", String::new()),
            ("EFXP_NMB_01", it.nombre.clone()),
            ("EFXP_QTY_01", it.cantidad.to_string()),
            ("EFXP_PRC_01", it.precio.to_string()),
            ("EFXP_SUBT_01", it.subtotal().to_string()),
            ("EFXP_DSC_ITEM_01", it.descripcion.clone()),
            ("EFXP_UNMD_01", String::new()),
            ("EFXP_PCTD_01", String::new()),
            ("EFXP_PCT_DESC", "0".into()),
            ("EFXP_MNT_DESC", "0".into()),
            ("IVA_TEMP", String::new()),
            ("MNT_NETO_TEMP", total.clone()),
            ("EFXP_SUBTOTAL", total.clone()),
            ("EFXP_MNT_NETO", total.clone()),
            ("EFXP_MNT_TOTAL", total.clone()),
        ]);
        let pares: Vec<Par> = CAMPOS_VALIDAR_FACTURA
            .iter()
            .map(|k| Par::new(*k, nuestros.get(k).cloned().unwrap_or_else(|| b(k))))
            .collect();
        let cuerpo = codificar_latin1(&pares).map_err(Error::Validacion)?;
        self.traza("body_validar.txt", &String::from_utf8_lossy(&cuerpo));
        let url_form = format!("{BASE}/mipeGenFacEx.cgi?IGUAL=ULT_FAC&PTDC_CODIGO={tipo}&ES_BORR=FALSE&esCRED_EC=FALSE&esFACT_TUR=FALSE");
        let r = self.req(
            "POST",
            &format!("{BASE}/mipeDisplayPreView.cgi"),
            Opciones {
                navegacion: true,
                content: Some(&cuerpo),
                referer: &url_form,
                origin: "https://www1.sii.cl",
                ..Default::default()
            },
        )?;
        let vista = r.texto();
        self.traza("preview.html", &vista);
        if r.rechazado() || !vista.contains("PreViewDTE") {
            self.evidencia(tipo, 0, "validar", &vista, "", &pares, &BTreeMap::new());
            return Err(Error::Rechazo(format!("el portal no aceptó 'Validar y visualizar' de la factura (http {}, {} bytes, código SII {:?})", r.status, vista.len(), codigo_sii(&vista))));
        }
        let mut p = armar_payload(
            &parsear_form_ordenado(&vista),
            tipo,
            receptor,
            items,
            &fecha,
            forma_pago,
            &[],
            &["ES_BORR", "INDICA_PRIMERA_EJECUCION"],
        )?;
        p.referer_emision = format!("{BASE}/mipeDisplayPreView.cgi");
        Ok(p)
    }

    /// El TOTAL del documento tal como el SII lo registró, leído del XML del envío (firma
    /// central). NO usar el monto del listado: en un documento inconsistente muestra la línea
    /// (factura 57: listado 3.270.323, total 3.068.005).
    pub fn total_registrado(
        &mut self,
        dhdr: &str,
        tipo: i32,
        rut_receptor: &str,
    ) -> Resultado<i64> {
        let xml = self.obtener_envio_xml(dhdr, tipo, rut_receptor)?;
        let texto = super::latin1(&xml);
        let m = re(&RE_MNT_TOTAL, r"<MntTotal>(\d+)</MntTotal>")
            .captures(&texto)
            .ok_or_else(|| Error::Sii(format!("el XML del documento {dhdr} no trae <MntTotal>")))?;
        m[1].parse()
            .map_err(|e| Error::Sii(format!("MntTotal: {e}")))
    }

    /// `preparar_nc_anulacion`: NC (61) que anula el documento dhdr. El portal pre-construye la
    /// NC en mipeDisplayPreView?EHDR_CODIGO&TIPO_NOTA=61; después es la misma cadena con
    /// PTDC_CODIGO=61 y la referencia código 1. Guardarraíl: la suma de items debe ser
    /// EXACTAMENTE el total registrado (si no, el SII la acepta con reparo REF-2-780 y el abono
    /// queda mal; costó la NC 56). NO gasta folio.
    #[allow(clippy::too_many_arguments)]
    pub fn preparar_nc_anulacion(
        &mut self,
        dhdr: &str,
        tipo_ref: i32,
        folio_ref: i64,
        fecha_ref: &str,
        receptor: &Receptor,
        items: &[Item],
        fecha: &str,
        verificar_monto: bool,
    ) -> Resultado<Payload> {
        self.preparar_nota_anulacion(
            TIPO_NOTA_CREDITO, dhdr, tipo_ref, folio_ref, fecha_ref, receptor, items, fecha, verificar_monto,
        )
    }

    /// `preparar_nd_anulacion`: nota de DÉBITO (56) que deja sin efecto la nota de crédito dhdr
    /// (código 1): el mismo formulario pre-construido por el portal, con TIPO_NOTA=56 (capturado
    /// 2026-10-02 al emitir a mano la ND 1 que anuló la NC 56). El documento que esa NC anulaba
    /// vuelve a valer. Mismo guardarraíl del total registrado. NO gasta folio; la cadena 56 no
    /// está en `cadenas_verificadas`, así que `emitir` exige `aceptar_riesgo_folio`.
    #[allow(clippy::too_many_arguments)]
    pub fn preparar_nd_anulacion(
        &mut self,
        dhdr: &str,
        folio_ref: i64,
        fecha_ref: &str,
        receptor: &Receptor,
        items: &[Item],
        fecha: &str,
        verificar_monto: bool,
    ) -> Resultado<Payload> {
        self.preparar_nota_anulacion(
            TIPO_NOTA_DEBITO, dhdr, TIPO_NOTA_CREDITO, folio_ref, fecha_ref, receptor, items, fecha, verificar_monto,
        )
    }

    /// Lo común a la NC (61) y la ND (56) de anulación:
    /// mipeDisplayPreView?EHDR_CODIGO&TIPO_NOTA=<tipo_nota>.
    #[allow(clippy::too_many_arguments)]
    fn preparar_nota_anulacion(
        &mut self,
        tipo_nota: i32,
        dhdr: &str,
        tipo_ref: i32,
        folio_ref: i64,
        fecha_ref: &str,
        receptor: &Receptor,
        items: &[Item],
        fecha: &str,
        verificar_monto: bool,
    ) -> Resultado<Payload> {
        self.requiere_empresa()?;
        receptor.validar()?;
        let sigla = sigla_nota(tipo_nota);
        if verificar_monto {
            let total_ref = self.total_registrado(dhdr, tipo_ref, &receptor.rut)?;
            let total_nc = suma_items(items);
            if total_nc != total_ref {
                return Err(Error::Validacion(format!(
                    "la {sigla} sumaría {total_nc} pero el documento {tipo_ref}/{folio_ref} está registrado por {total_ref}: el SII la aceptaría con reparo REF-2-780 y el abono quedaría mal; usa el total registrado"
                )));
            }
        }
        let vista = self.vista_nota(tipo_nota, dhdr)?;
        let refe = Referencia {
            tipo: tipo_ref,
            folio: folio_ref,
            fecha: fecha_ref.into(),
            codigo: CODIGO_REF_ANULA.into(),
            razon: RAZON_REF_ANULA.into(),
        };
        let mut p = armar_payload(
            &parsear_form_ordenado(&vista),
            tipo_nota,
            receptor,
            items,
            fecha,
            "",
            &[refe],
            &["ES_BORR", "EFXP_FMA_PAGO", "INDICA_PRIMERA_EJECUCION"],
        )?;
        // El navegador firma desde la página de revisión: usarla como Referer en GenXMLFirma.
        p.referer_emision =
            format!("{BASE}/mipeDisplayPreView.cgi?EHDR_CODIGO={dhdr}&TIPO_NOTA={tipo_nota}");
        Ok(p)
    }

    /// La página de la nota pre-construida por el portal (`mipeDisplayPreView?EHDR_CODIGO&TIPO_NOTA`).
    fn vista_nota(&mut self, tipo_nota: i32, dhdr: &str) -> Resultado<String> {
        let sigla = sigla_nota(tipo_nota);
        let params = [
            Par::new("EHDR_CODIGO", dhdr),
            Par::new("TIPO_NOTA", tipo_nota.to_string()),
        ];
        let r = self.req(
            "GET",
            &format!("{BASE}/mipeDisplayPreView.cgi"),
            Opciones {
                navegacion: true,
                params: Some(&params),
                referer: &format!("{BASE}/mipeGesDocEmi.cgi?CODIGO={dhdr}"),
                ..Default::default()
            },
        )?;
        let vista = r.texto();
        self.traza(&format!("{}_anulacion.html", sigla.to_lowercase()), &vista);
        if r.rechazado() || r.cuerpo.len() < 1000 {
            return Err(Error::Rechazo(format!(
                "el portal no pre-construyó la {sigla} de anulación (http {}, dhdr {dhdr})",
                r.status
            )));
        }
        Ok(vista)
    }

    /// `preparar_nc_correccion_montos`: NC (61) código 3 sobre el documento dhdr, calcada del
    /// flujo real de la NC 59 (2026-10-04): GET del form IGUAL=CORR_MNT → POST "Validar y
    /// visualizar" con los 60 campos exactos → página PreViewDTE. Una NC por el total registrado
    /// deja el documento en cero. NO gasta folio.
    #[allow(clippy::too_many_arguments)]
    pub fn preparar_nc_correccion_montos(
        &mut self,
        dhdr: &str,
        tipo_ref: i32,
        folio_ref: i64,
        fecha_ref: &str,
        receptor: &Receptor,
        items: &[Item],
        fecha: &str,
        verificar_monto: bool,
    ) -> Resultado<Payload> {
        self.requiere_empresa()?;
        receptor.validar()?;
        if items.len() > 3 {
            return Err(Error::Validacion(
                "el formulario de corrección admite hasta 3 líneas".into(),
            ));
        }
        let url_form = format!(
            "{BASE}/mipeGenFacEx.cgi?IGUAL=CORR_MNT&VALOR={dhdr}&PTDC_CODIGO={TIPO_NOTA_CREDITO}"
        );
        let params = [
            Par::new("IGUAL", "CORR_MNT"),
            Par::new("VALOR", dhdr),
            Par::new("PTDC_CODIGO", TIPO_NOTA_CREDITO.to_string()),
        ];
        let r = self.req(
            "GET",
            &format!("{BASE}/mipeGenFacEx.cgi"),
            Opciones {
                navegacion: true,
                referer: &format!("{BASE}/mipeGesDocEmi.cgi?ALL_PAGE_ANT=2&CODIGO={dhdr}"),
                params: Some(&params),
                ..Default::default()
            },
        )?;
        let doc = r.texto();
        self.traza("corr_form.html", &doc);
        if r.rechazado() || doc.len() < 5000 {
            return Err(Error::Rechazo(format!(
                "el portal no entregó el formulario de corrección de montos (dhdr {dhdr}, http {})",
                r.status
            )));
        }
        let base = parsear_form(&doc);
        let b = |k: &str| base.get(k).cloned().unwrap_or_default();
        let mut total_txt = b("EFXP_MNT_TOTAL");
        if total_txt.is_empty() {
            total_txt = b("MNT_TOTAL_ORI");
        }
        let total_ref: i64 = re_no_digito()
            .replace_all(&total_txt, "")
            .parse()
            .unwrap_or(0);
        let total_nc = suma_items(items);
        if verificar_monto && (total_ref <= 0 || total_nc > total_ref) {
            return Err(Error::Validacion(format!("la NC de corrección sumaría {total_nc} y el documento está registrado por {total_ref}")));
        }
        let fecha = if fecha.is_empty() {
            hoy()
        } else {
            fecha.to_string()
        };
        let (rut_n, dv) = separar_rut(&receptor.rut);
        let (tr, tn) = (total_ref.to_string(), total_nc.to_string());
        let mut nuestros: HashMap<String, String> = HashMap::from(
            [
                ("CANT_DET", "3".to_string()),
                ("DESCRIP_01", "DESCRIP_01".into()),
                ("REF_SI_NO", "SiChecked".into()),
                ("TIPO_PLANTILLA", "CORR_MNT_V_NC".into()),
                ("esCRED_EC", "FALSE".into()),
                ("IVA_TEMP", String::new()),
                ("MNT_NETO_TEMP", tr.clone()),
                ("MNT_TOTAL_ORI", tr.clone()),
                ("EHDR_CODIGO", dhdr.into()),
                ("PTDC_CODIGO", TIPO_NOTA_CREDITO.to_string()),
                ("EFXP_FCH_EMIS", fecha.clone()),
                ("EFXP_RUT_RECEP", rut_n),
                ("EFXP_DV_RECEP", dv),
                ("EFXP_RZN_SOC_RECEP", receptor.razon_social.clone()),
                ("EFXP_GIRO_RECEP", receptor.giro.clone()),
                ("EFXP_DIR_RECEP", receptor.direccion.clone()),
                ("EFXP_CIUDAD_RECEP", receptor.ciudad.clone()),
                ("EFXP_CMNA_RECEP", receptor.comuna.clone()),
                ("EFXP_PCT_DESC", "0".into()),
                ("EFXP_MNT_DESC", "0".into()),
                ("EFXP_SUBTOTAL", tn.clone()),
                ("EFXP_MNT_NETO", tn.clone()),
                ("EFXP_MNT_TOTAL", tn.clone()),
                ("EFXP_TPO_DOC_REF_001", tipo_ref.to_string()),
                ("EFXP_FOLIO_REF_001", folio_ref.to_string()),
                ("EFXP_FCH_REF_001", fecha_ref.into()),
                ("EFXP_CODIGO_REF_001", CODIGO_REF_CORRIGE_MONTO.into()),
                ("EFXP_RAZON_REF_001", RAZON_REF_CORRIGE_MONTO.into()),
                ("EFXP_IND_GLOBAL_001", String::new()),
            ]
            .map(|(k, v)| (k.to_string(), v)),
        );
        for i in 1..=3 {
            for cmp in ["NMB", "QTY", "PRC", "SUBT", "UNMD", "PCTD"] {
                nuestros.insert(format!("EFXP_{cmp}_{i:02}"), String::new());
            }
        }
        nuestros.insert("EFXP_DSC_ITEM_01".into(), String::new());
        for (n, it) in items.iter().enumerate() {
            let k = format!("{:02}", n + 1);
            nuestros.insert(format!("EFXP_NMB_{k}"), it.nombre.clone());
            nuestros.insert(format!("EFXP_QTY_{k}"), it.cantidad.to_string());
            nuestros.insert(format!("EFXP_PRC_{k}"), it.precio.to_string());
            nuestros.insert(format!("EFXP_SUBT_{k}"), it.subtotal().to_string());
            if n == 0 {
                nuestros.insert("EFXP_DSC_ITEM_01".into(), it.descripcion.clone());
            }
        }
        let pares: Vec<Par> = CAMPOS_VALIDAR_CORR_MNT
            .iter()
            .map(|k| Par::new(*k, nuestros.get(*k).cloned().unwrap_or_else(|| b(k))))
            .collect();
        let cuerpo = codificar_latin1(&pares).map_err(Error::Validacion)?;
        self.traza("body_corr_validar.txt", &String::from_utf8_lossy(&cuerpo));
        let r = self.req(
            "POST",
            &format!("{BASE}/mipeDisplayPreView.cgi"),
            Opciones {
                navegacion: true,
                content: Some(&cuerpo),
                referer: &url_form,
                origin: "https://www1.sii.cl",
                ..Default::default()
            },
        )?;
        let vista = r.texto();
        self.traza("corr_preview.html", &vista);
        if r.rechazado() || !vista.contains("PreViewDTE") {
            return Err(Error::Rechazo(format!("el portal no aceptó 'Validar y visualizar' de la NC de corrección (dhdr {dhdr}, http {}, {} bytes, código SII {:?})", r.status, vista.len(), codigo_sii(&vista))));
        }
        let refe = Referencia {
            tipo: tipo_ref,
            folio: folio_ref,
            fecha: fecha_ref.into(),
            codigo: CODIGO_REF_CORRIGE_MONTO.into(),
            razon: RAZON_REF_CORRIGE_MONTO.into(),
        };
        let mut p = armar_payload(
            &parsear_form_ordenado(&vista),
            TIPO_NOTA_CREDITO,
            receptor,
            items,
            &fecha,
            "",
            &[refe],
            &["ES_BORR", "EFXP_FMA_PAGO", "INDICA_PRIMERA_EJECUCION"],
        )?;
        p.referer_emision = format!("{BASE}/mipeDisplayPreView.cgi");
        Ok(p)
    }

    // ---------------------------------------------------------------------------
    // Emisión (PAGA: gasta un folio real en producción)
    // ---------------------------------------------------------------------------

    /// `emitir()`: GenXMLFirma (gasta el folio) → firma central → mipeSendXML → PDF.
    pub fn emitir(&mut self, p: &Payload, op: OpcionesEmitir) -> Resultado<ResultadoEmision> {
        if !op.confirmar {
            return Err(Error::Validacion(
                "emitir gasta un folio real en PRODUCCIÓN: llámalo con confirmar".into(),
            ));
        }
        let verificada = cadenas_verificadas().contains_key(&p.tipo);
        if !verificada && !op.aceptar_riesgo_folio {
            return Err(Error::Validacion(format!("la cadena de emisión del tipo {} NO está verificada contra el SII desde este motor; si falla después de GenXMLFirma se pierde un folio; para correrla igual: aceptar_riesgo_folio", p.tipo)));
        }
        self.requiere_empresa()?;
        if !verificada {
            self.log(format!(
                "SII engine: emitiendo tipo {} con cadena NO verificada (riesgo de folio aceptado)",
                p.tipo
            ));
        }
        if !p.campos_nuevos.is_empty() {
            self.log(format!(
                "emitiendo con drift del form (campos nuevos: {:?})",
                p.campos_nuevos
            ));
        }
        self.log(format!(
            "SII engine → PRODUCCIÓN: emitiendo tipo {} por ${} para la empresa {}",
            p.tipo,
            p.monto_total(),
            self.empresa
        ));

        // 3. GenXMLFirma — desde aquí el folio ya está gastado
        let cuerpo = codificar_latin1(&p.pares).map_err(Error::Validacion)?;
        let referer = if p.referer_emision.is_empty() {
            format!(
                "{BASE}/mipeGenFacEx.cgi?IGUAL=ULT_FAC&PTDC_CODIGO={}",
                p.tipo
            )
        } else {
            p.referer_emision.clone()
        };
        let r = self.req(
            "POST",
            &format!("{BASE}/mipeGenXMLFirma.cgi"),
            Opciones {
                navegacion: false,
                content: Some(&cuerpo),
                referer: &referer,
                ..Default::default()
            },
        )?;
        let doc = r.texto();
        if r.rechazado() {
            return Err(Error::Rechazo(format!(
                "mipeGenXMLFirma rechazado (¿payload incompleto?; http {})",
                r.status
            )));
        }
        let form_firma = extraer_form_firma(&doc);
        let mut extras: BTreeMap<String, String> = BTreeMap::new();
        extras.insert("respuesta_genxmlfirma.html".into(), doc.clone());
        let mut xml = form_firma
            .as_ref()
            .and_then(|f| f.campos.get("txtPlainText").cloned())
            .unwrap_or_default();
        if xml.is_empty() {
            xml = extraer_xml_dte(&doc);
        }
        if xml.is_empty() || !xml.contains("<DTE") {
            self.evidencia(p.tipo, 0, "genxml", &doc, "", &p.pares, &BTreeMap::new());
            return Err(Error::Sii(format!(
                "mipeGenXMLFirma no devolvió el XML del DTE (código SII {:?})",
                codigo_sii(&doc)
            )));
        }
        let folio: i32 = re(&RE_FOLIO, r"<Folio>(\d+)</Folio>")
            .captures(&xml)
            .ok_or_else(|| Error::Sii("el XML del portal no trae <Folio>".into()))?[1]
            .parse()
            .unwrap_or(0);
        self.log(format!(
            "SII engine: folio {folio} asignado (tipo {}); frmSign {}",
            p.tipo,
            if form_firma.is_some() {
                "encontrado"
            } else {
                "NO encontrado"
            }
        ));

        // 4. Firma central — clave del CERTIFICADO. La cookie la pone el JS del portal.
        self.poner_cookie("usa_firma_central", "true");
        let dato = if p.tipo == TIPO_NOTA_CREDITO || p.tipo == TIPO_NOTA_DEBITO {
            preparar_dato_firma(&xml)
        } else {
            xml.clone()
        };
        let (rf, cruda) = self.firma_central(
            &dato,
            "dte:DTE",
            "dte:Documento",
            &format!("{BASE}/mipeGenXMLFirma.cgi"),
        )?;
        extras.insert("respuesta_postfirma_cruda.txt".into(), cruda.clone());
        let (estado_firma, firmado) = parsear_respuesta_firma(&cruda);
        if estado_firma == 2 || re(&RE_CLAVE_NO, r"(?i)clave no corresponde").is_match(&cruda) {
            self.evidencia(p.tipo, folio, "firma", &cruda, "", &p.pares, &extras);
            return Err(Error::Autenticacion(format!("la firma central rechazó la clave del certificado (folio {folio} gastado sin documento); es la clave del .p12, no la tributaria")));
        }
        if rf.status != 200 || estado_firma != 0 || !firmado.contains("<Signature") {
            let carpeta = self.evidencia(p.tipo, folio, "firma", &firmado, "", &p.pares, &extras);
            return Err(Error::Rechazo(format!("la firma central falló para el folio {folio} (¿clave del certificado incorrecta?); el folio quedó gastado sin documento; evidencia en {carpeta}")));
        }
        let tmst = re_tmst_firma()
            .captures(&firmado)
            .map(|m| m[1].to_string())
            .unwrap_or_default();

        // 5. Envío, SOLO con el frmSign real de la página de firma (lo único que manda el navegador).
        let Some(form_firma) = form_firma.filter(|f| {
            !f.campos
                .get("txtPlainText")
                .unwrap_or(&String::new())
                .is_empty()
        }) else {
            let carpeta = self.evidencia(
                p.tipo,
                folio,
                "sin_frmsign",
                &doc,
                &firmado,
                &p.pares,
                &extras,
            );
            return Err(Error::Sii(format!("mipeGenXMLFirma no devolvió el formulario de firma (frmSign); folio {folio} firmado y NO enviado; evidencia en {carpeta}")));
        };
        let pares = armar_send_xml_desde_form(&form_firma, &firmado, &self.clave_cert, &tmst);
        let mut action = unescape(&form_firma.action);
        if action.is_empty() {
            action = "mipeSendXML.cgi".into();
        }
        let url_envio = resolver_relativa(&format!("{BASE}/mipeGenXMLFirma.cgi"), &action);
        self.log(format!(
            "SII engine: envío con frmSign ({} campos) → {url_envio}",
            pares.len()
        ));
        let cuerpo_envio = codificar_latin1(&pares).map_err(Error::Validacion)?;
        let re_ = self.req(
            "POST",
            &url_envio,
            Opciones {
                navegacion: true,
                content: Some(&cuerpo_envio),
                referer: &format!("{BASE}/mipeGenXMLFirma.cgi"),
                origin: "https://www1.sii.cl",
                ..Default::default()
            },
        )?;
        let out = re_.texto();
        let rdhdr = re(&RE_DHDR, r"DHDR_CODIGO=(\d+)");
        let m = rdhdr
            .captures(&out)
            .or_else(|| rdhdr.captures(&re_.location))
            .map(|m| m[1].to_string());
        let mut exito = m.is_some()
            || re(
                &RE_EXITO,
                r"(?i)Firmado y Enviado|ENVIADO EXITOSAMENTE|Documento\s+enviado",
            )
            .is_match(&out);
        if re(&RE_FIRMA_NO, r"(?i)Firma\s+no\s+reconocida").is_match(&out) {
            exito = false;
        }
        let rechazado =
            out.contains("Request Rejected") || (re_.status != 200 && re_.status != 302);
        if rechazado || !exito {
            let carpeta = self.evidencia(p.tipo, folio, "envio", &out, &firmado, &pares, &extras);
            let motivo = if out.contains("Request Rejected") {
                "WAF: Request Rejected"
            } else {
                "respuesta inesperada"
            };
            return Err(Error::Rechazo(format!("mipeSendXML no confirmó el envío del folio {folio} ({motivo}); el folio ya está gastado y firmado: revisar en el portal si el documento quedó emitido antes de reintentar; evidencia en {carpeta}")));
        }
        let dhdr = m.unwrap_or_default();
        self.evidencia(p.tipo, folio, "ok", &out, &firmado, &pares, &extras);
        let mut res = ResultadoEmision {
            tipo: p.tipo,
            folio,
            dhdr: dhdr.clone(),
            xml_firmado: firmado,
            monto_total: p.monto_total(),
            pdf: Vec::new(),
        };
        self.log(format!(
            "SII engine: tipo {} folio {folio} emitido, DHDR={dhdr}",
            p.tipo
        ));
        if op.con_pdf && !dhdr.is_empty() {
            match self.descargar_pdf(&dhdr) {
                Ok(pdf) => res.pdf = pdf,
                Err(e) => self.log(format!("PDF del DHDR {dhdr} no disponible: {e}")),
            }
        }
        Ok(res)
    }

    /// `preparar_nc_anulacion` tomando receptor e ítems del propio formulario que el portal
    /// pre-construye para anular el documento dhdr (lo que usa la app: la persona elige el
    /// documento y nada más). Mismo guardarraíl del total registrado.
    pub fn preparar_nc_anulacion_desde_portal(
        &mut self,
        dhdr: &str,
        tipo_ref: i32,
        folio_ref: i64,
        fecha_ref: &str,
        fecha: &str,
        verificar_monto: bool,
    ) -> Resultado<(Payload, Receptor, Vec<Item>)> {
        self.preparar_nota_anulacion_desde_portal(
            TIPO_NOTA_CREDITO, dhdr, tipo_ref, folio_ref, fecha_ref, fecha, verificar_monto,
        )
    }

    /// `preparar_nd_anulacion` tomando receptor e ítems del formulario que el portal
    /// pre-construye para dejar sin efecto la NC dhdr (lo que usa la app).
    pub fn preparar_nd_anulacion_desde_portal(
        &mut self,
        dhdr: &str,
        folio_ref: i64,
        fecha_ref: &str,
        fecha: &str,
        verificar_monto: bool,
    ) -> Resultado<(Payload, Receptor, Vec<Item>)> {
        self.preparar_nota_anulacion_desde_portal(
            TIPO_NOTA_DEBITO, dhdr, TIPO_NOTA_CREDITO, folio_ref, fecha_ref, fecha, verificar_monto,
        )
    }

    #[allow(clippy::too_many_arguments)]
    fn preparar_nota_anulacion_desde_portal(
        &mut self,
        tipo_nota: i32,
        dhdr: &str,
        tipo_ref: i32,
        folio_ref: i64,
        fecha_ref: &str,
        fecha: &str,
        verificar_monto: bool,
    ) -> Resultado<(Payload, Receptor, Vec<Item>)> {
        self.requiere_empresa()?;
        let sigla = sigla_nota(tipo_nota);
        let vista = self.vista_nota(tipo_nota, dhdr)?;
        let form = parsear_form_ordenado(&vista);
        let (receptor, items) = receptor_e_items_desde_form(&form);
        if let Err(e) = receptor.validar() {
            return Err(Error::Validacion(format!(
                "{e} (receptor según el portal: {:?})",
                receptor.rut
            )));
        }
        if items.is_empty() {
            return Err(Error::Sii(format!(
                "el formulario de la {sigla} no trae líneas del documento"
            )));
        }
        if verificar_monto {
            let total_ref = self.total_registrado(dhdr, tipo_ref, &receptor.rut)?;
            let total_nc = suma_items(&items);
            if total_nc != total_ref {
                return Err(Error::Validacion(format!("las líneas del formulario suman {total_nc} pero el documento {tipo_ref}/{folio_ref} está registrado por {total_ref} (documento inconsistente: anular a mano por el total registrado)")));
            }
        }
        let refe = Referencia {
            tipo: tipo_ref,
            folio: folio_ref,
            fecha: fecha_ref.into(),
            codigo: CODIGO_REF_ANULA.into(),
            razon: RAZON_REF_ANULA.into(),
        };
        let mut p = armar_payload(
            &form,
            tipo_nota,
            &receptor,
            &items,
            fecha,
            "",
            &[refe],
            &["ES_BORR", "EFXP_FMA_PAGO", "INDICA_PRIMERA_EJECUCION"],
        )?;
        p.referer_emision =
            format!("{BASE}/mipeDisplayPreView.cgi?EHDR_CODIGO={dhdr}&TIPO_NOTA={tipo_nota}");
        Ok((p, receptor, items))
    }
}

/// "NC" o "ND", para mensajes y trazas.
fn sigla_nota(tipo_nota: i32) -> &'static str {
    if tipo_nota == TIPO_NOTA_DEBITO {
        "ND"
    } else {
        "NC"
    }
}

/// Resuelve `action` contra la URL base como `url.ResolveReference` (solo lo que el portal usa:
/// absolutas, relativas al directorio y relativas a la raíz).
fn resolver_relativa(base: &str, action: &str) -> String {
    if action.starts_with("http://") || action.starts_with("https://") {
        return action.to_string();
    }
    let (esquema_host, ruta) = match base
        .find("://")
        .and_then(|i| base[i + 3..].find('/').map(|j| i + 3 + j))
    {
        Some(k) => (&base[..k], &base[k..]),
        None => (base, "/"),
    };
    if let Some(abs) = action.strip_prefix('/') {
        return format!("{esquema_host}/{abs}");
    }
    let dir = &ruta[..ruta.rfind('/').map(|i| i + 1).unwrap_or(ruta.len())];
    format!("{esquema_host}{dir}{action}")
}

/// `registrar_en_bd`: guarda el documento en `dtes` con ambiente producción y estado
/// emitido_mipyme; el DHDR va en track_id. Idempotente por (rut, tipo, folio).
pub fn registrar_en_bd(
    al: &Almacen,
    res: &ResultadoEmision,
    rut_emisor: &str,
    receptor: &Receptor,
    fecha_emision: &str,
) -> almacen::Resultado<i64> {
    let rut = formatear_rut(rut_emisor, false);
    let track: i64 = res.dhdr.parse().unwrap_or(0);
    if let Some(fila) = al.dte_por_folio(&rut, res.tipo, res.folio)? {
        al.actualizar_estado(fila.id, "emitido_mipyme", track)?;
        return Ok(fila.id);
    }
    let id = al.crear_dte(&almacen::Dte {
        tipo_dte: res.tipo,
        folio: res.folio,
        rut_emisor: rut,
        rut_receptor: formatear_rut(&receptor.rut, false),
        razon_social_receptor: receptor.razon_social.clone(),
        fecha_emision: fecha_emision.into(),
        monto_exento: res.monto_total,
        monto_total: res.monto_total,
        xml_firmado: res.xml_firmado.clone(),
        ambiente: "produccion".into(),
        ..Default::default()
    })?;
    al.actualizar_estado(id, "emitido_mipyme", track)?;
    Ok(id)
}

/// Lee del formulario pre-construido por el portal (la NC de anulación de un documento) el
/// receptor y las líneas del documento original, sin espacios de relleno. Sirve para anular
/// "tal cual" sin que la persona vuelva a teclear nada.
pub fn receptor_e_items_desde_form(form: &Form) -> (Receptor, Vec<Item>) {
    let c = |k: &str| {
        form.campos
            .get(k)
            .map(|v| v.trim().to_string())
            .unwrap_or_default()
    };
    let rec = Receptor {
        rut: format!("{}-{}", c("EFXP_RUT_RECEP"), c("EFXP_DV_RECEP")),
        razon_social: c("EFXP_RZN_SOC_RECEP"),
        giro: c("EFXP_GIRO_RECEP"),
        direccion: c("EFXP_DIR_RECEP"),
        ciudad: c("EFXP_CIUDAD_RECEP"),
        comuna: c("EFXP_CMNA_RECEP"),
    };
    let mut items = Vec::new();
    for i in 1..=10 {
        let k = format!("{i:02}");
        let nombre = c(&format!("EFXP_NMB_{k}"));
        if nombre.is_empty() {
            continue;
        }
        let mut qty: i64 = re_no_digito()
            .replace_all(&c(&format!("EFXP_QTY_{k}")), "")
            .parse()
            .unwrap_or(0);
        if qty <= 0 {
            qty = 1;
        }
        let prc: i64 = re_no_digito()
            .replace_all(&c(&format!("EFXP_PRC_{k}")), "")
            .parse()
            .unwrap_or(0);
        items.push(Item {
            nombre,
            precio: prc,
            cantidad: qty,
            descripcion: c(&format!("EFXP_DSC_ITEM_{k}")),
        });
    }
    (rec, items)
}

impl Cliente {
    fn clave_trib_ref(&self) -> &str {
        &self.clave_trib
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const HTML_PREVIEW: &str = r#"<form name="PreViewDTE"><input name="INDICA_PRIMERA_EJECUCION" value="1"><input name="ES_BORR" value=""><input name="EFXP_RZN_SOC" value="EMPRESA DEMO SPA"><input name="EFXP_GIRO_EMIS" value="VENTAS"><input name="EFXP_ACTECO" value="123456"><input name="EFXP_NMB_01" value="viejo"><input name="EFXP_TPO_COD_02" value="x"><input name="CAMPO_RARO" value="z"><input name="CANT_DET" value="1"><input name="EFXP_DIR_ORIGEN_DEFUALT" value="D"><input name="EFXP_TASA_IVA" value="19"><input name="EFXP_TPO_DOC_REF_001" value="33"><input type="button" name="btnSign" value="Firmar"></form>"#;

    fn receptor_prueba() -> Receptor {
        Receptor {
            rut: "76.111.111-6".into(),
            razon_social: "CLIENTE DEMO SPA".into(),
            giro: "SALUD".into(),
            direccion: "CAMINO 1".into(),
            ciudad: "Chillan".into(),
            comuna: "CHILLAN".into(),
        }
    }
    fn item_prueba() -> Item {
        Item {
            nombre: "Arriendo".into(),
            precio: 1000,
            cantidad: 1,
            descripcion: "Doc de prueba ñ".into(),
        }
    }
    fn esperado(nombre: &str) -> String {
        std::fs::read_to_string(format!(
            "{}/testdata/siiengine/{nombre}",
            env!("CARGO_MANIFEST_DIR")
        ))
        .unwrap()
    }
    fn cuerpo(pares: &[Par]) -> String {
        String::from_utf8_lossy(&codificar_latin1(pares).unwrap()).into_owned()
    }
    fn primera_diferencia(a: &str, b: &str) -> String {
        let i = a.bytes().zip(b.bytes()).take_while(|(x, y)| x == y).count();
        if i < a.len() && i < b.len() {
            let lo = i.saturating_sub(60);
            format!(
                "pos {i}\n got …{}\nwant …{}",
                &a[lo..(i + 60).min(a.len())],
                &b[lo..(i + 60).min(b.len())]
            )
        } else {
            format!("largos distintos: {} vs {}", a.len(), b.len())
        }
    }

    #[test]
    fn payload_factura() {
        let p = armar_payload(
            &parsear_form_ordenado(HTML_PREVIEW),
            34,
            &receptor_prueba(),
            &[item_prueba()],
            "2026-10-08",
            "1",
            &[],
            &["ES_BORR", "INDICA_PRIMERA_EJECUCION"],
        )
        .unwrap();
        assert_eq!(p.campos_nuevos, vec!["CAMPO_RARO".to_string()]);
        assert_eq!((p.monto_total(), p.pares.len()), (1000, 243));
        let (got, want) = (cuerpo(&p.pares), esperado("esp_factura.txt"));
        assert!(got == want, "factura: {}", primera_diferencia(&got, &want));
    }

    #[test]
    fn payload_nota() {
        let r = Referencia {
            tipo: 34,
            folio: 63,
            fecha: "2026-10-08".into(),
            codigo: "1".into(),
            razon: "ANULA DOCUMENTO DE LA REFERENCIA".into(),
        };
        let p = armar_payload(
            &parsear_form_ordenado(HTML_PREVIEW),
            61,
            &receptor_prueba(),
            &[item_prueba()],
            "2026-10-08",
            "",
            &[r],
            &["ES_BORR", "EFXP_FMA_PAGO", "INDICA_PRIMERA_EJECUCION"],
        )
        .unwrap();
        assert_eq!(
            (p.pares.len(), p.pares[0].nombre.as_str()),
            (246, "INDICA_PRIMERA_EJECUCION")
        );
        let (got, want) = (cuerpo(&p.pares), esperado("esp_nota.txt"));
        assert!(got == want, "nota: {}", primera_diferencia(&got, &want));
    }

    #[test]
    fn form_firma_y_send() {
        let doc = "<html><form name=\"PreViewDTE\" action=\"x\"><input name=\"a\" value=\"1\"></form><form name=\"frmSign\" action=\"mipeSendXML.cgi?csrt=123\"><input type=\"hidden\" name=\"PTDC_CODIGO\" value=\"34\"><input type=\"hidden\" name=\"EFXP_FMA_PAGO\" value=\"1\"><input type=\"hidden\" name=\"TMST_SIGN\" value=\"\"><textarea name=\"txtPlainText\"><?xml version=\"1.0\"?>\n<DTE>a &amp; b</DTE></textarea><input type=\"hidden\" name=\"EFXP_FMA_PAGO\" value=\"1\"><input type=\"hidden\" name=\"EFXP_FOLIO\" value=\"58\"><input type=\"button\" name=\"btnSign\" value=\"Firmar\"></form></html>";
        let f = extraer_form_firma(doc).expect("frmSign");
        assert_eq!(f.action, "mipeSendXML.cgi?csrt=123");
        assert_eq!(f.crudos.len(), 7);
        assert_eq!(
            f.crudos[3].valor,
            "<?xml version=\"1.0\"?>\n<DTE>a & b</DTE>"
        );
        let pares = armar_send_xml_desde_form(
            &f,
            "<?xml version=\"1.0\"?>\n<DTE><Signature/></DTE>",
            "***",
            "2026-10-08T16:59:00",
        );
        let (got, want) = (cuerpo(&pares), esperado("esp_send.txt"));
        assert!(got == want, "send: {}", primera_diferencia(&got, &want));
        assert!(extraer_form_firma("<html>sin form</html>").is_none());
        assert_eq!(
            extraer_xml_dte("<html><script>var xmlDte = '<DTE>x</DTE>';</script></html>"),
            "<DTE>x</DTE>"
        );
        assert_eq!(
            resolver_relativa(
                "https://www1.sii.cl/cgi-bin/Portal001/mipeGenXMLFirma.cgi",
                "mipeSendXML.cgi?csrt=1"
            ),
            "https://www1.sii.cl/cgi-bin/Portal001/mipeSendXML.cgi?csrt=1"
        );
        assert_eq!(
            resolver_relativa("https://www1.sii.cl/cgi-bin/Portal001/x.cgi", "/otro/y.cgi"),
            "https://www1.sii.cl/otro/y.cgi"
        );
    }

    /// Con las evidencias reales de emisiones aceptadas (Python), el cuerpo de mipeSendXML que
    /// arma Rust debe ser idéntico al que viajó (body_ok.txt, clave tachada ***). Privadas,
    /// gitignored: se salta si no están.
    #[test]
    fn paridad_evidencia() {
        let raiz = format!("{}/../storage/mipyme_fallidos", env!("CARGO_MANIFEST_DIR"));
        let Ok(ruts) = std::fs::read_dir(&raiz) else {
            return;
        };
        let mut n = 0;
        for rut in ruts.flatten() {
            let Ok(dirs) = std::fs::read_dir(rut.path()) else {
                continue;
            };
            for dir in dirs.flatten() {
                let dir = dir.path();
                let (Ok(pagina), Ok(cruda), Ok(want)) = (
                    std::fs::read(dir.join("respuesta_genxmlfirma.html")),
                    std::fs::read(dir.join("respuesta_postfirma_cruda.txt")),
                    std::fs::read(dir.join("body_ok.txt")),
                ) else {
                    continue;
                };
                let f = extraer_form_firma(&super::super::latin1(&pagina))
                    .unwrap_or_else(|| panic!("{}: sin frmSign", dir.display()));
                let (estado, firmado) = parsear_respuesta_firma(&super::super::latin1(&cruda));
                assert_eq!(estado, 0, "{}: firma estado", dir.display());
                let tmst = re_tmst_firma()
                    .captures(&firmado)
                    .map(|m| m[1].to_string())
                    .unwrap_or_default();
                let got = cuerpo(&armar_send_xml_desde_form(&f, &firmado, "***", &tmst));
                let want = String::from_utf8_lossy(&want).into_owned();
                assert!(
                    got == want,
                    "{}: cuerpo distinto: {}",
                    dir.display(),
                    primera_diferencia(&got, &want)
                );
                n += 1;
            }
        }
        eprintln!("evidencias comparadas: {n}");
    }

    /// Con las trazas privadas de storage/siiengine_paridad (páginas que el portal devolvió en
    /// un dry-run y cuerpos que Python armó sobre el mismo flujo), el payload de GenXMLFirma
    /// debe ser byte a byte el de Python. Se salta si no están.
    #[test]
    fn paridad_trazas() {
        let raiz = format!(
            "{}/../storage/siiengine_paridad",
            env!("CARGO_MANIFEST_DIR")
        );
        let Ok(pb) = std::fs::read(format!("{raiz}/params.json")) else {
            return;
        };
        let params: serde_json::Value = serde_json::from_slice(&pb).unwrap();
        let rec = &params["receptor"];
        let s = |v: &serde_json::Value, k: &str| {
            v.get(k).and_then(|x| x.as_str()).unwrap_or("").to_string()
        };
        let receptor = Receptor {
            rut: s(rec, "rut"),
            razon_social: s(rec, "razon_social"),
            giro: s(rec, "giro"),
            direccion: s(rec, "direccion"),
            ciudad: s(rec, "ciudad"),
            comuna: s(rec, "comuna"),
        };
        let it = &params["item"];
        let items = vec![Item {
            nombre: s(it, "nombre"),
            precio: it["precio"].as_i64().unwrap_or(0),
            cantidad: it["cantidad"].as_i64().unwrap_or(0),
            descripcion: s(it, "descripcion"),
        }];
        let (fecha, forma_pago) = (s(&params, "fecha"), s(&params, "forma_pago"));
        let leer = |flujo: &str, nombre: &str| {
            std::fs::read(format!("{raiz}/{flujo}/{nombre}"))
                .ok()
                .map(|b| super::super::latin1(&b))
        };
        let mut n = 0;
        if let (Some(pag), Some(want)) = (
            leer("factura", "go/preview.html"),
            leer("factura", "py/body_genxml.txt"),
        ) {
            let p = armar_payload(
                &parsear_form_ordenado(&pag),
                34,
                &receptor,
                &items,
                &fecha,
                &forma_pago,
                &[],
                &["ES_BORR", "INDICA_PRIMERA_EJECUCION"],
            )
            .unwrap();
            let got = cuerpo(&p.pares);
            assert!(
                got == want,
                "factura genxml: {}",
                primera_diferencia(&got, &want)
            );
            n += 1;
        }
        for (flujo, pagina, codigo, razon) in [
            (
                "nc-anular",
                "go/nc_anulacion.html",
                CODIGO_REF_ANULA,
                RAZON_REF_ANULA,
            ),
            (
                "nc-corregir",
                "go/corr_preview.html",
                CODIGO_REF_CORRIGE_MONTO,
                RAZON_REF_CORRIGE_MONTO,
            ),
        ] {
            let (Some(pag), Some(want)) = (leer(flujo, pagina), leer(flujo, "py/body_genxml.txt"))
            else {
                continue;
            };
            let r = &params[flujo];
            let refe = Referencia {
                tipo: r["tipo_ref"].as_i64().unwrap_or(0) as i32,
                folio: r["folio_ref"].as_i64().unwrap_or(0),
                fecha: s(r, "fecha_ref"),
                codigo: codigo.into(),
                razon: razon.into(),
            };
            let p = armar_payload(
                &parsear_form_ordenado(&pag),
                61,
                &receptor,
                &items,
                &fecha,
                "",
                &[refe],
                &["ES_BORR", "EFXP_FMA_PAGO", "INDICA_PRIMERA_EJECUCION"],
            )
            .unwrap();
            let got = cuerpo(&p.pares);
            assert!(
                got == want,
                "{flujo} genxml: {}",
                primera_diferencia(&got, &want)
            );
            n += 1;
        }
        eprintln!("flujos comparados: {n}");
        if let Some(pag) = leer("nc-anular", "go/nc_anulacion.html") {
            let (rec, items) = receptor_e_items_desde_form(&parsear_form_ordenado(&pag));
            assert!(
                validar_rut(&rec.rut)
                    && !rec.razon_social.is_empty()
                    && !rec.comuna.is_empty()
                    && items.len() == 1
                    && items[0].subtotal() == 1000,
                "receptor={rec:?} items={items:?}"
            );
            assert!(!rec.direccion.ends_with(' '), "dirección con relleno");
        }
    }
}
