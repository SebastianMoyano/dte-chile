// Package totales replica core/dte.py::calcular_totales byte a byte en sus resultados.
//
// Reglas (ver docs/DORADO.md §1): montos enteros en pesos; redondeo half-up sobre la
// representación decimal más corta del float (como Decimal(str(x)) en Python); en boletas
// el precio es bruto (IVA incluido) y el neto se deriva; el descuento por monto se resta sin
// redondear y el ítem entra al total truncado hacia cero (int()).
package totales

import (
	"math"
	"math/big"
	"strconv"
)

const TasaIVA = 19

type Item struct {
	Cantidad       float64 `json:"cantidad"`
	PrecioUnitario float64 `json:"precio_unitario"`
	DescuentoPct   float64 `json:"descuento_pct"`
	DescuentoMonto float64 `json:"descuento_monto"`
	Exento         bool    `json:"exento"`
}

type Totales struct {
	MontoNeto   int64 `json:"monto_neto"`
	MontoExento int64 `json:"monto_exento"`
	IvaTasa     int   `json:"iva_tasa"`
	IvaMonto    int64 `json:"iva_monto"`
	MontoTotal  int64 `json:"monto_total"`
}

// Redondear es `int(Decimal(str(valor)).quantize(1, ROUND_HALF_UP))`: se parte de la
// representación decimal más corta (la que imprime Python), no del binario del float.
func Redondear(v float64) int64 {
	s := strconv.FormatFloat(v, 'g', -1, 64)
	r, ok := new(big.Rat).SetString(s)
	if !ok {
		return int64(math.Round(v))
	}
	neg := r.Sign() < 0
	if neg {
		r.Neg(r)
	}
	r.Add(r, big.NewRat(1, 2))
	q := new(big.Int).Quo(r.Num(), r.Denom()) // floor para positivos
	if neg {
		q.Neg(q)
	}
	return q.Int64()
}

func montoItem(it Item) float64 { return float64(Redondear(it.Cantidad * it.PrecioUnitario)) }

func montoDescuento(it Item) float64 {
	m := montoItem(it)
	if it.DescuentoMonto > 0 {
		return it.DescuentoMonto
	}
	if it.DescuentoPct > 0 {
		return float64(Redondear(m * it.DescuentoPct / 100))
	}
	return 0
}

// MontoNetoItem = monto_item - monto_descuento (float, sin redondear), como la propiedad
// `ItemDTE.monto_neto`.
func MontoNetoItem(it Item) float64 { return montoItem(it) - montoDescuento(it) }

func esBoleta(tipo int) bool { return tipo == 39 || tipo == 41 }
func aplicaIVA(tipo int) bool {
	return tipo == 33 || tipo == 39 || tipo == 56 || tipo == 61 || tipo == 52
}
func docExento(tipo int) bool { return tipo == 34 || tipo == 41 }

func Calcular(items []Item, tipo int) Totales {
	var neto, exento, bruto int64
	for _, it := range items {
		m := int64(MontoNetoItem(it)) // int(): trunca hacia cero
		switch {
		case it.Exento || docExento(tipo):
			exento += m
		case esBoleta(tipo):
			bruto += m
		default:
			neto += m
		}
	}
	t := Totales{IvaTasa: TasaIVA, MontoExento: exento}
	if esBoleta(tipo) && bruto > 0 {
		t.MontoNeto = Redondear(float64(bruto) / (1 + float64(TasaIVA)/100))
		t.IvaMonto = bruto - t.MontoNeto
		t.MontoTotal = bruto + exento
		return t
	}
	t.MontoNeto = neto
	if aplicaIVA(tipo) && neto > 0 {
		t.IvaMonto = Redondear(float64(neto*int64(TasaIVA)) / 100)
	}
	t.MontoTotal = neto + exento + t.IvaMonto
	return t
}
