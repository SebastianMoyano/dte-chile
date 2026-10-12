//! `certificacion_sii.py` + `dry_run_certificacion.py`: los 16 casos del Set de Pruebas del SII
//! (facturas, exentas, notas de crédito y débito) generados con el mismo camino de firma que
//! la emisión (DTE standalone + sobre por string), medidos contra Python con
//! `tests/dorado/certificacion/` (certificado y CAF ficticios, hora fija). Transcripción de
//! `nucleo/certificacion` (Go).

use crate::firma::Certificado;
use crate::ted::{self, Caf};
use crate::totales;
use crate::xmlgen::{
    self, Documento, Emisor as EmisorXML, Item as ItemXML, Receptor, Referencia as ReferenciaXML,
};
use std::collections::BTreeMap;

/// Copia de `tests/dorado/certificacion/casos.json` (la única fuente es
/// `certificacion_sii.definir_casos`; el test exige que sean idénticos).
pub const CASOS_JSON: &str = include_str!("../datos/certificacion_casos.json");

#[derive(Debug, Clone, Default, serde::Deserialize)]
#[serde(default)]
pub struct Item {
    pub nombre: String,
    pub cantidad: f64,
    pub precio: f64,
    pub descuento_pct: f64,
    pub exento: bool,
    pub unidad: String,
}

#[derive(Debug, Clone, Default, serde::Deserialize)]
#[serde(default)]
pub struct Referencia {
    pub tipo_dte_ref: i32,
    pub folio_ref: i64,
    pub razon: String,
}

#[derive(Debug, Clone, Default, serde::Deserialize)]
#[serde(default)]
pub struct Caso {
    pub nombre: String,
    pub tipo_dte: i32,
    pub folio: i32,
    pub items: Vec<Item>,
    pub referencia: Option<Referencia>,
}

/// Los 16 casos del set.
pub fn casos() -> Result<Vec<Caso>, String> {
    serde_json::from_str(CASOS_JSON).map_err(|e| e.to_string())
}

pub const GIRO: &str = "Venta de alimentos";
pub const CODIGO_ACTIVIDAD: i64 = 463014;
pub const DIRECCION: &str = "Av. Providencia 1234";
pub const COMUNA: &str = "Providencia";
pub const CIUDAD: &str = "Santiago";
pub const RUT_RECEPTOR: &str = "60803000-K";
pub const RAZON_SOCIAL_RECEPTOR: &str = "SII";
pub const GIRO_RECEPTOR: &str = "Gobierno";
pub const DIRECCION_RECEPTOR: &str = "Morandé 115";
pub const COMUNA_RECEPTOR: &str = "Santiago";
pub const CIUDAD_RECEPTOR: &str = "Santiago";
/// la de certificación (Maullín)
pub const FECHA_RESOLUCION: &str = "2026-07-08";
pub const NUMERO_RESOLUCION: i64 = 0;

/// Lo configurable del script (--rut, --razon-social, --email).
#[derive(Debug, Clone, Default)]
pub struct Emisor {
    pub rut: String,
    pub razon_social: String,
    pub email: String,
}

/// `codigo_ref_desde_razon`: 1 anula, 2 corrige texto, 3 corrige montos.
pub fn codigo_ref(razon: &str) -> i32 {
    let r = razon.to_uppercase();
    if r.contains("ANULA") {
        1
    } else if r.contains("CORRIGE GIRO")
        || r.contains("CORRIGE TEXTO")
        || r.contains("MODIFICA GIRO")
    {
        2
    } else {
        3
    }
}

/// `_xml_escape` del script: & < > " ' (más que el del generador).
fn escapar_script(s: &str) -> String {
    s.replace('&', "&amp;")
        .replace('<', "&lt;")
        .replace('>', "&gt;")
        .replace('"', "&quot;")
        .replace('\'', "&apos;")
}

