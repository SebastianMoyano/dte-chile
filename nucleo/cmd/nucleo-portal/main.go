// nucleo-portal: el portal de timbraje del SII desde la terminal (nucleo/portal), lo que antes
// hacían solicitar_caf_sii.py y el MCP.
//
//	nucleo-portal empresa   --rut 77777777-7 [--ambiente certificacion]           (pública, sin certificado)
//	nucleo-portal timbrajes --rut … --tipo 33 --cert firma.pfx
//	nucleo-portal situacion --rut … [--tipos 33,61] --cert …
//	nucleo-portal software  --rut … [--ambiente produccion] --cert …
//	nucleo-portal empresas  --cert …                                              (asociadas al certificado)
//	nucleo-portal anulables --rut … --tipo 33 --cert …
//	nucleo-portal anular    --rut … --tipo 33 --desde 5 --hasta 9 --cert …        (irreversible)
//	nucleo-portal solicitar --rut … --tipo 61 [--cantidad 1] --cert … [--db dte_database.db]  (TIMBRA folios)
//
// Certificado: --cert ruta.p12 (clave por NUCLEO_CLAVE_CERTIFICADO, Llavero o prompt oculto) o
// --cert-id N (el keystore cifrado del motor, con --env/--db). La clave NUNCA va por flag. `solicitar` respeta los guardarraíles
// anti-acaparamiento del portal (tope por sesión, chequeo de bloqueo) y guarda el CAF en
// storage/cafs/ (y en la base con --db).
//
//go:debug rsa1024min=0
package main

import (
	"crypto/x509"
	"encoding/json"
	"encoding/pem"
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	"dtechile/nucleo/almacen"
	"dtechile/nucleo/cliutil"
	"dtechile/nucleo/portal"
	"dtechile/nucleo/ted"
)

