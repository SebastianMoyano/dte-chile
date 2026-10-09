package siiengine

// Paridad de los segmentos 2-4 con core/sii_mipyme.py. Los `testdata/esp_*.txt` los generó
// Python sobre las mismas entradas (2026-10-08; datos ficticios, L14). TestParidadEvidencia
// usa las evidencias REALES de storage/mipyme_fallidos (privadas, gitignored): el cuerpo de
// mipeSendXML que Python mandó y el SII aceptó (factura 63, NC 60) debe salir byte a byte
// igual del Go a partir de la misma página de firma y la misma respuesta de postFirma.

import (
	"encoding/json"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
)

func TestSchema(t *testing.T) {
	b, err := os.ReadFile("testdata/schema.json")
	if err != nil {
		t.Fatal(err)
	}
	var py []string
	if err := json.Unmarshal(b, &py); err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(SchemaCampos, py) {
		t.Fatalf("schema distinto: go %d, python %d", len(SchemaCampos), len(py))
	}
	if len(CamposValidarFactura) != 54 || len(CamposValidarCorrMnt) != 60 {
		t.Fatal("largos de los campos de validar")
	}
}

const htmlPreview = `<form name="PreViewDTE"><input name="INDICA_PRIMERA_EJECUCION" value="1"><input name="ES_BORR" value=""><input name="EFXP_RZN_SOC" value="EMPRESA DEMO SPA">` +
	`<input name="EFXP_GIRO_EMIS" value="VENTAS"><input name="EFXP_ACTECO" value="123456"><input name="EFXP_NMB_01" value="viejo"><input name="EFXP_TPO_COD_02" value="x">` +
	`<input name="CAMPO_RARO" value="z"><input name="CANT_DET" value="1"><input name="EFXP_DIR_ORIGEN_DEFUALT" value="D"><input name="EFXP_TASA_IVA" value="19">` +
	`<input name="EFXP_TPO_DOC_REF_001" value="33"><input type="button" name="btnSign" value="Firmar"></form>`

var receptorPrueba = Receptor{"76.111.111-6", "CLIENTE DEMO SPA", "SALUD", "CAMINO 1", "Chillan", "CHILLAN"}
var itemPrueba = Item{"Arriendo", 1000, 1, "Doc de prueba ñ"}

func esperado(t *testing.T, nombre string) string {
	b, err := os.ReadFile(filepath.Join("testdata", nombre))
	if err != nil {
		t.Fatal(err)
	}
	return string(b)
}

func cuerpo(t *testing.T, pares []Par) string {
	b, err := CodificarLatin1(pares)
	if err != nil {
		t.Fatal(err)
	}
	return string(b)
}

func primeraDiferencia(a, b string) string {
	for i := 0; i < len(a) && i < len(b); i++ {
		if a[i] != b[i] {
			lo := max(0, i-60)
			return "pos " + itoa(i) + "\n got …" + a[lo:min(len(a), i+60)] + "\nwant …" + b[lo:min(len(b), i+60)]
		}
	}
	return "largos distintos: " + itoa(len(a)) + " vs " + itoa(len(b))
}

func itoa(n int) string    { return strings.TrimSpace(strings.Repeat(" ", 0) + jsonNum(n)) }
func jsonNum(n int) string { b, _ := json.Marshal(n); return string(b) }

func TestArmarPayloadFactura(t *testing.T) {
	p, err := ArmarPayload(ParsearFormOrdenado(htmlPreview), 34, receptorPrueba, []Item{itemPrueba}, "2026-10-08", "1", nil,
		[]string{"ES_BORR", "INDICA_PRIMERA_EJECUCION"})
	if err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(p.CamposNuevos, []string{"CAMPO_RARO"}) || p.MontoTotal() != 1000 || len(p.Pares) != 243 {
		t.Fatalf("nuevos=%v monto=%d n=%d", p.CamposNuevos, p.MontoTotal(), len(p.Pares))
	}
	if got, want := cuerpo(t, p.Pares), esperado(t, "esp_factura.txt"); got != want {
		t.Fatal("factura: " + primeraDiferencia(got, want))
	}
}

func TestArmarPayloadNota(t *testing.T) {
	ref := Referencia{34, 63, "2026-10-08", "1", "ANULA DOCUMENTO DE LA REFERENCIA"}
	p, err := ArmarPayload(ParsearFormOrdenado(htmlPreview), 61, receptorPrueba, []Item{itemPrueba}, "2026-10-08", "", []Referencia{ref},
		[]string{"ES_BORR", "EFXP_FMA_PAGO", "INDICA_PRIMERA_EJECUCION"})
	if err != nil {
		t.Fatal(err)
	}
	if len(p.Pares) != 246 || p.Pares[0].Nombre != "INDICA_PRIMERA_EJECUCION" {
		t.Fatalf("n=%d primero=%s", len(p.Pares), p.Pares[0].Nombre)
	}
	if got, want := cuerpo(t, p.Pares), esperado(t, "esp_nota.txt"); got != want {
		t.Fatal("nota: " + primeraDiferencia(got, want))
	}
}

