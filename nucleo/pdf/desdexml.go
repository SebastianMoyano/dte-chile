// Package pdf dibuja la representación gráfica de un DTE (carta) o de una boleta (80 mm) con
// el timbre PDF417, réplica de core/pdf_gen.py, y reconstruye el documento desde el XML firmado
// (core/dte_xml.py). El TED va al PDF417 tal cual está en el XML (verbatim).
package pdf

import (
	"encoding/xml"
	"errors"
	"regexp"
	"strconv"
	"strings"

	"dtechile/nucleo/xmlgen"
)

type xmlDoc struct {
	Encabezado struct {
		IdDoc struct {
			TipoDTE     int    `xml:"TipoDTE"`
			Folio       int    `xml:"Folio"`
			FchEmis     string `xml:"FchEmis"`
			FmaPago     string `xml:"FmaPago"`
			FchVenc     string `xml:"FchVenc"`
			IndServicio string `xml:"IndServicio"`
		} `xml:"IdDoc"`
		Emisor struct {
			RUTEmisor    string `xml:"RUTEmisor"`
			RznSoc       string `xml:"RznSoc"`
			RznSocEmisor string `xml:"RznSocEmisor"`
			GiroEmis     string `xml:"GiroEmis"`
			GiroEmisor   string `xml:"GiroEmisor"`
			Acteco       string `xml:"Acteco"`
			DirOrigen    string `xml:"DirOrigen"`
			CmnaOrigen   string `xml:"CmnaOrigen"`
			CiudadOrigen string `xml:"CiudadOrigen"`
			Telefono     string `xml:"Telefono"`
			CorreoEmisor string `xml:"CorreoEmisor"`
		} `xml:"Emisor"`
		Receptor struct {
			RUTRecep    string `xml:"RUTRecep"`
			RznSocRecep string `xml:"RznSocRecep"`
			GiroRecep   string `xml:"GiroRecep"`
			DirRecep    string `xml:"DirRecep"`
			CmnaRecep   string `xml:"CmnaRecep"`
			CiudadRecep string `xml:"CiudadRecep"`
			CorreoRecep string `xml:"CorreoRecep"`
		} `xml:"Receptor"`
	} `xml:"Encabezado"`
	Detalle []struct {
		NroLinDet string `xml:"NroLinDet"`
		CdgItem   *struct {
			VlrCodigo string `xml:"VlrCodigo"`
		} `xml:"CdgItem"`
		NmbItem        string `xml:"NmbItem"`
		DscItem        string `xml:"DscItem"`
		QtyItem        string `xml:"QtyItem"`
		UnmdItem       string `xml:"UnmdItem"`
		PrcItem        string `xml:"PrcItem"`
		DescuentoPct   string `xml:"DescuentoPct"`
		DescuentoMonto string `xml:"DescuentoMonto"`
		IndExe         string `xml:"IndExe"`
	} `xml:"Detalle"`
	Referencia []struct {
		NroLinRef string `xml:"NroLinRef"`
		TpoDocRef string `xml:"TpoDocRef"`
		FolioRef  string `xml:"FolioRef"`
		FchRef    string `xml:"FchRef"`
		CodRef    string `xml:"CodRef"`
		RazonRef  string `xml:"RazonRef"`
	} `xml:"Referencia"`
}

var (
	reDocumento = regexp.MustCompile(`(?s)<Documento\b.*?</Documento>`)
	reTED       = regexp.MustCompile(`(?s)<TED\b.*?</TED>`)
	reDecl      = regexp.MustCompile(`(?s)^\s*<\?xml[^>]*\?>`)
)

// latin1 decodifica ISO-8859-1 (los DTE del motor no llevan declaración y son latin-1).
func latin1(b []byte) string {
	r := make([]rune, len(b))
	for i, c := range b {
		r[i] = rune(c)
	}
	return string(r)
}

func numero(s string, def float64) float64 {
	s = strings.TrimSpace(s)
	if s == "" {
		return def
	}
	f, err := strconv.ParseFloat(s, 64)
	if err != nil {
		return def
	}
	return f
}

func entero(s string, def int) int {
	s = strings.TrimSpace(s)
	if s == "" {
		return def
	}
	n, err := strconv.Atoi(s)
	if err != nil {
		return def
	}
	return n
}

