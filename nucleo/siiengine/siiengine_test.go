package siiengine

// Paridad con core/sii_mipyme.py: los valores esperados salieron de correr el módulo Python
// sobre las mismas entradas (2026-10-08). Si Python cambia, se regeneran desde Python; nunca
// se ajustan para que el Go pase (L15).

import (
	"os"
	"path/filepath"
	"reflect"
	"testing"

	"dtechile/nucleo/almacen"
)

func TestRut(t *testing.T) {
	if n, dv := SepararRut("12.345.678-5"); n != "12345678" || dv != "5" {
		t.Fatalf("separar: %s %s", n, dv)
	}
	if !ValidarRut("12.345.678-5") || !ValidarRut("77777777-7") || !ValidarRut("76111111-6") || ValidarRut("12345678-9") {
		t.Fatal("validar")
	}
	if FormatearRut("12345678-5", true) != "12.345.678-5" || FormatearRut("12.345.678-5", false) != "12345678-5" {
		t.Fatal("formatear")
	}
	if DigitoVerificador("77777777") != "7" || DigitoVerificador("12345678") != "5" {
		t.Fatal("dv")
	}
}

func TestCodificarLatin1(t *testing.T) {
	// Python: _body([...]) sobre los mismos pares.
	b, err := CodificarLatin1([]Par{{"rut", "12345678"}, {"dv", "5"}, {"clave", "ñandú pass/&=+ ~x"},
		{"referencia", "https://misiir.sii.cl/cgi_misii/siihome.cgi"}, {"411", ""}, {"rutcntr", "12.345.678-5"}})
	if err != nil {
		t.Fatal(err)
	}
	esperado := "rut=12345678&dv=5&clave=%F1and%FA+pass%2F%26%3D%2B+~x&referencia=https%3A%2F%2Fmisiir.sii.cl%2Fcgi_misii%2Fsiihome.cgi&411=&rutcntr=12.345.678-5"
	if string(b) != esperado {
		t.Fatalf("\n got %s\nwant %s", b, esperado)
	}
	if _, err := CodificarLatin1([]Par{{"x", "€"}}); err == nil {
		t.Fatal("€ no es latin-1: debe fallar, como Python")
	}
	if s := string(CodificarUTF8([]Par{{"dato", "ñ x"}})); s != "dato=%C3%B1+x" {
		t.Fatalf("utf8: %s", s)
	}
	if Latin1([]byte{0xF1, 0x41}) != "ñA" {
		t.Fatal("latin1")
	}
}

func TestParsearForm(t *testing.T) {
	html := `<form><input name="a" value="1"><input type="hidden" name="b"><select name="s"><option value="x">X</option><option value="y" selected>Y</option></select>
<select name="t"><option value="p">P</option><option value="q">Q</option></select><textarea name="ta">hola
mundo</textarea><input name="a" value="2"></form>`
	got := ParsearForm(html)
	want := map[string]string{"a": "1", "b": "", "s": "y", "t": "p", "ta": "hola\nmundo"}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("got %v want %v", got, want)
	}
	// Dentro de <script> no se parsean tags (CDATA, como html.parser); los valores se des-escapan.
	got = ParsearForm(`<script>var s = '<input name="falso" value="1">';</script><INPUT NAME="Real" VALUE="a &amp; b">`)
	if _, ok := got["falso"]; ok || got["Real"] != "a & b" {
		t.Fatalf("script/escape: %v", got)
	}
}

const htmlListado = `
<table>
<tr><th>RUT</th><th>Razón Social</th><th>Tipo</th><th>Folio</th><th>Fecha</th><th>Monto</th><th>Estado</th><th></th></tr>
<tr><td>76.111.111-6</td><td>CLIENTE DEMO SPA</td><td>FACTURA NO AFECTA O EXENTA ELECTRONICA</td><td>59</td>
    <td>06/09/2026</td><td>3.270.323</td><td>Aceptado</td><td><a href="mipeGesDocEmi.cgi?ALL_PAGE_ANT=2&CODIGO=2850540417">ver</a></td></tr>
<tr><td>76.111.111-6</td><td>CLIENTE DEMO SPA</td><td>NOTA DE CREDITO ELECTRONICA</td><td>56</td>
    <td>2026-09-06</td><td>$3.068.005</td><td>Aceptado con Reparos</td><td><a href="mipeGesDocEmi.cgi?CODIGO=2850540999">ver</a></td></tr>
<tr><td colspan="8">Página 1 de 3</td></tr>
</table>
`

func TestParsearListado(t *testing.T) {
	docs, ultima := ParsearListado(htmlListado)
	want := []DocumentoEmitido{
		{"2850540417", "FACTURA NO AFECTA O EXENTA ELECTRONICA", 59, "2026-09-06", 3270323, "Aceptado", "76111111-6", "CLIENTE DEMO SPA"},
		{"2850540999", "NOTA DE CREDITO ELECTRONICA", 56, "2026-09-06", 3068005, "Aceptado con Reparos", "76111111-6", "CLIENTE DEMO SPA"},
	}
	if ultima != 3 || !reflect.DeepEqual(docs, want) {
		t.Fatalf("ultima=%d docs=%+v", ultima, docs)
	}
	if docs[0].Tipo() != 34 || docs[1].Tipo() != 61 {
		t.Fatal("tipos")
	}
	if TipoDesdeTexto("FACTURA ELECTRONICA") != 33 || TipoDesdeTexto("GUIA DE DESPACHO ELECTRONICA") != 52 || TipoDesdeTexto("RARO") != 0 {
		t.Fatal("mapa de tipos")
	}
}

