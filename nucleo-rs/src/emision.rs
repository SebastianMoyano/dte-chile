//! El orquestador: folio → TED → XML → firma → sobre → XSD → disco → BD, en el mismo orden y
//! con las mismas rutas y filas que `core/orchestrator.py::OrquestadorDTE` y `nucleo/emision`
//! (Go). No genera PDF ni envía al SII.

use crate::almacen::{self, Almacen};
use crate::firma::Certificado;
use crate::ted;
use crate::totales;
use crate::xmlgen::{self, Documento};
use crate::xsd;
use serde_json::{json, Value};
use std::collections::BTreeMap;
use std::path::Path;

/// Un error de dominio con el mismo código y status que `core/errors.py`: sin_folios/folio/
/// conflicto (409), caf/certificado/validacion (422); `Interno` es un 500.
#[derive(Debug, Clone)]
pub struct Error {
    pub codigo: String,
    pub status: u16,
    pub mensaje: String,
    pub detalle: Option<Value>,
}

impl std::fmt::Display for Error {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.mensaje)
    }
}

impl std::error::Error for Error {}

impl Error {
    fn de(codigo: &str, status: u16, m: impl Into<String>, detalle: Option<Value>) -> Error {
        Error {
            codigo: codigo.into(),
            status,
            mensaje: m.into(),
            detalle,
        }
    }
    pub fn sin_folios(rut: &str, tipo: i32) -> Error {
        Error::de("sin_folios", 409, format!("No hay folios disponibles para el emisor {rut} y tipo DTE {tipo}. Verifique que el CAF esté cargado y activo."), Some(json!({"rut_emisor": rut, "tipo_dte": tipo})))
    }
    pub fn folio(m: impl Into<String>, d: Value) -> Error {
        Error::de("folio", 409, m, Some(d))
    }
    pub fn conflicto(m: impl Into<String>, d: Value) -> Error {
        Error::de("conflicto", 409, m, Some(d))
    }
    pub fn caf(m: impl Into<String>) -> Error {
        Error::de("caf", 422, m, None)
    }
    pub fn validacion(m: impl Into<String>) -> Error {
        Error::de("validacion", 422, m, None)
    }
    pub fn certificado(m: impl Into<String>) -> Error {
        Error::de("certificado", 422, m, None)
    }
    pub fn interno(m: impl Into<String>) -> Error {
        Error::de("error_interno", 500, m, None)
    }
}

impl From<almacen::Error> for Error {
    fn from(e: almacen::Error) -> Self {
        Error::interno(e.to_string())
    }
}
impl From<std::io::Error> for Error {
    fn from(e: std::io::Error) -> Self {
        Error::interno(e.to_string())
    }
}

/// Lo que la emisión necesita del motor.
pub struct Contexto<'a> {
    pub almacen: &'a Almacen,
    pub cert: &'a Certificado,
    /// p. ej. "storage"
    pub storage_base: String,
    /// certificacion | produccion | simulacion
    pub ambiente: String,
    pub fecha_resolucion: String,
    pub numero_resolucion: i64,
    /// hora (reloj único); el llamador decide si fija o no
    pub marca: String,
    /// validar el sobre contra el XSD ANTES de escribirlo y persistirlo (el folio ya está consumido)
    pub validar: bool,
}

#[derive(Debug, Clone, Default, serde::Serialize)]
pub struct Resultado {
    pub dte_id: i64,
    pub folio: i32,
    pub tipo_dte: i32,
    pub monto_total: i64,
    pub xml_dte_path: String,
    pub pdf_path: String,
    pub xml_envio_path: String,
    pub ambiente: String,
    pub mensaje: String,
    /// el sobre firmado (ISO-8859-1), para xml_envio_b64 de la API
    #[serde(skip)]
    pub envio: Vec<u8>,
}

pub fn es_boleta(t: i32) -> bool {
    t == 39 || t == 41
}

/// El documento listo: totales, TED, DTE firmado y sobre (lo que comparten la emisión real y
/// la previsualización).
pub struct Preparado {
    pub documento: Documento,
    pub monto_neto: i64,
    pub monto_exento: i64,
    pub iva: i64,
    pub monto_total: i64,
    pub ted: String,
    /// el DTE tal como se firmó (string; ISO-8859-1 al escribirlo)
    pub dte_firmado: String,
    /// el sobre, ISO-8859-1
    pub envio: Vec<u8>,
    pub raiz: String,
}

