//! Lo que comparten los binarios del operador: banderas al estilo del paquete `flag` de Go,
//! cargar el certificado desde un .p12 (clave por entorno, Llavero o prompt oculto) o desde el
//! keystore cifrado del motor (--cert-id), y la carpeta de datos de la app.

use crate::firma::{self, Certificado};
use crate::servidor::{self, Config};
use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

/// Banderas `--nombre valor` / `--nombre=valor` / `--bool` (también con un guión), como `flag`.
pub struct Flags {
    valores: BTreeMap<String, String>,
    pub posicionales: Vec<String>,
}

impl Flags {
    /// `bools`: las banderas sin valor.
    pub fn parsear(args: &[String], bools: &[&str]) -> Flags {
        let mut f = Flags {
            valores: BTreeMap::new(),
            posicionales: Vec::new(),
        };
        let mut i = 0;
        while i < args.len() {
            let a = &args[i];
            if let Some(resto) = a
                .strip_prefix("--")
                .or_else(|| a.strip_prefix('-'))
                .filter(|r| !r.is_empty() && !a.starts_with("---"))
            {
                if let Some((k, v)) = resto.split_once('=') {
                    f.valores.insert(k.to_string(), v.to_string());
                } else if bools.contains(&resto) {
                    f.valores.insert(resto.to_string(), "true".into());
                } else if i + 1 < args.len() {
                    f.valores.insert(resto.to_string(), args[i + 1].clone());
                    i += 1;
                } else {
                    f.valores.insert(resto.to_string(), String::new());
                }
            } else {
                f.posicionales.push(a.clone());
            }
            i += 1;
        }
        f
    }
    pub fn texto(&self, k: &str, def: &str) -> String {
        self.valores
            .get(k)
            .cloned()
            .unwrap_or_else(|| def.to_string())
    }
    pub fn entero(&self, k: &str, def: i64) -> i64 {
        self.valores
            .get(k)
            .and_then(|v| v.trim().parse().ok())
            .unwrap_or(def)
    }
    pub fn logico(&self, k: &str) -> bool {
        matches!(
            self.valores.get(k).map(|s| s.as_str()),
            Some("true") | Some("1") | Some("")
        ) && self.valores.contains_key(k)
    }
    pub fn tiene(&self, k: &str) -> bool {
        self.valores.contains_key(k)
    }
}

pub fn fatal(prefijo: &str, e: impl std::fmt::Display) -> ! {
    eprintln!("{prefijo}: {e}");
    std::process::exit(1)
}

/// Lee una clave del Llavero de macOS (`security find-generic-password`).
pub fn llavero(servicio: &str, cuenta: &str) -> String {
    let mut c = std::process::Command::new("security");
    c.args(["find-generic-password", "-s", servicio]);
    if !cuenta.is_empty() {
        c.args(["-a", cuenta]);
    }
    c.arg("-w");
    match c.output() {
        Ok(o) if o.status.success() => String::from_utf8_lossy(&o.stdout).trim().to_string(),
        _ => String::new(),
    }
}

/// Un prompt oculto en la terminal (si hay terminal).
pub fn prompt_oculto(texto: &str) -> String {
    use std::io::{BufRead, Write};
    if !es_terminal() {
        return String::new();
    }
    eprint!("{texto}");
    let _ = std::io::stderr().flush();
    let _ = std::process::Command::new("stty").arg("-echo").status();
    let mut linea = String::new();
    let _ = std::io::stdin().lock().read_line(&mut linea);
    let _ = std::process::Command::new("stty").arg("echo").status();
    eprintln!();
    linea.trim_end_matches(['\n', '\r']).to_string()
}

fn es_terminal() -> bool {
    std::process::Command::new("test")
        .args(["-t", "0"])
        .status()
        .map(|s| s.success())
        .unwrap_or(false)
}

/// `ClaveCertificado`: NUCLEO_CLAVE_CERTIFICADO, el Llavero de macOS (DTE_KEYCHAIN_SERVICE,
/// default dte-cert-firma) o, si hay terminal, un prompt oculto.
pub fn clave_certificado() -> String {
    for k in ["NUCLEO_CLAVE_CERTIFICADO", "NUCLEO_CERT_CLAVE"] {
        if let Ok(v) = std::env::var(k) {
            if !v.is_empty() {
                return v;
            }
        }
    }
    let servicio =
        std::env::var("DTE_KEYCHAIN_SERVICE").unwrap_or_else(|_| "dte-cert-firma".into());
    let v = llavero(&servicio, "");
    if !v.is_empty() {
        return v;
    }
    prompt_oculto("Clave del certificado (.p12): ")
}

