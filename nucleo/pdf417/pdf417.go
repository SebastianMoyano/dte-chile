// Package pdf417 codifica PDF417, port fiel de pdf417gen (Python), la librería con que el motor
// dibuja el timbre del SII. Las tablas (tablas.go) se generan desde pdf417gen con
// tools/generar_pdf417.py, y el test exige que las filas de códigos sean idénticas a las de
// Python para un juego de entradas (testdata/vectores.json): mismo timbre, módulo por módulo.
//
// Por qué un port y no una librería: la guía del SII pide nivel de corrección 5 y el timbre
// se lee con cualquier lector; la librería Go que se probó producía códigos que un
// decodificador no leía. Con el port, el timbre de Go es el mismo que el de Python, que sí se
// lee (verificado con pdf417decoder).
package pdf417

import (
	"errors"
	"fmt"
	"image"
	"image/color"
	"math"
	"math/big"
)

const (
	inicio       = 0x1fea8
	fin          = 0x3fa29
	relleno      = 900
	maxPalabras  = 928
	minFilas     = 3
	maxFilas     = 90
	latchTexto   = 900
	latchBytes   = 901
	latchBytes6  = 924
	latchNumeros = 902
	padInterino  = 29
)

const (
	upper = iota
	lower
	mixed
	punct
)

type modo int

const (
	modoTexto modo = iota
	modoNumeros
	modoBytes
)

type trozo struct {
	datos []byte
	fn    modo
}

func modoOptimo(c byte) modo {
	if c >= '0' && c <= '9' {
		return modoNumeros
	}
	if _, ok := caracteresLookup[c]; ok {
		return modoTexto
	}
	return modoBytes
}

// compactar es pdf417gen.compaction.compact.
func compactar(datos []byte) []int {
	// trozos por modo óptimo (groupby)
	var trozos []trozo
	for _, c := range datos {
		m := modoOptimo(c)
		if len(trozos) > 0 && trozos[len(trozos)-1].fn == m {
			trozos[len(trozos)-1].datos = append(trozos[len(trozos)-1].datos, c)
		} else {
			trozos = append(trozos, trozo{[]byte{c}, m})
		}
	}
	// numéricos cortos (<13) pegados a texto pasan a texto (se mira la lista ORIGINAL)
	reemplazados := make([]trozo, len(trozos))
	for i, t := range trozos {
		reemplazados[i] = t
		if t.fn == modoNumeros && len(t.datos) < 13 {
			bordeaTexto := (i > 0 && trozos[i-1].fn == modoTexto) || (i+1 < len(trozos) && trozos[i+1].fn == modoTexto)
			if bordeaTexto {
				reemplazados[i].fn = modoTexto
			}
		}
	}
	// fusionar consecutivos del mismo modo
	var fusionados []trozo
	for _, t := range reemplazados {
		if len(fusionados) > 0 && fusionados[len(fusionados)-1].fn == t.fn {
			fusionados[len(fusionados)-1].datos = append(fusionados[len(fusionados)-1].datos, t.datos...)
		} else {
			fusionados = append(fusionados, trozo{append([]byte{}, t.datos...), t.fn})
		}
	}
	var out []int
	for i, t := range fusionados {
		if i > 0 || t.fn != modoTexto {
			switch t.fn {
			case modoTexto:
				out = append(out, latchTexto)
			case modoBytes:
				if len(t.datos)%6 == 0 {
					out = append(out, latchBytes6)
				} else {
					out = append(out, latchBytes)
				}
			case modoNumeros:
				out = append(out, latchNumeros)
			}
		}
		switch t.fn {
		case modoTexto:
			out = append(out, compactarTexto(t.datos)...)
		case modoNumeros:
			out = append(out, compactarNumeros(t.datos)...)
		case modoBytes:
			out = append(out, compactarBytes(t.datos)...)
		}
	}
	return out
}

func submodoDe(c byte) int {
	v := caracteresLookup[c]
	for _, m := range []int{lower, upper, mixed, punct} { // preferencia de pdf417gen
		if v[m] >= 0 {
			return m
		}
	}
	return upper
}

func compactarTexto(datos []byte) []int {
	var interinos []int
	sub := upper
	for _, c := range datos {
		v := caracteresLookup[c]
		if v[sub] < 0 {
			prev := sub
			sub = submodoDe(c)
			interinos = append(interinos, switchCodes[prev][sub]...)
		}
		interinos = append(interinos, v[sub])
	}
	var out []int
	for i := 0; i < len(interinos); i += 2 {
		a := interinos[i]
		b := padInterino
		if i+1 < len(interinos) {
			b = interinos[i+1]
		}
		out = append(out, 30*a+b)
	}
	return out
}

func aBase(v *big.Int, base int64) []int {
	var digitos []int
	b := big.NewInt(base)
	zero := big.NewInt(0)
	n := new(big.Int).Set(v)
	m := new(big.Int)
	for n.Cmp(zero) > 0 {
		n.DivMod(n, b, m)
		digitos = append([]int{int(m.Int64())}, digitos...)
	}
	return digitos
}