pub fn items_totales(d: &Documento) -> Vec<totales::Item> {
    d.items
        .iter()
        .map(|it| totales::Item {
            cantidad: it.cantidad,
            precio_unitario: it.precio_unitario,
            descuento_pct: it.descuento_pct,
            descuento_monto: it.descuento_monto,
            exento: it.exento,
        })
        .collect()
}

pub fn monto_total_de(d: &Documento) -> i64 {
    totales::calcular(&items_totales(d), d.tipo_dte).monto_total
}

/// pasos 5-8b (totales → TED → XML → firma standalone → sobre por string → XSD).
fn preparar(c: &Contexto, mut d: Documento, caf: &ted::Caf) -> Result<Preparado, Error> {
    let (rut, tipo) = (d.emisor.rut.clone(), d.tipo_dte);
    let tot = totales::calcular(&items_totales(&d), tipo);
    let primer = d
        .items
        .first()
        .map(|i| i.nombre.clone())
        .unwrap_or_else(|| "Sin Items".into());
    d.marca = c.marca.clone();
    d.ted = ted::generar(
        caf,
        &ted::Datos {
            folio: d.folio,
            rut_emisor: rut.clone(),
            rut_receptor: d.receptor.rut.clone(),
            tipo_dte: tipo,
            fecha_emision: d.fecha_emision.clone(),
            monto_total: tot.monto_total,
            razon_social_receptor: d.receptor.razon_social.clone(),
            primer_item: primer,
            marca: c.marca.clone(),
            primer_item_literal: false,
        },
    )
    .map_err(|e| Error::caf(format!("No se pudo generar el TED: {e}")))?;
    let arbol = if es_boleta(tipo) {
        xmlgen::generar_boleta(&d)
    } else {
        xmlgen::generar_dte(&d)
    };
    let firmado = c
        .cert
        .firmar_dte(&arbol.string(), &arbol.hijos[0].string(), tipo, d.folio)
        .map_err(|e| Error::certificado(format!("No se pudo firmar el DTE: {e}")))?;
    let rut_envia = c
        .cert
        .rut_emisor()
        .map_err(|e| Error::certificado(format!("El certificado no trae RUT: {e}")))?;
    let raiz = if es_boleta(tipo) {
        "EnvioBOLETA"
    } else {
        "EnvioDTE"
    };
    let mut sub = BTreeMap::new();
    sub.insert(tipo, 1);
    let envio = c
        .cert
        .sobre(
            std::slice::from_ref(&firmado),
            &sub,
            &rut,
            &rut_envia,
            &c.fecha_resolucion,
            c.numero_resolucion,
            raiz,
            &c.marca,
        )
        .map_err(|e| Error::validacion(format!("No se pudo armar el sobre: {e}")))?;
    if c.validar {
        xsd::validar_error(&envio).map_err(|e| {
            Error::validacion(format!("el sobre no valida contra el XSD del SII: {e}"))
        })?;
    }
    Ok(Preparado {
        ted: d.ted.clone(),
        documento: d,
        monto_neto: tot.monto_neto,
        monto_exento: tot.monto_exento,
        iva: tot.iva_monto,
        monto_total: tot.monto_total,
        dte_firmado: firmado,
        envio,
        raiz: raiz.into(),
    })
}

/// `core/preview.py`: firma + TED + XSD con el CAF dado, SIN consumir folio ni tocar disco/BD.
/// Si `folio <= 0` usa el primer folio del CAF (solo para mirar).
pub fn previsualizar(c: &Contexto, mut d: Documento, caf: &ted::Caf) -> Result<Preparado, Error> {
    if d.folio <= 0 {
        d.folio = caf.folio_desde;
    }
    if d.folio < caf.folio_desde || d.folio > caf.folio_hasta {
        return Err(Error::folio(
            format!(
                "El folio {} no está en el rango del CAF [{}-{}].",
                d.folio, caf.folio_desde, caf.folio_hasta
            ),
            json!({"folio": d.folio, "desde": caf.folio_desde, "hasta": caf.folio_hasta}),
        ));
    }
    preparar(c, d, caf)
}

