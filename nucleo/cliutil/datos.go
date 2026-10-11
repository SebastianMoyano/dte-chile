package cliutil

import (
	"crypto/rand"
	"encoding/base64"
	"encoding/hex"
	"os"
	"path/filepath"
	"strings"

	"dtechile/nucleo/servidor"
)

// CarpetaDatos es donde vive todo lo que escribe el motor cuando no corre desde el repo:
// ~/Library/Application Support/DTE Chile (macOS), %AppData%\DTE Chile, ~/.config/DTE Chile.
// La comparten la app de escritorio y los binarios del operador (nucleo-mcp sin --env, el
// .mcpb de Claude Desktop), así que la IA ve exactamente lo que ve la app. DTE_DATOS la cambia
// (pruebas, o quien quiera sus datos en otra carpeta).
func CarpetaDatos() (string, error) {
	d := os.Getenv("DTE_DATOS")
	if d == "" {
		base, err := os.UserConfigDir()
		if err != nil {
			return "", err
		}
		d = filepath.Join(base, "DTE Chile")
	}
	for _, sub := range []string{"", "logs", "storage"} {
		if err := os.MkdirAll(filepath.Join(d, sub), 0o755); err != nil {
			return "", err
		}
	}
	return d, nil
}

// AsegurarEnv crea el `.env` de la carpeta de datos la primera vez, con secretos generados
// aquí (JWT y clave maestra del keystore) y la clave del usuario admin del panel web. Si ya
// existe no se toca: ahí vive la configuración del usuario. Devuelve la clave admin.
func AsegurarEnv(dir string) (string, error) {
	ruta := filepath.Join(dir, ".env")
	if b, err := os.ReadFile(ruta); err == nil {
		return ClaveAdminDe(string(b)), nil
	}
	azar := func(n int) string { b := make([]byte, n); _, _ = rand.Read(b); return hex.EncodeToString(b) }
	fernet := make([]byte, 32)
	_, _ = rand.Read(fernet)
	admin := azar(8)
	contenido := "# Configuración del motor DTE Chile (creada por la app; edítala si hace falta)\n" +
		"SII_AMBIENTE=certificacion\n" +
		"HOST=127.0.0.1\n" +
		"CORS_ORIGINS=http://127.0.0.1\n" +
		"LOG_LEVEL=info\n" +
		"NOMBRE_SOFTWARE=DTE_CHILE\n" +
		"JWT_SECRET_KEY=" + azar(32) + "\n" +
		"DTE_MASTER_KEY=" + base64.URLEncoding.EncodeToString(fernet) + "\n" +
		"ADMIN_PASSWORD=" + admin + "\n"
	if err := os.WriteFile(ruta, []byte(contenido), 0o600); err != nil {
		return "", err
	}
	return admin, nil
}

// ClaveAdminDe saca ADMIN_PASSWORD del texto de un .env ("" si no está).
func ClaveAdminDe(env string) string {
	for _, l := range strings.Split(env, "\n") {
		if strings.HasPrefix(l, "ADMIN_PASSWORD=") {
			return strings.TrimSpace(strings.TrimPrefix(l, "ADMIN_PASSWORD="))
		}
	}
	return ""
}

// ConfigDeRaiz carga raiz/.env y deja base y storage como rutas absolutas dentro de raiz
// (Python las resolvía desde su cwd, la raíz del repo; un binario lanzado por un cliente MCP
// no tiene cwd que valga).
func ConfigDeRaiz(raiz string) (*servidor.Config, error) {
	cfg, err := servidor.CargarConfig(filepath.Join(raiz, ".env"))
	if err != nil {
		return nil, err
	}
	if !filepath.IsAbs(cfg.DatabasePath) {
		cfg.DatabasePath = filepath.Join(raiz, cfg.DatabasePath)
	}
	if !filepath.IsAbs(cfg.StoragePath) {
		cfg.StoragePath = filepath.Join(raiz, cfg.StoragePath)
	}
	return cfg, nil
}

// ResolverRaiz decide desde qué carpeta trabaja un binario del operador:
//  1. --env explícito: la carpeta de ese archivo.
//  2. un .env en el directorio actual (desarrollo, desde el repo).
//  3. la carpeta de datos del usuario (la de la app), creando su .env si es la primera vez.
//
// Devuelve la raíz y si es la carpeta de datos (empaquetado).
func ResolverRaiz(env string) (string, bool, error) {
	if env != "" {
		abs, err := filepath.Abs(env)
		if err != nil {
			return "", false, err
		}
		// si el archivo no existe se trabaja igual desde su carpeta con los valores por defecto
		// (CargarConfig lo tolera), como hacía nucleo-mcp antes.
		return filepath.Dir(abs), false, nil
	}
	if wd, err := os.Getwd(); err == nil {
		if st, err := os.Stat(filepath.Join(wd, ".env")); err == nil && !st.IsDir() {
			return wd, false, nil
		}
	}
	d, err := CarpetaDatos()
	if err != nil {
		return "", false, err
	}
	if _, err := AsegurarEnv(d); err != nil {
		return "", false, err
	}
	return d, true, nil
}
