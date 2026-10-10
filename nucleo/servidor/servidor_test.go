package servidor

// Compatibilidad con Python: vectores generados con cryptography.fernet y passlib (2026-10-10).

import (
	"strings"
	"testing"
)

const (
	claveFernetPrueba = "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8="
	tokenPython       = "gAAAAABqyaqzGX45e4JtxfUl0M4d-HR5YXA7R4YEROUNU8or8ncKYcLZW6giUmUa4wzEiTzr5y1tZUmjgUKfy1zut27OJFoYwWKzxcgsltjE3um6YFx2_2o="
	hashPasslib       = "$5$rounds=535000$pQhQOPSGKmITcouG$A5K/tIlcDTz9my7b63d5nod.5..CzYzcIy.ibOkTCEA"
)

func TestFernetCompatiblePython(t *testing.T) {
	f, err := nuevoFernet(claveFernetPrueba, "")
	if err != nil {
		t.Fatal(err)
	}
	plano, err := f.Descifrar([]byte(tokenPython))
	if err != nil || string(plano) != "hola ñandú 2026" {
		t.Fatalf("descifrar token de Python: %q %v", plano, err)
	}
	tok, err := f.Cifrar([]byte("ida y vuelta ñ"))
	if err != nil {
		t.Fatal(err)
	}
	if !strings.HasPrefix(string(tok), "gAAAAA") {
		t.Fatalf("token sin la versión Fernet: %s", tok[:8])
	}
	back, err := f.Descifrar(tok)
	if err != nil || string(back) != "ida y vuelta ñ" {
		t.Fatalf("ida y vuelta: %q %v", back, err)
	}
	if _, err := f.Descifrar([]byte(string(tok[:len(tok)-5]) + "AAAA=")); err == nil {
		t.Fatal("un token manipulado debe fallar")
	}
	if _, err := nuevoFernet("", "secreto-jwt"); err != nil {
		t.Fatal("derivación desde el secreto JWT:", err)
	}
}

func TestSha256CryptCompatiblePasslib(t *testing.T) {
	if !verificarPassword("clave-de-prueba", hashPasslib) {
		t.Fatal("no verifica el hash de passlib")
	}
	if verificarPassword("otra", hashPasslib) {
		t.Fatal("verifica una clave incorrecta")
	}
	h, err := hashPassword("nueva-clave")
	if err != nil || !strings.HasPrefix(h, "$5$rounds=535000$") || !verificarPassword("nueva-clave", h) {
		t.Fatalf("hash propio: %s %v", h, err)
	}
}

func TestJWTIdaYVuelta(t *testing.T) {
	s := &Servidor{cfg: &Config{JWTSecret: "secreto-de-prueba", JWTExpiraMin: 60}}
	tok := s.crearJWT("alguien")
	if sub, ok := s.verificarJWT(tok); !ok || sub != "alguien" {
		t.Fatalf("jwt: %v %v", sub, ok)
	}
	s2 := &Servidor{cfg: &Config{JWTSecret: "otro"}}
	if _, ok := s2.verificarJWT(tok); ok {
		t.Fatal("otro secreto no debe verificar")
	}
}
