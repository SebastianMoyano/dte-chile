//! Conectar la IA del computador a la app: la propia app, lanzada con `--mcp`, es el servidor
//! MCP (`dtechile::mcp`) sobre la misma carpeta de datos. Así "un click" en la app escribe en
//! la configuración de Claude Code, Claude Desktop, Cursor, VS Code, Windsurf, Gemini o Codex
//! una entrada que apunta a este mismo ejecutable; no hay segundo binario ni nada que descargar.

use dtechile::conectores::{self, Cliente, Entrada, NOMBRE_POR_DEFECTO};
use std::io::{BufRead, Write};
use std::path::{Path, PathBuf};

/// La app en modo servidor MCP (sin ventana): atiende stdio hasta que el cliente cierra. Datos:
/// el repo si está al lado (desarrollo) o la carpeta de datos del usuario.
pub fn ejecutar_mcp(stdin: impl BufRead, stdout: impl Write) -> Result<(), String> {
    let mut env = String::new();
    if let Ok(raiz) = crate::motor::localizar_raiz() {
        if std::env::var("DTE_DATOS").unwrap_or_default().is_empty() {
            env = raiz.join(".env").to_string_lossy().into_owned();
        }
    }
    let m = dtechile::mcp::arrancar(&env, "")?;
    m.servir_stdio(stdin, stdout);
    Ok(())
}

fn goos() -> &'static str {
    if cfg!(target_os = "macos") {
        "darwin"
    } else if cfg!(target_os = "windows") {
        "windows"
    } else {
        "linux"
    }
}

fn home() -> Result<PathBuf, String> {
    std::env::var("HOME")
        .or_else(|_| std::env::var("USERPROFILE"))
        .map(PathBuf::from)
        .map_err(|_| "sin HOME".to_string())
}

/// Cómo debe lanzarnos un cliente: este ejecutable con --mcp (y DTE_DATOS si cambió la carpeta).
fn entrada_mcp() -> Result<Entrada, String> {
    let exe = std::env::current_exe().map_err(|e| e.to_string())?;
    let exe = std::fs::canonicalize(&exe).unwrap_or(exe);
    let mut e = Entrada {
        nombre: NOMBRE_POR_DEFECTO.into(),
        comando: exe.to_string_lossy().into_owned(),
        args: vec!["--mcp".into()],
        ..Default::default()
    };
    if let Ok(d) = std::env::var("DTE_DATOS") {
        if !d.is_empty() {
            e.env.insert("DTE_DATOS".into(), d);
        }
    }
    Ok(e)
}

/// Los clientes de IA de esta máquina y si ya tienen la app conectada.
pub fn conectores() -> Result<Vec<Cliente>, String> {
    Ok(conectores::clientes(&home()?, goos(), NOMBRE_POR_DEFECTO))
}

/// Escribe (o quita) la entrada de la app en ese cliente; devuelve el archivo tocado.
pub fn conectar_ia(id: &str, quitar: bool) -> Result<String, String> {
    let c = conectores::buscar(
        &conectores::clientes(&home()?, goos(), NOMBRE_POR_DEFECTO),
        id,
    )?;
    if quitar {
        c.quitar(NOMBRE_POR_DEFECTO)?;
        return Ok(c.archivo.clone());
    }
    let e = entrada_mcp()?;
    if e.comando.is_empty() {
        return Err("no sé dónde está el ejecutable de la app".into());
    }
    c.instalar(&e)?;
    Ok(c.archivo.clone())
}

#[allow(dead_code)]
fn _ruta(p: &Path) -> String {
    p.to_string_lossy().into_owned()
}

#[cfg(test)]
mod tests {
    use super::*;

    /// La app con --mcp responde MCP por stdio sobre la carpeta de datos, y conectar_ia deja la
    /// entrada (este ejecutable, --mcp) en la configuración del cliente.
    #[test]
    fn app_como_mcp() {
        let _g = crate::motor::SERIAL
            .lock()
            .unwrap_or_else(|e| e.into_inner());
        let datos = std::env::temp_dir().join(format!("app-rs-mcp-{}", std::process::id()));
        let home = std::env::temp_dir().join(format!("app-rs-home-{}", std::process::id()));
        for d in [&datos, &home] {
            let _ = std::fs::remove_dir_all(d);
            std::fs::create_dir_all(d).unwrap();
        }
        std::env::set_var("DTE_DATOS", &datos);
        let home_antes = std::env::var("HOME").unwrap_or_default();
        std::env::set_var("HOME", &home);
        let mut out = Vec::new();
        ejecutar_mcp(std::io::Cursor::new(b"{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"tools/call\",\"params\":{\"name\":\"salud\",\"arguments\":{}}}\n".to_vec()), &mut out).unwrap();
        let out = String::from_utf8(out).unwrap();
        assert!(out.contains("\"motor\":\"rust\""), "salud: {out}");
        assert!(
            datos.join("dte_database.db").exists(),
            "la base debía quedar en la carpeta de datos"
        );
        let lista = conectores().unwrap();
        assert_eq!(lista.len(), 7);
        let archivo = conectar_ia("cursor", false).unwrap();
        let doc: serde_json::Value =
            serde_json::from_slice(&std::fs::read(&archivo).unwrap()).unwrap();
        let e = &doc["mcpServers"]["dte-chile"];
        let exe = std::fs::canonicalize(std::env::current_exe().unwrap()).unwrap();
        assert_eq!(e["command"], exe.to_string_lossy().as_ref());
        assert_eq!(e["args"][0], "--mcp");
        assert_eq!(e["env"]["DTE_DATOS"], datos.to_string_lossy().as_ref());
        assert!(
            conectores()
                .unwrap()
                .iter()
                .any(|c| c.id == "cursor" && c.instalado),
            "debía verse conectado"
        );
        conectar_ia("cursor", true).unwrap();
        assert!(
            conectores()
                .unwrap()
                .iter()
                .any(|c| c.id == "cursor" && !c.instalado),
            "debía quedar desconectado"
        );
        std::env::set_var("HOME", home_antes);
        std::env::remove_var("DTE_DATOS");
        let _ = std::fs::remove_dir_all(&datos);
        let _ = std::fs::remove_dir_all(&home);
    }
}
