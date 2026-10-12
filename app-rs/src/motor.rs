//! El motor que esta app arranca y supervisa: `dtechile::servidor` EN ESTE PROCESO (sin Python,
//! sin Go): escucha en un puerto libre de 127.0.0.1 con una clave efímera (APP_SHELL_KEY) y la
//! interfaz le habla por los comandos de la app. Transcripción de `app/motor.go`.
//!
//! Modos:
//!   - normal: en desarrollo usa el repo (su .env, base y storage); empaquetado, la carpeta de
//!     datos del usuario. Sin procesos hijos.
//!   - externo: si existen DTE_API_URL (y DTE_API_KEY), no arranca nada y habla con ese motor.

use dtechile::cliutil;
use dtechile::servidor::http::ServidorHTTP;
use dtechile::servidor::{self, Servidor};
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::{Duration, Instant};

#[derive(Default)]
pub struct Motor {
    /// repo (desarrollo) o carpeta de datos (empaquetado)
    pub raiz: String,
    pub url: String,
    pub clave: String,
    pub externo: bool,
    /// sin repo al lado: datos en la carpeta del usuario
    pub empaquetado: bool,
    /// clave del usuario admin del panel web (solo empaquetado; del .env de datos)
    pub clave_admin: String,
    pub log_path: String,
    pub srv: Option<Arc<Servidor>>,
    http: Option<ServidorHTTP>,
}

fn es_raiz(d: &Path) -> bool {
    d.join("main.py").is_file() && d.join("core").is_dir()
}

/// `localizarRaiz`: la carpeta que tiene `main.py` y `core/`: DTE_REPO, o subiendo desde el
/// ejecutable y desde el cwd (hasta 6 niveles).
pub fn localizar_raiz() -> Result<PathBuf, String> {
    if let Ok(r) = std::env::var("DTE_REPO") {
        if !r.is_empty() {
            let p = PathBuf::from(&r);
            if es_raiz(&p) {
                return Ok(p);
            }
            return Err(format!("DTE_REPO={r} no contiene main.py y core/"));
        }
    }
    let mut inicios = Vec::new();
    if let Ok(exe) = std::env::current_exe() {
        if let Some(d) = exe.parent() {
            inicios.push(d.to_path_buf());
        }
    }
    if let Ok(wd) = std::env::current_dir() {
        inicios.push(wd);
    }
    for ini in inicios {
        let mut d = ini;
        for _ in 0..6 {
            if es_raiz(&d) {
                return Ok(d);
            }
            match d.parent() {
                Some(p) => d = p.to_path_buf(),
                None => break,
            }
        }
    }
    Err("no encontré el motor (main.py + core/). Define DTE_REPO con la ruta del repo".into())
}

fn puerto_libre() -> Result<u16, String> {
    let l = std::net::TcpListener::bind("127.0.0.1:0").map_err(|e| e.to_string())?;
    Ok(l.local_addr().map_err(|e| e.to_string())?.port())
}

fn clave_efimera() -> String {
    format!(
        "app_{}",
        servidor::auth::hex(&servidor::local::bytes_azar(24))
    )
}

impl Motor {
    /// `Iniciar`: arranca (o conecta) el motor y espera a que responda en "/". `carpeta_app` es
    /// de dónde servir la interfaz en /app (los recursos del bundle); sin ella, la del repo.
    pub fn iniciar(&mut self, carpeta_app: Option<PathBuf>) -> Result<(), String> {
        if let Ok(u) = std::env::var("DTE_API_URL") {
            if !u.is_empty() {
                self.url = u.trim_end_matches('/').to_string();
                self.clave = std::env::var("DTE_API_KEY").unwrap_or_default();
                self.externo = true;
                return self.esperar(Duration::from_secs(20));
            }
        }
        self.iniciar_rust(carpeta_app)
    }

    fn iniciar_rust(&mut self, carpeta_app: Option<PathBuf>) -> Result<(), String> {
        let repo = localizar_raiz();
        let con_datos = !std::env::var("DTE_DATOS").unwrap_or_default().is_empty();
        let raiz = match (&repo, con_datos) {
            (Ok(r), false) => r.clone(),
            _ => {
                let d = cliutil::carpeta_datos()?;
                self.clave_admin = cliutil::asegurar_env(&d)?;
                self.empaquetado = true;
                d
            }
        };
        self.raiz = raiz.to_string_lossy().into_owned();
        let mut cfg = cliutil::config_de_raiz(&raiz);
        self.clave = clave_efimera();
        cfg.app_shell_key = self.clave.clone();
        cfg.motor_python = std::env::var("DTE_MOTOR_PYTHON").unwrap_or_default();
        cfg.carpeta_app = match carpeta_app {
            Some(c) if c.is_dir() => c.to_string_lossy().into_owned(),
            _ => repo
                .as_ref()
                .map(|r| {
                    r.join("app")
                        .join("frontend")
                        .join("dist")
                        .to_string_lossy()
                        .into_owned()
                })
                .unwrap_or_default(),
        };
        let _ = std::fs::create_dir_all(raiz.join("logs"));
        self.log_path = raiz
            .join("logs")
            .join("app-motor.log")
            .to_string_lossy()
            .into_owned();
        servidor::log_en_archivo(&self.log_path).map_err(|e| e.to_string())?;
        let puerto = puerto_libre()?;
        self.url = format!("http://127.0.0.1:{puerto}");
        servidor::log(&format!(
            "==== arranque motor Rust en {} (base {}) ====",
            self.url, cfg.database_path
        ));
        let s = Servidor::nuevo(cfg).map_err(|e| format!("no pude arrancar el motor: {e}"))?;
        if !s.clave_admin_generada.is_empty() && self.clave_admin.is_empty() {
            self.clave_admin = s.clave_admin_generada.clone();
        }
        let s2 = s.clone();
        let http = ServidorHTTP::iniciar(&format!("127.0.0.1:{puerto}"), move |p| s2.atender(p))
            .inspect_err(|_| s.cerrar())?;
        self.srv = Some(s);
        self.http = Some(http);
        self.esperar(Duration::from_secs(20))
    }

