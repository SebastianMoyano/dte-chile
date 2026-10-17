// Faro (antes DTE Chile) — cascarón de escritorio (Wails) con el motor Go adentro.
//
// El motor es `nucleo/servidor` corriendo en este mismo proceso (fase 7 del port): escucha en
// un puerto libre de 127.0.0.1 con una clave efímera (APP_SHELL_KEY) y la interfaz
// (frontend/dist) le habla por HTTP a través de `App.API`, que firma las llamadas desde Go.
// La interfaz nunca ve la clave. Con DTE_MOTOR=python se arranca el sidecar Python de antes.
// Lanzada con `--mcp` no abre ventana: es el servidor MCP para la IA del computador (ia.go).
package main

import (
	"embed"
	"os"

	"github.com/wailsapp/wails/v2"
	"github.com/wailsapp/wails/v2/pkg/options"
	"github.com/wailsapp/wails/v2/pkg/options/assetserver"
)

//go:embed all:frontend/dist
var assets embed.FS

func main() {
	if len(os.Args) > 1 && os.Args[1] == "--mcp" { // la app como servidor MCP, sin ventana (ver ia.go)
		if err := ejecutarMCP(os.Stdin, os.Stdout); err != nil {
			println("Error:", err.Error())
			os.Exit(1)
		}
		return
	}
	app := NewApp()
	defer registrarCaida(func() string { return app.Estado().Raiz })
	err := wails.Run(&options.App{
		Title:            "Faro",
		Width:            1120,
		Height:           780,
		MinWidth:         820,
		MinHeight:        600,
		AssetServer:      &assetserver.Options{Assets: assets},
		BackgroundColour: &options.RGBA{R: 244, G: 245, B: 247, A: 1},
		OnStartup:        app.startup,
		OnShutdown:       app.shutdown,
		Bind:             []interface{}{app},
	})
	if err != nil {
		println("Error:", err.Error())
	}
}
