//! El motor HTTP en Rust (fase 8 del port): atiende `/api/v1` con el mismo contrato que el
//! motor Python y que `nucleo/servidor` (Go). Lo que no esté aquí se reenvía al motor Python
//! (`--motor`), o responde 503. Cada ruta se compara contra Python con `tools/contrato_api.py`.

pub mod auth;
pub mod config;
pub mod errores;
pub mod fernet;
pub mod http;

mod apikeys;
mod caf;
mod consulta;
mod db;
mod demo;
mod documentos;
mod emitir;
mod f29;
mod generar;
mod keystore;
pub mod local;
mod lote;
mod mipyme;
mod monitoreo;
mod portal_rutas;
mod portalks;
pub mod rvd;
mod simulacion;
mod usuarios;
mod valores_rutas;
mod xsd_rutas;

pub use config::Config;
pub use local::CertificadoInfo;

use crate::almacen::Almacen;
use crate::firma::Certificado;
use errores::{ErrorHTTP, Res};
use http::{Enrutado, Enrutador, Peticion, Respuesta};
use rusqlite::types::{Value as Sql, ValueRef};
use serde_json::{json, Map, Value};
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};

/// Lo que puede ir como parámetro SQL (`sql![…]`).
pub trait AParam {
    fn sql(self) -> Sql;
}
impl AParam for &str {
    fn sql(self) -> Sql {
        Sql::Text(self.to_string())
    }
}
impl AParam for String {
    fn sql(self) -> Sql {
        Sql::Text(self)
    }
}
impl AParam for &String {
    fn sql(self) -> Sql {
        Sql::Text(self.clone())
    }
}
impl AParam for i64 {
    fn sql(self) -> Sql {
        Sql::Integer(self)
    }
}
impl AParam for i32 {
    fn sql(self) -> Sql {
        Sql::Integer(self as i64)
    }
}
impl AParam for usize {
    fn sql(self) -> Sql {
        Sql::Integer(self as i64)
    }
}
impl AParam for bool {
    fn sql(self) -> Sql {
        Sql::Integer(self as i64)
    }
}
impl AParam for Vec<u8> {
    fn sql(self) -> Sql {
        Sql::Blob(self)
    }
}
impl AParam for Sql {
    fn sql(self) -> Sql {
        self
    }
}
impl AParam for Option<String> {
    fn sql(self) -> Sql {
        self.map(Sql::Text).unwrap_or(Sql::Null)
    }
}
impl AParam for Option<i64> {
    fn sql(self) -> Sql {
        self.map(Sql::Integer).unwrap_or(Sql::Null)
    }
}

/// Quién puede llamar a una ruta.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Prot {
    Publica,
    /// JWT, clave de la app o API key (`protegido`)
    Protegida,
    /// SOLO un JWT de usuario (`requiereUsuario`)
    Usuario,
}

pub type Manejador = fn(&Servidor, &mut Peticion) -> Res;

/// El servidor: la base, la configuración, el cifrado del keystore y las rutas.
pub struct Servidor {
    pub cfg: Config,
    pub alm: Almacen,
    pub fernet: Mutex<fernet::Fernet>,
    rutas: Enrutador<(Prot, Manejador)>,
    /// el certificado de la práctica, en memoria
    cert_demo: Mutex<Option<Certificado>>,
    rvd: Mutex<rvd::EstadoRVD>,
    parar_rvd: std::sync::atomic::AtomicBool,
    /// la clave aleatoria del admin si se creó en este arranque (y solo entonces)
    pub clave_admin_generada: String,
}

impl Servidor {
    /// `Nuevo`: abre (y migra) la base, arma las rutas y asegura el admin.
    pub fn nuevo(cfg: Config) -> Result<Arc<Servidor>, String> {
        let alm = Almacen::abrir_y_migrar(&cfg.database_path)
            .map_err(|e| format!("base de datos {}: {e}", cfg.database_path))?;
        let fer = fernet::Fernet::nuevo(&cfg.master_key, &cfg.jwt_secret)?;
        let mut s = Servidor {
            rvd: Mutex::new(rvd::EstadoRVD::nuevo(cfg.rvd_intervalo_seg)),
            cfg,
            alm,
            fernet: Mutex::new(fer),
            rutas: Enrutador::default(),
            cert_demo: Mutex::new(None),
            parar_rvd: std::sync::atomic::AtomicBool::new(false),
            clave_admin_generada: String::new(),
        };
        s.registrar_rutas();
        s.asegurar_admin().map_err(|e| e.mensaje)?;
        let s = Arc::new(s);
        rvd::iniciar_programador(&s);
        Ok(s)
    }

