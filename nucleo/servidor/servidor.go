package servidor

import (
	"crypto/rand"
	"database/sql"
	"encoding/base64"
	"fmt"
	"log"
	"net/http"
	"net/http/httputil"
	"net/url"
	"os"
	"path/filepath"
	"strings"

	"dtechile/nucleo/almacen"
	"dtechile/nucleo/firma"

	_ "modernc.org/sqlite"
)

// Servidor atiende las rutas portadas y reenvía el resto al motor Python.
type Servidor struct {
	cfg      *Config
	db       *sql.DB
	alm      *almacen.Almacen
	proxy    *httputil.ReverseProxy
	mux      *http.ServeMux
	fernet   *fernet
	certDemo *firma.Certificado // el de la práctica, en memoria
	rvd      *programadorRVD    // RVD diario de boletas (solo con el Go solo, sin motor Python)

	// ClaveAdminGenerada es la clave aleatoria del admin si se creó en este arranque (y solo entonces).
	ClaveAdminGenerada string
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
	fer, err := nuevoFernet(cfg.MasterKey, cfg.JWTSecret)
	if err != nil {
		return nil, err
	}
	s := &Servidor{cfg: cfg, db: db, alm: alm, mux: http.NewServeMux(), fernet: fer}
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
	if err := s.asegurarAdmin(); err != nil {
		return nil, err
	}
	s.iniciarProgramadorRVD()
	return s, nil
}

// asegurarAdmin es el arranque de main.py: si no hay ningún usuario, crea `admin` con
// ADMIN_PASSWORD o con una clave aleatoria que se registra UNA sola vez en el log.
func (s *Servidor) asegurarAdmin() error {
	var n int
	if err := s.db.QueryRow(`SELECT COUNT(*) FROM usuarios`).Scan(&n); err != nil {
		return err
	}
	if n > 0 {
		return nil
	}
	clave, generada := s.cfg.AdminPassword, false
	if clave == "" {
		b := make([]byte, 12)
		_, _ = rand.Read(b)
		clave, generada = base64.RawURLEncoding.EncodeToString(b), true
	}
	h, err := hashPassword(clave)
	if err != nil {
		return err
	}
	if _, err := s.db.Exec(`INSERT INTO usuarios (username, hashed_password, nombre_completo, email, creado_en) VALUES (?, ?, ?, ?, ?)`,
		"admin", h, "Administrador", "admin@localhost", ahoraPython()); err != nil {
		return err
	}
	s.log("USUARIO ADMIN CREADO — usuario: admin")
	if generada {
		s.log("  Password (ALEATORIA, se muestra solo esta vez): %s", clave)
		s.ClaveAdminGenerada = clave
	} else {
		s.log("  Password: la definida en ADMIN_PASSWORD")
	}
	return nil
}

// Cerrar libera la base.
func (s *Servidor) Cerrar() { s.detenerProgramadorRVD(); s.db.Close(); s.alm.Cerrar() }

// Handler es el servidor HTTP completo (con request-id, CORS y reenvío).
func (s *Servidor) Handler() http.Handler { return conRequestID(s.dominioPublico(s.cors(s.mux))) }

func (s *Servidor) rutas() {
	s.mux.HandleFunc("GET /{$}", s.raiz)
	s.rutasValores(s.mux)
	s.rutasAuth(s.mux)
	s.rutasAPIKeys(s.mux)
	s.rutasKeystore(s.mux)
	s.rutasDocumentos(s.mux)
	s.rutasSimulacion(s.mux)
	s.rutasXSD(s.mux)
	s.rutasEmision(s.mux)
	s.rutasRVD(s.mux)
	s.rutasDB(s.mux)
	s.rutasCAF(s.mux)
	s.rutasGenerar(s.mux)
	s.rutasMonitoreo(s.mux)
	s.rutasMipyme(s.mux)
	s.rutasPortal(s.mux)
	s.rutasConsulta(s.mux)
	s.rutasPortalKeystore(s.mux)
	s.mux.HandleFunc("POST /api/v1/estado/lote", s.protegido(s.estadoLote))
	var appFS http.FileSystem
	if s.cfg.AppFS != nil {
		appFS = s.cfg.AppFS
	} else if s.cfg.CarpetaApp != "" {
		if st, err := os.Stat(s.cfg.CarpetaApp); err == nil && st.IsDir() {
			appFS = http.Dir(s.cfg.CarpetaApp)
		}
	}
	if appFS != nil {
		s.mux.Handle("/app/", http.StripPrefix("/app/", http.FileServer(appFS)))
		s.mux.HandleFunc("/app", func(w http.ResponseWriter, r *http.Request) {
			http.Redirect(w, r, "/app/", http.StatusMovedPermanently)
		})
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

func (s *Servidor) log(format string, a ...any) { log.Printf(format, a...) }
