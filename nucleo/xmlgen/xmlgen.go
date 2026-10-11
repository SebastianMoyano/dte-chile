// Package xmlgen arma el <DTE> sin firmar exactamente como core/dte.py::GeneradorDTE
// (facturas, notas, guías) y core/boleta.py::generar_documento_boleta (39/41), y lo
// serializa como lo haría lxml: sin espacios entre tags, texto escapado, atributos en el
// orden de inserción.
package xmlgen

import (
	"fmt"
	"math"
	"strconv"
	"strings"

	"dtechile/nucleo/totales"
)

const NSSii = "http://www.sii.cl/SiiDte"

// Nodo es un elemento mínimo. `Raw` se inserta tal cual (el TED ya serializado).
type Nodo struct {
	Tag   string
	Attrs [][2]string
	Text  string
	Hijos []*Nodo
	Raw   string
}

func (n *Nodo) Sub(tag string, texto ...string) *Nodo {
	h := &Nodo{Tag: tag}
	if len(texto) > 0 {
		h.Text = texto[0]
	}
	n.Hijos = append(n.Hijos, h)
	return h
}

func (n *Nodo) Attr(k, v string) *Nodo { n.Attrs = append(n.Attrs, [2]string{k, v}); return n }

// EscTexto es el escape de libxml2 para texto: & < > y \r.
func EscTexto(s string) string {
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
			b.WriteString("&#13;")
		default:
			b.WriteRune(r)
		}
	}
	return b.String()
}

// EscAttr es el escape de libxml2 para valores de atributo.
func EscAttr(s string) string {
	var b strings.Builder
	for _, r := range s {
		switch r {
		case '&':
			b.WriteString("&amp;")
		case '<':
			b.WriteString("&lt;")
		case '"':
			b.WriteString("&quot;")
		case '\n':
			b.WriteString("&#10;")
		case '\r':
			b.WriteString("&#13;")
		case '\t':
			b.WriteString("&#9;")
		default:
			b.WriteRune(r)
		}
	}
	return b.String()
}

// Serializar escribe el nodo como lxml (`etree.tostring(..., encoding="unicode")`).
func (n *Nodo) Serializar(b *strings.Builder) {
	if n.Raw != "" {
		b.WriteString(n.Raw)
		return
	}
	b.WriteByte('<')
	b.WriteString(n.Tag)
	for _, a := range n.Attrs {
		b.WriteByte(' ')
		b.WriteString(a[0])
		b.WriteString("=\"")
		b.WriteString(EscAttr(a[1]))
		b.WriteByte('"')
	}
	if n.Text == "" && len(n.Hijos) == 0 {
		b.WriteString("/>")
		return
	}
	b.WriteByte('>')
	b.WriteString(EscTexto(n.Text))
	for _, h := range n.Hijos {
		h.Serializar(b)
	}
	b.WriteString("</")
	b.WriteString(n.Tag)
	b.WriteByte('>')
}

func (n *Nodo) String() string { var b strings.Builder; n.Serializar(&b); return b.String() }

// ---- datos de entrada (espejo de DTEInput) ----

type Emisor struct {
	Rut, RazonSocial, Giro, Direccion, Comuna, Ciudad, Telefono, Email string
	CodigoActividad                                                    int
}

type Receptor struct {
	Rut, RazonSocial, Giro, Direccion, Comuna, Ciudad, Email string
}

type Item struct {
	NumeroLinea    int
	Nombre         string
	Descripcion    string
	Cantidad       float64
	UnidadMedida   string
	PrecioUnitario float64
	DescuentoPct   float64
	DescuentoMonto float64
	Exento         bool
	CodigoProducto string
}

type Referencia struct {
	NumeroLinea int
	TipoDocRef  int
	FolioRef    int
	FechaDocRef string
	CodigoRef   int
	RazonRef    string
}

type Documento struct {
	TipoDTE           int
	Folio             int
	FechaEmision      string
	Emisor            Emisor
	Receptor          Receptor
	Items             []Item
	Referencias       []Referencia
	FormaPago         int
	FechaVencimiento  string
	IndicadorServicio int // 0 = ninguno
	IndServicioBoleta int // parámetro ind_servicio de generar_documento_boleta (0 = ninguno)
	TED               string
	Marca             string
}

// ---- formatos numéricos de Python ----

