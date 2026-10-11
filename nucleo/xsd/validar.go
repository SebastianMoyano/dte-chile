package xsd

import (
	"fmt"
	"strings"
)

// Error es un hallazgo de la validación. Elemento es el nombre local del elemento al que
// libxml2 se lo atribuiría (el inesperado, el que falta hijos, el dueño del atributo).
type Error struct {
	Linea    int
	Elemento string
	Atributo string
	Mensaje  string
}

func (e Error) String() string {
	if e.Elemento == "" {
		return e.Mensaje
	}
	s := fmt.Sprintf("Línea %d: Elemento '%s'", e.Linea, e.Elemento)
	if e.Atributo != "" {
		s += fmt.Sprintf(", atributo '%s'", e.Atributo)
	}
	return s + ": " + e.Mensaje
}

type contexto struct {
	errores []Error
	ids     map[string]bool // xs:ID vistos: libxml2 exige unicidad en el documento
}

func (c *contexto) error(n *nodo, msg string) {
	c.errores = append(c.errores, Error{Linea: n.Linea, Elemento: n.Nombre.Local, Mensaje: msg})
}

func (c *contexto) errorAttr(n *nodo, attr, msg string) {
	c.errores = append(c.errores, Error{Linea: n.Linea, Elemento: n.Nombre.Local, Atributo: attr, Mensaje: msg})
}

func (c *contexto) validarElemento(n *nodo, decl *elemento) {
	switch t := decl.tipo.(type) {
	case *tipoSimple:
		c.validarAtributos(n, nil)
		if len(n.Hijos) > 0 {
			c.error(n, "No se permiten elementos hijos, porque el tipo es simple.")
			return
		}
		for _, m := range validarSimple(t, n.Texto) {
			c.error(n, m)
		}
	case *tipoComplejo:
		c.validarAtributos(n, t.attrs)
		switch {
		case t.simple != nil:
			if len(n.Hijos) > 0 {
				c.error(n, "No se permiten elementos hijos, porque el contenido es de tipo simple.")
				return
			}
			for _, m := range validarSimple(t.simple, n.Texto) {
				c.error(n, m)
			}
		case t.particula == nil:
			if len(n.Hijos) > 0 {
				c.error(n, "No se permiten elementos hijos, porque el contenido es vacío.")
			}
			if n.Texto != "" {
				c.error(n, "No se permite texto, porque el contenido es vacío.")
			}
		default:
			if !esBlanco(n.Texto) {
				c.error(n, "No se permite texto que no sea blanco, porque el contenido es solo de elementos.")
			}
			c.validarContenido(n, t.particula)
		}
	}
}

func (c *contexto) validarAtributos(n *nodo, decls []*atributoDecl) {
	vistos := map[string]bool{}
	for _, a := range n.Attrs {
		if a.Nombre.NS == nsXSI {
			if a.Nombre.Local == "schemaLocation" || a.Nombre.Local == "noNamespaceSchemaLocation" {
				continue
			}
			c.errorAttr(n, "xsi:"+a.Nombre.Local, fmt.Sprintf("El atributo 'xsi:%s' no está permitido aquí.", a.Nombre.Local))
			continue
		}
		var d *atributoDecl
		if a.Nombre.NS == "" {
			for _, x := range decls {
				if x.nombre == a.Nombre.Local {
					d = x
					break
				}
			}
		}
		if d == nil {
			c.errorAttr(n, a.Nombre.String(), fmt.Sprintf("El atributo '%s' no está permitido.", a.Nombre))
			continue
		}
		vistos[d.nombre] = true
		errs := validarSimple(d.tipo, a.Valor)
		for _, m := range errs {
			c.errorAttr(n, d.nombre, m)
		}
		if len(errs) == 0 && raizBuiltin(d.tipo).builtin == "ID" {
			id := colapsar(a.Valor)
			if c.ids[id] {
				c.errorAttr(n, d.nombre, fmt.Sprintf("'%s' no es un valor válido del tipo 'xs:ID' (repetido en el documento).", a.Valor))
			}
			if c.ids == nil {
				c.ids = map[string]bool{}
			}
			c.ids[id] = true
		}
		if d.fijo != nil && len(errs) == 0 && !mismoValor(d.tipo, a.Valor, *d.fijo) {
			c.errorAttr(n, d.nombre, fmt.Sprintf("El valor '%s' no coincide con el valor fijo '%s'.", a.Valor, *d.fijo))
		}
	}
	for _, d := range decls {
		if d.req && !vistos[d.nombre] {
			c.error(n, fmt.Sprintf("Falta el atributo obligatorio '%s'.", d.nombre))
		}
	}
}