/// Arma el `Documento` del caso como `generar_dte` (ítem de relleno en las notas sin ítems,
/// referencia con su CodRef, contado).
pub fn documento(c: &Caso, e: &Emisor, fecha: &str) -> Documento {
    let mut d = Documento {
        tipo_dte: c.tipo_dte,
        folio: c.folio,
        fecha_emision: fecha.to_string(),
        forma_pago: 1,
        emisor: EmisorXML {
            rut: e.rut.clone(),
            razon_social: e.razon_social.clone(),
            giro: GIRO.into(),
            codigo_actividad: CODIGO_ACTIVIDAD,
            direccion: DIRECCION.into(),
            comuna: COMUNA.into(),
            ciudad: CIUDAD.into(),
            email: e.email.clone(),
            ..Default::default()
        },
        receptor: Receptor {
            rut: RUT_RECEPTOR.into(),
            razon_social: RAZON_SOCIAL_RECEPTOR.into(),
            giro: GIRO_RECEPTOR.into(),
            direccion: DIRECCION_RECEPTOR.into(),
            comuna: COMUNA_RECEPTOR.into(),
            ciudad: CIUDAD_RECEPTOR.into(),
            ..Default::default()
        },
        ..Default::default()
    };
    for (i, it) in c.items.iter().enumerate() {
        d.items.push(ItemXML {
            numero_linea: i as i32 + 1,
            nombre: it.nombre.clone(),
            cantidad: it.cantidad,
            precio_unitario: it.precio,
            unidad_medida: it.unidad.clone(),
            descuento_pct: it.descuento_pct,
            exento: it.exento,
            ..Default::default()
        });
    }
    if d.items.is_empty() {
        // Nota de corrección de texto / anulación sin monto: una línea con la razón, cantidad 1,
        // monto 0 (el generador omite PrcItem=0). XSD-válido.
        let mut razon = c
            .referencia
            .as_ref()
            .map(|r| r.razon.clone())
            .filter(|r| !r.is_empty())
            .unwrap_or_else(|| "REFERENCIA".into());
        if razon.chars().count() > 80 {
            razon = razon.chars().take(80).collect();
        }
        d.items.push(ItemXML {
            numero_linea: 1,
            nombre: razon,
            cantidad: 1.0,
            precio_unitario: 0.0,
            ..Default::default()
        });
    }
    if let Some(r) = &c.referencia {
        d.referencias = vec![ReferenciaXML {
            numero_linea: 1,
            tipo_doc_ref: r.tipo_dte_ref,
            folio_ref: r.folio_ref,
            fecha_doc_ref: fecha.to_string(),
            codigo_ref: codigo_ref(&r.razon),
            razon_ref: r.razon.clone(),
        }];
    }
    d
}

/// `generar_dte`: TED (el primer ítem escapado ANTES de recortar, como el script), DTE firmado
/// standalone y sobre EnvioDTE por string. Devuelve `(sobre ISO-8859-1, DTE firmado)`.
pub fn generar(
    c: &Caso,
    e: &Emisor,
    caf: &Caf,
    cert: &Certificado,
    fecha: &str,
    marca: &str,
) -> Result<(Vec<u8>, String), String> {
    let mut d = documento(c, e, fecha);
    let its: Vec<totales::Item> = d
        .items
        .iter()
        .map(|it| totales::Item {
            cantidad: it.cantidad,
            precio_unitario: it.precio_unitario,
            descuento_pct: it.descuento_pct,
            descuento_monto: it.descuento_monto,
            exento: it.exento,
        })
        .collect();
    let tot = totales::calcular(&its, c.tipo_dte);
    let primer = match d.items[0].nombre.as_str() {
        "" => "Sin Items".to_string(),
        s => s.to_string(),
    };
    d.marca = marca.to_string();
    d.ted = ted::generar(
        caf,
        &ted::Datos {
            folio: c.folio,
            rut_emisor: e.rut.clone(),
            rut_receptor: RUT_RECEPTOR.into(),
            tipo_dte: c.tipo_dte,
            fecha_emision: fecha.to_string(),
            monto_total: tot.monto_total,
            razon_social_receptor: RAZON_SOCIAL_RECEPTOR.into(),
            primer_item: escapar_script(&primer),
            primer_item_literal: true,
            marca: marca.to_string(),
        },
    )
    .map_err(|err| format!("{}: TED: {err}", c.nombre))?;
    let arbol = xmlgen::generar_dte(&d);
    let firmado = cert
        .firmar_dte(
            &arbol.string(),
            &arbol.hijos[0].string(),
            c.tipo_dte,
            c.folio,
        )
        .map_err(|err| format!("{}: firma: {err}", c.nombre))?;
    let rut_envia = cert.rut_emisor()?;
    let mut sub = BTreeMap::new();
    sub.insert(c.tipo_dte, 1);
    let envio = cert
        .sobre(
            std::slice::from_ref(&firmado),
            &sub,
            &e.rut,
            &rut_envia,
            FECHA_RESOLUCION,
            NUMERO_RESOLUCION,
            "EnvioDTE",
            marca,
        )
        .map_err(|err| format!("{}: sobre: {err}", c.nombre))?;
    Ok((envio, firmado))
}

