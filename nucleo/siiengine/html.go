package siiengine

import (
	"fmt"
	"html"
	"regexp"
	"strings"
)

// ---------------------------------------------------------------------------
// Codificación. El portal es ISO-8859-1 (Ley L8): los cuerpos se percent-encodean sobre los
// bytes latin-1 (`ñ` → %F1) y en el ORDEN dado (Python: urlencode(..., encoding="latin-1");
// url.Values.Encode() de Go ordena por nombre y codifica UTF-8, así que no sirve).
// ---------------------------------------------------------------------------

// Latin1 decodifica ISO-8859-1: cada byte es su propio code point.
func Latin1(b []byte) string {
	r := make([]rune, len(b))
	for i, c := range b {
		r[i] = rune(c)
	}
	return string(r)
}

// ABytesLatin1 es el inverso de Latin1. Falla con caracteres fuera de ISO-8859-1.
func ABytesLatin1(s string) ([]byte, error) {
	out := make([]byte, 0, len(s))
	for _, r := range s {
		if r > 0xFF {
			return nil, fmt.Errorf("hay un carácter que el portal (ISO-8859-1) no admite: %q", r)
		}
		out = append(out, byte(r))
	}
	return out, nil
}

func quotePlus(b []byte) string {
	const hex = "0123456789ABCDEF"
	var sb strings.Builder
	for _, c := range b {
		switch {
		case c == ' ':
			sb.WriteByte('+')
		case c >= 'a' && c <= 'z', c >= 'A' && c <= 'Z', c >= '0' && c <= '9', c == '_', c == '.', c == '-', c == '~':
			sb.WriteByte(c)
		default:
			sb.WriteByte('%')
			sb.WriteByte(hex[c>>4])
			sb.WriteByte(hex[c&15])
		}
	}
	return sb.String()
}

// Par es un campo de formulario; el orden de los pares es el orden del cuerpo.
type Par struct{ Nombre, Valor string }

// CodificarLatin1 es core/sii_mipyme.py::_body: x-www-form-urlencoded con quote_plus sobre
// bytes latin-1, sin ordenar.
func CodificarLatin1(pares []Par) ([]byte, error) {
	var sb strings.Builder
	for i, p := range pares {
		n, err := ABytesLatin1(p.Nombre)
		if err != nil {
			return nil, err
		}
		v, err := ABytesLatin1(p.Valor)
		if err != nil {
			return nil, err
		}
		if i > 0 {
			sb.WriteByte('&')
		}
		sb.WriteString(quotePlus(n))
		sb.WriteByte('=')
		sb.WriteString(quotePlus(v))
	}
	return []byte(sb.String()), nil
}

// CodificarUTF8 es urlencode(..., encoding="utf-8"): lo usa el XHR de la firma central.
func CodificarUTF8(pares []Par) []byte {
	var sb strings.Builder
	for i, p := range pares {
		if i > 0 {
			sb.WriteByte('&')
		}
		sb.WriteString(quotePlus([]byte(p.Nombre)))
		sb.WriteByte('=')
		sb.WriteString(quotePlus([]byte(p.Valor)))
	}
	return []byte(sb.String())
}

// ---------------------------------------------------------------------------
// Un tokenizador mínimo con la semántica de html.parser.HTMLParser (convert_charrefs=True):
// tags y atributos en minúscula, valores y datos des-escapados, <script>/<style> como texto
// crudo, comentarios ignorados. Suficiente para las páginas CGI del portal, y sin dependencias.
// ---------------------------------------------------------------------------

type token struct {
	tag    string            // "" = texto
	cierre bool              // </tag>
	attrs  map[string]string // para tags de apertura
	texto  string            // para texto
}

var (
	reTag  = regexp.MustCompile(`(?s)<!--.*?-->|<(/?)([a-zA-Z][a-zA-Z0-9]*)((?:\s+[^\s=>/]+(?:\s*=\s*(?:"[^"]*"|'[^']*'|[^\s"'>]+))?)*)\s*/?>`)
	reAttr = regexp.MustCompile(`([^\s=>/]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>]+)))?`)
)