// PyStrFloat es `str(float)` de Python: repr más corta, con ".0" si es entero.
func PyStrFloat(f float64) string {
	s := strconv.FormatFloat(f, 'g', -1, 64)
	if !strings.ContainsAny(s, ".eEn") {
		s += ".0"
	}
	return s
}

// FormatearNumero es core/dte.py::formatear_numero: entero si es redondo, si no hasta 6
// decimales sin ceros sobrantes.
func FormatearNumero(f float64) string {
	if f == math.Trunc(f) {
		return strconv.FormatInt(int64(f), 10)
	}
	s := strconv.FormatFloat(f, 'f', 6, 64)
	s = strings.TrimRight(s, "0")
	return strings.TrimRight(s, ".")
}

// numBoleta es core/boleta.py::_num: entero si es redondo, si no repr(float).
func numBoleta(f float64) string {
	if f == math.Trunc(f) {
		return strconv.FormatInt(int64(f), 10)
	}
	return strconv.FormatFloat(f, 'g', -1, 64)
}

func itemTotales(it Item) totales.Item {
	return totales.Item{Cantidad: it.Cantidad, PrecioUnitario: it.PrecioUnitario,
		DescuentoPct: it.DescuentoPct, DescuentoMonto: it.DescuentoMonto, Exento: it.Exento}
}

func montoDescuento(it Item) float64 {
	m := float64(totales.Redondear(it.Cantidad * it.PrecioUnitario))
	if it.DescuentoMonto > 0 {
		return it.DescuentoMonto
	}
	if it.DescuentoPct > 0 {
		return float64(totales.Redondear(m * it.DescuentoPct / 100))
	}
	return 0
}

