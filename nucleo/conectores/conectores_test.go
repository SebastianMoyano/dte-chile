package conectores

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func entrada() Entrada {
	return Entrada{Nombre: "dte-chile", Comando: "/opt/dte/nucleo-mcp", Args: []string{"--env", "/Users/x/DTE Chile/.env"}, Env: map[string]string{"DTE_DATOS": "/Users/x/DTE Chile"}}
}

func TestClientesPorSistema(t *testing.T) {
	home := t.TempDir()
	for _, goos := range []string{"darwin", "linux", "windows"} {
		l := Clientes(home, goos, "")
		if len(l) != 7 {
			t.Fatalf("%s: %d clientes", goos, len(l))
		}
		for _, c := range l {
			if c.Presente || c.Instalado {
				t.Fatalf("%s/%s: no debería estar presente ni instalado en un HOME vacío", goos, c.ID)
			}
		}
	}
	if c, _ := Buscar(Clientes(home, "darwin", ""), "claude-desktop"); !strings.Contains(c.Archivo, "Library/Application Support/Claude/claude_desktop_config.json") {
		t.Fatalf("ruta mac: %s", c.Archivo)
	}
	if c, _ := Buscar(Clientes(home, "linux", ""), "vscode"); !strings.HasSuffix(c.Archivo, ".config/Code/User/mcp.json") {
		t.Fatalf("ruta linux: %s", c.Archivo)
	}
	if _, err := Buscar(Clientes(home, "darwin", ""), "nada"); err == nil {
		t.Fatal("Buscar debía fallar")
	}
}

func TestJSONConservaLoDemas(t *testing.T) {
	home := t.TempDir()
	c, _ := Buscar(Clientes(home, "darwin", ""), "claude-desktop")
	_ = os.MkdirAll(filepath.Dir(c.Archivo), 0o755)
	_ = os.WriteFile(c.Archivo, []byte(`{"mcpServers":{"otro":{"command":"x"}},"preferencias":{"tema":"oscuro"}}`), 0o600)

	cambio, err := c.Instalar(entrada())
	if err != nil || !cambio {
		t.Fatalf("instalar: %v %v", cambio, err)
	}
	cambio, err = c.Instalar(entrada())
	if err != nil || cambio {
		t.Fatalf("segunda instalación debía ser idempotente: %v %v", cambio, err)
	}
	var doc map[string]any
	b, _ := os.ReadFile(c.Archivo)
	if err := json.Unmarshal(b, &doc); err != nil {
		t.Fatal(err)
	}
	if doc["preferencias"].(map[string]any)["tema"] != "oscuro" {
		t.Fatal("se perdió otra clave")
	}
	srv := doc["mcpServers"].(map[string]any)
	if srv["otro"] == nil {
		t.Fatal("se perdió otro servidor")
	}
	e := srv["dte-chile"].(map[string]any)
	if e["command"] != "/opt/dte/nucleo-mcp" || e["args"].([]any)[1] != "/Users/x/DTE Chile/.env" || e["env"].(map[string]any)["DTE_DATOS"] != "/Users/x/DTE Chile" {
		t.Fatalf("entrada: %v", e)
	}
	if _, ok := e["type"]; ok {
		t.Fatal("Claude Desktop no lleva type")
	}
	l := Clientes(home, "darwin", "")
	cd, _ := Buscar(l, "claude-desktop")
	if !cd.Presente || !cd.Instalado {
		t.Fatalf("debía verse presente e instalado: %+v", cd)
	}
	habia, err := c.Quitar("")
	if err != nil || !habia {
		t.Fatalf("quitar: %v %v", habia, err)
	}
	habia, _ = c.Quitar("")
	if habia {
		t.Fatal("ya no estaba")
	}
	b, _ = os.ReadFile(c.Archivo)
	if !strings.Contains(string(b), `"otro"`) || strings.Contains(string(b), "dte-chile") {
		t.Fatalf("tras quitar: %s", b)
	}
}

func TestVSCodeYClaudeCodeLlevanType(t *testing.T) {
	home := t.TempDir()
	for _, id := range []string{"vscode", "claude-code"} {
		c, _ := Buscar(Clientes(home, "linux", ""), id)
		if _, err := c.Instalar(entrada()); err != nil {
			t.Fatal(err)
		}
		var doc map[string]any
		b, _ := os.ReadFile(c.Archivo)
		_ = json.Unmarshal(b, &doc)
		raiz := "mcpServers"
		if id == "vscode" {
			raiz = "servers"
		}
		e := doc[raiz].(map[string]any)["dte-chile"].(map[string]any)
		if e["type"] != "stdio" {
			t.Fatalf("%s: falta type stdio: %v", id, e)
		}
	}
}

func TestJSONInvalidoNoSePisa(t *testing.T) {
	home := t.TempDir()
	c, _ := Buscar(Clientes(home, "linux", ""), "cursor")
	_ = os.MkdirAll(filepath.Dir(c.Archivo), 0o755)
	_ = os.WriteFile(c.Archivo, []byte("{ // comentario\n}"), 0o600)
	if _, err := c.Instalar(entrada()); err == nil {
		t.Fatal("debía negarse a pisar un archivo que no entiende")
	}
	b, _ := os.ReadFile(c.Archivo)
	if string(b) != "{ // comentario\n}" {
		t.Fatal("tocó el archivo")
	}
}

func TestTOMLCodex(t *testing.T) {
	home := t.TempDir()
	c, _ := Buscar(Clientes(home, "linux", ""), "codex")
	_ = os.MkdirAll(filepath.Dir(c.Archivo), 0o755)
	previo := "model = \"o3\"\n\n[mcp_servers.otro]\ncommand = \"x\"\nargs = []\n"
	_ = os.WriteFile(c.Archivo, []byte(previo), 0o600)
	e := entrada()
	e.Comando = `C:\Program Files\DTE "Chile"\nucleo-mcp.exe`
	if cambio, err := c.Instalar(e); err != nil || !cambio {
		t.Fatalf("instalar: %v %v", cambio, err)
	}
	if cambio, _ := c.Instalar(e); cambio {
		t.Fatal("debía ser idempotente")
	}
	b, _ := os.ReadFile(c.Archivo)
	s := string(b)
	for _, frag := range []string{"model = \"o3\"", "[mcp_servers.otro]", "[mcp_servers.dte-chile]",
		`command = "C:\\Program Files\\DTE \"Chile\"\\nucleo-mcp.exe"`, `args = ["--env", "/Users/x/DTE Chile/.env"]`,
		"[mcp_servers.dte-chile.env]", `DTE_DATOS = "/Users/x/DTE Chile"`} {
		if !strings.Contains(s, frag) {
			t.Fatalf("falta %q en:\n%s", frag, s)
		}
	}
	if cd, _ := Buscar(Clientes(home, "linux", ""), "codex"); !cd.Instalado {
		t.Fatal("debía verse instalado")
	}
	// cambiar la ruta reemplaza la sección (no la duplica)
	e.Comando = "/nuevo"
	_, _ = c.Instalar(e)
	b, _ = os.ReadFile(c.Archivo)
	if strings.Count(string(b), "[mcp_servers.dte-chile]") != 1 || strings.Contains(string(b), "nucleo-mcp.exe") {
		t.Fatalf("sección duplicada o vieja:\n%s", b)
	}
	if habia, err := c.Quitar(""); err != nil || !habia {
		t.Fatalf("quitar: %v %v", habia, err)
	}
	b, _ = os.ReadFile(c.Archivo)
	if string(b) != previo {
		t.Fatalf("tras quitar debía quedar lo previo:\n%q\n%q", b, previo)
	}
}
