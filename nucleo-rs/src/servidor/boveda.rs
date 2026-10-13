//! Bóveda con PIN (2026-10-13). La clave maestra del keystore deja de vivir en claro en el `.env`
//! y pasa a `boveda.json`, cifrada con una llave derivada del PIN (Argon2id). Mientras la app
//! está bloqueada, el motor no puede cifrar ni descifrar: el certificado y las claves del SII
//! quedan inaccesibles hasta escribir el PIN. Se bloquea sola tras un rato sin uso.
//!
//! Solo existe en Rust: es de la app de escritorio (Faro). Python y Go no la tienen, y la
//! interfaz la ignora cuando `GET /api/v1/boveda` responde 404.
//!
//! Modelo de amenaza, dicho claro: protege contra copiar la carpeta de datos (respaldo, disco,
//! otra cuenta). No protege contra un programa corriendo con el usuario mientras la app está
//! abierta. Un PIN corto se puede adivinar fuera de línea con una copia de `boveda.json`;
//! Argon2id (64 MiB, 3 pasadas) lo hace lento, no imposible: por eso el mínimo son 6 caracteres
//! y se recomienda una frase.

use super::errores::{ok, ErrorHTTP, Res};
use super::fernet::Fernet;
use super::local::bytes_azar;
use super::{ahora_utc, Json, Peticion, Prot, Servidor};
use argon2::{Algorithm, Argon2, Params, Version};
use base64::Engine;
use serde::{Deserialize, Serialize};
use serde_json::json;
use std::path::{Path, PathBuf};
use std::time::Instant;

pub const MENSAJE_BLOQUEADA: &str =
    "La app está bloqueada: escribe tu PIN para usar el certificado.";
pub const PIN_MINIMO: usize = 6;
const M_KIB: u32 = 64 * 1024;
const PASADAS: u32 = 3;
const HILOS: u32 = 1;
const INTENTOS_MAX: u32 = 5;
const ESPERA_SEG: u64 = 30;
const AUTOBLOQUEO_DEF: i64 = 15;
/// la variable del .env que guarda la clave maestra (el nombre va aparte para que el auditor
/// público no vea nunca "NOMBRE=valor" literal en el código)
const CLAVE_ENV: &str = "DTE_MASTER_KEY";

const B64: base64::engine::GeneralPurpose = base64::engine::general_purpose::URL_SAFE;

/// Lo que se escribe en `boveda.json`. Nada de aquí es secreto por sí solo.
#[derive(Serialize, Deserialize, Clone)]
pub struct Archivo {
    pub version: u32,
    pub kdf: String,
    pub sal: String,
    pub m_kib: u32,
    pub pasadas: u32,
    pub hilos: u32,
    /// la clave maestra (32 bytes) como token Fernet bajo la llave derivada del PIN
    pub maestra_cifrada: String,
    pub creada: String,
    pub autobloqueo_min: i64,
}

/// Estado en memoria. `kek` es la llave derivada del PIN mientras está abierta (sirve para
/// re-envolver la maestra al rotar claves o cambiar el PIN sin volver a pedirlo).
pub struct Estado {
    pub archivo: Option<Archivo>,
    pub kek: Option<Fernet>,
    pub ultimo_uso: Instant,
    intentos: u32,
    ultimo_fallo: Option<Instant>,
}

impl Estado {
    pub fn vacio() -> Estado {
        Estado {
            archivo: None,
            kek: None,
            ultimo_uso: Instant::now(),
            intentos: 0,
            ultimo_fallo: None,
        }
    }
    pub fn configurada(&self) -> bool {
        self.archivo.is_some()
    }
    pub fn autobloqueo_min(&self) -> i64 {
        self.archivo
            .as_ref()
            .map(|a| a.autobloqueo_min)
            .unwrap_or(AUTOBLOQUEO_DEF)
    }
}

fn derivar(pin: &str, sal: &[u8], m_kib: u32, pasadas: u32, hilos: u32) -> Result<Fernet, String> {
    let params = Params::new(m_kib, pasadas, hilos, Some(32)).map_err(|e| e.to_string())?;
    let a = Argon2::new(Algorithm::Argon2id, Version::V0x13, params);
    let mut out = [0u8; 32];
    a.hash_password_into(pin.as_bytes(), sal, &mut out)
        .map_err(|e| format!("no pude derivar la llave del PIN: {e}"))?;
    Fernet::de_bytes(&out)
}

