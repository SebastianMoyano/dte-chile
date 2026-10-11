package main

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// TestMotorGoEnProceso: la app arranca nucleo/servidor sin Python sobre una carpeta de datos
// vacía (como la app empaquetada la primera vez): crea .env, base, admin, y responde con la
// clave efímera; sin clave, 401; la interfaz se sirve en /app/.
func TestMotorGoEnProceso(t *testing.T) {
	datos := t.TempDir()
	t.Setenv("DTE_DATOS", datos)
	t.Setenv("DTE_MOTOR", "")
	t.Setenv("DTE_API_URL", "")
	m := &Motor{}
	if err := m.Iniciar(context.Background()); err != nil {
		t.Fatal(err)
	}
	defer m.Detener()
	if !m.Go || !m.Empaquetado || m.ClaveAdmin == "" {
		t.Fatalf("modo: go=%v empaquetado=%v admin=%v", m.Go, m.Empaquetado, m.ClaveAdmin != "")
	}
	for _, f := range []string{".env", "dte_database.db", "logs/app-motor.log"} {
		if _, err := os.Stat(filepath.Join(datos, f)); err != nil {
			t.Errorf("falta %s: %v", f, err)
		}
	}
	pedir := func(ruta, clave string) (int, string) {
		req, _ := http.NewRequest("GET", m.URL+ruta, nil)
		if clave != "" {
			req.Header.Set("Authorization", "Bearer "+clave)
		}
		r, err := http.DefaultClient.Do(req)
		if err != nil {
			t.Fatal(err)
		}
		defer r.Body.Close()
		b, _ := io.ReadAll(r.Body)
		return r.StatusCode, string(b)
	}
	if st, cuerpo := pedir("/", ""); st != 200 || !strings.Contains(cuerpo, `"status":"ok"`) {
		t.Fatalf("/: %d %s", st, cuerpo)
	}
	if st, _ := pedir("/api/v1/dte/documentos", ""); st != 401 {
		t.Fatalf("sin clave debería ser 401, fue %d", st)
	}
	st, cuerpo := pedir("/api/v1/dte/documentos", m.Clave)
	if st != 200 {
		t.Fatalf("con clave: %d %s", st, cuerpo)
	}
	// el admin del .env sirve para entrar al panel web (login por JWT)
	login, _ := json.Marshal(map[string]string{"username": "admin", "password": m.ClaveAdmin})
	r, err := http.Post(m.URL+"/api/v1/auth/login", "application/json", strings.NewReader(string(login)))
	if err != nil {
		t.Fatal(err)
	}
	r.Body.Close()
	if r.StatusCode != 200 {
		t.Fatalf("login admin: %d", r.StatusCode)
	}
	if st, cuerpo := pedir("/app/", ""); st != 200 || !strings.Contains(cuerpo, "<html") {
		t.Fatalf("/app/: %d %.100s", st, cuerpo)
	}
	// la práctica completa, sin Python: emitir una boleta y dibujar su PDF
	cuerpoEmitir, _ := json.Marshal(map[string]any{"tipo_dte": 39, "items": []map[string]any{{"nombre": "Café", "precio_unitario": 1190}}})
	req, _ := http.NewRequest("POST", m.URL+"/api/v1/simulacion/emitir", strings.NewReader(string(cuerpoEmitir)))
	req.Header.Set("Authorization", "Bearer "+m.Clave)
	req.Header.Set("Content-Type", "application/json")
	r, err = http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	b, _ := io.ReadAll(r.Body)
	r.Body.Close()
	if r.StatusCode != 200 || !strings.Contains(string(b), `"pdf_path"`) {
		t.Fatalf("práctica: %d %s", r.StatusCode, string(b))
	}
	m.Detener()
	if m.vivo() {
		t.Fatal("el motor sigue vivo tras Detener")
	}
}
