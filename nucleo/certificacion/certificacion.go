// Package certificacion es certificacion_sii.py + dry_run_certificacion.py: los 16 casos del
// Set de Pruebas del SII (facturas, exentas, notas de crédito y débito) generados con el
// mismo camino de firma que la emisión (DTE standalone + sobre por string), medidos contra
// Python con tests/dorado/certificacion/ (certificado y CAF ficticios, hora fija).
package certificacion

import (
	_ "embed"
	"encoding/json"
	"fmt"
	"strings"

	"dtechile/nucleo/firma"
	"dtechile/nucleo/ted"
	"dtechile/nucleo/totales"
	"dtechile/nucleo/xmlgen"
)

// Copia de tests/dorado/certificacion/casos.json (la única fuente es
// certificacion_sii.definir_casos; TestCasosIguales exige que sean idénticos).
//
//go:embed casos.json
var casosJSON []byte

type Item struct {
	Nombre       string  `json:"nombre"`
	Cantidad     float64 `json:"cantidad"`
	Precio       float64 `json:"precio"`
	DescuentoPct float64 `json:"descuento_pct"`
	Exento       bool    `json:"exento"`
	Unidad       string  `json:"unidad"`
}

type Referencia struct {
	TipoDTERef int    `json:"tipo_dte_ref"`
	FolioRef   int    `json:"folio_ref"`
	Razon      string `json:"razon"`
}

type Caso struct {
	Nombre     string      `json:"nombre"`
	TipoDTE    int         `json:"tipo_dte"`
	Folio      int         `json:"folio"`
	Items      []Item      `json:"items"`
	Referencia *Referencia `json:"referencia"`
}

// Casos devuelve los 16 casos del set.
func Casos() ([]Caso, error) {
	var c []Caso
	if err := json.Unmarshal(casosJSON, &c); err != nil {
		return nil, err
	}
	return c, nil
}

// Datos del emisor que el script toma de la CLI/.env y del receptor (el SII) que fija.
const (
	Giro                = "Venta de alimentos"
	CodigoActividad     = 463014
	Direccion           = "Av. Providencia 1234"
	Comuna              = "Providencia"
	Ciudad              = "Santiago"
	RutReceptor         = "60803000-K"
	RazonSocialReceptor = "SII"
	GiroReceptor        = "Gobierno"
	DireccionReceptor   = "Morandé 115"
	ComunaReceptor      = "Santiago"
	CiudadReceptor      = "Santiago"
	FechaResolucion     = "2026-07-08" // la de certificación (Maullín)
	NumeroResolucion    = 0
)

// Emisor es lo configurable del script (--rut, --razon-social, --email).
type Emisor struct {
	Rut, RazonSocial, Email string
}

// CodigoRef es codigo_ref_desde_razon: 1 anula, 2 corrige texto, 3 corrige montos.
func CodigoRef(razon string) int {
	r := strings.ToUpper(razon)
	switch {
	case strings.Contains(r, "ANULA"):
		return 1
	case strings.Contains(r, "CORRIGE GIRO"), strings.Contains(r, "CORRIGE TEXTO"), strings.Contains(r, "MODIFICA GIRO"):
		return 2
	}
	return 3
}

// escaparScript es _xml_escape del script: & < > " ' (más que el del generador).
func escaparScript(s string) string {
	return strings.NewReplacer("&", "&amp;", "<", "&lt;", ">", "&gt;", `"`, "&quot;", "'", "&apos;").Replace(s)
}

