//! nucleo-pdf: dibuja la representación gráfica de un DTE desde su XML firmado.
//!
//!     nucleo-pdf --xml storage/dtes/DTE_33_1.xml --salida /tmp/doc.pdf [--ambiente simulacion] [--resolucion 2026-01-01:0] [--hoy 2026-10-11]
//!     nucleo-pdf --xml … --json            (solo imprime el documento reconstruido y el TED, sin PDF)
//!     nucleo-pdf --xml … --timbre-png t.png (solo el PDF417 del TED como PNG, para verificar)
//!
//! Boletas (39/41) salen en 80 mm; el resto en carta. El TED va al PDF417 verbatim. Mismo
//! contrato que `nucleo/cmd/nucleo-pdf` (Go).

use dtechile::pdf;
use std::io::Write;

fn fatal<T>(e: impl std::fmt::Display) -> T {
    eprintln!("error: {e}");
    std::process::exit(1)
}

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let mut xml = String::new();
    let mut salida = String::new();
    let mut ambiente = "certificacion".to_string();
    let mut resol = "2026-07-08:0".to_string();
    let mut hoy = String::new();
    let mut solo_json = false;
    let mut timbre = String::new();
    let mut i = 0;
    while i < args.len() {
        let a = args[i].as_str();
        let valor = |i: &mut usize| -> String {
            *i += 1;
            args.get(*i)
                .cloned()
                .unwrap_or_else(|| fatal(format!("falta el valor de {a}")))
        };
        match a {
            "--xml" => xml = valor(&mut i),
            "--salida" => salida = valor(&mut i),
            "--ambiente" => ambiente = valor(&mut i),
            "--resolucion" => resol = valor(&mut i),
            "--hoy" => hoy = valor(&mut i),
            "--timbre-png" => timbre = valor(&mut i),
            "--json" => solo_json = true,
            otro => fatal(format!("opción desconocida: {otro}")),
        }
        i += 1;
    }
    if xml.is_empty() {
        eprintln!("falta --xml");
        std::process::exit(2);
    }
    let raw = std::fs::read(&xml).unwrap_or_else(fatal);
    let (d, ted) = pdf::desde_xml(&raw).unwrap_or_else(fatal);
    if !timbre.is_empty() {
        let b = pdf::timbre_png(&ted).unwrap_or_else(fatal);
        std::fs::write(&timbre, b).unwrap_or_else(fatal);
        return;
    }
    if solo_json {
        let j = serde_json::json!({ "documento": d, "ted": ted });
        println!("{}", serde_json::to_string_pretty(&j).unwrap_or_default());
        return;
    }
    let (fecha, num) = resol.split_once(':').unwrap_or((resol.as_str(), "0"));
    let num: i64 = num.parse().unwrap_or(0);
    let b = if d.tipo_dte == 39 || d.tipo_dte == 41 {
        pdf::boleta_80mm(&d, &ted)
    } else {
        pdf::carta(
            &d,
            &ted,
            &pdf::Opciones {
                ambiente,
                resolucion_fecha: fecha.to_string(),
                resolucion_num: num,
                hoy,
            },
        )
    }
    .unwrap_or_else(fatal);
    if salida.is_empty() {
        let _ = std::io::stdout().write_all(&b);
        return;
    }
    std::fs::write(&salida, &b).unwrap_or_else(fatal);
    eprintln!("PDF: {salida} ({} bytes)", b.len());
}
