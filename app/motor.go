package main

import (
	"context"
	"crypto/rand"
	"encoding/base64"
	"encoding/hex"
	"errors"
	"fmt"
	"net"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"time"
)

// Motor es el proceso Python (uvicorn main:app) que esta app arranca y supervisa.
//
// Dos modos:
//   - sidecar (normal): localiza la raíz del repo, usa su `.venv` y arranca uvicorn en un
//     puerto libre con una clave efímera en APP_SHELL_KEY.
//   - externo: si existen DTE_API_URL (y DTE_API_KEY), no arranca nada y habla con ese motor
//     (sirve para desarrollo y para el motor desplegado en otra máquina).
type Motor struct {
	Raiz        string // repo (desarrollo) o carpeta de datos (empaquetado)
	URL         string
	Clave       string
	Externo     bool
	Empaquetado bool   // el motor viene dentro de la app (PyInstaller)
	ClaveAdmin  string // clave del usuario admin del panel web (solo empaquetado; del .env de datos)
	LogPath     string
	cmd         *exec.Cmd
	logF        *os.File
}

// localizarRaiz busca la carpeta que tiene `main.py` y `core/`: DTE_REPO, o subiendo desde
// el ejecutable y desde el cwd (hasta 6 niveles).
func localizarRaiz() (string, error) {
	if r := os.Getenv("DTE_REPO"); r != "" {
		if esRaiz(r) {
			return r, nil
		}
		return "", fmt.Errorf("DTE_REPO=%s no contiene main.py y core/", r)
	}
	inicios := []string{}
	if exe, err := os.Executable(); err == nil {
		inicios = append(inicios, filepath.Dir(exe))
	}
	if wd, err := os.Getwd(); err == nil {
		inicios = append(inicios, wd)
	}
	for _, ini := range inicios {
		d := ini
		for i := 0; i < 6; i++ {
			if esRaiz(d) {
				return d, nil
			}
			p := filepath.Dir(d)
			if p == d {
				break
			}
			d = p
		}
	}
	return "", errors.New("no encontré el motor (main.py + core/). Define DTE_REPO con la ruta del repo")
}

func esRaiz(d string) bool {
	if st, err := os.Stat(filepath.Join(d, "main.py")); err != nil || st.IsDir() {
		return false
	}
	st, err := os.Stat(filepath.Join(d, "core"))
	return err == nil && st.IsDir()
}

func pythonDe(raiz string) string {
	cands := []string{
		filepath.Join(raiz, ".venv", "bin", "python"),
		filepath.Join(raiz, ".venv", "Scripts", "python.exe"),
	}
	for _, c := range cands {
		if _, err := os.Stat(c); err == nil {
			return c
		}
	}
	if p, err := exec.LookPath("python3"); err == nil {
		return p
	}
	return "python"
}

func puertoLibre() (int, error) {
	l, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		return 0, err
	}
	defer l.Close()
	return l.Addr().(*net.TCPAddr).Port, nil
}

func claveEfimera() string {
	b := make([]byte, 24)
	_, _ = rand.Read(b)
	return "app_" + hex.EncodeToString(b)
}

// motorEmpaquetado devuelve la ruta del motor congelado (PyInstaller) si la app lo lleva
// dentro: macOS → Contents/Resources/motor/motor; Windows/Linux → motor/motor(.exe) junto
// al ejecutable. "" si no está (modo desarrollo: se usa el repo y su .venv).
func motorEmpaquetado() string {
	exe, err := os.Executable()
	if err != nil {
		return ""
	}
	dir := filepath.Dir(exe)
	cands := []string{
		filepath.Join(dir, "..", "Resources", "motor", "motor"),
		filepath.Join(dir, "motor", "motor"),
		filepath.Join(dir, "motor", "motor.exe"),
	}
	for _, c := range cands {
		if st, err := os.Stat(c); err == nil && !st.IsDir() {
			return c
		}
	}
	return ""
}

// carpetaDatos es donde vive todo lo que la app escribe cuando va empaquetada:
// ~/Library/Application Support/DTE Chile (macOS), %AppData%\DTE Chile, ~/.config/DTE Chile.
func carpetaDatos() (string, error) {
	base, err := os.UserConfigDir()
	if err != nil {
		return "", err
	}
	d := filepath.Join(base, "DTE Chile")
	for _, sub := range []string{"", "logs", "storage"} {
		if err := os.MkdirAll(filepath.Join(d, sub), 0o755); err != nil {
			return "", err
		}
	}
	return d, nil
}

