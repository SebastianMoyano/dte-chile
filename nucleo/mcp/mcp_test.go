package mcp

import (
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"

	"dtechile/nucleo/servidor"
)

func motorDePrueba(t *testing.T, dir string) *servidor.Servidor {
	t.Helper()
	cfg, err := servidor.CargarConfig("")
	if err != nil {
		t.Fatal(err)
	}
	cfg.DatabasePath = filepath.Join(dir, "mcp.db")
	cfg.StoragePath = filepath.Join(dir, "storage")
	cfg.JWTSecret = "secreto-de-prueba-largo-para-el-jwt"
	cfg.AppShellKey = "clave-de-prueba-muy-larga-123456"
	cfg.RVDSchedulerActivo = false
	s, err := servidor.Nuevo(cfg)
	if err != nil {
		t.Fatal(err)
	}
	return s
}

func lineas(out string) []map[string]any {
	var r []map[string]any
	for _, l := range strings.Split(strings.TrimSpace(out), "\n") {
		var m map[string]any
		if json.Unmarshal([]byte(l), &m) == nil {
			r = append(r, m)
		}
	}
	return r
}

// El transporte stdio: initialize, tools/list con las 20 herramientas, una notificación sin
// respuesta y un tools/call que llega al motor.
func TestStdio(t *testing.T) {
	s := motorDePrueba(t, t.TempDir())
	defer s.Cerrar()
	m := Nuevo(s, 1, "certificacion")
	in := strings.Join([]string{
		`{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"t","version":"0"}}}`,
		`{"jsonrpc":"2.0","method":"notifications/initialized"}`,
		`{"jsonrpc":"2.0","id":2,"method":"tools/list"}`,
		`{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"salud","arguments":{}}}`,
		`{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"no_existe"}}`,
	}, "\n") + "\n"
	var out bytes.Buffer
	m.ServirStdio(strings.NewReader(in), &out)
	r := lineas(out.String())
	if len(r) != 4 {
		t.Fatalf("esperaba 4 respuestas (la notificación no responde), hay %d:\n%s", len(r), out.String())
	}
	if r[0]["result"].(map[string]any)["serverInfo"].(map[string]any)["name"] != "dte-chile" {
		t.Fatalf("initialize: %v", r[0])
	}
	tools := r[1]["result"].(map[string]any)["tools"].([]any)
	if len(tools) != 20 || len(m.Herramientas()) != 20 {
		t.Fatalf("herramientas: %d", len(tools))
	}
	salud := r[2]["result"].(map[string]any)["structuredContent"].(map[string]any)
	if salud["motor"] != "go" || salud["ambiente_defecto"] != "certificacion" {
		t.Fatalf("salud: %v", salud)
	}
	if r[3]["error"] == nil {
		t.Fatalf("tool desconocida debía dar error: %v", r[3])
	}
}

// La app y un cliente MCP abren la misma base a la vez (dos motores, dos conexiones SQLite):
// emitir en uno mientras el otro consulta no puede romper ni bloquear.
func TestDosMotoresMismaBase(t *testing.T) {
	dir := t.TempDir()
	app := motorDePrueba(t, dir)
	defer app.Cerrar()
	otro := motorDePrueba(t, dir)
	defer otro.Cerrar()
	m := Nuevo(otro, 1, "certificacion")

	var wg sync.WaitGroup
	errs := make(chan string, 100)
	wg.Add(2)
	go func() {
		defer wg.Done()
		for i := 0; i < 15; i++ {
			st, b := app.Llamar("POST", "/api/v1/simulacion/emitir", []byte(`{"tipo_dte":39,"items":[{"nombre":"Café","precio_unitario":1190}]}`))
			if st != 201 && st != 200 {
				errs <- "emitir " + string(b)
			}
		}
	}()
	go func() {
		defer wg.Done()
		for i := 0; i < 15; i++ {
			r := m.Atender([]byte(`{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"listar_negocios","arguments":{}}}`)).(map[string]any)
			if res, ok := r["result"].(map[string]any); !ok || res["isError"] == true {
				errs <- "tool: " + string(mustJSON(r))
			}
		}
	}()
	wg.Wait()
	close(errs)
	for e := range errs {
		t.Error(e)
	}
	if st, b := otro.Llamar("GET", "/api/v1/simulacion/estado", nil); st != 200 || !strings.Contains(string(b), `"documentos":15`) {
		t.Fatalf("el otro motor debía ver los 15 documentos: %d %s", st, b)
	}
}

func mustJSON(v any) []byte { b, _ := json.Marshal(v); return b }

// Arrancar sin --env ni ./.env usa la carpeta de datos (DTE_DATOS) y le crea su .env.
func TestArrancarCarpetaDatos(t *testing.T) {
	datos := t.TempDir()
	t.Setenv("DTE_DATOS", datos)
	wd, _ := os.Getwd()
	_ = os.Chdir(t.TempDir())
	defer func() { _ = os.Chdir(wd) }()
	m, cerrar, err := Arrancar("", "")
	if err != nil {
		t.Fatal(err)
	}
	defer cerrar()
	if _, err := os.Stat(filepath.Join(datos, ".env")); err != nil {
		t.Fatal("no creó el .env de la carpeta de datos")
	}
	if _, err := os.Stat(filepath.Join(datos, "dte_database.db")); err != nil {
		t.Fatal("la base no quedó en la carpeta de datos")
	}
	if len(m.Herramientas()) != 20 {
		t.Fatal("herramientas")
	}
}
