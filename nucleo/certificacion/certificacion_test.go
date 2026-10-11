package certificacion

import (
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"testing"

	"dtechile/nucleo/firma"
	"dtechile/nucleo/ted"
)

// TestCasosIguales: casos.json embebido == tests/dorado/certificacion/casos.json (la fuente).
func TestCasosIguales(t *testing.T) {
	fuente, err := os.ReadFile("../../tests/dorado/certificacion/casos.json")
	if err != nil {
		t.Skip("sin corpus del set")
	}
	if !bytes.Equal(fuente, casosJSON) {
		t.Fatal("casos.json difiere de tests/dorado/certificacion/casos.json: copiarlo de nuevo")
	}
}

// TestSetIgualAPython: los 16 sobres del set, byte a byte como certificacion_sii.generar_dte
// con el certificado y los CAF ficticios y hora fija. L15.
func TestSetIgualAPython(t *testing.T) {
	raw, err := os.ReadFile("../../tests/dorado/certificacion/parametros.json")
	if err != nil {
		t.Skip("sin corpus del set")
	}
	var p struct {
		Fecha, Marca, Rut, RazonSocial, Email string `json:",omitempty"`
	}
	var pm map[string]string
	_ = json.Unmarshal(raw, &pm)
	p.Fecha, p.Marca, p.Rut, p.RazonSocial, p.Email = pm["fecha"], pm["marca"], pm["rut"], pm["razon_social"], pm["email"]
	p12, _ := os.ReadFile("../../tests/dorado/fixtures/cert_demo.p12")
	cert, err := firma.CargarP12(p12, "demo")
	if err != nil {
		t.Fatal(err)
	}
	cafs := map[int]*ted.CAF{}
	for _, tipo := range []int{33, 34, 56, 61} {
		b, _ := os.ReadFile(filepath.Join("..", "..", "tests", "dorado", "fixtures", "caf_"+itoa(tipo)+".xml"))
		c, err := ted.ParsearCAF(string(b))
		if err != nil {
			t.Fatal(err)
		}
		cafs[tipo] = c
	}
	casos, err := Casos()
	if err != nil {
		t.Fatal(err)
	}
	if len(casos) != 16 {
		t.Fatalf("%d casos", len(casos))
	}
	e := Emisor{Rut: p.Rut, RazonSocial: p.RazonSocial, Email: p.Email}
	ok := 0
	for _, c := range casos {
		got, _, err := Generar(c, e, cafs[c.TipoDTE], cert, p.Fecha, p.Marca)
		if err != nil {
			t.Errorf("%s: %v", c.Nombre, err)
			continue
		}
		esperado, err := os.ReadFile(filepath.Join("..", "..", "tests", "dorado", "certificacion", "esperado", NombreArchivo(c)+".xml"))
		if err != nil {
			t.Errorf("%s: sin esperado", c.Nombre)
			continue
		}
		if !bytes.Equal(got, esperado) {
			i := 0
			for i < len(got) && i < len(esperado) && got[i] == esperado[i] {
				i++
			}
			lo := max(0, i-80)
			t.Errorf("%s difiere en el byte %d\n  esperado: …%q…\n  obtenido: …%q…", c.Nombre, i, esperado[lo:min(len(esperado), i+80)], got[lo:min(len(got), i+80)])
			continue
		}
		ok++
	}
	t.Logf("casos idénticos: %d de %d", ok, len(casos))
}

func itoa(n int) string {
	s := ""
	for n > 0 {
		s = string(rune('0'+n%10)) + s
		n /= 10
	}
	return s
}
