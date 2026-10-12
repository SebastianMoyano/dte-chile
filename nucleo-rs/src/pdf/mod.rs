//! La representación gráfica de un DTE (carta) o de una boleta (80 mm) con el timbre PDF417,
//! réplica de `core/pdf_gen.py` vía `nucleo/pdf` (Go). Equivalente en contenido, no byte a
//! byte (decisión en `docs/COMPARACION-PYTHON-GO.md`): lo que importa es el timbre, que lleva
//! el TED verbatim y las mismas filas de códigos que Python.

mod desdexml;
mod fpdf;
mod helvetica;
mod png;

pub use desdexml::desde_xml;
pub use fpdf::{Align, Estilo, Pdf};

use crate::pdf417;
use crate::totales;
use crate::xmlgen::Documento;

/// `NOMBRES_DTE`.
pub fn nombre_dte(tipo: i32) -> Option<&'static str> {
    Some(match tipo {
        33 => "FACTURA ELECTRÓNICA",
        34 => "FACTURA NO AFECTA O EXENTA ELECTRÓNICA",
        39 => "BOLETA ELECTRÓNICA",
        41 => "BOLETA NO AFECTA O EXENTA ELECTRÓNICA",
        52 => "GUÍA DE DESPACHO ELECTRÓNICA",
        56 => "NOTA DE DÉBITO ELECTRÓNICA",
        61 => "NOTA DE CRÉDITO ELECTRÓNICA",
        _ => return None,
    })
}

/// Opciones del pie: ambiente y resolución del emisor (la leyenda bajo el timbre es por
/// emisor, L4).
#[derive(Debug, Clone, Default)]
pub struct Opciones {
    /// certificacion | produccion | simulacion
    pub ambiente: String,
    /// YYYY-MM-DD
    pub resolucion_fecha: String,
    pub resolucion_num: i64,
    /// YYYY-MM-DD (vacío = hoy)
    pub hoy: String,
}

fn miles(digitos: &str) -> String {
    let mut b = String::with_capacity(digitos.len() + 4);
    let n = digitos.len();
    for (i, c) in digitos.chars().enumerate() {
        if i > 0 && (n - i).is_multiple_of(3) {
            b.push('.');
        }
        b.push(c);
    }
    b
}

/// `pdf_gen.formatear_rut`: puntos de miles y guión.
pub fn formatear_rut(rut: &str) -> String {
    match rut.split_once('-') {
        None => rut.to_string(),
        Some((n, dv)) => format!("{}-{}", miles(&n.replace('.', "")), dv),
    }
}

/// `formatear_monto`: "$ 1.234.567".
pub fn formatear_monto(m: i64) -> String {
    if m < 0 {
        format!("$ -{}", miles(&m.unsigned_abs().to_string()))
    } else {
        format!("$ {}", miles(&m.to_string()))
    }
}

/// `_generar_barcode_pdf417`: PDF417 con nivel de corrección 5 (guía del SII) y 12 columnas,
/// módulos de 2 px de ancho y 6 px de alto y margen de 20 px, exactamente como
/// `pdf417gen.render_image(scale=2, ratio=3)`. El dato son los bytes UTF-8 del TED.
pub fn timbre_png(ted: &str) -> Result<Vec<u8>, String> {
    let filas = pdf417::codificar(ted.as_bytes(), 12, 5)?;
    let img = pdf417::imagen(&filas, 2, 3, 20);
    Ok(png::gris(img.ancho, img.alto, &img.pix))
}

/// Pinta el PDF417 como vectores (un rectángulo por tramo de barras) en el recuadro
/// (x, y, w, h) en mm: sin interpolación al rasterizar ni al imprimir, el código se lee a
/// cualquier resolución. Mismas filas de códigos que el PNG.
fn dibujar_timbre(p: &mut Pdf, ted: &str, x: f64, y: f64, w: f64, h: f64) -> bool {
    if ted.is_empty() {
        return false;
    }
    let Ok(filas) = pdf417::codificar(ted.as_bytes(), 12, 5) else {
        return false;
    };
    let ancho_mod = filas[0].len() * 17 + 1;
    let mw = w / ancho_mod as f64;
    let mh = h / filas.len() as f64;
    p.set_fill_color(0, 0, 0);
    for (fy, fila) in filas.iter().enumerate() {
        for (ini, largo) in pdf417::tramos(fila) {
            p.rect(
                x + ini as f64 * mw,
                y + fy as f64 * mh,
                largo as f64 * mw,
                mh,
                Estilo::F,
            );
        }
    }
    true
}

