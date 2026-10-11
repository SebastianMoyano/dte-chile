package rvd

import (
	"encoding/json"
	"os"
	"reflect"
	"strings"
	"testing"

	"dtechile/nucleo/firma"
)

// El ConsumoFolios sin firmar y firmado deben ser byte a byte los de Python
// (tests/dorado/rvd/, hora fija, certificado y boletas ficticios). L15.
func TestRVDIgualAPython(t *testing.T) {
	raw, err := os.ReadFile("../../tests/dorado/rvd/entrada.json")
	if err != nil {
		t.Skip("sin corpus dorado del RVD")
	}
	var in struct {
		RutEmisor        string `json:"rut_emisor"`
		RutEnvia         string `json:"rut_envia"`
		FechaResolucion  string `json:"fecha_resolucion"`
		NumeroResolucion int    `json:"numero_resolucion"`
		Dia              string `json:"dia"`
		Tipos            []int  `json:"tipos"`
		SecEnvio         int    `json:"sec_envio"`
		Marca            string `json:"marca"`
		Documentos       []struct {
			TipoDTE     int    `json:"tipo_dte"`
			Folio       int    `json:"folio"`
			MontoNeto   int64  `json:"monto_neto"`
			IVA         int64  `json:"iva"`
			MontoExento int64  `json:"monto_exento"`
			MontoTotal  int64  `json:"monto_total"`
			Estado      string `json:"estado"`
		} `json:"documentos"`
	}
	if err := json.Unmarshal(raw, &in); err != nil {
		t.Fatal(err)
	}
	p := Parametros{RutEmisor: in.RutEmisor, RutEnvia: in.RutEnvia, FechaResolucion: in.FechaResolucion, NumeroResolucion: in.NumeroResolucion,
		Dia: in.Dia, Tipos: in.Tipos, SecEnvio: in.SecEnvio, Marca: in.Marca}
	for _, d := range in.Documentos {
		p.Documentos = append(p.Documentos, Boleta{TipoDTE: d.TipoDTE, Folio: d.Folio, MontoNeto: d.MontoNeto, IVA: d.IVA, MontoExento: d.MontoExento, MontoTotal: d.MontoTotal, Estado: d.Estado})
	}
	sinFirma, err := Generar(p)
	if err != nil {
		t.Fatal(err)
	}
	esperado, _ := os.ReadFile("../../tests/dorado/rvd/consumo_sin_firma.xml")
	// lxml.tostring(encoding=…) antepone su declaración (comillas simples); Generar no la lleva.
	comparar(t, "sin firma", sinFirma, strings.TrimPrefix(string(esperado), "<?xml version='1.0' encoding='ISO-8859-1'?>\n"))
	p12, _ := os.ReadFile("../../tests/dorado/fixtures/cert_demo.p12")
	cert, err := firma.CargarP12(p12, "demo")
	if err != nil {
		t.Fatal(err)
	}
	firmado, err := GenerarFirmado(cert, p)
	if err != nil {
		t.Fatal(err)
	}
	esperadoF, _ := os.ReadFile("../../tests/dorado/rvd/consumo_firmado.xml")
	comparar(t, "firmado", string(firmado), string(esperadoF))
}

func comparar(t *testing.T, que, got, esperado string) {
	t.Helper()
	if got == esperado {
		return
	}
	i := 0
	for i < len(got) && i < len(esperado) && got[i] == esperado[i] {
		i++
	}
	lo := max(0, i-80)
	t.Fatalf("%s difiere en el byte %d\nesperado: …%q…\nobtenido: …%q…", que, i, esperado[lo:min(len(esperado), i+80)], got[lo:min(len(got), i+80)])
}

func TestAgruparRangos(t *testing.T) {
	got := AgruparRangos([]int{5, 1, 2, 3, 7, 8, 10})
	if !reflect.DeepEqual(got, [][2]int{{1, 3}, {5, 5}, {7, 8}, {10, 10}}) {
		t.Fatalf("%v", got)
	}
	if AgruparRangos(nil) != nil {
		t.Fatal("vacío")
	}
}
