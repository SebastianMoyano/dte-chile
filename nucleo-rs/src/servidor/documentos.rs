//! /api/v1/dte/documentos* y /api/v1/dte/emisor, réplica de api/routes/dte.py. La
//! (re)generación del PDF (POST …/pdf) la hace `crate::pdf` desde el XML firmado.

use super::errores::{ok, ErrorHTTP, Res};
use super::http::{Peticion, Respuesta};
use super::keystore::id_de;
use super::{bytes_latin1, entero, existe_archivo, log, texto, Prot, Servidor};
use crate::pdf;
use serde_json::{json, Map, Value};
use std::path::Path;

pub type Fila = Map<String, Value>;

pub fn rutas(s: &mut Servidor) {
    s.ruta("GET /api/v1/dte/documentos", Prot::Protegida, listar);
    s.ruta(
        "GET /api/v1/dte/documentos/emisores",
        Prot::Protegida,
        emisores,
    );
    s.ruta(
        "GET /api/v1/dte/documentos/{id}/pdf",
        Prot::Protegida,
        pdf_documento,
    );
    s.ruta(
        "POST /api/v1/dte/documentos/{id}/pdf",
        Prot::Protegida,
        regenerar_pdf_documento,
    );
    s.ruta(
        "GET /api/v1/dte/documentos/{id}/xml",
        Prot::Protegida,
        xml_documento,
    );
    s.ruta(
        "GET /api/v1/dte/emisor",
        Prot::Protegida,
        emisor_configurado,
    );
}

impl Servidor {
    /// `SELECT * FROM dtes WHERE id=?` como dict.
    pub fn dte_por_id(&self, id: i64) -> Result<Option<Fila>, ErrorHTTP> {
        Ok(self.fila("SELECT * FROM dtes WHERE id=?", &sql![id])?)
    }

    /// `regenerarPDF`: dibuja el PDF desde el XML firmado (boletas en 80 mm, el resto en carta),
    /// lo guarda en storage[/simulacion]/pdfs/ y registra la ruta. Devuelve la ruta.
    pub fn regenerar_pdf(&self, d: &Fila) -> Result<String, String> {
        let xml = texto(&d["xml_firmado"]);
        if xml.is_empty() {
            return Err("sin xml".into());
        }
        let (doc, ted) = pdf::desde_xml(&bytes_latin1(&xml))?;
        let ambiente = texto(&d["ambiente"]);
        let mut base = Path::new(&self.cfg.storage_path).to_path_buf();
        if ambiente == "simulacion" {
            base = base.join("simulacion");
        }
        std::fs::create_dir_all(base.join("pdfs")).map_err(|e| e.to_string())?;
        let (tipo, folio) = (entero(&d["tipo_dte"]) as i32, entero(&d["folio"]));
        let amb = if ambiente.is_empty() {
            self.cfg.sii_ambiente.clone()
        } else {
            ambiente
        };
        let (ruta, b) = if tipo == 39 || tipo == 41 {
            (
                base.join("pdfs").join(format!("BOLETA_{tipo}_{folio}.pdf")),
                pdf::boleta_80mm(&doc, &ted)?,
            )
        } else {
            let (fecha, num) = self.resolucion_emisor(&doc.emisor.rut, &amb);
            (
                base.join("pdfs").join(format!("DTE_{tipo}_{folio}.pdf")),
                pdf::carta(
                    &doc,
                    &ted,
                    &pdf::Opciones {
                        ambiente: amb,
                        resolucion_fecha: fecha,
                        resolucion_num: num,
                        hoy: String::new(),
                    },
                )?,
            )
        };
        std::fs::write(&ruta, b).map_err(|e| e.to_string())?;
        let rel = self.ruta_para_bd(&ruta.to_string_lossy());
        self.alm
            .guardar_pdf(entero(&d["id"]), &rel)
            .map_err(|e| e.to_string())?;
        Ok(rel)
    }
}

/// `listar_documentos`: filtros, orden por creado_en DESC, límite 1..200.
fn listar(s: &Servidor, p: &mut Peticion) -> Res {
    let q = p.consulta();
    let mut limite: i64 = 25;
    if let Some(v) = q.get("limite").filter(|v| !v.is_empty()) {
        limite = v.parse().map_err(|_| {
            ErrorHTTP::query("limite", "Input should be a valid integer", "int_parsing")
        })?;
    }
    let limite = limite.clamp(1, 200);
    let mut cond = Vec::new();
    let mut args: Vec<rusqlite::types::Value> = Vec::new();
    if let Some(v) = q.get("rut_emisor").filter(|v| !v.is_empty()) {
        cond.push("rut_emisor=?");
        args.push(v.clone().into());
    }
    if let Some(v) = q.get("tipo_dte").filter(|v| !v.is_empty()) {
        let n: i64 = v.parse().map_err(|_| {
            ErrorHTTP::query("tipo_dte", "Input should be a valid integer", "int_parsing")
        })?;
        if n != 0 {
            cond.push("tipo_dte=?");
            args.push(n.into());
        }
    }
    if let Some(v) = q.get("estado").filter(|v| !v.is_empty()) {
        cond.push("estado=?");
        args.push(v.clone().into());
    }
    let donde = if cond.is_empty() {
        "1=1".to_string()
    } else {
        cond.join(" AND ")
    };
    args.push(limite.into());
    args.push(0i64.into());
    let filas = s.filas(
        &format!("SELECT * FROM dtes WHERE {donde} ORDER BY creado_en DESC LIMIT ? OFFSET ?"),
        &args,
    )?;
    let docs: Vec<Value> = filas
        .into_iter()
        .map(|mut d| {
            let xml = texto(d.get("xml_firmado").unwrap_or(&Value::Null));
            d.remove("xml_firmado");
            d.insert("tiene_xml".into(), json!(!xml.is_empty()));
            d.insert(
                "tiene_pdf".into(),
                json!(existe_archivo(&s.ruta_desde_bd(&texto(&d["pdf_path"])))),
            );
            let canal = if texto(&d["estado"]).ends_with("_mipyme") {
                "mipyme"
            } else {
                "motor"
            };
            d.insert("canal".into(), json!(canal));
            Value::Object(d)
        })
        .collect();
    ok(json!({"total": docs.len(), "documentos": docs}))
}

