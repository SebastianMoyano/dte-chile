// nucleo-dorado: el port en Go frente al corpus dorado.
//
//	nucleo-dorado <entrada.json> <fixtures/> <salida/>
//
// Lee el caso, los fixtures y el entorno (RELOJ_FIJO, DORADO_RESOLUCION_*), y escribe en
// <salida/> ted.xml, dte.xml, totales.json por documento y envio.xml.
// test_dorado.py --port nucleo/bin/nucleo-dorado lo compara byte a byte.
package main

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strconv"

	"dtechile/nucleo/firma"
	"dtechile/nucleo/ted"
	"dtechile/nucleo/totales"
	"dtechile/nucleo/xmlgen"
)

type itemIn struct {
	NumeroLinea    int      `json:"numero_linea"`
	Nombre         string   `json:"nombre"`
	Descripcion    string   `json:"descripcion"`
	Cantidad       *float64 `json:"cantidad"`
	UnidadMedida   string   `json:"unidad_medida"`
	PrecioUnitario float64  `json:"precio_unitario"`
	DescuentoPct   float64  `json:"descuento_pct"`
	DescuentoMonto float64  `json:"descuento_monto"`
	Exento         bool     `json:"exento"`
	CodigoProducto string   `json:"codigo_producto"`
}

type receptorIn struct {
	Rut         string `json:"rut"`
	RazonSocial string `json:"razon_social"`
	Giro        string `json:"giro"`
	Direccion   string `json:"direccion"`
	Comuna      string `json:"comuna"`
	Ciudad      string `json:"ciudad"`
	Email       string `json:"email"`
}

type refIn struct {
	NumeroLinea int    `json:"numero_linea"`
	TipoDocRef  int    `json:"tipo_doc_ref"`
	FolioRef    int    `json:"folio_ref"`
	FechaDocRef string `json:"fecha_doc_ref"`
	CodigoRef   int    `json:"codigo_ref"`
	RazonRef    string `json:"razon_ref"`
}

type docIn struct {
	TipoDTE           int        `json:"tipo_dte"`
	Folio             int        `json:"folio"`
	FechaEmision      string     `json:"fecha_emision"`
	Receptor          receptorIn `json:"receptor"`
	Items             []itemIn   `json:"items"`
	Referencias       []refIn    `json:"referencias"`
	FormaPago         *int       `json:"forma_pago"`
	FechaVencimiento  string     `json:"fecha_vencimiento"`
	IndicadorServicio int        `json:"indicador_servicio"`
	IndServicio       int        `json:"ind_servicio"`
	Observaciones     string     `json:"observaciones"`
}

type casoIn struct {
	docIn
	Documentos []docIn `json:"documentos"`
}

// EMISOR_DEMO de core/simulacion.py.
var emisorDemo = xmlgen.Emisor{Rut: "77777777-7", RazonSocial: "EMPRESA DEMO SPA", Giro: "Cafetería",
	CodigoActividad: 561000, Direccion: "Calle Ficticia 123", Comuna: "Santiago", Ciudad: "Santiago",
	Email: "hola@empresademo.cl"}

func latin1(s string) []byte {
	b, err := ted.Latin1(s)
	if err != nil {
		fatal(err)
	}
	return b
}

func leerLatin1(ruta string) string {
	b, err := os.ReadFile(ruta)
	if err != nil {
		fatal(err)
	}
	r := make([]rune, len(b))
	for i, c := range b {
		r[i] = rune(c)
	}
	return string(r)
}

