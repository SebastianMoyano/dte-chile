package rcv

import (
	"encoding/json"
	"os"
	"path/filepath"
	"reflect"
	"testing"

	"dtechile/nucleo/almacen"
)

// TestParidadConPython: normalización, payload, persistencia y F29 iguales a core/rcv.py
// sobre tests/dorado/rcv/ (datos ficticios). L15.
func TestParidadConPython(t *testing.T) {
	rawIn, err := os.ReadFile("../../tests/dorado/rcv/entrada.json")
	if err != nil {
		t.Skip("sin corpus del RCV")
	}
	var in struct {
		CSVVentas   any `json:"csv_ventas"`
		DictCompras any `json:"dict_compras"`
	}
	if err := json.Unmarshal(rawIn, &in); err != nil {
		t.Fatal(err)
	}
	rawEsp, _ := os.ReadFile("../../tests/dorado/rcv/esperado.json")
	var esp map[string]any
	if err := json.Unmarshal(rawEsp, &esp); err != nil {
		t.Fatal(err)
	}
	got := map[string]any{}
	ventas := NormalizarDetalle("77.777.777-7", Venta, "2026-01", in.CSVVentas, "")
	compras := NormalizarDetalle("77777777-7", Compra, "202601", in.DictCompras, "csv")
	got["ventas"], got["compras"] = ventas, compras
	got["lista_directa"] = NormalizarDetalle("77777777-7", Venta, "202601", []any{map[string]any{"tipoDoc": 33.0, "folio": 1.0}}, "")
	got["vacios"] = []any{NormalizarDetalle("77777777-7", Venta, "202601", map[string]any{"data": nil}, ""), NormalizarDetalle("77777777-7", Venta, "202601", map[string]any{"data": []any{}}, "")}
	var nums []int64
	for _, v := range []any{nil, "", 12.0, 12.6, "1.234", "1,234", "x", -3.5} {
		nums = append(nums, Num(v))
	}
	got["num"] = nums
	var fechas []*string
	for _, v := range []any{nil, "", "15/01/2026", "2026-01-15", "2026-01-15T10:00:00", "15-01-2026", "garbage!!!", "2026"} {
		fechas = append(fechas, FechaISO(v))
	}
	got["fecha"] = fechas
	got["periodo"] = []string{NormalizarPeriodo("2026-01"), NormalizarPeriodo("202601"), NormalizarPeriodo("2026/01"), NormalizarPeriodo(" 202601 ")}
	cli := Nuevo("TOK", nil)
	got["payload"] = map[string]any{"venta": cli.Payload("77777777-7", "2026-01", Venta, "", "<uuid>"), "compra": cli.Payload("77777777-7", "202601", Compra, "", "<uuid>"),
		"resumen": cli.Payload("77777777-7", "202601", Venta, "getResumen", "<uuid>")}
	got["payload_cookies"] = Nuevo("", map[string]string{"CSESSIONID": "CS", "TOKEN": "T2"}).Payload("77777777-7", "202601", Venta, "", "<uuid>")
	got["headers"] = Headers("TOK", "77777777", "7")
	got["endpoints"] = Endpoints()

	alm, err := almacen.AbrirYMigrar(filepath.Join(t.TempDir(), "rcv.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer alm.Cerrar()
	db := alm.DB()
	todos := append(append([]Documento{}, ventas...), compras...)
	n1, err := GuardarDocumentos(db, todos)
	if err != nil {
		t.Fatal(err)
	}
	n2, _ := GuardarDocumentos(db, todos)
	got["guardados"], got["guardados_otra_vez"] = n1, n2
	var filas int
	_ = db.QueryRow(`SELECT COUNT(*) FROM rcv_documentos`).Scan(&filas)
	got["filas_en_bd"] = filas
	d, err := CalcularDesglose(db, "77777777-7", "202601", 1234, 500)
	if err != nil {
		t.Fatal(err)
	}
	db1, _ := json.Marshal(d)
	var dm map[string]any
	_ = json.Unmarshal(db1, &dm)
	dm["iva_determinado"], dm["remanente_siguiente"], dm["base_ppm"], dm["total_a_pagar"] = d.IVADeterminado(), d.RemanenteSiguiente(), d.BasePPM, d.TotalAPagar()
	got["desglose"] = dm
	got["casilleros"] = MapearAF29(d)
	d2, _ := CalcularDesglose(db, "77777777-7", "202601", 0, 900000)
	got["casilleros_remanente"] = MapearAF29(d2)
	r, _ := CalcularResumen(db, "77777777-7", "202601", 10, 0)
	rb, _ := json.Marshal(r)
	var rm map[string]any
	_ = json.Unmarshal(rb, &rm)
	rm["iva_determinado"], rm["remanente_siguiente"], rm["total_a_pagar"] = r.IVADeterminado(), r.RemanenteSiguiente(), r.TotalAPagar()
	got["resumen"] = rm
	cod := map[string][]string{}
	for k, v := range CodigosF29 {
		cod[k] = []string{v[0], v[1]}
	}
	got["codigos_f29"] = cod

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
