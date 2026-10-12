//! /api/v1/simulacion/*: la práctica con EMPRESA DEMO SPA, réplica de api/routes/simulacion.py
//! y core/simulacion.py, emitiendo con `crate::emision` y dibujando el PDF con `crate::pdf`.

use super::demo::*;
use super::errores::{ok, ErrorHTTP, Res};
use super::http::Peticion;
use super::keystore::id_de;
use super::{entero, existe_archivo, log, texto, Json, Prot, Servidor};
use crate::emision;
use base64::Engine;
use serde_json::{json, Value};
use std::path::{Path, PathBuf};

pub fn rutas(s: &mut Servidor) {
    s.ruta("GET /api/v1/simulacion/estado", Prot::Protegida, sim_estado);
    s.ruta(
        "POST /api/v1/simulacion/emitir",
        Prot::Protegida,
        sim_emitir,
    );
    s.ruta(
        "POST /api/v1/simulacion/anular/{id}",
        Prot::Protegida,
        sim_anular,
    );
    s.ruta(
        "GET /api/v1/simulacion/documentos/{id}",
        Prot::Protegida,
        sim_ver,
    );
    s.ruta(
        "POST /api/v1/simulacion/reiniciar",
        Prot::Protegida,
        sim_reiniciar,
    );
}

#[derive(Debug, Clone, Default)]
pub struct ItemDemo {
    pub nombre: Option<String>,
    pub precio_unitario: Option<f64>,
    pub cantidad: Option<f64>,
    pub exento: bool,
}

#[derive(Debug, Clone, Default)]
pub struct ReceptorDemo {
    pub rut: Option<String>,
    pub razon_social: Option<String>,
    pub giro: String,
    pub direccion: String,
    pub comuna: String,
    pub ciudad: String,
}

fn item_de(v: &Value) -> Result<ItemDemo, ErrorHTTP> {
    let j = Json(v.clone());
    if !v.is_object() {
        return Err(ErrorHTTP::json_invalido());
    }
    Ok(ItemDemo {
        nombre: j.texto("nombre")?,
        precio_unitario: j.decimal("precio_unitario")?,
        cantidad: j.decimal("cantidad")?,
        exento: j.logico_o("exento", false)?,
    })
}

fn receptor_de(v: &Value) -> Result<ReceptorDemo, ErrorHTTP> {
    if !v.is_object() {
        return Err(ErrorHTTP::json_invalido());
    }
    let j = Json(v.clone());
    Ok(ReceptorDemo {
        rut: j.texto("rut")?,
        razon_social: j.texto("razon_social")?,
        giro: j.texto_o("giro", "")?,
        direccion: j.texto_o("direccion", "")?,
        comuna: j.texto_o("comuna", "")?,
        ciudad: j.texto_o("ciudad", "")?,
    })
}

impl Servidor {
    pub fn carpeta_demo(&self) -> PathBuf {
        Path::new(&self.cfg.storage_path).join("simulacion")
    }

    /// `asegurar_mundo`: carpeta, y un CAF por tipo si falta.
    pub fn asegurar_mundo(&self) -> Result<(), String> {
        std::fs::create_dir_all(self.carpeta_demo()).map_err(|e| e.to_string())?;
        for t in TIPOS_DEMO {
            if self
                .alm
                .caf_activo(RUT_DEMO, t)
                .map_err(|e| e.to_string())?
                .is_some()
            {
                continue;
            }
            let xml = caf_ficticio(t, 1, FOLIOS_POR_TIPO)?;
            self.alm
                .registrar_caf(t, RUT_DEMO, 1, FOLIOS_POR_TIPO, &hoy_iso(), &xml)
                .map_err(|e| e.to_string())?;
        }
        Ok(())
    }

