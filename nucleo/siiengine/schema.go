package siiengine

import (
	"fmt"
	"strings"
)

// Schema del form: los 243 nombres que el JS del portal manda a mipeGenXMLFirma, EN ORDEN
// (core/sii_mipyme.py::SCHEMA_CAMPOS, contrato capturado 2026-09-06). El HTML trae ~40
// inputs; el resto lo genera el JS al enviar. Mandar menos campos da "requerimiento no bien
// recepcionado". Se construye con los mismos bucles que Python; el test lo compara con la
// lista literal exportada desde Python (testdata/schema.json).
var SchemaCampos []string

var camposItem = []string{"TPO_COD", "COD", "NMB", "QTY", "UNMD", "PRC", "OTRO_IMP", "PCTD", "SUBT", "DSC_ITEM"}
var camposRef = []string{"TPO_DOC_REF", "IND_GLOBAL", "FOLIO_REF", "FCH_REF", "CODIGO_REF", "RAZON_REF"}

func init() {
	s := []string{
		"INDICA_PRIMERA_EJECUCION", "ES_BORR", "EHDR_CODIGO", "AGENTE_RETENEDOR", "PTES_ESTADO",
		"TIPO_PLANTILLA", "MNT_TOTAL_ORI", "PTDC_CODIGO", "EFXP_FMA_PAGO", "EFXP_FCH_PAGO_001",
		"EFXP_FCH_PAGO_002", "EFXP_FCH_PAGO_003", "EFXP_MNT_PAGO_001", "EFXP_MNT_PAGO_002",
		"EFXP_MNT_PAGO_003", "EFXP_GLOSA_PAGOS_001", "EFXP_GLOSA_PAGOS_002",
		"EFXP_GLOSA_PAGOS_003", "EFXP_FCH_VENC", "EFXP_IND_VENTA", "EFXP_RZN_SOC",
		"EFXP_GIRO_EMIS", "EFXP_ACTECO", "EFXP_CDG_SII_SUCUR", "EFXP_DIR_ORIGEN",
		"EFXP_CMNA_ORIGEN", "EFXP_CIUDAD_ORIGEN", "EFXP_TIPOVENTA_SELECT",
		"EFXP_TIPOCOMPRA_SELECT", "EFXP_DOC_REF_RAIZ", "EFXP_COMUNA_ROL_ORIGEN",
		"EFXP_MAN_ROL_ORIGEN", "EFXP_PRED_ROL_ORIGEN", "EFXP_SIST_REF_GEO",
		"EFXP_LAT_ORIG_MADERA", "EFXP_LONG_ORIG_MADERA", "EFXP_COD_PLAN_CONAF",
		"UBIC_MADERA_SI_NO", "EFXP_EMAIL_EMISOR", "EFXP_FONO_EMISOR", "EFXP_RUT_RECEP",
		"EFXP_DV_RECEP", "EFXP_FCH_EMIS", "EFXP_RZN_SOC_RECEP", "EFXP_GIRO_RECEP",
		"EFXP_DIR_RECEP", "EFXP_CIUDAD_RECEP", "EFXP_CMNA_RECEP", "EFXP_CONTACTO",
		"EFXP_RUT_SOLICITA", "EFXP_DV_SOLICITA",
	}
	for i := 1; i <= 10; i++ { // 10 ítems × 10 campos
		for _, c := range camposItem {
			s = append(s, fmt.Sprintf("EFXP_%s_%02d", c, i))
		}
	}
	s = append(s, "EFXP_SUBTOTAL", "EFXP_PCT_DESC", "EFXP_MNT_DESC",
		"EFXP_MNT_NETO", "EFXP_TASA_IVA", "EFXP_IVA", "EFXP_MNT_TOTAL", "EFXP_OTRO_IMP_TOTAL")
	for i := 1; i <= 3; i++ { // 3 referencias × 6 campos
		for _, c := range camposRef {
			s = append(s, fmt.Sprintf("EFXP_%s_%03d", c, i))
		}
	}
	s = append(s, "EMP_MENOR_TAMANO")
	for i := 1; i <= 10; i++ {
		s = append(s, fmt.Sprintf("EDL_PRC_EXE_%02d", i))
	}
	for i := 1; i <= 10; i++ {
		s = append(s, fmt.Sprintf("EDL_TPO_DOC_LIQ_%02d", i))
	}
	s = append(s, "EDL_MNT_NET_TRAN", "EDL_MNT_EXE_TRAN", "EDL_TASA_IVA_TRAN", "EDL_IVA_TRAN", "EDL_SUBTOTAL_TRAN")
	for i := 1; i <= 3; i++ {
		for _, c := range []string{"TIP_MOV", "GLOSA", "ITM_EXENTO", "VAL"} {
			s = append(s, fmt.Sprintf("EDL_COM_%s_%02d", c, i))
		}
	}
	s = append(s, "EDL_MNT_NET_COM", "EDL_MNT_EXE_COM", "EDL_TASA_IVA_COM", "EDL_IVA_COM", "EDL_SUBTOTAL_COM",
		"EFXP_CRED_EC", "esCRED_EC", "esFACT_TUR", "EFXP_TPO_DOC_TURISTA", "EFXP_NUM_ID",
		"EFXP_NACIONALIDAD", "EDFE_PAIS_DEST", "EDFE_TPO_MON", "EDFE_PTO_EMBAR", "EDFE_PTO_DESEM",
		"EDFE_TOT_BOLT", "EDFE_MOD_VTA", "EDFE_TPO_EXPO", "EDFE_PTO_EMBAR_TXT", "EDFE_PTO_DESEM_TXT",
		"EDFE_TAX_ID", "EDFE_TPO_CAMBIO", "EFXP_RUT_TRANSPORTE", "EFXP_DV_TRANSPORTE",
		"EFXP_PATENTE", "EFXP_RUT_CHOFER", "EFXP_DV_CHOFER", "EFXP_NOMBRE_CHOFER")
	SchemaCampos = s
	for _, n := range s {
		enSchema[n] = true
	}
}

