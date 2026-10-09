// nucleo-siiengine: el SII engine del núcleo (portal MIPYME del SII). PRODUCCIÓN, sin sandbox.
//
// Solo lectura (no gastan folios):
//
//	nucleo-siiengine sesion   --usuario 12.345.678-5 --empresa 77.777.777-7
//	nucleo-siiengine listar   --usuario … --empresa … [--desde 2026-01-01 --hasta 2026-12-31] [--tipo 34]
//	nucleo-siiengine importar --usuario … --empresa … --db dte_chile.db [--sin-pdf] [--xml] [--storage storage]
//
// Emisión (dry-run por defecto: abre sesión, valida, arma el payload y muestra el resumen;
// --emitir gasta el folio; --guardar lo registra en --db; mientras el tipo no esté en
// CadenasVerificadas de Go exige --acepto-riesgo-folio):
//
//	nucleo-siiengine factura    --usuario … --empresa … --receptor 76.111.111-6 --razon "CLIENTE SPA" --giro SALUD \
//	                            --dir "CAMINO 1" --ciudad Chillan --comuna CHILLAN --glosa Arriendo --precio 1000 \
//	                            [--detalle "…"] [--fecha 2026-10-08] [--forma-pago 1] [--emitir --acepto-riesgo-folio --guardar --db …]
//	nucleo-siiengine nc-anular  … --dhdr <DHDR> --tipo-ref 34 --folio-ref 63 --fecha-ref 2026-10-08 (mismos ítems que el documento)
//	nucleo-siiengine nc-corregir … --dhdr <DHDR> --tipo-ref 34 --folio-ref 57 --fecha-ref 2026-09-06 (código 3, hasta 3 líneas)
//
// --trazas <dir> guarda las páginas crudas del dry-run (form, vista previa) como fixtures.
//
// Claves (nunca por argumento): NUCLEO_CLAVE_TRIBUTARIA y NUCLEO_CLAVE_CERTIFICADO, o el
// Llavero de macOS (servicios sii-clave-tributaria y sii-clave-certificado, cuenta = RUT sin
// puntos con DV; los mismos que emitir_mipyme.py). La del certificado hace falta con --xml,
// con las notas (guardarraíl del total) y con --emitir.
package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"

	"dtechile/nucleo/almacen"
	"dtechile/nucleo/siiengine"
)

var camposClave = []string{"PTDC_CODIGO", "EHDR_CODIGO", "PTES_ESTADO", "EFXP_DOC_REF_RAIZ", "ES_BORR", "EFXP_FMA_PAGO",
	"EFXP_FCH_EMIS", "EFXP_NMB_01", "EFXP_QTY_01", "EFXP_PRC_01", "EFXP_SUBT_01", "EFXP_DSC_ITEM_01", "EFXP_SUBTOTAL",
	"EFXP_MNT_NETO", "EFXP_MNT_TOTAL", "EFXP_TPO_DOC_REF_001", "EFXP_FOLIO_REF_001", "EFXP_FCH_REF_001",
	"EFXP_CODIGO_REF_001", "EFXP_RAZON_REF_001"}

