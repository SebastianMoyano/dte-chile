// nucleo-dorado: el port en Go frente al corpus dorado.
//
//	nucleo-dorado <entrada.json> <fixtures/> <salida/>
//
// Lee el caso, los fixtures y RELOJ_FIJO, y escribe en <salida/> lo que ya sabe producir
// (hoy: ted.xml y totales.json por documento). test_dorado.py --port … --parcial lo compara.
package main

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"

	"dtechile/nucleo/ted"
	"dtechile/nucleo/totales"
)

type itemIn struct {
	Nombre         string   `json:"nombre"`
	Cantidad       *float64 `json:"cantidad"`
	PrecioUnitario float64  `json:"precio_unitario"`
	DescuentoPct   float64  `json:"descuento_pct"`
	DescuentoMonto float64  `json:"descuento_monto"`
	Exento         bool     `json:"exento"`
}

type receptorIn struct {
	Rut         string `json:"rut"`
	RazonSocial string `json:"razon_social"`
}

type docIn struct {
	TipoDTE      int        `json:"tipo_dte"`
	Folio        int        `json:"folio"`
	FechaEmision string     `json:"fecha_emision"`
	Receptor     receptorIn `json:"receptor"`
	Items        []itemIn   `json:"items"`
}

type casoIn struct {
	docIn
	Documentos []docIn `json:"documentos"`
}

const rutEmisorDemo = "77777777-7"

func latin1(s string) []byte {
	b, err := ted.Latin1(s)
	if err != nil {
		panic(err)
	}
	return b
}

func main() {
	if len(os.Args) != 4 {
		fmt.Fprintln(os.Stderr, "uso: nucleo-dorado <entrada.json> <fixtures/> <salida/>")
		os.Exit(2)
	}
	entrada, fixtures, salida := os.Args[1], os.Args[2], os.Args[3]
	marca := os.Getenv("RELOJ_FIJO")
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
	for i, d := range docs {
		suf := ""
		if len(docs) > 1 {
			suf = fmt.Sprintf("_%d", i+1)
		}
		cafBytes, err := os.ReadFile(filepath.Join(fixtures, fmt.Sprintf("caf_%d.xml", d.TipoDTE)))
		if err != nil {
			fatal(err)
		}
		// El archivo CAF viene en ISO-8859-1: cada byte es una runa.
		cafStr := make([]rune, len(cafBytes))
		for k, b := range cafBytes {
			cafStr[k] = rune(b)
		}
		caf, err := ted.ParsearCAF(string(cafStr))
		if err != nil {
			fatal(err)
		}
		items := make([]totales.Item, len(d.Items))
		for k, it := range d.Items {
			c := 1.0
			if it.Cantidad != nil {
				c = *it.Cantidad
			}
			items[k] = totales.Item{Cantidad: c, PrecioUnitario: it.PrecioUnitario,
				DescuentoPct: it.DescuentoPct, DescuentoMonto: it.DescuentoMonto, Exento: it.Exento}
		}
		tot := totales.Calcular(items, d.TipoDTE)
		tj, _ := json.MarshalIndent(tot, "", " ")
		_ = os.WriteFile(filepath.Join(salida, "totales"+suf+".json"), tj, 0o644)
		primer := "Sin Items"
		if len(d.Items) > 0 {
			primer = d.Items[0].Nombre
		}
		t, err := ted.Generar(caf, ted.Datos{Folio: d.Folio, RutEmisor: rutEmisorDemo, RutReceptor: d.Receptor.Rut,
			TipoDTE: d.TipoDTE, FechaEmision: d.FechaEmision, MontoTotal: tot.MontoTotal,
			RazonSocialReceptor: d.Receptor.RazonSocial, PrimerItem: primer, Marca: marca})
		if err != nil {
			fatal(err)
		}
		if err := os.WriteFile(filepath.Join(salida, "ted"+suf+".xml"), latin1(t), 0o644); err != nil {
			fatal(err)
		}
	}
}

func fatal(err error) {
	fmt.Fprintln(os.Stderr, "nucleo-dorado:", err)
	os.Exit(1)
}
