//! Cuando algo falla: registro local y un informe que la persona ve entero antes de compartir.
//!
//! Decisión (2026-10-17): **sin Sentry ni ningún reportero de errores en la nube**. La app
//! promete "nada sale de tu computador", los errores de este dominio llevan RUT, folios y montos,
//! y el público son colegios. En su lugar:
//!   - `capturar_caidas` deja cada caída (panic) de la app en `logs/app-fallas.log` de la carpeta
//!     de datos, con versión, sistema y traza; `registrar` hace lo mismo con los errores que la
//!     interfaz avisa (`registrar_falla`).
//!   - `informe` arma el texto de "Informar un problema": versión, sistema, y las últimas líneas
//!     de los dos registros con los RUT y las claves tachados. La interfaz lo muestra completo;
//!     la persona lo copia y decide dónde pegarlo. Nunca se envía solo.

use regex::Regex;
use std::path::{Path, PathBuf};
use std::sync::OnceLock;

static RAIZ: OnceLock<PathBuf> = OnceLock::new();

/// La carpeta de datos, en cuanto el motor la conoce (antes se usa la carpeta estándar).
pub fn fijar_raiz(raiz: &str) {
    if !raiz.is_empty() {
        let _ = RAIZ.set(PathBuf::from(raiz));
    }
}

fn raiz() -> Option<PathBuf> {
    RAIZ.get()
        .cloned()
        .or_else(|| dtechile::cliutil::carpeta_datos().ok())
}

/// Deja las caídas de la app (panic de cualquier hilo) en `logs/app-fallas.log`, y sigue con el
/// comportamiento normal (el mensaje en la consola).
pub fn capturar_caidas() {
    let previo = std::panic::take_hook();
    std::panic::set_hook(Box::new(move |info| {
        let traza = std::backtrace::Backtrace::force_capture();
        if let Some(r) = raiz() {
            registrar_en(&r, "caída de la app", &format!("{info}\n{traza}"));
        }
        previo(info);
    }));
}

/// Una falla avisada por la interfaz (error de JavaScript, promesa rechazada).
pub fn registrar(origen: &str, texto: &str) {
    if let Some(r) = raiz() {
        registrar_en(&r, origen, texto);
    }
}

pub fn registrar_en(raiz: &Path, origen: &str, texto: &str) {
    use std::io::Write;
    let _ = std::fs::create_dir_all(raiz.join("logs"));
    let p = raiz.join("logs").join("app-fallas.log");
    if let Ok(mut f) = std::fs::OpenOptions::new().create(true).append(true).open(p) {
        let _ = writeln!(
            f,
            "==== {} · {} · Faro {} ====\n{}\n",
            ahora(),
            origen,
            env!("CARGO_PKG_VERSION"),
            texto.trim_end()
        );
    }
}

/// El informe completo, listo para copiar. `ambiente` es el del motor ("certificacion",
/// "produccion"); `externo`, si el motor no corre dentro de la app.
pub fn informe(raiz: &str, version_motor: &str, externo: bool, ambiente: &str) -> String {
    let mut s = String::new();
    s.push_str("Informe de Faro\n");
    s.push_str(&format!(
        "App {} · motor {} ({}) · ambiente {}\n",
        env!("CARGO_PKG_VERSION"),
        if version_motor.is_empty() { "?" } else { version_motor },
        if externo { "externo" } else { "dentro de la app" },
        if ambiente.is_empty() { "?" } else { ambiente }
    ));
    s.push_str(&format!("Sistema: {}\nFecha: {}\n", sistema(), ahora()));
    if raiz.is_empty() {
        s.push_str("\n(el motor no llegó a arrancar: no hay carpeta de datos ni registros)\n");
        return s;
    }
    let logs = Path::new(raiz).join("logs");
    for (titulo, archivo, n) in [
        ("Fallas registradas", "app-fallas.log", 80),
        ("Registro del motor", "app-motor.log", 120),
    ] {
        s.push_str(&format!("\n== {titulo} (logs/{archivo}, últimas {n} líneas) ==\n"));
        match cola(&logs.join(archivo), n) {
            Some(t) if !t.trim().is_empty() => s.push_str(&tachar(&t)),
            _ => s.push_str("(nada)\n"),
        }
    }
    s.push_str("\nLos RUT y las claves aparecen tachados. Nada de esto se envió: lo compartes tú.\n");
    s
}

