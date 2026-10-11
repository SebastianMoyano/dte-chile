package main

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"

	wruntime "github.com/wailsapp/wails/v2/pkg/runtime"

	"dtechile/nucleo/almacen"
	"dtechile/nucleo/emision"
	"dtechile/nucleo/pdf"
	"dtechile/nucleo/valores"
	"dtechile/nucleo/xsd"
)

// Estado es lo que la interfaz necesita saber del motor. Nunca incluye la clave.
type Estado struct {
	Listo       bool   `json:"listo"`
	Error       string `json:"error"`
	URL         string `json:"url"`
	Ambiente    string `json:"ambiente"`
	Version     string `json:"version"`
	Externo     bool   `json:"externo"`
	Empaquetado bool   `json:"empaquetado"`
	Go          bool   `json:"go"`          // el motor corre dentro de la app (sin Python)
	ClaveAdmin  string `json:"clave_admin"` // panel web (solo empaquetado)
	Raiz        string `json:"raiz"`
	Log         string `json:"log"`
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

// refrescarValores trae UF, UTM y dólar de las páginas oficiales del SII a la tabla `valores`
// de la base del motor, al arrancar y cada 24 h. Es el "demonio" de nucleo-valores, pero
// dentro de la app: la app ya es Go y así no hace falta otro proceso.
func (a *App) refrescarValores() {
	for {
		if a.motor.Raiz != "" {
			db := filepath.Join(a.motor.Raiz, "dte_database.db")
			if c, err := valores.AbrirCache(db); err == nil {
				anio := time.Now().Year()
				// Histórico: una sola vez (si el primer año con UF es posterior a 2015, falta).
				if min, _ := c.AnioMinimo("uf"); min == 0 || min > 2015 {
					valores.CargarHistorico(c, 2015, anio-1, nil)
				}
				for _, ind := range []string{"uf", "utm", "dolar"} {
					if vs, _, err := valores.Fetch(ind, anio); err == nil {
						_, _ = c.Guardar(vs)
					}
				}
				c.Cerrar()
			}
		}
		time.Sleep(24 * time.Hour)
	}
}

func (a *App) shutdown(ctx context.Context) {
	a.motor.Detener()
}

func (a *App) arrancar() {
	err := a.motor.Iniciar(a.ctx)
	e := Estado{URL: a.motor.URL, Externo: a.motor.Externo, Empaquetado: a.motor.Empaquetado, Go: a.motor.Go,
		ClaveAdmin: a.motor.ClaveAdmin, Raiz: a.motor.Raiz, Log: a.motor.LogPath}
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
	if e.Listo && !e.Externo {
		go a.refrescarValores()
	}
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

// Bytes baja un recurso del motor (p. ej. un PDF) y lo devuelve en base64 para mostrarlo
// dentro de la app (visor embebido) sin pasar por disco.
func (a *App) Bytes(ruta string) (string, error) {
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
	return base64.StdEncoding.EncodeToString(datos), nil
}

// EmitirNucleo emite un documento con el NÚCLEO EN GO (fase 4 del port): pide al motor el
// contexto del negocio (certificado en PEM, resolución, rutas), firma y persiste con
// nucleo/emision sobre la misma base y storage, y le pide a Python el PDF. El material de la
// clave privada vive solo en memoria mientras dura la llamada.
// `docJSON` tiene la forma de la entrada de nucleo-emitir (tipo_dte, folio, fecha_emision,
// emisor, receptor, items, referencias…). Devuelve el resultado en JSON.
func (a *App) EmitirNucleo(negocioID int, docJSON string) (string, error) {
	r, err := a.API("GET", fmt.Sprintf("/api/v1/keystore/negocios/%d/contexto-emision", negocioID), "")
	if err != nil {
		return "", err
	}
	if r.Status != 200 {
		return "", fmt.Errorf("contexto de emisión: %s", r.Cuerpo)
	}
	ctx, err := emision.ContextoDesdeJSON([]byte(r.Cuerpo))
	if err != nil {
		return "", err
	}
	doc, err := emision.DocumentoDesdeJSON([]byte(docJSON))
	if err != nil {
		return "", err
	}
	if doc.Emisor.Rut != "" && doc.Emisor.Rut != ctx.Rut {
		return "", fmt.Errorf("el emisor del documento (%s) no es el negocio elegido (%s)", doc.Emisor.Rut, ctx.Rut)
	}
	alm, err := almacen.Abrir(ctx.DatabasePath)
	if err != nil {
		return "", err
	}
	defer alm.Cerrar()
	marca := os.Getenv("RELOJ_FIJO")
	if marca == "" {
		marca = time.Now().Format("2006-01-02T15:04:05")
	}
	// XSD: nucleo/xsd (mismo veredicto que lxml) antes de que el núcleo escriba nada.
	res, err := emision.Emitir(emision.Contexto{Almacen: alm, Cert: ctx.Cert, StorageBase: ctx.StoragePath,
		Ambiente: ctx.Ambiente, FechaResolucion: ctx.FechaResolucion, NumeroResolucion: ctx.NumeroResolucion,
		Marca: marca, Validar: xsd.ValidarError}, doc)
	if err != nil {
		return "", err
	}
	// El PDF lo dibuja el núcleo (nucleo/pdf) desde el XML firmado, con el TED verbatim.
	if ruta, err := dibujarPDF(alm, res.DTEID, ctx.StoragePath, ctx.Ambiente, ctx.FechaResolucion, ctx.NumeroResolucion); err == nil {
		res.PDFPath = ruta
	} else if p, err2 := a.API("POST", fmt.Sprintf("/api/v1/dte/documentos/%d/pdf", res.DTEID), ""); err2 == nil && p.Status == 200 {
		var pp struct {
			PDFPath string `json:"pdf_path"`
		}
		if json.Unmarshal([]byte(p.Cuerpo), &pp) == nil {
			res.PDFPath = pp.PDFPath
		}
	}
	res.Mensaje += " (núcleo Go)"
	out, _ := json.Marshal(res)
	return string(out), nil
}

// AbrirURL abre una dirección en el navegador del sistema (panel web del motor, SII, docs).
func (a *App) AbrirURL(u string) {
	wruntime.BrowserOpenURL(a.ctx, u)
}

// AbrirPanel abre la página web del motor (panel de certificados, documentos, etc.); el motor
// Go sirve las mismas páginas que Python (nucleo/servidor/static) y además /app (la interfaz).
func (a *App) AbrirPanel(pagina string) {
	if a.motor.URL != "" {
		wruntime.BrowserOpenURL(a.ctx, a.motor.URL+"/"+strings.TrimLeft(pagina, "/"))
	}
}

// dibujarPDF genera el PDF de un documento recién emitido por el núcleo y guarda su ruta en la
// base (misma ruta y nombre que el orquestador Python: storage[/simulacion]/pdfs/DTE_<t>_<f>.pdf).
func dibujarPDF(alm *almacen.Almacen, id int64, storage, ambiente, fechaRes string, numRes int) (string, error) {
	xml, tipo, folio, err := alm.XMLDe(id)
	if err != nil {
		return "", err
	}
	raw := make([]byte, 0, len(xml))
	for _, c := range xml {
		if c > 0xFF {
			raw = append(raw, '?')
		} else {
			raw = append(raw, byte(c))
		}
	}
	doc, ted, err := pdf.DesdeXML(raw)
	if err != nil {
		return "", err
	}
	base := storage
	if ambiente == "simulacion" {
		base = filepath.Join(base, "simulacion")
	}
	if err := os.MkdirAll(filepath.Join(base, "pdfs"), 0o755); err != nil {
		return "", err
	}
	var b []byte
	var ruta string
	if tipo == 39 || tipo == 41 {
		ruta = filepath.Join(base, "pdfs", fmt.Sprintf("BOLETA_%d_%d.pdf", tipo, folio))
		b, err = pdf.Boleta80mm(doc, ted)
	} else {
		ruta = filepath.Join(base, "pdfs", fmt.Sprintf("DTE_%d_%d.pdf", tipo, folio))
		b, err = pdf.Carta(doc, ted, pdf.Opciones{Ambiente: ambiente, ResolucionFecha: fechaRes, ResolucionNum: numRes})
	}
	if err != nil {
		return "", err
	}
	if err := os.WriteFile(ruta, b, 0o644); err != nil {
		return "", err
	}
	rel := ruta
	if r, err := filepath.Rel(filepath.Dir(storage), ruta); err == nil && !strings.HasPrefix(r, "..") {
		rel = r
	}
	return rel, alm.GuardarPDF(id, rel)
}
