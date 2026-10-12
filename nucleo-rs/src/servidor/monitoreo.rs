//! core/monitoreo.py: salud LOCAL de los CAF (sin tocar el SII): CAF vencidos (regla CAF-3-517,
//! 6 meses desde la autorización) y folios agotándose.

use super::errores::{ok, ErrorHTTP, Res};
use super::http::Peticion;
use super::{entero, texto, Prot, Servidor};
use serde_json::{json, Map, Value};

const REGLA_MESES_CAF: i64 = 6;

pub fn rutas(s: &mut Servidor) {
    s.ruta(
        "GET /api/v1/monitoreo/folios",
        Prot::Protegida,
        monitoreo_folios,
    );
    s.ruta(
        "GET /api/v1/monitoreo/folios/cartera",
        Prot::Protegida,
        monitoreo_cartera,
    );
}

fn ymd(f: &str) -> Option<(i64, i64, i64)> {
    if f.len() < 10 {
        return None;
    }
    Some((
        f[..4].parse().ok()?,
        f[5..7].parse().ok()?,
        f[8..10].parse().ok()?,
    ))
}

fn meses(desde: (i64, i64, i64), hoy: (i64, i64, i64)) -> i64 {
    (hoy.0 - desde.0) * 12 + hoy.1 - desde.1
}

impl Servidor {
    /// `salud_caf`: un item por CAF activo con estado ok|por_vencer|vencido|bajo|agotado.
    fn salud_caf(&self, rut: &str, hoy: &str) -> Result<Vec<Value>, ErrorHTTP> {
        let filas = self.filas(
            "SELECT tipo_dte, folio_desde, folio_hasta, COALESCE(folio_siguiente,0) AS sig, COALESCE(fecha_autorizacion,'') AS fa FROM cafs WHERE rut_emisor=? AND activo=1 ORDER BY tipo_dte, folio_desde",
            &sql![rut],
        )?;
        let h = ymd(hoy).unwrap_or((2026, 1, 1));
        let mut out = Vec::new();
        for f in filas {
            let (tipo, desde, hasta, mut sig) = (
                entero(&f["tipo_dte"]),
                entero(&f["folio_desde"]),
                entero(&f["folio_hasta"]),
                entero(&f["sig"]),
            );
            let fa_txt = texto(&f["fa"]);
            let fa = ymd(&fa_txt).unwrap_or(h);
            let m = meses(fa, h);
            if sig == 0 {
                sig = desde;
            }
            let restantes = (hasta - sig + 1).max(0);
            let total = hasta - desde + 1;
            let umbral_bajo = (total / 10).max(3);
            let (estado, detalle) = if m >= REGLA_MESES_CAF {
                ("vencido", format!("CAF de hace {m} meses (máx {REGLA_MESES_CAF} por el SII). No se puede usar; timbra folios nuevos."))
            } else if restantes == 0 {
                ("agotado", "Sin folios disponibles en este CAF.".to_string())
            } else if restantes <= umbral_bajo {
                (
                    "bajo",
                    format!("Quedan {restantes} de {total} folios — pide más pronto."),
                )
            } else if m >= REGLA_MESES_CAF - 1 {
                (
                    "por_vencer",
                    format!("Vence este mes (tiene {m} meses). Usa estos folios ya."),
                )
            } else {
                ("ok", format!("{restantes} de {total} folios disponibles."))
            };
            out.push(json!({"tipo_dte": tipo, "rango": [desde, hasta], "folio_siguiente": sig, "restantes": restantes,
                "total": total, "fecha_autorizacion": format!("{:04}-{:02}-{:02}", fa.0, fa.1, fa.2), "meses": m, "estado": estado, "detalle": detalle}));
        }
        Ok(out)
    }

    fn resumen_salud(&self, rut: &str, hoy: &str) -> Result<Value, ErrorHTTP> {
        let cafs = self.salud_caf(rut, hoy)?;
        let mut por_estado: Map<String, Value> = Map::new();
        for c in &cafs {
            let e = texto(&c["estado"]);
            let n = por_estado.get(&e).map(entero).unwrap_or(0);
            por_estado.insert(e, json!(n + 1));
        }
        let cuenta = |k: &str| por_estado.get(k).map(entero).unwrap_or(0);
        let critico = cuenta("vencido") + cuenta("agotado");
        let atencion = cuenta("bajo") + cuenta("por_vencer");
        let verdict = if critico > 0 {
            "critico"
        } else if atencion > 0 {
            "atencion"
        } else {
            "ok"
        };
        Ok(
            json!({"rut": rut, "total_cafs": cafs.len(), "por_estado": por_estado, "verdict": verdict, "cafs": cafs}),
        )
    }
}

fn monitoreo_folios(s: &Servidor, p: &mut Peticion) -> Res {
    let rut = p.q("rut");
    if rut.is_empty() {
        return Err(ErrorHTTP::query("rut", "Field required", "missing"));
    }
    ok(s.resumen_salud(&rut, &super::demo::hoy_iso())?)
}

/// `salud_cartera`: todas las empresas con CAF activo, ordenadas por urgencia.
fn monitoreo_cartera(s: &Servidor, _p: &mut Peticion) -> Res {
    let ruts: Vec<String> = s
        .filas(
            "SELECT DISTINCT rut_emisor FROM cafs WHERE activo=1 ORDER BY rut_emisor",
            &[],
        )?
        .iter()
        .map(|f| texto(&f["rut_emisor"]))
        .collect();
    let hoy = super::demo::hoy_iso();
    let mut empresas: Vec<Value> = ruts
        .iter()
        .filter_map(|r| s.resumen_salud(r, &hoy).ok())
        .collect();
    let orden = |v: &Value| match texto(&v["verdict"]).as_str() {
        "critico" => 0,
        "atencion" => 1,
        _ => 2,
    };
    empresas.sort_by_key(orden);
    let atencion: Vec<String> = empresas
        .iter()
        .filter(|e| texto(&e["verdict"]) != "ok")
        .map(|e| texto(&e["rut"]))
        .collect();
    ok(
        json!({"total_empresas": empresas.len(), "requieren_atencion": atencion, "empresas": empresas}),
    )
}