// Documento arma el xmlgen.Documento del caso como generar_dte (ítem de relleno en las notas
// sin ítems, referencia con su CodRef, contado).
func Documento(c Caso, e Emisor, fecha string) xmlgen.Documento {
	d := xmlgen.Documento{TipoDTE: c.TipoDTE, Folio: c.Folio, FechaEmision: fecha, FormaPago: 1,
		Emisor: xmlgen.Emisor{Rut: e.Rut, RazonSocial: e.RazonSocial, Giro: Giro, CodigoActividad: CodigoActividad,
			Direccion: Direccion, Comuna: Comuna, Ciudad: Ciudad, Email: e.Email},
		Receptor: xmlgen.Receptor{Rut: RutReceptor, RazonSocial: RazonSocialReceptor, Giro: GiroReceptor,
			Direccion: DireccionReceptor, Comuna: ComunaReceptor, Ciudad: CiudadReceptor}}
	for i, it := range c.Items {
		d.Items = append(d.Items, xmlgen.Item{NumeroLinea: i + 1, Nombre: it.Nombre, Cantidad: it.Cantidad, PrecioUnitario: it.Precio,
			UnidadMedida: it.Unidad, DescuentoPct: it.DescuentoPct, Exento: it.Exento})
	}
	if len(d.Items) == 0 {
		// Nota de corrección de texto / anulación sin monto: una línea con la razón, cantidad 1,
		// monto 0 (el generador omite PrcItem=0). XSD-válido.
		razon := "REFERENCIA"
		if c.Referencia != nil && c.Referencia.Razon != "" {
			razon = c.Referencia.Razon
		}
		if r := []rune(razon); len(r) > 80 {
			razon = string(r[:80])
		}
		d.Items = append(d.Items, xmlgen.Item{NumeroLinea: 1, Nombre: razon, Cantidad: 1, PrecioUnitario: 0})
	}
	if c.Referencia != nil {
		d.Referencias = []xmlgen.Referencia{{NumeroLinea: 1, TipoDocRef: c.Referencia.TipoDTERef, FolioRef: c.Referencia.FolioRef,
			FechaDocRef: fecha, CodigoRef: CodigoRef(c.Referencia.Razon), RazonRef: c.Referencia.Razon}}
	}
	return d
}

// Generar es generar_dte: TED (el primer ítem escapado ANTES de recortar, como el script),
// DTE firmado standalone y sobre EnvioDTE por string. Devuelve el sobre en ISO-8859-1.
func Generar(c Caso, e Emisor, caf *ted.CAF, cert *firma.Certificado, fecha, marca string) ([]byte, string, error) {
	d := Documento(c, e, fecha)
	its := make([]totales.Item, len(d.Items))
	for i, it := range d.Items {
		its[i] = totales.Item{Cantidad: it.Cantidad, PrecioUnitario: it.PrecioUnitario, DescuentoPct: it.DescuentoPct, DescuentoMonto: it.DescuentoMonto, Exento: it.Exento}
	}
	tot := totales.Calcular(its, c.TipoDTE)
	primer := d.Items[0].Nombre
	if primer == "" {
		primer = "Sin Items"
	}
	d.Marca = marca
	var err error
	d.TED, err = ted.Generar(caf, ted.Datos{Folio: c.Folio, RutEmisor: e.Rut, RutReceptor: RutReceptor, TipoDTE: c.TipoDTE, FechaEmision: fecha,
		MontoTotal: tot.MontoTotal, RazonSocialReceptor: RazonSocialReceptor, PrimerItem: escaparScript(primer), PrimerItemLiteral: true, Marca: marca})
	if err != nil {
		return nil, "", fmt.Errorf("%s: TED: %w", c.Nombre, err)
	}
	arbol := xmlgen.GenerarDTE(d)
	firmado, err := cert.FirmarDTE(arbol.String(), arbol.Hijos[0].String(), c.TipoDTE, c.Folio)
	if err != nil {
		return nil, "", fmt.Errorf("%s: firma: %w", c.Nombre, err)
	}
	rutEnvia, err := cert.RutEmisor()
	if err != nil {
		return nil, "", err
	}
	envio, err := cert.Sobre([]string{firmado}, map[int]int{c.TipoDTE: 1}, e.Rut, rutEnvia, FechaResolucion, NumeroResolucion, "EnvioDTE", marca)
	if err != nil {
		return nil, "", fmt.Errorf("%s: sobre: %w", c.Nombre, err)
	}
	return envio, firmado, nil
}

// NombreArchivo es el del dry run: <caso>_T<tipo>_F<folio>.xml
func NombreArchivo(c Caso) string { return fmt.Sprintf("%s_T%d_F%d", c.Nombre, c.TipoDTE, c.Folio) }
