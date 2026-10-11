package pdf

import (
	"bytes"
	"fmt"
	"image/png"
	"strings"
	"time"

	"dtechile/nucleo/pdf417"
	"github.com/go-pdf/fpdf"

	"dtechile/nucleo/totales"
	"dtechile/nucleo/xmlgen"
)

// NombresDTE es NOMBRES_DTE.
var NombresDTE = map[int]string{
	33: "FACTURA ELECTRÓNICA", 34: "FACTURA NO AFECTA O EXENTA ELECTRÓNICA", 39: "BOLETA ELECTRÓNICA",
	41: "BOLETA NO AFECTA O EXENTA ELECTRÓNICA", 52: "GUÍA DE DESPACHO ELECTRÓNICA", 56: "NOTA DE DÉBITO ELECTRÓNICA",
	61: "NOTA DE CRÉDITO ELECTRÓNICA",
}

// Opciones del pie: ambiente y resolución del emisor (la leyenda bajo el timbre es por emisor, L4).
type Opciones struct {
	Ambiente        string // certificacion | produccion | simulacion
	ResolucionFecha string // YYYY-MM-DD
	ResolucionNum   int
	Hoy             string // YYYY-MM-DD (vacío = hoy)
}

// FormatearRut es pdf_gen.formatear_rut: puntos de miles y guión.
func FormatearRut(rut string) string {
	n, dv, ok := strings.Cut(rut, "-")
	if !ok {
		return rut
	}
	n = strings.ReplaceAll(n, ".", "")
	var b strings.Builder
	for i := 0; i < len(n); i++ {
		if i > 0 && (len(n)-i)%3 == 0 {
			b.WriteByte('.')
		}
		b.WriteByte(n[i])
	}
	return b.String() + "-" + dv
}

// FormatearMonto es formatear_monto: "$ 1.234.567".
func FormatearMonto(m int64) string {
	neg := m < 0
	if neg {
		m = -m
	}
	s := fmt.Sprintf("%d", m)
	var b strings.Builder
	for i := 0; i < len(s); i++ {
		if i > 0 && (len(s)-i)%3 == 0 {
			b.WriteByte('.')
		}
		b.WriteByte(s[i])
	}
	if neg {
		return "$ -" + b.String()
	}
	return "$ " + b.String()
}

// TimbrePNG es _generar_barcode_pdf417: PDF417 con nivel de corrección 5 (guía del SII) y 12
// columnas, módulos de 2 px de ancho y 6 px de alto y margen de 20 px, exactamente como
// pdf417gen.render_image(scale=2, ratio=3) en Python. El dato son los bytes UTF-8 del TED.
func TimbrePNG(ted string) ([]byte, error) {
	filas, err := pdf417.Codificar([]byte(ted), 12, 5)
	if err != nil {
		return nil, err
	}
	var buf bytes.Buffer
	if err := png.Encode(&buf, pdf417.Imagen(filas, 2, 3, 20)); err != nil {
		return nil, err
	}
	return buf.Bytes(), nil
}

func timbrePNG(ted string) ([]byte, error) { return TimbrePNG(ted) }

// dibujarTimbre pinta el PDF417 como vectores (un rectángulo por módulo negro) en el recuadro
// (x, y, w, h) en mm: sin interpolación al rasterizar ni al imprimir, el código se lee a
// cualquier resolución. Mismas filas de códigos que el PNG (pdf417.Codificar, 12 col, nivel 5).
func dibujarTimbre(p *fpdf.Fpdf, ted string, x, y, w, h float64) bool {
	filas, err := pdf417.Codificar([]byte(ted), 12, 5)
	if err != nil {
		return false
	}
	anchoMod := len(filas[0])*17 + 1
	mw := w / float64(anchoMod)
	mh := h / float64(len(filas))
	p.SetFillColor(0, 0, 0)
	for fy, fila := range filas {
		col := 0
		for _, v := range fila {
			nbits := 0
			for t := v; t > 0; t >>= 1 {
				nbits++
			}
			for b := nbits - 1; b >= 0; b-- {
				if v&(1<<b) != 0 {
					// barras contiguas en un solo rectángulo (menos objetos y sin ranuras)
					ini := col
					for b > 0 && v&(1<<(b-1)) != 0 {
						b--
						col++
					}
					p.Rect(x+float64(ini)*mw, y+float64(fy)*mh, float64(col-ini+1)*mw, mh, "F")
				}
				col++
			}
		}
	}
	return true
}

