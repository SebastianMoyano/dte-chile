//! Arma el `<DTE>` sin firmar exactamente como `core/dte.py::GeneradorDTE` (facturas, notas,
//! guías) y `core/boleta.py::generar_documento_boleta` (39/41), y lo serializa como lo haría
//! lxml: sin espacios entre tags, texto escapado, atributos en el orden de inserción.
//! Transcripción de `nucleo/xmlgen` (Go).

use crate::totales;

pub const NS_SII: &str = "http://www.sii.cl/SiiDte";

/// Elemento mínimo. `raw` se inserta tal cual (el TED ya serializado).
#[derive(Debug, Clone, Default)]
pub struct Nodo {
    pub tag: String,
    pub attrs: Vec<(String, String)>,
    pub text: String,
    pub hijos: Vec<Nodo>,
    pub raw: String,
}

impl Nodo {
    pub fn nuevo(tag: &str) -> Nodo {
        Nodo {
            tag: tag.to_string(),
            ..Default::default()
        }
    }

    pub fn raw(xml: String) -> Nodo {
        Nodo {
            raw: xml,
            ..Default::default()
        }
    }

    pub fn sub(&mut self, tag: &str) -> &mut Nodo {
        self.hijos.push(Nodo::nuevo(tag));
        self.hijos.last_mut().expect("recién insertado")
    }

    pub fn sub_texto(&mut self, tag: &str, texto: impl Into<String>) -> &mut Nodo {
        let h = self.sub(tag);
        h.text = texto.into();
        h
    }

    pub fn attr(&mut self, k: &str, v: &str) -> &mut Nodo {
        self.attrs.push((k.to_string(), v.to_string()));
        self
    }

    /// Escribe el nodo como lxml (`etree.tostring(..., encoding="unicode")`).
    pub fn serializar(&self, b: &mut String) {
        if !self.raw.is_empty() {
            b.push_str(&self.raw);
            return;
        }
        b.push('<');
        b.push_str(&self.tag);
        for (k, v) in &self.attrs {
            b.push(' ');
            b.push_str(k);
            b.push_str("=\"");
            b.push_str(&esc_attr(v));
            b.push('"');
        }
        if self.text.is_empty() && self.hijos.is_empty() {
            b.push_str("/>");
            return;
        }
        b.push('>');
        b.push_str(&esc_texto(&self.text));
        for h in &self.hijos {
            h.serializar(b);
        }
        b.push_str("</");
        b.push_str(&self.tag);
        b.push('>');
    }

    pub fn string(&self) -> String {
        let mut b = String::new();
        self.serializar(&mut b);
        b
    }
}

/// Escape de libxml2 para texto: `& < >` y `\r`.
pub fn esc_texto(s: &str) -> String {
    let mut b = String::with_capacity(s.len());
    for c in s.chars() {
        match c {
            '&' => b.push_str("&amp;"),
            '<' => b.push_str("&lt;"),
            '>' => b.push_str("&gt;"),
            '\r' => b.push_str("&#13;"),
            _ => b.push(c),
        }
    }
    b
}

/// Escape de libxml2 para valores de atributo.
pub fn esc_attr(s: &str) -> String {
    let mut b = String::with_capacity(s.len());
    for c in s.chars() {
        match c {
            '&' => b.push_str("&amp;"),
            '<' => b.push_str("&lt;"),
            '"' => b.push_str("&quot;"),
            '\n' => b.push_str("&#10;"),
            '\r' => b.push_str("&#13;"),
            '\t' => b.push_str("&#9;"),
            _ => b.push(c),
        }
    }
    b
}

// ---- datos de entrada (espejo de DTEInput) ----

#[derive(Debug, Clone, Default, serde::Serialize)]
pub struct Emisor {
    pub rut: String,
    pub razon_social: String,
    pub giro: String,
    pub direccion: String,
    pub comuna: String,
    pub ciudad: String,
    pub telefono: String,
    pub email: String,
    pub codigo_actividad: i64,
}

#[derive(Debug, Clone, Default, serde::Serialize)]
pub struct Receptor {
    pub rut: String,
    pub razon_social: String,
    pub giro: String,
    pub direccion: String,
    pub comuna: String,
    pub ciudad: String,
    pub email: String,
}

#[derive(Debug, Clone, Default, serde::Serialize)]
pub struct Item {
    pub numero_linea: i32,
    pub nombre: String,
    pub descripcion: String,
    pub cantidad: f64,
    pub unidad_medida: String,
    pub precio_unitario: f64,
    pub descuento_pct: f64,
    pub descuento_monto: f64,
    pub exento: bool,
    pub codigo_producto: String,
}