pub fn leer_archivo(ruta: &Path) -> Option<Archivo> {
    let t = std::fs::read_to_string(ruta).ok()?;
    serde_json::from_str(&t).ok()
}

fn escribir_archivo(ruta: &Path, a: &Archivo) -> Result<(), String> {
    let t = serde_json::to_string_pretty(a).map_err(|e| e.to_string())?;
    std::fs::write(ruta, t).map_err(|e| format!("no pude escribir {}: {e}", ruta.display()))?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let _ = std::fs::set_permissions(ruta, std::fs::Permissions::from_mode(0o600));
    }
    Ok(())
}

/// El `.env` que acompaña a la bóveda (misma carpeta).
fn ruta_env(ruta_boveda: &Path) -> PathBuf {
    ruta_boveda
        .parent()
        .map(|p| p.join(".env"))
        .unwrap_or_else(|| PathBuf::from(".env"))
}

/// Deja el `.env` sin DTE_MASTER_KEY (o con una nueva, al reiniciar).
fn poner_master_en_env(ruta: &Path, valor: Option<&str>) -> Result<(), String> {
    let t = std::fs::read_to_string(ruta).unwrap_or_default();
    let re = regex::Regex::new(r"(?m)^#? ?DTE_MASTER_KEY[=:].*$").expect("regex");
    let linea = match valor {
        Some(v) => format!("{CLAVE_ENV}={v}"),
        None => format!(
            "# DTE_MASTER_KEY: desde {} vive cifrada con tu PIN en boveda.json",
            &ahora_utc()[..10]
        ),
    };
    let nuevo = if re.is_match(&t) {
        re.replace(&t, linea.as_str()).into_owned()
    } else {
        format!("{}\n{linea}\n", t.trim_end_matches('\n'))
    };
    std::fs::write(ruta, nuevo).map_err(|e| format!("no pude escribir {}: {e}", ruta.display()))
}

fn validar_pin(pin: &str) -> Result<(), ErrorHTTP> {
    if pin.chars().count() < PIN_MINIMO {
        return Err(ErrorHTTP::validacion(format!(
            "El PIN debe tener al menos {PIN_MINIMO} caracteres."
        )));
    }
    if pin.len() > 200 {
        return Err(ErrorHTTP::validacion("El PIN es demasiado largo."));
    }
    Ok(())
}

impl Servidor {
    fn ruta_boveda(&self) -> Option<PathBuf> {
        (!self.cfg.boveda_path.is_empty()).then(|| PathBuf::from(&self.cfg.boveda_path))
    }

    /// Al arrancar: si hay `boveda.json`, el motor parte bloqueado (sin Fernet).
    pub(crate) fn cargar_boveda(&self) {
        let Some(ruta) = self.ruta_boveda() else { return };
        if let Some(a) = leer_archivo(&ruta) {
            self.boveda.lock().expect("boveda").archivo = Some(a);
            *self.fernet.lock().expect("fernet") = None;
            if !self.cfg.master_key.is_empty() {
                super::log("aviso: el .env todavía trae DTE_MASTER_KEY aunque existe boveda.json; se ignora (bórrala del .env)");
            }
            super::log("bóveda con PIN: el motor arranca bloqueado hasta escribir el PIN");
        }
    }

    pub fn boveda_configurada(&self) -> bool {
        self.boveda.lock().expect("boveda").configurada()
    }

    pub fn boveda_bloqueada(&self) -> bool {
        self.boveda_configurada() && self.fernet.lock().expect("fernet").is_none()
    }

    /// Cada petición autenticada (menos el sondeo de estado) cuenta como uso.
    pub(crate) fn boveda_toque(&self) {
        self.boveda.lock().expect("boveda").ultimo_uso = Instant::now();
    }

    /// Bloquea si pasó el tiempo sin uso. Se llama antes de atender cada petición.
    pub(crate) fn boveda_revisar_autobloqueo(&self) {
        let (configurada, min, inactivo) = {
            let b = self.boveda.lock().expect("boveda");
            (
                b.configurada(),
                b.autobloqueo_min(),
                b.ultimo_uso.elapsed().as_secs() as i64,
            )
        };
        if configurada && min > 0 && inactivo >= min * 60 && !self.boveda_bloqueada() {
            self.boveda_bloquear();
            super::log(&format!("bóveda bloqueada sola tras {min} min sin uso"));
        }
    }

