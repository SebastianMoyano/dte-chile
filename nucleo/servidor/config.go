// Package servidor es el motor HTTP en Go (fase 7 del port): atiende /api/v1 con el mismo
// contrato que el motor Python y reenvía a Python lo que todavía no está portado (patrón
// estrangulador). La app y el navegador no cambian: mismo puerto, mismas rutas, mismos JSON.
// Cada ruta portada se compara contra Python con tools/contrato_api.py antes de apagarla ahí.
package servidor

import (
	"bufio"
	"os"
	"strings"
)

// Config es lo que el servidor necesita del `.env` del motor (mismos nombres que
// core/config.py; las variables de entorno ganan sobre el archivo, como en pydantic-settings).
type Config struct {
	AppName, AppVersion string
	DatabasePath        string // DATABASE_URL sin el prefijo sqlite:///
	StoragePath         string
	JWTSecret           string
	JWTAlgoritmo        string
	AppShellKey         string // solo por entorno (APP_SHELL_KEY)
	SIIAmbiente         string
	EmpresaRut          string
	EmpresaRazonSocial  string
	CORSOrigins         string
	MotorPython         string // URL del motor Python para el reenvío ("" = sin reenvío)
	CarpetaApp          string // app/frontend/dist, servida en /app
	Valores             map[string]string
}

// CargarConfig lee el .env (si existe) y el entorno. Los secretos nunca se registran en el log.
func CargarConfig(rutaEnv string) (*Config, error) {
	vals := map[string]string{}
	if rutaEnv != "" {
		f, err := os.Open(rutaEnv)
		if err == nil {
			sc := bufio.NewScanner(f)
			for sc.Scan() {
				l := strings.TrimSpace(sc.Text())
				if l == "" || strings.HasPrefix(l, "#") {
					continue
				}
				k, v, ok := strings.Cut(l, "=")
				if !ok {
					continue
				}
				k = strings.TrimSpace(k)
				v = strings.TrimSpace(v)
				if len(v) >= 2 && ((v[0] == '"' && v[len(v)-1] == '"') || (v[0] == '\'' && v[len(v)-1] == '\'')) {
					v = v[1 : len(v)-1]
				}
				vals[k] = v
			}
			f.Close()
		}
	}
	for _, kv := range os.Environ() { // el entorno gana
		if k, v, ok := strings.Cut(kv, "="); ok {
			vals[k] = v
		}
	}
	get := func(k, def string) string {
		if v, ok := vals[k]; ok && v != "" {
			return v
		}
		return def
	}
	c := &Config{
		AppName: get("APP_NAME", "DTE Chile API"), AppVersion: get("APP_VERSION", "1.0.0"),
		DatabasePath:       strings.TrimPrefix(get("DATABASE_URL", "sqlite:///./dte_database.db"), "sqlite:///"),
		StoragePath:        get("STORAGE_PATH", "./storage"),
		JWTSecret:          get("JWT_SECRET_KEY", ""),
		JWTAlgoritmo:       get("JWT_ALGORITHM", "HS256"),
		AppShellKey:        os.Getenv("APP_SHELL_KEY"),
		SIIAmbiente:        get("SII_AMBIENTE", "certificacion"),
		EmpresaRut:         get("EMPRESA_RUT", ""),
		EmpresaRazonSocial: get("EMPRESA_RAZON_SOCIAL", ""),
		CORSOrigins:        get("CORS_ORIGINS", "*"),
		Valores:            vals,
	}
	return c, nil
}

// EmpresaConfigurada es settings.empresa_configurada.
func (c *Config) EmpresaConfigurada() bool { return c.EmpresaRut != "" && c.EmpresaRazonSocial != "" }
