//! nucleo-servidor: el motor HTTP en Rust (fase 8 del port).
//!
//!     nucleo-servidor servir  [--puerto 8010] [--env .env] [--db ruta.db] [--motor http://127.0.0.1:8000] [--app app/frontend/dist]
//!     nucleo-servidor migrar  [--env .env] [--db ruta.db]        aplica las migraciones pendientes y muestra la versión
//!     nucleo-servidor rotar-claves [--env .env] [--db ruta.db]   re-cifra el keystore con claves nuevas (ADMIN_PASSWORD opcional)
//!
//! Atiende con el mismo contrato que el motor Python (/api/v1/…); lo que no esté aquí se reenvía
//! a --motor. Sin --motor, esas rutas responden 503. Secretos: del .env y del entorno, nunca por flag.

use dtechile::almacen::Almacen;
use dtechile::cliutil::{fatal, Flags};
use dtechile::servidor::{self, config, Servidor};

fn main() {
    let mut args: Vec<String> = std::env::args().skip(1).collect();
    let mut cmd = "servir".to_string();
    if let Some(a) = args.first() {
        if ["servir", "migrar", "rotar-claves"].contains(&a.as_str()) {
            cmd = a.clone();
            args.remove(0);
        }
    }
    let f = Flags::parsear(&args, &[]);
    let puerto = f.entero("puerto", 8010);
    let env = f.texto("env", ".env");
    let mut cfg = config::cargar(&env);
    let db = f.texto("db", "");
    if !db.is_empty() {
        cfg.database_path = db;
    }
    match cmd.as_str() {
        "migrar" => {
            let alm = Almacen::abrir(&cfg.database_path).unwrap_or_else(|e| fatal("error", e));
            let aplicadas = alm.migrar().unwrap_or_else(|e| fatal("error", e));
            let v = alm.version_esquema().unwrap_or(0);
            println!(
                "base {}: esquema versión {v} (aplicadas ahora: {aplicadas:?})",
                cfg.database_path
            );
        }
        "rotar-claves" => {
            cfg.rvd_scheduler_activo = false;
            let s = Servidor::nuevo(cfg).unwrap_or_else(|e| fatal("error", e));
            let admin = s
                .rotar_claves(&env, &std::env::var("ADMIN_PASSWORD").unwrap_or_default())
                .unwrap_or_else(|e| fatal("error", e));
            println!("ENDURECIMIENTO COMPLETO");
            println!("  Contraseña de admin (guárdala, se muestra 1 vez): {admin}");
            println!("  JWT y master key nuevos escritos en {env} (los tokens viejos ya no valen). Reinicia el motor.");
        }
        _ => {
            cfg.motor_python = f.texto("motor", "http://127.0.0.1:8000");
            cfg.carpeta_app = f.texto("app", "");
            if cfg.carpeta_app.is_empty() {
                cfg.carpeta_app = config::ruta_app(".");
            }
            let s = Servidor::nuevo(cfg).unwrap_or_else(|e| fatal("error", e));
            servidor::log(&format!(
                "motor Rust en http://127.0.0.1:{puerto} (base {}; reenvío a {:?}; app en {:?})",
                s.cfg.database_path, s.cfg.motor_python, s.cfg.carpeta_app
            ));
            let srv = s.clone();
            if let Err(e) =
                servidor::http::servir(&format!("127.0.0.1:{puerto}"), move |p| srv.atender(p))
            {
                fatal("error", e);
            }
        }
    }
}
