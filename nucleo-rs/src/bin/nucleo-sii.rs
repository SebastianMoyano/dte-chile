//! nucleo-sii: el cliente SII del núcleo, para probarlo contra Maullín/Palena.
//!
//!     nucleo-sii token   --ambiente certificacion --cert firma.pfx | --cert-id 2   (clave: NUCLEO_CLAVE_CERTIFICADO/Llavero)
//!     nucleo-sii estado  --track 261542052 --rut 77777777-7 --ambiente certificacion --cert …
//!     nucleo-sii enviar  --archivo storage/dtes/EnvioDTE_34_112.xml --rut 77777777-7 --ambiente … --cert …
//!     nucleo-sii boleta-enviar --archivo storage/dtes/EnvioBOLETA_39_1.xml --rut … --ambiente … --cert …   (REST de boletas)
//!     nucleo-sii boleta-estado --track 1234567890123456 --rut … --ambiente … --cert …

use dtechile::cliutil::{cargar_certificado, fatal, Flags};
use dtechile::sii;

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let Some(cmd) = args.first().cloned() else {
        eprintln!("uso: nucleo-sii token|estado|enviar|boleta-enviar|boleta-estado [opciones]");
        std::process::exit(2);
    };
    let f = Flags::parsear(&args[1..], &[]);
    let amb = f.texto("ambiente", sii::CERTIFICACION);
    let cert = cargar_certificado(
        &f.texto("cert", ""),
        f.entero("cert-id", 0),
        f.entero("cuenta", 1),
        &f.texto("env", ".env"),
        &f.texto("db", ""),
    )
    .unwrap_or_else(|e| fatal("nucleo-sii", e));
    let rut = f.texto("rut", "");
    let (rut_n, dv) = match rut.split_once('-') {
        Some((a, b)) => (a.to_string(), b.to_string()),
        None if rut.is_empty() => (String::new(), String::new()),
        None => fatal("nucleo-sii", "--rut con DV: 77777777-7"),
    };
    let track = f.entero("track", 0);
    let archivo = f.texto("archivo", "");
    match cmd.as_str() {
        "token" => {
            let mut cli =
                sii::http::Cliente::nuevo(&amb, cert).unwrap_or_else(|e| fatal("nucleo-sii", e));
            let t = cli.token().unwrap_or_else(|e| fatal("nucleo-sii", e));
            println!(
                "{{\"token_obtenido\": true, \"largo\": {}, \"ambiente\": \"{amb}\"}}",
                t.len()
            );
        }
        "estado" => {
            if track == 0 || rut_n.is_empty() {
                fatal("nucleo-sii", "faltan --track y --rut");
            }
            let mut cli =
                sii::http::Cliente::nuevo(&amb, cert).unwrap_or_else(|e| fatal("nucleo-sii", e));
            let e = cli
                .estado_track(track, &rut_n, &dv)
                .unwrap_or_else(|e| fatal("nucleo-sii", e));
            println!("{}", serde_json::to_string(&e).unwrap_or_default());
        }
        "enviar" => {
            if archivo.is_empty() || rut_n.is_empty() {
                fatal("nucleo-sii", "faltan --archivo y --rut");
            }
            let xml = std::fs::read(&archivo).unwrap_or_else(|e| fatal("nucleo-sii", e));
            let mut cli =
                sii::http::Cliente::nuevo(&amb, cert).unwrap_or_else(|e| fatal("nucleo-sii", e));
            let (tr, _) = cli
                .enviar_dte(&xml, &rut_n, &dv)
                .unwrap_or_else(|e| fatal("nucleo-sii", e));
            println!("{{\"track_id\": {tr}, \"mensaje\": \"Envío exitoso\"}}");
        }
        "boleta-enviar" => {
            if archivo.is_empty() || rut_n.is_empty() {
                fatal("nucleo-sii", "faltan --archivo y --rut");
            }
            let xml = std::fs::read(&archivo).unwrap_or_else(|e| fatal("nucleo-sii", e));
            let mut cb = sii::boleta::ClienteBoleta::nuevo(&amb, cert)
                .unwrap_or_else(|e| fatal("nucleo-sii", e));
            let (tr, resp) = cb
                .enviar(&xml, &rut_n, &dv)
                .unwrap_or_else(|e| fatal("nucleo-sii", e));
            println!(
                "{}",
                serde_json::json!({"track_id": tr, "respuesta": resp, "ambiente": amb})
            );
        }
        "boleta-estado" => {
            let mut tk = f.texto("track-boleta", "");
            if tk.is_empty() && track != 0 {
                tk = track.to_string();
            }
            if tk.is_empty() || rut_n.is_empty() {
                fatal("nucleo-sii", "faltan --track-boleta (o --track) y --rut");
            }
            let mut cb = sii::boleta::ClienteBoleta::nuevo(&amb, cert)
                .unwrap_or_else(|e| fatal("nucleo-sii", e));
            let e = cb
                .estado(&tk, &rut_n, &dv)
                .unwrap_or_else(|e| fatal("nucleo-sii", e));
            println!("{}", serde_json::to_string(&e).unwrap_or_default());
        }
        _ => fatal("nucleo-sii", format!("subcomando desconocido {cmd:?}")),
    }
}