/// El nombre de archivo del dry run: `<caso>_T<tipo>_F<folio>.xml`
pub fn nombre_archivo(c: &Caso) -> String {
    format!("{}_T{}_F{}", c.nombre, c.tipo_dte, c.folio)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn raiz() -> String {
        format!("{}/..", env!("CARGO_MANIFEST_DIR"))
    }

    /// casos.json embebido == tests/dorado/certificacion/casos.json (la fuente).
    #[test]
    fn casos_iguales() {
        let Ok(fuente) =
            std::fs::read_to_string(format!("{}/tests/dorado/certificacion/casos.json", raiz()))
        else {
            return;
        };
        assert_eq!(
            fuente, CASOS_JSON,
            "casos.json difiere de tests/dorado/certificacion/casos.json: copiarlo de nuevo"
        );
    }

    /// Los 16 sobres del set, byte a byte como certificacion_sii.generar_dte con el certificado
    /// y los CAF ficticios y hora fija. L15.
    #[test]
    fn set_igual_a_python() {
        let base = format!("{}/tests/dorado", raiz());
        let Ok(raw) = std::fs::read(format!("{base}/certificacion/parametros.json")) else {
            eprintln!("sin corpus del set");
            return;
        };
        let pm: std::collections::HashMap<String, String> = serde_json::from_slice(&raw).unwrap();
        let p12 = std::fs::read(format!("{base}/fixtures/cert_demo.p12")).unwrap();
        let cert = crate::firma::cargar_p12(&p12, "demo").unwrap();
        let mut cafs = std::collections::HashMap::new();
        for tipo in [33, 34, 56, 61] {
            let b = std::fs::read(format!("{base}/fixtures/caf_{tipo}.xml")).unwrap();
            cafs.insert(tipo, ted::parsear_caf(&ted::desde_latin1(&b)).unwrap());
        }
        let casos = casos().unwrap();
        assert_eq!(casos.len(), 16);
        let e = Emisor {
            rut: pm["rut"].clone(),
            razon_social: pm["razon_social"].clone(),
            email: pm["email"].clone(),
        };
        let mut ok = 0;
        for c in &casos {
            let (got, _) =
                generar(c, &e, &cafs[&c.tipo_dte], &cert, &pm["fecha"], &pm["marca"]).unwrap();
            let esperado = std::fs::read(format!(
                "{base}/certificacion/esperado/{}.xml",
                nombre_archivo(c)
            ))
            .unwrap_or_else(|_| panic!("{}: sin esperado", c.nombre));
            if got != esperado {
                let i = got
                    .iter()
                    .zip(&esperado)
                    .take_while(|(a, b)| a == b)
                    .count();
                let lo = i.saturating_sub(80);
                panic!(
                    "{} difiere en el byte {i}\n  esperado: …{}…\n  obtenido: …{}…",
                    c.nombre,
                    String::from_utf8_lossy(&esperado[lo..(i + 80).min(esperado.len())]),
                    String::from_utf8_lossy(&got[lo..(i + 80).min(got.len())])
                );
            }
            ok += 1;
        }
        eprintln!("casos idénticos: {ok} de {}", casos.len());
    }
}