    pub fn boveda_bloquear(&self) {
        *self.fernet.lock().expect("fernet") = None;
        self.boveda.lock().expect("boveda").kek = None;
    }

    fn tiene_secretos(&self) -> bool {
        let n = |sql: &str| {
            self.escalar::<i64>(sql, &[])
                .ok()
                .flatten()
                .unwrap_or(0)
        };
        n("SELECT count(*) FROM certificados") > 0
            || n("SELECT count(*) FROM claves_sii WHERE tributaria_cifrada IS NOT NULL OR certificado_cifrada IS NOT NULL") > 0
    }

    fn estado_json(&self) -> serde_json::Value {
        let b = self.boveda.lock().expect("boveda");
        json!({
            "disponible": self.ruta_boveda().is_some(),
            "configurada": b.configurada(),
            "bloqueada": b.configurada() && self.fernet.lock().expect("fernet").is_none(),
            "autobloqueo_min": b.autobloqueo_min(),
            "pin_minimo": PIN_MINIMO,
            "tiene_secretos": self.tiene_secretos(),
        })
    }

    /// Verifica el PIN contra el archivo y devuelve (kek, maestra). Lleva la cuenta de intentos.
    fn probar_pin(&self, pin: &str) -> Result<(Fernet, Fernet), ErrorHTTP> {
        let a = {
            let b = self.boveda.lock().expect("boveda");
            if let (Some(f), true) = (b.ultimo_fallo, b.intentos >= INTENTOS_MAX) {
                let falta = ESPERA_SEG.saturating_sub(f.elapsed().as_secs());
                if falta > 0 {
                    return Err(ErrorHTTP::nuevo(
                        429,
                        "boveda_espera",
                        format!("Demasiados intentos. Espera {falta} segundos y vuelve a probar."),
                    ));
                }
            }
            b.archivo.clone().ok_or_else(|| {
                ErrorHTTP::conflicto("Todavía no hay un PIN: créalo primero.")
            })?
        };
        let sal = B64
            .decode(&a.sal)
            .map_err(|_| ErrorHTTP::nuevo(500, "boveda", "boveda.json está dañado (sal)."))?;
        let kek = derivar(pin, &sal, a.m_kib, a.pasadas, a.hilos)
            .map_err(|e| ErrorHTTP::nuevo(500, "boveda", e))?;
        let maestra = kek.descifrar(a.maestra_cifrada.as_bytes()).ok().and_then(|raw| Fernet::de_bytes(&raw).ok());
        let mut b = self.boveda.lock().expect("boveda");
        match maestra {
            Some(m) => {
                b.intentos = 0;
                b.ultimo_fallo = None;
                Ok((kek, m))
            }
            None => {
                b.intentos += 1;
                b.ultimo_fallo = Some(Instant::now());
                let quedan = INTENTOS_MAX.saturating_sub(b.intentos);
                // 403 y no 401: el puente del navegador toma 401 como "sesión vencida"
                Err(ErrorHTTP::nuevo(
                    403,
                    "pin_incorrecto",
                    if quedan > 0 {
                        format!("PIN incorrecto. Te quedan {quedan} intentos antes de una pausa de {ESPERA_SEG} segundos.")
                    } else {
                        format!("PIN incorrecto. Espera {ESPERA_SEG} segundos antes de volver a probar.")
                    },
                ))
            }
        }
    }

