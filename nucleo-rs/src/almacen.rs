//! Acceso a la MISMA base SQLite del motor (mismo archivo, mismo esquema). Transcripción de
//! `nucleo/almacen` (Go). El esquema lo definen las migraciones embebidas (`migraciones/`),
//! idénticas a las de Go, que a su vez son lo que Python creaba al arrancar.
//!
//! Lo importante está en `consumir_siguiente_folio`: réplica de
//! `core/models.py::consumir_siguiente_folio`, una sola transacción `BEGIN IMMEDIATE` que lee
//! y avanza el folio. Separar la lectura del avance reintroduce la carrera TOCTOU (dos
//! emisiones con el mismo folio) que ese candado evita.

use rusqlite::{params, Connection, OptionalExtension};
use std::sync::{Mutex, MutexGuard};

pub const MIGRACIONES: [(u32, &str, &str); 1] =
    [(1, "base", include_str!("../migraciones/0001_base.sql"))];

pub struct Almacen {
    conn: Mutex<Connection>,
}

#[derive(Debug, Clone, Default)]
pub struct Caf {
    pub id: i64,
    pub tipo_dte: i32,
    pub rut_emisor: String,
    pub folio_desde: i32,
    pub folio_hasta: i32,
    pub folio_siguiente: i32,
    pub xml: String,
}

#[derive(Debug, Clone, Default)]
pub struct Dte {
    pub tipo_dte: i32,
    pub folio: i32,
    pub rut_emisor: String,
    pub rut_receptor: String,
    pub razon_social_receptor: String,
    pub fecha_emision: String,
    pub monto_neto: i64,
    pub monto_exento: i64,
    pub iva: i64,
    pub monto_total: i64,
    /// ISO-8859-1 decodificado (como lo guarda Python)
    pub xml_firmado: String,
    pub ambiente: String,
}

/// Lo mínimo de una fila existente de `dtes`.
#[derive(Debug, Clone, Default)]
pub struct DteFila {
    pub id: i64,
    pub estado: String,
    pub pdf_path: String,
    pub tiene_xml: bool,
}

/// Lo que la app necesita de un documento para anularlo por el SII engine.
#[derive(Debug, Clone, Default)]
pub struct DteDetalle {
    pub id: i64,
    pub tipo_dte: i32,
    pub folio: i32,
    pub rut_emisor: String,
    pub rut_receptor: String,
    pub razon_social_receptor: String,
    pub fecha_emision: String,
    pub monto_total: i64,
    pub estado: String,
    /// en el canal MIPYME es el DHDR del portal
    pub track_id: i64,
}

#[derive(Debug)]
pub enum Error {
    SinFolios,
    Sql(rusqlite::Error),
    Otro(String),
}

impl std::fmt::Display for Error {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Error::SinFolios => write!(f, "no hay folios disponibles"),
            Error::Sql(e) => write!(f, "{e}"),
            Error::Otro(s) => write!(f, "{s}"),
        }
    }
}

impl std::error::Error for Error {}

impl From<rusqlite::Error> for Error {
    fn from(e: rusqlite::Error) -> Self {
        Error::Sql(e)
    }
}

pub type Resultado<T> = Result<T, Error>;

/// `time.Now().Format("2006-01-02T15:04:05.000000")` en hora local, como Python.
pub fn ahora_iso() -> String {
    let (y, m, d, h, mi, s, us) = ahora_local();
    format!("{y:04}-{m:02}-{d:02}T{h:02}:{mi:02}:{s:02}.{us:06}")
}

fn ahora_local() -> (i64, u32, u32, u32, u32, u32, u32) {
    let d = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default();
    let secs = d.as_secs() as i64 + desfase_local_segundos();
    let dias = secs.div_euclid(86400);
    let resto = secs.rem_euclid(86400) as u32;
    let (y, m, dd) = civil_desde_dias(dias);
    (
        y,
        m,
        dd,
        resto / 3600,
        (resto % 3600) / 60,
        resto % 60,
        d.subsec_micros(),
    )
}