// GenerarDTE arma el <DTE> de factura/nota/guía (GeneradorDTE.generar_documento_xml).
func GenerarDTE(d Documento) *Nodo {
	its := make([]totales.Item, len(d.Items))
	for i, it := range d.Items {
		its[i] = itemTotales(it)
	}
	t := totales.Calcular(its, d.TipoDTE)
	dte := (&Nodo{Tag: "DTE"}).Attr("xmlns", NSSii).Attr("version", "1.0")
	doc := dte.Sub("Documento").Attr("ID", fmt.Sprintf("T%dF%d", d.TipoDTE, d.Folio))
	enc := doc.Sub("Encabezado")

	id := enc.Sub("IdDoc")
	id.Sub("TipoDTE", strconv.Itoa(d.TipoDTE))
	id.Sub("Folio", strconv.Itoa(d.Folio))
	id.Sub("FchEmis", d.FechaEmision)
	if d.IndicadorServicio != 0 {
		id.Sub("IndServicio", strconv.Itoa(d.IndicadorServicio))
	}
	id.Sub("FmaPago", strconv.Itoa(d.FormaPago))
	if d.FechaVencimiento != "" {
		id.Sub("FchVenc", d.FechaVencimiento)
	}

	e := enc.Sub("Emisor")
	e.Sub("RUTEmisor", d.Emisor.Rut)
	e.Sub("RznSoc", d.Emisor.RazonSocial)
	e.Sub("GiroEmis", d.Emisor.Giro)
	if d.Emisor.Telefono != "" {
		e.Sub("Telefono", d.Emisor.Telefono)
	}
	if d.Emisor.Email != "" {
		e.Sub("CorreoEmisor", d.Emisor.Email)
	}
	e.Sub("Acteco", strconv.Itoa(d.Emisor.CodigoActividad))
	e.Sub("DirOrigen", d.Emisor.Direccion)
	e.Sub("CmnaOrigen", d.Emisor.Comuna)
	e.Sub("CiudadOrigen", d.Emisor.Ciudad)

	r := enc.Sub("Receptor")
	r.Sub("RUTRecep", d.Receptor.Rut)
	r.Sub("RznSocRecep", d.Receptor.RazonSocial)
	if d.Receptor.Giro != "" {
		r.Sub("GiroRecep", d.Receptor.Giro)
	}
	if d.Receptor.Email != "" {
		r.Sub("CorreoRecep", d.Receptor.Email)
	}
	if d.Receptor.Direccion != "" {
		r.Sub("DirRecep", d.Receptor.Direccion)
	}
	if d.Receptor.Comuna != "" {
		r.Sub("CmnaRecep", d.Receptor.Comuna)
	}
	if d.Receptor.Ciudad != "" {
		r.Sub("CiudadRecep", d.Receptor.Ciudad)
	}

	tot := enc.Sub("Totales")
	if t.MontoNeto > 0 {
		tot.Sub("MntNeto", strconv.FormatInt(t.MontoNeto, 10))
	}
	if t.MontoExento > 0 {
		tot.Sub("MntExe", strconv.FormatInt(t.MontoExento, 10))
	}
	if t.IvaMonto > 0 {
		tot.Sub("TasaIVA", strconv.Itoa(t.IvaTasa))
		tot.Sub("IVA", strconv.FormatInt(t.IvaMonto, 10))
	}
	tot.Sub("MntTotal", strconv.FormatInt(t.MontoTotal, 10))

	for _, it := range d.Items {
		det := doc.Sub("Detalle")
		det.Sub("NroLinDet", strconv.Itoa(it.NumeroLinea))
		if it.CodigoProducto != "" {
			c := det.Sub("CdgItem")
			c.Sub("TpoCodigo", "INT1")
			c.Sub("VlrCodigo", it.CodigoProducto)
		}
		if it.Exento {
			det.Sub("IndExe", "1")
		}
		det.Sub("NmbItem", it.Nombre)
		if it.Descripcion != "" {
			det.Sub("DscItem", it.Descripcion)
		}
		if it.Cantidad > 0 {
			det.Sub("QtyItem", FormatearNumero(it.Cantidad))
		}
		if it.UnidadMedida != "" {
			det.Sub("UnmdItem", it.UnidadMedida)
		}
		if it.PrecioUnitario > 0 {
			det.Sub("PrcItem", FormatearNumero(it.PrecioUnitario))
		}
		if it.DescuentoPct > 0 {
			det.Sub("DescuentoPct", PyStrFloat(it.DescuentoPct))
		}
		if md := montoDescuento(it); md > 0 {
			det.Sub("DescuentoMonto", strconv.FormatInt(int64(md), 10))
		}
		det.Sub("MontoItem", strconv.FormatInt(int64(totales.MontoNetoItem(itemTotales(it))), 10))
	}

	for _, ref := range d.Referencias {
		rf := doc.Sub("Referencia")
		rf.Sub("NroLinRef", strconv.Itoa(ref.NumeroLinea))
		rf.Sub("TpoDocRef", strconv.Itoa(ref.TipoDocRef))
		rf.Sub("FolioRef", strconv.Itoa(ref.FolioRef))
		rf.Sub("FchRef", ref.FechaDocRef)
		rf.Sub("CodRef", strconv.Itoa(ref.CodigoRef))
		if ref.RazonRef != "" {
			rf.Sub("RazonRef", ref.RazonRef)
		}
	}
	doc.Hijos = append(doc.Hijos, &Nodo{Raw: tedOPlaceholder(d, t.MontoTotal)})
	doc.Sub("TmstFirma", d.Marca)
	return dte
}

func recortar(s string, n int) string {
	r := []rune(s)
	if len(r) > n {
		r = r[:n]
	}
	return string(r)
}

// tedOPlaceholder: el TED real si viene; si no, el de marcador de posición de
// GeneradorDTE._generar_ted_placeholder (sin firma del CAF; RSR es la razón social del
// EMISOR, como en Python), ya serializado como lo deja lxml (<CAF/>, texto escapado).
func tedOPlaceholder(d Documento, montoTotal int64) string {
	if d.TED != "" {
		return d.TED
	}
	primer := ""
	if len(d.Items) > 0 {
		primer = d.Items[0].Nombre
	}
	return `<TED version="1.0"><DD><RE>` + EscTexto(d.Emisor.Rut) + `</RE><TD>` + strconv.Itoa(d.TipoDTE) + `</TD>` +
		`<F>` + strconv.Itoa(d.Folio) + `</F><FE>` + d.FechaEmision + `</FE>` +
		`<RR>` + EscTexto(d.Receptor.Rut) + `</RR><RSR>` + EscTexto(recortar(d.Emisor.RazonSocial, 40)) + `</RSR>` +
		`<MNT>` + strconv.FormatInt(montoTotal, 10) + `</MNT><IT1>` + EscTexto(recortar(primer, 40)) + `</IT1>` +
		`<CAF/><TSTED>` + d.Marca + `</TSTED></DD><FRMT algoritmo="SHA1withRSA">FIRMA_PLACEHOLDER</FRMT></TED>`
}

