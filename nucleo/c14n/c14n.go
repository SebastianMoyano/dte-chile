// Package c14n implementa Canonical XML 1.0 (inclusiva, sin comentarios) sobre el
// subconjunto que usan los documentos del SII, reproduciendo lo que hace
// core/crypto.py::_c14n_reparse: el subárbol se canonicaliza como documento independiente
// con los namespaces heredados de sus ancestros declarados en su ápice.
package c14n

import (
	"encoding/xml"
	"fmt"
	"io"
	"sort"
	"strings"
)

type alcance map[string]string // prefijo ("" = default) → URI

// Canonicalizar recibe el XML del subárbol (string UTF-8, sin declaración) y los
// namespaces heredados de los ancestros (como los renderiza lxml en el ápice al
// serializar el subárbol). Devuelve los bytes C14N (UTF-8).
func Canonicalizar(subarbol string, heredados map[string]string) ([]byte, error) {
	dec := xml.NewDecoder(strings.NewReader(subarbol))
	dec.Strict = true
	var out strings.Builder
	pila := []alcance{{}}
	// prefijos por URI para reconstruir nombres (encoding/xml entrega la URI resuelta)
	profundidad := 0
	for {
		tok, err := dec.RawToken()
		if err == io.EOF {
			break
		}
		if err != nil {
			return nil, err
		}
		switch t := tok.(type) {
		case xml.StartElement:
			padre := pila[len(pila)-1]
			propio := alcance{}
			for k, v := range padre {
				propio[k] = v
			}
			declarados := map[string]string{}
			if profundidad == 0 {
				for p, u := range heredados {
					declarados[p] = u
				}
			}
			var attrs []xml.Attr
			for _, a := range t.Attr {
				switch {
				case a.Name.Space == "" && a.Name.Local == "xmlns":
					declarados[""] = a.Value
				case a.Name.Space == "xmlns":
					declarados[a.Name.Local] = a.Value
				default:
					attrs = append(attrs, a)
				}
			}
			// Namespaces que cambian respecto del alcance del padre, ordenados por prefijo
			// (el default, prefijo vacío, va primero).
			var prefijos []string
			for p, u := range declarados {
				if padre[p] != u {
					prefijos = append(prefijos, p)
				}
				propio[p] = u
			}
			sort.Strings(prefijos)
			out.WriteByte('<')
			out.WriteString(nombre(t.Name))
			for _, p := range prefijos {
				if p == "" {
					out.WriteString(` xmlns="` + escAttr(declarados[p]) + `"`)
				} else {
					out.WriteString(" xmlns:" + p + `="` + escAttr(declarados[p]) + `"`)
				}
			}
			// Atributos ordenados por (URI del namespace, nombre local); los sin prefijo
			// no tienen namespace y van primero.
			sort.SliceStable(attrs, func(i, j int) bool {
				ui, uj := propio[attrs[i].Name.Space], propio[attrs[j].Name.Space]
				if attrs[i].Name.Space == "" {
					ui = ""
				}
				if attrs[j].Name.Space == "" {
					uj = ""
				}
				if ui != uj {
					return ui < uj
				}
				return attrs[i].Name.Local < attrs[j].Name.Local
			})
			for _, a := range attrs {
				out.WriteString(" " + nombre(a.Name) + `="` + escAttr(a.Value) + `"`)
			}
			out.WriteByte('>')
			pila = append(pila, propio)
			profundidad++
		case xml.EndElement:
			out.WriteString("</" + nombre(t.Name) + ">")
			pila = pila[:len(pila)-1]
			profundidad--
		case xml.CharData:
			out.WriteString(escTexto(string(t)))
		case xml.Comment, xml.ProcInst, xml.Directive:
			// sin comentarios; no hay PI ni DTD en estos documentos
		}
	}
	return []byte(out.String()), nil
}

func nombre(n xml.Name) string {
	if n.Space != "" {
		return n.Space + ":" + n.Local // RawToken deja el prefijo literal en Space
	}
	return n.Local
}

func escTexto(s string) string {
	var b strings.Builder
	for _, r := range s {
		switch r {
		case '&':
			b.WriteString("&amp;")
		case '<':
			b.WriteString("&lt;")
		case '>':
			b.WriteString("&gt;")
		case '\r':
			b.WriteString("&#xD;")
		default:
			b.WriteRune(r)
		}
	}
	return b.String()
}

func escAttr(s string) string {
	var b strings.Builder
	for _, r := range s {
		switch r {
		case '&':
			b.WriteString("&amp;")
		case '<':
			b.WriteString("&lt;")
		case '"':
			b.WriteString("&quot;")
		case '\t':
			b.WriteString("&#x9;")
		case '\n':
			b.WriteString("&#xA;")
		case '\r':
			b.WriteString("&#xD;")
		default:
			b.WriteRune(r)
		}
	}
	return b.String()
}

var _ = fmt.Sprintf
