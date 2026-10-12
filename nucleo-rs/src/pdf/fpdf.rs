//! Un generador de PDF mínimo con la API de FPDF que usa `nucleo/pdf` (Go, go-pdf/fpdf):
//! páginas en mm con origen arriba a la izquierda, Helvetica y Helvetica-Bold (fuentes
//! estándar, WinAnsi), celdas, celdas multilínea con corte de palabras, líneas, rectángulos,
//! colores, guiones y salto de página automático. Sin dependencias fuera de flate2 (los
//! streams van comprimidos). No pretende ser FPDF entero: solo lo que el motor dibuja.

use super::helvetica::{HELVETICA, HELVETICA_BOLD};
use std::fmt::Write as _;
use std::io::Write as _;

const K: f64 = 72.0 / 25.4; // puntos por mm
const C_MARGIN: f64 = 1.0; // margen interior de las celdas, mm (FPDF)

#[derive(Clone, Copy, PartialEq, Eq)]
pub enum Align {
    L,
    C,
    R,
}

#[derive(Clone, Copy, PartialEq, Eq)]
pub enum Estilo {
    /// solo relleno
    F,
    /// solo borde
    D,
    /// relleno y borde
    FD,
}

pub struct Pdf {
    w: f64,
    h: f64,
    l_margin: f64,
    t_margin: f64,
    r_margin: f64,
    b_margin: f64,
    auto_pb: bool,
    pb_trigger: f64,
    x: f64,
    y: f64,
    lasth: f64,
    bold: bool,
    size_pt: f64,
    text_color: String,
    fill_color: String,
    draw_color: String,
    line_width: f64,
    dash: String,
    title: String,
    paginas: Vec<String>,
}

impl Pdf {
    /// Página de `w`×`h` mm (Carta: 215.9×279.4).
    pub fn new(w: f64, h: f64) -> Pdf {
        Pdf {
            w,
            h,
            l_margin: 10.0,
            t_margin: 10.0,
            r_margin: 10.0,
            b_margin: 20.0,
            auto_pb: true,
            pb_trigger: h - 20.0,
            x: 10.0,
            y: 10.0,
            lasth: 0.0,
            bold: false,
            size_pt: 12.0,
            text_color: "0 g".into(),
            fill_color: "0 g".into(),
            draw_color: "0 G".into(),
            line_width: 0.2,
            dash: String::new(),
            title: String::new(),
            paginas: Vec::new(),
        }
    }

    pub fn set_title(&mut self, t: &str) {
        self.title = t.to_string();
    }

    pub fn set_margins(&mut self, l: f64, t: f64, r: f64) {
        self.l_margin = l;
        self.t_margin = t;
        self.r_margin = r;
    }

    pub fn set_auto_page_break(&mut self, auto: bool, margen: f64) {
        self.auto_pb = auto;
        self.b_margin = margen;
        self.pb_trigger = self.h - margen;
    }

    fn out(&mut self, s: &str) {
        if let Some(p) = self.paginas.last_mut() {
            p.push_str(s);
            p.push('\n');
        }
    }

    pub fn add_page(&mut self) {
        self.paginas.push(String::new());
        self.x = self.l_margin;
        self.y = self.t_margin;
        // el estado gráfico es por página: se vuelve a emitir
        let (lw, dc, dash) = (self.line_width, self.draw_color.clone(), self.dash.clone());
        self.out(&format!("{:.2} w", lw * K));
        self.out(&dc);
        if !dash.is_empty() {
            self.out(&dash);
        }
    }

    pub fn set_font(&mut self, bold: bool, size_pt: f64) {
        self.bold = bold;
        self.size_pt = size_pt;
    }

    fn color(r: u8, g: u8, b: u8, op: &str) -> String {
        if r == g && g == b {
            format!("{:.3} {}", r as f64 / 255.0, op.to_lowercase())
        } else {
            format!(
                "{:.3} {:.3} {:.3} {}",
                r as f64 / 255.0,
                g as f64 / 255.0,
                b as f64 / 255.0,
                if op == "g" { "rg" } else { "RG" }
            )
        }
    }