// mismoValor compara en el espacio de valores: numérico para los tipos numéricos (1.00 == 1.0),
// lexical para el resto (anySimpleType incluido: libxml2 rechaza '1.00' contra el fijo '1.0').
func mismoValor(t *tipoSimple, a, b string) bool {
	raiz := raizBuiltin(t).builtin
	if esNumerico(raiz) {
		x, okx := parsearNumero(strings.TrimPrefix(colapsar(a), "+"))
		y, oky := parsearNumero(strings.TrimPrefix(colapsar(b), "+"))
		return okx && oky && x.rat.Cmp(y.rat) == 0
	}
	return normalizar(raiz, a) == normalizar(raiz, b)
}

// emparejador recorre los hijos con el modelo de contenido (greedy: los XSD cumplen la regla
// de atribución única, así que no hace falta retroceder) y anota, por posición, qué elementos
// se probaron sin éxito: con eso se arma el "se esperaba (…)" del error.
type emparejador struct {
	c         *contexto
	hijos     []*nodo
	esperados map[int][]string
}

func (m *emparejador) esperado(pos int, q QName) {
	for _, e := range m.esperados[pos] {
		if e == q.Local {
			return
		}
	}
	m.esperados[pos] = append(m.esperados[pos], q.Local)
}

func (m *emparejador) aceptar(p *particula, pos int) (int, bool) {
	switch p.clase {
	case pElemento:
		if pos < len(m.hijos) && m.hijos[pos].Nombre == p.elem.nombre {
			m.c.validarElemento(m.hijos[pos], p.elem)
			return pos + 1, true
		}
		m.esperado(pos, p.elem.nombre)
		return pos, false
	case pSecuencia:
		cur := pos
		for _, h := range p.hijos {
			n := 0
			for h.max < 0 || n < h.max {
				np, ok := m.aceptar(h, cur)
				if !ok {
					break
				}
				if np == cur { // el grupo admite vacío: cuenta como satisfecho
					n = h.min
					break
				}
				cur = np
				n++
			}
			if n < h.min {
				return pos, false
			}
		}
		return cur, true
	case pEleccion:
		vacioOK := false
		for _, h := range p.hijos {
			np, ok := m.aceptar(h, pos)
			if ok && np > pos {
				return np, true
			}
			if ok {
				vacioOK = true
			}
		}
		return pos, vacioOK
	}
	return pos, false
}

func (c *contexto) validarContenido(n *nodo, p *particula) {
	m := &emparejador{c: c, hijos: n.Hijos, esperados: map[int][]string{}}
	top := &particula{clase: pSecuencia, min: 1, max: 1, hijos: []*particula{p}}
	np, ok := m.aceptar(top, 0)
	if ok && np == len(n.Hijos) {
		return
	}
	// posición donde se trabó: la más lejana que se probó
	pos := np
	for k := range m.esperados {
		if k > pos {
			pos = k
		}
	}
	if pos >= len(n.Hijos) {
		c.error(n, "Faltan elementos hijos."+seEsperaba(m.esperados[pos]))
		return
	}
	c.error(n.Hijos[pos], "Este elemento no se esperaba aquí."+seEsperaba(m.esperados[pos]))
}

func seEsperaba(nombres []string) string {
	switch len(nombres) {
	case 0:
		return ""
	case 1:
		return " Se esperaba ( " + nombres[0] + " )."
	}
	return " Se esperaba uno de ( " + strings.Join(nombres, ", ") + " )."
}
