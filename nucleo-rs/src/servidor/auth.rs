//! Autenticación, réplica de `core/auth.py::requerir_autenticacion`: acepta un JWT (HS256 con
//! JWT_SECRET_KEY, claim `sub` = username), la clave efímera de la app (APP_SHELL_KEY, actúa
//! como el usuario dueño: el de menor id) o una API key (`dte_…`, sha256 en api_keys). 401 con
//! el mismo mensaje y envoltorio que Python. Las contraseñas van con `sha256_crypt` de passlib
//! (`$5$rounds=535000$…`), implementado aquí para verificar y producir los mismos hashes.

use super::errores::ErrorHTTP;
use super::http::Peticion;
use super::Servidor;
use base64::Engine;
use hmac::{Hmac, Mac};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};

/// Lo que las rutas reciben (el dict de Python: id, username, tipo…).
#[derive(Debug, Clone, Default)]
pub struct Usuario {
    pub id: i64,
    pub username: String,
    /// "usuario" | "apikey"
    pub tipo: String,
    /// "jwt" | "app" (APP_SHELL_KEY) | "apikey"
    pub via: String,
    pub apikey_id: i64,
}

pub const NO_AUTENTICADO: &str =
    "Se requiere un JWT o una API key válidos (Authorization: Bearer).";

const B64URL: base64::engine::GeneralPurpose = base64::engine::general_purpose::URL_SAFE_NO_PAD;

/// `firmaHS256`: HMAC-SHA256 en base64url sin relleno.
pub fn firma_hs256(secreto: &str, datos: &str) -> String {
    let mut mac = Hmac::<Sha256>::new_from_slice(secreto.as_bytes()).expect("hmac");
    mac.update(datos.as_bytes());
    B64URL.encode(mac.finalize().into_bytes())
}

/// `crear_access_token({"sub": username})`.
pub fn crear_jwt(secreto: &str, username: &str, expira_min: i64) -> String {
    let cab = B64URL.encode(br#"{"alg":"HS256","typ":"JWT"}"#);
    let exp = ahora_unix() + expira_min * 60;
    let cuerpo = B64URL
        .encode(serde_json::to_vec(&json!({"sub": username, "exp": exp})).unwrap_or_default());
    let firma = firma_hs256(secreto, &format!("{cab}.{cuerpo}"));
    format!("{cab}.{cuerpo}.{firma}")
}

pub fn ahora_unix() -> i64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs() as i64)
        .unwrap_or(0)
}

/// `verificarJWT`: firma HS256 y expiración; devuelve el `sub`.
pub fn verificar_jwt(secreto: &str, token: &str) -> Option<String> {
    let partes: Vec<&str> = token.split('.').collect();
    if partes.len() != 3 || secreto.is_empty() {
        return None;
    }
    let dec = |p: &str| B64URL.decode(p.trim_end_matches('=')).ok();
    let cab: Value = serde_json::from_slice(&dec(partes[0])?).ok()?;
    if cab.get("alg").and_then(Value::as_str) != Some("HS256") {
        return None;
    }
    let firma = dec(partes[2])?;
    let mut mac = Hmac::<Sha256>::new_from_slice(secreto.as_bytes()).ok()?;
    mac.update(format!("{}.{}", partes[0], partes[1]).as_bytes());
    mac.verify_slice(&firma).ok()?;
    let cuerpo: Value = serde_json::from_slice(&dec(partes[1])?).ok()?;
    let sub = cuerpo.get("sub").and_then(Value::as_str).unwrap_or("");
    if sub.is_empty() {
        return None;
    }
    let exp = cuerpo.get("exp").and_then(Value::as_f64).unwrap_or(0.0);
    if exp != 0.0 && ahora_unix() >= exp as i64 {
        return None;
    }
    Some(sub.to_string())
}

// ---------------------------------------------------------------- sha256_crypt (passlib)

pub const ROUNDS_PASSLIB: u32 = 535_000;
const ITOA64: &[u8; 64] = b"./0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz";

fn b64_crypt(out: &mut String, b2: u8, b1: u8, b0: u8, n: usize) {
    let mut w: u32 = ((b2 as u32) << 16) | ((b1 as u32) << 8) | b0 as u32;
    for _ in 0..n {
        out.push(ITOA64[(w & 0x3f) as usize] as char);
        w >>= 6;
    }
}

