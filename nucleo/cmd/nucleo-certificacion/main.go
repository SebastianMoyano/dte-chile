// nucleo-certificacion: el Set de Pruebas del SII (16 casos) con el núcleo Go, como
// dry_run_certificacion.py (sin red) y certificacion_sii.py (--enviar).
//
//	nucleo-certificacion --rut 77777777-7 --razon-social "EMPRESA DEMO SPA" --cert firma.pfx --cafs storage/cafs
//	nucleo-certificacion … --enviar --ambiente certificacion      (sube cada sobre por DTEUpload: gasta folios)
//
// La clave del certificado NUNCA va por flag: NUCLEO_CLAVE_CERTIFICADO en el entorno o el
// Llavero de macOS (servicio DTE_KEYCHAIN_SERVICE, default dte-cert-firma). Salida:
// <salida>/dtes_cert/<caso>_T<tipo>_F<folio>.xml, <salida>/pdfs_cert/…pdf y
// <salida>/resultados_certificacion_go.json. Cada sobre se valida contra el XSD antes de
// escribirse. --fecha y --marca fijan fecha y hora (reproducible; es lo que mide el test).
//
//go:debug rsa1024min=0
package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"

	"dtechile/nucleo/certificacion"
	"dtechile/nucleo/cliutil"
	"dtechile/nucleo/pdf"
	"dtechile/nucleo/sii"
	"dtechile/nucleo/ted"
	"dtechile/nucleo/xsd"
)

