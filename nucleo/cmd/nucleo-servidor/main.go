// nucleo-servidor: el motor HTTP en Go (fase 7 del port).
//
//	nucleo-servidor servir  [--puerto 8010] [--env .env] [--db ruta.db] [--motor http://127.0.0.1:8000] [--app app/frontend/dist]
//	nucleo-servidor migrar  [--env .env] [--db ruta.db]        aplica las migraciones pendientes y muestra la versión
//
// Atiende con el mismo contrato que el motor Python (/api/v1/…); lo que aún no está portado se
// reenvía a --motor. Sin --motor, esas rutas responden 503. Las rutas portadas se comparan
// contra Python con tools/contrato_api.py. Secretos: del .env y del entorno, nunca por flag.
package main

import (
	"flag"
	"fmt"
	"log"
	"net/http"
	"os"

	"dtechile/nucleo/almacen"
	"dtechile/nucleo/servidor"
)

func main() {
	cmd := "servir"
	args := os.Args[1:]
	if len(args) > 0 && (args[0] == "servir" || args[0] == "migrar" || args[0] == "rotar-claves") {
		cmd, args = args[0], args[1:]
	}
	fs := flag.NewFlagSet(cmd, flag.ExitOnError)
	puerto := fs.Int("puerto", 8010, "puerto de escucha")
	env := fs.String("env", ".env", "archivo .env del motor")
	db := fs.String("db", "", "SQLite (si no, DATABASE_URL del .env)")
	motor := fs.String("motor", "http://127.0.0.1:8000", "motor Python para reenviar lo no portado (vacío = sin reenvío)")
	app := fs.String("app", "", "carpeta de la interfaz (default: app/frontend/dist si existe)")
	_ = fs.Parse(args)

	cfg, err := servidor.CargarConfig(*env)
	if err != nil {
		fatal(err)
	}
	if *db != "" {
		cfg.DatabasePath = *db
	}
	if cmd == "migrar" {
		alm, err := almacen.Abrir(cfg.DatabasePath)
		if err != nil {
			fatal(err)
		}
		defer alm.Cerrar()
		aplicadas, err := alm.Migrar()
		if err != nil {
			fatal(err)
		}
		v, _ := alm.VersionEsquema()
		fmt.Printf("base %s: esquema versión %d (aplicadas ahora: %v)\n", cfg.DatabasePath, v, aplicadas)
		return
	}
	if cmd == "rotar-claves" {
		// rotar_claves.py: re-cifra certificados y claves del SII con una DTE_MASTER_KEY nueva,
		// renueva JWT_SECRET_KEY, acota CORS y resetea la clave de admin (ADMIN_PASSWORD o aleatoria).
		cfg.RVDSchedulerActivo = false
		s, err := servidor.Nuevo(cfg)
		if err != nil {
			fatal(err)
		}
		defer s.Cerrar()
		admin, err := s.RotarClaves(*env, os.Getenv("ADMIN_PASSWORD"))
		if err != nil {
			fatal(err)
		}
		fmt.Println("ENDURECIMIENTO COMPLETO")
		fmt.Printf("  Contraseña de admin (guárdala, se muestra 1 vez): %s\n", admin)
		fmt.Printf("  JWT y master key nuevos escritos en %s (los tokens viejos ya no valen). Reinicia el motor.\n", *env)
		return
	}
	cfg.MotorPython = *motor
	cfg.CarpetaApp = *app
	if cfg.CarpetaApp == "" {
		cfg.CarpetaApp = servidor.RutaApp(".")
	}
	s, err := servidor.Nuevo(cfg)
	if err != nil {
		fatal(err)
	}
	defer s.Cerrar()
	log.Printf("motor Go en http://127.0.0.1:%d (base %s; reenvío a %q; app en %q)", *puerto, cfg.DatabasePath, cfg.MotorPython, cfg.CarpetaApp)
	if err := http.ListenAndServe(fmt.Sprintf("127.0.0.1:%d", *puerto), s.Handler()); err != nil {
		fatal(err)
	}
}

func fatal(err error) {
	fmt.Fprintln(os.Stderr, "error:", err)
	os.Exit(1)
}