    /// `Cerrar`: detiene el programador de RVD (la base se cierra al soltar el Arc).
    pub fn cerrar(&self) {
        self.parar_rvd
            .store(true, std::sync::atomic::Ordering::SeqCst);
    }

    /// Si no hay ningún usuario, crea `admin` con ADMIN_PASSWORD o con una clave aleatoria que
    /// se registra UNA sola vez en el log.
    fn asegurar_admin(&mut self) -> Result<(), ErrorHTTP> {
        let n: i64 = self
            .escalar("SELECT COUNT(*) FROM usuarios", &[])?
            .unwrap_or(0);
        if n > 0 {
            return Ok(());
        }
        let (clave, generada) = if self.cfg.admin_password.is_empty() {
            (local::clave64(12), true)
        } else {
            (self.cfg.admin_password.clone(), false)
        };
        let h = auth::hash_password(&clave);
        self.ejecutar(
            "INSERT INTO usuarios (username, hashed_password, nombre_completo, email, creado_en) VALUES (?, ?, ?, ?, ?)",
            &sql!["admin", h, "Administrador", "admin@localhost", ahora_python()],
        )?;
        log("USUARIO ADMIN CREADO — usuario: admin");
        if generada {
            log(&format!(
                "  Password (ALEATORIA, se muestra solo esta vez): {clave}"
            ));
            self.clave_admin_generada = clave;
        } else {
            log("  Password: la definida en ADMIN_PASSWORD");
        }
        Ok(())
    }

    fn registrar_rutas(&mut self) {
        self.ruta("GET /{$}", Prot::Publica, raiz);
        valores_rutas::rutas(self);
        usuarios::rutas(self);
        apikeys::rutas(self);
        keystore::rutas(self);
        documentos::rutas(self);
        simulacion::rutas(self);
        xsd_rutas::rutas(self);
        emitir::rutas(self);
        rvd::rutas(self);
        db::rutas(self);
        caf::rutas(self);
        generar::rutas(self);
        monitoreo::rutas(self);
        mipyme::rutas(self);
        portal_rutas::rutas(self);
        consulta::rutas(self);
        portalks::rutas(self);
        self.ruta(
            "POST /api/v1/estado/lote",
            Prot::Protegida,
            lote::estado_lote,
        );
        if !self.cfg.carpeta_app.is_empty() && Path::new(&self.cfg.carpeta_app).is_dir() {
            self.ruta("/app/", Prot::Publica, servir_app);
            self.ruta("/app", Prot::Publica, |_, _| {
                Ok(Respuesta::nueva(301).con("Location", "/app/"))
            });
        }
        // Todo lo demás: Python (mientras exista) o 503.
        self.ruta("/", Prot::Publica, reenviar);
    }

    pub fn ruta(&mut self, patron: &str, prot: Prot, h: Manejador) {
        self.rutas.registrar(patron, (prot, h));
    }

    /// `Handler().ServeHTTP`: request-id, dominio público, CORS y enrutamiento.
    pub fn atender(&self, mut p: Peticion) -> Respuesta {
        let rid = {
            let r = p.cabecera("X-Request-ID").to_string();
            if r.is_empty() {
                auth::hex(&local::bytes_azar(6))
            } else {
                r
            }
        };
        p.request_id = rid.clone();
        let inicio = std::time::Instant::now();
        let mut r = self
            .dominio_publico(&p)
            .unwrap_or_else(|| self.cors(&mut p));
        r.poner("X-Request-ID", &rid);
        log(&format!(
            "{} {} → {} ({} ms) [rid={}]",
            p.metodo,
            p.ruta,
            r.status,
            inicio.elapsed().as_millis(),
            rid
        ));
        r
    }

