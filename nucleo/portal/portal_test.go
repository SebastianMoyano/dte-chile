package portal

import (
	"encoding/json"
	"os"
	"reflect"
	"testing"
)

// TestParidadConPython: parsers y diagnóstico sobre el mismo HTML sintético y los mismos dobles
// que tests/dorado/portal/generar_esperado.py. L15.
func TestParidadConPython(t *testing.T) {
	rawHTML, err := os.ReadFile("../../tests/dorado/portal/html.json")
	if err != nil {
		t.Skip("sin corpus del portal")
	}
	var h map[string]string
	if err := json.Unmarshal(rawHTML, &h); err != nil {
		t.Fatal(err)
	}
	rawEsp, _ := os.ReadFile("../../tests/dorado/portal/esperado.json")
	var esp map[string]any
	if err := json.Unmarshal(rawEsp, &esp); err != nil {
		t.Fatal(err)
	}
	got := map[string]any{}
	got["empresa_autorizada"] = ParsearEmpresaAutorizada(h["ee_empresa_rut"], "77.777.777-7")
	got["empresa_no_autorizada"] = ParsearEmpresaAutorizada(h["ee_empresa_rut_no"], "77777777-7")
	if real, ok := h["ee_empresa_rut_real"]; ok { // la página pública real del RUT de prueba del SII
		got["empresa_autorizada_real"] = ParsearEmpresaAutorizada(real, "77777777-7")
	}
	got["software"] = ParsearDatosSoftware(h["ad_empresa2"])
	got["software_sii"] = ParsearDatosSoftware(h["ad_empresa2_sii"])
	got["empresas_asociadas"] = ParsearEmpresasAsociadas(h["mipeSelEmpresa"])
	got["timbrajes"] = ParsearTimbrajes(h["of_consulta2_folio"], 33)
	got["anulables"] = ParsearAnulables(h["af_anular2"], 33)
	anul := map[string]any{}
	for _, k := range []string{"af_anular_ok", "af_anular_recep", "af_anular_antes", "af_anular_raro"} {
		anul[k] = InterpretarAnulacion(h[k], 7, 9)
	}
	anul["sin_padre"] = ResultadoAnulacion{false, "No hay rango anulable que contenga esos folios", 100, 101}
	got["anulacion"] = anul
	b := Bloqueado(h["bloqueado"])
	got["situacion_bloqueada"] = map[string]SituacionTipo{"33": {b, !b}, "61": {b, !b}}
	l := Bloqueado(h["libre"])
	got["situacion_libre"] = map[string]SituacionTipo{"39": {l, !l}}
	got["campos_form"] = CamposForm(h["of_confirma_folio"], "of_genera_folio")
	got["campos_form_none"] = CamposForm(h["of_confirma_folio"], "no_existe")

	// onboarding con dobles
	sw := func(nombre, res string) DatosSoftware {
		return DatosSoftware{Software: nombre, Resolucion: res, Propio: nombre != "" && nombre != "SII" && nombre != "sii", Certificado: res != "" && res != "0"}
	}
	empFull := &EmpresaAutorizadaDTE{"77777777-7", "EMPRESA DEMO SPA", "80", "22-08-2014", "SANTIAGO", []DocumentoAutorizado{
		{33, "FACTURA ELECTRONICA", "01-02-2026", ""}, {39, "BOLETA ELECTRONICA", "05-02-2026", ""}, {61, "NOTA DE CREDITO ELECTRONICA", "01-02-2026", "15-03-2026"}}}
	empExenta := &EmpresaAutorizadaDTE{"77777777-7", "EMPRESA DEMO SPA", "80", "22-08-2014", "SANTIAGO", []DocumentoAutorizado{
		{34, "FACTURA NO AFECTA O EXENTA ELECTRONICA", "01-02-2026", ""}, {41, "BOLETA EXENTA ELECTRONICA", "05-02-2026", ""}}}
	casos := map[string]*doble{
		"sin_propio_exenta":      {empExenta, sw("SII", "0"), sw("", "0"), nil, nil},
		"externo":                {empFull, sw("Haulmer Facturación", "500"), sw("", "0"), nil, nil},
		"emitiendo_nuestro":      {empFull, sw("DTE Chile v2", "500"), sw("DTE Chile v2", "500"), nil, nil},
		"certificando_bloqueada": {empFull, sw("SII", "0"), sw("Motor Demo", "0"), map[int]bool{33: true}, nil},
		"certificado":            {empFull, sw("SII", "0"), sw("Motor Demo", "77"), nil, nil},
		"desconocida":            {nil, sw("", "0"), sw("", "0"), map[int]bool{61: true}, nil},
	}
	const nombreSoftware = "DTE Chile, Motor Demo"
	diags := map[string]any{}
	for k, p := range casos {
		d, err := Diagnosticar(p, "77777777-7", "Motor Demo", "", nombreSoftware)
		if err != nil {
			t.Fatal(err)
		}
		diags[k] = d
	}
	got["diagnosticos"] = diags
	cartera := &doble{empFull, sw("SII", "0"), sw("", "0"), nil, []Empresa{{"77777777-7", "EMPRESA DEMO SPA"}, {"76111111-6", "CLIENTE"}}}
	cd, _ := DiagnosticarCartera(cartera, nil, "Motor Demo", nil, nombreSoftware)
	got["cartera"] = cd
	e1, l1 := ClasificarSoftware(sw("Otro Soft", "9"), sw("", "0"), "Mi Registro", nombreSoftware)
	e2, l2 := ClasificarSoftware(sw("mi registro pro", "9"), sw("", "0"), "Mi Registro", nombreSoftware)
	e3, l3 := ClasificarSoftware(sw("X", "9"), sw("", "0"), "", nombreSoftware) // el generador corre con NOMBRE_SOFTWARE puesto
	got["clasificar"] = map[string][]string{"externo_registrado": {e1, l1}, "nuestro_registrado": {e2, l2}, "propio_sin_config": {e3, l3}}

	// comparar bloque a bloque vía JSON normalizado
	for k, esperado := range esp {
		gb, _ := json.Marshal(got[k])
		var gn any
		_ = json.Unmarshal(gb, &gn)
		if !reflect.DeepEqual(gn, esperado) {
			eb, _ := json.Marshal(esperado)
			t.Errorf("%s difiere\n  python: %s\n  go:     %s", k, string(eb), string(gb))
		}
	}
}

// doble es el _Portal del generador: respuestas fijas.
type doble struct {
	emp        *EmpresaAutorizadaDTE
	prod, cert DatosSoftware
	bloq       map[int]bool
	asociadas  []Empresa
}

func (d *doble) ConsultarEmpresaAutorizada(rut, base string) (*EmpresaAutorizadaDTE, error) {
	return d.emp, nil
}
func (d *doble) DatosSoftwareDe(rut, base string) (DatosSoftware, error) {
	if base == BaseProduccion {
		return d.prod, nil
	}
	return d.cert, nil
}
func (d *doble) SituacionFolios(rut string, tipos []int) (map[int]SituacionTipo, error) {
	out := map[int]SituacionTipo{}
	for _, t := range tipos {
		b := d.bloq[t]
		out[t] = SituacionTipo{b, !b}
	}
	return out, nil
}
func (d *doble) EmpresasAsociadas() ([]Empresa, error) { return d.asociadas, nil }