    /// `_resultado`: la fila del documento más el PDF en base64 si existe.
    pub fn resultado_demo(&self, id: i64) -> Result<Value, ErrorHTTP> {
        let Some(d) = self.dte_por_id(id)? else {
            return Err(ErrorHTTP::interno());
        };
        let mut pdf_b64 = Value::Null;
        let pp = self.ruta_desde_bd(&texto(&d["pdf_path"]));
        if existe_archivo(&pp) {
            if let Ok(b) = std::fs::read(&pp) {
                pdf_b64 = Value::String(base64::engine::general_purpose::STANDARD.encode(b));
            }
        }
        Ok(json!({
            "dte_id": d["id"], "tipo_dte": d["tipo_dte"], "folio": d["folio"], "fecha_emision": d["fecha_emision"],
            "receptor": d["rut_receptor"], "razon_social_receptor": d["razon_social_receptor"],
            "monto_neto": d["monto_neto"], "monto_exento": d["monto_exento"], "iva": d["iva"], "monto_total": d["monto_total"],
            "ambiente": d["ambiente"], "estado": d["estado"], "pdf_path": d["pdf_path"], "pdf_b64": pdf_b64,
        }))
    }

    /// `simulacion.emitir`: arma el documento, emite con el núcleo (con XSD), marca simulado y
    /// dibuja el PDF. Devuelve el id.
    pub fn emitir_demo(
        &self,
        tipo: i32,
        items: &[ItemDemo],
        receptor: Option<&ReceptorDemo>,
        refs: Vec<Value>,
        fecha: &str,
    ) -> Result<i64, String> {
        self.asegurar_mundo()?;
        let cert = self.certificado_demo()?;
        let es_boleta = tipo == 39 || tipo == 41;
        let exento_forzado = tipo == 34 || tipo == 41;
        let its: Vec<Value> = items
            .iter()
            .enumerate()
            .map(|(i, it)| {
                let mut nombre = it.nombre.clone().filter(|n| !n.is_empty()).unwrap_or_else(|| "Venta".into());
                if nombre.chars().count() > 80 {
                    nombre = nombre.chars().take(80).collect();
                }
                let cant = it.cantidad.filter(|c| *c != 0.0).unwrap_or(1.0);
                json!({"numero_linea": i + 1, "nombre": nombre, "cantidad": cant, "precio_unitario": it.precio_unitario.unwrap_or(0.0), "exento": it.exento || exento_forzado})
            })
            .collect();
        let receptor_v = match receptor {
            Some(r) => {
                json!({"rut": r.rut.clone().unwrap_or_default(), "razon_social": r.razon_social.clone().unwrap_or_default(), "giro": r.giro,
                "direccion": r.direccion, "comuna": r.comuna, "ciudad": r.ciudad})
            }
            None if es_boleta => {
                json!({"rut": RUT_CONSUMIDOR_FINAL, "razon_social": "CONSUMIDOR FINAL"})
            }
            None => cliente_demo(),
        };
        let mut doc = json!({"tipo_dte": tipo, "folio": 0, "fecha_emision": fecha, "emisor": emisor_demo(), "forma_pago": 1, "items": its, "receptor": receptor_v});
        if !refs.is_empty() {
            doc["referencias"] = Value::Array(refs);
        }
        let d = emision::documento_desde_valor(&doc)?;
        let ctx = emision::Contexto {
            almacen: &self.alm,
            cert: &cert,
            storage_base: self.carpeta_demo().to_string_lossy().into_owned(),
            ambiente: AMBIENTE_DEMO.into(),
            fecha_resolucion: "2026-01-01".into(),
            numero_resolucion: 0,
            marca: crate::almacen::ahora_iso()[..19].to_string(),
            validar: true,
        };
        let res = emision::emitir(&ctx, d).map_err(|e| e.mensaje)?;
        let _ = self.ejecutar(
            "UPDATE dtes SET ambiente=?, estado=? WHERE id=?",
            &sql![AMBIENTE_DEMO, ESTADO_DEMO, res.dte_id],
        );
        if let Ok(Some(d)) = self.dte_por_id(res.dte_id) {
            if let Err(e) = self.regenerar_pdf(&d) {
                log(&format!(
                    "práctica: PDF del documento {} no generado: {e}",
                    res.dte_id
                ));
            }
        }
        Ok(res.dte_id)
    }
}

