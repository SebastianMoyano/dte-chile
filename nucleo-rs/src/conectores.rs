//! Enchufa el servidor MCP del motor en los clientes de IA del computador: Claude Code, la app
//! de escritorio de Claude, Cursor, VS Code, Windsurf, Gemini CLI y Codex CLI. Cada uno tiene su
//! archivo de configuración en una ruta conocida; aquí se escribe (o se quita) la entrada del
//! motor sin tocar lo demás que haya. Transcripción de `nucleo/conectores`.

use serde_json::{json, Map, Value};
use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

/// Un programa de IA del computador que entiende MCP por stdio.
#[derive(Debug, Clone, serde::Serialize)]
pub struct Cliente {
    pub id: String,
    pub nombre: String,
    pub archivo: String,
    /// el cliente parece instalado (existe su carpeta o su archivo)
    pub presente: bool,
    /// la entrada del motor ya está en el archivo
    pub instalado: bool,
    #[serde(skip)]
    formato: &'static str,
}

/// Cómo debe lanzar el cliente al servidor MCP.
#[derive(Debug, Clone, Default)]
pub struct Entrada {
    pub nombre: String,
    pub comando: String,
    pub args: Vec<String>,
    pub env: BTreeMap<String, String>,
}

pub const NOMBRE_POR_DEFECTO: &str = "dte-chile";

/// Los clientes conocidos para ese HOME y sistema (darwin, windows, linux), con
/// presente/instalado ya resueltos para la entrada `nombre`.
pub fn clientes(home: &Path, goos: &str, nombre: &str) -> Vec<Cliente> {
    let nombre = if nombre.is_empty() {
        NOMBRE_POR_DEFECTO
    } else {
        nombre
    };
    let cfg = |darwin: PathBuf, windows: PathBuf, linux: PathBuf| -> PathBuf {
        match goos {
            "darwin" => home
                .join("Library")
                .join("Application Support")
                .join(darwin),
            "windows" => {
                let appdata = std::env::var("APPDATA")
                    .map(PathBuf::from)
                    .unwrap_or_else(|_| home.join("AppData").join("Roaming"));
                appdata.join(windows)
            }
            _ => home.join(".config").join(linux),
        }
    };
    let claude: PathBuf = ["Claude", "claude_desktop_config.json"].iter().collect();
    let code: PathBuf = ["Code", "User", "mcp.json"].iter().collect();
    let c = |id: &str, nombre_c: &str, archivo: PathBuf, formato: &'static str| Cliente {
        id: id.into(),
        nombre: nombre_c.into(),
        archivo: archivo.to_string_lossy().into_owned(),
        presente: false,
        instalado: false,
        formato,
    };
    let mut lista = vec![
        c(
            "claude-code",
            "Claude Code",
            home.join(".claude.json"),
            "json-mcpServers",
        ),
        c(
            "claude-desktop",
            "Claude (app de escritorio)",
            cfg(claude.clone(), claude.clone(), claude),
            "json-mcpServers",
        ),
        c(
            "cursor",
            "Cursor",
            home.join(".cursor").join("mcp.json"),
            "json-mcpServers",
        ),
        c(
            "vscode",
            "VS Code (Copilot)",
            cfg(code.clone(), code.clone(), code),
            "json-servers",
        ),
        c(
            "windsurf",
            "Windsurf",
            home.join(".codeium")
                .join("windsurf")
                .join("mcp_config.json"),
            "json-mcpServers",
        ),
        c(
            "gemini",
            "Gemini CLI",
            home.join(".gemini").join("settings.json"),
            "json-mcpServers",
        ),
        c(
            "codex",
            "Codex CLI",
            home.join(".codex").join("config.toml"),
            "toml-codex",
        ),
    ];
    for cl in &mut lista {
        let ruta = Path::new(&cl.archivo);
        cl.presente = if ruta.exists() {
            true
        } else if cl.id == "claude-code" {
            home.join(".claude").exists()
        } else {
            ruta.parent().map(|p| p.exists()).unwrap_or(false)
        };
        cl.instalado = cl.instalado(nombre);
    }
    lista
}