    /// `dominioPublico`: si el Host es DOMINIO_PUBLICO_BOLETAS, "/" va a /consulta y todo lo que
    /// no sea /consulta* o /static/* es 404 (Internet entra solo por ahí).
    fn dominio_publico(&self, p: &Peticion) -> Option<Respuesta> {
        let pub_ = self.cfg.dominio_publico_boletas.trim().to_ascii_lowercase();
        if pub_.is_empty() {
            return None;
        }
        let host = p.host.split(':').next().unwrap_or("").to_ascii_lowercase();
        if host != pub_ {
            return None;
        }
        if p.ruta == "/" {
            return Some(Respuesta::nueva(302).con("Location", "/consulta"));
        }
        if !(p.ruta == "/consulta"
            || p.ruta.starts_with("/consulta/")
            || p.ruta.starts_with("/static/"))
        {
            return Some(errores::json(404, &json!({"detail": "No disponible"})));
        }
        None
    }

    fn cors(&self, p: &mut Peticion) -> Respuesta {
        let origen = p.cabecera("Origin").to_string();
        let mut cab: Vec<(String, String)> = Vec::new();
        if !origen.is_empty() {
            let permitido = self.cfg.cors_origins == "*"
                || self.cfg.cors_origins.split(',').any(|o| o.trim() == origen);
            if permitido {
                cab.push(("Access-Control-Allow-Origin".into(), origen.clone()));
                cab.push((
                    "Access-Control-Allow-Headers".into(),
                    "Authorization, Content-Type, X-Request-ID".into(),
                ));
                cab.push((
                    "Access-Control-Allow-Methods".into(),
                    "GET, POST, PUT, DELETE, OPTIONS".into(),
                ));
                cab.push((
                    "Access-Control-Expose-Headers".into(),
                    "X-Request-ID".into(),
                ));
            }
            if p.metodo == "OPTIONS" {
                let mut r = Respuesta::nueva(200);
                r.cabeceras = cab;
                return r;
            }
        }
        let mut r = self.enrutar(p);
        for (k, v) in cab {
            r.poner(&k, &v);
        }
        r
    }

    fn enrutar(&self, p: &mut Peticion) -> Respuesta {
        match self.rutas.resolver(&p.metodo, &p.ruta) {
            Enrutado::Encontrado((prot, h), params) => {
                p.params = params;
                let res = match prot {
                    Prot::Publica => h(self, p),
                    Prot::Protegida => match self.autenticar(p) {
                        Ok(u) => {
                            p.usuario = Some(u);
                            h(self, p)
                        }
                        Err(e) => Err(e),
                    },
                    Prot::Usuario => match self.autenticar(p) {
                        Ok(u) if u.via == "jwt" => {
                            p.usuario = Some(u);
                            h(self, p)
                        }
                        _ => Err(ErrorHTTP::autenticacion(
                            "Esta acción requiere un usuario autenticado (JWT), no una API key.",
                        )),
                    },
                };
                match res {
                    Ok(r) => r,
                    Err(e) => e.respuesta(&p.request_id),
                }
            }
            Enrutado::MetodoNoPermitido(allow) => {
                Respuesta::texto(405, "text/plain; charset=utf-8", "Method Not Allowed\n")
                    .con("Allow", &allow)
            }
            Enrutado::NoEncontrado => {
                Respuesta::texto(404, "text/plain; charset=utf-8", "404 page not found\n")
            }
        }
    }

    /// `Llamar`: ejecuta una ruta en el mismo proceso, sin red, como la cuenta dueña (clave de
    /// la app). Devuelve status y cuerpo.
    pub fn llamar(&self, metodo: &str, ruta: &str, cuerpo: Option<&[u8]>) -> (u16, Vec<u8>) {
        let mut p = Peticion::nueva(metodo, ruta, cuerpo.map(|c| c.to_vec()).unwrap_or_default());
        if cuerpo.is_some() {
            p.cabeceras
                .push(("Content-Type".into(), "application/json".into()));
        }
        if !self.cfg.app_shell_key.is_empty() {
            p.cabeceras.push((
                "Authorization".into(),
                format!("Bearer {}", self.cfg.app_shell_key),
            ));
        }
        p.host = "127.0.0.1".into();
        let r = self.atender(p);
        (r.status, r.cuerpo)
    }

