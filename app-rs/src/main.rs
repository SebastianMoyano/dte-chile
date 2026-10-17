//! Faro (antes DTE Chile) — cascarón de escritorio (Tauri) con el motor Rust adentro (fase 8, bloque 5).
//!
//! El motor es `dtechile::servidor` corriendo en este mismo proceso: escucha en un puerto libre
//! de 127.0.0.1 con una clave efímera (APP_SHELL_KEY) y la interfaz (`app/frontend/dist`, la
//! misma de la app Wails) le habla a través de los comandos de `app.rs`, que firman las llamadas
//! desde Rust. La interfaz nunca ve la clave. Lanzada con `--mcp` no abre ventana: es el
//! servidor MCP para la IA del computador (`ia.rs`).

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod app;
mod ia;
mod informe;
mod motor;
mod siiengine;

fn main() {
    informe::capturar_caidas();
    if std::env::args().nth(1).as_deref() == Some("--mcp") {
        if let Err(e) = ia::ejecutar_mcp(std::io::stdin().lock(), std::io::stdout()) {
            eprintln!("Error: {e}");
            std::process::exit(1);
        }
        return;
    }
    app::correr();
}