fn items_totales(d: &Documento) -> Vec<totales::Item> {
    d.items
        .iter()
        .map(|it| totales::Item {
            cantidad: it.cantidad,
            precio_unitario: it.precio_unitario,
            descuento_pct: it.descuento_pct,
            descuento_monto: it.descuento_monto,
            exento: it.exento,
        })
        .collect()
}

fn hoy(o: &Opciones) -> String {
    if !o.hoy.is_empty() {
        return o.hoy.clone();
    }
    // fecha local sin dependencias: días desde la época en UTC (como time.Now().Format en Go
    // sería local; la diferencia de un día en el borde no afecta a nada tributario)
    let secs = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs() as i64)
        .unwrap_or(0);
    let dias = secs.div_euclid(86400);
    let (y, m, d) = civil_desde_dias(dias);
    format!("{y:04}-{m:02}-{d:02}")
}

fn civil_desde_dias(z: i64) -> (i64, u32, u32) {
    let z = z + 719468;
    let era = if z >= 0 { z } else { z - 146096 } / 146097;
    let doe = z - era * 146097;
    let yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365;
    let y = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = (doy - (153 * mp + 2) / 5 + 1) as u32;
    let m = if mp < 10 { mp + 3 } else { mp - 9 } as u32;
    (if m <= 2 { y + 1 } else { y }, m, d)
}

/// `f"{x:g}"` (Go: `%g`, y `%.6g` si saliera exponente).
fn cantidad_g(f: f64) -> String {
    if f == f.trunc() && f.abs() < 1e6 {
        return format!("{}", f as i64);
    }
    if f.abs() >= 1e6 || (f != 0.0 && f.abs() < 1e-4) {
        let exp = f.abs().log10().floor() as i32;
        let mant = f / 10f64.powi(exp);
        let mut m = format!("{mant:.5}");
        m = m.trim_end_matches('0').trim_end_matches('.').to_string();
        return format!("{m}e{}{:02}", if exp < 0 { '-' } else { '+' }, exp.abs());
    }
    totales::py_repr(f).trim_end_matches(".0").to_string()
}

const COLOR_AZUL: (u8, u8, u8) = (0x1a, 0x3a, 0x5c);
const COLOR_LINEA: (u8, u8, u8) = (0x25, 0x63, 0xeb);
const COLOR_GRIS: (u8, u8, u8) = (0xf1, 0xf5, 0xf9);

