package servidor

import (
	"bytes"
	"os"
	"path/filepath"
	"testing"
)

// TestStaticIgual: las páginas del panel embebidas son copias exactas de static/ del repo.
func TestStaticIgual(t *testing.T) {
	entradas, _ := staticFS.ReadDir("static")
	for _, e := range entradas {
		mio, _ := staticFS.ReadFile("static/" + e.Name())
		fuente, err := os.ReadFile(filepath.Join("..", "..", "static", e.Name()))
		if err != nil {
			t.Skipf("sin static/ al lado: %v", err)
		}
		if !bytes.Equal(mio, fuente) {
			t.Errorf("%s difiere de static/%s: copiarlo de nuevo", e.Name(), e.Name())
		}
	}
}
