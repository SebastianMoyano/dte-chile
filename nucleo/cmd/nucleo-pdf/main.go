// nucleo-pdf: dibuja la representación gráfica de un DTE desde su XML firmado.
//
//	nucleo-pdf --xml storage/dtes/DTE_33_1.xml --salida /tmp/doc.pdf [--ambiente simulacion] [--resolucion 2026-01-01:0] [--hoy 2026-10-11]
//	nucleo-pdf --xml … --json            (solo imprime el documento reconstruido y el TED, sin PDF)
//
// Boletas (39/41) salen en 80 mm; el resto en carta. El TED va al PDF417 verbatim.
package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"strconv"
	"strings"

	"dtechile/nucleo/pdf"
)

func main() {
	xmlPath := flag.String("xml", "", "XML firmado del DTE (o el sobre)")
	salida := flag.String("salida", "", "archivo PDF a escribir")
	ambiente := flag.String("ambiente", "certificacion", "certificacion | produccion | simulacion")
	resol := flag.String("resolucion", "2026-07-08:0", "fecha:numero de la resolución del emisor (pie del PDF)")
	hoy := flag.String("hoy", "", "fecha de generación para el pie (default: hoy)")
	soloJSON := flag.Bool("json", false, "imprimir el documento reconstruido y el TED en JSON")
	timbre := flag.String("timbre-png", "", "escribir solo el PDF417 del TED como PNG (verificación)")
	flag.Parse()
	if *xmlPath == "" {
		fmt.Fprintln(os.Stderr, "falta --xml")
		os.Exit(2)
	}
	raw, err := os.ReadFile(*xmlPath)
	if err != nil {
		fatal(err)
	}
	d, ted, err := pdf.DesdeXML(raw)
	if err != nil {
		fatal(err)
	}
	if *timbre != "" {
		b, err := pdf.TimbrePNG(ted)
		if err != nil {
			fatal(err)
		}
		if err := os.WriteFile(*timbre, b, 0o644); err != nil {
			fatal(err)
		}
		return
	}
	if *soloJSON {
		enc := json.NewEncoder(os.Stdout)
		enc.SetIndent("", " ")
		enc.SetEscapeHTML(false)
		enc.Encode(map[string]any{"documento": d, "ted": ted})
		return
	}
	fecha, numTxt, _ := strings.Cut(*resol, ":")
	num, _ := strconv.Atoi(numTxt)
	var b []byte
	if d.TipoDTE == 39 || d.TipoDTE == 41 {
		b, err = pdf.Boleta80mm(d, ted)
	} else {
		b, err = pdf.Carta(d, ted, pdf.Opciones{Ambiente: *ambiente, ResolucionFecha: fecha, ResolucionNum: num, Hoy: *hoy})
	}
	if err != nil {
		fatal(err)
	}
	if *salida == "" {
		os.Stdout.Write(b)
		return
	}
	if err := os.WriteFile(*salida, b, 0o644); err != nil {
		fatal(err)
	}
	fmt.Fprintf(os.Stderr, "PDF: %s (%d bytes)\n", *salida, len(b))
}

func fatal(err error) {
	fmt.Fprintln(os.Stderr, "error:", err)
	os.Exit(1)
}
