//! nucleo-certificacion: el Set de Pruebas del SII (16 casos) con el núcleo Rust, como
//! dry_run_certificacion.py (sin red) y certificacion_sii.py (--enviar).
//!
//!     nucleo-certificacion --rut 77777777-7 --razon-social "EMPRESA DEMO SPA" --cert firma.pfx --cafs storage/cafs
//!     nucleo-certificacion … --enviar --ambiente certificacion      (sube cada sobre por DTEUpload: gasta folios)
//!
//! Salida: <salida>/dtes_cert/<caso>_T<tipo>_F<folio>.xml, <salida>/pdfs_cert/…pdf y
//! <salida>/resultados_certificacion_rust.json. --fecha y --marca fijan fecha y hora.

use dtechile::certificacion;
use dtechile::cliutil::{cargar_certificado, fatal, Flags};
use dtechile::pdf;
use dtechile::sii;
use dtechile::ted;
use dtechile::xsd;
use std::collections::BTreeMap;

fn env_o(k: &str, def: &str) -> String {
    std::env::var(k)
        .ok()
        .filter(|v| !v.is_empty())
        .unwrap_or_else(|| def.to_string())
}

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let f = Flags::parsear(&args, &["enviar"]);
    let rut = f.texto("rut", &env_o("DTE_RUT_EMPRESA", "76111111-6"));
    let razon = f.texto(
        "razon-social",
        &env_o("DTE_RAZON_SOCIAL", "EMPRESA DEMO SPA"),
    );
    let email = f.texto("email", &env_o("DTE_EMAIL", "contacto@ejemplo.cl"));
    let ahora = dtechile::almacen::ahora_iso();
    let fecha = f.texto("fecha", &ahora[..10]);
    let marca = f.texto("marca", &ahora[..19]);
    let ambiente = f.texto("ambiente", "certificacion");
    let enviar = f.logico("enviar");
    let cert = cargar_certificado(
        &f.texto("cert", &env_o("DTE_CERT_PATH", "firma.pfx")),
        f.entero("cert-id", 0),
        f.entero("cuenta", 1),
        &f.texto("env", ".env"),
        &f.texto("db", ""),
    )
    .unwrap_or_else(|e| fatal("error", format!("certificado: {e}")));
    println!(
        "✅ Certificado cargado: {}",
        cert.rut_emisor().unwrap_or_default()
    );
    let cafs_dir = f.texto("cafs", "storage/cafs");
    let mut por_tipo: BTreeMap<i32, ted::Caf> = BTreeMap::new();
    let mut archivos: Vec<_> = std::fs::read_dir(&cafs_dir)
        .map(|d| {
            d.flatten()
                .map(|e| e.path())
                .filter(|p| p.extension().map(|x| x == "xml").unwrap_or(false))
                .collect::<Vec<_>>()
        })
        .unwrap_or_default();
    archivos.sort();
    for a in archivos {
        let Ok(b) = std::fs::read(&a) else { continue };
        let base = a
            .file_name()
            .map(|n| n.to_string_lossy().into_owned())
            .unwrap_or_default();
        match ted::parsear_caf(&String::from_utf8_lossy(&b)) {
            Ok(c) => {
                println!(
                    "  ✅ CAF T{}: folios {}-{} ({base})",
                    c.tipo_dte, c.folio_desde, c.folio_hasta
                );
                por_tipo.insert(c.tipo_dte, c);
            }
            Err(e) => println!("  ✗ {base}: {e}"),
        }
    }
    for t in [33, 34, 56, 61] {
        if !por_tipo.contains_key(&t) {
            fatal("error", format!("falta CAF para T{t} en {cafs_dir}"));
        }
    }
    let casos = certificacion::casos().unwrap_or_else(|e| fatal("error", e));
    let salida = f.texto("salida", "storage");
    let (dtes, pdfs) = (format!("{salida}/dtes_cert"), format!("{salida}/pdfs_cert"));
    let _ = std::fs::create_dir_all(&dtes);
    let _ = std::fs::create_dir_all(&pdfs);
    let mut cli = if enviar {
        Some(
            sii::http::Cliente::nuevo(&ambiente, cert.clone())
                .unwrap_or_else(|e| fatal("error", e)),
        )
    } else {
        None
    };
    let e = certificacion::Emisor {
        rut: rut.clone(),
        razon_social: razon,
        email,
    };
    let mut res: Vec<serde_json::Value> = Vec::new();
    println!(
        "\n📋 {} casos del Set de Pruebas (fecha {fecha})",
        casos.len()
    );
    for (i, c) in casos.iter().enumerate() {
        print!(
            "[{:>2}/{}] {:<12} T{} F{:<3} ",
            i + 1,
            casos.len(),
            c.nombre,
            c.tipo_dte,
            c.folio
        );
        let mut r = serde_json::json!({"caso": c.nombre, "tipo_dte": c.tipo_dte, "folio": c.folio, "xml_ok": false, "xsd_ok": false, "pdf_ok": false, "estado": "generado"});
        let (envio, firmado) =
            match certificacion::generar(c, &e, &por_tipo[&c.tipo_dte], &cert, &fecha, &marca) {
                Ok(v) => v,
                Err(er) => {
                    println!("✗ {er}");
                    r["error"] = serde_json::json!(er);
                    r["estado"] = serde_json::json!("error");
                    res.push(r);
                    continue;
                }
            };
        r["xml_ok"] = serde_json::json!(true);
        if let Err(er) = xsd::validar_error(&envio) {
            println!("✗ XSD: {er}");
            r["error"] = serde_json::json!(er);
            r["estado"] = serde_json::json!("error");
            res.push(r);
            continue;
        }
        r["xsd_ok"] = serde_json::json!(true);
        let nombre = certificacion::nombre_archivo(c);
        std::fs::write(format!("{dtes}/{nombre}.xml"), &envio)
            .unwrap_or_else(|er| fatal("error", er));
        let mut pdf_ok = false;
        if let Ok(raw) = ted::latin1(&firmado) {
            if let Ok((doc, ted_xml)) = pdf::desde_xml(&raw) {
                if let Ok(b) = pdf::carta(
                    &doc,
                    &ted_xml,
                    &pdf::Opciones {
                        ambiente: ambiente.clone(),
                        resolucion_fecha: certificacion::FECHA_RESOLUCION.into(),
                        resolucion_num: certificacion::NUMERO_RESOLUCION,
                        hoy: fecha.clone(),
                    },
                ) {
                    let _ = std::fs::write(format!("{pdfs}/{nombre}.pdf"), b);
                    pdf_ok = true;
                }
            }
        }
        r["pdf_ok"] = serde_json::json!(pdf_ok);
        print!(
            "✓XML ✓XSD {}PDF ({} bytes)",
            if pdf_ok { "✓" } else { "✗" },
            envio.len()
        );
        if let Some(cl) = cli.as_mut() {
            let (n, dv) = rut.split_once('-').unwrap_or((&rut, ""));
            match cl.enviar_dte(&envio, n, dv) {
                Err(er) => {
                    r["error"] = serde_json::json!(er.to_string());
                    r["estado"] = serde_json::json!("error");
                    print!("  ✗ envío: {er}");
                }
                Ok((track, _)) => {
                    r["track_id"] = serde_json::json!(track);
                    r["estado"] = serde_json::json!("enviado");
                    print!("  📤 TrackID {track}");
                }
            }
        }
        println!();
        res.push(r);
    }
    let ok = res
        .iter()
        .filter(|r| {
            r["xml_ok"] == true
                && r["xsd_ok"] == true
                && r["pdf_ok"] == true
                && r.get("error").is_none()
        })
        .count();
    let ruta = format!("{salida}/resultados_certificacion_rust.json");
    let _ = std::fs::write(
        &ruta,
        serde_json::to_string_pretty(&res).unwrap_or_default(),
    );
    println!(
        "\n✅ Casos OK (XML+XSD+PDF{}): {ok}/{} — resultados en {ruta}",
        if enviar { "+envío" } else { "" },
        res.len()
    );
    if ok != res.len() {
        std::process::exit(1);
    }
}
