// nucleo-valores: trae los indicadores públicos del SII (UF, UTM, dólar) y los cachea en el
// SQLite del motor. Fuente primaria oficial (SII), fallback mindicador.cl.
//
//	nucleo-valores actualizar --indicador todos --anio 2026 --db dte_database.db
//	nucleo-valores get        --indicador uf --fecha 2026-10-08 --db dte_database.db
//	nucleo-valores vigente    --indicador uf --fecha 2026-10-08 --db dte_database.db
//	nucleo-valores demonio    --cada 24h --db dte_database.db
//
// actualizar/demonio bajan de la red y escriben en el cache; get/vigente solo leen. demonio es
// el refresco diario in-process (sin cron): refresca al arrancar y cada `--cada`, no muere ante
// un fallo de red. Corre donde corra el binario (p. ej. junto al servidor).
package main

import (
	"flag"
	"fmt"
	"log"
	"os"
	"time"

	"dtechile/nucleo/valores"
)

// refrescar baja los indicadores del año y los guarda; registra cada uno y nunca corta por un
// fallo de un indicador (sigue con los demás).
func refrescar(dbPath string, anio int, inds []string, logf func(string, ...any)) {
	c, err := valores.AbrirCache(dbPath)
	if err != nil {
		logf("valores: no se pudo abrir %s: %v", dbPath, err)
		return
	}
	defer c.Cerrar()
	for _, ind := range inds {
		vs, fuente, err := valores.Fetch(ind, anio)
		if err != nil {
			logf("valores: %s %d falló: %v", ind, anio, err)
			continue
		}
		n, err := c.Guardar(vs)
		if err != nil {
			logf("valores: %s %d no se guardó: %v", ind, anio, err)
			continue
		}
		logf("valores: %s %d → %d valores (fuente: %s)", ind, anio, n, fuente)
	}
}

func main() {
	if len(os.Args) < 2 {
		fmt.Fprintln(os.Stderr, "uso: nucleo-valores actualizar|get|vigente [opciones]")
		os.Exit(2)
	}
	fs := flag.NewFlagSet(os.Args[1], flag.ExitOnError)
	indicador := fs.String("indicador", "uf", "uf | utm | dolar | todos")
	anio := fs.Int("anio", time.Now().Year(), "año (actualizar)")
	fecha := fs.String("fecha", time.Now().Format("2006-01-02"), "fecha YYYY-MM-DD (get/vigente)")
	dbPath := fs.String("db", "dte_database.db", "ruta del SQLite del motor")
	cada := fs.Duration("cada", 24*time.Hour, "intervalo de refresco (demonio)")
	_ = fs.Parse(os.Args[2:])

	resolverInds := func() []string {
		if *indicador == "todos" {
			return []string{"uf", "utm", "dolar"}
		}
		return []string{*indicador}
	}

	switch os.Args[1] {
	case "actualizar":
		refrescar(*dbPath, *anio, resolverInds(), func(f string, a ...any) { fmt.Printf(f+"\n", a...) })

	case "demonio":
		inds := []string{"uf", "utm", "dolar"}
		log.Printf("nucleo-valores demonio: refresco cada %s en %s", *cada, *dbPath)
		for {
			// El año se recalcula cada vuelta para cubrir el cambio de año sin reiniciar.
			refrescar(*dbPath, time.Now().Year(), inds, log.Printf)
			time.Sleep(*cada)
		}

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