// asegurarEnv crea el `.env` de la carpeta de datos la primera vez, con secretos generados
// aquí (JWT y clave maestra del keystore) y la clave del usuario admin del panel web. Si ya
// existe no se toca: ahí vive la configuración del usuario.
func asegurarEnv(dir string) (string, error) {
	ruta := filepath.Join(dir, ".env")
	if b, err := os.ReadFile(ruta); err == nil {
		return claveAdminDe(string(b)), nil
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

func claveAdminDe(env string) string {
	for _, l := range strings.Split(env, "\n") {
		if strings.HasPrefix(l, "ADMIN_PASSWORD=") {
			return strings.TrimSpace(strings.TrimPrefix(l, "ADMIN_PASSWORD="))
		}
	}
	return ""
}

// Iniciar arranca (o conecta) el motor y espera a que responda en "/".
func (m *Motor) Iniciar(ctx context.Context) error {
	if u := os.Getenv("DTE_API_URL"); u != "" {
		m.URL = strings.TrimRight(u, "/")
		m.Clave = os.Getenv("DTE_API_KEY")
		m.Externo = true
		return m.esperar(ctx, 20*time.Second)
	}
	var programa []string
	var raiz string
	if emp := motorEmpaquetado(); emp != "" {
		d, err := carpetaDatos()
		if err != nil {
			return err
		}
		admin, err := asegurarEnv(d)
		if err != nil {
			return err
		}
		m.Empaquetado, m.ClaveAdmin, raiz = true, admin, d
		programa = []string{emp}
	} else {
		r, err := localizarRaiz()
		if err != nil {
			return err
		}
		raiz = r
		programa = []string{pythonDe(raiz), "-m", "uvicorn", "main:app"}
	}
	m.Raiz = raiz
	port, err := puertoLibre()
	if err != nil {
		return err
	}
	m.Clave = claveEfimera()
	m.URL = "http://127.0.0.1:" + strconv.Itoa(port)

	_ = os.MkdirAll(filepath.Join(raiz, "logs"), 0o755)
	m.LogPath = filepath.Join(raiz, "logs", "app-motor.log")
	m.logF, err = os.OpenFile(m.LogPath, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0o644)
	if err != nil {
		return err
	}
	fmt.Fprintf(m.logF, "\n==== %s arranque motor en %s ====\n", time.Now().Format(time.RFC3339), m.URL)

	// Sin CommandContext: el contexto de Wails se cancela antes de OnShutdown y mataría el
	// motor sin dejarnos cerrarlo con cuidado. Detener() se encarga.
	args := append(programa[1:], "--host", "127.0.0.1", "--port", strconv.Itoa(port), "--log-level", "info")
	cmd := exec.Command(programa[0], args...)
	cmd.Dir = raiz // el motor resuelve .env, base, storage y logs desde aquí
	cmd.Env = append(os.Environ(), "APP_SHELL_KEY="+m.Clave, "PYTHONUNBUFFERED=1")
	cmd.Stdout, cmd.Stderr = m.logF, m.logF
	if err := cmd.Start(); err != nil {
		return fmt.Errorf("no pude arrancar python: %w", err)
	}
	m.cmd = cmd

	salida := make(chan error, 1)
	go func() { salida <- cmd.Wait() }()

	plazo := time.After(90 * time.Second)
	tick := time.NewTicker(300 * time.Millisecond)
	defer tick.Stop()
	for {
		select {
		case err := <-salida:
			m.cmd = nil
			return fmt.Errorf("el motor terminó antes de responder (%v). Revisa %s", err, m.LogPath)
		case <-plazo:
			return fmt.Errorf("el motor no respondió en 90 s. Revisa %s", m.LogPath)
		case <-ctx.Done():
			return ctx.Err()
		case <-tick.C:
			if m.vivo() {
				return nil
			}
		}
	}
}

func (m *Motor) esperar(ctx context.Context, max time.Duration) error {
	plazo := time.After(max)
	for {
		if m.vivo() {
			return nil
		}
		select {
		case <-plazo:
			return fmt.Errorf("el motor en %s no responde", m.URL)
		case <-ctx.Done():
			return ctx.Err()
		case <-time.After(300 * time.Millisecond):
		}
	}
}

func (m *Motor) vivo() bool {
	c := http.Client{Timeout: 2 * time.Second}
	r, err := c.Get(m.URL + "/")
	if err != nil {
		return false
	}
	r.Body.Close()
	return r.StatusCode == 200
}

// Detener cierra el motor con cuidado (SIGINT → uvicorn apaga programadores y BD) y si no
// responde en 5 s lo mata.
func (m *Motor) Detener() {
	if m.cmd == nil || m.cmd.Process == nil {
		return
	}
	done := make(chan struct{})
	go func() { _, _ = m.cmd.Process.Wait(); close(done) }()
	if runtime.GOOS != "windows" {
		_ = m.cmd.Process.Signal(os.Interrupt)
	} else {
		_ = m.cmd.Process.Kill()
	}
	select {
	case <-done:
	case <-time.After(5 * time.Second):
		_ = m.cmd.Process.Kill()
	}
	if m.logF != nil {
		m.logF.Close()
	}
	m.cmd = nil
}
