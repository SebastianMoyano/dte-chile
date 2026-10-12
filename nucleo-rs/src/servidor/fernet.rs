//! Fernet (`cryptography.fernet`) compatible con Python: token = base64url( 0x80 | timestamp 8B BE |
//! IV 16B | AES-128-CBC/PKCS7 | HMAC-SHA256 32B ). La clave son 32 bytes en base64url: los
//! primeros 16 firman, los últimos 16 cifran. Lo que Python cifró en `certificados` y
//! `claves_sii` se descifra aquí tal cual, y lo que Rust cifra lo leen Python y Go.
//!
//! Clave maestra: DTE_MASTER_KEY; si no está, se deriva de sha256(JWT_SECRET_KEY)
//! (`core/keystore.py::_fernet`).

use aes::cipher::{block_padding::Pkcs7, BlockDecryptMut, BlockEncryptMut, KeyIvInit};
use base64::Engine;
use hmac::{Hmac, Mac};
use sha2::{Digest, Sha256};

type Enc = cbc::Encryptor<aes::Aes128>;
type Dec = cbc::Decryptor<aes::Aes128>;
type HmacSha256 = Hmac<Sha256>;

#[derive(Clone)]
pub struct Fernet {
    firma: [u8; 16],
    cifra: [u8; 16],
}

const B64: base64::engine::GeneralPurpose = base64::engine::general_purpose::URL_SAFE;

impl Fernet {
    pub fn nuevo(clave_b64: &str, jwt_secret: &str) -> Result<Fernet, String> {
        let raw: Vec<u8> = if !clave_b64.is_empty() {
            B64.decode(clave_b64)
                .or_else(|_| base64::engine::general_purpose::URL_SAFE_NO_PAD.decode(clave_b64))
                .map_err(|_| "DTE_MASTER_KEY no es base64url".to_string())?
        } else {
            Sha256::digest(jwt_secret.as_bytes()).to_vec()
        };
        if raw.len() != 32 {
            return Err("la clave Fernet debe tener 32 bytes".into());
        }
        let mut f = Fernet {
            firma: [0; 16],
            cifra: [0; 16],
        };
        f.firma.copy_from_slice(&raw[..16]);
        f.cifra.copy_from_slice(&raw[16..]);
        Ok(f)
    }

    pub fn cifrar(&self, texto: &[u8]) -> Vec<u8> {
        let mut iv = [0u8; 16];
        rand::RngCore::fill_bytes(&mut rand::rngs::OsRng, &mut iv);
        let cif = Enc::new(&self.cifra.into(), &iv.into()).encrypt_padded_vec_mut::<Pkcs7>(texto);
        let ts = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_secs())
            .unwrap_or(0);
        let mut tok = Vec::with_capacity(1 + 8 + 16 + cif.len() + 32);
        tok.push(0x80);
        tok.extend_from_slice(&ts.to_be_bytes());
        tok.extend_from_slice(&iv);
        tok.extend_from_slice(&cif);
        let mut mac = HmacSha256::new_from_slice(&self.firma).expect("hmac");
        mac.update(&tok);
        tok.extend_from_slice(&mac.finalize().into_bytes());
        B64.encode(tok).into_bytes()
    }

    pub fn descifrar(&self, token: &[u8]) -> Result<Vec<u8>, String> {
        let raw = B64
            .decode(token)
            .map_err(|_| "token Fernet inválido".to_string())?;
        if raw.len() < 1 + 8 + 16 + 32 || raw[0] != 0x80 || !(raw.len() - 57).is_multiple_of(16) {
            return Err("token Fernet inválido".into());
        }
        let (cuerpo, firma) = raw.split_at(raw.len() - 32);
        let mut mac = HmacSha256::new_from_slice(&self.firma).expect("hmac");
        mac.update(cuerpo);
        if mac.verify_slice(firma).is_err() {
            return Err("token Fernet inválido (firma)".into());
        }
        let iv: [u8; 16] = raw[9..25].try_into().expect("iv");
        let cif = &raw[25..raw.len() - 32];
        Dec::new(&self.cifra.into(), &iv.into())
            .decrypt_padded_vec_mut::<Pkcs7>(cif)
            .map_err(|_| "token Fernet inválido (relleno)".to_string())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    // Vectores generados con cryptography.fernet (2026-10-10), los mismos del test de Go.
    const CLAVE: &str = "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8=";
    const TOKEN_PY: &str = "gAAAAABqyaqzGX45e4JtxfUl0M4d-HR5YXA7R4YEROUNU8or8ncKYcLZW6giUmUa4wzEiTzr5y1tZUmjgUKfy1zut27OJFoYwWKzxcgsltjE3um6YFx2_2o=";

    #[test]
    fn compatible_con_python() {
        let f = Fernet::nuevo(CLAVE, "").unwrap();
        assert_eq!(
            f.descifrar(TOKEN_PY.as_bytes()).unwrap(),
            "hola ñandú 2026".as_bytes()
        );
        let tok = f.cifrar("ida y vuelta ñ".as_bytes());
        assert!(tok.starts_with(b"gAAAAA"));
        assert_eq!(f.descifrar(&tok).unwrap(), "ida y vuelta ñ".as_bytes());
        let mut malo = tok[..tok.len() - 5].to_vec();
        malo.extend_from_slice(b"AAAA=");
        assert!(f.descifrar(&malo).is_err());
        assert!(Fernet::nuevo("", "secreto-jwt").is_ok());
    }
}