fn emisores(s: &Servidor, _p: &mut Peticion) -> Res {
    let mut nombres: Map<String, Value> = Map::new();
    if let Ok(filas) = s.filas("SELECT rut, razon_social FROM negocios", &[]) {
        for f in filas {
            nombres.insert(texto(&f["rut"]), f["razon_social"].clone());
        }
    }
    let filas = s.filas(
        "SELECT rut_emisor, COUNT(*) AS n, MAX(fecha_emision) AS ultimo FROM dtes GROUP BY rut_emisor ORDER BY ultimo DESC",
        &[],
    )?;
    let out: Vec<Value> = filas
        .into_iter()
        .map(|f| {
            let rut = texto(&f["rut_emisor"]);
            json!({"rut": rut, "razon_social": nombres.get(&rut).cloned().unwrap_or(Value::Null), "documentos": f["n"], "ultimo": f["ultimo"]})
        })
        .collect();
    ok(json!({"emisores": out}))
}

fn pdf_documento(s: &Servidor, p: &mut Peticion) -> Res {
    let id = id_de(p, "id")?;
    let Some(d) = s.dte_por_id(id)? else {
        return Err(ErrorHTTP::no_encontrado(format!(
            "Documento {id} no existe"
        )));
    };
    let pp = s.ruta_desde_bd(&texto(&d["pdf_path"]));
    if !existe_archivo(&pp) {
        return Err(ErrorHTTP::no_encontrado(
            "Este documento no tiene PDF guardado",
        ));
    }
    let raiz = super::abs_limpia(&s.cfg.storage_path);
    let abs = super::abs_limpia(&pp);
    if !abs.starts_with(&format!("{raiz}/")) {
        return Err(ErrorHTTP::no_encontrado(
            "Ruta de PDF fuera del almacenamiento del motor",
        ));
    }
    let b = std::fs::read(&pp)
        .map_err(|_| ErrorHTTP::no_encontrado("Este documento no tiene PDF guardado"))?;
    Ok(Respuesta::binario(200, "application/pdf", b).con(
        "Content-Disposition",
        &format!(
            "inline; filename=\"dte_{}_{}.pdf\"",
            entero(&d["tipo_dte"]),
            entero(&d["folio"])
        ),
    ))
}

fn xml_documento(s: &Servidor, p: &mut Peticion) -> Res {
    let id = id_de(p, "id")?;
    let Some(d) = s.dte_por_id(id)? else {
        return Err(ErrorHTTP::no_encontrado(format!(
            "Documento {id} no existe"
        )));
    };
    let xml = texto(&d["xml_firmado"]);
    if xml.is_empty() {
        return Err(ErrorHTTP::no_encontrado(
            "Este documento no tiene XML guardado",
        ));
    }
    Ok(
        Respuesta::binario(200, "application/xml", bytes_latin1(&xml)).con(
            "Content-Disposition",
            &format!(
                "attachment; filename=\"dte_{}_{}.xml\"",
                entero(&d["tipo_dte"]),
                entero(&d["folio"])
            ),
        ),
    )
}

fn emisor_configurado(s: &Servidor, _p: &mut Peticion) -> Res {
    let get = |k: &str| s.cfg.valor(k);
    let cod: Value = get("EMPRESA_CODIGO_ACTIVIDAD")
        .parse::<i64>()
        .map(Value::from)
        .unwrap_or(Value::Null);
    let o_nulo = |k: &str| {
        let x = get(k);
        if x.is_empty() {
            Value::Null
        } else {
            Value::String(x)
        }
    };
    ok(json!({
        "configurada": s.cfg.empresa_configurada(), "rut": s.cfg.empresa_rut, "razon_social": s.cfg.empresa_razon_social,
        "giro": get("EMPRESA_GIRO"), "codigo_actividad": cod, "direccion": get("EMPRESA_DIRECCION"), "comuna": get("EMPRESA_COMUNA"),
        "ciudad": get("EMPRESA_CIUDAD"), "email": o_nulo("EMPRESA_EMAIL"), "telefono": o_nulo("EMPRESA_TELEFONO"),
    }))
}

fn regenerar_pdf_documento(s: &Servidor, p: &mut Peticion) -> Res {
    let id = id_de(p, "id")?;
    let Some(d) = s.dte_por_id(id)? else {
        return Err(ErrorHTTP::no_encontrado(format!(
            "Documento {id} no existe"
        )));
    };
    if texto(&d["xml_firmado"]).is_empty() {
        return Err(ErrorHTTP::no_encontrado(
            "Este documento no tiene XML guardado: no se puede dibujar",
        ));
    }
    let ruta = s
        .regenerar_pdf(&d)
        .map_err(|e| ErrorHTTP::validacion(format!("No se pudo dibujar el PDF: {e}")))?;
    let _ = log;
    ok(json!({"dte_id": id, "pdf_path": ruta}))
}