/// `CargarCertificado`: con cert_id > 0 lo saca del keystore del motor (env/db); si no, del .p12.
pub fn cargar_certificado(
    cert_path: &str,
    cert_id: i64,
    cuenta: i64,
    env: &str,
    db: &str,
) -> Result<Certificado, String> {
    if cert_id > 0 {
        let mut cfg = servidor::config::cargar(env);
        if !db.is_empty() {
            cfg.database_path = db.to_string();
        }
        cfg.rvd_scheduler_activo = false;
        let s = servidor::Servidor::nuevo(cfg)?;
        return s.certificado_del_keystore(cert_id, cuenta);
    }
    let ruta = if cert_path.is_empty() {
        std::env::var("DTE_CERT_PATH").unwrap_or_default()
    } else {
        cert_path.to_string()
    };
    if ruta.is_empty() {
        return Err("falta --cert (ruta del .p12) o --cert-id (keystore)".into());
    }
    let p12 = std::fs::read(&ruta).map_err(|e| format!("{ruta}: {e}"))?;
    let clave = clave_certificado();
    if clave.is_empty() {
        return Err("falta la clave del certificado: NUCLEO_CLAVE_CERTIFICADO o el Llavero".into());
    }
    firma::cargar_p12(&p12, &clave)
}

/// `os.UserConfigDir()`.
pub fn dir_config_usuario() -> Result<PathBuf, String> {
    let home = std::env::var("HOME")
        .or_else(|_| std::env::var("USERPROFILE"))
        .map_err(|_| "sin HOME".to_string())?;
    if cfg!(target_os = "macos") {
        return Ok(Path::new(&home).join("Library").join("Application Support"));
    }
    if cfg!(target_os = "windows") {
        return Ok(std::env::var("APPDATA")
            .map(PathBuf::from)
            .unwrap_or_else(|_| Path::new(&home).join("AppData").join("Roaming")));
    }
    Ok(std::env::var("XDG_CONFIG_HOME")
        .map(PathBuf::from)
        .unwrap_or_else(|_| Path::new(&home).join(".config")))
}

/// `CarpetaDatos`: donde vive todo lo que escribe el motor cuando no corre desde el repo:
/// ~/Library/Application Support/Faro (macOS), %AppData%\Faro, ~/.config/Faro.
/// DTE_DATOS la cambia. La app se llamó "DTE Chile" hasta 2026-10-12: si existe esa carpeta y
/// todavía no existe "Faro", se renombra (misma base, mismos documentos; nada se copia ni se pierde).
pub fn carpeta_datos() -> Result<PathBuf, String> {
    let d = match std::env::var("DTE_DATOS") {
        Ok(v) if !v.is_empty() => PathBuf::from(v),
        _ => {
            let base = dir_config_usuario()?;
            let nueva = base.join("Faro");
            let vieja = base.join("DTE Chile");
            if !nueva.exists() && vieja.is_dir() {
                std::fs::rename(&vieja, &nueva).map_err(|e| format!("no pude renombrar la carpeta de datos: {e}"))?;
            }
            nueva
        }
    };
    for sub in ["", "logs", "storage"] {
        std::fs::create_dir_all(d.join(sub)).map_err(|e| e.to_string())?;
    }
    proteger_carpeta_datos(&d);
    Ok(d)
}

/// `ProtegerCarpetaDatos`: la carpeta de datos guarda la clave maestra (`.env`) y la base con el
/// certificado y las claves cifradas. En Unix se deja solo para el usuario: 700 la carpeta y 600
/// el `.env` y la base (con su -wal y -shm). Silencioso si algo no existe o no se puede cambiar.
pub fn proteger_carpeta_datos(dir: &Path) {
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let _ = std::fs::set_permissions(dir, std::fs::Permissions::from_mode(0o700));
        for f in [".env", "dte_database.db", "dte_database.db-wal", "dte_database.db-shm"] {
            let r = dir.join(f);
            if r.is_file() {
                let _ = std::fs::set_permissions(&r, std::fs::Permissions::from_mode(0o600));
            }
        }
    }
    #[cfg(not(unix))]
    {
        let _ = dir;
    }
}