/// Desfase local respecto de UTC: `localtime_r` de libc (sin dependencias; es lo que usan
/// `time.Now()` en Go y `datetime.now()` en Python). Donde no haya libc (Windows), la
/// variable `DTE_TZ_OFFSET_MIN` o UTC.
pub fn desfase_local_segundos() -> i64 {
    if let Some(v) = std::env::var("DTE_TZ_OFFSET_MIN")
        .ok()
        .and_then(|v| v.parse::<i64>().ok())
    {
        return v * 60;
    }
    desfase_libc().unwrap_or(0)
}

#[cfg(unix)]
fn desfase_libc() -> Option<i64> {
    #[repr(C)]
    struct Tm {
        tm_sec: i32,
        tm_min: i32,
        tm_hour: i32,
        tm_mday: i32,
        tm_mon: i32,
        tm_year: i32,
        tm_wday: i32,
        tm_yday: i32,
        tm_isdst: i32,
        tm_gmtoff: std::ffi::c_long,
        tm_zone: *const std::ffi::c_char,
    }
    extern "C" {
        fn tzset();
        fn localtime_r(t: *const i64, tm: *mut Tm) -> *mut Tm;
    }
    let ahora = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .ok()?
        .as_secs() as i64;
    let mut tm = Tm {
        tm_sec: 0,
        tm_min: 0,
        tm_hour: 0,
        tm_mday: 0,
        tm_mon: 0,
        tm_year: 0,
        tm_wday: 0,
        tm_yday: 0,
        tm_isdst: 0,
        tm_gmtoff: 0,
        tm_zone: std::ptr::null(),
    };
    // SAFETY: `localtime_r` escribe solo en `tm`, un struct con la disposición de `struct tm`
    // en macOS y Linux (nueve enteros, el desfase y el nombre de la zona).
    let r = unsafe {
        tzset();
        localtime_r(&ahora, &mut tm)
    };
    if r.is_null() {
        return None;
    }
    Some(tm.tm_gmtoff as i64)
}

#[cfg(not(unix))]
fn desfase_libc() -> Option<i64> {
    None
}

pub fn civil_desde_dias(z: i64) -> (i64, u32, u32) {
    let z = z + 719468;
    let era = if z >= 0 { z } else { z - 146096 } / 146097;
    let doe = z - era * 146097;
    let yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365;
    let y = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = (doy - (153 * mp + 2) / 5 + 1) as u32;
    let m = if mp < 10 { mp + 3 } else { mp - 9 } as u32;
    (if m <= 2 { y + 1 } else { y }, m, d)
}

impl Almacen {
    pub fn abrir(ruta: &str) -> Resultado<Almacen> {
        let conn = Connection::open(ruta)?;
        conn.busy_timeout(std::time::Duration::from_millis(5000))?;
        conn.pragma_update(None, "journal_mode", "WAL")?;
        conn.pragma_update(None, "foreign_keys", "ON")?;
        Ok(Almacen {
            conn: Mutex::new(conn),
        })
    }

    /// Abre la base y aplica las migraciones pendientes (lo que hace el servidor y la app al
    /// arrancar).
    pub fn abrir_y_migrar(ruta: &str) -> Resultado<Almacen> {
        let a = Almacen::abrir(ruta)?;
        a.migrar()?;
        Ok(a)
    }