    // ------------------------------------------------------------ base de datos

    /// `SELECT … ` → filas como mapas JSON (los NULL salen null, como en Python).
    pub fn filas(
        &self,
        sql: &str,
        params: &[Sql],
    ) -> Result<Vec<Map<String, Value>>, rusqlite::Error> {
        let c = self.alm.conexion();
        let mut st = c.prepare(sql)?;
        let cols: Vec<String> = st.column_names().iter().map(|s| s.to_string()).collect();
        let mut rows = st.query(rusqlite::params_from_iter(params.iter()))?;
        let mut out = Vec::new();
        while let Some(r) = rows.next()? {
            let mut m = Map::new();
            for (i, c) in cols.iter().enumerate() {
                m.insert(c.clone(), valor_json(r.get_ref(i)?));
            }
            out.push(m);
        }
        Ok(out)
    }

    pub fn fila(
        &self,
        sql: &str,
        params: &[Sql],
    ) -> Result<Option<Map<String, Value>>, rusqlite::Error> {
        Ok(self.filas(sql, params)?.into_iter().next())
    }

    /// Filas afectadas.
    pub fn ejecutar(&self, sql: &str, params: &[Sql]) -> Result<usize, rusqlite::Error> {
        let c = self.alm.conexion();
        c.execute(sql, rusqlite::params_from_iter(params.iter()))
    }

    /// `last_insert_rowid`.
    pub fn ejecutar_id(&self, sql: &str, params: &[Sql]) -> Result<i64, rusqlite::Error> {
        let c = self.alm.conexion();
        c.execute(sql, rusqlite::params_from_iter(params.iter()))?;
        Ok(c.last_insert_rowid())
    }

    /// La primera columna de la primera fila.
    pub fn escalar<T: rusqlite::types::FromSql>(
        &self,
        sql: &str,
        params: &[Sql],
    ) -> Result<Option<T>, rusqlite::Error> {
        use rusqlite::OptionalExtension;
        let c = self.alm.conexion();
        c.query_row(sql, rusqlite::params_from_iter(params.iter()), |r| {
            r.get::<_, T>(0)
        })
        .optional()
    }

    /// Bytes de una columna (BLOB o TEXT; vacío si NULL).
    pub fn bytes_de(
        &self,
        sql: &str,
        params: &[Sql],
    ) -> Result<Option<Vec<Vec<u8>>>, rusqlite::Error> {
        let c = self.alm.conexion();
        let mut st = c.prepare(sql)?;
        let n = st.column_count();
        let mut rows = st.query(rusqlite::params_from_iter(params.iter()))?;
        match rows.next()? {
            None => Ok(None),
            Some(r) => {
                let mut out = Vec::new();
                for i in 0..n {
                    out.push(match r.get_ref(i)? {
                        ValueRef::Blob(b) => b.to_vec(),
                        ValueRef::Text(t) => t.to_vec(),
                        _ => Vec::new(),
                    });
                }
                Ok(Some(out))
            }
        }
    }

    pub fn registrar_log(&self, accion: &str, detalle: &str) {
        let _ = self.ejecutar(
            "INSERT INTO audit_log (accion, tipo_dte, folio, rut_emisor, detalle, ip_origen, creado_en) VALUES (?, NULL, NULL, NULL, ?, NULL, ?)",
            &sql![accion, detalle, ahora_python()],
        );
    }

    /// `core/reloj.py::marca`: RELOJ_FIJO o ahora.
    pub fn marca(&self) -> String {
        if !self.cfg.reloj_fijo.is_empty() {
            return self.cfg.reloj_fijo.clone();
        }
        crate::almacen::ahora_iso()[..19].to_string()
    }

    /// `resolucionEmisor`: caché en BD → default del ambiente.
    pub fn resolucion_emisor(&self, rut: &str, ambiente: &str) -> (String, i64) {
        if let Ok(Some(f)) = self.fila(
            "SELECT fecha_iso, numero FROM resolucion_cache WHERE rut=? AND ambiente=?",
            &sql![rut, ambiente],
        ) {
            return (texto(&f["fecha_iso"]), entero(&f["numero"]));
        }
        if ambiente == "produccion" {
            (
                self.cfg.resolucion_fecha.clone(),
                self.cfg.resolucion_numero,
            )
        } else {
            (
                self.cfg.resolucion_fecha_cert.clone(),
                self.cfg.resolucion_numero_cert,
            )
        }
    }