/// Tacha lo que identifica a alguien o abre una puerta: RUT (quedan los dos primeros dígitos y el
/// verificador) y cadenas largas que parecen claves o tokens.
pub fn tachar(texto: &str) -> String {
    static RUT: OnceLock<Regex> = OnceLock::new();
    static TOKEN: OnceLock<Regex> = OnceLock::new();
    let rut = RUT.get_or_init(|| Regex::new(r"(?i)\b(\d{1,2})\.?\d{3}\.?\d{3}-([\dk])\b").unwrap());
    let token = TOKEN.get_or_init(|| Regex::new(r"[A-Za-z0-9+/=_-]{40,}").unwrap());
    let t = rut.replace_all(texto, "$1.***.***-$2");
    token.replace_all(&t, "[clave tachada]").into_owned()
}

fn cola(p: &Path, n: usize) -> Option<String> {
    let datos = std::fs::read(p).ok()?;
    let texto = String::from_utf8_lossy(&datos);
    let lineas: Vec<&str> = texto.lines().collect();
    let desde = lineas.len().saturating_sub(n);
    let mut s = lineas[desde..].join("\n");
    s.push('\n');
    Some(s)
}

fn sistema() -> String {
    let base = format!("{} {}", std::env::consts::OS, std::env::consts::ARCH);
    let detalle = if cfg!(target_os = "macos") {
        std::process::Command::new("sw_vers")
            .arg("-productVersion")
            .output()
            .ok()
            .map(|o| String::from_utf8_lossy(&o.stdout).trim().to_string())
    } else if cfg!(target_os = "linux") {
        std::fs::read_to_string("/etc/os-release").ok().and_then(|t| {
            t.lines()
                .find_map(|l| l.strip_prefix("PRETTY_NAME="))
                .map(|v| v.trim_matches('"').to_string())
        })
    } else {
        None
    };
    match detalle {
        Some(d) if !d.is_empty() => format!("{base} ({d})"),
        _ => base,
    }
}

/// Fecha y hora en UTC, sin dependencias (días desde 1970 → fecha civil).
fn ahora() -> String {
    let seg = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs() as i64)
        .unwrap_or(0);
    let (dias, resto) = (seg.div_euclid(86_400), seg.rem_euclid(86_400));
    let z = dias + 719_468;
    let era = z.div_euclid(146_097);
    let doe = z - era * 146_097;
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let y = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = doy - (153 * mp + 2) / 5 + 1;
    let m = if mp < 10 { mp + 3 } else { mp - 9 };
    let y = if m <= 2 { y + 1 } else { y };
    format!(
        "{y:04}-{m:02}-{d:02} {:02}:{:02}:{:02} UTC",
        resto / 3600,
        (resto % 3600) / 60,
        resto % 60
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn tacha_rut_y_claves() {
        let t = tachar("emisor 76.111.111-6 y 12345678-5; clave app_0123456789abcdef0123456789abcdef0123456789abcdef fin");
        assert_eq!(
            t,
            "emisor 76.***.***-6 y 12.***.***-5; clave [clave tachada] fin"
        );
        assert_eq!(tachar("folio 1234 total 1190"), "folio 1234 total 1190");
    }

    #[test]
    fn registra_y_arma_el_informe() {
        let d = std::env::temp_dir().join(format!("app-rs-informe-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&d);
        std::fs::create_dir_all(d.join("logs")).unwrap();
        std::fs::write(
            d.join("logs/app-motor.log"),
            (1..=200).map(|i| format!("linea {i} rut 77777777-7\n")).collect::<String>(),
        )
        .unwrap();
        registrar_en(&d, "interfaz", "TypeError: x is not a function\n  at app.js:10");
        let inf = informe(&d.to_string_lossy(), "1.1.0", false, "certificacion");
        assert!(inf.starts_with("Informe de Faro\nApp "));
        assert!(inf.contains("motor 1.1.0 (dentro de la app) · ambiente certificacion"));
        assert!(inf.contains("== Fallas registradas") && inf.contains("TypeError: x is not a function"));
        assert!(inf.contains("linea 200 rut 77.***.***-7") && !inf.contains("linea 80 "));
        assert!(!inf.contains("77777777-7"));
        assert!(inf.contains("Nada de esto se envió"));
        let sin = informe("", "", true, "");
        assert!(sin.contains("no llegó a arrancar"));
        let _ = std::fs::remove_dir_all(&d);
    }

    #[test]
    fn fecha_civil() {
        // 2026-10-17 00:00:00 UTC = 1792195200; solo comprobamos la forma y que no explote.
        let a = ahora();
        assert_eq!(a.len(), "2026-10-17 00:00:00 UTC".len(), "{a}");
        assert!(a.ends_with(" UTC"));
    }
}
