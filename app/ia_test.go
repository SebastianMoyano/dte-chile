package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// La app con --mcp responde MCP por stdio sobre la carpeta de datos, y ConectarIA deja la
// entrada (este ejecutable, --mcp) en la configuración del cliente.
func TestAppComoMCP(t *testing.T) {
	datos := t.TempDir()
	t.Setenv("DTE_DATOS", datos)
	home := t.TempDir()
	t.Setenv("HOME", home)
	in := strings.NewReader(`{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"salud","arguments":{}}}` + "\n")
	var out strings.Builder
	if err := ejecutarMCP(in, &out); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(out.String(), `"motor":"go"`) {
		t.Fatalf("salud: %s", out.String())
	}
	if _, err := os.Stat(filepath.Join(datos, "dte_database.db")); err != nil {
		t.Fatal("la base debía quedar en la carpeta de datos")
	}

	a := NewApp()
	lista, err := a.Conectores()
	if err != nil || len(lista) != 7 {
		t.Fatalf("conectores: %d %v", len(lista), err)
	}
	archivo, err := a.ConectarIA("cursor", false)
	if err != nil {
		t.Fatal(err)
	}
	b, _ := os.ReadFile(archivo)
	var doc map[string]any
	_ = json.Unmarshal(b, &doc)
	e := doc["mcpServers"].(map[string]any)["dte-chile"].(map[string]any)
	exe, _ := os.Executable()
	exe, _ = filepath.EvalSymlinks(exe)
	if e["command"] != exe || e["args"].([]any)[0] != "--mcp" || e["env"].(map[string]any)["DTE_DATOS"] != datos {
		t.Fatalf("entrada: %v", e)
	}
	lista, _ = a.Conectores()
	for _, c := range lista {
		if c.ID == "cursor" && !c.Instalado {
			t.Fatal("debía verse conectado")
		}
	}
	if _, err := a.ConectarIA("cursor", true); err != nil {
		t.Fatal(err)
	}
	lista, _ = a.Conectores()
	for _, c := range lista {
		if c.ID == "cursor" && c.Instalado {
			t.Fatal("debía quedar desconectado")
		}
	}
}
