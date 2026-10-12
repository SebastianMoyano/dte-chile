//! Rutas de api/routes/db.py: consultas directas a las tablas (dtes, cafs, audit_log).

use super::caf::leer_archivo_form;
use super::errores::{ok, ErrorHTTP, Res};
use super::http::Peticion;
use super::{entero, Prot, Servidor};
use crate::ted;
use rusqlite::types::Value as Sql;
use serde_json::{json, Map, Value};

pub fn rutas(s: &mut Servidor) {
    s.ruta("GET /api/v1/db/dtes", Prot::Protegida, db_dtes);
    s.ruta(
        "GET /api/v1/db/dtes/buscar/{rut}/{tipo}/{folio}",
        Prot::Protegida,
        db_buscar_dte,
    );
    s.ruta("GET /api/v1/db/dtes/{id}", Prot::Protegida, db_dte);
    s.ruta("GET /api/v1/db/cafs", Prot::Protegida, db_cafs);
    s.ruta(
        "GET /api/v1/db/cafs/activo/{rut}/{tipo}",
        Prot::Protegida,
        db_caf_activo,
    );
    s.ruta("POST /api/v1/db/cafs", Prot::Protegida, db_registrar_caf);
    s.ruta(
        "GET /api/v1/db/folios/siguiente/{rut}/{tipo}",
        Prot::Protegida,
        db_folio_siguiente,
    );
    s.ruta("GET /api/v1/db/logs", Prot::Protegida, db_logs);
}

const INT_PARSING: &str = "Input should be a valid integer, unable to parse string as an integer";

/// `enteroQuery`: un entero opcional de la query con los límites de `Query(ge=, le=)`.
pub fn entero_query(
    p: &Peticion,
    campo: &str,
    def: i64,
    min: i64,
    max: i64,
) -> Result<i64, ErrorHTTP> {
    let v = p.q(campo);
    if v.is_empty() {
        return Ok(def);
    }
    let n: i64 = v
        .parse()
        .map_err(|_| ErrorHTTP::query(campo, INT_PARSING, "int_parsing"))?;
    if n < min {
        return Err(ErrorHTTP::query(
            campo,
            &format!("Input should be greater than or equal to {min}"),
            "greater_than_equal",
        ));
    }
    if max > 0 && n > max {
        return Err(ErrorHTTP::query(
            campo,
            &format!("Input should be less than or equal to {max}"),
            "less_than_equal",
        ));
    }
    Ok(n)
}

/// `DTEResponse`: el subconjunto de columnas que expone la ruta.
pub fn dte_response(d: &Map<String, Value>) -> Value {
    let mut out = Map::new();
    for k in [
        "id",
        "tipo_dte",
        "folio",
        "rut_emisor",
        "rut_receptor",
        "razon_social_receptor",
        "fecha_emision",
        "monto_neto",
        "monto_exento",
        "iva",
        "monto_total",
        "estado",
        "track_id",
        "pdf_path",
        "ambiente",
        "creado_en",
    ] {
        let mut v = d.get(k).cloned().unwrap_or(Value::Null);
        if k == "track_id" {
            // Optional[int]: Python convierte "123" → 123
            if let Value::String(t) = &v {
                v = match t.trim().parse::<i64>() {
                    Ok(n) => json!(n),
                    Err(_) if t.is_empty() => Value::Null,
                    Err(_) => v.clone(),
                };
            }
        }
        out.insert(k.into(), v);
    }
    for k in ["monto_neto", "monto_exento", "iva", "monto_total"] {
        if out[k].is_null() {
            out.insert(k.into(), json!(0));
        }
    }
    Value::Object(out)
}

