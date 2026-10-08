// nucleo-valores: trae los indicadores públicos del SII (hoy: UF) y los cachea en el SQLite
// del motor. Fuente primaria oficial (SII), fallback mindicador.cl.
//
//	nucleo-valores actualizar --indicador uf --anio 2026 --db dte_database.db
//	nucleo-valores get        --indicador uf --fecha 2026-10-08 --db dte_database.db
//	nucleo-valores vigente    --indicador uf --fecha 2026-10-08 --db dte_database.db
//
// actualizar baja de la red y escribe en el cache; get/vigente solo leen el cache.
package main

import (
	"flag"
	"fmt"
	"os"
	"time"

	"dtechile/nucleo/valores"
)

func main() {
	if len(os.Args) < 2 {
		fmt.Fprintln(os.Stderr, "uso: nucleo-valores actualizar|get|vigente [opciones]")
		os.Exit(2)
	}
	fs := flag.NewFlagSet(os.Args[1], flag.ExitOnError)
	indicador := fs.String("indicador", "uf", "uf (único soportado por ahora)")
	anio := fs.Int("anio", time.Now().Year(), "año (actualizar)")
	fecha := fs.String("fecha", time.Now().Format("2006-01-02"), "fecha YYYY-MM-DD (get/vigente)")
	dbPath := fs.String("db", "dte_database.db", "ruta del SQLite del motor")
	_ = fs.Parse(os.Args[2:])

	switch os.Args[1] {
	case "actualizar":
		if *indicador != "uf" {
			fatal(fmt.Errorf("por ahora solo 'uf'"))
		}
		vs, fuente, err := valores.FetchUF(*anio)
		if err != nil {
			fatal(err)
		}
		c, err := valores.AbrirCache(*dbPath)
		if err != nil {
			fatal(err)
		}
		defer c.Cerrar()
		n, err := c.Guardar(vs)
		if err != nil {
			fatal(err)
		}
		fmt.Printf("UF %d: %d valores (fuente: %s) guardados en %s\n", *anio, n, fuente, *dbPath)

	case "get":
		c, err := valores.AbrirCache(*dbPath)
		if err != nil {
			fatal(err)
		}
		defer c.Cerrar()
		v, err := c.Get(*indicador, *fecha)
		if err != nil {
			fatal(err)
		}
		fmt.Printf("%s %s = %.2f\n", *indicador, *fecha, v)

	case "vigente":
		c, err := valores.AbrirCache(*dbPath)
		if err != nil {
			fatal(err)
		}
		defer c.Cerrar()
		v, err := c.Vigente(*indicador, *fecha)
		if err != nil {
			fatal(err)
		}
		fmt.Printf("%s vigente al %s = %.2f (fecha del valor: %s)\n", v.Indicador, *fecha, v.Valor, v.Fecha)

	default:
		fatal(fmt.Errorf("comando desconocido: %s", os.Args[1]))
	}
}

func fatal(err error) {
	fmt.Fprintln(os.Stderr, "error:", err)
	os.Exit(1)
}
