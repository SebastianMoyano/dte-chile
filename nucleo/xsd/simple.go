package xsd

import (
	"fmt"
	"math/big"
	"regexp"
	"strconv"
	"strings"
	"time"
	"unicode/utf8"
)

// Tipos primitivos que usan los XSD del SII y XMLDSig. Uno nuevo en un esquema hace fallar la
// carga (y el test), en vez de validar a medias.
func builtinSoportado(local string) bool {
	switch local {
	case "string", "normalizedString", "token", "anyURI", "anySimpleType", "ID", "NCName", "boolean",
		"decimal", "integer", "long", "int", "nonNegativeInteger", "positiveInteger", "unsignedLong", "unsignedInt",
		"base64Binary", "date", "dateTime":
		return true
	}
	return false
}

func raizBuiltin(t *tipoSimple) *tipoSimple {
	for t.builtin == "" {
		t = t.base
	}
	return t
}

// nombreTipo es el nombre del tipo nombrado más cercano (como lo muestra libxml2).
func nombreTipo(t *tipoSimple) string {
	for ; t != nil; t = t.base {
		if t.nombre.Local != "" {
			if t.nombre.NS == nsXSD {
				return "xs:" + t.nombre.Local
			}
			return t.nombre.String()
		}
	}
	return "?"
}

func colapsar(s string) string { return strings.Join(strings.Fields(s), " ") }

var (
	reNCName  = regexp.MustCompile(`^[\pL_][\pL\pN\pM._\-]*$`)
	reDecimal = regexp.MustCompile(`^([+-]?)(\d*)(?:\.(\d*))?$`)
	reFecha   = regexp.MustCompile(`^(-?)(\d{4,})-(\d{2})-(\d{2})(?:T(\d{2}):(\d{2}):(\d{2})(\.\d+)?)?(Z|[+-]\d{2}:\d{2})?$`)
)

// numero es el valor canónico de un decimal: sin ceros a la izquierda ni a la derecha.
type numero struct {
	neg       bool
	ent, frac string
	rat       *big.Rat
}

func parsearNumero(v string) (numero, bool) {
	m := reDecimal.FindStringSubmatch(v)
	if m == nil || (m[2] == "" && m[3] == "") {
		return numero{}, false
	}
	n := numero{neg: m[1] == "-", ent: strings.TrimLeft(m[2], "0"), frac: strings.TrimRight(m[3], "0")}
	r, ok := new(big.Rat).SetString(m[1] + "0" + m[2] + "." + m[3] + "0")
	if !ok {
		return numero{}, false
	}
	n.rat = r
	return n, true
}

type instante struct {
	t    time.Time
	frac string
}

func (a instante) cmp(b instante) int {
	if a.t.Before(b.t) {
		return -1
	}
	if a.t.After(b.t) {
		return 1
	}
	return strings.Compare(strings.TrimRight(a.frac, "0"), strings.TrimRight(b.frac, "0"))
}

// parsearFecha acepta date (conHora=false) o dateTime. Reglas de libxml2: año de 4 dígitos sin
// cero inicial sobrante, día válido en el mes, hora 24 solo como 24:00:00, zona hasta ±14:00.
func parsearFecha(v string, conHora bool) (instante, bool) {
	m := reFecha.FindStringSubmatch(v)
	if m == nil || (m[5] != "") != conHora {
		return instante{}, false
	}
	if len(m[2]) > 4 && m[2][0] == '0' {
		return instante{}, false
	}
	y, _ := strconv.Atoi(m[2])
	if m[1] == "-" {
		y = -y
	}
	mes, _ := strconv.Atoi(m[3])
	dia, _ := strconv.Atoi(m[4])
	if mes < 1 || mes > 12 || dia < 1 || dia > diasDelMes(y, mes) {
		return instante{}, false
	}
	h, mi, s := 0, 0, 0
	if conHora {
		h, _ = strconv.Atoi(m[5])
		mi, _ = strconv.Atoi(m[6])
		s, _ = strconv.Atoi(m[7])
		if mi > 59 || s > 59 || h > 24 || (h == 24 && (mi != 0 || s != 0 || strings.Trim(m[8], ".0") != "")) {
			return instante{}, false
		}
	}
	off := 0
	if z := m[9]; z != "" && z != "Z" {
		zh, _ := strconv.Atoi(z[1:3])
		zm, _ := strconv.Atoi(z[4:6])
		if zh > 14 || zm > 59 || (zh == 14 && zm != 0) {
			return instante{}, false
		}
		off = zh*3600 + zm*60
		if z[0] == '-' {
			off = -off
		}
	}
	t := time.Date(y, time.Month(mes), dia, h, mi, s, 0, time.FixedZone("", off)).UTC()
	return instante{t: t, frac: strings.TrimPrefix(m[8], ".")}, true
}

