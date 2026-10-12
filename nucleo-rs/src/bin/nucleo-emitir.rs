//! nucleo-emitir: emite un documento con el núcleo en Rust contra la base y el storage del
//! motor. Lee el documento en JSON por stdin y escribe el resultado en JSON.
//!
//!     nucleo-emitir --db dte_database.db --storage storage --cert firma.p12 --ambiente certificacion \
//!                   --resolucion-fecha 2026-07-08 --resolucion-numero 0 < documento.json
//!
//! La clave del certificado va en NUCLEO_CERT_CLAVE (nunca como argumento). RELOJ_FIJO fija la
//! hora (solo pruebas). No genera PDF ni envía al SII.

use dtechile::almacen::Almacen;
use dtechile::cliutil::{fatal, Flags};
use dtechile::emision;
use std::io::Read;

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let f = Flags::parsear(&args, &[]);
    let mut raw = Vec::new();
    std::io::stdin()
        .read_to_end(&mut raw)
        .unwrap_or_else(|e| fatal("nucleo-emitir", e));
    let doc = emision::documento_desde_json(&raw).unwrap_or_else(|e| fatal("nucleo-emitir", e));
    let (cert, db, storage, amb, fr, nr) = if !f.texto("contexto", "").is_empty() {
        let cj =
            std::fs::read(f.texto("contexto", "")).unwrap_or_else(|e| fatal("nucleo-emitir", e));
        let c = emision::contexto_desde_json(&cj).unwrap_or_else(|e| fatal("nucleo-emitir", e));
        (
            c.cert,
            c.database_path,
            c.storage_path,
            c.ambiente,
            c.fecha_resolucion,
            c.numero_resolucion,
        )
    } else {
        let (cert_path, fr) = (f.texto("cert", ""), f.texto("resolucion-fecha", ""));
        if cert_path.is_empty() || fr.is_empty() {
            fatal(
                "nucleo-emitir",
                "faltan --cert y/o --resolucion-fecha (o --contexto)",
            );
        }
        let p12 = std::fs::read(&cert_path).unwrap_or_else(|e| fatal("nucleo-emitir", e));
        let cert = dtechile::firma::cargar_p12(
            &p12,
            &std::env::var("NUCLEO_CERT_CLAVE").unwrap_or_default(),
        )
        .unwrap_or_else(|e| fatal("nucleo-emitir", e));
        (
            cert,
            f.texto("db", "dte_database.db"),
            f.texto("storage", "storage"),
            f.texto("ambiente", "certificacion"),
            fr,
            f.entero("resolucion-numero", 0),
        )
    };
    let alm = Almacen::abrir(&db).unwrap_or_else(|e| fatal("nucleo-emitir", e));
    let marca = std::env::var("RELOJ_FIJO")
        .ok()
        .filter(|m| !m.is_empty())
        .unwrap_or_else(|| dtechile::almacen::ahora_iso()[..19].to_string());
    let ctx = emision::Contexto {
        almacen: &alm,
        cert: &cert,
        storage_base: storage,
        ambiente: amb,
        fecha_resolucion: fr,
        numero_resolucion: nr,
        marca,
        validar: false,
    };
    let res = emision::emitir(&ctx, doc).unwrap_or_else(|e| fatal("nucleo-emitir", e));
    println!("{}", serde_json::to_string(&res).unwrap_or_default());
}
