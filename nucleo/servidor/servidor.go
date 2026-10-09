package servidor

import (
	"database/sql"
	"fmt"
	"net/http"
	"net/http/httputil"
	"net/url"
	"os"
	"path/filepath"
	"strings"

	"dtechile/nucleo/almacen"

	_ "modernc.org/sqlite"
)

// Servidor atiende las rutas portadas y reenvía el resto al motor Python.
type Servidor struct {
	cfg   *Config
	db    *sql.DB
	alm   *almacen.Almacen
	proxy *httputil.ReverseProxy
	mux   *http.ServeMux
}

// Nuevo abre (y migra) la base, prepara el reenvío y arma las rutas.
func Nuevo(cfg *Config) (*Servidor, error) {
	alm, err := almacen.AbrirYMigrar(cfg.DatabasePath)
	if err != nil {
		return nil, fmt.Errorf("base de datos %s: %w", cfg.DatabasePath, err)
	}
	db, err := sql.Open("sqlite", cfg.DatabasePath+"?_pragma=busy_timeout(5000)&_pragma=journal_mode(WAL)")
	if err != nil {
		return nil, err
	}
	s := &Servidor{cfg: cfg, db: db, alm: alm, mux: http.NewServeMux()}
	if cfg.MotorPython != "" {
		u, err := url.Parse(cfg.MotorPython)
		if err != nil {
			return nil, fmt.Errorf("URL del motor Python inválida: %w", err)
		}
		s.proxy = httputil.NewSingleHostReverseProxy(u)
		s.proxy.ErrorHandler = func(w http.ResponseWriter, r *http.Request, err error) {
			responderError(w, r, 503, "motor_no_disponible", "El motor Python no responde (ruta aún no portada a Go).", nil)
		}
	}
	s.rutas()
	return s, nil
}

// Cerrar libera la base.
func (s *Servidor) Cerrar() { s.db.Close(); s.alm.Cerrar() }

// Handler es el servidor HTTP completo (con request-id, CORS y reenvío).
func (s *Servidor) Handler() http.Handler { return conRequestID(s.cors(s.mux)) }

func (s *Servidor) rutas() {
	s.mux.HandleFunc("GET /{$}", s.raiz)
	s.rutasValores(s.mux)
	if s.cfg.CarpetaApp != "" {
		if st, err := os.Stat(s.cfg.CarpetaApp); err == nil && st.IsDir() {
			fs := http.StripPrefix("/app/", http.FileServer(http.Dir(s.cfg.CarpetaApp)))
			s.mux.Handle("/app/", fs)
			s.mux.HandleFunc("/app", func(w http.ResponseWriter, r *http.Request) {
				http.Redirect(w, r, "/app/", http.StatusMovedPermanently)
			})
		}
	}
	// Todo lo demás: Python (mientras exista) o 503.
	s.mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		if s.proxy == nil {
			responderError(w, r, 503, "no_portado", "Esta ruta todavía no está en el motor Go y no hay motor Python configurado.", nil)
			return
		}
		s.proxy.ServeHTTP(w, r)
	})
}

// raiz es GET / de main.py (health check).
func (s *Servidor) raiz(w http.ResponseWriter, r *http.Request) {
	responderJSON(w, 200, map[string]any{
		"status": "ok", "servicio": s.cfg.AppName, "version": s.cfg.AppVersion, "documentacion": "/docs",
		"ambiente_sii": s.cfg.SIIAmbiente, "empresa_configurada": s.cfg.EmpresaConfigurada(),
	})
}

func (s *Servidor) cors(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		origen := r.Header.Get("Origin")
		if origen != "" {
			permitido := s.cfg.CORSOrigins == "*"
			for _, o := range strings.Split(s.cfg.CORSOrigins, ",") {
				if strings.TrimSpace(o) == origen {
					permitido = true
				}
			}
			if permitido {
				w.Header().Set("Access-Control-Allow-Origin", origen)
				w.Header().Set("Access-Control-Allow-Headers", "Authorization, Content-Type, X-Request-ID")
				w.Header().Set("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
				w.Header().Set("Access-Control-Expose-Headers", "X-Request-ID")
			}
			if r.Method == http.MethodOptions {
				w.WriteHeader(200)
				return
			}
		}
		next.ServeHTTP(w, r)
	})
}

// RutaApp localiza app/frontend/dist a partir de la raíz del repo (desarrollo).
func RutaApp(raiz string) string {
	p := filepath.Join(raiz, "app", "frontend", "dist")
	if st, err := os.Stat(p); err == nil && st.IsDir() {
		return p
	}
	return ""
}