/// Procesa un documento. Si `folio == 0` lo asigna atómicamente desde el CAF activo.
pub fn emitir(c: &Contexto, mut d: Documento) -> Result<Resultado, Error> {
    let (rut, tipo) = (d.emisor.rut.clone(), d.tipo_dte);
    let auto = d.folio <= 0;
    if auto {
        d.folio = match c.almacen.consumir_siguiente_folio(&rut, tipo) {
            Ok(f) => f,
            Err(almacen::Error::SinFolios) => return Err(Error::sin_folios(&rut, tipo)),
            Err(e) => return Err(e.into()),
        };
    }
    let Some(caf_db) = c.almacen.caf_activo(&rut, tipo)? else {
        return Err(Error::folio(
            format!("No se encontró un CAF activo en la base de datos para el emisor {rut} y tipo DTE {tipo}."),
            json!({"rut_emisor": rut, "tipo_dte": tipo}),
        ));
    };
    let caf = ted::parsear_caf(&caf_db.xml)
        .map_err(|e| Error::caf(format!("No se pudo procesar el CAF: {e}")))?;
    if d.folio < caf.folio_desde || d.folio > caf.folio_hasta {
        return Err(Error::folio(
            format!(
                "El folio {} no está en el rango autorizado por el CAF activo [{}-{}].",
                d.folio, caf.folio_desde, caf.folio_hasta
            ),
            json!({"folio": d.folio, "desde": caf.folio_desde, "hasta": caf.folio_hasta}),
        ));
    }
    if !auto
        && !c
            .almacen
            .consumir_folio(&rut, tipo, d.folio)
            .unwrap_or(false)
    {
        return Err(Error::conflicto(
            format!(
                "No se pudo consumir el folio {} en la base de datos (¿ya fue usado?).",
                d.folio
            ),
            json!({"folio": d.folio}),
        ));
    }
    let p = preparar(c, d, &caf)?;
    let d = p.documento;
    let (p_doc, p_env) = if es_boleta(tipo) {
        ("BOLETA", "EnvioBOLETA")
    } else {
        ("DTE", "EnvioDTE")
    };
    let dtes = Path::new(&c.storage_base).join("dtes");
    std::fs::create_dir_all(&dtes)?;
    let _ = std::fs::create_dir_all(Path::new(&c.storage_base).join("pdfs"));
    let xml_dte = ted::latin1(&p.dte_firmado).map_err(Error::interno)?;
    let path_dte = dtes.join(format!("{p_doc}_{tipo}_{}.xml", d.folio));
    let path_env = dtes.join(format!("{p_env}_{tipo}_{}.xml", d.folio));
    std::fs::write(&path_dte, &xml_dte)?;
    std::fs::write(&path_env, &p.envio)?;
    let id = c.almacen.crear_dte(&almacen::Dte {
        tipo_dte: tipo,
        folio: d.folio,
        rut_emisor: rut,
        rut_receptor: d.receptor.rut.clone(),
        razon_social_receptor: d.receptor.razon_social.clone(),
        fecha_emision: d.fecha_emision.clone(),
        monto_neto: p.monto_neto,
        monto_exento: p.monto_exento,
        iva: p.iva,
        monto_total: p.monto_total,
        xml_firmado: p.dte_firmado.clone(),
        ambiente: c.ambiente.clone(),
    })?;
    Ok(Resultado {
        dte_id: id,
        folio: d.folio,
        tipo_dte: tipo,
        monto_total: p.monto_total,
        xml_dte_path: path_dte.to_string_lossy().into_owned(),
        pdf_path: String::new(),
        xml_envio_path: path_env.to_string_lossy().into_owned(),
        ambiente: c.ambiente.clone(),
        mensaje: format!("DTE emitido exitosamente. Folio {}.", d.folio),
        envio: p.envio,
    })
}

// ---------------------------------------------------------------- entrada JSON

fn s(v: &Value, k: &str) -> String {
    v.get(k).and_then(Value::as_str).unwrap_or("").to_string()
}
fn n(v: &Value, k: &str) -> i64 {
    match v.get(k) {
        Some(Value::Number(x)) => x
            .as_i64()
            .or_else(|| x.as_f64().map(|f| f as i64))
            .unwrap_or(0),
        _ => 0,
    }
}
fn f(v: &Value, k: &str) -> f64 {
    v.get(k).and_then(Value::as_f64).unwrap_or(0.0)
}

/// `DocumentoDesdeJSON`: parsea y valida lo mínimo (tipo, fecha, emisor con RUT, al menos un
/// ítem). La forma es la de `DTEInput` en Python.
pub fn documento_desde_json(raw: &[u8]) -> Result<Documento, String> {
    let v: Value = serde_json::from_slice(raw).map_err(|e| e.to_string())?;
    documento_desde_valor(&v)
}

