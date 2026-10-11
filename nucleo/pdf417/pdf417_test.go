package pdf417

import (
	"encoding/json"
	"os"
	"reflect"
	"testing"
)

// TestParidadConPython: las filas de códigos deben ser idénticas a las de pdf417gen para cada
// vector (testdata/vectores.json, generado por tools/generar_pdf417.py). L15: si difiere, el
// error está aquí; los vectores no se tocan.
func TestParidadConPython(t *testing.T) {
	b, err := os.ReadFile("testdata/vectores.json")
	if err != nil {
		t.Fatal(err)
	}
	var vec []struct {
		Datos     string  `json:"datos"`
		Columnas  int     `json:"columnas"`
		Seguridad int     `json:"seguridad"`
		Filas     [][]int `json:"filas"`
		Error     string  `json:"error"`
	}
	if err := json.Unmarshal(b, &vec); err != nil {
		t.Fatal(err)
	}
	ok := 0
	for i, v := range vec {
		filas, err := Codificar([]byte(v.Datos), v.Columnas, v.Seguridad)
		if v.Error != "" {
			if err == nil {
				t.Errorf("vector %d (%d cols, sec %d): Python falló (%s) y Go no", i, v.Columnas, v.Seguridad, v.Error)
			}
			continue
		}
		if err != nil {
			t.Errorf("vector %d: %v", i, err)
			continue
		}
		if !reflect.DeepEqual(filas, v.Filas) {
			t.Errorf("vector %d (%d bytes, %d cols, sec %d): filas distintas (go %d filas, py %d)", i, len(v.Datos), v.Columnas, v.Seguridad, len(filas), len(v.Filas))
			continue
		}
		ok++
	}
	t.Logf("vectores idénticos: %d de %d", ok, len(vec))
	img := Imagen(mustEncode(t, "hola mundo"), 2, 3, 20)
	if img.Bounds().Dx() != (16*17+1)*2+40 {
		t.Fatalf("ancho de imagen: %d", img.Bounds().Dx())
	}
}

func mustEncode(t *testing.T, s string) [][]int {
	f, err := Codificar([]byte(s), 12, 5)
	if err != nil {
		t.Fatal(err)
	}
	return f
}