func itemsTotales(d xmlgen.Documento) []totales.Item {
	out := make([]totales.Item, len(d.Items))
	for i, it := range d.Items {
		out[i] = totales.Item{Cantidad: it.Cantidad, PrecioUnitario: it.PrecioUnitario, DescuentoPct: it.DescuentoPct, DescuentoMonto: it.DescuentoMonto, Exento: it.Exento}
	}
	return out
}

func hoy(o Opciones) string {
	if o.Hoy != "" {
		return o.Hoy
	}
	return time.Now().Format("2006-01-02")
}

func cantidadG(f float64) string { // f"{x:g}"
	s := fmt.Sprintf("%g", f)
	if strings.Contains(s, "e") {
		s = fmt.Sprintf("%.6g", f)
	}
	return s
}

// Carta es generar_pdf_dte: la representación gráfica en hoja carta.
func Carta(d xmlgen.Documento, ted string, o Opciones) ([]byte, error) {
	tot := totales.Calcular(itemsTotales(d), d.TipoDTE)
	p := fpdf.New("P", "mm", "Letter", "")
	tr := p.UnicodeTranslatorFromDescriptor("")
	p.SetTitle(fmt.Sprintf("DTE-%d-%d", d.TipoDTE, d.Folio), true)
	p.SetMargins(15, 15, 15)
	p.SetAutoPageBreak(true, 15)
	p.AddPage()
	azul := [3]int{0x1a, 0x3a, 0x5c}
	linea := [3]int{0x25, 0x63, 0xeb}
	gris := [3]int{0xf1, 0xf5, 0xf9}
	ancho := 215.9 - 30
	nombre := NombresDTE[d.TipoDTE]
	if nombre == "" {
		nombre = fmt.Sprintf("DTE TIPO %d", d.TipoDTE)
	}

	// ---- Cabecera: emisor | recuadro tipo/RUT/folio | S.I.I. ----
	y0 := p.GetY()
	p.SetTextColor(azul[0], azul[1], azul[2])
	// Recuadro central: el título se parte en líneas si no cabe en 80 mm (como ReportLab).
	p.SetFont("Helvetica", "B", 13)
	lineasTitulo := p.SplitText(nombre, 76) // SplitText espera UTF-8; tr() va por línea
	altoBox := 4 + 7*float64(len(lineasTitulo)) + 6 + 7 + 4
	p.SetFillColor(0xeb, 0xf2, 0xff)
	p.SetDrawColor(linea[0], linea[1], linea[2])
	p.SetLineWidth(0.5)
	p.Rect(85, y0, 80, altoBox, "FD")
	p.SetXY(85, y0+2)
	for _, l := range lineasTitulo {
		p.SetX(85)
		p.CellFormat(80, 7, tr(l), "", 1, "C", false, 0, "")
	}
	p.SetFont("Helvetica", "B", 10)
	p.SetX(85)
	p.CellFormat(80, 6, tr("RUT: "+FormatearRut(d.Emisor.Rut)), "", 1, "C", false, 0, "")
	p.SetFont("Helvetica", "B", 13)
	p.SetX(85)
	p.CellFormat(80, 7, tr(fmt.Sprintf("N° %d", d.Folio)), "", 1, "C", false, 0, "")
	p.SetFont("Helvetica", "B", 10)
	p.SetXY(15, y0+altoBox/2-3)
	p.MultiCell(68, 5, tr(strings.ToUpper(d.Emisor.RazonSocial)), "", "C", false)
	p.SetXY(165, y0+altoBox/2-3)
	p.CellFormat(35, 6, "S.I.I.", "", 0, "R", false, 0, "")
	p.SetXY(15, y0+altoBox+3)

	// ---- Datos del emisor ----
	p.SetTextColor(0, 0, 0)
	p.SetFont("Helvetica", "", 8)
	y := p.GetY()
	p.SetXY(15, y)
	p.CellFormat(120, 4.5, tr("Giro: "+d.Emisor.Giro), "", 0, "L", false, 0, "")
	p.SetXY(135, y)
	p.CellFormat(65, 4.5, tr("Fecha de Emisión: "), "", 0, "L", false, 0, "")
	p.SetFont("Helvetica", "B", 8)
	p.SetXY(135+p.GetStringWidth(tr("Fecha de Emisión: ")), y)
	p.CellFormat(40, 4.5, d.FechaEmision, "", 1, "L", false, 0, "")
	p.SetFont("Helvetica", "", 8)
	p.SetX(15)
	p.CellFormat(120, 4.5, tr(fmt.Sprintf("Dirección: %s, %s, %s", d.Emisor.Direccion, d.Emisor.Comuna, d.Emisor.Ciudad)), "", 1, "L", false, 0, "")
	p.Ln(1.5)
	p.SetDrawColor(linea[0], linea[1], linea[2])
	p.SetLineWidth(0.35)
	p.Line(15, p.GetY(), 15+ancho, p.GetY())
	p.Ln(1.5)

	// ---- Receptor ----
	p.SetFont("Helvetica", "", 7)
	p.SetTextColor(128, 128, 128)
	p.CellFormat(ancho, 4, "DATOS DEL RECEPTOR", "", 1, "L", false, 0, "")
	p.SetTextColor(0, 0, 0)
	p.SetFillColor(gris[0], gris[1], gris[2])
	filas := [][2]string{{"Razón Social: ", d.Receptor.RazonSocial}}
	if d.Receptor.Giro != "" {
		filas = append(filas, [2]string{"Giro: ", d.Receptor.Giro})
	}
	if d.Receptor.Direccion != "" {
		filas = append(filas, [2]string{"Dirección: ", fmt.Sprintf("%s, %s, %s", d.Receptor.Direccion, d.Receptor.Comuna, d.Receptor.Ciudad)})
	}
	yr := p.GetY()
	p.Rect(15, yr, ancho, 5.5*float64(len(filas))+1, "F")
	p.SetY(yr + 0.5)
	for i, f := range filas {
		p.SetX(15)
		p.SetFont("Helvetica", "", 8)
		p.CellFormat(p.GetStringWidth(tr(f[0]))+1, 5.5, tr(f[0]), "", 0, "L", false, 0, "")
		if i == 0 {
			p.SetFont("Helvetica", "B", 8)
			p.CellFormat(110, 5.5, tr(f[1]), "", 0, "L", false, 0, "")
			p.SetFont("Helvetica", "", 8)
			p.SetX(135)
			p.CellFormat(10, 5.5, "RUT: ", "", 0, "L", false, 0, "")
			p.SetFont("Helvetica", "B", 8)
			p.CellFormat(50, 5.5, FormatearRut(d.Receptor.Rut), "", 1, "L", false, 0, "")
		} else {
			p.CellFormat(150, 5.5, tr(f[1]), "", 1, "L", false, 0, "")
		}
	}
	p.Ln(4)

	// ---- Ítems ----
	cols := []float64{7, 20, 63, 12, 10, 25, 15, 28}
	heads := []string{"N°", "Código", "Descripción", "Cant.", "U.M.", "Precio Unit.", "Desc.", "Total"}
	p.SetFillColor(azul[0], azul[1], azul[2])
	p.SetTextColor(255, 255, 255)
	p.SetDrawColor(0xcb, 0xd5, 0xe1)
	p.SetLineWidth(0.1)
	p.SetFont("Helvetica", "B", 8)
	for i, h := range heads {
		p.CellFormat(cols[i], 6, tr(h), "1", 0, "C", true, 0, "")
	}
	p.Ln(-1)
	p.SetTextColor(0, 0, 0)
	p.SetFont("Helvetica", "", 8)
	for i, it := range d.Items {
		fill := i%2 == 1
		p.SetFillColor(gris[0], gris[1], gris[2])
		descr := it.Nombre
		if it.Descripcion != "" {
			descr += "\n" + it.Descripcion
		}
		lineas := p.SplitText(descr, cols[2]-2)
		alto := 6.0
		if n := float64(len(lineas)); n > 1 {
			alto = 4.2*n + 1.8
		}
		desc := "-"
		if it.DescuentoMonto != 0 || it.DescuentoPct != 0 {
			desc = FormatearMonto(int64(totales.MontoNetoItem(totales.Item{Cantidad: it.Cantidad, PrecioUnitario: it.PrecioUnitario}) - totales.MontoNetoItem(totales.Item{Cantidad: it.Cantidad, PrecioUnitario: it.PrecioUnitario, DescuentoPct: it.DescuentoPct, DescuentoMonto: it.DescuentoMonto})))
		}
		vals := []string{fmt.Sprint(it.NumeroLinea), it.CodigoProducto, "", cantidadG(it.Cantidad), it.UnidadMedida,
			FormatearMonto(int64(it.PrecioUnitario)), desc, FormatearMonto(int64(totales.MontoNetoItem(totales.Item{Cantidad: it.Cantidad, PrecioUnitario: it.PrecioUnitario, DescuentoPct: it.DescuentoPct, DescuentoMonto: it.DescuentoMonto, Exento: it.Exento})))}
		aligns := []string{"C", "C", "L", "C", "C", "R", "R", "R"}
		x, yy := p.GetX(), p.GetY()
		for c := range cols {
			if c == 2 {
				p.SetXY(x, yy)
				p.Rect(x, yy, cols[2], alto, map[bool]string{true: "FD", false: "D"}[fill])
				p.SetXY(x+1, yy+0.9)
				p.MultiCell(cols[2]-2, 4.2, tr(descr), "", "L", false)
				x += cols[2]
				p.SetXY(x, yy)
				continue
			}
			p.SetXY(x, yy)
			p.CellFormat(cols[c], alto, tr(vals[c]), "1", 0, aligns[c], fill, 0, "")
			x += cols[c]
		}
		p.SetXY(15, yy+alto)
	}
	p.Ln(4)

	// ---- Totales (a la derecha) ----
	type fila struct {
		et string
		v  int64
	}
	var tf []fila
	if tot.MontoNeto > 0 {
		tf = append(tf, fila{"Neto:", tot.MontoNeto})
	}
	if tot.MontoExento > 0 {
		tf = append(tf, fila{"Exento:", tot.MontoExento})
	}
	if tot.IvaMonto > 0 {
		tf = append(tf, fila{fmt.Sprintf("IVA (%d%%):", tot.IvaTasa), tot.IvaMonto})
	}
	p.SetFont("Helvetica", "", 9)
	xt := 15 + ancho - 60
	for _, f := range tf {
		p.SetX(xt)
		p.CellFormat(30, 5, tr(f.et), "", 0, "R", false, 0, "")
		p.CellFormat(30, 5, FormatearMonto(f.v), "", 1, "R", false, 0, "")
	}
	p.SetX(xt)
	p.SetDrawColor(linea[0], linea[1], linea[2])
	p.SetLineWidth(0.35)
	p.Line(xt, p.GetY(), xt+60, p.GetY())
	p.SetFillColor(gris[0], gris[1], gris[2])
	p.SetFont("Helvetica", "B", 9)
	p.CellFormat(30, 6, "TOTAL:", "", 0, "R", true, 0, "")
	p.CellFormat(30, 6, FormatearMonto(tot.MontoTotal), "", 1, "R", true, 0, "")

	// ---- Referencias ----
	if len(d.Referencias) > 0 {
		p.Ln(4)
		p.SetFont("Helvetica", "", 8)
		p.SetTextColor(0x33, 0x33, 0x33)
		motivos := map[int]string{1: "Anula", 2: "Corrige texto de", 3: "Corrige montos de"}
		for _, r := range d.Referencias {
			nref := NombresDTE[r.TipoDocRef]
			if nref == "" {
				nref = fmt.Sprintf("documento tipo %d", r.TipoDocRef)
			}
			mot := motivos[r.CodigoRef]
			if mot == "" {
				mot = "Referencia a"
			}
			t := fmt.Sprintf("Referencia: %s %s N° %d del %s", mot, nref, r.FolioRef, r.FechaDocRef)
			if r.RazonRef != "" {
				t += " — " + r.RazonRef
			}
			p.SetX(15)
			p.MultiCell(ancho, 4.5, tr(t), "", "L", false)
		}
		p.SetTextColor(0, 0, 0)
	}

	// ---- Timbre ----
	p.Ln(6)
	p.SetDrawColor(211, 211, 211)
	p.SetLineWidth(0.2)
	p.Line(15, p.GetY(), 15+ancho, p.GetY())
	p.Ln(2)
	p.SetFont("Helvetica", "", 7)
	p.SetTextColor(128, 128, 128)
	p.CellFormat(ancho, 4, tr("Timbre Electrónico SII"), "", 1, "C", false, 0, "")
	if ted != "" {
		p.Ln(2)
		if dibujarTimbre(p, ted, 15+(ancho-90)/2, p.GetY(), 90, 25) {
			p.SetY(p.GetY() + 25)
		}
	}
	p.Ln(2)
	amb := o.Ambiente
	if amb == "simulacion" {
		p.CellFormat(ancho, 4, tr("Documento de práctica — no existe en www.sii.cl"), "", 1, "C", false, 0, "")
	} else {
		anio := o.ResolucionFecha
		if len(anio) >= 4 {
			anio = anio[:4]
		}
		p.CellFormat(ancho, 4, tr(fmt.Sprintf("Res. %d de %s — Verifique documento: www.sii.cl", o.ResolucionNum, anio)), "", 1, "C", false, 0, "")
	}
	p.Ln(3)
	etiqueta := map[string]string{"certificacion": "AMBIENTE DE CERTIFICACIÓN SII", "produccion": "PRODUCCIÓN SII",
		"simulacion": "SIMULACIÓN · EMPRESA DE PRÁCTICA · SIN VALIDEZ TRIBUTARIA"}[amb]
	if etiqueta == "" {
		etiqueta = strings.ToUpper(amb)
	}
	p.CellFormat(ancho, 4, tr(fmt.Sprintf("Documento generado el %s — %s", hoy(o), etiqueta)), "", 1, "C", false, 0, "")
	var buf bytes.Buffer
	if err := p.Output(&buf); err != nil {
		return nil, err
	}
	return buf.Bytes(), nil
}