    pub fn conexion(&self) -> MutexGuard<'_, Connection> {
        self.conn.lock().unwrap_or_else(|e| e.into_inner())
    }

    /// Aplica las migraciones pendientes. Devuelve las versiones aplicadas en esta corrida.
    pub fn migrar(&self) -> Resultado<Vec<u32>> {
        let mut c = self.conexion();
        c.execute_batch("CREATE TABLE IF NOT EXISTS migraciones (version INTEGER PRIMARY KEY, nombre TEXT NOT NULL, aplicada TEXT NOT NULL)")?;
        let mut aplicadas = Vec::new();
        for (version, nombre, sql) in MIGRACIONES {
            let n: i64 = c.query_row(
                "SELECT COUNT(*) FROM migraciones WHERE version=?1",
                params![version],
                |r| r.get(0),
            )?;
            if n > 0 {
                continue;
            }
            let tx = c.transaction()?;
            tx.execute_batch(sql)
                .map_err(|e| Error::Otro(format!("migración {version:04}_{nombre}: {e}")))?;
            tx.execute(
                "INSERT INTO migraciones (version, nombre, aplicada) VALUES (?1, ?2, ?3)",
                params![version, nombre, ahora_utc_rfc3339()],
            )?;
            tx.commit()?;
            aplicadas.push(version);
        }
        drop(c);
        self.asegurar_columnas()?;
        Ok(aplicadas)
    }

    /// Los `ALTER TABLE … ADD COLUMN` que Python hace al arrancar (`core/negocios.py`): se
    /// agregan solo si faltan, así una base adoptada de Python y una creada aquí quedan con el
    /// mismo esquema.
    fn asegurar_columnas(&self) -> Resultado<()> {
        const COLUMNAS: [(&str, &str, &str); 12] = [
            ("negocios", "estado", "TEXT"),
            ("negocios", "estado_etiqueta", "TEXT"),
            ("negocios", "usa_sw_propio", "INTEGER"),
            ("negocios", "estado_ts", "TEXT"),
            ("negocios", "software_registrado", "TEXT"),
            // Datos del emisor por negocio (core/negocios.py::_COLS_DATOS, 2026-10-13).
            ("negocios", "giro", "TEXT"),
            ("negocios", "codigo_actividad", "INTEGER"),
            ("negocios", "direccion", "TEXT"),
            ("negocios", "comuna", "TEXT"),
            ("negocios", "ciudad", "TEXT"),
            ("negocios", "email", "TEXT"),
            ("negocios", "telefono", "TEXT"),
        ];
        let c = self.conexion();
        for (tabla, columna, ddl) in COLUMNAS {
            let mut st = c.prepare(&format!("PRAGMA table_info({tabla})"))?;
            let existe = st
                .query_map([], |r| r.get::<_, String>(1))?
                .any(|n| n.map(|x| x == columna).unwrap_or(false));
            if !existe {
                c.execute_batch(&format!("ALTER TABLE {tabla} ADD COLUMN {columna} {ddl}"))
                    .map_err(|e| Error::Otro(format!("columna {tabla}.{columna}: {e}")))?;
            }
        }
        Ok(())
    }

    /// La última migración aplicada (0 si ninguna).
    pub fn version_esquema(&self) -> Resultado<u32> {
        let c = self.conexion();
        match c.query_row(
            "SELECT COALESCE(MAX(version), 0) FROM migraciones",
            [],
            |r| r.get::<_, u32>(0),
        ) {
            Ok(v) => Ok(v),
            Err(e) if e.to_string().contains("no such table") => Ok(0),
            Err(e) => Err(e.into()),
        }
    }

    /// `obtener_caf_activo`: el CAF activo de mayor folio_desde.
    pub fn caf_activo(&self, rut: &str, tipo: i32) -> Resultado<Option<Caf>> {
        let c = self.conexion();
        Ok(c.query_row(
            "SELECT id, tipo_dte, rut_emisor, folio_desde, folio_hasta, folio_siguiente, caf_xml FROM cafs WHERE rut_emisor=?1 AND tipo_dte=?2 AND activo=1 ORDER BY folio_desde DESC LIMIT 1",
            params![rut, tipo],
            |r| Ok(Caf { id: r.get(0)?, tipo_dte: r.get(1)?, rut_emisor: r.get(2)?, folio_desde: r.get(3)?, folio_hasta: r.get(4)?, folio_siguiente: r.get(5)?, xml: r.get(6)? }),
        )
        .optional()?)
    }

    /// Toma y avanza el folio en una transacción BEGIN IMMEDIATE (reintenta hasta 3 veces si
    /// la base está bloqueada, 50 ms entre intentos, como Python).
    pub fn consumir_siguiente_folio(&self, rut: &str, tipo: i32) -> Resultado<i32> {
        let mut ultimo = Error::Otro("sin intentos".into());
        for _ in 0..3 {
            match self.consumir(rut, tipo) {
                Ok(f) => return Ok(f),
                Err(Error::SinFolios) => return Err(Error::SinFolios),
                Err(e) => {
                    let msg = e.to_string();
                    if !msg.contains("locked") && !msg.contains("busy") {
                        return Err(e);
                    }
                    ultimo = e;
                }
            }
            std::thread::sleep(std::time::Duration::from_millis(50));
        }
        Err(ultimo)
    }

    fn consumir(&self, rut: &str, tipo: i32) -> Resultado<i32> {
        let c = self.conexion();
        c.execute_batch("BEGIN IMMEDIATE")?;
        let fila: Option<(i64, i32, i32)> = c
            .query_row(
                "SELECT id, folio_siguiente, folio_hasta FROM cafs WHERE rut_emisor=?1 AND tipo_dte=?2 AND activo=1 ORDER BY folio_desde DESC LIMIT 1",
                params![rut, tipo],
                |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)),
            )
            .optional()
            .inspect_err(|_| {
                let _ = c.execute_batch("ROLLBACK");
            })?;
        let Some((id, siguiente, hasta)) = fila else {
            let _ = c.execute_batch("COMMIT");
            return Err(Error::SinFolios);
        };
        if siguiente > hasta {
            let _ = c.execute_batch("COMMIT");
            return Err(Error::SinFolios);
        }
        if let Err(e) = c.execute(
            "UPDATE cafs SET folio_siguiente=?1 WHERE id=?2",
            params![siguiente + 1, id],
        ) {
            let _ = c.execute_batch("ROLLBACK");
            return Err(e.into());
        }
        c.execute_batch("COMMIT")?;
        Ok(siguiente)
    }

    /// `consumir_folio` (folio explícito): avanza folio_siguiente a folio+1.
    pub fn consumir_folio(&self, rut: &str, tipo: i32, folio: i32) -> Resultado<bool> {
        let Some(c) = self.caf_activo(rut, tipo)? else {
            return Ok(false);
        };
        if folio < c.folio_desde || folio > c.folio_hasta {
            return Ok(false);
        }
        self.conexion().execute(
            "UPDATE cafs SET folio_siguiente=?1 WHERE id=?2",
            params![folio + 1, c.id],
        )?;
        Ok(true)
    }

    /// `crear_dte`: misma fila, estado 'generado', creado_en/actualizado_en ISO.
    pub fn crear_dte(&self, d: &Dte) -> Resultado<i64> {
        let ahora = ahora_iso();
        let c = self.conexion();
        c.execute(
            "INSERT INTO dtes (tipo_dte, folio, rut_emisor, rut_receptor, razon_social_receptor, fecha_emision, monto_neto, monto_exento, iva, monto_total, estado, xml_firmado, ambiente, creado_en, actualizado_en) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, 'generado', ?11, ?12, ?13, ?13)",
            params![d.tipo_dte, d.folio, d.rut_emisor, d.rut_receptor, d.razon_social_receptor, d.fecha_emision, d.monto_neto, d.monto_exento, d.iva, d.monto_total, d.xml_firmado, d.ambiente, ahora],
        )
        .map_err(|e| Error::Otro(format!("insertar dte: {e}")))?;
        Ok(c.last_insert_rowid())
    }

    /// La fila (rut_emisor, tipo, folio) o `None` si no existe.
    pub fn dte_por_folio(&self, rut: &str, tipo: i32, folio: i32) -> Resultado<Option<DteFila>> {
        let c = self.conexion();
        c.query_row(
            "SELECT id, estado, pdf_path, xml_firmado FROM dtes WHERE rut_emisor=?1 AND tipo_dte=?2 AND folio=?3",
            params![rut, tipo, folio],
            |r| {
                let xml: Option<String> = r.get(3)?;
                Ok(DteFila { id: r.get(0)?, estado: r.get::<_, Option<String>>(1)?.unwrap_or_default(), pdf_path: r.get::<_, Option<String>>(2)?.unwrap_or_default(), tiene_xml: xml.is_some_and(|x| !x.is_empty()) })
            },
        )
        .optional()
        .map_err(|e| Error::Otro(format!("leer dte: {e}")))
    }

    /// `actualizar_estado_dte`; track_id 0 deja track_id como está.
    pub fn actualizar_estado(&self, id: i64, estado: &str, track_id: i64) -> Resultado<()> {
        let ahora = ahora_iso();
        let c = self.conexion();
        let r = if track_id != 0 {
            c.execute(
                "UPDATE dtes SET estado=?1, track_id=?2, actualizado_en=?3 WHERE id=?4",
                params![estado, track_id, ahora, id],
            )
        } else {
            c.execute(
                "UPDATE dtes SET estado=?1, actualizado_en=?2 WHERE id=?3",
                params![estado, ahora, id],
            )
        };
        r.map_err(|e| Error::Otro(format!("actualizar estado: {e}")))?;
        Ok(())
    }

    /// `guardar_pdf_dte`.
    pub fn guardar_pdf(&self, id: i64, ruta: &str) -> Resultado<()> {
        self.conexion()
            .execute(
                "UPDATE dtes SET pdf_path=?1, actualizado_en=?2 WHERE id=?3",
                params![ruta, ahora_iso(), id],
            )
            .map_err(|e| Error::Otro(format!("guardar pdf: {e}")))?;
        Ok(())
    }

    /// Guarda el XML firmado (decodificado ISO-8859-1, como lo guarda Python).
    pub fn guardar_xml(&self, id: i64, xml: &str) -> Resultado<()> {
        self.conexion()
            .execute(
                "UPDATE dtes SET xml_firmado=?1, actualizado_en=datetime('now') WHERE id=?2",
                params![xml, id],
            )
            .map_err(|e| Error::Otro(format!("guardar xml: {e}")))?;
        Ok(())
    }

    /// Corre una sentencia de esquema (tests y migraciones mínimas).
    pub fn ejecutar_ddl(&self, ddl: &str) -> Resultado<()> {
        self.conexion().execute_batch(ddl)?;
        Ok(())
    }

    /// El documento o `None` si no existe.
    pub fn dte_por_id(&self, id: i64) -> Resultado<Option<DteDetalle>> {
        let c = self.conexion();
        c.query_row(
            "SELECT id, tipo_dte, folio, rut_emisor, rut_receptor, razon_social_receptor, fecha_emision, monto_total, estado, track_id FROM dtes WHERE id=?1",
            params![id],
            |r| {
                Ok(DteDetalle {
                    id: r.get(0)?,
                    tipo_dte: r.get(1)?,
                    folio: r.get(2)?,
                    rut_emisor: r.get(3)?,
                    rut_receptor: r.get(4)?,
                    razon_social_receptor: r.get::<_, Option<String>>(5)?.unwrap_or_default(),
                    fecha_emision: r.get(6)?,
                    monto_total: r.get(7)?,
                    estado: r.get::<_, Option<String>>(8)?.unwrap_or_default(),
                    track_id: r.get::<_, Option<i64>>(9)?.unwrap_or(0),
                })
            },
        )
        .optional()
        .map_err(|e| Error::Otro(format!("leer dte {id}: {e}")))
    }

    /// `registrar_caf`: inserta el CAF con folio_siguiente = folio_desde.
    pub fn registrar_caf(
        &self,
        tipo: i32,
        rut: &str,
        desde: i32,
        hasta: i32,
        fecha_autorizacion: &str,
        caf_xml: &str,
    ) -> Resultado<i64> {
        let c = self.conexion();
        c.execute(
            "INSERT INTO cafs (tipo_dte, rut_emisor, folio_desde, folio_hasta, folio_siguiente, fecha_autorizacion, caf_xml, creado_en) VALUES (?1, ?2, ?3, ?4, ?3, ?5, ?6, ?7)",
            params![tipo, rut, desde, hasta, fecha_autorizacion, caf_xml, ahora_iso()],
        )
        .map_err(|e| Error::Otro(format!("registrar caf: {e}")))?;
        Ok(c.last_insert_rowid())
    }

    /// El XML firmado (texto decodificado de ISO-8859-1), tipo y folio de un documento.
    pub fn xml_de(&self, id: i64) -> Resultado<(String, i32, i32)> {
        let c = self.conexion();
        let (xml, tipo, folio): (Option<String>, i32, i32) = c
            .query_row(
                "SELECT xml_firmado, tipo_dte, folio FROM dtes WHERE id=?1",
                params![id],
                |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)),
            )
            .map_err(|e| Error::Otro(format!("leer xml del dte {id}: {e}")))?;
        match xml {
            Some(x) if !x.is_empty() => Ok((x, tipo, folio)),
            _ => Err(Error::Otro(format!("el documento {id} no tiene XML"))),
        }
    }
}

