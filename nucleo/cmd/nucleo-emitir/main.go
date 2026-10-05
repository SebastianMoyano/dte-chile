// nucleo-emitir: emite un documento con el núcleo en Go contra la base y el storage del
// motor (fase 2 del plan). Lee el documento en JSON por stdin y escribe el resultado en JSON.
//
//	nucleo-emitir --db dte_database.db --storage storage --cert firma.p12 --ambiente certificacion \
//	              --resolucion-fecha 2026-07-08 --resolucion-numero 0 < documento.json
//
// La clave del certificado va en NUCLEO_CERT_CLAVE (nunca como argumento: se vería en ps).
// RELOJ_FIJO fija la hora (solo pruebas). No genera PDF ni envía al SII.
// Los CAF que entrega el SII traen claves RSA de 512 bits; Go >= 1.24 las rechaza por defecto
// ("512-bit keys are insecure"). Se habilitan aquí porque firmar el TED con esa clave no es
// opcional: es el formato del SII. No afecta a la firma del DTE (certificado de 2048).
//
//go:debug rsa1024min=0
package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"os"
	"time"

	"dtechile/nucleo/almacen"
	"dtechile/nucleo/emision"
	"dtechile/nucleo/firma"
	"dtechile/nucleo/xmlgen"
)

type entrada struct {
	TipoDTE      int    `json:"tipo_dte"`
	Folio        int    `json:"folio"`
	FechaEmision string `json:"fecha_emision"`
	Emisor       struct {
		Rut, RazonSocial, Giro, Direccion, Comuna, Ciudad, Telefono, Email string
		CodigoActividad                                                    int
	} `json:"-"`
	EmisorJSON   map[string]any `json:"emisor"`
	ReceptorJSON map[string]any `json:"receptor"`
	Items        []struct {
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
	} `json:"items"`
	Referencias []struct {
		NumeroLinea int    `json:"numero_linea"`
		TipoDocRef  int    `json:"tipo_doc_ref"`
		FolioRef    int    `json:"folio_ref"`
		FechaDocRef string `json:"fecha_doc_ref"`
		CodigoRef   int    `json:"codigo_ref"`
		RazonRef    string `json:"razon_ref"`
	} `json:"referencias"`
	FormaPago         *int   `json:"forma_pago"`
	FechaVencimiento  string `json:"fecha_vencimiento"`
	IndicadorServicio int    `json:"indicador_servicio"`
	IndServicio       int    `json:"ind_servicio"`
}

func s(m map[string]any, k string) string {
	if v, ok := m[k]; ok && v != nil {
		return fmt.Sprint(v)
	}
	return ""
}

func main() {
	db := flag.String("db", "dte_database.db", "ruta de la base SQLite del motor")
	storage := flag.String("storage", "storage", "carpeta storage del motor")
	certPath := flag.String("cert", "", "certificado .p12/.pfx")
	ambiente := flag.String("ambiente", "certificacion", "certificacion | produccion | simulacion")
	fResol := flag.String("resolucion-fecha", "", "FchResol de la carátula (la del emisor y ambiente)")
	nResol := flag.Int("resolucion-numero", 0, "NroResol de la carátula")
	flag.Parse()
	clave := os.Getenv("NUCLEO_CERT_CLAVE")
	if *certPath == "" || *fResol == "" {
		fatal(fmt.Errorf("faltan --cert y/o --resolucion-fecha"))
	}
	raw, err := io.ReadAll(os.Stdin)
	if err != nil {
		fatal(err)
	}
	var e entrada
	if err := json.Unmarshal(raw, &e); err != nil {
		fatal(err)
	}
	p12, err := os.ReadFile(*certPath)
	if err != nil {
		fatal(err)
	}
	cert, err := firma.CargarP12(p12, clave)
	if err != nil {
		fatal(err)
	}
	alm, err := almacen.Abrir(*db)
	if err != nil {
		fatal(err)
	}
	defer alm.Cerrar()
	marca := os.Getenv("RELOJ_FIJO")
	if marca == "" {
		marca = time.Now().Format("2006-01-02T15:04:05")
	}
	doc := xmlgen.Documento{TipoDTE: e.TipoDTE, Folio: e.Folio, FechaEmision: e.FechaEmision,
		FechaVencimiento: e.FechaVencimiento, IndicadorServicio: e.IndicadorServicio, IndServicioBoleta: e.IndServicio, FormaPago: 1}
	if e.FormaPago != nil {
		doc.FormaPago = *e.FormaPago
	}
	em := e.EmisorJSON
	doc.Emisor = xmlgen.Emisor{Rut: s(em, "rut"), RazonSocial: s(em, "razon_social"), Giro: s(em, "giro"),
		Direccion: s(em, "direccion"), Comuna: s(em, "comuna"), Ciudad: s(em, "ciudad"), Telefono: s(em, "telefono"), Email: s(em, "email")}
	if v, ok := em["codigo_actividad"].(float64); ok {
		doc.Emisor.CodigoActividad = int(v)
	}
	rc := e.ReceptorJSON
	doc.Receptor = xmlgen.Receptor{Rut: s(rc, "rut"), RazonSocial: s(rc, "razon_social"), Giro: s(rc, "giro"),
		Direccion: s(rc, "direccion"), Comuna: s(rc, "comuna"), Ciudad: s(rc, "ciudad"), Email: s(rc, "email")}
	for _, it := range e.Items {
		c := 1.0
		if it.Cantidad != nil {
			c = *it.Cantidad
		}
		doc.Items = append(doc.Items, xmlgen.Item{NumeroLinea: it.NumeroLinea, Nombre: it.Nombre, Descripcion: it.Descripcion,
			Cantidad: c, UnidadMedida: it.UnidadMedida, PrecioUnitario: it.PrecioUnitario, DescuentoPct: it.DescuentoPct,
			DescuentoMonto: it.DescuentoMonto, Exento: it.Exento, CodigoProducto: it.CodigoProducto})
	}
	for _, r := range e.Referencias {
		doc.Referencias = append(doc.Referencias, xmlgen.Referencia{NumeroLinea: r.NumeroLinea, TipoDocRef: r.TipoDocRef,
			FolioRef: r.FolioRef, FechaDocRef: r.FechaDocRef, CodigoRef: r.CodigoRef, RazonRef: r.RazonRef})
	}
	res, err := emision.Emitir(emision.Contexto{Almacen: alm, Cert: cert, StorageBase: *storage, Ambiente: *ambiente,
		FechaResolucion: *fResol, NumeroResolucion: *nResol, Marca: marca}, doc)
	if err != nil {
		fatal(err)
	}
	out, _ := json.Marshal(res)
	fmt.Println(string(out))
}

func fatal(err error) {
	fmt.Fprintln(os.Stderr, "nucleo-emitir:", err)
	os.Exit(1)
}
