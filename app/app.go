package main

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"strings"
	"sync"
	"time"

	wruntime "github.com/wailsapp/wails/v2/pkg/runtime"
)

// Estado es lo que la interfaz necesita saber del motor. Nunca incluye la clave.
type Estado struct {
	Listo    bool   `json:"listo"`
	Error    string `json:"error"`
	URL      string `json:"url"`
	Ambiente string `json:"ambiente"`
	Version  string `json:"version"`
	Externo  bool   `json:"externo"`
	Raiz     string `json:"raiz"`
	Log      string `json:"log"`
}

// Respuesta de una llamada al motor: status HTTP y cuerpo tal cual (normalmente JSON).
type Respuesta struct {
	Status int    `json:"status"`
	Cuerpo string `json:"cuerpo"`
}

type App struct {
	ctx    context.Context
	motor  *Motor
	mu     sync.RWMutex
	estado Estado
	http   *http.Client
}

func NewApp() *App {
	return &App{motor: &Motor{}, http: &http.Client{Timeout: 180 * time.Second}}
}

func (a *App) startup(ctx context.Context) {
	a.ctx = ctx
	go a.arrancar()
}

func (a *App) shutdown(ctx context.Context) {
	a.motor.Detener()
}

func (a *App) arrancar() {
	err := a.motor.Iniciar(a.ctx)
	e := Estado{URL: a.motor.URL, Externo: a.motor.Externo, Raiz: a.motor.Raiz, Log: a.motor.LogPath}
	if err != nil {
		e.Error = err.Error()
	} else {
		e.Listo = true
		if r, err := a.API("GET", "/", ""); err == nil && r.Status == 200 {
			var info struct {
				Ambiente string `json:"ambiente_sii"`
				Version  string `json:"version"`
			}
			if json.Unmarshal([]byte(r.Cuerpo), &info) == nil {
				e.Ambiente, e.Version = info.Ambiente, info.Version
			}
		}
	}
	a.mu.Lock()
	a.estado = e
	a.mu.Unlock()
	wruntime.EventsEmit(a.ctx, "motor", e)
}

// Estado devuelve el estado actual del motor (la interfaz lo consulta al abrir y escucha el
// evento "motor" para enterarse cuando termina de arrancar).
func (a *App) Estado() Estado {
	a.mu.RLock()
	defer a.mu.RUnlock()
	return a.estado
}

// API llama al motor con la clave de la app. `ruta` es absoluta ("/api/v1/..."), `cuerpo` es
// JSON o vacío. Devuelve status y cuerpo sin interpretar: la interfaz decide qué mostrar.
func (a *App) API(metodo, ruta, cuerpo string) (Respuesta, error) {
	if a.motor.URL == "" {
		return Respuesta{}, fmt.Errorf("el motor todavía no está listo")
	}
	var body io.Reader
	if cuerpo != "" {
		body = strings.NewReader(cuerpo)
	}
	req, err := http.NewRequest(metodo, a.motor.URL+ruta, body)
	if err != nil {
		return Respuesta{}, err
	}
	if a.motor.Clave != "" {
		req.Header.Set("Authorization", "Bearer "+a.motor.Clave)
	}
	if cuerpo != "" {
		req.Header.Set("Content-Type", "application/json")
	}
	req.Header.Set("Accept", "application/json")
	r, err := a.http.Do(req)
	if err != nil {
		return Respuesta{}, err
	}
	defer r.Body.Close()
	b, err := io.ReadAll(r.Body)
	if err != nil {
		return Respuesta{}, err
	}
	return Respuesta{Status: r.StatusCode, Cuerpo: string(b)}, nil
}

// Guardar baja un archivo del motor (PDF/XML) y lo guarda donde el usuario elija.
// Devuelve la ruta elegida, o "" si canceló.
func (a *App) Guardar(ruta, nombreSugerido string) (string, error) {
	req, err := http.NewRequest("GET", a.motor.URL+ruta, nil)
	if err != nil {
		return "", err
	}
	if a.motor.Clave != "" {
		req.Header.Set("Authorization", "Bearer "+a.motor.Clave)
	}
	r, err := a.http.Do(req)
	if err != nil {
		return "", err
	}
	defer r.Body.Close()
	if r.StatusCode != 200 {
		b, _ := io.ReadAll(io.LimitReader(r.Body, 4096))
		return "", fmt.Errorf("el motor respondió %d: %s", r.StatusCode, string(b))
	}
	datos, err := io.ReadAll(r.Body)
	if err != nil {
		return "", err
	}
	destino, err := wruntime.SaveFileDialog(a.ctx, wruntime.SaveDialogOptions{
		DefaultFilename: nombreSugerido, Title: "Guardar",
	})
	if err != nil || destino == "" {
		return "", err
	}
	return destino, os.WriteFile(destino, datos, 0o644)
}

// AbrirURL abre una dirección en el navegador del sistema (panel web del motor, SII, docs).
func (a *App) AbrirURL(u string) {
	wruntime.BrowserOpenURL(a.ctx, u)
}

// AbrirPanel abre la página web del motor (panel de certificados, documentos, etc.).
func (a *App) AbrirPanel(pagina string) {
	if a.motor.URL != "" {
		wruntime.BrowserOpenURL(a.ctx, a.motor.URL+"/"+strings.TrimLeft(pagina, "/"))
	}
}