pub fn buscar(lista: &[Cliente], id: &str) -> Result<Cliente, String> {
    if let Some(c) = lista.iter().find(|c| c.id == id) {
        return Ok(c.clone());
    }
    let mut ids: Vec<&str> = lista.iter().map(|c| c.id.as_str()).collect();
    ids.sort();
    Err(format!(
        "cliente desconocido {id:?} (conozco: {})",
        ids.join(", ")
    ))
}

impl Cliente {
    fn raiz_json(&self) -> &'static str {
        if self.formato == "json-servers" {
            "servers"
        } else {
            "mcpServers"
        }
    }

    /// (documento) o None si el archivo no existe.
    fn leer_json(&self) -> Result<Option<Map<String, Value>>, String> {
        let b = match std::fs::read(&self.archivo) {
            Ok(b) => b,
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Ok(None),
            Err(e) => return Err(e.to_string()),
        };
        if String::from_utf8_lossy(&b).trim().is_empty() {
            return Ok(Some(Map::new()));
        }
        match serde_json::from_slice::<Value>(&b) {
            Ok(Value::Object(m)) => Ok(Some(m)),
            Ok(_) => Err(format!(
                "{} no es JSON válido (¿comentarios?): no es un objeto. Agrega la entrada a mano",
                self.archivo
            )),
            Err(e) => Err(format!(
                "{} no es JSON válido (¿comentarios?): {e}. Agrega la entrada a mano",
                self.archivo
            )),
        }
    }

    fn escribir_json(&self, doc: &Map<String, Value>) -> Result<(), String> {
        if let Some(p) = Path::new(&self.archivo).parent() {
            std::fs::create_dir_all(p).map_err(|e| e.to_string())?;
        }
        let mut b =
            serde_json::to_string_pretty(&Value::Object(doc.clone())).map_err(|e| e.to_string())?;
        b.push('\n');
        std::fs::write(&self.archivo, b).map_err(|e| e.to_string())
    }

    /// Escribe la entrada en la configuración del cliente (creando el archivo si no existe) y
    /// conserva todo lo demás. Devuelve si hubo que cambiar algo.
    pub fn instalar(&self, e: &Entrada) -> Result<bool, String> {
        let mut e = e.clone();
        if e.nombre.is_empty() {
            e.nombre = NOMBRE_POR_DEFECTO.into();
        }
        if e.comando.is_empty() {
            return Err("falta el comando del servidor MCP".into());
        }
        match self.formato {
            "json-mcpServers" | "json-servers" => self.instalar_json(&e),
            "toml-codex" => self.instalar_toml(&e),
            f => Err(format!("formato desconocido {f:?}")),
        }
    }

    /// Saca la entrada; true si estaba.
    pub fn quitar(&self, nombre: &str) -> Result<bool, String> {
        let nombre = if nombre.is_empty() {
            NOMBRE_POR_DEFECTO
        } else {
            nombre
        };
        match self.formato {
            "json-mcpServers" | "json-servers" => {
                let Some(mut doc) = self.leer_json()? else {
                    return Ok(false);
                };
                let raiz = self.raiz_json();
                let Some(Value::Object(m)) = doc.get_mut(raiz) else {
                    return Ok(false);
                };
                if m.remove(nombre).is_none() {
                    return Ok(false);
                }
                self.escribir_json(&doc)?;
                Ok(true)
            }
            "toml-codex" => {
                let Ok(t) = std::fs::read_to_string(&self.archivo) else {
                    return Ok(false);
                };
                let (resto, habia) = quitar_seccion_toml(&t, &format!("mcp_servers.{nombre}"));
                if !habia {
                    return Ok(false);
                }
                std::fs::write(&self.archivo, resto).map_err(|e| e.to_string())?;
                Ok(true)
            }
            f => Err(format!("formato desconocido {f:?}")),
        }
    }

    fn instalado(&self, nombre: &str) -> bool {
        match self.formato {
            "json-mcpServers" | "json-servers" => self
                .leer_json()
                .ok()
                .flatten()
                .and_then(|d| {
                    d.get(self.raiz_json())
                        .and_then(|m| m.as_object())
                        .map(|m| m.contains_key(nombre))
                })
                .unwrap_or(false),
            "toml-codex" => std::fs::read_to_string(&self.archivo)
                .map(|t| quitar_seccion_toml(&t, &format!("mcp_servers.{nombre}")).1)
                .unwrap_or(false),
            _ => false,
        }
    }

    fn instalar_json(&self, e: &Entrada) -> Result<bool, String> {
        let mut doc = self.leer_json()?.unwrap_or_default();
        let raiz = self.raiz_json();
        if !doc.get(raiz).map(|v| v.is_object()).unwrap_or(false) {
            doc.insert(raiz.into(), json!({}));
        }
        let mut entrada = json!({"command": e.comando, "args": e.args});
        if self.formato == "json-servers" || self.id == "claude-code" {
            entrada["type"] = json!("stdio");
        }
        if !e.env.is_empty() {
            entrada["env"] = json!(e.env);
        }
        let m = doc
            .get_mut(raiz)
            .and_then(|v| v.as_object_mut())
            .expect("raíz");
        if m.get(&e.nombre) == Some(&entrada) {
            return Ok(false);
        }
        m.insert(e.nombre.clone(), entrada);
        self.escribir_json(&doc)?;
        Ok(true)
    }

    fn instalar_toml(&self, e: &Entrada) -> Result<bool, String> {
        let texto = match std::fs::read_to_string(&self.archivo) {
            Ok(t) => t,
            Err(er) if er.kind() == std::io::ErrorKind::NotFound => String::new(),
            Err(er) => return Err(er.to_string()),
        };
        let nueva = seccion_toml(e);
        let (mut resto, habia) = quitar_seccion_toml(&texto, &format!("mcp_servers.{}", e.nombre));
        if habia && texto.contains(&nueva) {
            return Ok(false);
        }
        if !resto.is_empty() && !resto.ends_with("\n\n") {
            resto.push('\n');
        }
        if let Some(p) = Path::new(&self.archivo).parent() {
            std::fs::create_dir_all(p).map_err(|er| er.to_string())?;
        }
        std::fs::write(&self.archivo, format!("{resto}{nueva}")).map_err(|er| er.to_string())?;
        Ok(true)
    }
}

