package firma

import (
	"os"
	"testing"
)

// El certificado cargado desde PEM (lo que entrega el keystore del motor) debe ser el mismo
// que el cargado desde el .p12: mismo RUT, misma clave, misma firma.
func TestCargarPEMEquivaleAP12(t *testing.T) {
	p12, err := os.ReadFile("../../tests/dorado/fixtures/cert_demo.p12")
	if err != nil {
		t.Skip("sin fixtures")
	}
	a, err := CargarP12(p12, "demo")
	if err != nil {
		t.Fatal(err)
	}
	cp, _ := os.ReadFile("../../tests/dorado/fixtures/cert_demo.cert.pem")
	kp, _ := os.ReadFile("../../tests/dorado/fixtures/cert_demo.key.pem")
	b, err := CargarPEM(cp, kp)
	if err != nil {
		t.Fatal(err)
	}
	ra, _ := a.RutEmisor()
	rb, _ := b.RutEmisor()
	if ra != rb || ra != "12345678-5" {
		t.Fatalf("RUT distinto: %s vs %s", ra, rb)
	}
	if a.Clave.N.Cmp(b.Clave.N) != 0 || string(a.Cert.Raw) != string(b.Cert.Raw) {
		t.Fatal("clave o certificado distintos entre p12 y PEM")
	}
	sa, _ := a.firmar([]byte("hola"))
	sb, _ := b.firmar([]byte("hola"))
	if string(sa) != string(sb) {
		t.Fatal("la firma RSA-SHA1 difiere (debería ser determinista e idéntica)")
	}
}