/// `generar_pdf_dte`: la representación gráfica en hoja carta.
pub fn carta(d: &Documento, ted: &str, o: &Opciones) -> Result<Vec<u8>, String> {
    let tot = totales::calcular(&items_totales(d), d.tipo_dte);
    let mut p = Pdf::new(215.9, 279.4);
    p.set_title(&format!("DTE-{}-{}", d.tipo_dte, d.folio));
    p.set_margins(15.0, 15.0, 15.0);
    p.set_auto_page_break(true, 15.0);
    p.add_page();
    let (azul, linea, gris) = (COLOR_AZUL, COLOR_LINEA, COLOR_GRIS);
    let ancho = 215.9 - 30.0;
    let nombre = nombre_dte(d.tipo_dte)
        .map(str::to_string)
        .unwrap_or_else(|| format!("DTE TIPO {}", d.tipo_dte));

    // ---- Cabecera: emisor | recuadro tipo/RUT/folio | S.I.I. ----
    let y0 = p.get_y();
    p.set_text_color(azul.0, azul.1, azul.2);
    p.set_font(true, 13.0);
    let lineas_titulo = p.split_text(&nombre, 76.0);
    let alto_box = 4.0 + 7.0 * lineas_titulo.len() as f64 + 6.0 + 7.0 + 4.0;
    p.set_fill_color(0xeb, 0xf2, 0xff);
    p.set_draw_color(linea.0, linea.1, linea.2);
    p.set_line_width(0.5);
    p.rect(85.0, y0, 80.0, alto_box, Estilo::FD);
    p.set_xy(85.0, y0 + 2.0);
    for l in &lineas_titulo {
        p.set_x(85.0);
        p.cell(80.0, 7.0, l, false, 1, Align::C, false);
    }
    p.set_font(true, 10.0);
    p.set_x(85.0);
    p.cell(
        80.0,
        6.0,
        &format!("RUT: {}", formatear_rut(&d.emisor.rut)),
        false,
        1,
        Align::C,
        false,
    );
    p.set_font(true, 13.0);
    p.set_x(85.0);
    p.cell(
        80.0,
        7.0,
        &format!("N° {}", d.folio),
        false,
        1,
        Align::C,
        false,
    );
    p.set_font(true, 10.0);
    p.set_xy(15.0, y0 + alto_box / 2.0 - 3.0);
    p.multi_cell(
        68.0,
        5.0,
        &d.emisor.razon_social.to_uppercase(),
        Align::C,
        false,
    );
    p.set_xy(165.0, y0 + alto_box / 2.0 - 3.0);
    p.cell(35.0, 6.0, "S.I.I.", false, 0, Align::R, false);
    p.set_xy(15.0, y0 + alto_box + 3.0);

    // ---- Datos del emisor ----
    p.set_text_color(0, 0, 0);
    p.set_font(false, 8.0);
    let y = p.get_y();
    p.set_xy(15.0, y);
    p.cell(
        120.0,
        4.5,
        &format!("Giro: {}", d.emisor.giro),
        false,
        0,
        Align::L,
        false,
    );
    p.set_xy(135.0, y);
    p.cell(65.0, 4.5, "Fecha de Emisión: ", false, 0, Align::L, false);
    let w_fecha = p.get_string_width("Fecha de Emisión: ");
    p.set_font(true, 8.0);
    p.set_xy(135.0 + w_fecha, y);
    p.cell(40.0, 4.5, &d.fecha_emision, false, 1, Align::L, false);
    p.set_font(false, 8.0);
    p.set_x(15.0);
    p.cell(
        120.0,
        4.5,
        &format!(
            "Dirección: {}, {}, {}",
            d.emisor.direccion, d.emisor.comuna, d.emisor.ciudad
        ),
        false,
        1,
        Align::L,
        false,
    );
    p.ln(1.5);
    p.set_draw_color(linea.0, linea.1, linea.2);
    p.set_line_width(0.35);
    let yl = p.get_y();
    p.line(15.0, yl, 15.0 + ancho, yl);
    p.ln(1.5);

    // ---- Receptor ----
    p.set_font(false, 7.0);
    p.set_text_color(128, 128, 128);
    p.cell(ancho, 4.0, "DATOS DEL RECEPTOR", false, 1, Align::L, false);
    p.set_text_color(0, 0, 0);
    p.set_fill_color(gris.0, gris.1, gris.2);
    let mut filas: Vec<(String, String)> =
        vec![("Razón Social: ".into(), d.receptor.razon_social.clone())];
    if !d.receptor.giro.is_empty() {
        filas.push(("Giro: ".into(), d.receptor.giro.clone()));
    }
    if !d.receptor.direccion.is_empty() {
        filas.push((
            "Dirección: ".into(),
            format!(
                "{}, {}, {}",
                d.receptor.direccion, d.receptor.comuna, d.receptor.ciudad
            ),
        ));
    }
    let yr = p.get_y();
    p.rect(15.0, yr, ancho, 5.5 * filas.len() as f64 + 1.0, Estilo::F);
    p.set_y(yr + 0.5);
    for (i, f) in filas.iter().enumerate() {
        p.set_x(15.0);
        p.set_font(false, 8.0);
        let w = p.get_string_width(&f.0) + 1.0;
        p.cell(w, 5.5, &f.0, false, 0, Align::L, false);
        if i == 0 {
            p.set_font(true, 8.0);
            p.cell(110.0, 5.5, &f.1, false, 0, Align::L, false);
            p.set_font(false, 8.0);
            p.set_x(135.0);
            p.cell(10.0, 5.5, "RUT: ", false, 0, Align::L, false);
            p.set_font(true, 8.0);
            p.cell(
                50.0,
                5.5,
                &formatear_rut(&d.receptor.rut),
                false,
                1,
                Align::L,
                false,
            );
        } else {
            p.cell(150.0, 5.5, &f.1, false, 1, Align::L, false);
        }
    }
    p.ln(4.0);

    // ---- Ítems ----
    let cols = [7.0, 20.0, 63.0, 12.0, 10.0, 25.0, 15.0, 28.0];
    let heads = [
        "N°",
        "Código",
        "Descripción",
        "Cant.",
        "U.M.",
        "Precio Unit.",
        "Desc.",
        "Total",
    ];
    p.set_fill_color(azul.0, azul.1, azul.2);
    p.set_text_color(255, 255, 255);
    p.set_draw_color(0xcb, 0xd5, 0xe1);
    p.set_line_width(0.1);
    p.set_font(true, 8.0);
    for (i, h) in heads.iter().enumerate() {
        p.cell(cols[i], 6.0, h, true, 0, Align::C, true);
    }
    p.ln(-1.0);
    p.set_text_color(0, 0, 0);
    p.set_font(false, 8.0);
    for (i, it) in d.items.iter().enumerate() {
        let fill = i % 2 == 1;
        p.set_fill_color(gris.0, gris.1, gris.2);
        let mut descr = it.nombre.clone();
        if !it.descripcion.is_empty() {
            descr.push('\n');
            descr.push_str(&it.descripcion);
        }
        let lineas = p.split_text(&descr, cols[2] - 2.0);
        let alto = if lineas.len() > 1 {
            4.2 * lineas.len() as f64 + 1.8
        } else {
            6.0
        };
        let base = totales::Item {
            cantidad: it.cantidad,
            precio_unitario: it.precio_unitario,
            ..Default::default()
        };
        let con_desc = totales::Item {
            cantidad: it.cantidad,
            precio_unitario: it.precio_unitario,
            descuento_pct: it.descuento_pct,
            descuento_monto: it.descuento_monto,
            exento: it.exento,
        };
        let desc = if it.descuento_monto != 0.0 || it.descuento_pct != 0.0 {
            formatear_monto(
                (totales::monto_neto_item(&base) - totales::monto_neto_item(&con_desc)) as i64,
            )
        } else {
            "-".to_string()
        };
        let vals = [
            it.numero_linea.to_string(),
            it.codigo_producto.clone(),
            String::new(),
            cantidad_g(it.cantidad),
            it.unidad_medida.clone(),
            formatear_monto(it.precio_unitario as i64),
            desc,
            formatear_monto(totales::monto_neto_item(&con_desc) as i64),
        ];
        let aligns = [
            Align::C,
            Align::C,
            Align::L,
            Align::C,
            Align::C,
            Align::R,
            Align::R,
            Align::R,
        ];
        let (mut x, yy) = (p.get_x(), p.get_y());
        for c in 0..cols.len() {
            if c == 2 {
                p.set_xy(x, yy);
                p.rect(
                    x,
                    yy,
                    cols[2],
                    alto,
                    if fill { Estilo::FD } else { Estilo::D },
                );
                p.set_xy(x + 1.0, yy + 0.9);
                p.multi_cell(cols[2] - 2.0, 4.2, &descr, Align::L, false);
                x += cols[2];
                p.set_xy(x, yy);
                continue;
            }
            p.set_xy(x, yy);
            p.cell(cols[c], alto, &vals[c], true, 0, aligns[c], fill);
            x += cols[c];
        }
        p.set_xy(15.0, yy + alto);
    }
    p.ln(4.0);

    // ---- Totales (a la derecha) ----
    let mut tf: Vec<(String, i64)> = Vec::new();
    if tot.monto_neto > 0 {
        tf.push(("Neto:".into(), tot.monto_neto));
    }
    if tot.monto_exento > 0 {
        tf.push(("Exento:".into(), tot.monto_exento));
    }
    if tot.iva_monto > 0 {
        tf.push((format!("IVA ({}%):", tot.iva_tasa), tot.iva_monto));
    }
    p.set_font(false, 9.0);
    let xt = 15.0 + ancho - 60.0;
    for (et, v) in &tf {
        p.set_x(xt);
        p.cell(30.0, 5.0, et, false, 0, Align::R, false);
        p.cell(30.0, 5.0, &formatear_monto(*v), false, 1, Align::R, false);
    }
    p.set_x(xt);
    p.set_draw_color(linea.0, linea.1, linea.2);
    p.set_line_width(0.35);
    let yt = p.get_y();
    p.line(xt, yt, xt + 60.0, yt);
    p.set_fill_color(gris.0, gris.1, gris.2);
    p.set_font(true, 9.0);
    p.cell(30.0, 6.0, "TOTAL:", false, 0, Align::R, true);
    p.cell(
        30.0,
        6.0,
        &formatear_monto(tot.monto_total),
        false,
        1,
        Align::R,
        true,
    );

    // ---- Referencias ----
    if !d.referencias.is_empty() {
        p.ln(4.0);
        p.set_font(false, 8.0);
        p.set_text_color(0x33, 0x33, 0x33);
        for r in &d.referencias {
            let nref = nombre_dte(r.tipo_doc_ref)
                .map(str::to_string)
                .unwrap_or_else(|| format!("documento tipo {}", r.tipo_doc_ref));
            let mot = match r.codigo_ref {
                1 => "Anula",
                2 => "Corrige texto de",
                3 => "Corrige montos de",
                _ => "Referencia a",
            };
            let mut t = format!(
                "Referencia: {mot} {nref} N° {} del {}",
                r.folio_ref, r.fecha_doc_ref
            );
            if !r.razon_ref.is_empty() {
                t.push_str(" — ");
                t.push_str(&r.razon_ref);
            }
            p.set_x(15.0);
            p.multi_cell(ancho, 4.5, &t, Align::L, false);
        }
        p.set_text_color(0, 0, 0);
    }

    // ---- Timbre ----
    p.ln(6.0);
    p.set_draw_color(211, 211, 211);
    p.set_line_width(0.2);
    let yl = p.get_y();
    p.line(15.0, yl, 15.0 + ancho, yl);
    p.ln(2.0);
    p.set_font(false, 7.0);
    p.set_text_color(128, 128, 128);
    p.cell(
        ancho,
        4.0,
        "Timbre Electrónico SII",
        false,
        1,
        Align::C,
        false,
    );
    if !ted.is_empty() {
        p.ln(2.0);
        let yt = p.get_y();
        if dibujar_timbre(&mut p, ted, 15.0 + (ancho - 90.0) / 2.0, yt, 90.0, 25.0) {
            p.set_y(yt + 25.0);
        }
    }
    p.ln(2.0);
    if o.ambiente == "simulacion" {
        p.cell(
            ancho,
            4.0,
            "Documento de práctica — no existe en www.sii.cl",
            false,
            1,
            Align::C,
            false,
        );
    } else {
        let anio = if o.resolucion_fecha.len() >= 4 {
            &o.resolucion_fecha[..4]
        } else {
            o.resolucion_fecha.as_str()
        };
        p.cell(
            ancho,
            4.0,
            &format!(
                "Res. {} de {} — Verifique documento: www.sii.cl",
                o.resolucion_num, anio
            ),
            false,
            1,
            Align::C,
            false,
        );
    }
    p.ln(3.0);
    let etiqueta = match o.ambiente.as_str() {
        "certificacion" => "AMBIENTE DE CERTIFICACIÓN SII".to_string(),
        "produccion" => "PRODUCCIÓN SII".to_string(),
        "simulacion" => "SIMULACIÓN · EMPRESA DE PRÁCTICA · SIN VALIDEZ TRIBUTARIA".to_string(),
        otro => otro.to_uppercase(),
    };
    p.cell(
        ancho,
        4.0,
        &format!("Documento generado el {} — {}", hoy(o), etiqueta),
        false,
        1,
        Align::C,
        false,
    );
    Ok(p.output())
}

