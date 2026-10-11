package main

// Conectar la IA del computador a la app: la propia app, lanzada con `--mcp`, es el servidor
// MCP (nucleo/mcp) sobre la misma carpeta de datos. Así "un click" en la app escribe en la
// configuración de Claude Code, Claude Desktop, Cursor, VS Code, Windsurf, Gemini o Codex una
// entrada que apunta a este mismo ejecutable; no hay segundo binario ni nada que descargar.

import (
	"errors"
	"io"
	"os"
	"path/filepath"
	"runtime"

	"dtechile/nucleo/conectores"
	"dtechile/nucleo/mcp"
)

// ejecutarMCP es la app en modo servidor MCP (sin ventana): atiende stdio hasta que el cliente
// cierra. Datos: el repo si está al lado (desarrollo) o la carpeta de datos del usuario, la
// misma regla que el motor de la ventana.
func ejecutarMCP(stdin io.Reader, stdout io.Writer) error {
	env := ""
	if raiz, err := localizarRaiz(); err == nil && os.Getenv("DTE_DATOS") == "" {
		env = filepath.Join(raiz, ".env")
	}
	m, cerrar, err := mcp.Arrancar(env, "")
	if err != nil {
		return err
	}
	defer cerrar()
	m.ServirStdio(stdin, stdout)
	return nil
}

// entradaMCP es cómo debe lanzarnos un cliente: este ejecutable con --mcp (y DTE_DATOS si
// el usuario cambió su carpeta).
func entradaMCP() (conectores.Entrada, error) {
	exe, err := os.Executable()
	if err != nil {
		return conectores.Entrada{}, err
	}
	if r, err := filepath.EvalSymlinks(exe); err == nil {
		exe = r
	}
	e := conectores.Entrada{Nombre: conectores.NombrePorDefecto, Comando: exe, Args: []string{"--mcp"}}
	if d := os.Getenv("DTE_DATOS"); d != "" {
		e.Env = map[string]string{"DTE_DATOS": d}
	}
	return e, nil
}

func homeDir() (string, error) {
	h, err := os.UserHomeDir()
	if err != nil {
		return "", err
	}
	return h, nil
}

// Conectores lista los clientes de IA de esta máquina y si ya tienen la app conectada.
func (a *App) Conectores() ([]conectores.Cliente, error) {
	h, err := homeDir()
	if err != nil {
		return nil, err
	}
	return conectores.Clientes(h, runtime.GOOS, conectores.NombrePorDefecto), nil
}

// ConectarIA escribe (o quita, con quitar=true) la entrada de la app en ese cliente y
// devuelve el archivo tocado.
func (a *App) ConectarIA(id string, quitar bool) (string, error) {
	h, err := homeDir()
	if err != nil {
		return "", err
	}
	c, err := conectores.Buscar(conectores.Clientes(h, runtime.GOOS, conectores.NombrePorDefecto), id)
	if err != nil {
		return "", err
	}
	if quitar {
		_, err = c.Quitar(conectores.NombrePorDefecto)
		return c.Archivo, err
	}
	e, err := entradaMCP()
	if err != nil {
		return "", err
	}
	if e.Comando == "" {
		return "", errors.New("no sé dónde está el ejecutable de la app")
	}
	_, err = c.Instalar(e)
	return c.Archivo, err
}