#[derive(Debug, Clone, Default, serde::Serialize)]
pub struct Referencia {
    pub numero_linea: i32,
    pub tipo_doc_ref: i32,
    pub folio_ref: i64,
    pub fecha_doc_ref: String,
    pub codigo_ref: i32,
    pub razon_ref: String,
}

#[derive(Debug, Clone, Default, serde::Serialize)]
pub struct Documento {
    pub tipo_dte: i32,
    pub folio: i32,
    pub fecha_emision: String,
    pub emisor: Emisor,
    pub receptor: Receptor,
    pub items: Vec<Item>,
    pub referencias: Vec<Referencia>,
    pub forma_pago: i32,
    pub fecha_vencimiento: String,
    /// 0 = ninguno
    pub indicador_servicio: i32,
    /// parámetro `ind_servicio` de `generar_documento_boleta` (0 = ninguno)
    pub ind_servicio_boleta: i32,
    pub ted: String,
    pub marca: String,
}

// ---- formatos numéricos de Python ----

/// `str(float)` de Python: repr más corta, con ".0" si es entero.
pub fn py_str_float(f: f64) -> String {
    totales::py_repr(f)
}

/// `core/dte.py::formatear_numero`: entero si es redondo, si no hasta 6 decimales sin ceros
/// sobrantes.
pub fn formatear_numero(f: f64) -> String {
    if f == f.trunc() {
        return format!("{}", f as i64);
    }
    let s = format!("{f:.6}");
    let s = s.trim_end_matches('0');
    s.trim_end_matches('.').to_string()
}

/// `core/boleta.py::_num`: entero si es redondo, si no `repr(float)`.
fn num_boleta(f: f64) -> String {
    if f == f.trunc() {
        return format!("{}", f as i64);
    }
    totales::py_repr(f)
}

fn item_totales(it: &Item) -> totales::Item {
    totales::Item {
        cantidad: it.cantidad,
        precio_unitario: it.precio_unitario,
        descuento_pct: it.descuento_pct,
        descuento_monto: it.descuento_monto,
        exento: it.exento,
    }
}

fn monto_descuento(it: &Item) -> f64 {
    let m = totales::redondear(it.cantidad * it.precio_unitario) as f64;
    if it.descuento_monto > 0.0 {
        return it.descuento_monto;
    }
    if it.descuento_pct > 0.0 {
        return totales::redondear(m * it.descuento_pct / 100.0) as f64;
    }
    0.0
}

fn recortar(s: &str, n: usize) -> String {
    s.chars().take(n).collect()
}

/// El TED real si viene; si no, el de marcador de posición de
/// `GeneradorDTE._generar_ted_placeholder` (sin firma del CAF; RSR es la razón social del
/// EMISOR, como en Python), ya serializado como lo deja lxml (`<CAF/>`, texto escapado).
fn ted_o_placeholder(d: &Documento, monto_total: i64) -> String {
    if !d.ted.is_empty() {
        return d.ted.clone();
    }
    let primer = d.items.first().map(|i| i.nombre.as_str()).unwrap_or("");
    format!(
        "<TED version=\"1.0\"><DD><RE>{}</RE><TD>{}</TD><F>{}</F><FE>{}</FE><RR>{}</RR><RSR>{}</RSR><MNT>{}</MNT><IT1>{}</IT1><CAF/><TSTED>{}</TSTED></DD><FRMT algoritmo=\"SHA1withRSA\">FIRMA_PLACEHOLDER</FRMT></TED>",
        esc_texto(&d.emisor.rut),
        d.tipo_dte,
        d.folio,
        d.fecha_emision,
        esc_texto(&d.receptor.rut),
        esc_texto(&recortar(&d.emisor.razon_social, 40)),
        monto_total,
        esc_texto(&recortar(primer, 40)),
        d.marca
    )
}

fn raiz_dte(d: &Documento) -> (Nodo, usize) {
    let mut dte = Nodo::nuevo("DTE");
    dte.attr("xmlns", NS_SII).attr("version", "1.0");
    let doc = dte.sub("Documento");
    doc.attr("ID", &format!("T{}F{}", d.tipo_dte, d.folio));
    (dte, 0)
}