func diasDelMes(y, m int) int {
	switch m {
	case 2:
		if y%4 == 0 && (y%100 != 0 || y%400 == 0) {
			return 29
		}
		return 28
	case 4, 6, 9, 11:
		return 30
	}
	return 31
}

var (
	maxInt64  = new(big.Int).SetInt64(1<<63 - 1)
	minInt64  = new(big.Int).SetInt64(-1 << 63)
	maxUint64 = new(big.Int).SetUint64(^uint64(0))
)

// base64Valido reproduce a libxml2 (xmlschemastypes.c), que es lo que valida Python: los
// caracteres que no son base64 se IGNORAN (blancos, '-', 'ñ'…); se cuentan los válidos hasta el
// primer '=', después del cual no puede venir otro válido; a lo más dos '='; (válidos + '=') % 4
// == 0; y el último válido debe tener en cero los bits que cubre el relleno.
func base64Valido(v string) bool {
	decodificar := func(c byte) int {
		switch {
		case c >= 'A' && c <= 'Z':
			return int(c - 'A')
		case c >= 'a' && c <= 'z':
			return int(c-'a') + 26
		case c >= '0' && c <= '9':
			return int(c-'0') + 52
		case c == '+':
			return 62
		case c == '/':
			return 63
		case c == '=':
			return 64
		}
		return -1
	}
	i, pad, ultimo, k := 0, 0, -1, 0
	for ; k < len(v); k++ {
		d := decodificar(v[k])
		if d == 64 {
			break
		}
		if d >= 0 {
			i++
			ultimo = d
		}
	}
	for ; k < len(v); k++ {
		d := decodificar(v[k])
		if d >= 0 && d < 64 {
			return false
		}
		if d == 64 {
			pad++
		}
	}
	if pad > 2 || (i+pad)%4 != 0 {
		return false
	}
	switch pad {
	case 1:
		return ultimo&0x03 == 0
	case 2:
		return ultimo&0x0f == 0
	}
	return true
}

// lexicoValido: ¿`v` (ya normalizado) es un valor del tipo primitivo?
func lexicoValido(builtin, v string) bool {
	switch builtin {
	case "string", "normalizedString", "token", "anyURI", "anySimpleType":
		return true
	case "ID", "NCName":
		return reNCName.MatchString(v)
	case "boolean":
		return v == "true" || v == "false" || v == "1" || v == "0"
	case "decimal":
		_, ok := parsearNumero(v)
		return ok
	case "base64Binary":
		return base64Valido(v)
	case "date":
		_, ok := parsearFecha(v, false)
		return ok
	case "dateTime":
		_, ok := parsearFecha(v, true)
		return ok
	}
	// familia integer
	n, ok := new(big.Int).SetString(strings.TrimPrefix(v, "+"), 10)
	if !ok || strings.ContainsAny(v, " ._") {
		return false
	}
	switch builtin {
	case "integer":
		return true
	case "nonNegativeInteger":
		return n.Sign() >= 0
	case "positiveInteger":
		return n.Sign() > 0
	case "long":
		return n.Cmp(minInt64) >= 0 && n.Cmp(maxInt64) <= 0
	case "int":
		return n.IsInt64() && n.Int64() >= -1<<31 && n.Int64() <= 1<<31-1
	case "unsignedLong":
		return n.Sign() >= 0 && n.Cmp(maxUint64) <= 0
	case "unsignedInt":
		return n.Sign() >= 0 && n.Int64() <= 1<<32-1
	}
	return false
}

func esNumerico(builtin string) bool {
	switch builtin {
	case "decimal", "integer", "long", "int", "nonNegativeInteger", "positiveInteger", "unsignedLong", "unsignedInt":
		return true
	}
	return false
}

// normalizar aplica los blancos como libxml2: string y anySimpleType conservan; date/dateTime
// no toleran blancos alrededor (los rechaza, medido); todo lo demás (anyURI, ID, numéricos,
// boolean, base64) colapsa.
func normalizar(builtin, lexico string) string {
	switch builtin {
	case "string", "normalizedString", "anySimpleType", "date", "dateTime":
		return lexico
	}
	return colapsar(lexico)
}

