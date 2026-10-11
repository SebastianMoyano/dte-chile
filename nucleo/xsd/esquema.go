package xsd

import (
	"embed"
	"fmt"
	"path"
	"regexp"
	"strconv"
)

// Copias byte a byte de core/xsd/*.xsd (TestEsquemasIguales lo exige): los XSD oficiales
// del SII más el de XMLDSig que importan.
//
//go:embed esquemas/*.xsd
var esquemasFS embed.FS

type tipo interface{ esTipo() }

type faceta struct {
	clase  string
	valor  string
	patron *regexp.Regexp
}

// tipoSimple es un xs:simpleType (nombrado o anónimo) o un tipo primitivo de XSD (builtin != "").
type tipoSimple struct {
	nombre  QName
	base    *tipoSimple
	baseRef QName
	builtin string
	facetas []faceta
}

func (*tipoSimple) esTipo() {}

type atributoDecl struct {
	nombre  string
	tipo    *tipoSimple
	tipoRef QName
	req     bool
	fijo    *string
}

// tipoComplejo: atributos + (secuencia/elección | contenido simple | vacío).
type tipoComplejo struct {
	nombre    QName
	attrs     []*atributoDecl
	particula *particula
	simple    *tipoSimple
}

func (*tipoComplejo) esTipo() {}

const (
	pSecuencia = iota
	pEleccion
	pElemento
)

type particula struct {
	clase    int
	min, max int // max -1 = unbounded
	hijos    []*particula
	elem     *elemento
	ref      QName
}

type elemento struct {
	nombre  QName
	tipo    tipo
	tipoRef QName
}

type esquema struct {
	elementos map[QName]*elemento
	tipos     map[QName]tipo
	archivos  map[string]bool
	builtins  map[string]*tipoSimple

	pendSimples []*tipoSimple
	pendElems   []*elemento
	pendAttrs   []*atributoDecl
	pendParts   []*particula
}

// cargarEsquema carga un XSD embebido con sus include/import y resuelve las referencias.
func cargarEsquema(archivo string) (*esquema, error) {
	e := &esquema{elementos: map[QName]*elemento{}, tipos: map[QName]tipo{}, archivos: map[string]bool{}, builtins: map[string]*tipoSimple{}}
	if err := e.cargarArchivo(archivo); err != nil {
		return nil, err
	}
	if err := e.resolver(); err != nil {
		return nil, err
	}
	return e, nil
}

func (e *esquema) cargarArchivo(archivo string) error {
	if e.archivos[archivo] {
		return nil
	}
	e.archivos[archivo] = true
	raw, err := esquemasFS.ReadFile("esquemas/" + archivo)
	if err != nil {
		return err
	}
	raiz, err := parsearArbol(raw)
	if err != nil {
		return fmt.Errorf("%s: %v", archivo, err)
	}
	if raiz.Nombre != (QName{nsXSD, "schema"}) {
		return fmt.Errorf("%s: la raíz no es xs:schema", archivo)
	}
	tns, _ := raiz.attr("targetNamespace")
	for _, h := range raiz.Hijos {
		if h.Nombre.NS != nsXSD {
			return fmt.Errorf("%s: nodo inesperado %s", archivo, h.Nombre)
		}
		switch h.Nombre.Local {
		case "include", "import":
			loc, _ := h.attr("schemaLocation")
			if err := e.cargarArchivo(path.Base(loc)); err != nil {
				return err
			}
		case "element":
			el, err := e.parsearElemento(h, tns)
			if err != nil {
				return fmt.Errorf("%s: %v", archivo, err)
			}
			e.elementos[el.nombre] = el
		case "complexType":
			nombre, _ := h.attr("name")
			t, err := e.parsearComplejo(h, tns)
			if err != nil {
				return fmt.Errorf("%s: %v", archivo, err)
			}
			t.nombre = QName{tns, nombre}
			e.tipos[t.nombre] = t
		case "simpleType":
			nombre, _ := h.attr("name")
			t, err := e.parsearSimple(h)
			if err != nil {
				return fmt.Errorf("%s: %v", archivo, err)
			}
			t.nombre = QName{tns, nombre}
			e.tipos[t.nombre] = t
		case "attribute": // declaración global (SiiTypes declara una `version` que nadie referencia)
			if _, err := e.parsearAtributo(h); err != nil {
				return fmt.Errorf("%s: %v", archivo, err)
			}
		case "annotation":
		default:
			return fmt.Errorf("%s: constructo XSD no soportado: %s", archivo, h.Nombre.Local)
		}
	}
	return nil
}