func TestRespuestaFirma(t *testing.T) {
	casos := []struct {
		in  string
		st  int
		txt string
	}{
		{`while(1);{"status":0,"text":"<DTE>x</DTE>"}`, 0, "<DTE>x</DTE>"},
		{`{"statusCode":2,"text":"Clave no corresponde"}`, 2, "Clave no corresponde"},
		{`<?xml version="1.0"?><DTE/>`, 0, `<?xml version="1.0"?><DTE/>`},
		{`basura`, -1, ""},
		{`pre {status: 0, text: "<DTE>a</DTE>"} post`, 0, "<DTE>a</DTE>"},
	}
	for _, c := range casos {
		if st, txt := ParsearRespuestaFirma(c.in); st != c.st || txt != c.txt {
			t.Errorf("%q → (%d, %q), want (%d, %q)", c.in, st, txt, c.st, c.txt)
		}
	}
	in := "<?xml version=\"1.0\"?>\n<EnvioDTE><SetDTE><DTE><Documento ID=\"x\"/></DTE></SetDTE></EnvioDTE>"
	want := "<?xml version=\"1.0\"?>\n<EnvioDTE><SetDTE><DTE>" + ComentarioFirma + "\n<Documento ID=\"x\"/></DTE></SetDTE></EnvioDTE>"
	if got := PrepararDatoFirma(in); got != want || PrepararDatoFirma(got) != want {
		t.Fatalf("dato firma: %q", got)
	}
}

type lectorFalso struct{}

func (lectorFalso) DescargarPDF(dhdr string) ([]byte, error) {
	return []byte("%PDF-1.4 fake " + dhdr), nil
}
func (lectorFalso) ObtenerEnvioXML(string, int, string) ([]byte, error) {
	return []byte("<EnvioDTE>\xf1</EnvioDTE>"), nil
}

func TestImportar(t *testing.T) {
	dir := t.TempDir()
	al, err := almacen.Abrir(filepath.Join(dir, "t.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer al.Cerrar()
	// El esquema lo define core/database.py (SCHEMA_SQL); aquí solo la tabla que toca la importación.
	if err := al.EjecutarDDL(ddlDtes); err != nil {
		t.Fatal(err)
	}
	docs, _ := ParsearListado(htmlListado)
	op := OpcionesImportar{ConPDF: true, Carpeta: filepath.Join(dir, "storage")}
	r1, err := Importar(lectorFalso{}, al, "77.777.777-7", docs, op)
	if err != nil {
		t.Fatal(err)
	}
	if r1.Importados != 2 || r1.PDFOk != 2 || r1.Listados != 2 {
		t.Fatalf("r1: %+v", r1)
	}
	fila, err := al.DTEPorFolio("77777777-7", 34, 59)
	if err != nil || fila == nil || fila.Estado != "emitido_mipyme" || fila.PDFPath == "" {
		t.Fatalf("fila: %+v %v", fila, err)
	}
	if _, err := os.Stat(fila.PDFPath); err != nil {
		t.Fatal("pdf en disco:", err)
	}
	r2, err := Importar(lectorFalso{}, al, "77777777-7", docs, op)
	if err != nil || r2.Importados != 0 || r2.YaExistian != 2 || r2.PDFOk != 0 {
		t.Fatalf("idempotente: %+v %v", r2, err)
	}
	op.ConXML = true
	r3, _ := Importar(lectorFalso{}, al, "77777777-7", docs, op)
	fila, _ = al.DTEPorFolio("77777777-7", 61, 56)
	if r3.XMLOk != 2 || !fila.TieneXML {
		t.Fatalf("xml: %+v tieneXML=%v", r3, fila.TieneXML)
	}
}

// Copia literal de la tabla `dtes` de core/database.py::SCHEMA_SQL.
const ddlDtes = `CREATE TABLE IF NOT EXISTS dtes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tipo_dte INTEGER NOT NULL,
    folio INTEGER NOT NULL,
    rut_emisor TEXT NOT NULL,
    rut_receptor TEXT NOT NULL,
    razon_social_receptor TEXT,
    fecha_emision TEXT NOT NULL,
    monto_neto INTEGER DEFAULT 0,
    monto_exento INTEGER DEFAULT 0,
    iva INTEGER DEFAULT 0,
    monto_total INTEGER NOT NULL,
    estado TEXT DEFAULT 'generado',
    track_id INTEGER,
    xml_firmado TEXT,
    pdf_path TEXT,
    ambiente TEXT DEFAULT 'certificacion',
    creado_en TEXT NOT NULL,
    actualizado_en TEXT NOT NULL,
    UNIQUE(rut_emisor, tipo_dte, folio)
)`
