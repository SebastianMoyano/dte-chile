// Package conectores enchufa el servidor MCP del motor en los clientes de IA que corren en el
// computador del usuario: Claude Code, la app de escritorio de Claude, Cursor, VS Code,
// Windsurf, Gemini CLI y Codex CLI. Cada uno tiene su archivo de configuración en una ruta
// conocida; aquí se escribe (o se quita) la entrada del motor sin tocar lo demás que haya.
//
// Es la parte "local" de la conectividad: todo pasa por stdio en la misma máquina, sin red,
// sin cuentas, sin tokens. Los clientes que viven en la nube de un tercero (claude.ai en el
// navegador, la app de ChatGPT) no se conectan así: necesitan una URL pública y OAuth.
package conectores

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
)

// Cliente es un programa de IA del computador que entiende MCP por stdio.
type Cliente struct {
	ID        string `json:"id"`        // claude-code, claude-desktop, cursor, vscode, windsurf, gemini, codex
	Nombre    string `json:"nombre"`    // para mostrar
	Archivo   string `json:"archivo"`   // configuración donde va la entrada
	Presente  bool   `json:"presente"`  // el cliente parece instalado (existe su carpeta o su archivo)
	Instalado bool   `json:"instalado"` // la entrada del motor ya está en el archivo
	formato   string // json-mcpServers | json-servers | toml-codex
}

// Entrada es cómo debe lanzar el cliente al servidor MCP.
type Entrada struct {
	Nombre  string            // clave en la configuración (ej. "dte-chile")
	Comando string            // ruta absoluta del binario
	Args    []string          // argumentos (ej. --env /ruta/.env, o --mcp para la app)
	Env     map[string]string // variables (ej. DTE_DATOS)
}

// NombrePorDefecto es la clave con que el motor aparece en los clientes.
const NombrePorDefecto = "dte-chile"

// Clientes devuelve los clientes conocidos para ese HOME y sistema (darwin, windows, linux),
// con Presente/Instalado ya resueltos para la entrada `nombre`.
func Clientes(home, goos, nombre string) []Cliente {
	if nombre == "" {
		nombre = NombrePorDefecto
	}
	cfg := func(darwin, windows, linux string) string {
		switch goos {
		case "darwin":
			return filepath.Join(home, "Library", "Application Support", darwin)
		case "windows":
			appdata := os.Getenv("APPDATA")
			if appdata == "" {
				appdata = filepath.Join(home, "AppData", "Roaming")
			}
			return filepath.Join(appdata, windows)
		}
		return filepath.Join(home, ".config", linux)
	}
	lista := []Cliente{
		{ID: "claude-code", Nombre: "Claude Code", Archivo: filepath.Join(home, ".claude.json"), formato: "json-mcpServers"},
		{ID: "claude-desktop", Nombre: "Claude (app de escritorio)", Archivo: cfg(filepath.Join("Claude", "claude_desktop_config.json"), filepath.Join("Claude", "claude_desktop_config.json"), filepath.Join("Claude", "claude_desktop_config.json")), formato: "json-mcpServers"},
		{ID: "cursor", Nombre: "Cursor", Archivo: filepath.Join(home, ".cursor", "mcp.json"), formato: "json-mcpServers"},
		{ID: "vscode", Nombre: "VS Code (Copilot)", Archivo: cfg(filepath.Join("Code", "User", "mcp.json"), filepath.Join("Code", "User", "mcp.json"), filepath.Join("Code", "User", "mcp.json")), formato: "json-servers"},
		{ID: "windsurf", Nombre: "Windsurf", Archivo: filepath.Join(home, ".codeium", "windsurf", "mcp_config.json"), formato: "json-mcpServers"},
		{ID: "gemini", Nombre: "Gemini CLI", Archivo: filepath.Join(home, ".gemini", "settings.json"), formato: "json-mcpServers"},
		{ID: "codex", Nombre: "Codex CLI", Archivo: filepath.Join(home, ".codex", "config.toml"), formato: "toml-codex"},
	}
	for i := range lista {
		c := &lista[i]
		if _, err := os.Stat(c.Archivo); err == nil {
			c.Presente = true
		} else if c.ID == "claude-code" {
			_, err := os.Stat(filepath.Join(home, ".claude"))
			c.Presente = err == nil
		} else {
			_, err := os.Stat(filepath.Dir(c.Archivo))
			c.Presente = err == nil
		}
		c.Instalado, _ = c.instalado(nombre)
	}
	return lista
}