func compactarNumeros(datos []byte) []int {
	var out []int
	for i := 0; i < len(datos); i += 44 {
		fin := i + 44
		if fin > len(datos) {
			fin = len(datos)
		}
		v, _ := new(big.Int).SetString("1"+string(datos[i:fin]), 10)
		out = append(out, aBase(v, 900)...)
	}
	return out
}

func compactarBytes(datos []byte) []int {
	var out []int
	for i := 0; i < len(datos); i += 6 {
		fin := i + 6
		if fin > len(datos) {
			fin = len(datos)
		}
		tr := datos[i:fin]
		if len(tr) == 6 {
			v := new(big.Int).SetBytes(tr)
			d := aBase(v, 900)
			for len(d) < 5 {
				d = append([]int{0}, d...)
			}
			out = append(out, d...)
		} else {
			for _, c := range tr {
				out = append(out, int(c))
			}
		}
	}
	return out
}

// correccion es compute_error_correction_code_words (Reed-Solomon sobre GF(929)).
func correccion(palabras []int, nivel int) []int {
	f := factoresEC[nivel]
	n := 1 << (nivel + 1)
	ec := make([]int, n)
	for _, p := range palabras {
		t := (p + ec[n-1]) % 929
		for x := n - 1; x >= 0; x-- {
			w := 0
			if x > 0 {
				w = ec[x-1]
			}
			ec[x] = (w + 929 - (t*f[x])%929) % 929
		}
	}
	out := make([]int, n)
	for i := range ec {
		v := ec[n-1-i]
		if v > 0 {
			v = 929 - v
		}
		out[i] = v
	}
	return out
}

func indicadorIzq(fila, filas, cols, nivel int) int {
	var x int
	switch fila % 3 {
	case 0:
		x = (filas - 1) / 3
	case 1:
		x = nivel*3 + (filas-1)%3
	case 2:
		x = cols - 1
	}
	return 30*(fila/3) + x
}

func indicadorDer(fila, filas, cols, nivel int) int {
	var x int
	switch fila % 3 {
	case 0:
		x = cols - 1
	case 1:
		x = (filas - 1) / 3
	case 2:
		x = nivel*3 + (filas-1)%3
	}
	return 30*(fila/3) + x
}

// Codificar es pdf417gen.encode: filas de códigos de bajo nivel (patrones de barras), con
// `columnas` columnas de datos (1-30) y nivel de seguridad 0-8.
func Codificar(datos []byte, columnas, nivel int) ([][]int, error) {
	if columnas < 1 || columnas > 30 {
		return nil, fmt.Errorf("'columns' must be between 1 and 30. Given: %d", columnas)
	}
	if nivel < 0 || nivel > 8 {
		return nil, fmt.Errorf("'security_level' must be between 1 and 8. Given: %d", nivel)
	}
	palabras := compactar(datos)
	ecN := 1 << (nivel + 1)
	total := len(palabras) + ecN + 1
	pad := 0
	if m := total % columnas; m > 0 {
		pad = columnas - m
	}
	descriptor := len(palabras) + pad + 1
	filas := int(math.Ceil(float64(len(palabras)+ecN+pad+1) / float64(columnas)))
	if descriptor > maxPalabras {
		return nil, errors.New("Data too long")
	}
	if filas < minFilas {
		return nil, fmt.Errorf("Generated bar code has %d rows. Minimum is %d rows. Try decreasing column count.", filas, minFilas)
	}
	if filas > maxFilas {
		return nil, fmt.Errorf("Generated bar code has %d rows. Maximum is %d rows. Try increasing column count.", filas, maxFilas)
	}
	ext := append([]int{descriptor}, palabras...)
	for i := 0; i < pad; i++ {
		ext = append(ext, relleno)
	}
	todas := append(ext, correccion(ext, nivel)...)
	var out [][]int
	for r := 0; r < filas; r++ {
		tabla := r % 3
		fila := []int{inicio, codigos[tabla][indicadorIzq(r, filas, columnas, nivel)]}
		for c := 0; c < columnas; c++ {
			fila = append(fila, codigos[tabla][todas[r*columnas+c]])
		}
		fila = append(fila, codigos[tabla][indicadorDer(r, filas, columnas, nivel)], fin)
		out = append(out, fila)
	}
	return out, nil
}

// Imagen es render_image: módulo de `escala` px de ancho y `escala*razon` px de alto, con un
// margen `margen` px en blanco. Gris de 8 bits (negro = barra).
func Imagen(filas [][]int, escala, razon, margen int) *image.Gray {
	ancho := len(filas[0])*17 + 1
	alto := len(filas)
	img := image.NewGray(image.Rect(0, 0, ancho*escala+2*margen, alto*escala*razon+2*margen))
	for i := range img.Pix {
		img.Pix[i] = 255
	}
	for y, fila := range filas {
		x := 0
		for _, v := range fila {
			nbits := 0
			for t := v; t > 0; t >>= 1 {
				nbits++
			}
			for b := nbits - 1; b >= 0; b-- {
				if v&(1<<b) != 0 {
					for dy := 0; dy < escala*razon; dy++ {
						for dx := 0; dx < escala; dx++ {
							img.SetGray(margen+x*escala+dx, margen+y*escala*razon+dy, color.Gray{0})
						}
					}
				}
				x++
			}
		}
	}
	return img
}