fn sim_estado(s: &Servidor, _p: &mut Peticion) -> Res {
    s.asegurar_mundo().map_err(|_| ErrorHTTP::interno())?;
    let mut folios = serde_json::Map::new();
    for t in TIPOS_DEMO {
        let v = match s.alm.caf_activo(RUT_DEMO, t) {
            Ok(Some(c)) => json!({"siguiente": c.folio_siguiente, "hasta": c.folio_hasta}),
            _ => Value::Null,
        };
        folios.insert(t.to_string(), v);
    }
    let n: i64 = s
        .escalar(
            "SELECT COUNT(*) FROM dtes WHERE rut_emisor=?",
            &sql![RUT_DEMO],
        )?
        .unwrap_or(0);
    ok(
        json!({"empresa": emisor_demo(), "documentos": n, "folios": folios, "ambiente": AMBIENTE_DEMO}),
    )
}

fn sim_emitir(s: &Servidor, p: &mut Peticion) -> Res {
    let j = Json::leer(p)?;
    let tipo = j.entero("tipo_dte")?;
    let items_v = match j.get("items") {
        None => None,
        Some(Value::Array(a)) => Some(a.clone()),
        Some(_) => return Err(ErrorHTTP::json_invalido()),
    };
    let mut f = Vec::new();
    if tipo.is_none() {
        f.push("tipo_dte");
    }
    if items_v.is_none() {
        f.push("items");
    }
    if !f.is_empty() {
        return Err(ErrorHTTP::faltan(&f));
    }
    let tipo = tipo.unwrap_or(0) as i32;
    let items: Vec<ItemDemo> = items_v
        .unwrap_or_default()
        .iter()
        .map(item_de)
        .collect::<Result<_, _>>()?;
    for it in &items {
        let malo = it.nombre.is_none()
            || it.precio_unitario.is_none()
            || it.precio_unitario.unwrap_or(0.0) < 0.0
            || it.cantidad.map(|c| c < 0.0).unwrap_or(false)
            || it
                .nombre
                .as_ref()
                .map(|n| n.chars().count() > 80)
                .unwrap_or(false);
        if malo {
            return Err(ErrorHTTP::pydantic(
                "body",
                "items",
                "ítem inválido",
                "value_error",
            ));
        }
    }
    let receptor = match j.get("receptor") {
        None => None,
        Some(v) => Some(receptor_de(v)?),
    };
    if let Some(r) = &receptor {
        if r.rut.is_none() || r.razon_social.is_none() {
            return Err(ErrorHTTP::pydantic(
                "body",
                "receptor",
                "Field required",
                "missing",
            ));
        }
    }
    if !TIPOS_DEMO.contains(&tipo) {
        return Err(ErrorHTTP::validacion(
            "La simulación solo emite tipos (33, 34, 39, 41, 56, 61)",
        )
        .detalle(json!({"tipo_dte": tipo})));
    }
    if items.is_empty() {
        return Err(ErrorHTTP::validacion("Hace falta al menos un ítem"));
    }
    let mut fecha = hoy_iso();
    if let Some(fv) = j.texto("fecha")?.filter(|f| !f.is_empty()) {
        if !fecha_valida(&fv) {
            return Err(ErrorHTTP::pydantic(
                "body",
                "fecha",
                "fecha inválida",
                "date_parsing",
            ));
        }
        fecha = fv;
    }
    let id = s
        .emitir_demo(tipo, &items, receptor.as_ref(), Vec::new(), &fecha)
        .map_err(ErrorHTTP::validacion)?;
    ok(s.resultado_demo(id)?)
}