// Buscar devuelve el cliente con ese id.
func Buscar(lista []Cliente, id string) (Cliente, error) {
	for _, c := range lista {
		if c.ID == id {
			return c, nil
		}
	}
	var ids []string
	for _, c := range lista {
		ids = append(ids, c.ID)
	}
	sort.Strings(ids)
	return Cliente{}, fmt.Errorf("cliente desconocido %q (conozco: %s)", id, strings.Join(ids, ", "))
}

// Instalar escribe la entrada en la configuración del cliente (creando el archivo si no
// existe) y conserva todo lo demás. Devuelve si hubo que cambiar algo.
func (c Cliente) Instalar(e Entrada) (bool, error) {
	if e.Nombre == "" {
		e.Nombre = NombrePorDefecto
	}
	if e.Comando == "" {
		return false, errors.New("falta el comando del servidor MCP")
	}
	switch c.formato {
	case "json-mcpServers", "json-servers":
		return c.instalarJSON(e)
	case "toml-codex":
		return c.instalarTOML(e)
	}
	return false, fmt.Errorf("formato desconocido %q", c.formato)
}

// Quitar saca la entrada; true si estaba.
func (c Cliente) Quitar(nombre string) (bool, error) {
	if nombre == "" {
		nombre = NombrePorDefecto
	}
	switch c.formato {
	case "json-mcpServers", "json-servers":
		raiz, doc, err := c.leerJSON()
		if err != nil || doc == nil {
			return false, err
		}
		m, _ := doc[raiz].(map[string]any)
		if _, ok := m[nombre]; !ok {
			return false, nil
		}
		delete(m, nombre)
		return true, c.escribirJSON(doc)
	case "toml-codex":
		b, err := os.ReadFile(c.Archivo)
		if err != nil {
			return false, nil
		}
		resto, habia := quitarSeccionTOML(string(b), "mcp_servers."+nombre)
		if !habia {
			return false, nil
		}
		return true, os.WriteFile(c.Archivo, []byte(resto), 0o600)
	}
	return false, fmt.Errorf("formato desconocido %q", c.formato)
}

func (c Cliente) instalado(nombre string) (bool, error) {
	switch c.formato {
	case "json-mcpServers", "json-servers":
		raiz, doc, err := c.leerJSON()
		if err != nil || doc == nil {
			return false, err
		}
		m, _ := doc[raiz].(map[string]any)
		_, ok := m[nombre]
		return ok, nil
	case "toml-codex":
		b, err := os.ReadFile(c.Archivo)
		if err != nil {
			return false, nil
		}
		_, habia := quitarSeccionTOML(string(b), "mcp_servers."+nombre)
		return habia, nil
	}
	return false, nil
}

// --- JSON (Claude Code, Claude Desktop, Cursor, Windsurf, Gemini: "mcpServers"; VS Code: "servers")

func (c Cliente) raizJSON() string {
	if c.formato == "json-servers" {
		return "servers"
	}
	return "mcpServers"
}

// leerJSON devuelve (clave raíz, documento) o doc nil si el archivo no existe.
func (c Cliente) leerJSON() (string, map[string]any, error) {
	b, err := os.ReadFile(c.Archivo)
	if err != nil {
		if os.IsNotExist(err) {
			return c.raizJSON(), nil, nil
		}
		return "", nil, err
	}
	doc := map[string]any{}
	if len(strings.TrimSpace(string(b))) > 0 {
		if err := json.Unmarshal(b, &doc); err != nil {
			return "", nil, fmt.Errorf("%s no es JSON válido (¿comentarios?): %w. Agrega la entrada a mano", c.Archivo, err)
		}
	}
	return c.raizJSON(), doc, nil
}

func (c Cliente) escribirJSON(doc map[string]any) error {
	if err := os.MkdirAll(filepath.Dir(c.Archivo), 0o755); err != nil {
		return err
	}
	b, err := json.MarshalIndent(doc, "", "  ")
	if err != nil {
		return err
	}
	return os.WriteFile(c.Archivo, append(b, '\n'), 0o600)
}

