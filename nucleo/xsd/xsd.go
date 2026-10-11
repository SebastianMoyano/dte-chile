// Package xsd valida XML contra los esquemas oficiales del SII (core/xsd, embebidos aquí) sin
// libxml2: un intérprete del subconjunto de XSD que esos esquemas usan (sequence, choice,
// simpleContent/extension, atributos fijos, restricciones con enumeration, length, pattern,
// totalDigits, fractionDigits, min/maxInclusive sobre string, decimal, la familia integer,
// base64Binary, date, dateTime, ID y anyURI). Cualquier constructo fuera del subconjunto hace
// fallar la carga del esquema, nunca pasa en silencio.
//
// El veredicto (válido / inválido) y el elemento del primer error deben coincidir con los de
// lxml: TestParidadConLxml lo exige sobre testdata/vectores.json.gz (tools/generar_xsd_vectores.py).
package xsd

import (
	"fmt"
	"sync"
)

// Igual que core/schema_validator.py: la raíz elige el esquema; una raíz desconocida se valida
// contra EnvioDTE (donde, por ejemplo, un <Signature> suelto es válido).
var xsdPorTipo = map[string]string{
	"EnvioBOLETA":   "EnvioBOLETA_v11.xsd",
	"ConsumoFolios": "ConsumoFolio_v10.xsd",
	"EnvioDTE":      "EnvioDTE_v10.xsd",
	"DTE":           "EnvioDTE_v10.xsd",
}

const esquemaPorDefecto = "EnvioDTE_v10.xsd"

var (
	cargaUna sync.Once
	esquemas map[string]*esquema
	errCarga error
)

func cargarTodos() {
	esquemas = map[string]*esquema{}
	for _, archivo := range []string{"EnvioDTE_v10.xsd", "EnvioBOLETA_v11.xsd", "ConsumoFolio_v10.xsd"} {
		e, err := cargarEsquema(archivo)
		if err != nil {
			errCarga = fmt.Errorf("xsd: %s: %v", archivo, err)
			return
		}
		esquemas[archivo] = e
	}
}

// Resultado es el espejo de ValidationResult (valido, errores, tipo_xml).
type Resultado struct {
	Valido  bool
	TipoXML string
	Errores []Error
}

// Mensajes son los errores como texto ("Línea N: Elemento 'X': …"), el formato de la API.
func (r Resultado) Mensajes() []string {
	out := make([]string, 0, len(r.Errores))
	for _, e := range r.Errores {
		out = append(out, e.String())
	}
	return out
}

// Validar valida un XML (ISO-8859-1 o UTF-8, con o sin declaración) contra el XSD que le
// corresponde por su raíz. Un documento mal formado es inválido con tipo "desconocido".
func Validar(raw []byte) Resultado {
	cargaUna.Do(cargarTodos)
	if errCarga != nil {
		return Resultado{TipoXML: "desconocido", Errores: []Error{{Mensaje: errCarga.Error()}}}
	}
	raiz, err := parsearArbol(raw)
	if err != nil {
		return Resultado{TipoXML: "desconocido", Errores: []Error{{Mensaje: "Error de sintaxis XML: " + err.Error()}}}
	}
	tipo := raiz.Nombre.Local
	archivo, ok := xsdPorTipo[tipo]
	if !ok {
		tipo, archivo = "desconocido", esquemaPorDefecto
	}
	esq := esquemas[archivo]
	decl, ok := esq.elementos[raiz.Nombre]
	if !ok {
		return Resultado{TipoXML: tipo, Errores: []Error{{Linea: raiz.Linea, Elemento: raiz.Nombre.Local,
			Mensaje: fmt.Sprintf("No hay una declaración global para la raíz '%s'.", raiz.Nombre)}}}
	}
	c := &contexto{}
	c.validarElemento(raiz, decl)
	return Resultado{Valido: len(c.errores) == 0, TipoXML: tipo, Errores: c.errores}
}

// ValidarError es Validar como error (nil si es válido): para el hook Validar de emision.
func ValidarError(raw []byte) error {
	r := Validar(raw)
	if r.Valido {
		return nil
	}
	msgs := r.Mensajes()
	if len(msgs) > 5 {
		msgs = append(msgs[:5], fmt.Sprintf("… y %d más", len(r.Errores)-5))
	}
	return fmt.Errorf("el XML no cumple el esquema XSD del SII: %s", joinPuntoComa(msgs))
}

func joinPuntoComa(s []string) string {
	out := ""
	for i, x := range s {
		if i > 0 {
			out += "; "
		}
		out += x
	}
	return out
}
