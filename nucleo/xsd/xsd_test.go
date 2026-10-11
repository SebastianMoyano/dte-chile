package xsd

import (
	"bytes"
	"compress/gzip"
	"encoding/base64"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// TestEsquemasIguales: los XSD embebidos son copias exactas de core/xsd (la fuente oficial).
func TestEsquemasIguales(t *testing.T) {
	entradas, _ := esquemasFS.ReadDir("esquemas")
	for _, e := range entradas {
		mio, _ := esquemasFS.ReadFile("esquemas/" + e.Name())
		fuente, err := os.ReadFile(filepath.Join("..", "..", "core", "xsd", e.Name()))
		if err != nil {
			t.Skipf("sin core/xsd al lado: %v", err)
		}
		if !bytes.Equal(mio, fuente) {
			t.Errorf("%s difiere de core/xsd/%s: copiarlo de nuevo", e.Name(), e.Name())
		}
	}
}

func TestCargaEsquemas(t *testing.T) {
	cargaUna.Do(cargarTodos)
	if errCarga != nil {
		t.Fatal(errCarga)
	}
	for archivo, e := range esquemas {
		t.Logf("%s: %d elementos globales, %d tipos", archivo, len(e.elementos), len(e.tipos))
	}
}

// TestCorpusDoradoValido: todos los sobres del corpus dorado son válidos (lxml también lo dice).
func TestCorpusDoradoValido(t *testing.T) {
	sobres, _ := filepath.Glob(filepath.Join("..", "..", "tests", "dorado", "esperado", "*", "envio.xml"))
	if len(sobres) == 0 {
		t.Skip("sin corpus dorado al lado")
	}
	for _, s := range sobres {
		raw, _ := os.ReadFile(s)
		r := Validar(raw)
		if !r.Valido {
			t.Errorf("%s: inválido: %v", s, r.Mensajes())
		}
	}
}

type vector struct {
	Nombre         string `json:"nombre"`
	Base           string `json:"base"`
	XMLB64         string `json:"xml_b64"`
	Valido         bool   `json:"valido"`
	TipoXML        string `json:"tipo_xml"`
	NErrores       int    `json:"n_errores"`
	PrimerElemento string `json:"primer_elemento"`
	PrimerError    string `json:"primer_error"`
	Excepcion      bool   `json:"excepcion"`
}

// TestParidadConLxml: mismo veredicto, mismo tipo_xml y mismo elemento del primer error que
// lxml para cada vector (tools/generar_xsd_vectores.py). L15: si difiere, el error está aquí.
func TestParidadConLxml(t *testing.T) {
	f, err := os.Open("testdata/vectores.json.gz")
	if err != nil {
		t.Fatal(err)
	}
	defer f.Close()
	gz, err := gzip.NewReader(f)
	if err != nil {
		t.Fatal(err)
	}
	var vectores []vector
	if err := json.NewDecoder(gz).Decode(&vectores); err != nil {
		t.Fatal(err)
	}
	ok := 0
	for _, v := range vectores {
		raw, _ := base64.StdEncoding.DecodeString(v.XMLB64)
		r := Validar(raw)
		if v.Excepcion {
			if r.Valido {
				t.Errorf("%s/%s: lxml lanzó excepción y Go lo da por válido", v.Base, v.Nombre)
				continue
			}
			ok++
			continue
		}
		if r.Valido != v.Valido || r.TipoXML != v.TipoXML {
			t.Errorf("%s/%s: Go valido=%v tipo=%s; lxml valido=%v tipo=%s\n  lxml: %s\n  go:   %s", v.Base, v.Nombre, r.Valido, r.TipoXML, v.Valido, v.TipoXML, v.PrimerError, strings.Join(r.Mensajes(), " | "))
			continue
		}
		if !v.Valido && v.PrimerElemento != "" && (len(r.Errores) == 0 || r.Errores[0].Elemento != v.PrimerElemento) {
			t.Errorf("%s/%s: primer error en distinto elemento\n  lxml: %s\n  go:   %s", v.Base, v.Nombre, v.PrimerError, strings.Join(r.Mensajes(), " | "))
			continue
		}
		ok++
	}
	t.Logf("vectores en paridad: %d de %d", ok, len(vectores))
}
