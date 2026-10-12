//! nucleo-rvd: el Registro de Ventas Diario (ConsumoFolios) de boletas desde la terminal.
//!
//!     nucleo-rvd --rut 77777777-7 --dia 2026-01-23 --cert firma.pfx [--db dte_database.db] [--ambiente certificacion]
//!     nucleo-rvd --rut … --dia … --cert-id 2 [--cuenta 1] [--env .env]      (certificado del keystore)
//!     nucleo-rvd … --enviar          (lo sube por DTEUpload al ambiente elegido y lo registra en rvd_envios)
//!
//! Sin --enviar solo genera, valida contra el XSD y escribe storage/rvd/RVD_<rut>_<dia>.xml.
//! La clave del certificado: NUCLEO_CLAVE_CERTIFICADO o el Llavero.

use dtechile::almacen::Almacen;
use dtechile::cliutil::{cargar_certificado, fatal, Flags};
use dtechile::rvd;
use dtechile::servidor::rvd::sumar_dias;
use dtechile::sii;

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let f = Flags::parsear(&args, &["enviar"]);
    let rut = f.texto("rut", "");
    if rut.is_empty() {
        fatal("error", "falta --rut");
    }
    let hoy = dtechile::almacen::ahora_iso()[..10].to_string();
    let dia = f.texto("dia", &sumar_dias(&hoy, -1));
    let db = f.texto("db", "dte_database.db");
    let ambiente = f.texto("ambiente", "certificacion");
    let cert = cargar_certificado(
        &f.texto("cert", &std::env::var("DTE_CERT_PATH").unwrap_or_default()),
        f.entero("cert-id", 0),
        f.entero("cuenta", 1),
        &f.texto("env", ".env"),
        &db,
    )
    .unwrap_or_else(|e| fatal("error", format!("certificado: {e}")));
    let rut_envia = cert.rut_emisor().unwrap_or_else(|e| fatal("error", e));
    let alm = Almacen::abrir_y_migrar(&db).unwrap_or_else(|e| fatal("error", e));
    let docs =
        rvd::boletas_del_dia(&alm, &rut, &dia, &ambiente).unwrap_or_else(|e| fatal("error", e));
    // Resolución POR EMPRESA (la cacheada del registro del SII); si no, la del ambiente.
    let (mut fecha, mut num) = if ambiente == "produccion" {
        ("2014-08-22".to_string(), 80i64)
    } else {
        ("2026-07-08".to_string(), 0)
    };
    {
        use rusqlite::OptionalExtension;
        let c = alm.conexion();
        if let Ok(Some((fc, nc))) = c
            .query_row(
                "SELECT fecha_iso, numero FROM resolucion_cache WHERE rut=? AND ambiente=?",
                rusqlite::params![rut, ambiente],
                |r| Ok((r.get::<_, String>(0)?, r.get::<_, i64>(1)?)),
            )
            .optional()
        {
            fecha = fc;
            num = nc;
        }
    }
    let resol = f.texto("resolucion", "");
    if let Some((fr, nr)) = resol.split_once(':') {
        fecha = fr.to_string();
        num = nr.trim().parse().unwrap_or(num);
    }
    let sec = f.entero("sec", 1) as i32;
    let xml = rvd::generar_firmado(
        &cert,
        &rvd::Parametros {
            rut_emisor: rut.clone(),
            rut_envia,
            fecha_resolucion: fecha,
            numero_resolucion: num,
            dia: dia.clone(),
            tipos: rvd::TIPOS_CONSUMO.to_vec(),
            sec_envio: sec,
            marca: dtechile::almacen::ahora_iso()[..19].to_string(),
            documentos: docs.clone(),
            ..Default::default()
        },
    )
    .unwrap_or_else(|e| fatal("error", e));
    let salida = f.texto("salida", "storage/rvd");
    let _ = std::fs::create_dir_all(&salida);
    let ruta = format!("{salida}/RVD_{rut}_{dia}.xml");
    std::fs::write(&ruta, &xml).unwrap_or_else(|e| fatal("error", e));
    println!(
        "RVD de {rut} para {dia}: {} boleta(s) del día, XSD válido → {ruta} ({} bytes)",
        docs.len(),
        xml.len()
    );
    if !f.logico("enviar") {
        let _ = rvd::registrar(
            &alm,
            &rut,
            &dia,
            "generado",
            sec,
            "",
            &ruta,
            "Generado por nucleo-rvd (sin enviar).",
        );
        return;
    }
    let mut cli = sii::http::Cliente::nuevo(&ambiente, cert).unwrap_or_else(|e| fatal("error", e));
    match rvd::enviar(&mut cli, &xml, &rut) {
        Err(e) => {
            let _ = rvd::registrar(&alm, &rut, &dia, "generado", sec, "", &ruta, &e);
            fatal("error", format!("generado pero NO enviado: {e}"));
        }
        Ok((track, _)) => {
            let _ = rvd::registrar(
                &alm,
                &rut,
                &dia,
                "enviado",
                sec,
                &track.to_string(),
                &ruta,
                &format!("Enviado por DTEUpload ({ambiente})."),
            );
            println!("📤 enviado por DTEUpload ({ambiente}) → TrackID {track}. Consulta el veredicto con: nucleo-sii estado --track {track} --rut {rut} --ambiente {ambiente} --cert …");
        }
    }
}
