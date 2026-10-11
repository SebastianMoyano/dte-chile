package xsd

import (
	"bytes"
	"encoding/xml"
	"errors"
	"fmt"
	"io"
	"strings"
	"unicode/utf16"
	"unicode/utf8"
)

const (
	nsXSD = "http://www.w3.org/2001/XMLSchema"
	nsXSI = "http://www.w3.org/2001/XMLSchema-instance"
	nsXML = "http://www.w3.org/XML/1998/namespace"
)

// QName es un nombre con namespace (URI, no prefijo).
type QName struct{ NS, Local string }

func (q QName) String() string {
	if q.NS == "" {
		return q.Local
	}
	return "{" + q.NS + "}" + q.Local
}

type atributo struct {
	Nombre QName
	Valor  string
}

// nodo es un elemento del documento (o del XSD): nombre resuelto, atributos sin los xmlns,
// texto concatenado (incluye CDATA), hijos y línea de inicio.
type nodo struct {
	Nombre QName
	Attrs  []atributo
	Texto  string
	Hijos  []*nodo
	Linea  int
	padre  *nodo
	ns     map[string]string // prefijos declarados en ESTE nodo
}

// prefijo resuelve un prefijo declarado en el nodo o en un ancestro ("" = default).
func (n *nodo) prefijo(p string) (string, bool) {
	for m := n; m != nil; m = m.padre {
		if u, ok := m.ns[p]; ok {
			return u, true
		}
	}
	if p == "xml" {
		return nsXML, true
	}
	return "", false
}

// qname resuelve un valor QName ("SiiDte:RUTType") con los prefijos en alcance del nodo.
func (n *nodo) qname(v string) (QName, error) {
	pref, local, con := strings.Cut(v, ":")
	if !con {
		u, _ := n.prefijo("")
		return QName{u, v}, nil
	}
	u, ok := n.prefijo(pref)
	if !ok {
		return QName{}, fmt.Errorf("prefijo no declarado en %q", v)
	}
	return QName{u, local}, nil
}

func (n *nodo) attr(local string) (string, bool) {
	for _, a := range n.Attrs {
		if a.Nombre.NS == "" && a.Nombre.Local == local {
			return a.Valor, true
		}
	}
	return "", false
}

func esBlanco(s string) bool { return strings.TrimSpace(s) == "" }

// parsearArbol construye el árbol del documento. Cualquier error es de sintaxis (mal formado,
// codificación inválida, entidades no definidas, contenido fuera de la raíz). El decoder de
// Go no resuelve entidades externas ni DTD: no hay XXE ni "billion laughs" (como parse_seguro).
func parsearArbol(raw []byte) (*nodo, error) {
	raw = normalizarCodificacion(raw)
	if len(bytes.TrimSpace(raw)) == 0 {
		return nil, errors.New("el documento está vacío")
	}
	d := xml.NewDecoder(bytes.NewReader(raw))
	d.Strict = true
	d.CharsetReader = lectorCharset
	var raiz, actual *nodo
	for {
		tok, err := d.Token()
		if err == io.EOF {
			break
		}
		if err != nil {
			return nil, err
		}
		switch t := tok.(type) {
		case xml.StartElement:
			if raiz != nil && actual == nil {
				return nil, errors.New("contenido extra al final del documento")
			}
			linea, _ := d.InputPos()
			n := &nodo{Nombre: QName{t.Name.Space, t.Name.Local}, Linea: linea, padre: actual}
			for _, a := range t.Attr {
				switch {
				case a.Name.Space == "xmlns":
					if n.ns == nil {
						n.ns = map[string]string{}
					}
					n.ns[a.Name.Local] = a.Value
				case a.Name.Space == "" && a.Name.Local == "xmlns":
					if n.ns == nil {
						n.ns = map[string]string{}
					}
					n.ns[""] = a.Value
				default:
					n.Attrs = append(n.Attrs, atributo{QName{a.Name.Space, a.Name.Local}, a.Value})
				}
			}
			if actual == nil {
				raiz = n
			} else {
				actual.Hijos = append(actual.Hijos, n)
			}
			actual = n
		case xml.EndElement:
			actual = actual.padre
		case xml.CharData:
			if actual == nil {
				if !esBlanco(string(t)) {
					return nil, errors.New("contenido extra al final del documento")
				}
			} else {
				actual.Texto += string(t)
			}
		}
	}
	if raiz == nil {
		return nil, errors.New("no hay elemento raíz")
	}
	return raiz, nil
}

// normalizarCodificacion quita el BOM UTF-8 y transcodifica UTF-16 (con BOM) a UTF-8, que es
// lo único que el decoder no puede resolver por sí mismo a través de CharsetReader.
func normalizarCodificacion(raw []byte) []byte {
	if bytes.HasPrefix(raw, []byte{0xEF, 0xBB, 0xBF}) {
		return raw[3:]
	}
	var be bool
	switch {
	case bytes.HasPrefix(raw, []byte{0xFF, 0xFE}):
	case bytes.HasPrefix(raw, []byte{0xFE, 0xFF}):
		be = true
	default:
		return raw
	}
	raw = raw[2:]
	u := make([]uint16, 0, len(raw)/2)
	for i := 0; i+1 < len(raw); i += 2 {
		if be {
			u = append(u, uint16(raw[i])<<8|uint16(raw[i+1]))
		} else {
			u = append(u, uint16(raw[i+1])<<8|uint16(raw[i]))
		}
	}
	return []byte(string(utf16.Decode(u)))
}

// lectorCharset atiende la declaración encoding="…". ISO-8859-1 es la del SII; windows-1252 y
// el resto de la familia latina se leen como ISO-8859-1 (un byte = un carácter, que es lo que
// importa para largos y patrones). UTF-16 ya viene transcodificado.
func lectorCharset(charset string, r io.Reader) (io.Reader, error) {
	switch strings.ToLower(charset) {
	case "utf-8", "utf8", "us-ascii", "ascii", "utf-16", "utf-16le", "utf-16be":
		return r, nil
	case "iso-8859-1", "iso8859-1", "latin1", "latin-1", "l1", "iso-8859-15", "windows-1252", "cp1252", "iso-8859-2":
		return &lectorLatin1{r: r}, nil
	}
	return nil, fmt.Errorf("codificación no soportada: %s", charset)
}

type lectorLatin1 struct {
	r   io.Reader
	buf []byte
}

func (l *lectorLatin1) Read(p []byte) (int, error) {
	if len(l.buf) == 0 {
		tmp := make([]byte, 4096)
		n, err := l.r.Read(tmp)
		if n == 0 {
			return 0, err
		}
		l.buf = make([]byte, 0, n*2)
		for _, b := range tmp[:n] {
			l.buf = utf8.AppendRune(l.buf, rune(b))
		}
	}
	n := copy(p, l.buf)
	l.buf = l.buf[n:]
	return n, nil
}
