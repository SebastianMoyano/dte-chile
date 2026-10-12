//! nucleo-cafs: los CAF de la base, como load_cafs.py.
//!
//!     nucleo-cafs listar [--db dte_database.db]
//!     nucleo-cafs cargar [--dir storage/cafs] [--db dte_database.db]   (salta los ya cargados)

use dtechile::almacen::Almacen;
use dtechile::cliutil::{fatal, Flags};
use dtechile::ted;

fn tabla(alm: &Almacen, titulo: &str) {
    let c = alm.conexion();
    let mut st = c.prepare("SELECT id, rut_emisor, tipo_dte, folio_desde, folio_hasta, folio_siguiente, activo FROM cafs ORDER BY id").unwrap_or_else(|e| fatal("error", e));
    println!(
        "\n{titulo}\n{:<4}  {:<12} {:>5}  {:>6}  {:>6}  {:>6}  ACTIVO",
        "ID", "RUT", "TIPO", "DESDE", "HASTA", "SIG"
    );
    let mut n = 0;
    let filas = st
        .query_map([], |r| {
            Ok((
                r.get::<_, i64>(0)?,
                r.get::<_, String>(1)?,
                r.get::<_, i64>(2)?,
                r.get::<_, i64>(3)?,
                r.get::<_, i64>(4)?,
                r.get::<_, i64>(5)?,
                r.get::<_, i64>(6)?,
            ))
        })
        .unwrap_or_else(|e| fatal("error", e));
    for f in filas.flatten() {
        println!(
            "{:<4}  {:<12} {:>5}  {:>6}  {:>6}  {:>6}  {}",
            f.0, f.1, f.2, f.3, f.4, f.5, f.6
        );
        n += 1;
    }
    if n == 0 {
        println!("  (vacío)");
    }
}

fn main() {
    let mut args: Vec<String> = std::env::args().skip(1).collect();
    let mut cmd = "listar".to_string();
    if let Some(a) = args.first() {
        if a == "listar" || a == "cargar" {
            cmd = a.clone();
            args.remove(0);
        }
    }
    let f = Flags::parsear(&args, &[]);
    let alm = Almacen::abrir_y_migrar(&f.texto("db", "dte_database.db"))
        .unwrap_or_else(|e| fatal("error", e));
    if cmd == "listar" {
        tabla(&alm, "CAF EN LA BASE");
        return;
    }
    let dir = f.texto("dir", "storage/cafs");
    let mut archivos: Vec<std::path::PathBuf> = std::fs::read_dir(&dir)
        .map(|d| {
            d.flatten()
                .map(|e| e.path())
                .filter(|p| p.extension().map(|x| x == "xml").unwrap_or(false))
                .collect()
        })
        .unwrap_or_default();
    archivos.sort();
    if archivos.is_empty() {
        fatal("error", format!("no hay *.xml en {dir}"));
    }
    tabla(&alm, "ESTADO ANTES DE LA CARGA");
    let (mut ins, mut salt) = (0, 0);
    for a in &archivos {
        let base = a
            .file_name()
            .map(|n| n.to_string_lossy().into_owned())
            .unwrap_or_default();
        let b = match std::fs::read(a) {
            Ok(b) => b,
            Err(e) => {
                println!("✗ {base}: {e}");
                continue;
            }
        };
        let txt = String::from_utf8_lossy(&b).into_owned();
        let c = match ted::parsear_caf(&txt) {
            Ok(c) => c,
            Err(e) => {
                println!("✗ {base}: {e}");
                continue;
            }
        };
        let ya: Option<i64> = {
            use rusqlite::OptionalExtension;
            let con = alm.conexion();
            con.query_row(
                "SELECT id FROM cafs WHERE rut_emisor=? AND tipo_dte=? AND folio_desde=?",
                rusqlite::params![c.rut_emisor, c.tipo_dte, c.folio_desde],
                |r| r.get(0),
            )
            .optional()
            .unwrap_or(None)
        };
        if let Some(id) = ya {
            println!(
                "· {base}: T{} {}-{} de {} ya está (id {id})",
                c.tipo_dte, c.folio_desde, c.folio_hasta, c.rut_emisor
            );
            salt += 1;
            continue;
        }
        match alm.registrar_caf(
            c.tipo_dte,
            &c.rut_emisor,
            c.folio_desde,
            c.folio_hasta,
            &c.fecha_autorizacion,
            &txt,
        ) {
            Ok(id) => {
                println!(
                    "✓ {base}: T{} {}-{} de {} (FA {}) → id {id}",
                    c.tipo_dte, c.folio_desde, c.folio_hasta, c.rut_emisor, c.fecha_autorizacion
                );
                ins += 1;
            }
            Err(e) => println!("✗ {base}: {e}"),
        }
    }
    tabla(&alm, "ESTADO DESPUÉS DE LA CARGA");
    println!("\ninsertados {ins}, saltados {salt}");
}
