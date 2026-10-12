//! nucleo-mcp: el servidor MCP del motor en Rust, y el instalador que lo enchufa en los
//! clientes de IA del computador. El motor corre EN ESTE PROCESO (`mcp::arrancar`).
//!
//!     nucleo-mcp                                     stdio (JSON-RPC por líneas): lo que lanzan los clientes
//!     nucleo-mcp --env /ruta/.env [--db …]           ídem, con un .env concreto (sin --env: ./.env o la carpeta de datos)
//!     MCP_AUTH_TOKEN=secreto nucleo-mcp --http 127.0.0.1:8090   HTTP: POST /mcp con Authorization: Bearer
//!
//!     nucleo-mcp clientes [--json]                   qué clientes de IA hay en esta máquina y cuáles ya tienen el motor
//!     nucleo-mcp instalar --en claude-code           escribe la entrada en la configuración de ese cliente
//!     nucleo-mcp instalar --en todos                 en todos los que estén instalados
//!     nucleo-mcp instalar --en cursor --quitar       la saca

use dtechile::cliutil::Flags;
use dtechile::conectores::{self, Entrada, NOMBRE_POR_DEFECTO};
use dtechile::mcp;
use dtechile::servidor::{abs_limpia, log};
use std::path::{Path, PathBuf};
use std::sync::Arc;

fn goos() -> &'static str {
    if cfg!(target_os = "macos") {
        "darwin"
    } else if cfg!(target_os = "windows") {
        "windows"
    } else {
        "linux"
    }
}

fn home() -> PathBuf {
    PathBuf::from(
        std::env::var("HOME")
            .or_else(|_| std::env::var("USERPROFILE"))
            .unwrap_or_default(),
    )
}

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    match args.first().map(|s| s.as_str()) {
        Some("clientes") => std::process::exit(cmd_clientes(&args[1..])),
        Some("instalar") => std::process::exit(cmd_instalar(&args[1..])),
        _ => {}
    }
    let f = Flags::parsear(&args, &[]);
    let m = match mcp::arrancar(&f.texto("env", ""), &f.texto("db", "")) {
        Ok(m) => Arc::new(m),
        Err(e) => {
            eprintln!("{e}");
            std::process::exit(1);
        }
    };
    let http = f.texto("http", "");
    if !http.is_empty() {
        let token = std::env::var("MCP_AUTH_TOKEN").unwrap_or_default();
        log(&format!(
            "MCP HTTP en http://{http}/mcp — auth por MCP_AUTH_TOKEN{}",
            if token.is_empty() {
                " (no definido: solo JWT)"
            } else {
                ""
            }
        ));
        if let Err(e) = m.servir_http(&http, token) {
            eprintln!("{e}");
            std::process::exit(1);
        }
        return;
    }
    let stdin = std::io::stdin();
    m.servir_stdio(stdin.lock(), std::io::stdout());
}

fn cmd_clientes(args: &[String]) -> i32 {
    let f = Flags::parsear(args, &["json"]);
    let lista = conectores::clientes(&home(), goos(), &f.texto("nombre", NOMBRE_POR_DEFECTO));
    if f.logico("json") {
        println!("{}", serde_json::to_string(&lista).unwrap_or_default());
        return 0;
    }
    for c in lista {
        let estado = if c.instalado {
            "conectado"
        } else if c.presente {
            "detectado, sin conectar"
        } else {
            "no detectado"
        };
        println!("{:<15} {:<28} {:<24} {}", c.id, c.nombre, estado, c.archivo);
    }
    0
}

fn cmd_instalar(args: &[String]) -> i32 {
    let f = Flags::parsear(args, &["quitar", "json"]);
    let en = f.texto("en", "");
    if en.is_empty() {
        eprintln!("falta --en <cliente|todos>");
        return 2;
    }
    let nombre = f.texto("nombre", NOMBRE_POR_DEFECTO);
    let exe = std::env::current_exe()
        .ok()
        .and_then(|e| std::fs::canonicalize(e).ok())
        .unwrap_or_default();
    let mut e = Entrada {
        nombre: nombre.clone(),
        comando: exe.to_string_lossy().into_owned(),
        ..Default::default()
    };
    for k in ["env", "db"] {
        let v = f.texto(k, "");
        if !v.is_empty() {
            e.args.push(format!("--{k}"));
            e.args.push(abs_limpia(&v));
        }
    }
    if let Ok(d) = std::env::var("DTE_DATOS") {
        if !d.is_empty() {
            e.env.insert("DTE_DATOS".into(), d);
        }
    }
    let lista = conectores::clientes(&home(), goos(), &nombre);
    let objetivo: Vec<conectores::Cliente> = if en == "todos" {
        let o: Vec<_> = lista.into_iter().filter(|c| c.presente).collect();
        if o.is_empty() {
            eprintln!("no detecté ningún cliente de IA en esta máquina");
            return 1;
        }
        o
    } else {
        match conectores::buscar(&lista, &en) {
            Ok(c) => vec![c],
            Err(er) => {
                eprintln!("{er}");
                return 2;
            }
        }
    };
    let quitar = f.logico("quitar");
    let mut rc = 0;
    let mut out = Vec::new();
    for c in &objetivo {
        let r = if quitar {
            c.quitar(&nombre)
        } else {
            c.instalar(&e)
        };
        let (cambio, error) = match r {
            Ok(b) => (b, String::new()),
            Err(er) => {
                rc = 1;
                (false, er)
            }
        };
        out.push((c.id.clone(), c.archivo.clone(), cambio, error));
    }
    if f.logico("json") {
        let v: Vec<serde_json::Value> = out
            .iter()
            .map(|(c, a, cambio, err)| {
                let mut m = serde_json::json!({"cliente": c, "archivo": a, "cambio": cambio});
                if !err.is_empty() {
                    m["error"] = serde_json::json!(err);
                }
                m
            })
            .collect();
        println!("{}", serde_json::to_string(&v).unwrap_or_default());
        return rc;
    }
    for (c, a, cambio, err) in &out {
        if !err.is_empty() {
            println!("{c:<15} ERROR {err}");
        } else if quitar && *cambio {
            println!("{c:<15} quitado de {a}");
        } else if quitar {
            println!("{c:<15} no estaba");
        } else if *cambio {
            println!("{c:<15} conectado: {a}");
        } else {
            println!("{c:<15} ya estaba conectado");
        }
    }
    if !quitar && rc == 0 {
        println!(
            "Reinicia el cliente para que vea el motor. La IA trabaja con los datos de {}",
            datos_de(&e)
        );
    }
    rc
}

fn datos_de(e: &Entrada) -> String {
    if let Some(i) = e.args.iter().position(|a| a == "--env") {
        if let Some(v) = e.args.get(i + 1) {
            return Path::new(v)
                .parent()
                .map(|p| p.to_string_lossy().into_owned())
                .unwrap_or_default();
        }
    }
    if let Ok(d) = std::env::var("DTE_DATOS") {
        if !d.is_empty() {
            return d;
        }
    }
    "la carpeta de datos de la app (o ./.env si existe)".into()
}