func main() {
	rut := flag.String("rut", envO("DTE_RUT_EMPRESA", "76111111-6"), "RUT del emisor, con guión y DV")
	razon := flag.String("razon-social", envO("DTE_RAZON_SOCIAL", "EMPRESA DEMO SPA"), "razón social del emisor")
	email := flag.String("email", envO("DTE_EMAIL", "contacto@ejemplo.cl"), "correo del emisor")
	certPath := flag.String("cert", envO("DTE_CERT_PATH", "firma.pfx"), ".pfx/.p12 del mandatario")
	certID := flag.Int64("cert-id", 0, "certificado del keystore del motor (en vez de --cert)")
	cuenta := flag.Int64("cuenta", 1, "cuenta dueña del keystore")
	env := flag.String("env", ".env", "archivo .env del motor (para --cert-id)")
	db := flag.String("db", "", "SQLite del motor (para --cert-id)")
	cafs := flag.String("cafs", "storage/cafs", "carpeta con los CAF (xml) de 33, 34, 56 y 61")
	salida := flag.String("salida", "storage", "raíz de salida (dtes_cert/, pdfs_cert/, resultados)")
	fecha := flag.String("fecha", time.Now().Format("2006-01-02"), "fecha de emisión y de las referencias")
	marca := flag.String("marca", time.Now().Format("2006-01-02T15:04:05"), "hora de firma (TmstFirma/TmstFirmaEnv/TSTED)")
	enviar := flag.Bool("enviar", false, "subir cada sobre al SII por DTEUpload (gasta folios)")
	ambiente := flag.String("ambiente", "certificacion", "certificacion | produccion (solo con --enviar)")
	flag.Parse()

	cert, err := cliutil.CargarCertificado(*certPath, *certID, *cuenta, *env, *db)
	if err != nil {
		fatal(fmt.Errorf("certificado: %w", err))
	}
	rutCert, _ := cert.RutEmisor()
	fmt.Printf("✅ Certificado cargado: %s\n", rutCert)
	porTipo := map[int]*ted.CAF{}
	archivos, _ := filepath.Glob(filepath.Join(*cafs, "*.xml"))
	for _, a := range archivos {
		b, err := os.ReadFile(a)
		if err != nil {
			continue
		}
		c, err := ted.ParsearCAF(string(b))
		if err != nil {
			fmt.Printf("  ✗ %s: %v\n", filepath.Base(a), err)
			continue
		}
		porTipo[c.TipoDTE] = c
		fmt.Printf("  ✅ CAF T%d: folios %d-%d (%s)\n", c.TipoDTE, c.FolioDesde, c.FolioHasta, filepath.Base(a))
	}
	for _, t := range []int{33, 34, 56, 61} {
		if porTipo[t] == nil {
			fatal(fmt.Errorf("falta CAF para T%d en %s", t, *cafs))
		}
	}
	casos, err := certificacion.Casos()
	if err != nil {
		fatal(err)
	}
	dtes, pdfs := filepath.Join(*salida, "dtes_cert"), filepath.Join(*salida, "pdfs_cert")
	_ = os.MkdirAll(dtes, 0o755)
	_ = os.MkdirAll(pdfs, 0o755)
	var cli *sii.Cliente
	if *enviar {
		if cli, err = sii.Nuevo(*ambiente, cert); err != nil {
			fatal(err)
		}
	}
	e := certificacion.Emisor{Rut: *rut, RazonSocial: *razon, Email: *email}
	type resultado struct {
		Caso    string `json:"caso"`
		TipoDTE int    `json:"tipo_dte"`
		Folio   int    `json:"folio"`
		XMLOK   bool   `json:"xml_ok"`
		XSDOK   bool   `json:"xsd_ok"`
		PDFOK   bool   `json:"pdf_ok"`
		Estado  string `json:"estado"`
		TrackID int64  `json:"track_id,omitempty"`
		Error   string `json:"error,omitempty"`
	}
	var res []resultado
	fmt.Printf("\n📋 %d casos del Set de Pruebas (fecha %s)\n", len(casos), *fecha)
	for i, c := range casos {
		r := resultado{Caso: c.Nombre, TipoDTE: c.TipoDTE, Folio: c.Folio, Estado: "generado"}
		fmt.Printf("[%2d/%d] %-12s T%d F%-3d ", i+1, len(casos), c.Nombre, c.TipoDTE, c.Folio)
		envio, firmado, err := certificacion.Generar(c, e, porTipo[c.TipoDTE], cert, *fecha, *marca)
		if err != nil {
			r.Error, r.Estado = err.Error(), "error"
			fmt.Printf("✗ %v\n", err)
			res = append(res, r)
			continue
		}
		r.XMLOK = true
		if err := xsd.ValidarError(envio); err != nil {
			r.Error, r.Estado = err.Error(), "error"
			fmt.Printf("✗ XSD: %v\n", err)
			res = append(res, r)
			continue
		}
		r.XSDOK = true
		nombre := certificacion.NombreArchivo(c)
		if err := os.WriteFile(filepath.Join(dtes, nombre+".xml"), envio, 0o644); err != nil {
			fatal(err)
		}
		if raw, err := ted.Latin1(firmado); err == nil {
			if doc, tedXML, err := pdf.DesdeXML(raw); err == nil {
				if b, err := pdf.Carta(doc, tedXML, pdf.Opciones{Ambiente: *ambiente, ResolucionFecha: certificacion.FechaResolucion, ResolucionNum: certificacion.NumeroResolucion, Hoy: *fecha}); err == nil {
					_ = os.WriteFile(filepath.Join(pdfs, nombre+".pdf"), b, 0o644)
					r.PDFOK = true
				}
			}
		}
		fmt.Printf("✓XML ✓XSD %sPDF (%d bytes)", marcaOK(r.PDFOK), len(envio))
		if cli != nil {
			n, dv, _ := strings.Cut(*rut, "-")
			track, _, err := cli.EnviarDTE(envio, n, dv)
			if err != nil {
				r.Error, r.Estado = err.Error(), "error"
				fmt.Printf("  ✗ envío: %v", err)
			} else {
				r.TrackID, r.Estado = track, "enviado"
				fmt.Printf("  📤 TrackID %d", track)
			}
		}
		fmt.Println()
		res = append(res, r)
	}
	ok := 0
	for _, r := range res {
		if r.XMLOK && r.XSDOK && r.PDFOK && r.Error == "" {
			ok++
		}
	}
	out, _ := json.MarshalIndent(res, "", " ")
	ruta := filepath.Join(*salida, "resultados_certificacion_go.json")
	_ = os.WriteFile(ruta, out, 0o644)
	fmt.Printf("\n✅ Casos OK (XML+XSD+PDF%s): %d/%d — resultados en %s\n", ternario(*enviar, "+envío", ""), ok, len(res), ruta)
	if ok != len(res) {
		os.Exit(1)
	}
}

func marcaOK(b bool) string {
	if b {
		return "✓"
	}
	return "✗"
}

func ternario(c bool, a, b string) string {
	if c {
		return a
	}
	return b
}

func envO(k, def string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return def
}

func fatal(err error) {
	fmt.Fprintln(os.Stderr, "error:", err)
	os.Exit(1)
}