// Boleta80mm es generar_boleta_80mm: recibo para rollo térmico de 80 mm.
func Boleta80mm(d xmlgen.Documento, ted string) ([]byte, error) {
	tot := totales.Calcular(itemsTotales(d), d.TipoDTE)
	n := len(d.Items)
	if n < 1 {
		n = 1
	}
	alto := 115 + 11*float64(n)
	p := fpdf.NewCustom(&fpdf.InitType{OrientationStr: "P", UnitStr: "mm", Size: fpdf.SizeType{Wd: 80, Ht: alto}})
	tr := p.UnicodeTranslatorFromDescriptor("")
	m := 3.5
	util := 80 - 2*m
	p.SetMargins(m, m, m)
	p.SetAutoPageBreak(false, m)
	p.AddPage()
	hr := func() {
		p.Ln(1)
		p.SetDrawColor(0x94, 0xa3, 0xb8)
		p.SetLineWidth(0.2)
		p.SetDashPattern([]float64{0.4, 0.4}, 0)
		p.Line(m, p.GetY(), m+util, p.GetY())
		p.SetDashPattern([]float64{}, 0)
		p.Ln(1.5)
	}
	ctr := func(txt string, size float64, estilo string, grisTxt bool) {
		p.SetFont("Helvetica", estilo, size)
		if grisTxt {
			p.SetTextColor(128, 128, 128)
		} else {
			p.SetTextColor(0, 0, 0)
		}
		p.SetX(m)
		p.MultiCell(util, size*0.42, tr(txt), "", "C", false)
	}
	ctr(strings.ToUpper(d.Emisor.RazonSocial), 9.5, "B", false)
	ctr("RUT: "+FormatearRut(d.Emisor.Rut), 8, "", false)
	if d.Emisor.Giro != "" {
		ctr(d.Emisor.Giro, 6.5, "", true)
	}
	if d.Emisor.Direccion != "" {
		dir := d.Emisor.Direccion
		if d.Emisor.Comuna != "" {
			dir += ", " + d.Emisor.Comuna
		}
		ctr(dir, 6.5, "", true)
	}
	p.Ln(2.5)
	nombre := NombresDTE[d.TipoDTE]
	if nombre == "" {
		nombre = fmt.Sprintf("DTE %d", d.TipoDTE)
	}
	ctr(nombre, 9.5, "B", false)
	ctr(fmt.Sprintf("N° %d", d.Folio), 8, "", false)
	ctr("Fecha: "+d.FechaEmision, 6.5, "", true)
	hr()
	p.SetTextColor(0, 0, 0)
	for _, it := range d.Items {
		monto := int64(totales.Redondear(it.Cantidad*it.PrecioUnitario - it.DescuentoMonto))
		nom := it.Nombre
		if rs := []rune(nom); len(rs) > 38 {
			nom = string(rs[:38])
		}
		y := p.GetY()
		p.SetFont("Helvetica", "", 7.5)
		p.SetXY(m, y)
		p.CellFormat(util*0.66, 3.8, tr(nom), "", 0, "L", false, 0, "")
		p.SetXY(m+util*0.66, y)
		p.CellFormat(util*0.34, 3.8, FormatearMonto(monto), "", 1, "R", false, 0, "")
		p.SetFont("Helvetica", "", 6)
		p.SetTextColor(0x64, 0x74, 0x8b)
		p.SetX(m)
		p.CellFormat(util, 3, tr(fmt.Sprintf("%d x %s", int(it.Cantidad), FormatearMonto(int64(it.PrecioUnitario)))), "", 1, "L", false, 0, "")
		p.SetTextColor(0, 0, 0)
		p.Ln(1)
	}
	hr()
	p.SetFont("Helvetica", "", 7.5)
	linea := func(et string, v int64, size float64, estilo string) {
		p.SetFont("Helvetica", estilo, size)
		p.SetX(m)
		p.CellFormat(util*0.6, size*0.5, tr(et), "", 0, "L", false, 0, "")
		p.CellFormat(util*0.4, size*0.5, FormatearMonto(v), "", 1, "R", false, 0, "")
	}
	if tot.MontoNeto != 0 {
		linea("Neto", tot.MontoNeto, 7.5, "")
	}
	if tot.IvaMonto != 0 {
		linea("IVA (19%)", tot.IvaMonto, 7.5, "")
	}
	if tot.MontoExento != 0 {
		linea("Exento", tot.MontoExento, 7.5, "")
	}
	p.Ln(1)
	linea("TOTAL", tot.MontoTotal, 10, "B")
	hr()
	if ted != "" {
		ctr("Timbre Electrónico SII", 6.5, "", true)
		p.Ln(1)
		if dibujarTimbre(p, ted, m, p.GetY(), util, util/3.0) {
			p.SetY(p.GetY() + util/3.0)
		}
	}
	p.Ln(1)
	ctr("Verifique este documento en www.sii.cl", 6.5, "", true)
	var buf bytes.Buffer
	if err := p.Output(&buf); err != nil {
		return nil, err
	}
	return buf.Bytes(), nil
}