func main() {
	if len(os.Args) < 2 {
		fatal(fmt.Errorf("falta el subcomando: empresa|timbrajes|situacion|software|empresas|anulables|anular|solicitar"))
	}
	cmd := os.Args[1]
	fs := flag.NewFlagSet(cmd, flag.ExitOnError)
	rut := fs.String("rut", "", "RUT de la empresa, con guión y DV")
	tipo := fs.Int("tipo", 33, "tipo de DTE")
	tipos := fs.String("tipos", "", "tipos separados por coma (situacion)")
	ambiente := fs.String("ambiente", "certificacion", "certificacion | produccion")
	certPath := fs.String("cert", os.Getenv("DTE_CERT_PATH"), ".pfx/.p12 del mandatario")
	certID := fs.Int64("cert-id", 0, "certificado del keystore del motor (en vez de --cert)")
	cuenta := fs.Int64("cuenta", 1, "cuenta dueña del keystore")
	env := fs.String("env", ".env", "archivo .env del motor (para --cert-id)")
	desde := fs.Int("desde", 0, "folio inicial (anular)")
	hasta := fs.Int("hasta", 0, "folio final (anular)")
	cantidad := fs.Int("cantidad", 1, "folios a pedir (solicitar)")
	db := fs.String("db", "", "SQLite del motor para registrar el CAF (solicitar)")
	dir := fs.String("dir", filepath.Join("storage", "cafs"), "carpeta donde guardar el CAF (solicitar)")
	jsonOut := fs.Bool("json", false, "salida en JSON")
	_ = fs.Parse(os.Args[2:])
	base := portal.BaseDe(*ambiente)

	imprimir := func(v any) {
		if *jsonOut {
			b, _ := json.MarshalIndent(v, "", " ")
			fmt.Println(string(b))
			return
		}
		b, _ := json.MarshalIndent(v, "", "  ")
		fmt.Println(string(b))
	}
	if cmd == "empresa" {
		p, _ := portal.Nuevo(nil, nil, base)
		e, err := p.ConsultarEmpresaAutorizada(*rut, "")
		if err != nil {
			fatal(err)
		}
		if e == nil {
			fmt.Printf("El RUT %s no aparece autorizado a emitir DTE en %s.\n", *rut, *ambiente)
			os.Exit(1)
		}
		imprimir(e)
		return
	}
	cert, err := cliutil.CargarCertificado(*certPath, *certID, *cuenta, *env, *db)
	if err != nil {
		fatal(fmt.Errorf("certificado: %w", err))
	}
	certPEM := pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: cert.Cert.Raw})
	keyPEM := pem.EncodeToMemory(&pem.Block{Type: "RSA PRIVATE KEY", Bytes: x509.MarshalPKCS1PrivateKey(cert.Clave)})
	p, err := portal.Nuevo(certPEM, keyPEM, base)
	if err != nil {
		fatal(err)
	}
	if _, err := p.Autenticar(""); err != nil {
		fatal(fmt.Errorf("autenticación en el SII: %w", err))
	}
	fmt.Fprintf(os.Stderr, "sesión por certificado abierta (RUT_NS %s)\n", p.RutSesion)
	switch cmd {
	case "timbrajes":
		r, err := p.ConsultarTimbrajes(*rut, *tipo)
		if err != nil {
			fatal(err)
		}
		imprimir(r)
	case "situacion":
		var ts []int
		for _, t := range strings.Split(*tipos, ",") {
			if n, err := strconv.Atoi(strings.TrimSpace(t)); err == nil {
				ts = append(ts, n)
			}
		}
		r, err := p.SituacionFolios(*rut, ts)
		if err != nil {
			fatal(err)
		}
		imprimir(r)
	case "software":
		r, err := p.DatosSoftwareDe(*rut, base)
		if err != nil {
			fatal(err)
		}
		imprimir(r)
	case "empresas":
		r, err := p.EmpresasAsociadas()
		if err != nil {
			fatal(err)
		}
		imprimir(r)
	case "anulables":
		r, err := p.ListarAnulables(*rut, *tipo)
		if err != nil {
			fatal(err)
		}
		imprimir(r)
	case "anular":
		if *desde == 0 || *hasta == 0 {
			fatal(fmt.Errorf("faltan --desde y --hasta"))
		}
		r, err := p.AnularFolios(*rut, *tipo, *desde, *hasta, "")
		if err != nil {
			fatal(err)
		}
		imprimir(r)
		if !r.OK {
			os.Exit(1)
		}
	case "solicitar":
		caf, info, err := p.SolicitarFolios(*rut, *tipo, *cantidad, true, false)
		if err != nil {
			fatal(err)
		}
		imprimir(info)
		if caf == nil {
			os.Exit(1)
		}
		_ = os.MkdirAll(*dir, 0o755)
		nombre := filepath.Join(*dir, fmt.Sprintf("CAF_%s_T%d_%d-%d_%s.xml", strings.ReplaceAll(*rut, "-", ""), *tipo, info.FolioDesde, info.FolioHasta, time.Now().Format("20060102")))
		if err := os.WriteFile(nombre, caf, 0o644); err != nil {
			fatal(err)
		}
		fmt.Printf("CAF guardado: %s (%d bytes)\n", nombre, len(caf))
		if *db != "" {
			c, err := ted.ParsearCAF(string(caf))
			if err != nil {
				fatal(err)
			}
			alm, err := almacen.AbrirYMigrar(*db)
			if err != nil {
				fatal(err)
			}
			defer alm.Cerrar()
			id, err := alm.RegistrarCAF(c.TipoDTE, c.RutEmisor, c.FolioDesde, c.FolioHasta, c.FechaAutorizacion, string(caf))
			if err != nil {
				fatal(err)
			}
			fmt.Printf("registrado en la base: id %d\n", id)
		}
	default:
		fatal(fmt.Errorf("subcomando desconocido: %s", cmd))
	}
}

func fatal(err error) {
	fmt.Fprintln(os.Stderr, "error:", err)
	os.Exit(1)
}