pub fn documento_desde_valor(v: &Value) -> Result<Documento, String> {
    if !v.is_object() {
        return Err("el documento debe ser un objeto JSON".into());
    }
    let tipo = n(v, "tipo_dte") as i32;
    let em = v.get("emisor").cloned().unwrap_or(Value::Null);
    let rec = v.get("receptor").cloned().unwrap_or(Value::Null);
    let items = v
        .get("items")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();
    if tipo == 0 || s(v, "fecha_emision").is_empty() || s(&em, "rut").is_empty() || items.is_empty()
    {
        return Err("faltan tipo_dte, fecha_emision, emisor.rut o items".into());
    }
    if ![33, 34, 39, 41, 52, 56, 61].contains(&tipo) {
        return Err(format!(
            "tipo_dte {tipo} no soportado (33, 34, 39, 41, 52, 56, 61)"
        ));
    }
    let mut doc = Documento {
        tipo_dte: tipo,
        folio: n(v, "folio") as i32,
        fecha_emision: s(v, "fecha_emision"),
        forma_pago: 1,
        fecha_vencimiento: s(v, "fecha_vencimiento"),
        indicador_servicio: n(v, "indicador_servicio") as i32,
        ind_servicio_boleta: n(v, "ind_servicio") as i32,
        emisor: xmlgen::Emisor {
            rut: s(&em, "rut"),
            razon_social: s(&em, "razon_social"),
            giro: s(&em, "giro"),
            codigo_actividad: n(&em, "codigo_actividad"),
            direccion: s(&em, "direccion"),
            comuna: s(&em, "comuna"),
            ciudad: s(&em, "ciudad"),
            telefono: s(&em, "telefono"),
            email: s(&em, "email"),
        },
        receptor: xmlgen::Receptor {
            rut: s(&rec, "rut"),
            razon_social: s(&rec, "razon_social"),
            giro: s(&rec, "giro"),
            direccion: s(&rec, "direccion"),
            comuna: s(&rec, "comuna"),
            ciudad: s(&rec, "ciudad"),
            email: s(&rec, "email"),
        },
        ..Default::default()
    };
    if let Some(Value::Number(fp)) = v.get("forma_pago") {
        doc.forma_pago = fp.as_i64().unwrap_or(1) as i32;
    }
    for (i, it) in items.iter().enumerate() {
        let cant = match it.get("cantidad") {
            Some(Value::Number(c)) => c.as_f64().unwrap_or(1.0),
            _ => 1.0,
        };
        let nl = n(it, "numero_linea") as i32;
        doc.items.push(xmlgen::Item {
            numero_linea: if nl == 0 { i as i32 + 1 } else { nl },
            nombre: s(it, "nombre"),
            descripcion: s(it, "descripcion"),
            cantidad: cant,
            unidad_medida: s(it, "unidad_medida"),
            precio_unitario: f(it, "precio_unitario"),
            descuento_pct: f(it, "descuento_pct"),
            descuento_monto: f(it, "descuento_monto"),
            exento: it.get("exento").and_then(Value::as_bool).unwrap_or(false),
            codigo_producto: s(it, "codigo_producto"),
        });
    }
    if let Some(refs) = v.get("referencias").and_then(Value::as_array) {
        for r in refs {
            doc.referencias.push(xmlgen::Referencia {
                numero_linea: n(r, "numero_linea") as i32,
                tipo_doc_ref: n(r, "tipo_doc_ref") as i32,
                folio_ref: n(r, "folio_ref"),
                fecha_doc_ref: s(r, "fecha_doc_ref"),
                codigo_ref: n(r, "codigo_ref") as i32,
                razon_ref: s(r, "razon_ref"),
            });
        }
    }
    Ok(doc)
}

/// La respuesta de `GET /api/v1/keystore/negocios/{id}/contexto-emision` ya convertida.
pub struct ContextoEmision {
    pub rut: String,
    pub ambiente: String,
    pub fecha_resolucion: String,
    pub numero_resolucion: i64,
    pub database_path: String,
    pub storage_path: String,
    pub cert: Certificado,
}

pub fn contexto_desde_json(raw: &[u8]) -> Result<ContextoEmision, String> {
    let v: Value = serde_json::from_slice(raw).map_err(|e| e.to_string())?;
    let cert = crate::firma::cargar_pem(&s(&v, "cert_pem"), &s(&v, "key_pem"))?;
    let res = v.get("resolucion").cloned().unwrap_or(Value::Null);
    let c = ContextoEmision {
        rut: s(&v, "rut"),
        ambiente: s(&v, "ambiente"),
        fecha_resolucion: s(&res, "fecha"),
        numero_resolucion: n(&res, "numero"),
        database_path: s(&v, "database_path"),
        storage_path: s(&v, "storage_path"),
        cert,
    };
    if c.fecha_resolucion.is_empty() || c.database_path.is_empty() || c.storage_path.is_empty() {
        return Err("el contexto de emisión viene incompleto (resolución, base o storage)".into());
    }
    Ok(c)
}
