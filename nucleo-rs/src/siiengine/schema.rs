//! Schema del form: los 243 nombres que el JS del portal manda a mipeGenXMLFirma, EN ORDEN
//! (`core/sii_mipyme.py::SCHEMA_CAMPOS`, contrato capturado 2026-09-06). El HTML trae ~40
//! inputs; el resto lo genera el JS al enviar. Mandar menos campos da "requerimiento no bien
//! recepcionado". Se construye con los mismos bucles que Python; el test lo compara con la
//! lista literal exportada desde Python (`testdata/siiengine/schema.json`).

use std::collections::{HashMap, HashSet};
use std::sync::OnceLock;

pub const CAMPOS_ITEM: [&str; 10] = [
    "TPO_COD", "COD", "NMB", "QTY", "UNMD", "PRC", "OTRO_IMP", "PCTD", "SUBT", "DSC_ITEM",
];
pub const CAMPOS_REF: [&str; 6] = [
    "TPO_DOC_REF",
    "IND_GLOBAL",
    "FOLIO_REF",
    "FCH_REF",
    "CODIGO_REF",
    "RAZON_REF",
];

static SCHEMA: OnceLock<(Vec<String>, HashSet<String>)> = OnceLock::new();

fn construir() -> (Vec<String>, HashSet<String>) {
    let mut s: Vec<String> = [
        "INDICA_PRIMERA_EJECUCION",
        "ES_BORR",
        "EHDR_CODIGO",
        "AGENTE_RETENEDOR",
        "PTES_ESTADO",
        "TIPO_PLANTILLA",
        "MNT_TOTAL_ORI",
        "PTDC_CODIGO",
        "EFXP_FMA_PAGO",
        "EFXP_FCH_PAGO_001",
        "EFXP_FCH_PAGO_002",
        "EFXP_FCH_PAGO_003",
        "EFXP_MNT_PAGO_001",
        "EFXP_MNT_PAGO_002",
        "EFXP_MNT_PAGO_003",
        "EFXP_GLOSA_PAGOS_001",
        "EFXP_GLOSA_PAGOS_002",
        "EFXP_GLOSA_PAGOS_003",
        "EFXP_FCH_VENC",
        "EFXP_IND_VENTA",
        "EFXP_RZN_SOC",
        "EFXP_GIRO_EMIS",
        "EFXP_ACTECO",
        "EFXP_CDG_SII_SUCUR",
        "EFXP_DIR_ORIGEN",
        "EFXP_CMNA_ORIGEN",
        "EFXP_CIUDAD_ORIGEN",
        "EFXP_TIPOVENTA_SELECT",
        "EFXP_TIPOCOMPRA_SELECT",
        "EFXP_DOC_REF_RAIZ",
        "EFXP_COMUNA_ROL_ORIGEN",
        "EFXP_MAN_ROL_ORIGEN",
        "EFXP_PRED_ROL_ORIGEN",
        "EFXP_SIST_REF_GEO",
        "EFXP_LAT_ORIG_MADERA",
        "EFXP_LONG_ORIG_MADERA",
        "EFXP_COD_PLAN_CONAF",
        "UBIC_MADERA_SI_NO",
        "EFXP_EMAIL_EMISOR",
        "EFXP_FONO_EMISOR",
        "EFXP_RUT_RECEP",
        "EFXP_DV_RECEP",
        "EFXP_FCH_EMIS",
        "EFXP_RZN_SOC_RECEP",
        "EFXP_GIRO_RECEP",
        "EFXP_DIR_RECEP",
        "EFXP_CIUDAD_RECEP",
        "EFXP_CMNA_RECEP",
        "EFXP_CONTACTO",
        "EFXP_RUT_SOLICITA",
        "EFXP_DV_SOLICITA",
    ]
    .iter()
    .map(|x| x.to_string())
    .collect();
    for i in 1..=10 {
        for c in CAMPOS_ITEM {
            s.push(format!("EFXP_{c}_{i:02}"));
        }
    }
    for x in [
        "EFXP_SUBTOTAL",
        "EFXP_PCT_DESC",
        "EFXP_MNT_DESC",
        "EFXP_MNT_NETO",
        "EFXP_TASA_IVA",
        "EFXP_IVA",
        "EFXP_MNT_TOTAL",
        "EFXP_OTRO_IMP_TOTAL",
    ] {
        s.push(x.into());
    }
    for i in 1..=3 {
        for c in CAMPOS_REF {
            s.push(format!("EFXP_{c}_{i:03}"));
        }
    }
    s.push("EMP_MENOR_TAMANO".into());
    for i in 1..=10 {
        s.push(format!("EDL_PRC_EXE_{i:02}"));
    }
    for i in 1..=10 {
        s.push(format!("EDL_TPO_DOC_LIQ_{i:02}"));
    }
    for x in [
        "EDL_MNT_NET_TRAN",
        "EDL_MNT_EXE_TRAN",
        "EDL_TASA_IVA_TRAN",
        "EDL_IVA_TRAN",
        "EDL_SUBTOTAL_TRAN",
    ] {
        s.push(x.into());
    }
    for i in 1..=3 {
        for c in ["TIP_MOV", "GLOSA", "ITM_EXENTO", "VAL"] {
            s.push(format!("EDL_COM_{c}_{i:02}"));
        }
    }
    for x in [
        "EDL_MNT_NET_COM",
        "EDL_MNT_EXE_COM",
        "EDL_TASA_IVA_COM",
        "EDL_IVA_COM",
        "EDL_SUBTOTAL_COM",
        "EFXP_CRED_EC",
        "esCRED_EC",
        "esFACT_TUR",
        "EFXP_TPO_DOC_TURISTA",
        "EFXP_NUM_ID",
        "EFXP_NACIONALIDAD",
        "EDFE_PAIS_DEST",
        "EDFE_TPO_MON",
        "EDFE_PTO_EMBAR",
        "EDFE_PTO_DESEM",
        "EDFE_TOT_BOLT",
        "EDFE_MOD_VTA",
        "EDFE_TPO_EXPO",
        "EDFE_PTO_EMBAR_TXT",
        "EDFE_PTO_DESEM_TXT",
        "EDFE_TAX_ID",
        "EDFE_TPO_CAMBIO",
        "EFXP_RUT_TRANSPORTE",
        "EFXP_DV_TRANSPORTE",
        "EFXP_PATENTE",
        "EFXP_RUT_CHOFER",
        "EFXP_DV_CHOFER",
        "EFXP_NOMBRE_CHOFER",
    ] {
        s.push(x.into());
    }
    let set = s.iter().cloned().collect();
    (s, set)
}

