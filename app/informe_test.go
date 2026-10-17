package main

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestTachar(t *testing.T) {
	got := tachar("emisor 76.111.111-6 y 12345678-5; clave app_0123456789abcdef0123456789abcdef0123456789abcdef fin")
	want := "emisor 76.***.***-6 y 12.***.***-5; clave [clave tachada] fin"
	if got != want {
		t.Fatalf("tachar: %q", got)
	}
	if tachar("folio 1234 total 1190") != "folio 1234 total 1190" {
		t.Fatal("tachó de más")
	}
}

func TestInformeProblema(t *testing.T) {
	d := t.TempDir()
	os.MkdirAll(filepath.Join(d, "logs"), 0o755)
	var sb strings.Builder
	for i := 1; i <= 200; i++ {
		fmt.Fprintf(&sb, "linea %d rut 77777777-7\n", i)
	}
	os.WriteFile(filepath.Join(d, "logs", "app-motor.log"), []byte(sb.String()), 0o644)
	registrarFalla(d, "interfaz", "TypeError: x is not a function\n  at app.js:10")
	inf := informeDe(d, "1.1.0", false, "certificacion")
	for _, s := range []string{"Informe de Faro\nApp (Wails) · motor 1.1.0 (dentro de la app) · ambiente certificacion",
		"== Fallas registradas", "TypeError: x is not a function", "linea 200 rut 77.***.***-7", "Nada de esto se envió"} {
		if !strings.Contains(inf, s) {
			t.Fatalf("falta %q en:\n%s", s, inf)
		}
	}
	if strings.Contains(inf, "77777777-7") || strings.Contains(inf, "linea 80 ") {
		t.Fatal("el informe no tacha o no recorta")
	}
	if !strings.Contains(informeDe("", "", true, ""), "no llegó a arrancar") {
		t.Fatal("sin carpeta de datos debe decirlo")
	}
}