fn toml_str(s: &str) -> String {
    format!("\"{}\"", s.replace('\\', "\\\\").replace('"', "\\\""))
}

fn seccion_toml(e: &Entrada) -> String {
    let mut b = format!(
        "[mcp_servers.{}]\ncommand = {}\n",
        e.nombre,
        toml_str(&e.comando)
    );
    let args: Vec<String> = e.args.iter().map(|a| toml_str(a)).collect();
    b.push_str(&format!("args = [{}]\n", args.join(", ")));
    if !e.env.is_empty() {
        b.push_str(&format!("\n[mcp_servers.{}.env]\n", e.nombre));
        for (k, v) in &e.env {
            b.push_str(&format!("{k} = {}\n", toml_str(v)));
        }
    }
    b
}

/// Saca [sec] y sus subsecciones ([sec.x]) del texto; devuelve el resto y si existía.
pub fn quitar_seccion_toml(texto: &str, sec: &str) -> (String, bool) {
    let mut out = Vec::new();
    let (mut dentro, mut habia) = (false, false);
    for l in texto.split('\n') {
        let t = l.trim();
        if t.starts_with('[') && t.ends_with(']') {
            let nombre = t.trim_matches(|c| c == '[' || c == ']').trim();
            dentro = nombre == sec || nombre.starts_with(&format!("{sec}."));
            if dentro {
                habia = true;
            }
        }
        if !dentro {
            out.push(l);
        }
    }
    let mut resto = out.join("\n").trim_end_matches('\n').to_string();
    if !resto.is_empty() {
        resto.push('\n');
    }
    (resto, habia)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn entrada() -> Entrada {
        Entrada {
            nombre: "dte-chile".into(),
            comando: "/opt/dte/nucleo-mcp".into(),
            args: vec!["--env".into(), "/Users/x/DTE Chile/.env".into()],
            env: [("DTE_DATOS".to_string(), "/Users/x/DTE Chile".to_string())]
                .into_iter()
                .collect(),
        }
    }

    #[test]
    fn clientes_por_sistema() {
        let home = std::env::temp_dir().join(format!("conectores-{}", std::process::id()));
        let _ = std::fs::create_dir_all(&home);
        for goos in ["darwin", "linux", "windows"] {
            let l = clientes(&home, goos, "");
            assert_eq!(l.len(), 7);
            assert!(l.iter().all(|c| !c.presente && !c.instalado));
        }
        let c = buscar(&clientes(&home, "darwin", ""), "claude-desktop").unwrap();
        assert!(c
            .archivo
            .contains("Library/Application Support/Claude/claude_desktop_config.json"));
        let c = buscar(&clientes(&home, "linux", ""), "vscode").unwrap();
        assert!(c.archivo.ends_with(".config/Code/User/mcp.json"));
        assert!(buscar(&clientes(&home, "darwin", ""), "nada").is_err());
        // JSON conserva lo demás y es idempotente
        let c = buscar(&clientes(&home, "darwin", ""), "claude-desktop").unwrap();
        std::fs::create_dir_all(Path::new(&c.archivo).parent().unwrap()).unwrap();
        std::fs::write(
            &c.archivo,
            r#"{"mcpServers":{"otro":{"command":"x"}},"preferencias":{"tema":"oscuro"}}"#,
        )
        .unwrap();
        assert!(c.instalar(&entrada()).unwrap());
        assert!(!c.instalar(&entrada()).unwrap());
        let doc: Value = serde_json::from_slice(&std::fs::read(&c.archivo).unwrap()).unwrap();
        assert_eq!(doc["preferencias"]["tema"], "oscuro");
        assert_eq!(doc["mcpServers"]["otro"]["command"], "x");
        assert!(doc["mcpServers"]["dte-chile"].get("type").is_none());
        let cc = buscar(&clientes(&home, "darwin", ""), "claude-code").unwrap();
        cc.instalar(&entrada()).unwrap();
        let doc: Value = serde_json::from_slice(&std::fs::read(&cc.archivo).unwrap()).unwrap();
        assert_eq!(doc["mcpServers"]["dte-chile"]["type"], "stdio");
        assert!(
            buscar(&clientes(&home, "darwin", ""), "claude-code")
                .unwrap()
                .instalado
        );
        assert!(cc.quitar("").unwrap() && !cc.quitar("").unwrap());
        // JSON inválido no se pisa
        let cu = buscar(&clientes(&home, "darwin", ""), "cursor").unwrap();
        std::fs::create_dir_all(Path::new(&cu.archivo).parent().unwrap()).unwrap();
        std::fs::write(&cu.archivo, "{ // comentario\n}").unwrap();
        assert!(cu.instalar(&entrada()).is_err());
        // TOML (Codex)
        let cx = buscar(&clientes(&home, "darwin", ""), "codex").unwrap();
        std::fs::create_dir_all(Path::new(&cx.archivo).parent().unwrap()).unwrap();
        std::fs::write(
            &cx.archivo,
            "model = \"o3\"\n\n[mcp_servers.otro]\ncommand = \"y\"\n",
        )
        .unwrap();
        assert!(cx.instalar(&entrada()).unwrap());
        assert!(!cx.instalar(&entrada()).unwrap());
        let t = std::fs::read_to_string(&cx.archivo).unwrap();
        assert!(
            t.contains("model = \"o3\"")
                && t.contains("[mcp_servers.otro]")
                && t.contains("[mcp_servers.dte-chile]")
                && t.contains("[mcp_servers.dte-chile.env]")
        );
        assert!(cx.quitar("").unwrap());
        let t = std::fs::read_to_string(&cx.archivo).unwrap();
        assert!(!t.contains("dte-chile") && t.contains("[mcp_servers.otro]"));
        let _ = std::fs::remove_dir_all(&home);
    }
}