fn db_dtes(s: &Servidor, p: &mut Peticion) -> Res {
    let limite = entero_query(p, "limite", 100, 1, 1000)?;
    let offset = entero_query(p, "offset", 0, 0, 0)?;
    let q = p.consulta();
    let (mut cond, mut args): (Vec<&str>, Vec<Sql>) = (Vec::new(), Vec::new());
    if let Some(v) = q.get("rut_emisor").filter(|v| !v.is_empty()) {
        cond.push("rut_emisor=?");
        args.push(v.clone().into());
    }
    if let Some(v) = q.get("tipo_dte").filter(|v| !v.is_empty()) {
        let n: i64 = v
            .parse()
            .map_err(|_| ErrorHTTP::query("tipo_dte", INT_PARSING, "int_parsing"))?;
        if n != 0 {
            cond.push("tipo_dte=?");
            args.push(n.into());
        }
    }
    if let Some(v) = q.get("estado").filter(|v| !v.is_empty()) {
        cond.push("estado=?");
        args.push(v.clone().into());
    }
    let (cond_conteo, args_conteo) = (cond.clone(), args.clone());
    if let Some(v) = q.get("fecha_desde").filter(|v| !v.is_empty()) {
        cond.push("fecha_emision>=?");
        args.push(v.clone().into());
    }
    if let Some(v) = q.get("fecha_hasta").filter(|v| !v.is_empty()) {
        cond.push("fecha_emision<=?");
        args.push(v.clone().into());
    }
    let donde = if cond.is_empty() {
        "1=1".to_string()
    } else {
        cond.join(" AND ")
    };
    let donde_c = if cond_conteo.is_empty() {
        "1=1".to_string()
    } else {
        cond_conteo.join(" AND ")
    };
    args.push(limite.into());
    args.push(offset.into());
    let filas = s.filas(
        &format!("SELECT * FROM dtes WHERE {donde} ORDER BY creado_en DESC LIMIT ? OFFSET ?"),
        &args,
    )?;
    let total: i64 = s
        .escalar(
            &format!("SELECT COUNT(*) FROM dtes WHERE {donde_c}"),
            &args_conteo,
        )?
        .unwrap_or(0);
    ok(json!({"total": total, "dtes": filas.iter().map(dte_response).collect::<Vec<_>>()}))
}

fn db_dte(s: &Servidor, p: &mut Peticion) -> Res {
    let id: i64 = p
        .param("id")
        .parse()
        .map_err(|_| ErrorHTTP::path("dte_id"))?;
    let Some(d) = s.dte_por_id(id)? else {
        return Err(ErrorHTTP::no_encontrado("DTE no encontrado"));
    };
    ok(dte_response(&d))
}

fn db_buscar_dte(s: &Servidor, p: &mut Peticion) -> Res {
    let tipo: i64 = p
        .param("tipo")
        .parse()
        .map_err(|_| ErrorHTTP::path("tipo_dte"))?;
    let folio: i64 = p
        .param("folio")
        .parse()
        .map_err(|_| ErrorHTTP::path("folio"))?;
    let f = s.fila(
        "SELECT * FROM dtes WHERE rut_emisor=? AND tipo_dte=? AND folio=?",
        &sql![p.param("rut"), tipo, folio],
    )?;
    let Some(d) = f else {
        return Err(ErrorHTTP::no_encontrado("DTE no encontrado"));
    };
    ok(dte_response(&d))
}

pub fn caf_response(c: &Map<String, Value>) -> Value {
    json!({"id": c["id"], "tipo_dte": c["tipo_dte"], "rut_emisor": c["rut_emisor"], "folio_desde": c["folio_desde"],
        "folio_hasta": c["folio_hasta"], "folio_siguiente": c["folio_siguiente"], "fecha_autorizacion": c["fecha_autorizacion"],
        "activo": entero(&c["activo"]) != 0, "creado_en": c["creado_en"]})
}

impl Servidor {
    pub fn caf_activo_fila(
        &self,
        rut: &str,
        tipo: i64,
    ) -> Result<Option<Map<String, Value>>, ErrorHTTP> {
        Ok(self.fila(
            "SELECT * FROM cafs WHERE rut_emisor=? AND tipo_dte=? AND activo=1 ORDER BY folio_desde DESC LIMIT 1",
            &sql![rut, tipo],
        )?)
    }
}

fn db_cafs(s: &Servidor, p: &mut Peticion) -> Res {
    let q = p.consulta();
    let (mut cond, mut args): (Vec<&str>, Vec<Sql>) = (Vec::new(), Vec::new());
    if let Some(v) = q.get("rut_emisor").filter(|v| !v.is_empty()) {
        cond.push("rut_emisor=?");
        args.push(v.clone().into());
    }
    if let Some(v) = q.get("tipo_dte").filter(|v| !v.is_empty()) {
        let n: i64 = v
            .parse()
            .map_err(|_| ErrorHTTP::query("tipo_dte", INT_PARSING, "int_parsing"))?;
        if n != 0 {
            cond.push("tipo_dte=?");
            args.push(n.into());
        }
    }
    let donde = if cond.is_empty() {
        "1=1".to_string()
    } else {
        cond.join(" AND ")
    };
    let filas = s.filas(
        &format!("SELECT * FROM cafs WHERE {donde} ORDER BY creado_en DESC"),
        &args,
    )?;
    ok(Value::Array(filas.iter().map(caf_response).collect()))
}