/// Los 243 nombres, en orden.
pub fn schema_campos() -> &'static [String] {
    &SCHEMA.get_or_init(construir).0
}

pub fn en_schema(nombre: &str) -> bool {
    SCHEMA.get_or_init(construir).1.contains(nombre)
}

/// Los 54 campos (en su orden) que el navegador manda a mipeDisplayPreView ("Validar y
/// visualizar") en una factura (captura 2026-10-04). Paso OBLIGATORIO antes de GenXMLFirma:
/// sin él, "No se pudo generar XML para firmar".
pub const CAMPOS_VALIDAR_FACTURA: [&str; 54] = [
    "CANT_DET",
    "DESCRIP_01",
    "EFXP_ACTECO",
    "EFXP_ACTECO_SELECT",
    "EFXP_CDG_SII_SUCUR",
    "EFXP_CIUDAD_ORIGEN",
    "EFXP_CIUDAD_RECEP",
    "EFXP_CMNA_ORIGEN",
    "EFXP_CMNA_RECEP",
    "EFXP_CONTACTO",
    "EFXP_DIR_ORIGEN",
    "EFXP_DIR_ORIGEN_DEFUALT",
    "EFXP_DIR_RECEP",
    "EFXP_DIR_RECEP_DEFUALT",
    "EFXP_DSC_ITEM_01",
    "EFXP_DV_CHOFER",
    "EFXP_DV_RECEP",
    "EFXP_DV_SOLICITA",
    "EFXP_DV_TRANSPORTE",
    "EFXP_EMAIL_EMISOR",
    "EFXP_FCH_EMIS",
    "EFXP_FMA_PAGO",
    "EFXP_FONO_EMISOR",
    "EFXP_GIRO_EMIS",
    "EFXP_GIRO_RECEP",
    "EFXP_GIRO_RECEP_DEFUALT",
    "EFXP_MNT_DESC",
    "EFXP_MNT_NETO",
    "EFXP_MNT_TOTAL",
    "EFXP_NMB_01",
    "EFXP_NOMBRE_CHOFER",
    "EFXP_PATENTE",
    "EFXP_PCTD_01",
    "EFXP_PCT_DESC",
    "EFXP_PRC_01",
    "EFXP_QTY_01",
    "EFXP_RUT_CHOFER",
    "EFXP_RUT_RECEP",
    "EFXP_RUT_SOLICITA",
    "EFXP_RUT_TRANSPORTE",
    "EFXP_RZN_SOC",
    "EFXP_RZN_SOC_RECEP",
    "EFXP_SUBTOTAL",
    "EFXP_SUBT_01",
    "EFXP_TIPOCOMPRA_SELECT",
    "EFXP_TIPOVENTA_SELECT",
    "EFXP_UNMD_01",
    "EHDR_CODIGO",
    "ES_BORR",
    "IVA_TEMP",
    "MNT_NETO_TEMP",
    "PTDC_CODIGO",
    "esCRED_EC",
    "esFACT_TUR",
];

