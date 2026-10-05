// DTE Chile — cascarón de escritorio (Wails) sobre el motor Python.
//
// El motor (FastAPI, `main.py`) sigue siendo la única fuente de verdad: esta app lo arranca
// como proceso hijo en un puerto libre de 127.0.0.1, le pasa una clave efímera
// (APP_SHELL_KEY) y le habla por HTTP. La interfaz (frontend/dist) nunca ve la clave: todas
// las llamadas pasan por `App.API`, que las firma desde Go.
package main

import (
	"embed"

	"github.com/wailsapp/wails/v2"
	"github.com/wailsapp/wails/v2/pkg/options"
	"github.com/wailsapp/wails/v2/pkg/options/assetserver"
)

//go:embed all:frontend/dist
var assets embed.FS

func main() {
	app := NewApp()
	err := wails.Run(&options.App{
		Title:            "DTE Chile",
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
