//! Lo que los CLI y el servidor MCP necesitan del motor sin pasar por la red: el keystore, la
//! rotación de claves y utilidades de azar (`nucleo/servidor/local.go`).

use super::errores::ErrorHTTP;
use super::fernet::Fernet;
use super::{ahora_utc, entero, texto, Servidor};
use crate::firma::{self, Certificado};
use base64::Engine;
use rusqlite::types::Value as Sql;

pub fn bytes_azar(n: usize) -> Vec<u8> {
    let mut b = vec![0u8; n];
    rand::RngCore::fill_bytes(&mut rand::rngs::OsRng, &mut b);
    b
}

/// `clave64`: n bytes aleatorios en base64url sin relleno.
pub fn clave64(n: usize) -> String {
    base64::engine::general_purpose::URL_SAFE_NO_PAD.encode(bytes_azar(n))
}

/// Metadatos de un certificado del keystore (sin secretos).
#[derive(Debug, Clone, Default, serde::Serialize)]
pub struct CertificadoInfo {
    pub id: i64,
    pub rut: String,
    pub nombre: String,
    pub alias: String,
    pub vencimiento: String,
    pub creado: String,
}

/// `rutDelCertificado` / `CertificadoDigital.rut_emisor`: "SIN-RUT" si no aparece.
pub fn rut_del_certificado(c: &Certificado) -> String {
    match c.rut_emisor() {
        Ok(r) if !r.is_empty() => r,
        _ => "SIN-RUT".into(),
    }
}

/// `NotAfter.UTC().Format("2006-01-02T15:04:05+00:00")`.
pub fn vencimiento(c: &Certificado) -> String {
    format!("{}+00:00", c.not_after())
}

fn nulo(s: &str) -> Sql {
    if s.is_empty() {
        Sql::Null
    } else {
        Sql::Text(s.to_string())
    }
}

impl Servidor {
    pub fn cifrar(&self, b: &[u8]) -> Vec<u8> {
        self.fernet.lock().expect("fernet").cifrar(b)
    }
    pub fn descifrar(&self, b: &[u8]) -> Result<Vec<u8>, String> {
        self.fernet.lock().expect("fernet").descifrar(b)
    }

    /// `keystore.guardar_certificado`: valida el .p12 con su clave y guarda ambos cifrados
    /// (upsert por cuenta+RUT, ids consecutivos).
    pub fn guardar_certificado(
        &self,
        cuenta: i64,
        p12: &[u8],
        clave: &str,
        nombre: &str,
        alias: &str,
    ) -> Result<CertificadoInfo, String> {
        let cert = firma::cargar_p12(p12, clave)
            .map_err(|e| format!("certificado inválido o contraseña incorrecta: {e}"))?;
        let rut = rut_del_certificado(&cert);
        let vence = vencimiento(&cert);
        let id = self
            .guardar_certificado_cifrado(
                cuenta,
                &rut,
                &vence,
                p12,
                clave,
                nulo(nombre),
                nulo(alias),
            )
            .map_err(|e| e.to_string())?;
        Ok(CertificadoInfo {
            id,
            rut,
            nombre: nombre.into(),
            alias: alias.into(),
            vencimiento: vence,
            creado: ahora_utc(),
        })
    }

    #[allow(clippy::too_many_arguments)]
    pub(crate) fn guardar_certificado_cifrado(
        &self,
        cuenta: i64,
        rut: &str,
        vence: &str,
        p12: &[u8],
        clave: &str,
        nombre: Sql,
        alias: Sql,
    ) -> Result<i64, rusqlite::Error> {
        let p12c = Sql::Blob(self.cifrar(p12));
        let clc = Sql::Blob(self.cifrar(clave.as_bytes()));
        let ahora = ahora_utc();
        if let Some(id) = self.escalar::<i64>(
            "SELECT id FROM certificados WHERE cuenta_id=? AND rut=?",
            &sql![cuenta, rut],
        )? {
            self.ejecutar(
                "UPDATE certificados SET nombre=?, alias=?, vencimiento=?, p12_cifrado=?, clave_cifrada=?, creado=? WHERE id=?",
                &sql![nombre, alias, vence, p12c, clc, ahora, id],
            )?;
            return Ok(id);
        }
        self.ejecutar_id(
            "INSERT INTO certificados (cuenta_id, rut, nombre, alias, vencimiento, p12_cifrado, clave_cifrada, creado) VALUES (?,?,?,?,?,?,?,?)",
            &sql![cuenta, rut, nombre, alias, vence, p12c, clc, ahora],
        )
    }

    /// `keystore.listar_certificados`.
    pub fn listar_certificados(&self, cuenta: i64) -> Result<Vec<CertificadoInfo>, String> {
        let filas = self
            .filas(
                "SELECT id, rut, COALESCE(nombre,'') AS nombre, COALESCE(alias,'') AS alias, COALESCE(vencimiento,'') AS vencimiento, creado FROM certificados WHERE cuenta_id=? ORDER BY id",
                &sql![cuenta],
            )
            .map_err(|e| e.to_string())?;
        Ok(filas
            .iter()
            .map(|f| CertificadoInfo {
                id: entero(&f["id"]),
                rut: texto(&f["rut"]),
                nombre: texto(&f["nombre"]),
                alias: texto(&f["alias"]),
                vencimiento: texto(&f["vencimiento"]),
                creado: texto(&f["creado"]),
            })
            .collect())
    }