func parsearAttrs(s string) map[string]string {
	out := map[string]string{}
	for _, m := range reAttr.FindAllStringSubmatch(s, -1) {
		v := m[2] + m[3] + m[4]
		out[strings.ToLower(m[1])] = html.UnescapeString(v)
	}
	return out
}

func tokenizar(doc string) []token {
	var out []token
	pos := 0
	for pos < len(doc) {
		loc := reTag.FindStringSubmatchIndex(doc[pos:])
		if loc == nil {
			out = append(out, token{texto: html.UnescapeString(doc[pos:])})
			break
		}
		if loc[0] > 0 {
			out = append(out, token{texto: html.UnescapeString(doc[pos : pos+loc[0]])})
		}
		if loc[4] < 0 { // comentario
			pos += loc[1]
			continue
		}
		cierre := loc[3] > loc[2]
		tag := strings.ToLower(doc[pos+loc[4] : pos+loc[5]])
		t := token{tag: tag, cierre: cierre}
		if !cierre {
			t.attrs = parsearAttrs(doc[pos+loc[6] : pos+loc[7]])
		}
		out = append(out, t)
		pos += loc[1]
		if !cierre && (tag == "script" || tag == "style") {
			fin := strings.Index(strings.ToLower(doc[pos:]), "</"+tag)
			if fin < 0 {
				fin = len(doc) - pos
			}
			out = append(out, token{texto: doc[pos : pos+fin]})
			pos += fin
		}
	}
	return out
}

// ParsearForm es core/sii_mipyme.py::parsear_form: `{name: value}` de todos los
// input/select/textarea del HTML. El primer input con un nombre gana; en un select gana la
// opción marcada y, si ninguna lo está, la primera (como el navegador); el textarea acumula
// su texto.
func ParsearForm(doc string) map[string]string {
	campos := map[string]string{}
	sel, textarea := "", ""
	selMarcado, selVioOpcion := false, false
	setdefault := func(k, v string) {
		if _, ok := campos[k]; !ok {
			campos[k] = v
		}
	}
	for _, t := range tokenizar(doc) {
		switch {
		case t.tag == "" && textarea != "":
			campos[textarea] += t.texto
		case t.tag == "":
		case t.cierre && t.tag == "select":
			sel = ""
		case t.cierre && t.tag == "textarea":
			textarea = ""
		case t.cierre:
		case t.tag == "input" && t.attrs["name"] != "":
			setdefault(t.attrs["name"], t.attrs["value"])
		case t.tag == "select" && t.attrs["name"] != "":
			sel = t.attrs["name"]
			selMarcado, selVioOpcion = false, false
			setdefault(sel, "")
		case t.tag == "option" && sel != "":
			if _, ok := t.attrs["selected"]; ok {
				campos[sel] = t.attrs["value"]
				selMarcado = true
			} else if !selMarcado && !selVioOpcion {
				campos[sel] = t.attrs["value"]
			}
			selVioOpcion = true
		case t.tag == "textarea" && t.attrs["name"] != "":
			textarea = t.attrs["name"]
			setdefault(textarea, "")
		}
	}
	return campos
}

// fila es lo que _FilasParser junta por cada <tr>: celdas y hrefs.
type fila struct {
	celdas []string
	hrefs  []string
}

func parsearFilas(doc string) []fila {
	var out []fila
	var cur *fila
	celda := -1
	for _, t := range tokenizar(doc) {
		switch {
		case t.tag == "":
			if cur != nil && celda >= 0 {
				cur.celdas[celda] += t.texto
			}
		case !t.cierre && t.tag == "tr":
			cur = &fila{}
			celda = -1
		case !t.cierre && cur != nil && (t.tag == "td" || t.tag == "th"):
			cur.celdas = append(cur.celdas, "")
			celda = len(cur.celdas) - 1
		case !t.cierre && cur != nil && t.tag == "a" && t.attrs["href"] != "":
			cur.hrefs = append(cur.hrefs, t.attrs["href"])
		case t.cierre && (t.tag == "td" || t.tag == "th"):
			celda = -1
		case t.cierre && t.tag == "tr" && cur != nil:
			for _, c := range cur.celdas {
				if strings.TrimSpace(c) != "" {
					out = append(out, *cur)
					break
				}
			}
			cur = nil
		}
	}
	return out
}