    // ------------------------------------------------------------ rutas de archivos

    /// `rutaParaBD`: relativa al padre del storage si cuelga de él ("storage/pdfs/…"); si no, absoluta.
    pub fn ruta_para_bd(&self, ruta: &str) -> String {
        let padre = abs_limpia(&dir_de(&self.cfg.storage_path));
        let abs = abs_limpia(ruta);
        match Path::new(&abs).strip_prefix(&padre) {
            Ok(rel) if !rel.as_os_str().is_empty() => rel.to_string_lossy().into_owned(),
            _ => abs,
        }
    }

    /// `rutaDesdeBD`: una ruta guardada (`storage/pdfs/…`, relativa al padre de STORAGE_PATH)
    /// vuelve a ser absoluta; si así no existe, se prueba relativa al cwd.
    pub fn ruta_desde_bd(&self, p: &str) -> String {
        if p.is_empty() || Path::new(p).is_absolute() {
            return p.to_string();
        }
        let cand = Path::new(&abs_limpia(&dir_de(&self.cfg.storage_path))).join(p);
        if cand.exists() {
            return cand.to_string_lossy().into_owned();
        }
        p.to_string()
    }
}

/// `filepath.Dir`.
fn dir_de(p: &str) -> String {
    let t = p.trim_end_matches('/');
    match t.rfind('/') {
        Some(0) => "/".into(),
        Some(i) => t[..i].to_string(),
        None => ".".into(),
    }
}

/// `filepath.Abs` + `Clean`: absoluta y sin `.`/`..` (léxico, sin resolver enlaces).
pub fn abs_limpia(p: &str) -> String {
    let base = if Path::new(p).is_absolute() {
        PathBuf::from(p)
    } else {
        std::env::current_dir().unwrap_or_default().join(p)
    };
    let mut out = PathBuf::from("/");
    for c in base.components() {
        match c {
            std::path::Component::RootDir | std::path::Component::Prefix(_) => {}
            std::path::Component::CurDir => {}
            std::path::Component::ParentDir => {
                out.pop();
            }
            std::path::Component::Normal(n) => out.push(n),
        }
    }
    out.to_string_lossy().into_owned()
}

/// `Path(...).resolve()`: absoluta y con los enlaces simbólicos resueltos.
pub fn ruta_real(p: &str) -> String {
    let abs = abs_limpia(p);
    std::fs::canonicalize(&abs)
        .map(|r| r.to_string_lossy().into_owned())
        .unwrap_or(abs)
}

pub fn existe_archivo(p: &str) -> bool {
    !p.is_empty() && Path::new(p).exists()
}

// ---------------------------------------------------------------- valores

fn valor_json(v: ValueRef<'_>) -> Value {
    match v {
        ValueRef::Null => Value::Null,
        ValueRef::Integer(i) => json!(i),
        ValueRef::Real(f) => json!(f),
        ValueRef::Text(t) => Value::String(String::from_utf8_lossy(t).into_owned()),
        ValueRef::Blob(b) => Value::String(String::from_utf8_lossy(b).into_owned()),
    }
}

/// `numero(v)`: entero de un valor JSON (número o texto de dígitos).
pub fn entero(v: &Value) -> i64 {
    match v {
        Value::Number(n) => n
            .as_i64()
            .or_else(|| n.as_f64().map(|f| f as i64))
            .unwrap_or(0),
        Value::String(s) => s.trim().parse().unwrap_or(0),
        _ => 0,
    }
}

pub fn texto(v: &Value) -> String {
    match v {
        Value::String(s) => s.clone(),
        _ => String::new(),
    }
}

/// `time.Now().Format("2006-01-02T15:04:05.000000")`.
pub fn ahora_python() -> String {
    crate::almacen::ahora_iso()
}

/// `ahoraUTC`: "2006-01-02T15:04:05.000000+00:00".
pub fn ahora_utc() -> String {
    let d = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default();
    format!(
        "{}.{:06}+00:00",
        fecha_hora_utc(d.as_secs() as i64),
        d.subsec_micros()
    )
}