var enSchema = map[string]bool{}

// CamposValidarFactura: los 54 campos (en su orden) que el navegador manda a
// mipeDisplayPreView ("Validar y visualizar") en una factura (captura 2026-10-04). Paso
// OBLIGATORIO antes de GenXMLFirma: sin él, "No se pudo generar XML para firmar".
var CamposValidarFactura = []string{
	"CANT_DET", "DESCRIP_01", "EFXP_ACTECO", "EFXP_ACTECO_SELECT", "EFXP_CDG_SII_SUCUR",
	"EFXP_CIUDAD_ORIGEN", "EFXP_CIUDAD_RECEP", "EFXP_CMNA_ORIGEN", "EFXP_CMNA_RECEP", "EFXP_CONTACTO",
	"EFXP_DIR_ORIGEN", "EFXP_DIR_ORIGEN_DEFUALT", "EFXP_DIR_RECEP", "EFXP_DIR_RECEP_DEFUALT",
	"EFXP_DSC_ITEM_01", "EFXP_DV_CHOFER", "EFXP_DV_RECEP", "EFXP_DV_SOLICITA", "EFXP_DV_TRANSPORTE",
	"EFXP_EMAIL_EMISOR", "EFXP_FCH_EMIS", "EFXP_FMA_PAGO", "EFXP_FONO_EMISOR", "EFXP_GIRO_EMIS",
	"EFXP_GIRO_RECEP", "EFXP_GIRO_RECEP_DEFUALT", "EFXP_MNT_DESC", "EFXP_MNT_NETO", "EFXP_MNT_TOTAL",
	"EFXP_NMB_01", "EFXP_NOMBRE_CHOFER", "EFXP_PATENTE", "EFXP_PCTD_01", "EFXP_PCT_DESC", "EFXP_PRC_01",
	"EFXP_QTY_01", "EFXP_RUT_CHOFER", "EFXP_RUT_RECEP", "EFXP_RUT_SOLICITA", "EFXP_RUT_TRANSPORTE",
	"EFXP_RZN_SOC", "EFXP_RZN_SOC_RECEP", "EFXP_SUBTOTAL", "EFXP_SUBT_01", "EFXP_TIPOCOMPRA_SELECT",
	"EFXP_TIPOVENTA_SELECT", "EFXP_UNMD_01", "EHDR_CODIGO", "ES_BORR", "IVA_TEMP", "MNT_NETO_TEMP",
	"PTDC_CODIGO", "esCRED_EC", "esFACT_TUR",
}

