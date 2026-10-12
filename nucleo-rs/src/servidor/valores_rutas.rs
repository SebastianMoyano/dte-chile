//! Rutas /api/v1/valores*, réplica de api/routes/valores.py (solo lectura de la tabla `valores`,
//! que llena `crate::valores`). Mismos JSON, mismos códigos.

use super::demo::{fecha_valida, hoy_iso};
use super::errores::{ok, ErrorHTTP, Res};
use super::http::Peticion;
use super::{entero, texto, Prot, Servidor};
use serde_json::{json, Map, Value};

const INDICADORES: [&str; 3] = ["uf", "utm", "dolar"];

pub fn rutas(s: &mut Servidor) {
    s.ruta("GET /api/v1/valores", Prot::Protegida, vigentes);
    s.ruta("GET /api/v1/valores/{$}", Prot::Protegida, vigentes);
    s.ruta("GET /api/v1/valores/historico", Prot::Protegida, historico);
    s.ruta(
        "GET /api/v1/valores/{indicador}/serie",
        Prot::Protegida,
        serie,
    );
    s.ruta("GET /api/v1/valores/{indicador}", Prot::Protegida, uno);
}

/// Días desde el 1970-01-01 de una fecha ISO.
fn dias(f: &str) -> i64 {
    let (a, m, d) = (
        f[..4].parse::<i64>().unwrap_or(1970),
        f[5..7].parse::<i64>().unwrap_or(1),
        f[8..10].parse::<i64>().unwrap_or(1),
    );
    let (y, mm) = if m <= 2 { (a - 1, m + 9) } else { (a, m - 3) };
    let era = y.div_euclid(400);
    let yoe = y - era * 400;
    let doy = (153 * mm + 2) / 5 + d - 1;
    let doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    era * 146097 + doe - 719468
}

impl Servidor {
    /// `_vigente`: último valor en o antes de la fecha; la UTM del mismo mes no es rezago.
    fn vigente(&self, indicador: &str, fecha: &str) -> Result<Option<Value>, ErrorHTTP> {
        let Some(f) = self.fila(
            "SELECT indicador, fecha, valor, actualizado FROM valores WHERE indicador=? AND fecha<=? ORDER BY fecha DESC LIMIT 1",
            &sql![indicador, fecha],
        )?
        else {
            return Ok(None);
        };
        let fv = texto(&f["fecha"]);
        let mut rezago = dias(fecha) - dias(&fv);
        if indicador == "utm" && fecha[..7] == fv[..7] {
            rezago = 0;
        }
        Ok(Some(
            json!({"indicador": indicador, "fecha": fecha, "valor": f["valor"], "fecha_valor": fv, "actualizado": f["actualizado"], "rezago_dias": rezago}),
        ))
    }
}

fn vigentes(s: &Servidor, p: &mut Peticion) -> Res {
    let mut f = p.q("fecha");
    if f.is_empty() {
        f = hoy_iso();
    }
    if !fecha_valida(&f) {
        return Err(ErrorHTTP::validacion(format!("Fecha inválida: {f}")));
    }
    let mut out = Map::new();
    out.insert("fecha".into(), json!(f));
    let mut alguno = false;
    for k in INDICADORES {
        let v = s.vigente(k, &f)?;
        alguno |= v.is_some();
        out.insert(k.into(), v.unwrap_or(Value::Null));
    }
    if !alguno {
        return Err(ErrorHTTP::no_encontrado(
            "No hay indicadores cacheados: corre `nucleo-valores actualizar` (o abre la app)",
        ));
    }
    ok(Value::Object(out))
}

fn historico(s: &Servidor, p: &mut Peticion) -> Res {
    let txt = p.q("anio");
    let anio: i64 = txt.parse().unwrap_or(0);
    if txt.is_empty() || !(2000..=2100).contains(&anio) {
        return Err(ErrorHTTP::query("anio", "anio inválido", "value_error"));
    }
    let mut meses = Vec::new();
    for m in 1..=12 {
        let f = format!("{anio:04}-{m:02}-01");
        let mut fila = Map::new();
        fila.insert("mes".into(), json!(&f[..7]));
        for k in INDICADORES {
            let v = s.vigente(k, &f)?;
            let val = match v {
                Some(v) if entero(&v["rezago_dias"]) <= 7 => v["valor"].clone(),
                _ => Value::Null,
            };
            fila.insert(k.into(), val);
        }
        for k in ["uf", "dolar"] {
            let r = s.fila(
                "SELECT valor, fecha FROM valores WHERE indicador=? AND fecha LIKE ? ORDER BY fecha DESC LIMIT 1",
                &sql![k, format!("{}%", &f[..7])],
            )?;
            fila.insert(
                format!("{k}_fin"),
                r.map(|r| r["valor"].clone()).unwrap_or(Value::Null),
            );
        }
        meses.push(Value::Object(fila));
    }
    let anios: Vec<Value> = s
        .filas(
            "SELECT DISTINCT substr(fecha,1,4) AS a FROM valores ORDER BY a",
            &[],
        )
        .unwrap_or_default()
        .iter()
        .map(|f| f["a"].clone())
        .collect();
    ok(json!({"anio": anio, "meses": meses, "anios_disponibles": anios}))
}

fn serie(s: &Servidor, p: &mut Peticion) -> Res {
    let ind = p.param("indicador").to_string();
    let (desde, hasta) = (p.q("desde"), p.q("hasta"));
    if desde.is_empty() || hasta.is_empty() {
        let faltan: Vec<Value> = [("desde", &desde), ("hasta", &hasta)]
            .iter()
            .filter(|(_, v)| v.is_empty())
            .map(|(k, _)| json!({"loc": ["query", k], "msg": "Field required", "type": "missing"}))
            .collect();
        return Err(ErrorHTTP::datos_invalidos().detalle(json!({"errores": faltan})));
    }
    if !INDICADORES.contains(&ind.as_str()) {
        return Err(ErrorHTTP::validacion(format!(
            "Indicador desconocido: {ind}"
        )));
    }
    let filas = s.filas(
        "SELECT fecha, valor FROM valores WHERE indicador=? AND fecha BETWEEN ? AND ? ORDER BY fecha",
        &sql![ind.clone(), desde.clone(), hasta.clone()],
    )?;
    let serie: Vec<Value> = filas
        .iter()
        .map(|f| json!({"fecha": f["fecha"], "valor": f["valor"]}))
        .collect();
    ok(json!({"indicador": ind, "desde": desde, "hasta": hasta, "serie": serie}))
}

fn uno(s: &Servidor, p: &mut Peticion) -> Res {
    let ind = p.param("indicador").to_string();
    if !INDICADORES.contains(&ind.as_str()) {
        return Err(ErrorHTTP::validacion(format!(
            "Indicador desconocido: {ind} (uf | utm | dolar)"
        )));
    }
    let mut f = p.q("fecha");
    if f.is_empty() {
        f = hoy_iso();
    }
    if !fecha_valida(&f) {
        return Err(ErrorHTTP::validacion(format!("Fecha inválida: {f}")));
    }
    match s.vigente(&ind, &f)? {
        Some(v) => ok(v),
        None => Err(ErrorHTTP::no_encontrado(format!(
            "Sin {ind} cacheado en o antes de {f}"
        ))),
    }
}