// DesdeXML es documento_desde_xml: `(Documento, TED)` desde el <DTE> firmado (o el sobre que
// lo contiene; toma el primero). El XML puede venir como bytes ISO-8859-1 sin declaración
// (lo que guarda la base) o como texto. El TED se devuelve verbatim, sin el xmlns heredado.
func DesdeXML(raw []byte) (xmlgen.Documento, string, error) {
	var texto string
	if reDecl.Match(raw) {
		texto = string(raw) // con declaración: respetarla (normalmente ISO-8859-1 → igual que latin1)
		if strings.Contains(strings.ToUpper(texto[:80]), "ISO-8859-1") {
			texto = latin1(raw)
		}
	} else {
		texto = latin1(raw)
	}
	m := reDocumento.FindString(texto)
	if m == "" {
		return xmlgen.Documento{}, "", errors.New("El XML no contiene un <Documento> del SII")
	}
	// encoding/xml ignora el namespace si el tag no lo declara; el xmlns por defecto se tolera.
	var x xmlDoc
	if err := xml.Unmarshal([]byte(m), &x); err != nil {
		return xmlgen.Documento{}, "", err
	}
	e, r, id := x.Encabezado.Emisor, x.Encabezado.Receptor, x.Encabezado.IdDoc
	tipo := id.TipoDTE
	esBoleta := tipo == 39 || tipo == 41
	razon := e.RznSoc
	if razon == "" {
		razon = e.RznSocEmisor
	}
	giro := e.GiroEmis
	if giro == "" {
		giro = e.GiroEmisor
	}
	rznRecep := r.RznSocRecep
	if rznRecep == "" {
		rznRecep = "CONSUMIDOR FINAL"
	}
	d := xmlgen.Documento{
		TipoDTE: tipo, Folio: id.Folio, FechaEmision: id.FchEmis, FormaPago: entero(id.FmaPago, 1), FechaVencimiento: id.FchVenc,
		IndicadorServicio: entero(id.IndServicio, 0),
		Emisor: xmlgen.Emisor{Rut: e.RUTEmisor, RazonSocial: razon, Giro: giro, CodigoActividad: entero(e.Acteco, 0),
			Direccion: e.DirOrigen, Comuna: e.CmnaOrigen, Ciudad: e.CiudadOrigen, Telefono: e.Telefono, Email: e.CorreoEmisor},
		Receptor: xmlgen.Receptor{Rut: r.RUTRecep, RazonSocial: rznRecep, Giro: r.GiroRecep, Direccion: r.DirRecep,
			Comuna: r.CmnaRecep, Ciudad: r.CiudadRecep, Email: r.CorreoRecep},
	}
	for i, det := range x.Detalle {
		cant := 1.0
		if esBoleta {
			cant = 0
		}
		it := xmlgen.Item{NumeroLinea: entero(det.NroLinDet, i+1), Nombre: det.NmbItem, Descripcion: det.DscItem,
			Cantidad: numero(det.QtyItem, cant), UnidadMedida: det.UnmdItem, PrecioUnitario: numero(det.PrcItem, 0),
			DescuentoPct: numero(det.DescuentoPct, 0), DescuentoMonto: numero(det.DescuentoMonto, 0), Exento: strings.TrimSpace(det.IndExe) == "1"}
		if det.CdgItem != nil {
			it.CodigoProducto = det.CdgItem.VlrCodigo
		}
		d.Items = append(d.Items, it)
	}
	for _, ref := range x.Referencia {
		t := strings.TrimSpace(ref.TpoDocRef)
		if t == "" || ref.FchRef == "" {
			continue
		}
		if _, err := strconv.Atoi(t); err != nil {
			continue
		}
		d.Referencias = append(d.Referencias, xmlgen.Referencia{NumeroLinea: entero(ref.NroLinRef, 1), TipoDocRef: entero(t, 0),
			FolioRef: entero(ref.FolioRef, 0), FechaDocRef: ref.FchRef, CodigoRef: entero(ref.CodRef, 1), RazonRef: ref.RazonRef})
	}
	ted := reTED.FindString(m)
	ted = strings.Replace(ted, ` xmlns="http://www.sii.cl/SiiDte"`, "", 1)
	return d, ted, nil
}