fn sim_anular(s: &Servidor, p: &mut Peticion) -> Res {
    let id = id_de(p, "id")?;
    let mut motivo = "Anula documento".to_string();
    if !p.cuerpo.is_empty() {
        let j = Json::leer(p)?;
        if let Some(m) = j.texto("motivo")? {
            if m.chars().count() > 90 {
                return Err(ErrorHTTP::datos_invalidos());
            }
            motivo = m;
        }
    }
    let d = s.dte_por_id(id)?;
    let Some(d) =
        d.filter(|d| texto(&d["rut_emisor"]) == RUT_DEMO && texto(&d["ambiente"]) == AMBIENTE_DEMO)
    else {
        return Err(ErrorHTTP::no_encontrado(
            "Ese documento no es de la simulación",
        ));
    };
    let tipo = entero(&d["tipo_dte"]) as i32;
    if tipo == 56 || tipo == 61 {
        return Err(ErrorHTTP::validacion(
            "Una nota de crédito o débito no se anula con otra nota de crédito en este curso",
        ));
    }
    if texto(&d["estado"]) == "anulado_simulado" {
        return Err(ErrorHTTP::validacion("Ese documento ya fue anulado"));
    }
    let nombre = nombre_tipo(tipo);
    let folio = entero(&d["folio"]);
    let mut items = Vec::new();
    let neto = entero(&d["monto_neto"]);
    if neto != 0 {
        items.push(ItemDemo {
            nombre: Some(format!("Anula {nombre} folio {folio}")),
            precio_unitario: Some(neto as f64),
            ..Default::default()
        });
    }
    let ex = entero(&d["monto_exento"]);
    if ex != 0 {
        items.push(ItemDemo {
            nombre: Some(format!("Anula {nombre} folio {folio} (exento)")),
            precio_unitario: Some(ex as f64),
            exento: true,
            ..Default::default()
        });
    }
    let mut razon = texto(&d["razon_social_receptor"]);
    if razon.is_empty() {
        razon = "CONSUMIDOR FINAL".into();
    }
    let rec = ReceptorDemo {
        rut: Some(texto(&d["rut_receptor"])),
        razon_social: Some(razon),
        ..Default::default()
    };
    if motivo.chars().count() > 90 {
        motivo = motivo.chars().take(90).collect();
    }
    let fecha_ref: String = texto(&d["fecha_emision"]).chars().take(10).collect();
    let refs = vec![
        json!({"numero_linea": 1, "tipo_doc_ref": tipo, "folio_ref": folio, "fecha_doc_ref": fecha_ref, "codigo_ref": 1, "razon_ref": motivo}),
    ];
    let nc_id = s
        .emitir_demo(61, &items, Some(&rec), refs, &hoy_iso())
        .map_err(ErrorHTTP::validacion)?;
    let _ = s.ejecutar(
        "UPDATE dtes SET estado='anulado_simulado' WHERE id=?",
        &sql![id],
    );
    ok(s.resultado_demo(nc_id)?)
}

fn sim_ver(s: &Servidor, p: &mut Peticion) -> Res {
    let id = id_de(p, "id")?;
    let d = s.dte_por_id(id).ok().flatten();
    if d.map(|d| texto(&d["rut_emisor"]) != RUT_DEMO)
        .unwrap_or(true)
    {
        return Err(ErrorHTTP::no_encontrado(
            "Ese documento no es de la simulación",
        ));
    }
    ok(s.resultado_demo(id)?)
}

fn sim_reiniciar(s: &Servidor, _p: &mut Peticion) -> Res {
    let a = s
        .ejecutar("DELETE FROM dtes WHERE rut_emisor=?", &sql![RUT_DEMO])
        .unwrap_or(0);
    let b = s
        .ejecutar("DELETE FROM cafs WHERE rut_emisor=?", &sql![RUT_DEMO])
        .unwrap_or(0);
    let _ = std::fs::remove_dir_all(s.carpeta_demo());
    s.asegurar_mundo().map_err(|_| ErrorHTTP::interno())?;
    ok(json!({"documentos_borrados": a, "cafs_borrados": b}))
}

pub fn nombre_tipo(t: i32) -> String {
    match t {
        33 => "factura",
        34 => "factura exenta",
        39 => "boleta",
        41 => "boleta exenta",
        52 => "guía",
        56 => "nota de débito",
        61 => "nota de crédito",
        _ => return format!("tipo {t}"),
    }
    .into()
}