// validarSimple valida el texto `lexico` contra el tipo simple y devuelve los mensajes (sin el
// prefijo del elemento). Normalización de blancos como libxml2: los numéricos, boolean y base64
// colapsan; string conserva; date/dateTime NO toleran blancos alrededor.
func validarSimple(t *tipoSimple, lexico string) []string {
	raiz := raizBuiltin(t)
	valor := normalizar(raiz.builtin, lexico)
	if !lexicoValido(raiz.builtin, valor) {
		return []string{fmt.Sprintf("'%s' no es un valor válido del tipo '%s'.", lexico, nombreTipo(t))}
	}
	var cadena []*tipoSimple
	for x := t; x.builtin == ""; x = x.base {
		cadena = append([]*tipoSimple{x}, cadena...)
	}
	var num numero
	var fecha instante
	switch {
	case esNumerico(raiz.builtin):
		num, _ = parsearNumero(strings.TrimPrefix(valor, "+"))
	case raiz.builtin == "date" || raiz.builtin == "dateTime":
		fecha, _ = parsearFecha(valor, raiz.builtin == "dateTime")
	}
	var errores []string
	for _, x := range cadena {
		var enum []string
		hayEnum := false
		for _, f := range x.facetas {
			switch f.clase {
			case "enumeration":
				hayEnum = true
				enum = append(enum, f.valor)
			case "length", "minLength", "maxLength":
				largo := utf8.RuneCountInString(valor)
				lim, _ := strconv.Atoi(f.valor)
				switch {
				case f.clase == "length" && largo != lim:
					errores = append(errores, fmt.Sprintf("[faceta 'length'] El valor tiene largo %d; se exige %d.", largo, lim))
				case f.clase == "minLength" && largo < lim:
					errores = append(errores, fmt.Sprintf("[faceta 'minLength'] El valor tiene largo %d; no alcanza el mínimo de %d.", largo, lim))
				case f.clase == "maxLength" && largo > lim:
					errores = append(errores, fmt.Sprintf("[faceta 'maxLength'] El valor tiene largo %d; supera el máximo de %d.", largo, lim))
				}
			case "pattern":
				if !f.patron.MatchString(valor) {
					errores = append(errores, fmt.Sprintf("[faceta 'pattern'] El valor '%s' no cumple el patrón '%s'.", valor, f.valor))
				}
			case "totalDigits":
				lim, _ := strconv.Atoi(f.valor)
				if d := len(num.ent) + len(num.frac); d > lim {
					errores = append(errores, fmt.Sprintf("[faceta 'totalDigits'] El valor '%s' tiene más dígitos que los permitidos (%d).", valor, lim))
				}
			case "fractionDigits":
				lim, _ := strconv.Atoi(f.valor)
				if len(num.frac) > lim {
					errores = append(errores, fmt.Sprintf("[faceta 'fractionDigits'] El valor '%s' tiene más decimales que los permitidos (%d).", valor, lim))
				}
			case "minInclusive", "maxInclusive", "minExclusive", "maxExclusive":
				c := comparar(raiz.builtin, num, fecha, f.valor)
				mal := false
				switch f.clase {
				case "minInclusive":
					mal = c < 0
				case "maxInclusive":
					mal = c > 0
				case "minExclusive":
					mal = c <= 0
				case "maxExclusive":
					mal = c >= 0
				}
				if mal {
					rel := "menor que el mínimo"
					if strings.HasPrefix(f.clase, "max") {
						rel = "mayor que el máximo"
					}
					errores = append(errores, fmt.Sprintf("[faceta '%s'] El valor '%s' es %s permitido ('%s').", f.clase, valor, rel, f.valor))
				}
			}
		}
		if hayEnum && !enEnum(raiz.builtin, valor, num, fecha, enum) {
			errores = append(errores, fmt.Sprintf("[faceta 'enumeration'] El valor '%s' no está en el conjunto {'%s'}.", valor, strings.Join(enum, "', '")))
		}
	}
	return errores
}

// comparar devuelve el signo de (valor - faceta) en el espacio de valores del tipo.
func comparar(builtin string, num numero, fecha instante, facetaValor string) int {
	switch {
	case esNumerico(builtin):
		f, ok := parsearNumero(facetaValor)
		if !ok {
			return 0
		}
		return num.rat.Cmp(f.rat)
	case builtin == "date" || builtin == "dateTime":
		f, ok := parsearFecha(facetaValor, builtin == "dateTime")
		if !ok {
			return 0
		}
		return fecha.cmp(f)
	}
	return 0
}

func enEnum(builtin, valor string, num numero, fecha instante, enum []string) bool {
	for _, e := range enum {
		switch {
		case esNumerico(builtin):
			if f, ok := parsearNumero(e); ok && f.rat.Cmp(num.rat) == 0 {
				return true
			}
		case builtin == "date" || builtin == "dateTime":
			if f, ok := parsearFecha(e, builtin == "dateTime"); ok && f.cmp(fecha) == 0 {
				return true
			}
		default:
			if e == valor {
				return true
			}
		}
	}
	return false
}