func ocurrencias(n *nodo) (int, int, error) {
	min, max := 1, 1
	if v, ok := n.attr("minOccurs"); ok {
		x, err := strconv.Atoi(v)
		if err != nil {
			return 0, 0, fmt.Errorf("minOccurs inválido: %q", v)
		}
		min = x
	}
	if v, ok := n.attr("maxOccurs"); ok {
		if v == "unbounded" {
			max = -1
		} else {
			x, err := strconv.Atoi(v)
			if err != nil {
				return 0, 0, fmt.Errorf("maxOccurs inválido: %q", v)
			}
			max = x
		}
	}
	return min, max, nil
}

func (e *esquema) parsearElemento(n *nodo, tns string) (*elemento, error) {
	nombre, _ := n.attr("name")
	el := &elemento{nombre: QName{tns, nombre}}
	if t, ok := n.attr("type"); ok {
		q, err := n.qname(t)
		if err != nil {
			return nil, err
		}
		el.tipoRef = q
		e.pendElems = append(e.pendElems, el)
	}
	for _, h := range n.Hijos {
		switch h.Nombre.Local {
		case "complexType":
			t, err := e.parsearComplejo(h, tns)
			if err != nil {
				return nil, err
			}
			el.tipo = t
		case "simpleType":
			t, err := e.parsearSimple(h)
			if err != nil {
				return nil, err
			}
			el.tipo = t
		case "annotation":
		default:
			return nil, fmt.Errorf("elemento %s: hijo no soportado %s", nombre, h.Nombre.Local)
		}
	}
	if el.tipo == nil && el.tipoRef == (QName{}) {
		return nil, fmt.Errorf("elemento %s sin tipo (anyType no soportado)", nombre)
	}
	return el, nil
}

// parsearParticulaElemento es un xs:element dentro de un grupo: declaración local o ref.
func (e *esquema) parsearParticulaElemento(n *nodo, tns string) (*particula, error) {
	min, max, err := ocurrencias(n)
	if err != nil {
		return nil, err
	}
	p := &particula{clase: pElemento, min: min, max: max}
	if ref, ok := n.attr("ref"); ok {
		q, err := n.qname(ref)
		if err != nil {
			return nil, err
		}
		p.ref = q
		e.pendParts = append(e.pendParts, p)
		return p, nil
	}
	el, err := e.parsearElemento(n, tns)
	if err != nil {
		return nil, err
	}
	p.elem = el
	return p, nil
}

func (e *esquema) parsearGrupo(n *nodo, tns string) (*particula, error) {
	min, max, err := ocurrencias(n)
	if err != nil {
		return nil, err
	}
	p := &particula{min: min, max: max}
	switch n.Nombre.Local {
	case "sequence":
		p.clase = pSecuencia
	case "choice":
		p.clase = pEleccion
	default:
		return nil, fmt.Errorf("grupo no soportado: %s", n.Nombre.Local)
	}
	for _, h := range n.Hijos {
		switch h.Nombre.Local {
		case "element":
			c, err := e.parsearParticulaElemento(h, tns)
			if err != nil {
				return nil, err
			}
			p.hijos = append(p.hijos, c)
		case "sequence", "choice":
			c, err := e.parsearGrupo(h, tns)
			if err != nil {
				return nil, err
			}
			p.hijos = append(p.hijos, c)
		case "annotation":
		default:
			return nil, fmt.Errorf("dentro de %s: %s no soportado", n.Nombre.Local, h.Nombre.Local)
		}
	}
	return p, nil
}

func (e *esquema) parsearComplejo(n *nodo, tns string) (*tipoComplejo, error) {
	t := &tipoComplejo{}
	for _, h := range n.Hijos {
		switch h.Nombre.Local {
		case "sequence", "choice":
			p, err := e.parsearGrupo(h, tns)
			if err != nil {
				return nil, err
			}
			t.particula = p
		case "simpleContent":
			for _, x := range h.Hijos {
				if x.Nombre.Local != "extension" {
					return nil, fmt.Errorf("simpleContent/%s no soportado", x.Nombre.Local)
				}
				base, _ := x.attr("base")
				q, err := x.qname(base)
				if err != nil {
					return nil, err
				}
				st := &tipoSimple{baseRef: q}
				e.pendSimples = append(e.pendSimples, st)
				t.simple = st
				for _, a := range x.Hijos {
					switch a.Nombre.Local {
					case "attribute":
						ad, err := e.parsearAtributo(a)
						if err != nil {
							return nil, err
						}
						t.attrs = append(t.attrs, ad)
					case "annotation":
					default:
						return nil, fmt.Errorf("extension/%s no soportado", a.Nombre.Local)
					}
				}
			}
		case "attribute":
			ad, err := e.parsearAtributo(h)
			if err != nil {
				return nil, err
			}
			t.attrs = append(t.attrs, ad)
		case "annotation":
		default:
			return nil, fmt.Errorf("complexType/%s no soportado", h.Nombre.Local)
		}
	}
	return t, nil
}

