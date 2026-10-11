// nucleo-rvd: el Registro de Ventas Diario (ConsumoFolios) de boletas desde la terminal.
//
//	nucleo-rvd --rut 77777777-7 --dia 2026-01-23 --cert firma.pfx [--db dte_database.db] [--ambiente certificacion]
//	nucleo-rvd --rut … --dia … --cert-id 2 [--cuenta 1] [--env .env]      (certificado del keystore)
//	nucleo-rvd … --enviar          (lo sube por DTEUpload al ambiente elegido y lo registra en rvd_envios)
//
// Sin --enviar solo genera, valida contra el XSD y escribe storage/rvd/RVD_<rut>_<dia>.xml. En
// certificación no tiene efecto tributario; en producción es el reporte obligatorio del día.
// La clave del certificado: NUCLEO_CLAVE_CERTIFICADO o el Llavero.
//
//go:debug rsa1024min=0
package main

import (
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"

	"dtechile/nucleo/almacen"
	"dtechile/nucleo/cliutil"
	"dtechile/nucleo/rvd"
	"dtechile/nucleo/sii"
)

func main() {
	rut := flag.String("rut", "", "RUT del emisor, con guión y DV")
	dia := flag.String("dia", time.Now().AddDate(0, 0, -1).Format("2006-01-02"), "día reportado (YYYY-MM-DD; default ayer)")
	certPath := flag.String("cert", os.Getenv("DTE_CERT_PATH"), ".pfx/.p12 del mandatario")
	certID := flag.Int64("cert-id", 0, "certificado del keystore del motor (en vez de --cert)")
	cuenta := flag.Int64("cuenta", 1, "cuenta dueña del keystore")
	env := flag.String("env", ".env", "archivo .env del motor (para --cert-id)")
	db := flag.String("db", "dte_database.db", "SQLite del motor (boletas del día y rvd_envios)")
	ambiente := flag.String("ambiente", "certificacion", "certificacion | produccion")
	resol := flag.String("resolucion", "", "fecha:numero de la resolución (default según ambiente)")
	salida := flag.String("salida", filepath.Join("storage", "rvd"), "carpeta del XML")
	enviar := flag.Bool("enviar", false, "subir por DTEUpload y registrar")
	sec := flag.Int("sec", 1, "SecEnvio (para corregir, +1 y se reenvía completo)")
	flag.Parse()
	if *rut == "" {
		fatal(fmt.Errorf("falta --rut"))
	}
	cert, err := cliutil.CargarCertificado(*certPath, *certID, *cuenta, *env, *db)
	if err != nil {
		fatal(fmt.Errorf("certificado: %w", err))
	}
	rutEnvia, err := cert.RutEmisor()
	if err != nil {
		fatal(err)
	}
	alm, err := almacen.AbrirYMigrar(*db)
	if err != nil {
		fatal(err)
	}
	defer alm.Cerrar()
	docs, err := rvd.BoletasDelDia(alm.DB(), *rut, *dia, *ambiente)
	if err != nil {
		fatal(err)
	}
	// Resolución POR EMPRESA (la cacheada del registro del SII, como el servidor); si no, la del ambiente.
	fecha, num := "2026-07-08", 0
	if *ambiente == "produccion" {
		fecha, num = "2014-08-22", 80
	}
	var fc string
	var nc int
	if err := alm.DB().QueryRow(`SELECT fecha_iso, numero FROM resolucion_cache WHERE rut=? AND ambiente=?`, *rut, *ambiente).Scan(&fc, &nc); err == nil {
		fecha, num = fc, nc
	}
	if *resol != "" {
		f, n, _ := strings.Cut(*resol, ":")
		fecha = f
		fmt.Sscan(n, &num)
	}
	xml, err := rvd.GenerarFirmado(cert, rvd.Parametros{RutEmisor: *rut, RutEnvia: rutEnvia, FechaResolucion: fecha, NumeroResolucion: num,
		Dia: *dia, Tipos: rvd.TiposConsumo, SecEnvio: *sec, Marca: time.Now().Format("2006-01-02T15:04:05"), Documentos: docs})
	if err != nil {
		fatal(err)
	}
	_ = os.MkdirAll(*salida, 0o755)
	ruta := filepath.Join(*salida, fmt.Sprintf("RVD_%s_%s.xml", *rut, *dia))
	if err := os.WriteFile(ruta, xml, 0o644); err != nil {
		fatal(err)
	}
	fmt.Printf("RVD de %s para %s: %d boleta(s) del día, XSD válido → %s (%d bytes)\n", *rut, *dia, len(docs), ruta, len(xml))
	if !*enviar {
		_ = rvd.Registrar(alm.DB(), *rut, *dia, "generado", *sec, "", ruta, "Generado por nucleo-rvd (sin enviar).")
		return
	}
	cli, err := sii.Nuevo(*ambiente, cert)
	if err != nil {
		fatal(err)
	}
	track, _, err := rvd.Enviar(cli, xml, *rut)
	if err != nil {
		_ = rvd.Registrar(alm.DB(), *rut, *dia, "generado", *sec, "", ruta, err.Error())
		fatal(fmt.Errorf("generado pero NO enviado: %w", err))
	}
	_ = rvd.Registrar(alm.DB(), *rut, *dia, "enviado", *sec, fmt.Sprint(track), ruta, fmt.Sprintf("Enviado por DTEUpload (%s).", *ambiente))
	fmt.Printf("📤 enviado por DTEUpload (%s) → TrackID %d. Consulta el veredicto con: nucleo-sii estado --track %d --rut %s --ambiente %s --cert …\n", *ambiente, track, track, *rut, *ambiente)
}

func fatal(err error) {
	fmt.Fprintln(os.Stderr, "error:", err)
	os.Exit(1)
}