    fn esperar(&self, max: Duration) -> Result<(), String> {
        let ini = Instant::now();
        while ini.elapsed() < max {
            if self.vivo() {
                return Ok(());
            }
            std::thread::sleep(Duration::from_millis(300));
        }
        Err(format!("el motor en {} no responde", self.url))
    }

    pub fn vivo(&self) -> bool {
        let ag = dtechile::sii::http::agente(Duration::from_secs(2), false);
        matches!(dtechile::sii::http::ejecutar_get(ag.get(format!("{}/", self.url))), Ok(r) if r.status == 200)
    }

    /// `Detener`: apaga el HTTP, el programador de RVD y suelta la base.
    pub fn detener(&mut self) {
        if let Some(h) = self.http.take() {
            h.detener();
        }
        if let Some(s) = self.srv.take() {
            s.cerrar();
        }
    }
}

#[cfg(test)]
pub(crate) static SERIAL: std::sync::Mutex<()> = std::sync::Mutex::new(());

#[cfg(test)]
mod tests {
    use super::*;

    fn pedir(url: &str, clave: &str) -> (u16, String) {
        let ag = dtechile::sii::http::agente(Duration::from_secs(10), false);
        let mut req = ag.get(url);
        if !clave.is_empty() {
            req = req.header("Authorization", &format!("Bearer {clave}"));
        }
        let r = dtechile::sii::http::ejecutar_get(req).unwrap();
        (r.status, String::from_utf8_lossy(&r.cuerpo).into_owned())
    }

    fn postear(url: &str, clave: &str, cuerpo: &str) -> (u16, String) {
        let ag = dtechile::sii::http::agente(Duration::from_secs(60), false);
        let mut req = ag.post(url).header("Content-Type", "application/json");
        if !clave.is_empty() {
            req = req.header("Authorization", &format!("Bearer {clave}"));
        }
        let r = dtechile::sii::http::ejecutar(req, cuerpo.as_bytes()).unwrap();
        (r.status, String::from_utf8_lossy(&r.cuerpo).into_owned())
    }

    /// La app arranca el motor Rust sobre una carpeta de datos vacía (como la app empaquetada
    /// la primera vez): crea .env, base, admin, y responde con la clave efímera; sin clave,
    /// 401; la interfaz se sirve en /app/; la práctica emite y dibuja el PDF.
    #[test]
    fn motor_rust_en_proceso() {
        let _g = SERIAL.lock().unwrap_or_else(|e| e.into_inner());
        let datos = std::env::temp_dir().join(format!("app-rs-motor-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&datos);
        std::fs::create_dir_all(&datos).unwrap();
        std::env::set_var("DTE_DATOS", &datos);
        std::env::remove_var("DTE_API_URL");
        let dist = Path::new(env!("CARGO_MANIFEST_DIR")).join("../app/frontend/dist");
        let mut m = Motor::default();
        m.iniciar(Some(dist)).unwrap();
        assert!(m.empaquetado && !m.clave_admin.is_empty() && m.srv.is_some());
        for f in [".env", "dte_database.db", "logs/app-motor.log"] {
            assert!(datos.join(f).exists(), "falta {f}");
        }
        let (st, cuerpo) = pedir(&format!("{}/", m.url), "");
        assert!(
            st == 200 && cuerpo.contains("\"status\":\"ok\""),
            "{st} {cuerpo}"
        );
        assert_eq!(
            pedir(&format!("{}/api/v1/dte/documentos", m.url), "").0,
            401
        );
        assert_eq!(
            pedir(&format!("{}/api/v1/dte/documentos", m.url), &m.clave).0,
            200
        );
        let (st, _) = postear(
            &format!("{}/api/v1/auth/login", m.url),
            "",
            &format!(r#"{{"username":"admin","password":"{}"}}"#, m.clave_admin),
        );
        assert_eq!(st, 200, "login admin");
        let (st, cuerpo) = pedir(&format!("{}/app/", m.url), "");
        assert!(st == 200 && cuerpo.contains("<html"), "/app/: {st}");
        let (st, b) = postear(
            &format!("{}/api/v1/simulacion/emitir", m.url),
            &m.clave,
            r#"{"tipo_dte":39,"items":[{"nombre":"Café","precio_unitario":1190}]}"#,
        );
        assert!(
            st == 200 && b.contains("\"pdf_path\""),
            "práctica: {st} {b}"
        );
        let (st, cuerpo) = pedir(&format!("{}/api/v1/dte/documentos", m.url), &m.clave);
        assert!(
            st == 200 && cuerpo.contains("\"tiene_pdf\":true"),
            "{st} {cuerpo:.300}"
        );
        let v: serde_json::Value = serde_json::from_str(&b).unwrap();
        let (st, pdf) = pedir(
            &format!("{}/api/v1/dte/documentos/{}/pdf", m.url, v["dte_id"]),
            &m.clave,
        );
        assert!(st == 200 && pdf.starts_with("%PDF"), "pdf: {st}");
        m.detener();
        assert!(!m.vivo(), "el motor sigue vivo tras detener");
        std::env::remove_var("DTE_DATOS");
        let _ = std::fs::remove_dir_all(&datos);
    }
}