/// Segundos UNIX → "YYYY-MM-DDTHH:MM:SS" en UTC.
pub fn fecha_hora_utc(segundos: i64) -> String {
    let dias = segundos.div_euclid(86400);
    let s = segundos.rem_euclid(86400);
    let (a, m, d) = crate::almacen::civil_desde_dias(dias);
    format!(
        "{a:04}-{m:02}-{d:02}T{:02}:{:02}:{:02}",
        s / 3600,
        (s % 3600) / 60,
        s % 60
    )
}

/// `bytesLatin1`: el texto (decodificado de ISO-8859-1 al guardarse) vuelve a esos bytes; lo
/// que no cabe sale como '?' (errors="replace").
pub fn bytes_latin1(s: &str) -> Vec<u8> {
    s.chars()
        .map(|c| {
            if (c as u32) > 0xFF {
                b'?'
            } else {
                c as u32 as u8
            }
        })
        .collect()
}

/// Lo que registra el servidor (stderr, con la hora como `log.Printf` de Go).
pub fn log(m: &str) {
    let t = crate::almacen::ahora_iso();
    eprintln!("{}/{}/{} {} {m}", &t[..4], &t[5..7], &t[8..10], &t[11..19]);
}

// ---------------------------------------------------------------- cuerpo JSON

/// El cuerpo JSON de una petición, con los accesos tipados de los structs de Go: un campo
/// presente con otro tipo es "JSON inválido" (422), uno ausente o `null` es `None`.
pub struct Json(pub Value);

impl Json {
    pub fn leer(p: &Peticion) -> Result<Json, ErrorHTTP> {
        let v: Value = serde_json::from_slice(&p.cuerpo).map_err(|_| ErrorHTTP::json_invalido())?;
        match v {
            Value::Object(_) => Ok(Json(v)),
            Value::Null => Ok(Json(json!({}))),
            _ => Err(ErrorHTTP::json_invalido()),
        }
    }
    pub fn get(&self, k: &str) -> Option<&Value> {
        self.0.get(k).filter(|v| !v.is_null())
    }
    pub fn texto(&self, k: &str) -> Result<Option<String>, ErrorHTTP> {
        match self.get(k) {
            None => Ok(None),
            Some(Value::String(s)) => Ok(Some(s.clone())),
            Some(_) => Err(ErrorHTTP::json_invalido()),
        }
    }
    pub fn texto_o(&self, k: &str, def: &str) -> Result<String, ErrorHTTP> {
        Ok(self.texto(k)?.unwrap_or_else(|| def.to_string()))
    }
    pub fn entero(&self, k: &str) -> Result<Option<i64>, ErrorHTTP> {
        match self.get(k) {
            None => Ok(None),
            Some(Value::Number(n)) => n
                .as_i64()
                .or_else(|| n.as_f64().filter(|f| f.fract() == 0.0).map(|f| f as i64))
                .map(Some)
                .ok_or_else(ErrorHTTP::json_invalido),
            Some(_) => Err(ErrorHTTP::json_invalido()),
        }
    }
    pub fn entero_o(&self, k: &str, def: i64) -> Result<i64, ErrorHTTP> {
        Ok(self.entero(k)?.unwrap_or(def))
    }
    pub fn decimal(&self, k: &str) -> Result<Option<f64>, ErrorHTTP> {
        match self.get(k) {
            None => Ok(None),
            Some(Value::Number(n)) => Ok(n.as_f64()),
            Some(_) => Err(ErrorHTTP::json_invalido()),
        }
    }
    pub fn logico_o(&self, k: &str, def: bool) -> Result<bool, ErrorHTTP> {
        match self.get(k) {
            None => Ok(def),
            Some(Value::Bool(b)) => Ok(*b),
            Some(_) => Err(ErrorHTTP::json_invalido()),
        }
    }
}

// ---------------------------------------------------------------- rutas básicas

/// GET / de main.py (health check).
fn raiz(s: &Servidor, _p: &mut Peticion) -> Res {
    errores::ok(json!({
        "status": "ok", "servicio": s.cfg.app_name, "version": s.cfg.app_version, "documentacion": "/docs",
        "ambiente_sii": s.cfg.sii_ambiente, "empresa_configurada": s.cfg.empresa_configurada(),
    }))
}

