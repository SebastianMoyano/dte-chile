package sii

import (
	"os"
	"strings"
	"testing"

	"dtechile/nucleo/firma"
)

// La semilla firmada debe ser byte a byte la de Python (tests/dorado/sii/semilla_firmada.xml).
func TestFirmarSemillaIgualAPython(t *testing.T) {
	p12, err := os.ReadFile("../../tests/dorado/fixtures/cert_demo.p12")
	if err != nil {
		t.Skip("sin fixtures")
	}
	cert, err := firma.CargarP12(p12, "demo")
	if err != nil {
		t.Fatal(err)
	}
	sem, _ := os.ReadFile("../../tests/dorado/sii/semilla.txt")
	esperado, err := os.ReadFile("../../tests/dorado/sii/semilla_firmada.xml")
	if err != nil {
		t.Skip("sin esperado")
	}
	got, err := FirmarSemilla(cert, strings.TrimSpace(string(sem)))
	if err != nil {
		t.Fatal(err)
	}
	if got != string(esperado) {
		i := 0
		for i < len(got) && i < len(esperado) && got[i] == esperado[i] {
			i++
		}
		lo := max(0, i-60)
		t.Fatalf("difiere en el byte %d\nesperado: …%q…\nobtenido: …%q…", i, string(esperado[lo:min(len(esperado), i+60)]), got[lo:min(len(got), i+60)])
	}
}

// La semilla firmada del REST de boletas (compacta) también debe ser byte a byte la de Python.
func TestFirmarSemillaBoletaIgualAPython(t *testing.T) {
	p12, err := os.ReadFile("../../tests/dorado/fixtures/cert_demo.p12")
	if err != nil {
		t.Skip("sin fixtures")
	}
	cert, err := firma.CargarP12(p12, "demo")
	if err != nil {
		t.Fatal(err)
	}
	sem, _ := os.ReadFile("../../tests/dorado/sii/semilla.txt")
	esperado, err := os.ReadFile("../../tests/dorado/sii/semilla_firmada_boleta.xml")
	if err != nil {
		t.Skip("sin esperado")
	}
	got, err := FirmarSemillaBoleta(cert, strings.TrimSpace(string(sem)))
	if err != nil {
		t.Fatal(err)
	}
	if got != string(esperado) {
		i := 0
		for i < len(got) && i < len(esperado) && got[i] == esperado[i] {
			i++
		}
		lo := max(0, i-60)
		t.Fatalf("difiere en el byte %d\nesperado: …%q…\nobtenido: …%q…", i, string(esperado[lo:min(len(esperado), i+60)]), got[lo:min(len(got), i+60)])
	}
	if textoDe("<x><ESTADO>00</ESTADO><SEMILLA> 123 </SEMILLA></x>", "SEMILLA") != "123" {
		t.Fatal("textoDe")
	}
}
