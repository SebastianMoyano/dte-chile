//! nucleo-valores: trae los indicadores públicos del SII (UF, UTM, dólar) y los cachea en el
//! SQLite del motor. Fuente primaria oficial (SII), fallback mindicador.cl.
//!
//!     nucleo-valores actualizar --indicador todos --anio 2026 --db dte_database.db
//!     nucleo-valores get        --indicador uf --fecha 2026-10-08 --db dte_database.db
//!     nucleo-valores vigente    --indicador uf --fecha 2026-10-08 --db dte_database.db
//!     nucleo-valores demonio    --cada 24h --db dte_database.db
//!     nucleo-valores historico  --desde 2015 --db dte_database.db     (una sola vez)

use dtechile::cliutil::{fatal, Flags};
use dtechile::valores::{self, Cache};

fn anio_actual() -> i32 {
    dtechile::almacen::ahora_iso()[..4].parse().unwrap_or(2026)
}

fn refrescar(db: &str, anio: i32, inds: &[&str], logf: &dyn Fn(&str)) {
    let c = match Cache::abrir(db) {
        Ok(c) => c,
        Err(e) => {
            logf(&format!("valores: no se pudo abrir {db}: {e}"));
            return;
        }
    };
    for ind in inds {
        match valores::fetch(ind, anio) {
            Err(e) => logf(&format!("valores: {ind} {anio} falló: {e}")),
            Ok((vs, fuente)) => match c.guardar(&vs) {
                Err(e) => logf(&format!("valores: {ind} {anio} no se guardó: {e}")),
                Ok(n) => logf(&format!(
                    "valores: {ind} {anio} → {n} valores (fuente: {fuente})"
                )),
            },
        }
    }
}

/// "24h", "30m", "90s" → segundos.
fn duracion(s: &str) -> u64 {
    let (n, u) = s.trim().split_at(s.trim().len().saturating_sub(1));
    let v: u64 = n.parse().unwrap_or(24);
    match u {
        "h" => v * 3600,
        "m" => v * 60,
        _ => v,
    }
}

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let Some(cmd) = args.first().cloned() else {
        eprintln!("uso: nucleo-valores actualizar|historico|get|vigente|demonio [opciones]");
        std::process::exit(2);
    };
    let f = Flags::parsear(&args[1..], &[]);
    let indicador = f.texto("indicador", "uf");
    let anio = f.entero("anio", anio_actual() as i64) as i32;
    let fecha = f.texto("fecha", &dtechile::almacen::ahora_iso()[..10]);
    let db = f.texto("db", "dte_database.db");
    let inds: Vec<&str> = if indicador == "todos" {
        vec!["uf", "utm", "dolar"]
    } else {
        vec![indicador.as_str()]
    };
    match cmd.as_str() {
        "actualizar" => refrescar(&db, anio, &inds, &|m| println!("{m}")),
        "historico" => {
            let c = Cache::abrir(&db).unwrap_or_else(|e| fatal("error", e));
            let desde = f.entero("desde", 2015) as i32;
            let tot = valores::cargar_historico(&c, desde, anio_actual(), &|m| println!("{m}"));
            println!("histórico {desde}-{} guardado: {tot:?}", anio_actual());
        }
        "demonio" => {
            let cada = duracion(&f.texto("cada", "24h"));
            dtechile::servidor::log(&format!(
                "nucleo-valores demonio: refresco cada {cada}s en {db}"
            ));
            loop {
                refrescar(&db, anio_actual(), &["uf", "utm", "dolar"], &|m| {
                    dtechile::servidor::log(m)
                });
                std::thread::sleep(std::time::Duration::from_secs(cada));
            }
        }
        "get" => {
            let c = Cache::abrir(&db).unwrap_or_else(|e| fatal("error", e));
            let v = c
                .get(&indicador, &fecha)
                .unwrap_or_else(|e| fatal("error", e));
            println!("{indicador} {fecha} = {v:.2}");
        }
        "vigente" => {
            let c = Cache::abrir(&db).unwrap_or_else(|e| fatal("error", e));
            let v = c
                .vigente(&indicador, &fecha)
                .unwrap_or_else(|e| fatal("error", e));
            println!(
                "{} vigente al {fecha} = {:.2} (fecha del valor: {})",
                v.indicador, v.valor, v.fecha
            );
        }
        _ => fatal("error", format!("comando desconocido: {cmd}")),
    }
}