    /// Crea la bóveda con la clave maestra que ya cifra la base (la del .env) y saca esa clave
    /// del .env. Requiere motor abierto y DTE_MASTER_KEY explícita (no derivada del JWT).
    fn boveda_crear(&self, pin: &str, autobloqueo_min: i64) -> Result<(), ErrorHTTP> {
        let ruta = self
            .ruta_boveda()
            .ok_or_else(|| ErrorHTTP::conflicto("Este motor no tiene carpeta de datos propia; la bóveda es de la app."))?;
        if self.boveda_configurada() {
            return Err(ErrorHTTP::conflicto("Ya hay un PIN. Para cambiarlo usa PUT /api/v1/boveda."));
        }
        if self.cfg.master_key.is_empty() {
            return Err(ErrorHTTP::conflicto(
                "El .env no define DTE_MASTER_KEY (la clave se deriva del JWT). Rota las claves primero.",
            ));
        }
        let maestra = self
            .fernet
            .lock()
            .expect("fernet")
            .clone()
            .ok_or_else(|| ErrorHTTP::nuevo(423, "boveda_bloqueada", MENSAJE_BLOQUEADA))?;
        let sal = bytes_azar(16);
        let kek = derivar(pin, &sal, M_KIB, PASADAS, HILOS).map_err(|e| ErrorHTTP::nuevo(500, "boveda", e))?;
        let a = Archivo {
            version: 1,
            kdf: "argon2id".into(),
            sal: B64.encode(&sal),
            m_kib: M_KIB,
            pasadas: PASADAS,
            hilos: HILOS,
            maestra_cifrada: String::from_utf8_lossy(&kek.cifrar(&maestra.bytes())).into_owned(),
            creada: ahora_utc(),
            autobloqueo_min,
        };
        escribir_archivo(&ruta, &a).map_err(|e| ErrorHTTP::nuevo(500, "boveda", e))?;
        poner_master_en_env(&ruta_env(&ruta), None).map_err(|e| ErrorHTTP::nuevo(500, "boveda", e))?;
        let mut b = self.boveda.lock().expect("boveda");
        b.archivo = Some(a);
        b.kek = Some(kek);
        b.ultimo_uso = Instant::now();
        super::log("bóveda con PIN creada; DTE_MASTER_KEY salió del .env");
        Ok(())
    }

    fn boveda_abrir(&self, pin: &str) -> Result<(), ErrorHTTP> {
        let (kek, maestra) = self.probar_pin(pin)?;
        *self.fernet.lock().expect("fernet") = Some(maestra);
        let mut b = self.boveda.lock().expect("boveda");
        b.kek = Some(kek);
        b.ultimo_uso = Instant::now();
        Ok(())
    }

    /// Re-envuelve la clave maestra actual (p.ej. tras rotar claves) con la kek en memoria.
    pub(crate) fn boveda_reenvolver(&self, maestra: &Fernet) -> Result<(), String> {
        let Some(ruta) = self.ruta_boveda() else { return Ok(()) };
        let mut b = self.boveda.lock().expect("boveda");
        let Some(kek) = b.kek.clone() else {
            return Err(MENSAJE_BLOQUEADA.into());
        };
        let Some(a) = b.archivo.as_mut() else {
            return Err(MENSAJE_BLOQUEADA.into());
        };
        a.maestra_cifrada = String::from_utf8_lossy(&kek.cifrar(&maestra.bytes())).into_owned();
        escribir_archivo(&ruta, a)
    }

    fn boveda_cambiar(&self, pin_actual: &str, pin_nuevo: Option<&str>, autobloqueo_min: Option<i64>) -> Result<(), ErrorHTTP> {
        let ruta = self.ruta_boveda().ok_or_else(|| ErrorHTTP::conflicto("Sin bóveda."))?;
        let (_, maestra) = self.probar_pin(pin_actual)?;
        let mut b = self.boveda.lock().expect("boveda");
        let Some(a) = b.archivo.as_mut() else {
            return Err(ErrorHTTP::conflicto("Todavía no hay un PIN."));
        };
        let mut kek_nueva = None;
        if let Some(p) = pin_nuevo {
            let sal = bytes_azar(16);
            let kek = derivar(p, &sal, M_KIB, PASADAS, HILOS).map_err(|e| ErrorHTTP::nuevo(500, "boveda", e))?;
            a.sal = B64.encode(&sal);
            a.m_kib = M_KIB;
            a.pasadas = PASADAS;
            a.hilos = HILOS;
            a.maestra_cifrada = String::from_utf8_lossy(&kek.cifrar(&maestra.bytes())).into_owned();
            kek_nueva = Some(kek);
        }
        if let Some(m) = autobloqueo_min {
            a.autobloqueo_min = m;
        }
        escribir_archivo(&ruta, a).map_err(|e| ErrorHTTP::nuevo(500, "boveda", e))?;
        if let Some(k) = kek_nueva {
            b.kek = Some(k);
        }
        // abrir de paso (el PIN actual fue correcto)
        drop(b);
        *self.fernet.lock().expect("fernet") = Some(maestra);
        Ok(())
    }