fn tipo_mime(nombre: &str) -> &'static str {
    match nombre
        .rsplit('.')
        .next()
        .unwrap_or("")
        .to_ascii_lowercase()
        .as_str()
    {
        "html" => "text/html; charset=utf-8",
        "js" => "text/javascript; charset=utf-8",
        "css" => "text/css; charset=utf-8",
        "json" => "application/json",
        "png" => "image/png",
        "svg" => "image/svg+xml",
        "ico" => "image/x-icon",
        "woff2" => "font/woff2",
        "woff" => "font/woff",
        "txt" => "text/plain; charset=utf-8",
        _ => "application/octet-stream",
    }
}

/// `/app/`: la interfaz desde la carpeta (`http.FileServer`).
fn servir_app(s: &Servidor, p: &mut Peticion) -> Res {
    let rel = p.ruta.trim_start_matches("/app/");
    if rel.contains("..") {
        return Ok(Respuesta::texto(
            404,
            "text/plain; charset=utf-8",
            "404 page not found\n",
        ));
    }
    let mut ruta = Path::new(&s.cfg.carpeta_app).join(rel);
    if ruta.is_dir() {
        if !p.ruta.ends_with('/') {
            return Ok(Respuesta::nueva(301).con("Location", &format!("{}/", p.ruta)));
        }
        ruta = ruta.join("index.html");
    }
    match std::fs::read(&ruta) {
        Ok(b) => Ok(Respuesta::binario(
            200,
            tipo_mime(&ruta.to_string_lossy()),
            b,
        )),
        Err(_) => Ok(Respuesta::texto(
            404,
            "text/plain; charset=utf-8",
            "404 page not found\n",
        )),
    }
}

/// Todo lo demás: el motor Python (reenvío) o 503.
fn reenviar(s: &Servidor, p: &mut Peticion) -> Res {
    if s.cfg.motor_python.is_empty() {
        return Err(ErrorHTTP::nuevo(
            503,
            "no_portado",
            "Esta ruta todavía no está en el motor Rust y no hay motor Python configurado.",
        ));
    }
    let url = format!(
        "{}{}{}",
        s.cfg.motor_python.trim_end_matches('/'),
        p.ruta,
        if p.query.is_empty() {
            String::new()
        } else {
            format!("?{}", p.query)
        }
    );
    let agente = crate::sii::http::agente(std::time::Duration::from_secs(120), false);
    let pasa =
        |k: &str| !k.eq_ignore_ascii_case("host") && !k.eq_ignore_ascii_case("content-length");
    let r = match p.metodo.as_str() {
        "GET" | "HEAD" | "DELETE" | "OPTIONS" => {
            let mut req = match p.metodo.as_str() {
                "DELETE" => agente.delete(&url),
                "HEAD" => agente.head(&url),
                _ => agente.get(&url),
            };
            for (k, v) in p.cabeceras.iter().filter(|(k, _)| pasa(k)) {
                req = req.header(k.as_str(), v.as_str());
            }
            crate::sii::http::ejecutar_get(req)
        }
        _ => {
            let mut req = match p.metodo.as_str() {
                "PUT" => agente.put(&url),
                "PATCH" => agente.patch(&url),
                _ => agente.post(&url),
            };
            for (k, v) in p.cabeceras.iter().filter(|(k, _)| pasa(k)) {
                req = req.header(k.as_str(), v.as_str());
            }
            crate::sii::http::ejecutar(req, &p.cuerpo)
        }
    };
    match r {
        Ok(r) => {
            let mut out = Respuesta::nueva(r.status).cuerpo(r.cuerpo);
            for (k, v) in r.headers {
                if !k.eq_ignore_ascii_case("transfer-encoding")
                    && !k.eq_ignore_ascii_case("content-length")
                {
                    out.cabeceras.push((k, v));
                }
            }
            Ok(out)
        }
        Err(_) => Err(ErrorHTTP::nuevo(
            503,
            "motor_no_disponible",
            "El motor Python no responde (ruta aún no portada a Go).",
        )),
    }
}
