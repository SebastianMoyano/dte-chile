//! Los indicadores públicos del SII (UF, UTM, dólar observado) desde las páginas oficiales de
//! "Valores y Fechas" (www.sii.cl/valores_y_fechas/...), con mindicador.cl como fallback, y su
//! caché en el MISMO SQLite del motor (tabla `valores`). Transcripción de `nucleo/valores`.
//!
//! El HTML es ISO-8859-1. Dos formatos de tabla:
//!   - UF y DÓLAR: una tabla por mes (<h2>Mes</h2>), pares <th>día</th><td>valor</td>. Diario.
//!     OJO: la UF usa coma decimal ("41.065,38"); el dólar usa punto ("972.6").
//!   - UTM: una sola tabla, una fila por mes. Mensual (se guarda en el día 1 del mes).

use crate::almacen::Almacen;
use crate::sii::http::{agente, ejecutar_get};
use regex::Regex;
use std::collections::BTreeMap;
use std::sync::OnceLock;
use std::time::Duration;

/// Un indicador en una fecha. Valor en pesos.
#[derive(Debug, Clone, PartialEq, serde::Serialize)]
pub struct Valor {
    /// "uf" | "utm" | "dolar"
    pub indicador: String,
    /// YYYY-MM-DD
    pub fecha: String,
    pub valor: f64,
}

const UA_NAVEGADOR: &str = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/154.0 Safari/537.36";

fn meses() -> &'static BTreeMap<&'static str, u32> {
    static M: OnceLock<BTreeMap<&'static str, u32>> = OnceLock::new();
    M.get_or_init(|| {
        [
            ("enero", 1),
            ("febrero", 2),
            ("marzo", 3),
            ("abril", 4),
            ("mayo", 5),
            ("junio", 6),
            ("julio", 7),
            ("agosto", 8),
            ("septiembre", 9),
            ("octubre", 10),
            ("noviembre", 11),
            ("diciembre", 12),
        ]
        .into_iter()
        .collect()
    })
}