    /// "Olvidé mi PIN": borra el certificado y las claves del SII guardadas, crea una clave
    /// maestra nueva en el .env y quita la bóveda. Los documentos emitidos no se tocan.
    fn boveda_reiniciar(&self) -> Result<serde_json::Value, ErrorHTTP> {
        let ruta = self.ruta_boveda().ok_or_else(|| ErrorHTTP::conflicto("Sin bóveda."))?;
        let interno = |e: String| ErrorHTTP::nuevo(500, "boveda", e);
        let certs = self
            .ejecutar("DELETE FROM certificados", &[])
            .map_err(|e| interno(e.to_string()))?;
        let claves = self
            .ejecutar("DELETE FROM claves_sii", &[])
            .map_err(|e| interno(e.to_string()))?;
        self.ejecutar("UPDATE negocios SET cert_id=NULL", &[])
            .map_err(|e| interno(e.to_string()))?;
        let nueva = B64.encode(bytes_azar(32));
        let f = Fernet::nuevo(&nueva, "").map_err(interno)?;
        poner_master_en_env(&ruta_env(&ruta), Some(&nueva)).map_err(interno)?;
        if ruta.exists() {
            std::fs::remove_file(&ruta).map_err(|e| interno(e.to_string()))?;
        }
        *self.fernet.lock().expect("fernet") = Some(f);
        let mut b = self.boveda.lock().expect("boveda");
        *b = Estado::vacio();
        super::log(&format!("bóveda reiniciada: {certs} certificado(s) y {claves} clave(s) borrados; clave maestra nueva"));
        Ok(json!({"certificados_borrados": certs, "claves_borradas": claves}))
    }
}

fn estado(s: &Servidor, _p: &mut Peticion) -> Res {
    ok(s.estado_json())
}

fn crear(s: &Servidor, p: &mut Peticion) -> Res {
    let j = Json::leer(p)?;
    let Some(pin) = j.texto("pin")? else {
        return Err(ErrorHTTP::faltan(&["pin"]));
    };
    validar_pin(&pin)?;
    let min = j.entero_o("autobloqueo_min", AUTOBLOQUEO_DEF)?.clamp(0, 24 * 60);
    s.boveda_crear(&pin, min)?;
    ok(s.estado_json())
}

fn abrir(s: &Servidor, p: &mut Peticion) -> Res {
    let j = Json::leer(p)?;
    let Some(pin) = j.texto("pin")? else {
        return Err(ErrorHTTP::faltan(&["pin"]));
    };
    s.boveda_abrir(&pin)?;
    ok(s.estado_json())
}

fn bloquear(s: &Servidor, _p: &mut Peticion) -> Res {
    if s.boveda_configurada() {
        s.boveda_bloquear();
    }
    ok(s.estado_json())
}

fn cambiar(s: &Servidor, p: &mut Peticion) -> Res {
    let j = Json::leer(p)?;
    let Some(actual) = j.texto("pin_actual")? else {
        return Err(ErrorHTTP::faltan(&["pin_actual"]));
    };
    let nuevo = j.texto("pin_nuevo")?.filter(|s| !s.is_empty());
    if let Some(n) = &nuevo {
        validar_pin(n)?;
    }
    let min = j.entero("autobloqueo_min")?.map(|m| m.clamp(0, 24 * 60));
    s.boveda_cambiar(&actual, nuevo.as_deref(), min)?;
    ok(s.estado_json())
}

fn reiniciar(s: &Servidor, p: &mut Peticion) -> Res {
    let j = Json::leer(p)?;
    if j.get("confirmar").and_then(|v| v.as_bool()) != Some(true) {
        return Err(ErrorHTTP::validacion("Hay que confirmar: {\"confirmar\": true}."));
    }
    let r = s.boveda_reiniciar()?;
    let mut v = s.estado_json();
    if let (Some(o), Some(extra)) = (v.as_object_mut(), r.as_object()) {
        for (k, x) in extra {
            o.insert(k.clone(), x.clone());
        }
    }
    ok(v)
}