/// `<DTE>` de factura/nota/guía (`GeneradorDTE.generar_documento_xml`).
pub fn generar_dte(d: &Documento) -> Nodo {
    let its: Vec<totales::Item> = d.items.iter().map(item_totales).collect();
    let t = totales::calcular(&its, d.tipo_dte);
    let (mut dte, _) = raiz_dte(d);
    let doc = &mut dte.hijos[0];
    {
        let enc = doc.sub("Encabezado");
        let id = enc.sub("IdDoc");
        id.sub_texto("TipoDTE", d.tipo_dte.to_string());
        id.sub_texto("Folio", d.folio.to_string());
        id.sub_texto("FchEmis", d.fecha_emision.clone());
        if d.indicador_servicio != 0 {
            id.sub_texto("IndServicio", d.indicador_servicio.to_string());
        }
        id.sub_texto("FmaPago", d.forma_pago.to_string());
        if !d.fecha_vencimiento.is_empty() {
            id.sub_texto("FchVenc", d.fecha_vencimiento.clone());
        }

        let e = enc.sub("Emisor");
        e.sub_texto("RUTEmisor", d.emisor.rut.clone());
        e.sub_texto("RznSoc", d.emisor.razon_social.clone());
        e.sub_texto("GiroEmis", d.emisor.giro.clone());
        if !d.emisor.telefono.is_empty() {
            e.sub_texto("Telefono", d.emisor.telefono.clone());
        }
        if !d.emisor.email.is_empty() {
            e.sub_texto("CorreoEmisor", d.emisor.email.clone());
        }
        e.sub_texto("Acteco", d.emisor.codigo_actividad.to_string());
        e.sub_texto("DirOrigen", d.emisor.direccion.clone());
        e.sub_texto("CmnaOrigen", d.emisor.comuna.clone());
        e.sub_texto("CiudadOrigen", d.emisor.ciudad.clone());

        let r = enc.sub("Receptor");
        r.sub_texto("RUTRecep", d.receptor.rut.clone());
        r.sub_texto("RznSocRecep", d.receptor.razon_social.clone());
        if !d.receptor.giro.is_empty() {
            r.sub_texto("GiroRecep", d.receptor.giro.clone());
        }
        if !d.receptor.email.is_empty() {
            r.sub_texto("CorreoRecep", d.receptor.email.clone());
        }
        if !d.receptor.direccion.is_empty() {
            r.sub_texto("DirRecep", d.receptor.direccion.clone());
        }
        if !d.receptor.comuna.is_empty() {
            r.sub_texto("CmnaRecep", d.receptor.comuna.clone());
        }
        if !d.receptor.ciudad.is_empty() {
            r.sub_texto("CiudadRecep", d.receptor.ciudad.clone());
        }

        let tot = enc.sub("Totales");
        if t.monto_neto > 0 {
            tot.sub_texto("MntNeto", t.monto_neto.to_string());
        }
        if t.monto_exento > 0 {
            tot.sub_texto("MntExe", t.monto_exento.to_string());
        }
        if t.iva_monto > 0 {
            tot.sub_texto("TasaIVA", t.iva_tasa.to_string());
            tot.sub_texto("IVA", t.iva_monto.to_string());
        }
        tot.sub_texto("MntTotal", t.monto_total.to_string());
    }

    for it in &d.items {
        let det = doc.sub("Detalle");
        det.sub_texto("NroLinDet", it.numero_linea.to_string());
        if !it.codigo_producto.is_empty() {
            let c = det.sub("CdgItem");
            c.sub_texto("TpoCodigo", "INT1");
            c.sub_texto("VlrCodigo", it.codigo_producto.clone());
        }
        if it.exento {
            det.sub_texto("IndExe", "1");
        }
        det.sub_texto("NmbItem", it.nombre.clone());
        if !it.descripcion.is_empty() {
            det.sub_texto("DscItem", it.descripcion.clone());
        }
        if it.cantidad > 0.0 {
            det.sub_texto("QtyItem", formatear_numero(it.cantidad));
        }
        if !it.unidad_medida.is_empty() {
            det.sub_texto("UnmdItem", it.unidad_medida.clone());
        }
        if it.precio_unitario > 0.0 {
            det.sub_texto("PrcItem", formatear_numero(it.precio_unitario));
        }
        if it.descuento_pct > 0.0 {
            det.sub_texto("DescuentoPct", py_str_float(it.descuento_pct));
        }
        let md = monto_descuento(it);
        if md > 0.0 {
            det.sub_texto("DescuentoMonto", (md as i64).to_string());
        }
        det.sub_texto(
            "MontoItem",
            (totales::monto_neto_item(&item_totales(it)) as i64).to_string(),
        );
    }

    for r in &d.referencias {
        let rf = doc.sub("Referencia");
        rf.sub_texto("NroLinRef", r.numero_linea.to_string());
        rf.sub_texto("TpoDocRef", r.tipo_doc_ref.to_string());
        rf.sub_texto("FolioRef", r.folio_ref.to_string());
        rf.sub_texto("FchRef", r.fecha_doc_ref.clone());
        rf.sub_texto("CodRef", r.codigo_ref.to_string());
        if !r.razon_ref.is_empty() {
            rf.sub_texto("RazonRef", r.razon_ref.clone());
        }
    }
    doc.hijos
        .push(Nodo::raw(ted_o_placeholder(d, t.monto_total)));
    doc.sub_texto("TmstFirma", d.marca.clone());
    dte
}

