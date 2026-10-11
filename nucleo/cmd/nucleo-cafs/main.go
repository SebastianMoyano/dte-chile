// nucleo-cafs: los CAF de la base, como load_cafs.py.
//
//	nucleo-cafs listar [--db dte_database.db]
//	nucleo-cafs cargar [--dir storage/cafs] [--db dte_database.db]   (salta los ya cargados)
package main

import (
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"sort"

	"dtechile/nucleo/almacen"
	"dtechile/nucleo/ted"
)

func main() {
	cmd := "listar"
	args := os.Args[1:]
	if len(args) > 0 && (args[0] == "listar" || args[0] == "cargar") {
		cmd, args = args[0], args[1:]
	}
	fs := flag.NewFlagSet(cmd, flag.ExitOnError)
	db := fs.String("db", "dte_database.db", "SQLite del motor")
	dir := fs.String("dir", filepath.Join("storage", "cafs"), "carpeta con los CAF (xml)")
	_ = fs.Parse(args)
	alm, err := almacen.AbrirYMigrar(*db)
	if err != nil {
		fatal(err)
	}
	defer alm.Cerrar()
	tabla := func(titulo string) {
		rows, err := alm.DB().Query(`SELECT id, rut_emisor, tipo_dte, folio_desde, folio_hasta, folio_siguiente, activo FROM cafs ORDER BY id`)
		if err != nil {
			fatal(err)
		}
		defer rows.Close()
		fmt.Printf("\n%s\n%-4s  %-12s %5s  %6s  %6s  %6s  %s\n", titulo, "ID", "RUT", "TIPO", "DESDE", "HASTA", "SIG", "ACTIVO")
		n := 0
		for rows.Next() {
			var id, tipo, desde, hasta, sig, activo int
			var rut string
			if err := rows.Scan(&id, &rut, &tipo, &desde, &hasta, &sig, &activo); err == nil {
				fmt.Printf("%-4d  %-12s %5d  %6d  %6d  %6d  %d\n", id, rut, tipo, desde, hasta, sig, activo)
				n++
			}
		}
		if n == 0 {
			fmt.Println("  (vacío)")
		}
	}
	if cmd == "listar" {
		tabla("CAF EN LA BASE")
		return
	}
	archivos, _ := filepath.Glob(filepath.Join(*dir, "*.xml"))
	sort.Strings(archivos)
	if len(archivos) == 0 {
		fatal(fmt.Errorf("no hay *.xml en %s", *dir))
	}
	tabla("ESTADO ANTES DE LA CARGA")
	ins, salt := 0, 0
	for _, a := range archivos {
		b, err := os.ReadFile(a)
		if err != nil {
			fmt.Printf("✗ %s: %v\n", filepath.Base(a), err)
			continue
		}
		c, err := ted.ParsearCAF(string(b))
		if err != nil {
			fmt.Printf("✗ %s: %v\n", filepath.Base(a), err)
			continue
		}
		var id int64
		if err := alm.DB().QueryRow(`SELECT id FROM cafs WHERE rut_emisor=? AND tipo_dte=? AND folio_desde=?`, c.RutEmisor, c.TipoDTE, c.FolioDesde).Scan(&id); err == nil {
			fmt.Printf("· %s: T%d %d-%d de %s ya está (id %d)\n", filepath.Base(a), c.TipoDTE, c.FolioDesde, c.FolioHasta, c.RutEmisor, id)
			salt++
			continue
		}
		id, err = alm.RegistrarCAF(c.TipoDTE, c.RutEmisor, c.FolioDesde, c.FolioHasta, c.FechaAutorizacion, string(b))
		if err != nil {
			fmt.Printf("✗ %s: %v\n", filepath.Base(a), err)
			continue
		}
		fmt.Printf("✓ %s: T%d %d-%d de %s (FA %s) → id %d\n", filepath.Base(a), c.TipoDTE, c.FolioDesde, c.FolioHasta, c.RutEmisor, c.FechaAutorizacion, id)
		ins++
	}
	tabla("ESTADO DESPUÉS DE LA CARGA")
	fmt.Printf("\ninsertados %d, saltados %d\n", ins, salt)
}

func fatal(err error) {
	fmt.Fprintln(os.Stderr, "error:", err)
	os.Exit(1)
}