func TestFormFirmaYSend(t *testing.T) {
	doc := `<html><form name="PreViewDTE" action="x"><input name="a" value="1"></form>` +
		`<form name="frmSign" action="mipeSendXML.cgi?csrt=123"><input type="hidden" name="PTDC_CODIGO" value="34"><input type="hidden" name="EFXP_FMA_PAGO" value="1">` +
		`<input type="hidden" name="TMST_SIGN" value=""><textarea name="txtPlainText"><?xml version="1.0"?>` + "\n" + `<DTE>a &amp; b</DTE></textarea>` +
		`<input type="hidden" name="EFXP_FMA_PAGO" value="1"><input type="hidden" name="EFXP_FOLIO" value="58"><input type="button" name="btnSign" value="Firmar"></form></html>`
	f := ExtraerFormFirma(doc)
	if f == nil || f.Action != "mipeSendXML.cgi?csrt=123" || len(f.Crudos) != 7 || f.Crudos[3].Valor != "<?xml version=\"1.0\"?>\n<DTE>a & b</DTE>" {
		t.Fatalf("frmSign: %+v", f)
	}
	pares := ArmarSendXMLDesdeForm(f, "<?xml version=\"1.0\"?>\n<DTE><Signature/></DTE>", "***", "2026-10-08T16:59:00")
	if got, want := cuerpo(t, pares), esperado(t, "esp_send.txt"); got != want {
		t.Fatal("send: " + primeraDiferencia(got, want))
	}
	if ExtraerFormFirma("<html>sin form</html>") != nil {
		t.Fatal("sin frmSign → nil")
	}
	if ExtraerXMLDTE(`<html><script>var xmlDte = '<DTE>x</DTE>';</script></html>`) != "<DTE>x</DTE>" {
		t.Fatal("xml en var")
	}
}

// TestParidadEvidencia: con las evidencias reales de emisiones aceptadas (Python), el cuerpo
// de mipeSendXML que arma Go debe ser idéntico al que viajó (body_ok.txt, clave tachada ***).
func TestParidadEvidencia(t *testing.T) {
	carpetas, _ := filepath.Glob("../../storage/mipyme_fallidos/*/T*_F*")
	n := 0
	for _, dir := range carpetas {
		pagina, err1 := os.ReadFile(filepath.Join(dir, "respuesta_genxmlfirma.html"))
		cruda, err2 := os.ReadFile(filepath.Join(dir, "respuesta_postfirma_cruda.txt"))
		want, err3 := os.ReadFile(filepath.Join(dir, "body_ok.txt"))
		if err1 != nil || err2 != nil || err3 != nil {
			continue
		}
		f := ExtraerFormFirma(Latin1(pagina))
		if f == nil {
			t.Errorf("%s: sin frmSign", dir)
			continue
		}
		estado, firmado := ParsearRespuestaFirma(Latin1(cruda))
		if estado != 0 {
			t.Errorf("%s: firma estado %d", dir, estado)
			continue
		}
		tmst := ""
		if m := reTmstFirma.FindStringSubmatch(firmado); m != nil {
			tmst = m[1]
		}
		got := cuerpo(t, ArmarSendXMLDesdeForm(f, firmado, "***", tmst))
		if got != string(want) {
			t.Errorf("%s: cuerpo distinto: %s", dir, primeraDiferencia(got, string(want)))
		}
		n++
	}
	if n == 0 {
		t.Skip("sin evidencias reales en storage/mipyme_fallidos (privadas)")
	}
	t.Logf("evidencias comparadas: %d", n)
}