    /// `keystore.eliminar_certificado`.
    pub fn eliminar_certificado(&self, cuenta: i64, id: i64) -> Result<bool, String> {
        let n = self
            .ejecutar(
                "DELETE FROM certificados WHERE id=? AND cuenta_id=?",
                &sql![id, cuenta],
            )
            .map_err(|e| e.to_string())?;
        Ok(n > 0)
    }

    /// `keystore._descifrar`: (p12, clave) de un certificado de la cuenta.
    pub fn descifrar_certificado(
        &self,
        cert_id: i64,
        cuenta: i64,
    ) -> Result<(Vec<u8>, String), String> {
        let fila = self
            .bytes_de(
                "SELECT p12_cifrado, clave_cifrada FROM certificados WHERE id=? AND cuenta_id=?",
                &sql![cert_id, cuenta],
            )
            .map_err(|e| e.to_string())?;
        let Some(f) = fila else {
            return Err(format!("Certificado {cert_id} no encontrado"));
        };
        let p12 = self.descifrar(&f[0])?;
        let clave = self.descifrar(&f[1])?;
        Ok((p12, String::from_utf8_lossy(&clave).into_owned()))
    }

    /// `keystore.cargar_certificado`: el certificado en memoria.
    pub fn certificado_del_keystore(
        &self,
        cert_id: i64,
        cuenta: i64,
    ) -> Result<Certificado, String> {
        let (p12, clave) = self.descifrar_certificado(cert_id, cuenta)?;
        firma::cargar_p12(&p12, &clave)
    }

    /// `keystore.pem_transitorio` (en memoria): cert y clave en PEM.
    pub fn pem_del_keystore(&self, cert_id: i64, cuenta: i64) -> Result<(String, String), String> {
        let (p12, clave) = self
            .descifrar_certificado(cert_id, cuenta)
            .map_err(|_| format!("Certificado {cert_id} no encontrado"))?;
        let cert = firma::cargar_p12(&p12, &clave)?;
        Ok((cert.cert_pem(), cert.key_pem()?))
    }