    pub fn set_text_color(&mut self, r: u8, g: u8, b: u8) {
        self.text_color = Self::color(r, g, b, "g");
    }

    pub fn set_fill_color(&mut self, r: u8, g: u8, b: u8) {
        self.fill_color = Self::color(r, g, b, "g");
        let c = self.fill_color.clone();
        self.out(&c);
    }

    pub fn set_draw_color(&mut self, r: u8, g: u8, b: u8) {
        self.draw_color = Self::color(r, g, b, "G");
        let c = self.draw_color.clone();
        self.out(&c);
    }

    pub fn set_line_width(&mut self, w: f64) {
        self.line_width = w;
        self.out(&format!("{:.2} w", w * K));
    }

    /// `[a b] 0 d` en mm; `None` = línea continua.
    pub fn set_dash(&mut self, patron: Option<(f64, f64)>) {
        self.dash = match patron {
            Some((a, b)) => format!("[{:.3} {:.3}] 0 d", a * K, b * K),
            None => "[] 0 d".into(),
        };
        let d = self.dash.clone();
        self.out(&d);
    }

    pub fn get_x(&self) -> f64 {
        self.x
    }
    pub fn get_y(&self) -> f64 {
        self.y
    }
    pub fn set_x(&mut self, x: f64) {
        self.x = if x >= 0.0 { x } else { self.w + x };
    }
    pub fn set_y(&mut self, y: f64) {
        self.x = self.l_margin;
        self.y = if y >= 0.0 { y } else { self.h + y };
    }
    pub fn set_xy(&mut self, x: f64, y: f64) {
        self.set_y(y);
        self.set_x(x);
    }

    /// Salto de línea: `h < 0` usa el alto de la última celda.
    pub fn ln(&mut self, h: f64) {
        self.x = self.l_margin;
        self.y += if h < 0.0 { self.lasth } else { h };
    }