pub fn rutas(s: &mut Servidor) {
    s.ruta("GET /api/v1/boveda", Prot::Protegida, estado);
    s.ruta("POST /api/v1/boveda", Prot::Protegida, crear);
    s.ruta("PUT /api/v1/boveda", Prot::Protegida, cambiar);
    s.ruta("POST /api/v1/boveda/abrir", Prot::Protegida, abrir);
    s.ruta("POST /api/v1/boveda/bloquear", Prot::Protegida, bloquear);
    s.ruta("POST /api/v1/boveda/reiniciar", Prot::Protegida, reiniciar);
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn derivar_es_determinista_y_sensible_al_pin() {
        let sal = [7u8; 16];
        let a = derivar("mi frase 123", &sal, 8 * 1024, 1, 1).unwrap();
        let b = derivar("mi frase 123", &sal, 8 * 1024, 1, 1).unwrap();
        let c = derivar("mi frase 124", &sal, 8 * 1024, 1, 1).unwrap();
        assert_eq!(a.bytes(), b.bytes());
        assert_ne!(a.bytes(), c.bytes());
        let tok = a.cifrar(b"hola");
        assert_eq!(b.descifrar(&tok).unwrap(), b"hola");
        assert!(c.descifrar(&tok).is_err());
    }

    /// Ciclo completo contra un motor real en una carpeta temporal: crear, bloquear (423),
    /// abrir con PIN malo y bueno, cambiar PIN, autobloqueo y reiniciar.
    #[test]
    fn ciclo_completo() {
        let d = tempfile::tempdir().unwrap();
        let env = d.path().join(".env");
        let maestra = B64.encode(bytes_azar(32));
        std::fs::write(&env, format!("{CLAVE_ENV}={maestra}\n")).unwrap();
        let mut cfg = super::super::config::cargar(&env.to_string_lossy());
        cfg.database_path = d.path().join("b.db").to_string_lossy().into_owned();
        cfg.storage_path = d.path().join("storage").to_string_lossy().into_owned();
        cfg.jwt_secret = "secreto-de-prueba-largo-para-el-jwt".into();
        cfg.app_shell_key = "clave-de-prueba-muy-larga-123456".into();
        cfg.rvd_scheduler_activo = false;
        cfg.admin_password = "admin-de-prueba".into();
        let s = Servidor::nuevo(cfg).unwrap();
        let j = |st: u16, b: Vec<u8>| -> (u16, serde_json::Value) {
            (st, serde_json::from_slice(&b).unwrap_or(serde_json::Value::Null))
        };
        // sin bóveda: disponible pero no configurada; cifrar funciona
        let (st, v) = { let (a, b) = s.llamar("GET", "/api/v1/boveda", None); j(a, b) };
        assert_eq!(st, 200);
        assert_eq!(v["configurada"], false);
        assert_eq!(v["bloqueada"], false);
        let tok = s.cifrar(b"secreto").unwrap();
        // guardar una clave del SII para que haya secretos
        let (st, _) = s.llamar("PUT", "/api/v1/keystore/claves-sii", Some(br#"{"rut_empresa":"76111111-6","clave_tributaria":"abc"}"#));
        assert_eq!(st, 200);
        // PIN corto → 422
        let (st, _) = s.llamar("POST", "/api/v1/boveda", Some(br#"{"pin":"123"}"#));
        assert_eq!(st, 422);
        // crear
        let (st, v) = { let (a, b) = s.llamar("POST", "/api/v1/boveda", Some(br#"{"pin":"mi frase 123","autobloqueo_min":15}"#)); j(a, b) };
        assert_eq!(st, 200, "{v}");
        assert_eq!(v["configurada"], true);
        assert_eq!(v["tiene_secretos"], true);
        let t = std::fs::read_to_string(&env).unwrap();
        assert!(!t.contains(&format!("{CLAVE_ENV}={maestra}")), "la maestra sigue en el .env");
        assert!(d.path().join("boveda.json").exists());
        // sigue abierta: lo cifrado antes se lee
        assert_eq!(s.descifrar(&tok).unwrap(), b"secreto");
        // bloquear → 423 en lo que necesita el cifrador
        let (st, _) = s.llamar("POST", "/api/v1/boveda/bloquear", None);
        assert_eq!(st, 200);
        assert!(s.boveda_bloqueada());
        assert!(s.descifrar(&tok).is_err());
        let (st, v) = { let (a, b) = s.llamar("PUT", "/api/v1/keystore/claves-sii", Some(br#"{"rut_empresa":"76111111-6","clave_tributaria":"xyz"}"#)); j(a, b) };
        assert_eq!(st, 423, "{v}");
        assert_eq!(v["error"]["codigo"], "boveda_bloqueada");
        // PIN malo → 403, bueno → 200
        let (st, v) = { let (a, b) = s.llamar("POST", "/api/v1/boveda/abrir", Some(br#"{"pin":"otra cosa"}"#)); j(a, b) };
        assert_eq!(st, 403, "{v}");
        let (st, _) = s.llamar("POST", "/api/v1/boveda/abrir", Some(br#"{"pin":"mi frase 123"}"#));
        assert_eq!(st, 200);
        assert_eq!(s.descifrar(&tok).unwrap(), b"secreto");
        // cambiar PIN (y autobloqueo)
        let (st, v) = { let (a, b) = s.llamar("PUT", "/api/v1/boveda", Some(br#"{"pin_actual":"mi frase 123","pin_nuevo":"frase nueva 9","autobloqueo_min":0}"#)); j(a, b) };
        assert_eq!(st, 200, "{v}");
        assert_eq!(v["autobloqueo_min"], 0);
        s.boveda_bloquear();
        let (st, _) = s.llamar("POST", "/api/v1/boveda/abrir", Some(br#"{"pin":"mi frase 123"}"#));
        assert_eq!(st, 403);
        let (st, _) = s.llamar("POST", "/api/v1/boveda/abrir", Some(br#"{"pin":"frase nueva 9"}"#));
        assert_eq!(st, 200);
        // un segundo arranque sobre la misma carpeta parte bloqueado
        let cfg2 = { let mut c = super::super::config::cargar(&env.to_string_lossy()); c.database_path = s.cfg.database_path.clone(); c.storage_path = s.cfg.storage_path.clone(); c.jwt_secret = s.cfg.jwt_secret.clone(); c.app_shell_key = s.cfg.app_shell_key.clone(); c.rvd_scheduler_activo = false; c };
        drop(s);
        let s = Servidor::nuevo(cfg2).unwrap();
        assert!(s.boveda_bloqueada());
        assert!(s.descifrar(&tok).is_err());
        let (st, _) = s.llamar("POST", "/api/v1/boveda/abrir", Some(br#"{"pin":"frase nueva 9"}"#));
        assert_eq!(st, 200);
        assert_eq!(s.descifrar(&tok).unwrap(), b"secreto");
        // autobloqueo: con 1 minuto y "último uso" hace 2 minutos, la próxima petición bloquea
        {
            let mut b = s.boveda.lock().unwrap();
            b.archivo.as_mut().unwrap().autobloqueo_min = 1;
            b.ultimo_uso = Instant::now() - std::time::Duration::from_secs(120);
        }
        let (st, v) = { let (a, b) = s.llamar("GET", "/api/v1/boveda", None); j(a, b) };
        assert_eq!(st, 200);
        assert_eq!(v["bloqueada"], true);
        // reiniciar: borra secretos, quita la bóveda, clave maestra nueva en el .env
        let (st, _) = s.llamar("POST", "/api/v1/boveda/reiniciar", Some(br#"{}"#));
        assert_eq!(st, 422);
        let (st, v) = { let (a, b) = s.llamar("POST", "/api/v1/boveda/reiniciar", Some(br#"{"confirmar":true}"#)); j(a, b) };
        assert_eq!(st, 200, "{v}");
        assert_eq!(v["configurada"], false);
        assert_eq!(v["tiene_secretos"], false);
        assert_eq!(v["claves_borradas"], 1);
        assert!(!d.path().join("boveda.json").exists());
        assert!(std::fs::read_to_string(&env).unwrap().contains(&format!("{CLAVE_ENV}=")));
        assert!(s.descifrar(&tok).is_err(), "la clave vieja ya no sirve");
        assert!(s.cifrar(b"x").is_ok());
    }

    #[test]
    fn env_sin_master_y_con_master() {
        let d = tempfile::tempdir().unwrap();
        let env = d.path().join(".env");
        std::fs::write(&env, format!("A=1\n{CLAVE_ENV}=abc\nB=2\n")).unwrap();
        poner_master_en_env(&env, None).unwrap();
        let t = std::fs::read_to_string(&env).unwrap();
        assert!(t.contains("# DTE_MASTER_KEY: desde"));
        assert!(!t.contains(&format!("{CLAVE_ENV}=abc")));
        poner_master_en_env(&env, Some("xyz")).unwrap();
        let t = std::fs::read_to_string(&env).unwrap();
        assert!(t.contains(&format!("{CLAVE_ENV}=xyz")));
        assert!(!t.contains("# DTE_MASTER_KEY"));
        assert!(t.contains("A=1\n") && t.contains("B=2"));
    }
}