fn ahora_utc_rfc3339() -> String {
    let d = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default();
    let secs = d.as_secs() as i64;
    let (y, m, dd) = civil_desde_dias(secs.div_euclid(86400));
    let r = secs.rem_euclid(86400);
    format!(
        "{y:04}-{m:02}-{dd:02}T{:02}:{:02}:{:02}Z",
        r / 3600,
        (r % 3600) / 60,
        r % 60
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn migra_y_consume_folios_sin_repetir() {
        let dir = std::env::temp_dir().join(format!("almacen-{}", std::process::id()));
        let _ = std::fs::create_dir_all(&dir);
        let ruta = dir.join("t.db");
        let a = Almacen::abrir_y_migrar(ruta.to_str().unwrap()).unwrap();
        assert_eq!(a.version_esquema().unwrap(), 1);
        assert!(
            a.migrar().unwrap().is_empty(),
            "la segunda vez no aplica nada"
        );
        a.registrar_caf(39, "77777777-7", 1, 3, "2026-01-01", "<CAF/>")
            .unwrap();
        assert_eq!(a.consumir_siguiente_folio("77777777-7", 39).unwrap(), 1);
        assert_eq!(a.consumir_siguiente_folio("77777777-7", 39).unwrap(), 2);
        assert!(a.consumir_folio("77777777-7", 39, 3).unwrap());
        assert!(matches!(
            a.consumir_siguiente_folio("77777777-7", 39),
            Err(Error::SinFolios)
        ));
        let id = a
            .crear_dte(&Dte {
                tipo_dte: 39,
                folio: 1,
                rut_emisor: "77777777-7".into(),
                rut_receptor: "66666666-6".into(),
                fecha_emision: "2026-01-01".into(),
                monto_total: 1190,
                ambiente: "simulacion".into(),
                ..Default::default()
            })
            .unwrap();
        a.actualizar_estado(id, "aceptado", 123).unwrap();
        let f = a.dte_por_folio("77777777-7", 39, 1).unwrap().unwrap();
        assert_eq!(
            (f.id, f.estado.as_str(), f.tiene_xml),
            (id, "aceptado", false)
        );
        a.guardar_xml(id, "<DTE/>").unwrap();
        assert_eq!(a.xml_de(id).unwrap(), ("<DTE/>".into(), 39, 1));
        let d = a.dte_por_id(id).unwrap().unwrap();
        assert_eq!((d.track_id, d.monto_total), (123, 1190));
        let _ = std::fs::remove_dir_all(&dir);
    }
}