// TestParidadTrazas: con las trazas privadas de storage/siiengine_paridad (páginas que el
// portal devolvió a Go en un dry-run y cuerpos que Python armó sobre el mismo flujo, vía
// tools/paridad_siiengine.py), el payload de GenXMLFirma que arma Go debe ser byte a byte el
// de Python. Se salta si no están.
func TestParidadTrazas(t *testing.T) {
	raiz := "../../storage/siiengine_paridad"
	pb, err := os.ReadFile(filepath.Join(raiz, "params.json"))
	if err != nil {
		t.Skip("sin storage/siiengine_paridad/params.json (privado)")
	}
	var params struct {
		Receptor struct {
			Rut, RazonSocial, Giro, Direccion, Ciudad, Comuna string
		}
		Item struct {
			Nombre      string
			Precio      int64
			Cantidad    int
			Descripcion string
		}
		Fecha, FormaPago string `json:",omitempty"`
		NCAnular         struct {
			DHDR     string `json:"dhdr"`
			TipoRef  int    `json:"tipo_ref"`
			FolioRef int    `json:"folio_ref"`
			FechaRef string `json:"fecha_ref"`
		} `json:"nc-anular"`
		NCCorregir struct {
			DHDR     string `json:"dhdr"`
			TipoRef  int    `json:"tipo_ref"`
			FolioRef int    `json:"folio_ref"`
			FechaRef string `json:"fecha_ref"`
		} `json:"nc-corregir"`
	}
	// claves JSON en snake_case → mapear a mano lo que no calza por nombre
	var crudo map[string]any
	json.Unmarshal(pb, &crudo)
	rec := crudo["receptor"].(map[string]any)
	params.Receptor.Rut, _ = rec["rut"].(string)
	params.Receptor.RazonSocial, _ = rec["razon_social"].(string)
	params.Receptor.Giro, _ = rec["giro"].(string)
	params.Receptor.Direccion, _ = rec["direccion"].(string)
	params.Receptor.Ciudad, _ = rec["ciudad"].(string)
	params.Receptor.Comuna, _ = rec["comuna"].(string)
	it := crudo["item"].(map[string]any)
	params.Item.Nombre, _ = it["nombre"].(string)
	params.Item.Descripcion, _ = it["descripcion"].(string)
	params.Item.Precio = int64(it["precio"].(float64))
	params.Item.Cantidad = int(it["cantidad"].(float64))
	params.Fecha, _ = crudo["fecha"].(string)
	params.FormaPago, _ = crudo["forma_pago"].(string)
	json.Unmarshal(pb, &params)
	receptor := Receptor{params.Receptor.Rut, params.Receptor.RazonSocial, params.Receptor.Giro, params.Receptor.Direccion, params.Receptor.Ciudad, params.Receptor.Comuna}
	items := []Item{{params.Item.Nombre, params.Item.Precio, params.Item.Cantidad, params.Item.Descripcion}}
	leer := func(flujo, nombre string) string {
		b, err := os.ReadFile(filepath.Join(raiz, flujo, nombre))
		if err != nil {
			t.Skipf("sin %s/%s", flujo, nombre)
		}
		return Latin1(b)
	}
	n := 0
	if pag := leer("factura", "go/preview.html"); pag != "" {
		p, err := ArmarPayload(ParsearFormOrdenado(pag), 34, receptor, items, params.Fecha, params.FormaPago, nil, []string{"ES_BORR", "INDICA_PRIMERA_EJECUCION"})
		if err != nil {
			t.Fatal(err)
		}
		if got, want := cuerpo(t, p.Pares), leer("factura", "py/body_genxml.txt"); got != want {
			t.Error("factura genxml: " + primeraDiferencia(got, want))
		}
		n++
	}
	if pag := leer("nc-anular", "go/nc_anulacion.html"); pag != "" {
		r := params.NCAnular
		p, err := ArmarPayload(ParsearFormOrdenado(pag), 61, receptor, items, params.Fecha, "",
			[]Referencia{{r.TipoRef, r.FolioRef, r.FechaRef, CodigoRefAnula, RazonRefAnula}}, []string{"ES_BORR", "EFXP_FMA_PAGO", "INDICA_PRIMERA_EJECUCION"})
		if err != nil {
			t.Fatal(err)
		}
		if got, want := cuerpo(t, p.Pares), leer("nc-anular", "py/body_genxml.txt"); got != want {
			t.Error("nc-anular genxml: " + primeraDiferencia(got, want))
		}
		n++
	}
	if pag := leer("nc-corregir", "go/corr_preview.html"); pag != "" {
		r := params.NCCorregir
		p, err := ArmarPayload(ParsearFormOrdenado(pag), 61, receptor, items, params.Fecha, "",
			[]Referencia{{r.TipoRef, r.FolioRef, r.FechaRef, CodigoRefCorrigeMonto, RazonRefCorrigeMonto}}, []string{"ES_BORR", "EFXP_FMA_PAGO", "INDICA_PRIMERA_EJECUCION"})
		if err != nil {
			t.Fatal(err)
		}
		if got, want := cuerpo(t, p.Pares), leer("nc-corregir", "py/body_genxml.txt"); got != want {
			t.Error("nc-corregir genxml: " + primeraDiferencia(got, want))
		}
		n++
	}
	t.Logf("flujos comparados: %d", n)
}
