package main

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"errors"
	"fmt"
	"io/fs"
	"log"
	"net"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"time"

	"dtechile/nucleo/cliutil"
	"dtechile/nucleo/servidor"
)

// Motor es el motor que esta app arranca y supervisa. Desde la fase 7 del port el motor es
// `nucleo/servidor` EN ESTE PROCESO (sin Python): escucha en un puerto libre de 127.0.0.1 con
// una clave efímera (APP_SHELL_KEY) y la interfaz le habla por HTTP a través de `App.API`.
//
// Modos:
//   - go (normal): en desarrollo usa el repo (su .env, base y storage); empaquetado, la carpeta
//     de datos del usuario. Sin procesos hijos.
//   - python (DTE_MOTOR=python): el sidecar de antes (uvicorn main:app del repo, o el motor
//     PyInstaller si viene en el bundle). Queda para comparar durante la transición.
//   - externo: si existen DTE_API_URL (y DTE_API_KEY), no arranca nada y habla con ese motor.
type Motor struct {
	Raiz        string // repo (desarrollo) o carpeta de datos (empaquetado)
	URL         string
	Clave       string
	Externo     bool
	Empaquetado bool   // sin repo al lado: datos en la carpeta del usuario
	Go          bool   // el motor corre en este proceso (nucleo/servidor)
	ClaveAdmin  string // clave del usuario admin del panel web (solo empaquetado; del .env de datos)
	LogPath     string
	cmd         *exec.Cmd
	logF        *os.File
	srv         *servidor.Servidor
	httpSrv     *http.Server
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

// motorEmpaquetado devuelve la ruta del motor Python congelado (PyInstaller) si la app lo
// lleva dentro (modo python). "" si no está.
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

// Iniciar arranca (o conecta) el motor y espera a que responda en "/".
func (m *Motor) Iniciar(ctx context.Context) error {
	if u := os.Getenv("DTE_API_URL"); u != "" {
		m.URL = strings.TrimRight(u, "/")
		m.Clave = os.Getenv("DTE_API_KEY")
		m.Externo = true
		return m.esperar(ctx, 20*time.Second)
	}
	if os.Getenv("DTE_MOTOR") == "python" {
		return m.iniciarPython(ctx)
	}
	return m.iniciarGo(ctx)
}

// iniciarGo levanta nucleo/servidor en este proceso. Con repo al lado (desarrollo) usa su
// .env, base y storage; si no, la carpeta de datos del usuario (empaquetado).
func (m *Motor) iniciarGo(ctx context.Context) error {
	raiz, err := localizarRaiz()
	if err != nil || os.Getenv("DTE_DATOS") != "" {
		d, err := cliutil.CarpetaDatos()
		if err != nil {
			return err
		}
		admin, err := cliutil.AsegurarEnv(d)
		if err != nil {
			return err
		}
		m.Empaquetado, m.ClaveAdmin, raiz = true, admin, d
	}
	m.Raiz, m.Go = raiz, true
	cfg, err := servidor.CargarConfig(filepath.Join(raiz, ".env"))
	if err != nil {
		return err
	}
	// Python resolvía las rutas relativas desde su cwd (la raíz); aquí no hay cwd que valga.
	if !filepath.IsAbs(cfg.DatabasePath) {
		cfg.DatabasePath = filepath.Join(raiz, cfg.DatabasePath)
	}
	if !filepath.IsAbs(cfg.StoragePath) {
		cfg.StoragePath = filepath.Join(raiz, cfg.StoragePath)
	}
	m.Clave = claveEfimera()
	cfg.AppShellKey = m.Clave
	cfg.MotorPython = os.Getenv("DTE_MOTOR_PYTHON") // "" = nada reenviado
	if sub, err := fs.Sub(assets, "frontend/dist"); err == nil {
		cfg.AppFS = http.FS(sub) // la misma interfaz, en el navegador (/app)
	}
	_ = os.MkdirAll(filepath.Join(raiz, "logs"), 0o755)
	m.LogPath = filepath.Join(raiz, "logs", "app-motor.log")
	m.logF, err = os.OpenFile(m.LogPath, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0o644)
	if err != nil {
		return err
	}
	log.SetOutput(m.logF)
	port, err := puertoLibre()
	if err != nil {
		return err
	}
	m.URL = "http://127.0.0.1:" + strconv.Itoa(port)
	fmt.Fprintf(m.logF, "\n==== %s arranque motor Go en %s (base %s) ====\n", time.Now().Format(time.RFC3339), m.URL, cfg.DatabasePath)
	s, err := servidor.Nuevo(cfg)
	if err != nil {
		return fmt.Errorf("no pude arrancar el motor: %w", err)
	}
	if s.ClaveAdminGenerada != "" && m.ClaveAdmin == "" {
		m.ClaveAdmin = s.ClaveAdminGenerada
	}
	m.srv = s
	l, err := net.Listen("tcp", "127.0.0.1:"+strconv.Itoa(port))
	if err != nil {
		s.Cerrar()
		return err
	}
	m.httpSrv = &http.Server{Handler: s.Handler(), ReadHeaderTimeout: 10 * time.Second}
	go func() { _ = m.httpSrv.Serve(l) }()
	return m.esperar(ctx, 20*time.Second)
}

// iniciarPython es el sidecar de antes (uvicorn del repo o el motor PyInstaller del bundle).
func (m *Motor) iniciarPython(ctx context.Context) error {
	var programa []string
	var raiz string
	if emp := motorEmpaquetado(); emp != "" {
		d, err := cliutil.CarpetaDatos()
		if err != nil {
			return err
		}
		admin, err := cliutil.AsegurarEnv(d)
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
	fmt.Fprintf(m.logF, "\n==== %s arranque motor Python en %s ====\n", time.Now().Format(time.RFC3339), m.URL)

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

// Detener cierra el motor con cuidado: el Go en proceso (apaga el HTTP, el programador y la
// base); el sidecar Python con SIGINT y, si no responde en 5 s, lo mata.
func (m *Motor) Detener() {
	if m.httpSrv != nil {
		ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		_ = m.httpSrv.Shutdown(ctx)
		cancel()
		m.httpSrv = nil
	}
	if m.srv != nil {
		m.srv.Cerrar()
		m.srv = nil
	}
	if m.cmd != nil && m.cmd.Process != nil {
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
		m.cmd = nil
	}
	if m.logF != nil {
		m.logF.Close()
		m.logF = nil
	}
}