fn re(cache: &'static OnceLock<Regex>, pat: &str) -> &'static Regex {
    cache.get_or_init(|| Regex::new(pat).expect("regex"))
}
static RE_MES: OnceLock<Regex> = OnceLock::new();
static RE_PAR: OnceLock<Regex> = OnceLock::new();
static RE_FILA_MES: OnceLock<Regex> = OnceLock::new();

/// ISO-8859-1 → String.
pub fn latin1(b: &[u8]) -> String {
    b.iter().map(|&c| c as char).collect()
}

/// Número con coma decimal chilena ("41.065,38" → 41065.38).
pub fn numero_cl(s: &str) -> Option<f64> {
    let s = s.trim();
    if s.is_empty() {
        return None;
    }
    s.replace('.', "").replace(',', ".").parse().ok()
}

/// El formato de la página dólar: punto decimal ("972.6"); con coma, cae a `numero_cl`.
pub fn numero_dolar(s: &str) -> Option<f64> {
    let s = s.trim();
    if s.is_empty() {
        return None;
    }
    if s.contains(',') {
        return numero_cl(s);
    }
    s.parse().ok()
}

type Parser = fn(&[u8], i32) -> Result<Vec<Valor>, String>;

fn parsear_diario(
    html: &[u8],
    anio: i32,
    indicador: &str,
    num: fn(&str) -> Option<f64>,
) -> Result<Vec<Valor>, String> {
    let doc = latin1(html);
    let re_mes = re(&RE_MES, r"(?i)<h[23][^>]*>\s*([a-záéíóúñ]+)\s*</h[23]>");
    let re_par = re(
        &RE_PAR,
        r"(?is)<th[^>]*>\s*(?:<strong>)?\s*(\d{1,2})\s*(?:</strong>)?\s*</th>\s*<td[^>]*>([^<]*)</td>",
    );
    let enc: Vec<(usize, usize, String)> = re_mes
        .captures_iter(&doc)
        .map(|c| {
            (
                c.get(0).unwrap().start(),
                c.get(0).unwrap().end(),
                c[1].to_lowercase(),
            )
        })
        .collect();
    if enc.is_empty() {
        return Err(format!(
            "no se encontraron meses en la página {indicador} {anio}"
        ));
    }
    let mut out = Vec::new();
    for (i, (_, fin_titulo, nombre)) in enc.iter().enumerate() {
        let Some(&mes) = meses().get(nombre.as_str()) else {
            continue;
        };
        let fin = if i + 1 < enc.len() {
            enc[i + 1].0
        } else {
            doc.len()
        };
        for p in re_par.captures_iter(&doc[*fin_titulo..fin]) {
            let Ok(dia) = p[1].trim().parse::<u32>() else {
                continue;
            };
            if !(1..=31).contains(&dia) {
                continue;
            }
            if let Some(v) = num(&p[2]) {
                out.push(Valor {
                    indicador: indicador.into(),
                    fecha: format!("{anio:04}-{mes:02}-{dia:02}"),
                    valor: v,
                });
            }
        }
    }
    if out.is_empty() {
        return Err(format!("página {indicador} {anio} sin valores parseables"));
    }
    Ok(out)
}

pub fn parsear_uf(html: &[u8], anio: i32) -> Result<Vec<Valor>, String> {
    parsear_diario(html, anio, "uf", numero_cl)
}

pub fn parsear_dolar(html: &[u8], anio: i32) -> Result<Vec<Valor>, String> {
    parsear_diario(html, anio, "dolar", numero_dolar)
}

/// Una tabla con una fila por mes; la UTM es el PRIMER <td> tras el <th>Mes</th>.
pub fn parsear_utm(html: &[u8], anio: i32) -> Result<Vec<Valor>, String> {
    let doc = latin1(html);
    let re_fila = re(
        &RE_FILA_MES,
        r"(?is)<tr>\s*<th[^>]*>\s*([a-záéíóúñ]+)\s*</th>\s*<td[^>]*>([^<]*)</td>",
    );
    let mut out = Vec::new();
    for m in re_fila.captures_iter(&doc) {
        let Some(&mes) = meses().get(m[1].trim().to_lowercase().as_str()) else {
            continue;
        };
        if let Some(v) = numero_cl(&m[2]) {
            out.push(Valor {
                indicador: "utm".into(),
                fecha: format!("{anio:04}-{mes:02}-01"),
                valor: v,
            });
        }
    }
    if out.is_empty() {
        return Err(format!("página UTM {anio} sin valores parseables"));
    }
    Ok(out)
}

fn bajar(url: &str) -> Result<Vec<u8>, String> {
    let ag = agente(Duration::from_secs(20), true);
    let r = ejecutar_get(
        ag.get(url)
            .header("User-Agent", UA_NAVEGADOR)
            .header("Accept-Language", "es-CL,es;q=0.9"),
    )?;
    if r.status != 200 {
        return Err(format!("{url} → HTTP {}", r.status));
    }
    Ok(r.cuerpo)
}

/// Trae un indicador del año: primero la página oficial del SII; si falla, mindicador.cl.
/// Devuelve los valores y la fuente ("sii"|"mindicador").
pub fn fetch(indicador: &str, anio: i32) -> Result<(Vec<Valor>, &'static str), String> {
    let (url, parse): (String, Parser) = match indicador {
        "uf" => (
            format!("https://www.sii.cl/valores_y_fechas/uf/uf{anio}.htm"),
            parsear_uf,
        ),
        "dolar" => (
            format!("https://www.sii.cl/valores_y_fechas/dolar/dolar{anio}.htm"),
            parsear_dolar,
        ),
        "utm" => (
            format!("https://www.sii.cl/valores_y_fechas/utm/utm{anio}.htm"),
            parsear_utm,
        ),
        _ => return Err(format!("indicador desconocido: {indicador}")),
    };
    if let Ok(b) = bajar(&url) {
        if let Ok(vs) = parse(&b, anio) {
            return Ok((vs, "sii"));
        }
    }
    let vs = fetch_mindicador(indicador, anio)
        .map_err(|e| format!("{indicador} {anio}: falló SII y mindicador: {e}"))?;
    Ok((vs, "mindicador"))
}

fn fetch_mindicador(indicador: &str, anio: i32) -> Result<Vec<Valor>, String> {
    let b = bajar(&format!("https://mindicador.cl/api/{indicador}/{anio}"))?;
    let v: serde_json::Value = serde_json::from_slice(&b).map_err(|e| e.to_string())?;
    let out: Vec<Valor> = v
        .get("serie")
        .and_then(|s| s.as_array())
        .map(|a| {
            a.iter()
                .filter_map(|x| {
                    let f = x.get("fecha")?.as_str()?;
                    if f.len() < 10 {
                        return None;
                    }
                    Some(Valor {
                        indicador: indicador.into(),
                        fecha: f[..10].to_string(),
                        valor: x.get("valor")?.as_f64()?,
                    })
                })
                .collect()
        })
        .unwrap_or_default();
    if out.is_empty() {
        return Err(format!("mindicador {indicador} {anio} sin serie"));
    }
    Ok(out)
}

// ---------------------------------------------------------------- caché

/// La tabla `valores` en el SQLite del motor (se crea con IF NOT EXISTS; no toca folios).
pub struct Cache {
    pub al: Almacen,
}

const DDL: &str = "CREATE TABLE IF NOT EXISTS valores (\n  indicador   TEXT NOT NULL,\n  fecha       TEXT NOT NULL,   -- YYYY-MM-DD\n  valor       REAL NOT NULL,\n  actualizado TEXT NOT NULL,\n  PRIMARY KEY (indicador, fecha)\n);";

impl Cache {
    pub fn abrir(ruta: &str) -> Result<Cache, String> {
        let al = Almacen::abrir(ruta).map_err(|e| e.to_string())?;
        al.ejecutar_ddl(DDL)
            .map_err(|e| format!("creando tabla valores: {e}"))?;
        Ok(Cache { al })
    }

    /// Upsert de los valores. Devuelve cuántos escribió.
    pub fn guardar(&self, vs: &[Valor]) -> Result<usize, String> {
        let mut c = self.al.conexion();
        let tx = c.transaction().map_err(|e| e.to_string())?;
        let ahora = {
            let d = std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap_or_default();
            format!("{}Z", crate::servidor::fecha_hora_utc(d.as_secs() as i64))
        };
        let mut n = 0;
        for v in vs {
            tx.execute(
                "INSERT INTO valores(indicador,fecha,valor,actualizado) VALUES(?,?,?,?) ON CONFLICT(indicador,fecha) DO UPDATE SET valor=excluded.valor, actualizado=excluded.actualizado",
                rusqlite::params![v.indicador, v.fecha, v.valor, ahora],
            )
            .map_err(|e| e.to_string())?;
            n += 1;
        }
        tx.commit().map_err(|e| e.to_string())?;
        Ok(n)
    }

    /// El valor exacto de un indicador en una fecha.
    pub fn get(&self, indicador: &str, fecha: &str) -> Result<f64, String> {
        use rusqlite::OptionalExtension;
        let c = self.al.conexion();
        c.query_row(
            "SELECT valor FROM valores WHERE indicador=? AND fecha=?",
            rusqlite::params![indicador, fecha],
            |r| r.get(0),
        )
        .optional()
        .map_err(|e| e.to_string())?
        .ok_or_else(|| "sin valor cacheado".into())
    }

    /// El último valor conocido en o antes de `fecha`.
    pub fn vigente(&self, indicador: &str, fecha: &str) -> Result<Valor, String> {
        use rusqlite::OptionalExtension;
        let c = self.al.conexion();
        c.query_row(
            "SELECT indicador,fecha,valor FROM valores WHERE indicador=? AND fecha<=? ORDER BY fecha DESC LIMIT 1",
            rusqlite::params![indicador, fecha],
            |r| Ok(Valor { indicador: r.get(0)?, fecha: r.get(1)?, valor: r.get(2)? }),
        )
        .optional()
        .map_err(|e| e.to_string())?
        .ok_or_else(|| "sin valor cacheado".into())
    }

    /// El primer año con datos del indicador (0 si no hay).
    pub fn anio_minimo(&self, indicador: &str) -> Result<i32, String> {
        let c = self.al.conexion();
        let f: Option<String> = c
            .query_row(
                "SELECT MIN(fecha) FROM valores WHERE indicador=?",
                rusqlite::params![indicador],
                |r| r.get(0),
            )
            .map_err(|e| e.to_string())?;
        Ok(f.filter(|f| f.len() >= 4)
            .and_then(|f| f[..4].parse().ok())
            .unwrap_or(0))
    }
}

/// Trae y guarda todos los años [desde, hasta] de los tres indicadores (una vez; el histórico
/// no cambia). Devuelve cuántos valores guardó por indicador; no se detiene en el primer error.
pub fn cargar_historico(
    c: &Cache,
    desde: i32,
    hasta: i32,
    logf: &dyn Fn(&str),
) -> BTreeMap<String, usize> {
    let mut tot: BTreeMap<String, usize> = BTreeMap::new();
    for anio in desde..=hasta {
        for ind in ["uf", "utm", "dolar"] {
            match fetch(ind, anio) {
                Err(e) => logf(&format!("valores: {ind} {anio} falló: {e}")),
                Ok((vs, fuente)) => match c.guardar(&vs) {
                    Err(e) => logf(&format!("valores: {ind} {anio} no se guardó: {e}")),
                    Ok(n) => {
                        *tot.entry(ind.into()).or_default() += n;
                        logf(&format!("valores: {ind} {anio} → {n} (fuente: {fuente})"));
                    }
                },
            }
        }
    }
    tot
}

#[cfg(test)]
mod tests {
    use super::*;

    const UF: &str = "<table class='table'><tbody>\n<tr><th colspan='6'><h2>Octubre</h2></th></tr>\n<tr><th width='40'><strong>1</strong></th><td width='200'>41.065,38</td><th width='40'><strong>11</strong></th><td width='200'></td><th width='40'><strong>21</strong></th><td width='200'></td></tr>\n<tr><th width='40'><strong>2</strong></th><td width='200'>41.073,57</td><th width='40'><strong>12</strong></th><td width='200'></td><th width='40'><strong>22</strong></th><td width='200'></td></tr>\n</tbody></table>\n<table class='table'><tbody>\n<tr><th colspan='6'><h2>Septiembre</h2></th></tr>\n<tr><th width='40'><strong>1</strong></th><td width='200'>40.900,10</td><th width='40'><strong>11</strong></th><td width='200'>40.950,00</td><th width='40'><strong>21</strong></th><td width='200'></td></tr>\n</tbody></table>";
    const DOLAR: &str = "<table class='table'><tbody>\n<tr><th colspan='6'><h2>Octubre</h2></th></tr>\n<tr><th width='40'><strong>1</strong></th><td width='200'>972.6</td><th width='40'><strong>11</strong></th><td width='200'></td></tr>\n</tbody></table>";
    const UTM: &str = "<table id='table_export'><thead>\n<tr><th rowspan='2'>2026</th><th>UTM (1)</th><th>UTA (2)</th></tr>\n<tr><th>Valor en puntos</th></tr></thead><tbody>\n<tr><th>Enero</th><td>69.751</td><td>837.012</td><td align='center'>109,71</td></tr>\n<tr><th>Febrero</th><td>69.611</td><td>835.332</td></tr>\n</tbody></table>";

    #[test]
    fn parsea_las_paginas_del_sii() {
        let vs = parsear_uf(UF.as_bytes(), 2026).unwrap();
        assert_eq!(vs.len(), 4);
        let m: BTreeMap<&str, f64> = vs.iter().map(|v| (v.fecha.as_str(), v.valor)).collect();
        assert_eq!(m["2026-10-01"], 41065.38);
        assert_eq!(m["2026-09-11"], 40950.0);
        let d = parsear_dolar(DOLAR.as_bytes(), 2026).unwrap();
        assert_eq!(
            (d[0].fecha.as_str(), d[0].valor, d[0].indicador.as_str()),
            ("2026-10-01", 972.6, "dolar")
        );
        let u = parsear_utm(UTM.as_bytes(), 2026).unwrap();
        assert_eq!(
            (u.len(), u[0].fecha.as_str(), u[0].valor, u[1].valor),
            (2, "2026-01-01", 69751.0, 69611.0)
        );
        assert_eq!(numero_dolar("1.023,5"), Some(1023.5));
        assert_eq!(numero_cl(""), None);
        let dir = std::env::temp_dir().join(format!("valores-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let c = Cache::abrir(dir.join("v.db").to_str().unwrap()).unwrap();
        assert_eq!(c.guardar(&vs).unwrap(), 4);
        assert_eq!(c.get("uf", "2026-10-02").unwrap(), 41073.57);
        assert_eq!(c.vigente("uf", "2026-10-05").unwrap().fecha, "2026-10-02");
        assert_eq!(c.anio_minimo("uf").unwrap(), 2026);
        let _ = std::fs::remove_dir_all(dir);
    }
}
