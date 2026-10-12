//! nucleo-dorado: el port en Rust frente al corpus dorado.
//!
//!     nucleo-dorado <entrada.json> <fixtures/> <salida/>
//!
//! Lee el caso, los fixtures y el entorno (RELOJ_FIJO, DORADO_RESOLUCION_*), y escribe en
//! <salida/> ted.xml, dte.xml, totales.json por documento y envio.xml.
//! `test_dorado.py --port nucleo-rs/target/release/nucleo-dorado` lo compara byte a byte.
//! Mismo contrato que `nucleo/cmd/nucleo-dorado` (Go).

use dtechile::{firma, ted, totales, xmlgen};
use serde::Deserialize;
use std::collections::BTreeMap;
use std::path::Path;

#[derive(Deserialize, Default, Clone)]
#[serde(default)]
struct ItemIn {
    numero_linea: i32,
    nombre: String,
    descripcion: String,
    cantidad: Option<f64>,
    unidad_medida: String,
    precio_unitario: f64,
    descuento_pct: f64,
    descuento_monto: f64,
    exento: bool,
    codigo_producto: String,
}

#[derive(Deserialize, Default, Clone)]
#[serde(default)]
struct ReceptorIn {
    rut: String,
    razon_social: String,
    giro: String,
    direccion: String,
    comuna: String,
    ciudad: String,
    email: String,
}

#[derive(Deserialize, Default, Clone)]
#[serde(default)]
struct RefIn {
    numero_linea: i32,
    tipo_doc_ref: i32,
    folio_ref: i64,
    fecha_doc_ref: String,
    codigo_ref: i32,
    razon_ref: String,
}

#[derive(Deserialize, Default, Clone)]
#[serde(default)]
struct EmisorIn {
    rut: String,
    razon_social: String,
    giro: String,
    codigo_actividad: i64,
    direccion: String,
    comuna: String,
    ciudad: String,
    telefono: String,
    email: String,
}

#[derive(Deserialize, Default, Clone)]
#[serde(default)]
struct DocIn {
    tipo_dte: i32,
    folio: i32,
    fecha_emision: String,
    receptor: ReceptorIn,
    items: Vec<ItemIn>,
    referencias: Vec<RefIn>,
    forma_pago: Option<i32>,
    fecha_vencimiento: String,
    indicador_servicio: i32,
    ind_servicio: i32,
    emisor: Option<EmisorIn>,
}

#[derive(Deserialize, Default)]
#[serde(default)]
struct CasoIn {
    #[serde(flatten)]
    doc: DocIn,
    documentos: Vec<DocIn>,
}

/// EMISOR_DEMO de core/simulacion.py.
fn emisor_demo() -> xmlgen::Emisor {
    xmlgen::Emisor {
        rut: "77777777-7".into(),
        razon_social: "EMPRESA DEMO SPA".into(),
        giro: "Cafetería".into(),
        codigo_actividad: 561000,
        direccion: "Calle Ficticia 123".into(),
        comuna: "Santiago".into(),
        ciudad: "Santiago".into(),
        email: "hola@empresademo.cl".into(),
        ..Default::default()
    }
}