func (c Cliente) instalarJSON(e Entrada) (bool, error) {
	raiz, doc, err := c.leerJSON()
	if err != nil {
		return false, err
	}
	if doc == nil {
		doc = map[string]any{}
	}
	m, _ := doc[raiz].(map[string]any)
	if m == nil {
		m = map[string]any{}
		doc[raiz] = m
	}
	entrada := map[string]any{"command": e.Comando, "args": aLista(e.Args)}
	if c.formato == "json-servers" || c.ID == "claude-code" {
		entrada["type"] = "stdio"
	}
	if len(e.Env) > 0 {
		env := map[string]any{}
		for k, v := range e.Env {
			env[k] = v
		}
		entrada["env"] = env
	}
	if antes, ok := m[e.Nombre]; ok {
		a, _ := json.Marshal(antes)
		d, _ := json.Marshal(entrada)
		if string(a) == string(d) {
			return false, nil
		}
	}
	m[e.Nombre] = entrada
	return true, c.escribirJSON(doc)
}

func aLista(s []string) []any {
	l := make([]any, 0, len(s))
	for _, v := range s {
		l = append(l, v)
	}
	return l
}

// --- TOML (Codex CLI: [mcp_servers.<nombre>] command = "…" args = […])

func tomlStr(s string) string {
	return `"` + strings.NewReplacer(`\`, `\\`, `"`, `\"`).Replace(s) + `"`
}

func seccionTOML(e Entrada) string {
	var b strings.Builder
	fmt.Fprintf(&b, "[mcp_servers.%s]\n", e.Nombre)
	fmt.Fprintf(&b, "command = %s\n", tomlStr(e.Comando))
	args := make([]string, 0, len(e.Args))
	for _, a := range e.Args {
		args = append(args, tomlStr(a))
	}
	fmt.Fprintf(&b, "args = [%s]\n", strings.Join(args, ", "))
	if len(e.Env) > 0 {
		keys := make([]string, 0, len(e.Env))
		for k := range e.Env {
			keys = append(keys, k)
		}
		sort.Strings(keys)
		fmt.Fprintf(&b, "\n[mcp_servers.%s.env]\n", e.Nombre)
		for _, k := range keys {
			fmt.Fprintf(&b, "%s = %s\n", k, tomlStr(e.Env[k]))
		}
	}
	return b.String()
}

// quitarSeccionTOML saca [sec] y sus subsecciones ([sec.x]) del texto; devuelve el resto y si
// existía. No interpreta TOML: solo corta por cabeceras de sección, que es lo que hace falta.
func quitarSeccionTOML(texto, sec string) (string, bool) {
	lineas := strings.Split(texto, "\n")
	var out []string
	dentro, habia := false, false
	for _, l := range lineas {
		t := strings.TrimSpace(l)
		if strings.HasPrefix(t, "[") && strings.HasSuffix(t, "]") {
			nombre := strings.TrimSpace(strings.Trim(t, "[]"))
			dentro = nombre == sec || strings.HasPrefix(nombre, sec+".")
			if dentro {
				habia = true
			}
		}
		if !dentro {
			out = append(out, l)
		}
	}
	resto := strings.TrimRight(strings.Join(out, "\n"), "\n")
	if resto != "" {
		resto += "\n"
	}
	return resto, habia
}

func (c Cliente) instalarTOML(e Entrada) (bool, error) {
	var texto string
	if b, err := os.ReadFile(c.Archivo); err == nil {
		texto = string(b)
	} else if !os.IsNotExist(err) {
		return false, err
	}
	nueva := seccionTOML(e)
	resto, habia := quitarSeccionTOML(texto, "mcp_servers."+e.Nombre)
	if habia && strings.Contains(texto, nueva) {
		return false, nil
	}
	if resto != "" && !strings.HasSuffix(resto, "\n\n") {
		resto += "\n"
	}
	if err := os.MkdirAll(filepath.Dir(c.Archivo), 0o755); err != nil {
		return false, err
	}
	return true, os.WriteFile(c.Archivo, []byte(resto+nueva), 0o600)
}