func main() {
	if len(os.Args) != 4 {
		fmt.Fprintln(os.Stderr, "uso: nucleo-dorado <entrada.json> <fixtures/> <salida/>")
		os.Exit(2)
	}
	entrada, fixtures, salida := os.Args[1], os.Args[2], os.Args[3]
	marca := os.Getenv("RELOJ_FIJO")
	fechaResol := os.Getenv("DORADO_RESOLUCION_FECHA")
	nroResol, _ := strconv.Atoi(os.Getenv("DORADO_RESOLUCION_NUMERO"))

	raw, err := os.ReadFile(entrada)
	if err != nil {
		fatal(err)
	}
	var caso casoIn
	if err := json.Unmarshal(raw, &caso); err != nil {
		fatal(err)
	}
	docs := caso.Documentos
	if len(docs) == 0 {
		docs = []docIn{caso.docIn}
	}
	if err := os.MkdirAll(salida, 0o755); err != nil {
		fatal(err)
	}
	p12, err := os.ReadFile(filepath.Join(fixtures, "cert_demo.p12"))
	if err != nil {
		fatal(err)
	}
	cert, err := firma.CargarP12(p12, "demo")
	if err != nil {
		fatal(err)
	}
	rutEnvia, err := cert.RutEmisor()
	if err != nil {
		fatal(err)
	}

	esBoleta := true
	for _, d := range docs {
		if d.TipoDTE != 39 && d.TipoDTE != 41 {
			esBoleta = false
		}
	}
	var firmados []string
	subtotales := map[int]int{}
	for i, d := range docs {
		suf := ""
		if len(docs) > 1 {
			suf = fmt.Sprintf("_%d", i+1)
		}
		caf, err := ted.ParsearCAF(leerLatin1(filepath.Join(fixtures, fmt.Sprintf("caf_%d.xml", d.TipoDTE))))
		if err != nil {
			fatal(err)
		}
		items := make([]xmlgen.Item, len(d.Items))
		tItems := make([]totales.Item, len(d.Items))
		for k, it := range d.Items {
			c := 1.0
			if it.Cantidad != nil {
				c = *it.Cantidad
			}
			items[k] = xmlgen.Item{NumeroLinea: it.NumeroLinea, Nombre: it.Nombre, Descripcion: it.Descripcion,
				Cantidad: c, UnidadMedida: it.UnidadMedida, PrecioUnitario: it.PrecioUnitario,
				DescuentoPct: it.DescuentoPct, DescuentoMonto: it.DescuentoMonto, Exento: it.Exento,
				CodigoProducto: it.CodigoProducto}
			tItems[k] = totales.Item{Cantidad: c, PrecioUnitario: it.PrecioUnitario, DescuentoPct: it.DescuentoPct,
				DescuentoMonto: it.DescuentoMonto, Exento: it.Exento}
		}
		tot := totales.Calcular(tItems, d.TipoDTE)
		tj, _ := json.MarshalIndent(tot, "", " ")
		_ = os.WriteFile(filepath.Join(salida, "totales"+suf+".json"), tj, 0o644)

		primer := "Sin Items"
		if len(d.Items) > 0 {
			primer = d.Items[0].Nombre
		}
		t, err := ted.Generar(caf, ted.Datos{Folio: d.Folio, RutEmisor: emisorDemo.Rut, RutReceptor: d.Receptor.Rut,
			TipoDTE: d.TipoDTE, FechaEmision: d.FechaEmision, MontoTotal: tot.MontoTotal,
			RazonSocialReceptor: d.Receptor.RazonSocial, PrimerItem: primer, Marca: marca})
		if err != nil {
			fatal(err)
		}
		if err := os.WriteFile(filepath.Join(salida, "ted"+suf+".xml"), latin1(t), 0o644); err != nil {
			fatal(err)
		}

		fp := 1
		if d.FormaPago != nil {
			fp = *d.FormaPago
		}
		var refs []xmlgen.Referencia
		for _, r := range d.Referencias {
			refs = append(refs, xmlgen.Referencia{NumeroLinea: r.NumeroLinea, TipoDocRef: r.TipoDocRef, FolioRef: r.FolioRef,
				FechaDocRef: r.FechaDocRef, CodigoRef: r.CodigoRef, RazonRef: r.RazonRef})
		}
		doc := xmlgen.Documento{TipoDTE: d.TipoDTE, Folio: d.Folio, FechaEmision: d.FechaEmision, Emisor: emisorDemo,
			Receptor: xmlgen.Receptor{Rut: d.Receptor.Rut, RazonSocial: d.Receptor.RazonSocial, Giro: d.Receptor.Giro,
				Direccion: d.Receptor.Direccion, Comuna: d.Receptor.Comuna, Ciudad: d.Receptor.Ciudad, Email: d.Receptor.Email},
			Items: items, Referencias: refs, FormaPago: fp, FechaVencimiento: d.FechaVencimiento,
			IndicadorServicio: d.IndicadorServicio, IndServicioBoleta: d.IndServicio, TED: t, Marca: marca}
		var arbol *xmlgen.Nodo
		if esBoleta {
			arbol = xmlgen.GenerarBoleta(doc)
		} else {
			arbol = xmlgen.GenerarDTE(doc)
		}
		documento := arbol.Hijos[0].String() // <Documento …> sin el xmlns (lo aporta el apex en C14N)
		firmado, err := cert.FirmarDTE(arbol.String(), documento, d.TipoDTE, d.Folio)
		if err != nil {
			fatal(err)
		}
		if err := os.WriteFile(filepath.Join(salida, "dte"+suf+".xml"), latin1(firmado), 0o644); err != nil {
			fatal(err)
		}
		firmados = append(firmados, firmado)
		subtotales[d.TipoDTE]++
	}
	raiz := "EnvioDTE"
	if esBoleta {
		raiz = "EnvioBOLETA"
	}
	envio, err := cert.Sobre(firmados, subtotales, emisorDemo.Rut, rutEnvia, fechaResol, nroResol, raiz, marca)
	if err != nil {
		fatal(err)
	}
	if err := os.WriteFile(filepath.Join(salida, "envio.xml"), envio, 0o644); err != nil {
		fatal(err)
	}
}

func fatal(err error) {
	fmt.Fprintln(os.Stderr, "nucleo-dorado:", err)
	os.Exit(1)
}