fn fatal<T>(e: impl std::fmt::Display) -> T {
    eprintln!("nucleo-dorado: {e}");
    std::process::exit(1)
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    if args.len() != 4 {
        eprintln!("uso: nucleo-dorado <entrada.json> <fixtures/> <salida/>");
        std::process::exit(2);
    }
    let (entrada, fixtures, salida) = (
        Path::new(&args[1]),
        Path::new(&args[2]),
        Path::new(&args[3]),
    );
    let marca = std::env::var("RELOJ_FIJO").unwrap_or_default();
    let fecha_resol = std::env::var("DORADO_RESOLUCION_FECHA").unwrap_or_default();
    let nro_resol: i64 = std::env::var("DORADO_RESOLUCION_NUMERO")
        .ok()
        .and_then(|s| s.parse().ok())
        .unwrap_or(0);

    let raw = std::fs::read(entrada).unwrap_or_else(fatal);
    let caso: CasoIn = serde_json::from_slice(&raw).unwrap_or_else(fatal);
    let docs = if caso.documentos.is_empty() {
        vec![caso.doc.clone()]
    } else {
        caso.documentos.clone()
    };
    std::fs::create_dir_all(salida).unwrap_or_else(fatal);
    let p12 = std::fs::read(fixtures.join("cert_demo.p12")).unwrap_or_else(fatal);
    let clave = std::env::var("DORADO_CERT_CLAVE")
        .ok()
        .filter(|s| !s.is_empty())
        .unwrap_or_else(|| "demo".into());
    let cert = firma::cargar_p12(&p12, &clave).unwrap_or_else(fatal);
    let rut_envia = cert.rut_emisor().unwrap_or_else(fatal);

    let es_boleta = docs.iter().all(|d| d.tipo_dte == 39 || d.tipo_dte == 41);
    let mut firmados: Vec<String> = Vec::new();
    let mut subtotales: BTreeMap<i32, i32> = BTreeMap::new();
    for (i, d) in docs.iter().enumerate() {
        let suf = if docs.len() > 1 {
            format!("_{}", i + 1)
        } else {
            String::new()
        };
        let emisor = match &d.emisor {
            Some(e) => xmlgen::Emisor {
                rut: e.rut.clone(),
                razon_social: e.razon_social.clone(),
                giro: e.giro.clone(),
                codigo_actividad: e.codigo_actividad,
                direccion: e.direccion.clone(),
                comuna: e.comuna.clone(),
                ciudad: e.ciudad.clone(),
                telefono: e.telefono.clone(),
                email: e.email.clone(),
            },
            None => emisor_demo(),
        };
        let caf_bytes =
            std::fs::read(fixtures.join(format!("caf_{}.xml", d.tipo_dte))).unwrap_or_else(fatal);
        let caf = ted::parsear_caf(&ted::desde_latin1(&caf_bytes)).unwrap_or_else(fatal);
        let mut items = Vec::with_capacity(d.items.len());
        let mut t_items = Vec::with_capacity(d.items.len());
        for it in &d.items {
            let c = it.cantidad.unwrap_or(1.0);
            items.push(xmlgen::Item {
                numero_linea: it.numero_linea,
                nombre: it.nombre.clone(),
                descripcion: it.descripcion.clone(),
                cantidad: c,
                unidad_medida: it.unidad_medida.clone(),
                precio_unitario: it.precio_unitario,
                descuento_pct: it.descuento_pct,
                descuento_monto: it.descuento_monto,
                exento: it.exento,
                codigo_producto: it.codigo_producto.clone(),
            });
            t_items.push(totales::Item {
                cantidad: c,
                precio_unitario: it.precio_unitario,
                descuento_pct: it.descuento_pct,
                descuento_monto: it.descuento_monto,
                exento: it.exento,
            });
        }
        let tot = totales::calcular(&t_items, d.tipo_dte);
        std::fs::write(salida.join(format!("totales{suf}.json")), tot.json()).unwrap_or_else(fatal);

        let primer = d
            .items
            .first()
            .map(|i| i.nombre.clone())
            .unwrap_or_else(|| "Sin Items".into());
        let t = ted::generar(
            &caf,
            &ted::Datos {
                folio: d.folio,
                rut_emisor: emisor.rut.clone(),
                rut_receptor: d.receptor.rut.clone(),
                tipo_dte: d.tipo_dte,
                fecha_emision: d.fecha_emision.clone(),
                monto_total: tot.monto_total,
                razon_social_receptor: d.receptor.razon_social.clone(),
                primer_item: primer,
                marca: marca.clone(),
                primer_item_literal: false,
            },
        )
        .unwrap_or_else(fatal);
        std::fs::write(
            salida.join(format!("ted{suf}.xml")),
            ted::latin1(&t).unwrap_or_else(fatal),
        )
        .unwrap_or_else(fatal);

        let refs = d
            .referencias
            .iter()
            .map(|r| xmlgen::Referencia {
                numero_linea: r.numero_linea,
                tipo_doc_ref: r.tipo_doc_ref,
                folio_ref: r.folio_ref,
                fecha_doc_ref: r.fecha_doc_ref.clone(),
                codigo_ref: r.codigo_ref,
                razon_ref: r.razon_ref.clone(),
            })
            .collect();
        let doc = xmlgen::Documento {
            tipo_dte: d.tipo_dte,
            folio: d.folio,
            fecha_emision: d.fecha_emision.clone(),
            emisor: emisor.clone(),
            receptor: xmlgen::Receptor {
                rut: d.receptor.rut.clone(),
                razon_social: d.receptor.razon_social.clone(),
                giro: d.receptor.giro.clone(),
                direccion: d.receptor.direccion.clone(),
                comuna: d.receptor.comuna.clone(),
                ciudad: d.receptor.ciudad.clone(),
                email: d.receptor.email.clone(),
            },
            items,
            referencias: refs,
            forma_pago: d.forma_pago.unwrap_or(1),
            fecha_vencimiento: d.fecha_vencimiento.clone(),
            indicador_servicio: d.indicador_servicio,
            ind_servicio_boleta: d.ind_servicio,
            ted: t,
            marca: marca.clone(),
        };
        let arbol = if es_boleta {
            xmlgen::generar_boleta(&doc)
        } else {
            xmlgen::generar_dte(&doc)
        };
        let documento = arbol.hijos[0].string(); // <Documento …> sin el xmlns (lo aporta el ápice en C14N)
        let firmado = cert
            .firmar_dte(&arbol.string(), &documento, d.tipo_dte, d.folio)
            .unwrap_or_else(fatal);
        std::fs::write(
            salida.join(format!("dte{suf}.xml")),
            ted::latin1(&firmado).unwrap_or_else(fatal),
        )
        .unwrap_or_else(fatal);
        firmados.push(firmado);
        *subtotales.entry(d.tipo_dte).or_insert(0) += 1;
    }
    let raiz = if es_boleta { "EnvioBOLETA" } else { "EnvioDTE" };
    let rut_emisor = docs[0]
        .emisor
        .as_ref()
        .map(|e| e.rut.clone())
        .unwrap_or_else(|| emisor_demo().rut);
    let envio = cert
        .sobre(
            &firmados,
            &subtotales,
            &rut_emisor,
            &rut_envia,
            &fecha_resol,
            nro_resol,
            raiz,
            &marca,
        )
        .unwrap_or_else(fatal);
    std::fs::write(salida.join("envio.xml"), envio).unwrap_or_else(fatal);
}