/// Los 60 campos del "Validar y visualizar" de la NC de corrección de montos (form
/// IGUAL=CORR_MNT; captura 2026-10-04, NC 59 emitida con éxito).
pub const CAMPOS_VALIDAR_CORR_MNT: [&str; 60] = [
    "CANT_DET",
    "DESCRIP_01",
    "EFXP_ACTECO",
    "EFXP_CDG_SII_SUCUR",
    "EFXP_CIUDAD_ORIGEN",
    "EFXP_CIUDAD_RECEP",
    "EFXP_CMNA_ORIGEN",
    "EFXP_CMNA_RECEP",
    "EFXP_CODIGO_REF_001",
    "EFXP_CONTACTO",
    "EFXP_DIR_ORIGEN",
    "EFXP_DIR_RECEP",
    "EFXP_DSC_ITEM_01",
    "EFXP_DV_RECEP",
    "EFXP_DV_SOLICITA",
    "EFXP_EMAIL_EMISOR",
    "EFXP_FCH_EMIS",
    "EFXP_FCH_REF_001",
    "EFXP_FOLIO_REF_001",
    "EFXP_FONO_EMISOR",
    "EFXP_GIRO_EMIS",
    "EFXP_GIRO_RECEP",
    "EFXP_IND_GLOBAL_001",
    "EFXP_MNT_DESC",
    "EFXP_MNT_NETO",
    "EFXP_MNT_TOTAL",
    "EFXP_NMB_01",
    "EFXP_NMB_02",
    "EFXP_NMB_03",
    "EFXP_PCTD_01",
    "EFXP_PCTD_02",
    "EFXP_PCTD_03",
    "EFXP_PCT_DESC",
    "EFXP_PRC_01",
    "EFXP_PRC_02",
    "EFXP_PRC_03",
    "EFXP_QTY_01",
    "EFXP_QTY_02",
    "EFXP_QTY_03",
    "EFXP_RAZON_REF_001",
    "EFXP_RUT_RECEP",
    "EFXP_RUT_SOLICITA",
    "EFXP_RZN_SOC",
    "EFXP_RZN_SOC_RECEP",
    "EFXP_SUBTOTAL",
    "EFXP_SUBT_01",
    "EFXP_SUBT_02",
    "EFXP_SUBT_03",
    "EFXP_TPO_DOC_REF_001",
    "EFXP_UNMD_01",
    "EFXP_UNMD_02",
    "EFXP_UNMD_03",
    "EHDR_CODIGO",
    "IVA_TEMP",
    "MNT_NETO_TEMP",
    "MNT_TOTAL_ORI",
    "PTDC_CODIGO",
    "REF_SI_NO",
    "TIPO_PLANTILLA",
    "esCRED_EC",
];

/// Inputs "helper" que el HTML trae pero el JS del SII NO manda. No son drift.
const CAMPOS_HELPER: [&str; 9] = [
    "CANT_DET",
    "COD_SI_NO",
    "REF_SI_NO",
    "PAGO_SI_NO",
    "IVA_TEMP",
    "MNT_NETO_TEMP",
    "btnSign",
    "btnVolver",
    "btnCorregir",
];

/// `es_campo_helper` (los `*_DEFUALT`, sic, son del SII).
pub fn es_campo_helper(nombre: &str) -> bool {
    CAMPOS_HELPER.contains(&nombre) || nombre.ends_with("_DEFUALT")
}

/// Los 5 montos que deben coincidir SIEMPRE (con 1 ítem): PRC/SUBT por ítem + estos 3
/// totales. Sustituir solo 2 de ellos dio el reparo HED-2-220.
pub const CAMPOS_MONTO_TOTAL: [&str; 3] = ["EFXP_SUBTOTAL", "EFXP_MNT_NETO", "EFXP_MNT_TOTAL"];

pub const CODIGO_REF_ANULA: &str = "1";
pub const RAZON_REF_ANULA: &str = "ANULA DOCUMENTO DE LA REFERENCIA";
pub const CODIGO_REF_CORRIGE_MONTO: &str = "3";
pub const RAZON_REF_CORRIGE_MONTO: &str = "CORRIGE MONTO";

/// Tipos cuya cadena de emisión está verificada de punta a punta contra el SII DESDE ESTE
/// MOTOR, con evidencia. Python ya tiene 34 y 61 (factura 63 y NC 60, 2026-10-08); el port se
/// da por verificado cuando reproduce esos cuerpos byte a byte Y una corrida real pasa. Hasta
/// entonces, `emitir` exige `aceptar_riesgo_folio`.
pub fn cadenas_verificadas() -> HashMap<i32, &'static str> {
    HashMap::new()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn schema_igual_a_python() {
        let b = std::fs::read(format!(
            "{}/testdata/siiengine/schema.json",
            env!("CARGO_MANIFEST_DIR")
        ))
        .unwrap();
        let py: Vec<String> = serde_json::from_slice(&b).unwrap();
        assert_eq!(
            schema_campos(),
            py.as_slice(),
            "schema distinto: rust {}, python {}",
            schema_campos().len(),
            py.len()
        );
        assert_eq!(schema_campos().len(), 243);
        assert!(en_schema("EFXP_NMB_01") && !en_schema("CAMPO_RARO"));
        assert!(
            es_campo_helper("CANT_DET")
                && es_campo_helper("EFXP_DIR_ORIGEN_DEFUALT")
                && !es_campo_helper("EFXP_NMB_01")
        );
    }
}