// CamposValidarCorrMnt: los 60 campos del "Validar y visualizar" de la NC de corrección de
// montos (form IGUAL=CORR_MNT; captura 2026-10-04, NC 59 emitida con éxito).
var CamposValidarCorrMnt = []string{
	"CANT_DET", "DESCRIP_01", "EFXP_ACTECO", "EFXP_CDG_SII_SUCUR", "EFXP_CIUDAD_ORIGEN", "EFXP_CIUDAD_RECEP",
	"EFXP_CMNA_ORIGEN", "EFXP_CMNA_RECEP", "EFXP_CODIGO_REF_001", "EFXP_CONTACTO", "EFXP_DIR_ORIGEN", "EFXP_DIR_RECEP",
	"EFXP_DSC_ITEM_01", "EFXP_DV_RECEP", "EFXP_DV_SOLICITA", "EFXP_EMAIL_EMISOR", "EFXP_FCH_EMIS", "EFXP_FCH_REF_001",
	"EFXP_FOLIO_REF_001", "EFXP_FONO_EMISOR", "EFXP_GIRO_EMIS", "EFXP_GIRO_RECEP", "EFXP_IND_GLOBAL_001", "EFXP_MNT_DESC",
	"EFXP_MNT_NETO", "EFXP_MNT_TOTAL", "EFXP_NMB_01", "EFXP_NMB_02", "EFXP_NMB_03", "EFXP_PCTD_01", "EFXP_PCTD_02",
	"EFXP_PCTD_03", "EFXP_PCT_DESC", "EFXP_PRC_01", "EFXP_PRC_02", "EFXP_PRC_03", "EFXP_QTY_01", "EFXP_QTY_02", "EFXP_QTY_03",
	"EFXP_RAZON_REF_001", "EFXP_RUT_RECEP", "EFXP_RUT_SOLICITA", "EFXP_RZN_SOC", "EFXP_RZN_SOC_RECEP", "EFXP_SUBTOTAL",
	"EFXP_SUBT_01", "EFXP_SUBT_02", "EFXP_SUBT_03", "EFXP_TPO_DOC_REF_001", "EFXP_UNMD_01", "EFXP_UNMD_02", "EFXP_UNMD_03",
	"EHDR_CODIGO", "IVA_TEMP", "MNT_NETO_TEMP", "MNT_TOTAL_ORI", "PTDC_CODIGO", "REF_SI_NO", "TIPO_PLANTILLA", "esCRED_EC",
}

// Inputs "helper" que el HTML trae pero el JS del SII NO manda. No son drift.
var camposHelper = map[string]bool{
	"CANT_DET": true, "COD_SI_NO": true, "REF_SI_NO": true, "PAGO_SI_NO": true, "IVA_TEMP": true, "MNT_NETO_TEMP": true,
	"btnSign": true, "btnVolver": true, // botones de la página de revisión de notas (2026-10-02)
	"btnCorregir": true, // botón del form de factura, apareció el 2026-10-08 (factura 63)
}

// EsCampoHelper es es_campo_helper (los `*_DEFUALT`, sic, son del SII).
func EsCampoHelper(nombre string) bool {
	return camposHelper[nombre] || strings.HasSuffix(nombre, "_DEFUALT")
}

// Los 5 montos que deben coincidir SIEMPRE (con 1 ítem): PRC/SUBT por ítem + estos 3 totales.
// Sustituir solo 2 de ellos dio el reparo HED-2-220.
var camposMontoTotal = []string{"EFXP_SUBTOTAL", "EFXP_MNT_NETO", "EFXP_MNT_TOTAL"}

const (
	CodigoRefAnula        = "1"
	RazonRefAnula         = "ANULA DOCUMENTO DE LA REFERENCIA"
	CodigoRefCorrigeMonto = "3"
	RazonRefCorrigeMonto  = "CORRIGE MONTO"
)

// CadenasVerificadas: tipos cuya cadena de emisión está verificada de punta a punta contra el
// SII DESDE GO, con evidencia. Python ya tiene 34 y 61 (factura 63 y NC 60, 2026-10-08); el
// port se da por verificado cuando reproduce esos cuerpos byte a byte Y una corrida real pasa.
// Hasta entonces, Emitir exige AceptarRiesgoFolio.
var CadenasVerificadas = map[int]string{}