    /// `RotarClaves` (rotar_claves.py): descifra TODO lo cifrado con la clave actual, genera
    /// JWT_SECRET_KEY y DTE_MASTER_KEY nuevos, re-cifra, escribe el .env (y acota CORS_ORIGINS a
    /// localhost), resetea la clave de `admin` y verifica. Si algo falla antes de re-cifrar, no
    /// toca nada. Devuelve la clave nueva de admin.
    pub fn rotar_claves(&self, ruta_env: &str, admin_password: &str) -> Result<String, String> {
        let mut certs: Vec<(i64, Vec<u8>, Vec<u8>)> = Vec::new();
        {
            let c = self.alm.conexion();
            let mut st = c
                .prepare("SELECT id, p12_cifrado, clave_cifrada FROM certificados")
                .map_err(|e| e.to_string())?;
            let mut rows = st.query([]).map_err(|e| e.to_string())?;
            while let Some(r) = rows.next().map_err(|e| e.to_string())? {
                let id: i64 = r.get(0).map_err(|e| e.to_string())?;
                let p12c = blob(r.get_ref(1).map_err(|e| e.to_string())?);
                let clc = blob(r.get_ref(2).map_err(|e| e.to_string())?);
                certs.push((id, p12c, clc));
            }
        }
        let mut claros = Vec::new();
        for (id, p12c, clc) in &certs {
            let p12 = self
                .descifrar(p12c)
                .map_err(|e| format!("no se pudo descifrar el certificado id={id} con la clave actual: {e} (abortado, no se cambió nada)"))?;
            let cl = self.descifrar(clc).map_err(|e| {
                format!("no se pudo descifrar la clave del certificado id={id}: {e} (abortado)")
            })?;
            claros.push((*id, p12, cl));
        }
        let mut claves: Vec<ClaveCifrada> = Vec::new();
        {
            let c = self.alm.conexion();
            let mut st = c
                .prepare("SELECT id, tributaria_cifrada, certificado_cifrada FROM claves_sii")
                .map_err(|e| e.to_string())?;
            let mut rows = st.query([]).map_err(|e| e.to_string())?;
            while let Some(r) = rows.next().map_err(|e| e.to_string())? {
                let id: i64 = r.get(0).map_err(|e| e.to_string())?;
                let t = blob(r.get_ref(1).map_err(|e| e.to_string())?);
                let cc = blob(r.get_ref(2).map_err(|e| e.to_string())?);
                claves.push((
                    id,
                    (!t.is_empty()).then_some(t),
                    (!cc.is_empty()).then_some(cc),
                ));
            }
        }
        let mut claves_claras = Vec::new();
        for (id, t, cc) in &claves {
            let tt = match t {
                Some(b) => Some(
                    self.descifrar(b)
                        .map_err(|e| format!("claves_sii id={id}: {e} (abortado)"))?,
                ),
                None => None,
            };
            let c2 = match cc {
                Some(b) => Some(
                    self.descifrar(b)
                        .map_err(|e| format!("claves_sii id={id}: {e} (abortado)"))?,
                ),
                None => None,
            };
            claves_claras.push((*id, tt, c2));
        }
        // secretos nuevos
        let nuevo_jwt = clave64(48);
        let nuevo_master = base64::engine::general_purpose::URL_SAFE.encode(bytes_azar(32));
        let nuevo = Fernet::nuevo(&nuevo_master, &nuevo_jwt)?;
        let admin = if admin_password.is_empty() {
            clave64(12)
        } else {
            admin_password.to_string()
        };
        let h = super::auth::hash_password(&admin);
        {
            let mut c = self.alm.conexion();
            let tx = c.transaction().map_err(|e| e.to_string())?;
            for (id, p12, cl) in &claros {
                tx.execute(
                    "UPDATE certificados SET p12_cifrado=?, clave_cifrada=? WHERE id=?",
                    rusqlite::params![
                        Sql::Blob(nuevo.cifrar(p12)),
                        Sql::Blob(nuevo.cifrar(cl)),
                        id
                    ],
                )
                .map_err(|e| e.to_string())?;
            }
            for (id, t, cc) in &claves_claras {
                let tv = t
                    .as_ref()
                    .map(|b| Sql::Blob(nuevo.cifrar(b)))
                    .unwrap_or(Sql::Null);
                let cv = cc
                    .as_ref()
                    .map(|b| Sql::Blob(nuevo.cifrar(b)))
                    .unwrap_or(Sql::Null);
                tx.execute(
                    "UPDATE claves_sii SET tributaria_cifrada=?, certificado_cifrada=? WHERE id=?",
                    rusqlite::params![tv, cv, id],
                )
                .map_err(|e| e.to_string())?;
            }
            tx.execute(
                "UPDATE usuarios SET hashed_password=? WHERE username='admin'",
                rusqlite::params![h],
            )
            .map_err(|e| e.to_string())?;
            tx.commit().map_err(|e| e.to_string())?;
        }
        *self.fernet.lock().expect("fernet") = nuevo;
        // .env
        let mut t = std::fs::read_to_string(ruta_env).unwrap_or_default();
        for (k, v) in [
            ("JWT_SECRET_KEY", nuevo_jwt.as_str()),
            ("DTE_MASTER_KEY", nuevo_master.as_str()),
            (
                "CORS_ORIGINS",
                "http://localhost:8000,http://127.0.0.1:8000",
            ),
        ] {
            let re = regex::Regex::new(&format!(r"(?m)^{k}=.*$")).expect("regex");
            if re.is_match(&t) {
                t = re.replace_all(&t, format!("{k}={v}")).into_owned();
            } else {
                t = format!("{}\n{k}={v}\n", t.trim_end_matches('\n'));
            }
        }
        std::fs::write(ruta_env, t).map_err(|e| {
            format!("la base ya está re-cifrada pero no se pudo escribir {ruta_env}: {e}. DTE_MASTER_KEY={} JWT_SECRET_KEY={}", nuevo_master, nuevo_jwt)
        })?;
        // verificación
        for (id, _, _) in &claros {
            let f = self
                .bytes_de(
                    "SELECT p12_cifrado, clave_cifrada FROM certificados WHERE id=?",
                    &sql![*id],
                )
                .map_err(|e| e.to_string())?
                .ok_or_else(|| format!("certificado id={id} desapareció"))?;
            let p12 = self.descifrar(&f[0]).map_err(|e| {
                format!(
                    "verificación: el certificado id={id} no se descifra con la clave nueva: {e}"
                )
            })?;
            let cl = self.descifrar(&f[1]).map_err(|e| {
                format!(
                    "verificación: el certificado id={id} no se descifra con la clave nueva: {e}"
                )
            })?;
            firma::cargar_p12(&p12, &String::from_utf8_lossy(&cl))
                .map_err(|e| format!("verificación: el certificado id={id}: {e}"))?;
        }
        Ok(admin)
    }
}

/// (id, tributaria cifrada, certificado cifrada) de `claves_sii`.
type ClaveCifrada = (i64, Option<Vec<u8>>, Option<Vec<u8>>);

fn blob(v: rusqlite::types::ValueRef<'_>) -> Vec<u8> {
    match v {
        rusqlite::types::ValueRef::Blob(b) => b.to_vec(),
        rusqlite::types::ValueRef::Text(t) => t.to_vec(),
        _ => Vec::new(),
    }
}

impl From<String> for ErrorHTTP {
    fn from(m: String) -> Self {
        ErrorHTTP::validacion(m)
    }
}
