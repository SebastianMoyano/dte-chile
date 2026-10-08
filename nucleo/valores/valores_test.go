package valores

import "testing"

// Muestra con la estructura REAL de la página UF del SII (dos meses, pares th/td, celdas vacías).
const fixtureUF = `<table class='table'><tbody>
<tr><th colspan='6'><h2>Octubre</h2></th></tr>
<tr><th width='40'><strong>1</strong></th><td width='200'>41.065,38</td><th width='40'><strong>11</strong></th><td width='200'></td><th width='40'><strong>21</strong></th><td width='200'></td></tr>
<tr><th width='40'><strong>2</strong></th><td width='200'>41.073,57</td><th width='40'><strong>12</strong></th><td width='200'></td><th width='40'><strong>22</strong></th><td width='200'></td></tr>
</tbody></table>
<table class='table'><tbody>
<tr><th colspan='6'><h2>Septiembre</h2></th></tr>
<tr><th width='40'><strong>1</strong></th><td width='200'>40.900,10</td><th width='40'><strong>11</strong></th><td width='200'>40.950,00</td><th width='40'><strong>21</strong></th><td width='200'></td></tr>
</tbody></table>`

func TestParsearUF(t *testing.T) {
	vs, err := ParsearUF([]byte(fixtureUF), 2026)
	if err != nil {
		t.Fatal(err)
	}
	// 4 valores con dato (oct 1, oct 2, sep 1, sep 11); las celdas vacías no cuentan.
	if len(vs) != 4 {
		t.Fatalf("esperaba 4 valores, obtuve %d: %+v", len(vs), vs)
	}
	quiero := map[string]float64{
		"2026-10-01": 41065.38,
		"2026-10-02": 41073.57,
		"2026-09-01": 40900.10,
		"2026-09-11": 40950.00,
	}
	for _, v := range vs {
		if v.Indicador != "uf" {
			t.Errorf("indicador %q", v.Indicador)
		}
		esperado, ok := quiero[v.Fecha]
		if !ok {
			t.Errorf("fecha inesperada %s", v.Fecha)
			continue
		}
		if v.Valor != esperado {
			t.Errorf("%s: esperaba %.2f, obtuve %.2f", v.Fecha, esperado, v.Valor)
		}
	}
}

func TestNumeroCL(t *testing.T) {
	casos := map[string]float64{"41.065,38": 41065.38, "1.234.567,00": 1234567, "0,50": 0.5}
	for s, esperado := range casos {
		if v, ok := numeroCL(s); !ok || v != esperado {
			t.Errorf("numeroCL(%q) = %v,%v; esperaba %v", s, v, ok, esperado)
		}
	}
	if _, ok := numeroCL(""); ok {
		t.Error("numeroCL(\"\") debería ser inválido")
	}
}