func main() {
	if len(os.Args) < 2 {
		fmt.Fprintln(os.Stderr, "uso: nucleo-siiengine sesion|listar|importar|factura|nc-anular|nc-corregir [opciones]")
		os.Exit(2)
	}
	cmd := os.Args[1]
	fs := flag.NewFlagSet(cmd, flag.ExitOnError)
	usuario := fs.String("usuario", "", "RUT (con DV) de quien entra al SII")
	empresa := fs.String("empresa", "", "RUT (con DV) de la empresa a operar")
	desde := fs.String("desde", "", "YYYY-MM-DD (listar/importar)")
	hasta := fs.String("hasta", "", "YYYY-MM-DD (listar/importar)")
	tipo := fs.String("tipo", "", "filtro de tipo del portal (listar)")
	db := fs.String("db", "", "SQLite del motor (importar, --guardar)")
	sinPDF := fs.Bool("sin-pdf", false, "no bajar PDF (importar)")
	conXML := fs.Bool("xml", false, "bajar también el XML por firma central (importar; exige la clave del certificado)")
	storage := fs.String("storage", "storage", "raíz de storage (PDF, XML, evidencia)")
	trazas := fs.String("trazas", "", "carpeta donde dejar las páginas crudas del dry-run (fixtures)")
	// emisión
	receptor := fs.String("receptor", "", "RUT del receptor (con DV)")
	razon := fs.String("razon", "", "razón social del receptor")
	giro := fs.String("giro", "", "giro del receptor")
	dir := fs.String("dir", "", "dirección del receptor")
	ciudad := fs.String("ciudad", "", "ciudad del receptor")
	comuna := fs.String("comuna", "", "comuna del receptor")
	glosa := fs.String("glosa", "", "nombre del ítem")
	precio := fs.Int64("precio", 0, "precio del ítem (total con cantidad 1)")
	detalle := fs.String("detalle", "", "descripción del ítem")
	fecha := fs.String("fecha", "", "fecha de emisión YYYY-MM-DD (hoy)")
	formaPago := fs.String("forma-pago", "1", "1 contado (lo habitual), 2 crédito")
	dhdr := fs.String("dhdr", "", "DHDR_CODIGO del documento a anular/corregir")
	tipoRef := fs.Int("tipo-ref", 34, "tipo del documento referenciado")
	folioRef := fs.Int("folio-ref", 0, "folio del documento referenciado")
	fechaRef := fs.String("fecha-ref", "", "fecha del documento referenciado YYYY-MM-DD")
	sinVerificar := fs.Bool("sin-verificar-monto", false, "apaga el guardarraíl del total registrado (NO recomendado)")
	emitir := fs.Bool("emitir", false, "emitir de verdad (gasta el folio)")
	riesgo := fs.Bool("acepto-riesgo-folio", false, "emitir aunque la cadena no esté verificada desde Go")
	guardar := fs.Bool("guardar", false, "registrar el documento emitido en --db y guardar el PDF")
	_ = fs.Parse(os.Args[2:])
	if *usuario == "" || *empresa == "" {
		fatal(fmt.Errorf("faltan --usuario y --empresa"))
	}
	esEmision := cmd == "factura" || cmd == "nc-anular" || cmd == "nc-corregir"
	necesitaCert := *conXML || *emitir || (esEmision && cmd != "factura")
	claveTrib := clave("NUCLEO_CLAVE_TRIBUTARIA", "sii-clave-tributaria", *usuario)
	if claveTrib == "" {
		fatal(fmt.Errorf("sin clave tributaria: exporta NUCLEO_CLAVE_TRIBUTARIA o guárdala en el Llavero:\n  security add-generic-password -s sii-clave-tributaria -a %s", siiengine.FormatearRut(*usuario, false)))
	}
	claveCert := ""
	if necesitaCert {
		if claveCert = clave("NUCLEO_CLAVE_CERTIFICADO", "sii-clave-certificado", *usuario); claveCert == "" {
			fatal(fmt.Errorf("este comando exige la clave del certificado: NUCLEO_CLAVE_CERTIFICADO o el Llavero (sii-clave-certificado)"))
		}
	}

	cli, err := siiengine.Nuevo(*usuario, claveTrib, claveCert)
	if err != nil {
		fatal(err)
	}
	cli.RaizStorage = *storage
	cli.Log = func(f string, a ...any) { fmt.Fprintf(os.Stderr, f+"\n", a...) }
	if *trazas != "" {
		cli.Trazas = map[string]string{}
	}
	defer func() {
		if err := cli.Cerrar(); err != nil {
			fmt.Fprintln(os.Stderr, "aviso:", err)
		}
		if *trazas != "" {
			os.MkdirAll(*trazas, 0o755)
			for nombre, contenido := range cli.Trazas {
				b, _ := siiengine.ABytesLatin1(contenido)
				os.WriteFile(filepath.Join(*trazas, nombre), b, 0o644)
			}
			fmt.Fprintf(os.Stderr, "trazas: %d página(s) en %s\n", len(cli.Trazas), *trazas)
		}
	}()
	t0 := time.Now()
	if err := cli.IniciarSesion(); err != nil {
		fatal(err)
	}
	if err := cli.SeleccionarEmpresa(*empresa); err != nil {
		fatal(err)
	}
	fmt.Fprintf(os.Stderr, "SII engine → PRODUCCIÓN. Usuario %s, empresa %s (sesión en %s)\n",
		cli.RutUsuario, cli.Empresa, time.Since(t0).Round(time.Millisecond))

	switch cmd {
	case "sesion":
		form, err := cli.LeerForm(siiengine.TipoFacturaExenta)
		if err != nil {
			fatal(err)
		}
		campos := form.Campos
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
			ConPDF: !*sinPDF, ConXML: *conXML, Carpeta: *storage, Pausa: 500 * time.Millisecond})
		if err != nil {
			fatal(err)
		}
		imprimir(res)
	case "factura", "nc-anular", "nc-corregir":
		if *receptor == "" || *razon == "" || *glosa == "" || *precio <= 0 {
			fatal(fmt.Errorf("faltan --receptor, --razon, --glosa o --precio"))
		}
		rec := siiengine.Receptor{Rut: *receptor, RazonSocial: *razon, Giro: *giro, Direccion: *dir, Ciudad: *ciudad, Comuna: *comuna}
		items := []siiengine.Item{{Nombre: *glosa, Precio: *precio, Cantidad: 1, Descripcion: *detalle}}
		var p *siiengine.Payload
		switch cmd {
		case "factura":
			p, err = cli.Preparar(siiengine.TipoFacturaExenta, rec, items, *fecha, *formaPago)
		case "nc-anular":
			if *dhdr == "" || *folioRef == 0 || *fechaRef == "" {
				fatal(fmt.Errorf("nc-anular exige --dhdr, --folio-ref y --fecha-ref"))
			}
			p, err = cli.PrepararNCAnulacion(*dhdr, *tipoRef, *folioRef, *fechaRef, rec, items, *fecha, !*sinVerificar)
		case "nc-corregir":
			if *dhdr == "" || *folioRef == 0 || *fechaRef == "" {
				fatal(fmt.Errorf("nc-corregir exige --dhdr, --folio-ref y --fecha-ref"))
			}
			p, err = cli.PrepararNCCorreccionMontos(*dhdr, *tipoRef, *folioRef, *fechaRef, rec, items, *fecha, !*sinVerificar)
		}
		if err != nil {
			fatal(err)
		}
		if cli.Trazas != nil {
			if b, err := siiengine.CodificarLatin1(p.Pares); err == nil {
				cli.Trazas["body_genxml.txt"] = string(b)
			}
		}
		fmt.Fprintf(os.Stderr, "\nTipo %d | receptor %s %s | total $%d | %d campos\n", p.Tipo, siiengine.FormatearRut(rec.Rut, false), rec.RazonSocial, p.MontoTotal(), len(p.Pares))
		if len(p.CamposNuevos) > 0 {
			fmt.Fprintf(os.Stderr, "⚠️ el form del SII trae campos que el schema no conoce: %v\n", p.CamposNuevos)
		}
		fmt.Fprintln(os.Stderr, "Campos clave del documento:")
		for _, k := range camposClave {
			fmt.Fprintf(os.Stderr, "  %-24s = %q\n", k, p.Valor(k))
		}
		if !*emitir {
			fmt.Fprintln(os.Stderr, "\n[DRY-RUN] no se emitió nada. Agrega --emitir para gastar el folio y emitir.")
			return
		}
		res, err := cli.Emitir(p, siiengine.OpcionesEmitir{Confirmar: true, ConPDF: true, AceptarRiesgoFolio: *riesgo})
		if err != nil {
			fatal(err)
		}
		salida := map[string]any{"tipo": res.Tipo, "folio": res.Folio, "dhdr": res.DHDR, "monto_total": res.MontoTotal}
		if res.PDF != nil {
			ruta := filepath.Join(*storage, "pdfs", fmt.Sprintf("mipyme_T%d_F%d_%s.pdf", res.Tipo, res.Folio, fechaEmision(p)))
			os.MkdirAll(filepath.Dir(ruta), 0o755)
			if err := os.WriteFile(ruta, res.PDF, 0o644); err == nil {
				salida["pdf"] = ruta
			}
		}
		if *guardar {
			if *db == "" {
				fatal(fmt.Errorf("--guardar exige --db"))
			}
			al, err := almacen.Abrir(*db)
			if err != nil {
				fatal(err)
			}
			defer al.Cerrar()
			id, err := siiengine.RegistrarEnBD(al, res, *empresa, rec, fechaEmision(p))
			if err != nil {
				fatal(err)
			}
			if ruta, ok := salida["pdf"].(string); ok {
				al.GuardarPDF(id, ruta)
			}
			salida["db_id"] = id
		}
		fmt.Fprintf(os.Stderr, "\n✅ EMITIDO: tipo %d folio %d DHDR=%s\n", res.Tipo, res.Folio, res.DHDR)
		imprimir(salida)
	default:
		fatal(fmt.Errorf("comando desconocido: %s", cmd))
	}
}

func fechaEmision(p *siiengine.Payload) string {
	if f := p.Valor("EFXP_FCH_EMIS"); f != "" {
		return f
	}
	return time.Now().Format("2006-01-02")
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