/// `AsegurarEnv`: crea el `.env` de la carpeta de datos la primera vez, con secretos generados
/// aquí y la clave del usuario admin. Si ya existe no se toca. Devuelve la clave admin.
pub fn asegurar_env(dir: &Path) -> Result<String, String> {
    let ruta = dir.join(".env");
    if let Ok(b) = std::fs::read_to_string(&ruta) {
        return Ok(clave_admin_de(&b));
    }
    let azar = |n: usize| servidor::auth::hex(&servidor::local::bytes_azar(n));
    let fernet = base64::Engine::encode(
        &base64::engine::general_purpose::URL_SAFE,
        servidor::local::bytes_azar(32),
    );
    let admin = azar(8);
    let mut contenido = String::from(
        "# Configuración del motor Faro (creada por la app; edítala si hace falta)\nSII_AMBIENTE=certificacion\nHOST=127.0.0.1\nCORS_ORIGINS=http://127.0.0.1\nLOG_LEVEL=info\nNOMBRE_SOFTWARE=DTE_CHILE\n",
    );
    for (k, v) in [
        ("JWT_SECRET_KEY", azar(32)),
        ("DTE_MASTER_KEY", fernet),
        ("ADMIN_PASSWORD", admin.clone()),
    ] {
        contenido.push_str(&format!("{k}={v}\n"));
    }
    std::fs::write(&ruta, contenido).map_err(|e| e.to_string())?;
    proteger_carpeta_datos(dir);
    Ok(admin)
}

/// `ClaveAdminDe`: ADMIN_PASSWORD del texto de un .env ("" si no está).
pub fn clave_admin_de(env: &str) -> String {
    env.lines()
        .find_map(|l| l.strip_prefix("ADMIN_PASSWORD="))
        .map(|v| v.trim().to_string())
        .unwrap_or_default()
}

/// `ConfigDeRaiz`: carga raiz/.env y deja base y storage como rutas absolutas dentro de raiz.
pub fn config_de_raiz(raiz: &Path) -> Config {
    let mut cfg = servidor::config::cargar(&raiz.join(".env").to_string_lossy());
    if !Path::new(&cfg.database_path).is_absolute() {
        cfg.database_path = servidor::abs_limpia(&raiz.join(&cfg.database_path).to_string_lossy());
    }
    if !Path::new(&cfg.storage_path).is_absolute() {
        cfg.storage_path = servidor::abs_limpia(&raiz.join(&cfg.storage_path).to_string_lossy());
    }
    cfg
}

/// `ResolverRaiz`: --env explícito (su carpeta), un .env en el directorio actual, o la carpeta
/// de datos del usuario (creando su .env la primera vez). Devuelve (raíz, es la carpeta de datos).
pub fn resolver_raiz(env: &str) -> Result<(PathBuf, bool), String> {
    if !env.is_empty() {
        let abs = PathBuf::from(servidor::abs_limpia(env));
        return Ok((
            abs.parent().map(|p| p.to_path_buf()).unwrap_or_default(),
            false,
        ));
    }
    if let Ok(wd) = std::env::current_dir() {
        if wd.join(".env").is_file() {
            return Ok((wd, false));
        }
    }
    let d = carpeta_datos()?;
    asegurar_env(&d)?;
    Ok((d, true))
}

/// `nucleo-siiengine`: NUCLEO_CLAVE_* o el Llavero (servicio, cuenta = RUT sin puntos con DV).
pub fn clave_sii(env: &str, servicio: &str, rut: &str) -> String {
    if let Ok(v) = std::env::var(env) {
        if !v.is_empty() {
            return v;
        }
    }
    llavero(servicio, &crate::siiengine::formatear_rut(rut, false))
}

/// JSON con sangría de dos espacios y salto final (`json.MarshalIndent`).
pub fn imprimir_json<T: serde::Serialize>(v: &T) {
    println!("{}", serde_json::to_string_pretty(v).unwrap_or_default());
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn flags_como_go() {
        let a: Vec<String> = [
            "servir",
            "--puerto",
            "8010",
            "-env",
            "x.env",
            "--enviar",
            "--db=base.db",
            "extra",
        ]
        .iter()
        .map(|s| s.to_string())
        .collect();
        let f = Flags::parsear(&a[1..], &["enviar"]);
        assert_eq!(f.entero("puerto", 0), 8010);
        assert_eq!(f.texto("env", ""), "x.env");
        assert_eq!(f.texto("db", ""), "base.db");
        assert!(f.logico("enviar") && !f.logico("otro"));
        assert_eq!(f.posicionales, vec!["extra"]);
        assert_eq!(clave_admin_de("A=1\nADMIN_PASSWORD= abc \n"), "abc");
    }
}
