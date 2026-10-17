// Cuando algo falla: registro local y un informe que la persona ve entero antes de compartir.
// Mismo contrato que app-rs/src/informe.rs (la app Tauri). Decisión 2026-10-17: sin Sentry ni
// reportero de errores en la nube; ver docs/APP.md.
package main

import (
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"runtime"
	"runtime/debug"
	"strings"
	"time"
)

var (
	reRUT   = regexp.MustCompile(`(?i)\b(\d{1,2})\.?\d{3}\.?\d{3}-([\dk])\b`)
	reToken = regexp.MustCompile(`[A-Za-z0-9+/=_-]{40,}`)
)

// InformeProblema arma el texto de "Informar un problema": versión, sistema y las últimas
// líneas de los registros con los RUT y las claves tachados. Nunca se envía solo.
func (a *App) InformeProblema() (string, error) {
	e := a.Estado()
	return informeDe(e.Raiz, e.Version, e.Externo, e.Ambiente), nil
}

// RegistrarFalla deja en logs/app-fallas.log un error que avisa la interfaz.
func (a *App) RegistrarFalla(texto string) {
	registrarFalla(a.Estado().Raiz, "interfaz", texto)
}

// registrarCaida se difiere en main: una caída (panic) del hilo principal queda en el registro
// antes de que la app termine.
func registrarCaida(raiz func() string) {
	if r := recover(); r != nil {
		registrarFalla(raiz(), "caída de la app", fmt.Sprintf("%v\n%s", r, debug.Stack()))
		panic(r)
	}
}

func registrarFalla(raiz, origen, texto string) {
	if raiz == "" {
		return
	}
	_ = os.MkdirAll(filepath.Join(raiz, "logs"), 0o755)
	f, err := os.OpenFile(filepath.Join(raiz, "logs", "app-fallas.log"), os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0o644)
	if err != nil {
		return
	}
	defer f.Close()
	fmt.Fprintf(f, "==== %s · %s · Faro ====\n%s\n\n", time.Now().UTC().Format("2006-01-02 15:04:05 UTC"), origen, strings.TrimRight(texto, "\n"))
}

func informeDe(raiz, versionMotor string, externo bool, ambiente string) string {
	var b strings.Builder
	donde := "dentro de la app"
	if externo {
		donde = "externo"
	}
	if versionMotor == "" {
		versionMotor = "?"
	}
	if ambiente == "" {
		ambiente = "?"
	}
	fmt.Fprintf(&b, "Informe de Faro\nApp (Wails) · motor %s (%s) · ambiente %s\n", versionMotor, donde, ambiente)
	fmt.Fprintf(&b, "Sistema: %s %s\nFecha: %s\n", runtime.GOOS, runtime.GOARCH, time.Now().UTC().Format("2006-01-02 15:04:05 UTC"))
	if raiz == "" {
		b.WriteString("\n(el motor no llegó a arrancar: no hay carpeta de datos ni registros)\n")
		return b.String()
	}
	for _, s := range []struct {
		titulo, archivo string
		n               int
	}{{"Fallas registradas", "app-fallas.log", 80}, {"Registro del motor", "app-motor.log", 120}} {
		fmt.Fprintf(&b, "\n== %s (logs/%s, últimas %d líneas) ==\n", s.titulo, s.archivo, s.n)
		if t := cola(filepath.Join(raiz, "logs", s.archivo), s.n); strings.TrimSpace(t) != "" {
			b.WriteString(tachar(t))
		} else {
			b.WriteString("(nada)\n")
		}
	}
	b.WriteString("\nLos RUT y las claves aparecen tachados. Nada de esto se envió: lo compartes tú.\n")
	return b.String()
}

// tachar deja de un RUT solo los dos primeros dígitos y el verificador, y tapa las cadenas
// largas que parecen claves o tokens.
func tachar(t string) string {
	return reToken.ReplaceAllString(reRUT.ReplaceAllString(t, "$1.***.***-$2"), "[clave tachada]")
}

func cola(ruta string, n int) string {
	datos, err := os.ReadFile(ruta)
	if err != nil {
		return ""
	}
	lineas := strings.Split(strings.TrimRight(string(datos), "\n"), "\n")
	if len(lineas) > n {
		lineas = lineas[len(lineas)-n:]
	}
	return strings.Join(lineas, "\n") + "\n"
}