func (e *esquema) parsearAtributo(n *nodo) (*atributoDecl, error) {
	nombre, _ := n.attr("name")
	a := &atributoDecl{nombre: nombre}
	if u, _ := n.attr("use"); u == "required" {
		a.req = true
	}
	if f, ok := n.attr("fixed"); ok {
		a.fijo = &f
	}
	if t, ok := n.attr("type"); ok {
		q, err := n.qname(t)
		if err != nil {
			return nil, err
		}
		a.tipoRef = q
		e.pendAttrs = append(e.pendAttrs, a)
	}
	for _, h := range n.Hijos {
		switch h.Nombre.Local {
		case "simpleType":
			t, err := e.parsearSimple(h)
			if err != nil {
				return nil, err
			}
			a.tipo = t
		case "annotation":
		default:
			return nil, fmt.Errorf("attribute/%s no soportado", h.Nombre.Local)
		}
	}
	if a.tipo == nil && a.tipoRef == (QName{}) {
		a.tipoRef = QName{nsXSD, "anySimpleType"}
		e.pendAttrs = append(e.pendAttrs, a)
	}
	return a, nil
}

func (e *esquema) parsearSimple(n *nodo) (*tipoSimple, error) {
	t := &tipoSimple{}
	for _, h := range n.Hijos {
		switch h.Nombre.Local {
		case "restriction":
			if b, ok := h.attr("base"); ok {
				q, err := h.qname(b)
				if err != nil {
					return nil, err
				}
				t.baseRef = q
				e.pendSimples = append(e.pendSimples, t)
			}
			for _, f := range h.Hijos {
				switch f.Nombre.Local {
				case "simpleType":
					b, err := e.parsearSimple(f)
					if err != nil {
						return nil, err
					}
					t.base = b
				case "annotation":
				case "enumeration", "length", "minLength", "maxLength", "pattern", "totalDigits", "fractionDigits",
					"minInclusive", "maxInclusive", "minExclusive", "maxExclusive":
					v, _ := f.attr("value")
					fa := faceta{clase: f.Nombre.Local, valor: v}
					if fa.clase == "pattern" {
						re, err := regexp.Compile("^(?:" + v + ")$")
						if err != nil {
							return nil, fmt.Errorf("patrón %q: %v", v, err)
						}
						fa.patron = re
					}
					t.facetas = append(t.facetas, fa)
				case "whiteSpace":
					return nil, fmt.Errorf("faceta whiteSpace no soportada")
				default:
					return nil, fmt.Errorf("faceta no soportada: %s", f.Nombre.Local)
				}
			}
		case "annotation":
		default:
			return nil, fmt.Errorf("simpleType/%s no soportado (union/list)", h.Nombre.Local)
		}
	}
	if t.base == nil && t.baseRef == (QName{}) {
		return nil, fmt.Errorf("simpleType sin restriction/base")
	}
	return t, nil
}

func (e *esquema) builtin(local string) (*tipoSimple, error) {
	if t, ok := e.builtins[local]; ok {
		return t, nil
	}
	if !builtinSoportado(local) {
		return nil, fmt.Errorf("tipo primitivo xs:%s no soportado", local)
	}
	t := &tipoSimple{nombre: QName{nsXSD, local}, builtin: local}
	e.builtins[local] = t
	return t, nil
}

func (e *esquema) tipoSimplePor(q QName) (*tipoSimple, error) {
	if q.NS == nsXSD {
		return e.builtin(q.Local)
	}
	t, ok := e.tipos[q]
	if !ok {
		return nil, fmt.Errorf("tipo no declarado: %s", q)
	}
	st, ok := t.(*tipoSimple)
	if !ok {
		return nil, fmt.Errorf("%s no es un tipo simple", q)
	}
	return st, nil
}

func (e *esquema) resolver() error {
	for _, t := range e.pendSimples {
		b, err := e.tipoSimplePor(t.baseRef)
		if err != nil {
			return err
		}
		t.base = b
	}
	for _, el := range e.pendElems {
		if el.tipoRef.NS == nsXSD {
			b, err := e.builtin(el.tipoRef.Local)
			if err != nil {
				return err
			}
			el.tipo = b
			continue
		}
		t, ok := e.tipos[el.tipoRef]
		if !ok {
			return fmt.Errorf("elemento %s: tipo no declarado %s", el.nombre, el.tipoRef)
		}
		el.tipo = t
	}
	for _, a := range e.pendAttrs {
		t, err := e.tipoSimplePor(a.tipoRef)
		if err != nil {
			return fmt.Errorf("atributo %s: %v", a.nombre, err)
		}
		a.tipo = t
	}
	for _, p := range e.pendParts {
		el, ok := e.elementos[p.ref]
		if !ok {
			return fmt.Errorf("ref a elemento no declarado: %s", p.ref)
		}
		p.elem = el
	}
	return nil
}