    fn widths(&self) -> &'static [u16; 256] {
        if self.bold {
            &HELVETICA_BOLD
        } else {
            &HELVETICA
        }
    }

    /// Ancho del texto en mm con la fuente actual.
    pub fn get_string_width(&self, s: &str) -> f64 {
        let w = self.widths();
        let total: u64 = cp1252(s).iter().map(|&b| w[b as usize] as u64).sum();
        total as f64 * self.size_pt / 1000.0 / K
    }

    pub fn line(&mut self, x1: f64, y1: f64, x2: f64, y2: f64) {
        let s = format!(
            "{:.2} {:.2} m {:.2} {:.2} l S",
            x1 * K,
            (self.h - y1) * K,
            x2 * K,
            (self.h - y2) * K
        );
        self.out(&s);
    }

    pub fn rect(&mut self, x: f64, y: f64, w: f64, h: f64, estilo: Estilo) {
        let op = match estilo {
            Estilo::F => "f",
            Estilo::D => "S",
            Estilo::FD => "B",
        };
        let s = format!(
            "{:.2} {:.2} {:.2} {:.2} re {}",
            x * K,
            (self.h - (y + h)) * K,
            w * K,
            h * K,
            op
        );
        self.out(&s);
    }

    fn texto(&mut self, x: f64, y: f64, s: &str) {
        let font = if self.bold { "/F2" } else { "/F1" };
        let mut b = String::new();
        // q … Q: el color del texto no debe pisar el color de relleno de los rectángulos que
        // vienen después (FPDF hace lo mismo cuando ColorFlag está activo).
        let _ = write!(
            b,
            "q {} BT {} {:.2} Tf {:.2} {:.2} Td (",
            self.text_color,
            font,
            self.size_pt,
            x * K,
            (self.h - y) * K
        );
        for &c in &cp1252(s) {
            match c {
                b'(' | b')' | b'\\' => {
                    b.push('\\');
                    b.push(c as char);
                }
                0x20..=0x7E => b.push(c as char),
                _ => {
                    let _ = write!(b, "\\{:03o}", c);
                }
            }
        }
        b.push_str(") Tj ET Q");
        self.out(&b);
    }

    /// `CellFormat(w, h, txt, border, ln, align, fill)`: `ln` 0 = sigue a la derecha, 1 = baja
    /// de línea (x al margen), 2 = baja de línea manteniendo x.
    #[allow(clippy::too_many_arguments)]
    pub fn cell(
        &mut self,
        w: f64,
        h: f64,
        txt: &str,
        border: bool,
        ln: u8,
        align: Align,
        fill: bool,
    ) {
        if self.auto_pb && self.y + h > self.pb_trigger && !self.paginas.is_empty() {
            let x = self.x;
            self.add_page();
            self.x = x;
        }
        let w = if w == 0.0 {
            self.w - self.r_margin - self.x
        } else {
            w
        };
        if fill || border {
            let estilo = match (fill, border) {
                (true, true) => Estilo::FD,
                (true, false) => Estilo::F,
                _ => Estilo::D,
            };
            self.rect(self.x, self.y, w, h, estilo);
        }
        if !txt.is_empty() {
            let sw = self.get_string_width(txt);
            let dx = match align {
                Align::L => C_MARGIN,
                Align::C => (w - sw) / 2.0,
                Align::R => w - C_MARGIN - sw,
            };
            let (x, y) = (self.x + dx, self.y + 0.5 * h + 0.3 * self.size_pt / K);
            self.texto(x, y, txt);
        }
        self.lasth = h;
        match ln {
            0 => self.x += w,
            1 => {
                self.y += h;
                self.x = self.l_margin;
            }
            _ => self.y += h,
        }
    }

    /// Corta `txt` en líneas que quepan en `w` mm (interior de celda), como `SplitText` de
    /// fpdf: por espacios, respetando los saltos de línea, partiendo palabras largas.
    pub fn split_text(&self, txt: &str, w: f64) -> Vec<String> {
        let wmax = (w - 2.0 * C_MARGIN) * 1000.0 * K / self.size_pt; // en milésimas de em
        let widths = self.widths();
        let mut lineas = Vec::new();
        for parrafo in txt.replace("\r\n", "\n").split('\n') {
            let chars: Vec<char> = parrafo.chars().collect();
            let anchos: Vec<f64> = cp1252(parrafo)
                .iter()
                .map(|&b| widths[b as usize] as f64)
                .collect();
            let (mut i, mut j, mut l, mut sep) = (0usize, 0usize, 0.0f64, None::<usize>);
            if chars.is_empty() {
                lineas.push(String::new());
                continue;
            }
            while i < chars.len() {
                let c = chars[i];
                l += anchos[i];
                if c == ' ' {
                    sep = Some(i);
                }
                if l > wmax {
                    match sep {
                        None => {
                            if i == j {
                                i += 1;
                            }
                            lineas.push(chars[j..i].iter().collect());
                        }
                        Some(s) => {
                            lineas.push(chars[j..s].iter().collect());
                            i = s + 1;
                        }
                    }
                    sep = None;
                    j = i;
                    l = 0.0;
                } else {
                    i += 1;
                }
            }
            if i != j {
                lineas.push(chars[j..i].iter().collect());
            }
        }
        lineas
    }

    /// `MultiCell(w, h, txt, "", align, fill)`: una celda por línea, y al final x vuelve al
    /// margen izquierdo.
    pub fn multi_cell(&mut self, w: f64, h: f64, txt: &str, align: Align, fill: bool) {
        let w = if w == 0.0 {
            self.w - self.r_margin - self.x
        } else {
            w
        };
        let x0 = self.x;
        for l in self.split_text(txt, w) {
            self.x = x0;
            self.cell(w, h, &l, false, 2, align, fill);
        }
        self.x = self.l_margin;
    }

    /// El archivo PDF (1.3; streams con FlateDecode).
    pub fn output(&self) -> Vec<u8> {
        let mut objs: Vec<Vec<u8>> = Vec::new();
        // 1 catálogo, 2 páginas, 3 F1, 4 F2, 5 info, luego (página, contenido)×n
        let n = self.paginas.len();
        let kids: Vec<String> = (0..n).map(|i| format!("{} 0 R", 6 + 2 * i)).collect();
        objs.push(b"<< /Type /Catalog /Pages 2 0 R >>".to_vec());
        objs.push(
            format!("<< /Type /Pages /Kids [{}] /Count {} >>", kids.join(" "), n).into_bytes(),
        );
        objs.push(
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"
                .to_vec(),
        );
        objs.push(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>".to_vec());
        let mut titulo = Vec::new();
        for &c in &cp1252(&self.title) {
            if matches!(c, b'(' | b')' | b'\\') {
                titulo.push(b'\\');
            }
            titulo.push(c);
        }
        let mut info = b"<< /Producer (DTE Chile nucleo-rs) /Title (".to_vec();
        info.extend(titulo);
        info.extend(b") >>");
        objs.push(info);
        for (i, contenido) in self.paginas.iter().enumerate() {
            let pid = 6 + 2 * i;
            objs.push(
                format!(
                    "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {:.2} {:.2}] /Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> /Contents {} 0 R >>",
                    self.w * K,
                    self.h * K,
                    pid + 1
                )
                .into_bytes(),
            );
            let mut enc =
                flate2::write::ZlibEncoder::new(Vec::new(), flate2::Compression::default());
            let _ = enc.write_all(contenido.as_bytes());
            let comprimido = enc.finish().unwrap_or_default();
            let mut s = format!(
                "<< /Length {} /Filter /FlateDecode >>\nstream\n",
                comprimido.len()
            )
            .into_bytes();
            s.extend(comprimido);
            s.extend(b"\nendstream");
            objs.push(s);
        }
        let mut out = b"%PDF-1.3\n%\xE2\xE3\xCF\xD3\n".to_vec();
        let mut offsets = Vec::with_capacity(objs.len());
        for (i, o) in objs.iter().enumerate() {
            offsets.push(out.len());
            out.extend(format!("{} 0 obj\n", i + 1).into_bytes());
            out.extend(o);
            out.extend(b"\nendobj\n");
        }
        let xref = out.len();
        out.extend(format!("xref\n0 {}\n0000000000 65535 f \n", objs.len() + 1).into_bytes());
        for off in offsets {
            out.extend(format!("{off:010} 00000 n \n").into_bytes());
        }
        out.extend(
            format!(
                "trailer\n<< /Size {} /Root 1 0 R /Info 5 0 R >>\nstartxref\n{}\n%%EOF\n",
                objs.len() + 1,
                xref
            )
            .into_bytes(),
        );
        out
    }
}

