package siiengine

import (
	"regexp"
	"strconv"
	"strings"
)

var reNoRut = regexp.MustCompile(`[^0-9kK]`)

// SepararRut es core/rut.py::separar_rut: "12.345.678-9" → ("12345678", "9"). Sin DV → ("", "").
func SepararRut(rut string) (string, string) {
	s := strings.ToUpper(reNoRut.ReplaceAllString(rut, ""))
	if len(s) < 2 {
		return "", ""
	}
	return s[:len(s)-1], s[len(s)-1:]
}

// DigitoVerificador calcula el DV por módulo 11 (core/rut.py::calcular_dv).
func DigitoVerificador(numero string) string {
	suma, mult := 0, 2
	for i := len(numero) - 1; i >= 0; i-- {
		suma += int(numero[i]-'0') * mult
		mult++
		if mult > 7 {
			mult = 2
		}
	}
	switch r := 11 - suma%11; r {
	case 11:
		return "0"
	case 10:
		return "K"
	default:
		return strconv.Itoa(r)
	}
}

// ValidarRut es core/rut.py::validar_rut.
func ValidarRut(rut string) bool {
	n, dv := SepararRut(rut)
	if n == "" {
		return false
	}
	for _, c := range n {
		if c < '0' || c > '9' {
			return false
		}
	}
	return DigitoVerificador(n) == dv
}

// FormatearRut es core/rut.py::formatear_rut: con puntos "12.345.678-9", sin puntos "12345678-9".
// Un RUT que no se puede separar vuelve tal cual (como Python).
func FormatearRut(rut string, conPuntos bool) string {
	n, dv := SepararRut(rut)
	if n == "" {
		return rut
	}
	if !conPuntos {
		return n + "-" + dv
	}
	var b strings.Builder
	for i := 0; i < len(n); i++ {
		if i > 0 && (len(n)-i)%3 == 0 {
			b.WriteByte('.')
		}
		b.WriteByte(n[i])
	}
	return b.String() + "-" + dv
}
