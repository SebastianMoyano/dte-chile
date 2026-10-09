// nucleo-siiengine: el SII engine del núcleo (portal MIPYME del SII), segmento 1: sesión y
// lectura. PRODUCCIÓN, solo lectura: nada de lo que hace gasta folios.
//
//	nucleo-siiengine sesion   --usuario 12.345.678-5 --empresa 77.777.777-7
//	nucleo-siiengine listar   --usuario … --empresa … [--desde 2026-01-01 --hasta 2026-12-31] [--tipo 34]
//	nucleo-siiengine importar --usuario … --empresa … --db dte_chile.db [--sin-pdf] [--xml] [--carpeta storage]
//
// Claves (nunca por argumento): variables NUCLEO_CLAVE_TRIBUTARIA y NUCLEO_CLAVE_CERTIFICADO,
// o el Llavero de macOS (servicios `sii-clave-tributaria` y `sii-clave-certificado`, cuenta =
// RUT sin puntos con DV; los mismos que usa emitir_mipyme.py). La del certificado solo hace
// falta con --xml.
package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"os/exec"
	"strings"
	"time"

	"dtechile/nucleo/almacen"
	"dtechile/nucleo/siiengine"
)

func main() {
	if len(os.Args) < 2 {
		fmt.Fprintln(os.Stderr, "uso: nucleo-siiengine sesion|listar|importar [opciones]")
		os.Exit(2)
	}
	cmd := os.Args[1]
	fs := flag.NewFlagSet(cmd, flag.ExitOnError)
	usuario := fs.String("usuario", "", "RUT (con DV) de quien entra al SII")
	empresa := fs.String("empresa", "", "RUT (con DV) de la empresa a operar")
	desde := fs.String("desde", "", "YYYY-MM-DD (listar/importar)")
	hasta := fs.String("hasta", "", "YYYY-MM-DD (listar/importar)")
	tipo := fs.String("tipo", "", "filtro de tipo del portal (listar)")
	db := fs.String("db", "", "SQLite del motor (importar)")
	sinPDF := fs.Bool("sin-pdf", false, "no bajar PDF (importar)")
	conXML := fs.Bool("xml", false, "bajar también el XML por firma central (importar; exige la clave del certificado)")
	carpeta := fs.String("carpeta", "storage", "raíz de storage para PDF y XML (importar)")
	_ = fs.Parse(os.Args[2:])
	if *usuario == "" || *empresa == "" {
		fatal(fmt.Errorf("faltan --usuario y --empresa"))
	}
	claveTrib := clave("NUCLEO_CLAVE_TRIBUTARIA", "sii-clave-tributaria", *usuario)
	if claveTrib == "" {
		fatal(fmt.Errorf("sin clave tributaria: exporta NUCLEO_CLAVE_TRIBUTARIA o guárdala en el Llavero:\n  security add-generic-password -s sii-clave-tributaria -a %s", siiengine.FormatearRut(*usuario, false)))
	}
	claveCert := ""
	if *conXML {
		if claveCert = clave("NUCLEO_CLAVE_CERTIFICADO", "sii-clave-certificado", *usuario); claveCert == "" {
			fatal(fmt.Errorf("--xml exige la clave del certificado: NUCLEO_CLAVE_CERTIFICADO o el Llavero (sii-clave-certificado)"))
		}
	}

	cli, err := siiengine.Nuevo(*usuario, claveTrib, claveCert)
	if err != nil {
		fatal(err)
	}
	defer func() {
		if err := cli.Cerrar(); err != nil {
			fmt.Fprintln(os.Stderr, "aviso:", err)
		}
	}()
	t0 := time.Now()
	if err := cli.IniciarSesion(); err != nil {
		fatal(err)
	}
	if err := cli.SeleccionarEmpresa(*empresa); err != nil {
		fatal(err)
	}
	fmt.Fprintf(os.Stderr, "SII engine → PRODUCCIÓN, solo lectura. Usuario %s, empresa %s (sesión en %s)\n",
		cli.RutUsuario, cli.Empresa, time.Since(t0).Round(time.Millisecond))

	switch cmd {
	case "sesion":
		campos, err := cli.LeerForm(siiengine.TipoFacturaExenta)
		if err != nil {
			fatal(err)
		}
		imprimir(map[string]any{
			"ambiente": "produccion",
			"emisor_segun_portal": map[string]string{"razon_social": campos["EFXP_RZN_SOC"], "giro": campos["EFXP_GIRO_EMIS"],
				"acteco": campos["EFXP_ACTECO"], "comuna": campos["EFXP_CMNA_ORIGEN"], "ciudad": campos["EFXP_CIUDAD_ORIGEN"]},
			"form":    map[string]int{"campos_en_html": len(campos)},
			"menu":    cli.ResumenMenu(),
			"enlaces": len(cli.EnlacesMenu()),
			"nota":    "Solo lectura en el SII: sesión comprobada y form leído. Nada se emitió.",
		})
	case "listar":
		docs, err := cli.ListarEmitidos(*tipo, *desde, *hasta)
		if err != nil {
			fatal(err)
		}
		imprimir(docs)
	case "importar":
		if *db == "" {
			fatal(fmt.Errorf("importar exige --db"))
		}
		al, err := almacen.Abrir(*db)
		if err != nil {
			fatal(err)
		}
		defer al.Cerrar()
		docs, err := cli.ListarEmitidos("", *desde, *hasta)
		if err != nil {
			fatal(err)
		}
		res, err := siiengine.Importar(cli, al, *empresa, docs, siiengine.OpcionesImportar{
			ConPDF: !*sinPDF, ConXML: *conXML, Carpeta: *carpeta, Pausa: 500 * time.Millisecond})
		if err != nil {
			fatal(err)
		}
		imprimir(res)
	default:
		fatal(fmt.Errorf("comando desconocido: %s", cmd))
	}
}

// clave busca primero la variable de entorno y después el Llavero de macOS (como
// core/sii_mipyme.py::clave_desde_llavero). Nunca se imprime.
func clave(env, servicio, rut string) string {
	if v := os.Getenv(env); v != "" {
		return v
	}
	if _, err := exec.LookPath("security"); err != nil {
		return ""
	}
	out, err := exec.Command("security", "find-generic-password", "-s", servicio, "-a", siiengine.FormatearRut(rut, false), "-w").Output()
	if err != nil {
		return ""
	}
	return strings.TrimSpace(string(out))
}

func imprimir(v any) {
	enc := json.NewEncoder(os.Stdout)
	enc.SetIndent("", "  ")
	enc.SetEscapeHTML(false)
	if err := enc.Encode(v); err != nil {
		fatal(err)
	}
}

func fatal(err error) {
	fmt.Fprintln(os.Stderr, "error:", err)
	os.Exit(1)
}