// GenerarBoleta arma el <DTE> de una boleta 39/41 (core/boleta.py::generar_documento_boleta).
func GenerarBoleta(d Documento) *Nodo {
	its := make([]totales.Item, len(d.Items))
	for i, it := range d.Items {
		its[i] = itemTotales(it)
	}
	t := totales.Calcular(its, d.TipoDTE)
	dte := (&Nodo{Tag: "DTE"}).Attr("xmlns", NSSii).Attr("version", "1.0")
	doc := dte.Sub("Documento").Attr("ID", fmt.Sprintf("T%dF%d", d.TipoDTE, d.Folio))
	enc := doc.Sub("Encabezado")

	id := enc.Sub("IdDoc")
	id.Sub("TipoDTE", strconv.Itoa(d.TipoDTE))
	id.Sub("Folio", strconv.Itoa(d.Folio))
	id.Sub("FchEmis", d.FechaEmision)
	ind := d.IndicadorServicio
	if ind == 0 {
		ind = d.IndServicioBoleta
	}
	if ind == 0 {
		ind = 3
	}
	id.Sub("IndServicio", strconv.Itoa(ind))

	e := enc.Sub("Emisor")
	e.Sub("RUTEmisor", d.Emisor.Rut)
	e.Sub("RznSocEmisor", d.Emisor.RazonSocial)
	e.Sub("GiroEmisor", d.Emisor.Giro)
	if d.Emisor.Direccion != "" {
		e.Sub("DirOrigen", d.Emisor.Direccion)
	}
	if d.Emisor.Comuna != "" {
		e.Sub("CmnaOrigen", d.Emisor.Comuna)
	}
	if d.Emisor.Ciudad != "" {
		e.Sub("CiudadOrigen", d.Emisor.Ciudad)
	}

	r := enc.Sub("Receptor")
	r.Sub("RUTRecep", d.Receptor.Rut)
	if d.Receptor.RazonSocial != "" && strings.ToUpper(d.Receptor.RazonSocial) != "CONSUMIDOR FINAL" {
		r.Sub("RznSocRecep", d.Receptor.RazonSocial)
	}
	if d.Receptor.Direccion != "" {
		r.Sub("DirRecep", d.Receptor.Direccion)
	}
	if d.Receptor.Comuna != "" {
		r.Sub("CmnaRecep", d.Receptor.Comuna)
	}
	if d.Receptor.Ciudad != "" {
		r.Sub("CiudadRecep", d.Receptor.Ciudad)
	}

	tot := enc.Sub("Totales")
	if t.MontoNeto != 0 {
		tot.Sub("MntNeto", strconv.FormatInt(t.MontoNeto, 10))
	}
	if t.MontoExento != 0 {
		tot.Sub("MntExe", strconv.FormatInt(t.MontoExento, 10))
	}
	if t.IvaMonto != 0 {
		tot.Sub("IVA", strconv.FormatInt(t.IvaMonto, 10))
	}
	tot.Sub("MntTotal", strconv.FormatInt(t.MontoTotal, 10))

	for i, it := range d.Items {
		det := doc.Sub("Detalle")
		nl := it.NumeroLinea
		if nl == 0 {
			nl = i + 1
		}
		det.Sub("NroLinDet", strconv.Itoa(nl))
		if it.Exento {
			det.Sub("IndExe", "1")
		}
		det.Sub("NmbItem", it.Nombre)
		det.Sub("QtyItem", numBoleta(it.Cantidad))
		if it.UnidadMedida != "" {
			det.Sub("UnmdItem", it.UnidadMedida)
		}
		det.Sub("PrcItem", numBoleta(it.PrecioUnitario))
		if it.DescuentoMonto != 0 {
			det.Sub("DescuentoMonto", strconv.FormatInt(int64(it.DescuentoMonto), 10))
		}
		// int(round(cant*precio - desc_monto)): round() de Python es half-even.
		monto := math.RoundToEven(it.Cantidad*it.PrecioUnitario - it.DescuentoMonto)
		det.Sub("MontoItem", strconv.FormatInt(int64(monto), 10))
	}
	doc.Hijos = append(doc.Hijos, &Nodo{Raw: tedOPlaceholder(d, t.MontoTotal)})
	doc.Sub("TmstFirma", d.Marca)
	return dte
}