fn db_caf_activo(s: &Servidor, p: &mut Peticion) -> Res {
    let tipo: i64 = p
        .param("tipo")
        .parse()
        .map_err(|_| ErrorHTTP::path("tipo_dte"))?;
    let Some(c) = s.caf_activo_fila(p.param("rut"), tipo)? else {
        return Err(ErrorHTTP::no_encontrado(
            "No hay CAF activo para estos parámetros",
        ));
    };
    ok(caf_response(&c))
}

/// `post_registrar_caf`: sube el XML, desactiva los CAF anteriores del mismo emisor+tipo y
/// registra el nuevo (folio_siguiente = folio_desde).
fn db_registrar_caf(s: &Servidor, p: &mut Peticion) -> Res {
    let (_, contenido, nombre) = leer_archivo_form(p, "archivo")?;
    if nombre.is_empty() || !nombre.to_ascii_lowercase().ends_with(".xml") {
        return Err(ErrorHTTP::validacion(
            "El archivo debe ser un CAF en formato XML.",
        ));
    }
    let texto = String::from_utf8_lossy(&contenido).into_owned();
    let caf = ted::parsear_caf(&texto)
        .map_err(|e| ErrorHTTP::caf(format!("No se pudo parsear el CAF: {e}")))?;
    let _ = s.ejecutar(
        "UPDATE cafs SET activo=0 WHERE rut_emisor=? AND tipo_dte=?",
        &sql![caf.rut_emisor.clone(), caf.tipo_dte],
    );
    s.alm
        .registrar_caf(
            caf.tipo_dte,
            &caf.rut_emisor,
            caf.folio_desde,
            caf.folio_hasta,
            &caf.fecha_autorizacion,
            &texto,
        )
        .map_err(|_| ErrorHTTP::interno())?;
    let Some(c) = s.caf_activo_fila(&caf.rut_emisor, caf.tipo_dte as i64)? else {
        return Err(ErrorHTTP::interno());
    };
    ok(caf_response(&c))
}

fn db_folio_siguiente(s: &Servidor, p: &mut Peticion) -> Res {
    let rut = p.param("rut").to_string();
    let tipo: i64 = p
        .param("tipo")
        .parse()
        .map_err(|_| ErrorHTTP::path("tipo_dte"))?;
    let Some(c) = s.caf_activo_fila(&rut, tipo)? else {
        return ok(
            json!({"rut_emisor": rut, "tipo_dte": tipo, "folio_disponible": null, "folio_desde": null, "folio_hasta": null,
            "mensaje": "No hay CAF activo. Debe registrar un CAF primero."}),
        );
    };
    let (sig, hasta) = (entero(&c["folio_siguiente"]), entero(&c["folio_hasta"]));
    if sig > hasta {
        return ok(
            json!({"rut_emisor": rut, "tipo_dte": tipo, "folio_disponible": null, "folio_desde": c["folio_desde"], "folio_hasta": c["folio_hasta"],
            "mensaje": "Rango de folios agotado. Debe solicitar nuevos folios al SII."}),
        );
    }
    ok(
        json!({"rut_emisor": rut, "tipo_dte": tipo, "folio_disponible": sig, "folio_desde": c["folio_desde"], "folio_hasta": c["folio_hasta"],
        "mensaje": format!("Siguiente folio disponible: {sig}")}),
    )
}

fn db_logs(s: &Servidor, p: &mut Peticion) -> Res {
    let limite = entero_query(p, "limite", 100, 1, 1000)?;
    let q = p.consulta();
    let (mut cond, mut args): (Vec<&str>, Vec<Sql>) = (Vec::new(), Vec::new());
    for (campo, col) in [
        ("accion", "accion=?"),
        ("rut_emisor", "rut_emisor=?"),
        ("fecha_desde", "creado_en>=?"),
    ] {
        if let Some(v) = q.get(campo).filter(|v| !v.is_empty()) {
            cond.push(col);
            args.push(v.clone().into());
        }
    }
    let donde = if cond.is_empty() {
        "1=1".to_string()
    } else {
        cond.join(" AND ")
    };
    args.push(limite.into());
    let filas = s.filas(
        &format!("SELECT * FROM audit_log WHERE {donde} ORDER BY creado_en DESC LIMIT ?"),
        &args,
    )?;
    let out: Vec<Value> = filas
        .iter()
        .map(|f| {
            let mut m = Map::new();
            for k in [
                "id",
                "accion",
                "tipo_dte",
                "folio",
                "rut_emisor",
                "detalle",
                "creado_en",
            ] {
                m.insert(k.into(), f.get(k).cloned().unwrap_or(Value::Null));
            }
            Value::Object(m)
        })
        .collect();
    ok(Value::Array(out))
}
