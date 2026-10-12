# `app-rs/`: la app de escritorio en Tauri, con el motor Rust adentro (fase 8, bloque 5)

La misma interfaz que la app Wails (`app/frontend/dist` es la interfaz **compartida**: HTML/CSS/JS sin framework), el mismo
contrato con ella (los 12 bindings `window.go.main.App.*`, definidos aquí por
`app/frontend/dist/tauri.js` sobre los comandos de `src/app.rs`) y el motor `dtechile::servidor`
(`nucleo-rs/`) corriendo **en el mismo proceso**: puerto libre en 127.0.0.1, clave efímera
(`APP_SHELL_KEY`) que la interfaz nunca ve, datos en el repo (desarrollo) o en la carpeta del
usuario (`~/Library/Application Support/Faro`, `DTE_DATOS` la cambia). Lanzada con
`--mcp` no abre ventana: es el servidor MCP para la IA del computador, y la pestaña "Tu IA"
escribe este mismo ejecutable en la configuración del cliente (Claude Code, Claude Desktop,
Cursor, VS Code, Windsurf, Gemini, Codex).

```bash
cd app-rs
cargo test                         # el motor en proceso sobre una carpeta vacía; la app como MCP
cargo clippy --all-targets -- -D warnings
cargo run                          # la ventana, con los datos del repo (.env, base, storage)
cargo tauri build --bundles app    # target/release/bundle/macos/Faro.app  (cargo install tauri-cli)
```

| archivo | qué hace | transcribe |
|---|---|---|
| `src/main.rs` | `--mcp` o la ventana | `app/main.go` |
| `src/motor.rs` | localiza el repo o la carpeta de datos, arranca el motor Rust en un puerto libre, lo apaga al cerrar | `app/motor.go` |
| `src/app.rs` | los comandos: `estado`, `api`, `guardar`, `bytes`, `emitir_nucleo`, `abrir_url`, `abrir_panel`, `conectores`, `conectar_ia`, `sii_engine_*`; el evento `motor` | `app/app.go`, `app/ia.go` |
| `src/siiengine.rs` | sincronizar, factura exenta y nota de crédito por el SII engine (dry-run sin folio; emitir solo con la cadena verificada) | `app/siiengine.go` |
| `src/ia.rs` | la app como servidor MCP; conectar/quitar en los clientes de IA | `app/ia.go` |
| `tauri.conf.json`, `capabilities/default.json`, `icons/` | ventana 1120×780, CSP abierta para la interfaz sin framework, diálogo de guardar y abrir enlaces; íconos desde `app/build/appicon.png` | `app/wails.json`, `app/build/` |

Modos como en la Wails: normal (repo o carpeta de datos), `DTE_API_URL` + `DTE_API_KEY` (motor
externo, nada se arranca). `DTE_MOTOR=python` no existe aquí: no hay sidecar Python.

**Esta es la app que se publica como Faro** (decidido el 2026-10-12: Rust es el destino del
port). Pasó el recorrido guiado completo, la boleta de práctica, la anulación y las capturas
del README (`docs/APP.md`, `docs/PRUEBA-DE-USUARIO.md`). Pendiente: la firma y notarización
para distribuirla fuera del repo, y "Tu IA" probado desde la app de Claude. La Wails (`app/`)
sigue construyéndose como alternativa con el motor Go mientras dura la transición.