/// `generar_boleta_80mm`: recibo para rollo térmico de 80 mm.
pub fn boleta_80mm(d: &Documento, ted: &str) -> Result<Vec<u8>, String> {
    let tot = totales::calcular(&items_totales(d), d.tipo_dte);
    let n = d.items.len().max(1);
    let alto = 115.0 + 11.0 * n as f64;
    let mut p = Pdf::new(80.0, alto);
    let m = 3.5;
    let util = 80.0 - 2.0 * m;
    p.set_margins(m, m, m);
    p.set_auto_page_break(false, m);
    p.add_page();
    fn hr(p: &mut Pdf, m: f64, util: f64) {
        p.ln(1.0);
        p.set_draw_color(0x94, 0xa3, 0xb8);
        p.set_line_width(0.2);
        p.set_dash(Some((0.4, 0.4)));
        let y = p.get_y();
        p.line(m, y, m + util, y);
        p.set_dash(None);
        p.ln(1.5);
    }
    fn ctr(p: &mut Pdf, m: f64, util: f64, txt: &str, size: f64, bold: bool, gris: bool) {
        p.set_font(bold, size);
        if gris {
            p.set_text_color(128, 128, 128);
        } else {
            p.set_text_color(0, 0, 0);
        }
        p.set_x(m);
        p.multi_cell(util, size * 0.42, txt, Align::C, false);
    }
    ctr(
        &mut p,
        m,
        util,
        &d.emisor.razon_social.to_uppercase(),
        9.5,
        true,
        false,
    );
    ctr(
        &mut p,
        m,
        util,
        &format!("RUT: {}", formatear_rut(&d.emisor.rut)),
        8.0,
        false,
        false,
    );
    if !d.emisor.giro.is_empty() {
        ctr(&mut p, m, util, &d.emisor.giro, 6.5, false, true);
    }
    if !d.emisor.direccion.is_empty() {
        let mut dir = d.emisor.direccion.clone();
        if !d.emisor.comuna.is_empty() {
            dir.push_str(", ");
            dir.push_str(&d.emisor.comuna);
        }
        ctr(&mut p, m, util, &dir, 6.5, false, true);
    }
    p.ln(2.5);
    let nombre = nombre_dte(d.tipo_dte)
        .map(str::to_string)
        .unwrap_or_else(|| format!("DTE {}", d.tipo_dte));
    ctr(&mut p, m, util, &nombre, 9.5, true, false);
    ctr(
        &mut p,
        m,
        util,
        &format!("N° {}", d.folio),
        8.0,
        false,
        false,
    );
    ctr(
        &mut p,
        m,
        util,
        &format!("Fecha: {}", d.fecha_emision),
        6.5,
        false,
        true,
    );
    hr(&mut p, m, util);
    p.set_text_color(0, 0, 0);
    for it in &d.items {
        let monto = totales::redondear(it.cantidad * it.precio_unitario - it.descuento_monto);
        let nom: String = it.nombre.chars().take(38).collect();
        let y = p.get_y();
        p.set_font(false, 7.5);
        p.set_xy(m, y);
        p.cell(util * 0.66, 3.8, &nom, false, 0, Align::L, false);
        p.set_xy(m + util * 0.66, y);
        p.cell(
            util * 0.34,
            3.8,
            &formatear_monto(monto),
            false,
            1,
            Align::R,
            false,
        );
        p.set_font(false, 6.0);
        p.set_text_color(0x64, 0x74, 0x8b);
        p.set_x(m);
        p.cell(
            util,
            3.0,
            &format!(
                "{} x {}",
                it.cantidad as i64,
                formatear_monto(it.precio_unitario as i64)
            ),
            false,
            1,
            Align::L,
            false,
        );
        p.set_text_color(0, 0, 0);
        p.ln(1.0);
    }
    hr(&mut p, m, util);
    p.set_font(false, 7.5);
    fn linea(p: &mut Pdf, m: f64, util: f64, et: &str, v: i64, size: f64, bold: bool) {
        p.set_font(bold, size);
        p.set_x(m);
        p.cell(util * 0.6, size * 0.5, et, false, 0, Align::L, false);
        p.cell(
            util * 0.4,
            size * 0.5,
            &formatear_monto(v),
            false,
            1,
            Align::R,
            false,
        );
    }
    if tot.monto_neto != 0 {
        linea(&mut p, m, util, "Neto", tot.monto_neto, 7.5, false);
    }
    if tot.iva_monto != 0 {
        linea(&mut p, m, util, "IVA (19%)", tot.iva_monto, 7.5, false);
    }
    if tot.monto_exento != 0 {
        linea(&mut p, m, util, "Exento", tot.monto_exento, 7.5, false);
    }
    p.ln(1.0);
    linea(&mut p, m, util, "TOTAL", tot.monto_total, 10.0, true);
    hr(&mut p, m, util);
    if !ted.is_empty() {
        ctr(&mut p, m, util, "Timbre Electrónico SII", 6.5, false, true);
        p.ln(1.0);
        let y = p.get_y();
        if dibujar_timbre(&mut p, ted, m, y, util, util / 3.0) {
            p.set_y(y + util / 3.0);
        }
    }
    p.ln(1.0);
    ctr(
        &mut p,
        m,
        util,
        "Verifique este documento en www.sii.cl",
        6.5,
        false,
        true,
    );
    Ok(p.output())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Read;

    fn texto_del_pdf(pdf: &[u8]) -> String {
        // concatena los streams descomprimidos para buscar texto en ellos
        let mut out = String::new();
        let mut pos = 0;
        while let Some(i) = pdf[pos..].windows(10).position(|w| w == b">>\nstream\n") {
            let ini = pos + i + 10;
            let fin = ini
                + pdf[ini..]
                    .windows(10)
                    .position(|w| w == b"\nendstream")
                    .unwrap();
            let mut dec = flate2::read::ZlibDecoder::new(&pdf[ini..fin]);
            let mut s = Vec::new();
            dec.read_to_end(&mut s).unwrap();
            out.push_str(&s.iter().map(|&b| b as char).collect::<String>());
            pos = fin;
        }
        out
    }

    #[test]
    fn formatos() {
        assert_eq!(formatear_rut("77777777-7"), "77.777.777-7");
        assert_eq!(formatear_rut("1-9"), "1-9");
        assert_eq!(formatear_monto(1234567), "$ 1.234.567");
        assert_eq!(formatear_monto(-50), "$ -50");
        assert_eq!(formatear_monto(0), "$ 0");
        assert_eq!(cantidad_g(3.0), "3");
        assert_eq!(cantidad_g(2.5), "2.5");
        assert_eq!(cantidad_g(1000000.0), "1e+06");
        assert_eq!(civil_desde_dias(0), (1970, 1, 1));
        assert_eq!(civil_desde_dias(20_000), (2024, 10, 4));
    }

    #[test]
    fn boleta_y_carta_desde_el_corpus() {
        let base = format!("{}/../tests/dorado/esperado", env!("CARGO_MANIFEST_DIR"));
        let Ok(raw) = std::fs::read(format!("{base}/01_boleta_cafe/dte.xml")) else {
            eprintln!("sin corpus");
            return;
        };
        let (d, ted) = desde_xml(&raw).unwrap();
        assert_eq!((d.tipo_dte, d.folio, d.items.len()), (39, 1, 1));
        assert!(
            ted.starts_with("<TED version=\"1.0\">")
                && ted.ends_with("</TED>")
                && !ted.contains("xmlns")
        );
        let pdf = boleta_80mm(&d, &ted).unwrap();
        assert!(pdf.starts_with(b"%PDF-1.3"));
        let t = texto_del_pdf(&pdf);
        assert!(t.contains("BOLETA ELECTR") && t.contains("$ 1.190") && t.contains("Caf"));
        assert!(
            t.matches(" re f").count() > 200,
            "el timbre va como rectángulos"
        );

        let raw = std::fs::read(format!("{base}/08_factura_descuentos/dte.xml")).unwrap();
        let (d, ted) = desde_xml(&raw).unwrap();
        let pdf = carta(
            &d,
            &ted,
            &Opciones {
                ambiente: "certificacion".into(),
                resolucion_fecha: "2026-07-08".into(),
                ..Default::default()
            },
        )
        .unwrap();
        let t = texto_del_pdf(&pdf);
        assert!(
            t.contains("FACTURA ELECTR") && t.contains("TOTAL:") && t.contains("Res. 0 de 2026")
        );
        assert!(t.contains("/F2 13.00 Tf"), "título en negrita 13");

        let png = timbre_png(&ted).unwrap();
        assert!(png.starts_with(b"\x89PNG"));
    }
}