/// El algoritmo SHA-crypt (Drepper) con SHA-256: `$5$rounds=N$salt$hash`.
pub fn sha256_crypt(clave: &[u8], salt: &str, rounds: u32) -> String {
    let salt_b = salt.as_bytes();
    let mut b = Sha256::new();
    b.update(clave);
    b.update(salt_b);
    b.update(clave);
    let db = b.finalize();
    let mut a = Sha256::new();
    a.update(clave);
    a.update(salt_b);
    let mut n = clave.len();
    while n > 32 {
        a.update(db);
        n -= 32;
    }
    a.update(&db[..n]);
    let mut bits = clave.len();
    while bits > 0 {
        if bits & 1 == 1 {
            a.update(db);
        } else {
            a.update(clave);
        }
        bits >>= 1;
    }
    let da = a.finalize();
    let mut dp = Sha256::new();
    for _ in 0..clave.len() {
        dp.update(clave);
    }
    let dp = dp.finalize();
    let mut p = Vec::with_capacity(clave.len());
    while p.len() < clave.len() {
        let falta = clave.len() - p.len();
        p.extend_from_slice(&dp[..falta.min(32)]);
    }
    let mut ds = Sha256::new();
    for _ in 0..(16 + da[0] as usize) {
        ds.update(salt_b);
    }
    let ds = ds.finalize();
    let mut s = Vec::with_capacity(salt_b.len());
    while s.len() < salt_b.len() {
        let falta = salt_b.len() - s.len();
        s.extend_from_slice(&ds[..falta.min(32)]);
    }
    let mut c: [u8; 32] = da.into();
    for i in 0..rounds as usize {
        let mut h = Sha256::new();
        if i & 1 == 1 {
            h.update(&p);
        } else {
            h.update(c);
        }
        if i % 3 != 0 {
            h.update(&s);
        }
        if i % 7 != 0 {
            h.update(&p);
        }
        if i & 1 == 1 {
            h.update(c);
        } else {
            h.update(&p);
        }
        c = h.finalize().into();
    }
    let mut out = String::with_capacity(43);
    let grupos: [(usize, usize, usize); 10] = [
        (0, 10, 20),
        (21, 1, 11),
        (12, 22, 2),
        (3, 13, 23),
        (24, 4, 14),
        (15, 25, 5),
        (6, 16, 26),
        (27, 7, 17),
        (18, 28, 8),
        (9, 19, 29),
    ];
    for (x, y, z) in grupos {
        b64_crypt(&mut out, c[x], c[y], c[z], 4);
    }
    b64_crypt(&mut out, 0, c[31], c[30], 3);
    if rounds == 5000 {
        format!("$5${salt}${out}")
    } else {
        format!("$5$rounds={rounds}${salt}${out}")
    }
}

/// `hashPassword`: salt de 16 caracteres del alfabeto de crypt y las rondas de passlib.
pub fn hash_password(clave: &str) -> String {
    let mut raw = [0u8; 16];
    rand::RngCore::fill_bytes(&mut rand::rngs::OsRng, &mut raw);
    let salt: String = raw
        .iter()
        .map(|b| ITOA64[(*b & 63) as usize] as char)
        .collect();
    sha256_crypt(clave.as_bytes(), &salt, ROUNDS_PASSLIB)
}

/// `verificarPassword`: acepta `$5$rounds=N$salt$hash` y `$5$salt$hash`.
pub fn verificar_password(clave: &str, hash: &str) -> bool {
    let Some(resto) = hash.strip_prefix("$5$") else {
        return false;
    };
    let (rounds, resto) = match resto.strip_prefix("rounds=") {
        Some(r) => {
            let Some((n, resto)) = r.split_once('$') else {
                return false;
            };
            let Ok(n) = n.parse::<u32>() else {
                return false;
            };
            (n.clamp(1000, 999_999_999), resto)
        }
        None => (5000, resto),
    };
    let Some((salt, _)) = resto.split_once('$') else {
        return false;
    };
    let calc = sha256_crypt(clave.as_bytes(), salt, rounds);
    calc.len() == hash.len()
        && calc
            .bytes()
            .zip(hash.bytes())
            .fold(0u8, |acc, (a, b)| acc | (a ^ b))
            == 0
}

// ---------------------------------------------------------------- en el servidor

impl Servidor {
    /// `autenticar`: JWT → clave de la app → API key.
    pub fn autenticar(&self, p: &Peticion) -> Result<Usuario, ErrorHTTP> {
        let auth = p.cabecera("Authorization");
        if !auth.to_ascii_lowercase().starts_with("bearer ") {
            return Err(ErrorHTTP::autenticacion(NO_AUTENTICADO));
        }
        let token = auth[7..].trim();
        if token.is_empty() {
            return Err(ErrorHTTP::autenticacion(NO_AUTENTICADO));
        }
        if let Some(username) = verificar_jwt(&self.cfg.jwt_secret, token) {
            if let Some(mut u) = self.usuario_por_username(&username)? {
                u.via = "jwt".into();
                self.tocar_ultimo_acceso(u.id);
                return Ok(u);
            }
        }
        let k = self.cfg.app_shell_key.as_bytes();
        if k.len() >= 24
            && k.len() == token.len()
            && k.iter()
                .zip(token.bytes())
                .fold(0u8, |a, (x, y)| a | (x ^ y))
                == 0
        {
            if let Some(mut u) = self.usuario_dueno()? {
                u.via = "app".into();
                self.tocar_ultimo_acceso(u.id);
                return Ok(u);
            }
        }
        if token.starts_with("dte_") {
            if let Some(u) = self.verificar_api_key(token)? {
                return Ok(u);
            }
        }
        Err(ErrorHTTP::autenticacion(NO_AUTENTICADO))
    }