/// `<DTE>` de una boleta 39/41 (`core/boleta.py::generar_documento_boleta`).
pub fn generar_boleta(d: &Documento) -> Nodo {
    let its: Vec<totales::Item> = d.items.iter().map(item_totales).collect();
    let t = totales::calcular(&its, d.tipo_dte);
    let (mut dte, _) = raiz_dte(d);
    let doc = &mut dte.hijos[0];
    {
        let enc = doc.sub("Encabezado");
        let id = enc.sub("IdDoc");
        id.sub_texto("TipoDTE", d.tipo_dte.to_string());
        id.sub_texto("Folio", d.folio.to_string());
        id.sub_texto("FchEmis", d.fecha_emision.clone());
        let mut ind = d.indicador_servicio;
        if ind == 0 {
            ind = d.ind_servicio_boleta;
        }
        if ind == 0 {
            ind = 3;
        }
        id.sub_texto("IndServicio", ind.to_string());

        let e = enc.sub("Emisor");
        e.sub_texto("RUTEmisor", d.emisor.rut.clone());
        e.sub_texto("RznSocEmisor", d.emisor.razon_social.clone());
        e.sub_texto("GiroEmisor", d.emisor.giro.clone());
        if !d.emisor.direccion.is_empty() {
            e.sub_texto("DirOrigen", d.emisor.direccion.clone());
        }
        if !d.emisor.comuna.is_empty() {
            e.sub_texto("CmnaOrigen", d.emisor.comuna.clone());
        }
        if !d.emisor.ciudad.is_empty() {
            e.sub_texto("CiudadOrigen", d.emisor.ciudad.clone());
        }

        let r = enc.sub("Receptor");
        r.sub_texto("RUTRecep", d.receptor.rut.clone());
        if !d.receptor.razon_social.is_empty()
            && d.receptor.razon_social.to_uppercase() != "CONSUMIDOR FINAL"
        {
            r.sub_texto("RznSocRecep", d.receptor.razon_social.clone());
        }
        if !d.receptor.direccion.is_empty() {
            r.sub_texto("DirRecep", d.receptor.direccion.clone());
        }
        if !d.receptor.comuna.is_empty() {
            r.sub_texto("CmnaRecep", d.receptor.comuna.clone());
        }
        if !d.receptor.ciudad.is_empty() {
            r.sub_texto("CiudadRecep", d.receptor.ciudad.clone());
        }

        let tot = enc.sub("Totales");
        if t.monto_neto != 0 {
            tot.sub_texto("MntNeto", t.monto_neto.to_string());
        }
        if t.monto_exento != 0 {
            tot.sub_texto("MntExe", t.monto_exento.to_string());
        }
        if t.iva_monto != 0 {
            tot.sub_texto("IVA", t.iva_monto.to_string());
        }
        tot.sub_texto("MntTotal", t.monto_total.to_string());
    }

    for (i, it) in d.items.iter().enumerate() {
        let det = doc.sub("Detalle");
        let nl = if it.numero_linea == 0 {
            i as i32 + 1
        } else {
            it.numero_linea
        };
        det.sub_texto("NroLinDet", nl.to_string());
        if it.exento {
            det.sub_texto("IndExe", "1");
        }
        det.sub_texto("NmbItem", it.nombre.clone());
        det.sub_texto("QtyItem", num_boleta(it.cantidad));
        if !it.unidad_medida.is_empty() {
            det.sub_texto("UnmdItem", it.unidad_medida.clone());
        }
        det.sub_texto("PrcItem", num_boleta(it.precio_unitario));
        if it.descuento_monto != 0.0 {
            det.sub_texto("DescuentoMonto", (it.descuento_monto as i64).to_string());
        }
        // int(round(cant*precio - desc_monto)): round() de Python es half-even.
        let monto = (it.cantidad * it.precio_unitario - it.descuento_monto).round_ties_even();
        det.sub_texto("MontoItem", (monto as i64).to_string());
    }
    doc.hijos
        .push(Nodo::raw(ted_o_placeholder(d, t.monto_total)));
    doc.sub_texto("TmstFirma", d.marca.clone());
    dte
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn formatos_numericos() {
        assert_eq!(formatear_numero(3.0), "3");
        assert_eq!(formatear_numero(2.5), "2.5");
        assert_eq!(formatear_numero(0.1234567), "0.123457");
        assert_eq!(py_str_float(10.0), "10.0");
        assert_eq!(py_str_float(12.5), "12.5");
    }

    #[test]
    fn serializa_como_lxml() {
        let mut n = Nodo::nuevo("A");
        n.attr("x", "1&2");
        n.sub_texto("B", "a<b");
        n.sub("C");
        assert_eq!(n.string(), r#"<A x="1&amp;2"><B>a&lt;b</B><C/></A>"#);
    }
}
