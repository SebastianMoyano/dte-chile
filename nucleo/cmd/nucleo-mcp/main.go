// nucleo-mcp: el servidor MCP del motor (mcp_server.py) en Go, y el instalador que lo enchufa
// en los clientes de IA del computador. El motor corre EN ESTE PROCESO (nucleo/mcp.Arrancar):
// no necesita la app ni un servidor andando, y comparte la carpeta de datos de la app.
//
//	nucleo-mcp                                     stdio (JSON-RPC por líneas): lo que lanzan los clientes
//	nucleo-mcp --env /ruta/.env [--db …]           ídem, con un .env concreto (sin --env: ./.env o la carpeta de datos)
//	MCP_AUTH_TOKEN=secreto nucleo-mcp --http 127.0.0.1:8090   HTTP: POST /mcp con Authorization: Bearer
//
//	nucleo-mcp clientes [--json]                   qué clientes de IA hay en esta máquina y cuáles ya tienen el motor
//	nucleo-mcp instalar --en claude-code           escribe la entrada en la configuración de ese cliente
//	nucleo-mcp instalar --en todos                 en todos los que estén instalados
//	nucleo-mcp instalar --en cursor --quitar       la saca
//
// Clientes: claude-code, claude-desktop, cursor, vscode, windsurf, gemini, codex.
//
//go:debug rsa1024min=0
package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"log"
	"net/http"
	"os"
	"path/filepath"
	"runtime"

	"dtechile/nucleo/conectores"
	"dtechile/nucleo/mcp"
)

func main() {
	log.SetOutput(os.Stderr)
	if len(os.Args) > 1 {
		switch os.Args[1] {
		case "clientes":
			os.Exit(cmdClientes(os.Args[2:]))
		case "instalar":
			os.Exit(cmdInstalar(os.Args[2:]))
		}
	}
	env := flag.String("env", "", "archivo .env del motor (sin él: ./.env, o la carpeta de datos de la app)")
	db := flag.String("db", "", "SQLite (si no, DATABASE_URL del .env)")
	httpAddr := flag.String("http", "", "escuchar por HTTP (host:puerto); exige Authorization: Bearer")
	flag.Parse()
	m, cerrar, err := mcp.Arrancar(*env, *db)
	if err != nil {
		log.Fatal(err)
	}
	defer cerrar()
	if *httpAddr != "" {
		token := os.Getenv("MCP_AUTH_TOKEN")
		log.Printf("MCP HTTP en http://%s/mcp — auth por MCP_AUTH_TOKEN%s", *httpAddr, map[bool]string{true: "", false: " (no definido: solo JWT)"}[token != ""])
		log.Fatal(http.ListenAndServe(*httpAddr, m.Handler(token)))
	}
	m.ServirStdio(os.Stdin, os.Stdout)
}

func home() string {
	h, err := os.UserHomeDir()
	if err != nil {
		log.Fatal(err)
	}
	return h
}

func cmdClientes(args []string) int {
	fs := flag.NewFlagSet("clientes", flag.ExitOnError)
	asJSON := fs.Bool("json", false, "salida JSON")
	nombre := fs.String("nombre", conectores.NombrePorDefecto, "nombre de la entrada")
	_ = fs.Parse(args)
	lista := conectores.Clientes(home(), runtime.GOOS, *nombre)
	if *asJSON {
		_ = json.NewEncoder(os.Stdout).Encode(lista)
		return 0
	}
	for _, c := range lista {
		estado := "no detectado"
		if c.Instalado {
			estado = "conectado"
		} else if c.Presente {
			estado = "detectado, sin conectar"
		}
		fmt.Printf("%-15s %-28s %-24s %s\n", c.ID, c.Nombre, estado, c.Archivo)
	}
	return 0
}

func cmdInstalar(args []string) int {
	fs := flag.NewFlagSet("instalar", flag.ExitOnError)
	en := fs.String("en", "", "cliente: claude-code, claude-desktop, cursor, vscode, windsurf, gemini, codex o todos (los detectados)")
	quitar := fs.Bool("quitar", false, "sacar la entrada en vez de ponerla")
	nombre := fs.String("nombre", conectores.NombrePorDefecto, "nombre de la entrada")
	env := fs.String("env", "", "el .env que usará el servidor (sin él: la regla de nucleo-mcp)")
	db := fs.String("db", "", "base que usará el servidor")
	asJSON := fs.Bool("json", false, "salida JSON")
	_ = fs.Parse(args)
	if *en == "" {
		fmt.Fprintln(os.Stderr, "falta --en <cliente|todos>")
		return 2
	}
	exe, err := os.Executable()
	if err != nil {
		log.Fatal(err)
	}
	exe, _ = filepath.EvalSymlinks(exe)
	e := conectores.Entrada{Nombre: *nombre, Comando: exe}
	if *env != "" {
		abs, _ := filepath.Abs(*env)
		e.Args = append(e.Args, "--env", abs)
	}
	if *db != "" {
		abs, _ := filepath.Abs(*db)
		e.Args = append(e.Args, "--db", abs)
	}
	if d := os.Getenv("DTE_DATOS"); d != "" {
		e.Env = map[string]string{"DTE_DATOS": d}
	}
	lista := conectores.Clientes(home(), runtime.GOOS, *nombre)
	var objetivo []conectores.Cliente
	if *en == "todos" {
		for _, c := range lista {
			if c.Presente {
				objetivo = append(objetivo, c)
			}
		}
		if len(objetivo) == 0 {
			fmt.Fprintln(os.Stderr, "no detecté ningún cliente de IA en esta máquina")
			return 1
		}
	} else {
		c, err := conectores.Buscar(lista, *en)
		if err != nil {
			fmt.Fprintln(os.Stderr, err)
			return 2
		}
		objetivo = []conectores.Cliente{c}
	}
	type res struct {
		Cliente string `json:"cliente"`
		Archivo string `json:"archivo"`
		Cambio  bool   `json:"cambio"`
		Error   string `json:"error,omitempty"`
	}
	var out []res
	rc := 0
	for _, c := range objetivo {
		var cambio bool
		var err error
		if *quitar {
			cambio, err = c.Quitar(*nombre)
		} else {
			cambio, err = c.Instalar(e)
		}
		r := res{Cliente: c.ID, Archivo: c.Archivo, Cambio: cambio}
		if err != nil {
			r.Error = err.Error()
			rc = 1
		}
		out = append(out, r)
	}
	if *asJSON {
		_ = json.NewEncoder(os.Stdout).Encode(out)
		return rc
	}
	for _, r := range out {
		switch {
		case r.Error != "":
			fmt.Printf("%-15s ERROR %s\n", r.Cliente, r.Error)
		case *quitar && r.Cambio:
			fmt.Printf("%-15s quitado de %s\n", r.Cliente, r.Archivo)
		case *quitar:
			fmt.Printf("%-15s no estaba\n", r.Cliente)
		case r.Cambio:
			fmt.Printf("%-15s conectado: %s\n", r.Cliente, r.Archivo)
		default:
			fmt.Printf("%-15s ya estaba conectado\n", r.Cliente)
		}
	}
	if !*quitar && rc == 0 {
		fmt.Println("Reinicia el cliente para que vea el motor. La IA trabaja con los datos de", datosDe(e))
	}
	return rc
}

func datosDe(e conectores.Entrada) string {
	for i, a := range e.Args {
		if a == "--env" && i+1 < len(e.Args) {
			return filepath.Dir(e.Args[i+1])
		}
	}
	if d := os.Getenv("DTE_DATOS"); d != "" {
		return d
	}
	return "la carpeta de datos de la app (o ./.env si existe)"
}