    fn usuario_por_username(&self, username: &str) -> Result<Option<Usuario>, ErrorHTTP> {
        let f = self.fila(
            "SELECT id, username FROM usuarios WHERE username=? AND activo=1",
            &sql![username],
        )?;
        Ok(f.map(|m| Usuario {
            id: super::entero(&m["id"]),
            username: super::texto(&m["username"]),
            tipo: "usuario".into(),
            ..Default::default()
        }))
    }

    fn usuario_dueno(&self) -> Result<Option<Usuario>, ErrorHTTP> {
        let f = self.fila("SELECT id, username FROM usuarios ORDER BY id LIMIT 1", &[])?;
        Ok(f.map(|m| Usuario {
            id: super::entero(&m["id"]),
            username: super::texto(&m["username"]),
            tipo: "usuario".into(),
            ..Default::default()
        }))
    }

    fn tocar_ultimo_acceso(&self, id: i64) {
        let _ = self.ejecutar(
            "UPDATE usuarios SET ultimo_acceso=? WHERE id=?",
            &sql![super::ahora_python(), id],
        );
    }

    fn verificar_api_key(&self, token: &str) -> Result<Option<Usuario>, ErrorHTTP> {
        let kh = hex(&Sha256::digest(token.as_bytes()));
        let Some(f) = self.fila(
            "SELECT id, nombre FROM api_keys WHERE key_hash=? AND activo=1",
            &sql![kh],
        )?
        else {
            return Ok(None);
        };
        let id = super::entero(&f["id"]);
        let _ = self.ejecutar(
            "UPDATE api_keys SET ultimo_uso=? WHERE id=?",
            &sql![super::ahora_python(), id],
        );
        Ok(Some(Usuario {
            id: 0,
            username: format!("apikey:{}", super::texto(&f["nombre"])),
            tipo: "apikey".into(),
            via: "apikey".into(),
            apikey_id: id,
        }))
    }

    /// `TokenValido`: ¿es un JWT válido del proyecto o la clave de la app? (auth del MCP por HTTP).
    pub fn token_valido(&self, token: &str) -> bool {
        (!self.cfg.app_shell_key.is_empty() && token == self.cfg.app_shell_key)
            || verificar_jwt(&self.cfg.jwt_secret, token).is_some()
    }

    /// `cuentaID`: Python usa usuario["id"] (None para API keys → 0: no encuentra nada).
    pub fn cuenta_id(&self, p: &Peticion) -> i64 {
        match &p.usuario {
            Some(u) if u.tipo == "usuario" => u.id,
            _ => 0,
        }
    }
}

pub fn hex(b: &[u8]) -> String {
    b.iter().map(|x| format!("{x:02x}")).collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    // Hash generado con passlib (2026-10-10), el mismo del test de Go.
    const HASH_PASSLIB: &str =
        "$5$rounds=535000$pQhQOPSGKmITcouG$A5K/tIlcDTz9my7b63d5nod.5..CzYzcIy.ibOkTCEA";

    #[test]
    fn sha256_crypt_compatible_passlib() {
        assert!(verificar_password("clave-de-prueba", HASH_PASSLIB));
        assert!(!verificar_password("otra", HASH_PASSLIB));
        // vector clásico de la especificación (rounds=5000)
        assert_eq!(
            sha256_crypt(b"Hello world!", "saltstring", 5000),
            "$5$saltstring$5B8vYYiY.CVt1RlTTf8KbXBH3hsxY/GNooZaBBGWEc5"
        );
        let h = hash_password("nueva-clave");
        assert!(h.starts_with("$5$rounds=535000$") && verificar_password("nueva-clave", &h));
    }

    #[test]
    fn jwt_ida_y_vuelta() {
        let t = crear_jwt("secreto-de-prueba", "alguien", 60);
        assert_eq!(
            verificar_jwt("secreto-de-prueba", &t).as_deref(),
            Some("alguien")
        );
        assert!(verificar_jwt("otro", &t).is_none());
    }
}
