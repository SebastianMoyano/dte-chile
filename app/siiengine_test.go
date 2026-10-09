package main

// Prueba en vivo (solo lectura en el SII, sin gastar folio) del binding SIIEngineFactura en
// modo dry-run, contra un motor levantado aparte. Se salta sin las variables:
//   APP_TEST_MOTOR_URL   http://127.0.0.1:8771        APP_TEST_MOTOR_CLAVE  (la APP_SHELL_KEY del motor)
//   APP_TEST_SII_EMPRESA 77.777.777-7                 APP_TEST_SII_USUARIO  12.345.678-5
//   APP_TEST_SII_TRIB / APP_TEST_SII_CERT             claves (del Llavero, nunca escritas aquí)
//   APP_TEST_SII_DOC     JSON del documento (receptor, item, fecha, forma_pago)

import (
	"encoding/json"
	"net/http"
	"os"
	"testing"
	"time"
)

func TestSIIEngineFacturaDryRun(t *testing.T) {
	u, k := os.Getenv("APP_TEST_MOTOR_URL"), os.Getenv("APP_TEST_MOTOR_CLAVE")
	if u == "" || k == "" || os.Getenv("APP_TEST_SII_DOC") == "" {
		t.Skip("sin motor/claves de prueba (APP_TEST_*)")
	}
	a := &App{motor: &Motor{URL: u, Clave: k}, http: &http.Client{Timeout: 120 * time.Second}}
	out, err := a.SIIEngineFactura(os.Getenv("APP_TEST_SII_EMPRESA"), os.Getenv("APP_TEST_SII_USUARIO"),
		os.Getenv("APP_TEST_SII_TRIB"), os.Getenv("APP_TEST_SII_CERT"), false, os.Getenv("APP_TEST_SII_DOC"), false)
	if err != nil {
		t.Fatal(err)
	}
	var v struct {
		DryRun     bool   `json:"dry_run"`
		Tipo       int    `json:"tipo"`
		MontoTotal int64  `json:"monto_total"`
		Verificada bool   `json:"cadena_verificada"`
		Fecha      string `json:"fecha"`
		Receptor   struct {
			RazonSocial string `json:"razon_social"`
		} `json:"receptor"`
	}
	if err := json.Unmarshal([]byte(out), &v); err != nil {
		t.Fatal(err)
	}
	if !v.DryRun || v.Tipo != 34 || v.MontoTotal <= 0 || v.Receptor.RazonSocial == "" {
		t.Fatalf("dry-run inesperado: %s", out)
	}
	t.Logf("dry-run OK: tipo %d, total %d, fecha %s, verificada=%v", v.Tipo, v.MontoTotal, v.Fecha, v.Verificada)
	// Emitir sin cadena verificada debe negarse ANTES de abrir sesión.
	if !v.Verificada {
		if _, err := a.SIIEngineFactura(os.Getenv("APP_TEST_SII_EMPRESA"), os.Getenv("APP_TEST_SII_USUARIO"),
			os.Getenv("APP_TEST_SII_TRIB"), os.Getenv("APP_TEST_SII_CERT"), false, os.Getenv("APP_TEST_SII_DOC"), true); err == nil {
			t.Fatal("emitir con cadena no verificada debió fallar")
		}
	}
}