/// UTF-8 → Windows-1252 (lo que FPDF llama `UnicodeTranslatorFromDescriptor("")`): lo que no
/// existe en cp1252 sale como '?'.
pub fn cp1252(s: &str) -> Vec<u8> {
    s.chars()
        .map(|c| match c as u32 {
            0..=0x7F | 0xA0..=0xFF => c as u8,
            0x20AC => 0x80,
            0x201A => 0x82,
            0x0192 => 0x83,
            0x201E => 0x84,
            0x2026 => 0x85,
            0x2020 => 0x86,
            0x2021 => 0x87,
            0x02C6 => 0x88,
            0x2030 => 0x89,
            0x0160 => 0x8A,
            0x2039 => 0x8B,
            0x0152 => 0x8C,
            0x017D => 0x8E,
            0x2018 => 0x91,
            0x2019 => 0x92,
            0x201C => 0x93,
            0x201D => 0x94,
            0x2022 => 0x95,
            0x2013 => 0x96,
            0x2014 => 0x97,
            0x02DC => 0x98,
            0x2122 => 0x99,
            0x0161 => 0x9A,
            0x203A => 0x9B,
            0x0153 => 0x9C,
            0x017E => 0x9E,
            0x0178 => 0x9F,
            _ => b'?',
        })
        .collect()
}
