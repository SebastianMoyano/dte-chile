// Package emision es el orquestador: folio → TED → XML → firma → sobre → disco → BD, en el
// mismo orden y con las mismas rutas y filas que core/orchestrator.py::OrquestadorDTE y
// core/orchestrator_boleta.py. No genera PDF (eso sigue en Python) ni envía al SII.
package emision

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"

	"dtechile/nucleo/almacen"
	"dtechile/nucleo/firma"
	"dtechile/nucleo/ted"
	"dtechile/nucleo/totales"
	"dtechile/nucleo/xmlgen"
)

type Contexto struct {
	Almacen          *almacen.Almacen
	Cert             *firma.Certificado
	StorageBase      string // p. ej. "storage"
	Ambiente         string // certificacion | produccion | simulacion
	FechaResolucion  string
	NumeroResolucion int
	Marca            string // hora (reloj único); el llamador decide si fija o no
	// Validar, si no es nil, recibe el sobre completo ANTES de escribirlo y persistirlo (el
	// folio ya está consumido, igual que en Python). El núcleo no valida XSD por sí mismo
	// (fase 1.6 del plan): la app lo conecta a `POST /api/v1/dte/validar-xml` del motor.
	Validar func(xmlEnvio []byte) error
}

type Resultado struct {
	DTEID        int64  `json:"dte_id"`
	Folio        int    `json:"folio"`
	TipoDTE      int    `json:"tipo_dte"`
	MontoTotal   int64  `json:"monto_total"`
	XMLDTEPath   string `json:"xml_dte_path"`
	PDFPath      string `json:"pdf_path"`
	XMLEnvioPath string `json:"xml_envio_path"`
	Ambiente     string `json:"ambiente"`
	Mensaje      string `json:"mensaje"`
	Envio        []byte `json:"-"` // el sobre firmado (ISO-8859-1), para xml_envio_b64 de la API
}

func esBoleta(t int) bool { return t == 39 || t == 41 }

// Preparado es el documento listo: totales, TED, DTE firmado y sobre (lo que comparten la
// emisión real y la previsualización).
type Preparado struct {
	Documento   xmlgen.Documento
	MontoNeto   int64
	MontoExento int64
	IVA         int64
	MontoTotal  int64
	TED         string
	DTEFirmado  string // el DTE tal como se firmó (string; ISO-8859-1 al escribirlo)
	Envio       []byte // el sobre, ISO-8859-1
	Raiz        string // EnvioDTE | EnvioBOLETA
}

// preparar: pasos 5-8b (totales → TED → XML → firma standalone → sobre por string → XSD).
func preparar(c Contexto, d xmlgen.Documento, caf *ted.CAF) (*Preparado, error) {
	rut, tipo := d.Emisor.Rut, d.TipoDTE
	its := make([]totales.Item, len(d.Items))
	for i, it := range d.Items {
		its[i] = totales.Item{Cantidad: it.Cantidad, PrecioUnitario: it.PrecioUnitario,
			DescuentoPct: it.DescuentoPct, DescuentoMonto: it.DescuentoMonto, Exento: it.Exento}
	}
	tot := totales.Calcular(its, tipo)
	primer := "Sin Items"
	if len(d.Items) > 0 {
		primer = d.Items[0].Nombre
	}
	d.Marca = c.Marca
	var err error
	d.TED, err = ted.Generar(caf, ted.Datos{Folio: d.Folio, RutEmisor: rut, RutReceptor: d.Receptor.Rut,
		TipoDTE: tipo, FechaEmision: d.FechaEmision, MontoTotal: tot.MontoTotal,
		RazonSocialReceptor: d.Receptor.RazonSocial, PrimerItem: primer, Marca: c.Marca})
	if err != nil {
		return nil, errCAF("No se pudo generar el TED: " + err.Error())
	}
	var arbol *xmlgen.Nodo
	if esBoleta(tipo) {
		arbol = xmlgen.GenerarBoleta(d)
	} else {
		arbol = xmlgen.GenerarDTE(d)
	}
	firmado, err := c.Cert.FirmarDTE(arbol.String(), arbol.Hijos[0].String(), tipo, d.Folio)
	if err != nil {
		return nil, ErrCertificado("No se pudo firmar el DTE: " + err.Error())
	}
	rutEnvia, err := c.Cert.RutEmisor()
	if err != nil {
		return nil, ErrCertificado("El certificado no trae RUT: " + err.Error())
	}
	raiz := "EnvioDTE"
	if esBoleta(tipo) {
		raiz = "EnvioBOLETA"
	}
	envio, err := c.Cert.Sobre([]string{firmado}, map[int]int{tipo: 1}, rut, rutEnvia,
		c.FechaResolucion, c.NumeroResolucion, raiz, c.Marca)
	if err != nil {
		return nil, ErrValidacion("No se pudo armar el sobre: " + err.Error())
	}
	// 8b. XSD (nucleo/xsd), antes de tocar disco o BD.
	if c.Validar != nil {
		if err := c.Validar(envio); err != nil {
			return nil, ErrValidacion("el sobre no valida contra el XSD del SII: " + err.Error())
		}
	}
	return &Preparado{Documento: d, MontoNeto: tot.MontoNeto, MontoExento: tot.MontoExento, IVA: tot.IvaMonto,
		MontoTotal: tot.MontoTotal, TED: d.TED, DTEFirmado: firmado, Envio: envio, Raiz: raiz}, nil
}

// Previsualizar es core/preview.py: firma + TED + XSD con el CAF dado, SIN consumir folio ni
// tocar disco/BD. Si d.Folio <= 0 usa el primer folio del CAF (solo para mirar).
func Previsualizar(c Contexto, d xmlgen.Documento, caf *ted.CAF) (*Preparado, error) {
	if d.Folio <= 0 {
		d.Folio = caf.FolioDesde
	}
	if d.Folio < caf.FolioDesde || d.Folio > caf.FolioHasta {
		return nil, errFolio(fmt.Sprintf("El folio %d no está en el rango del CAF [%d-%d].", d.Folio, caf.FolioDesde, caf.FolioHasta),
			map[string]any{"folio": d.Folio, "desde": caf.FolioDesde, "hasta": caf.FolioHasta})
	}
	return preparar(c, d, caf)
}

// Emitir procesa un documento. Si d.Folio == 0 lo asigna atómicamente desde el CAF activo.
func Emitir(c Contexto, d xmlgen.Documento) (*Resultado, error) {
	rut, tipo := d.Emisor.Rut, d.TipoDTE
	// 1-2. folio (auto: atómico) y CAF activo
	auto := d.Folio <= 0
	if auto {
		f, err := c.Almacen.ConsumirSiguienteFolio(rut, tipo)
		if errors.Is(err, almacen.ErrSinFolios) {
			return nil, errSinFolios(rut, tipo)
		}
		if err != nil {
			return nil, err
		}
		d.Folio = f
	}
	cafDB, err := c.Almacen.CAFActivo(rut, tipo)
	if err != nil {
		return nil, err
	}
	if cafDB == nil {
		return nil, errFolio(fmt.Sprintf("No se encontró un CAF activo en la base de datos para el emisor %s y tipo DTE %d.", rut, tipo),
			map[string]any{"rut_emisor": rut, "tipo_dte": tipo})
	}
	caf, err := ted.ParsearCAF(cafDB.XML)
	if err != nil {
		return nil, errCAF("No se pudo procesar el CAF: " + err.Error())
	}
	if d.Folio < caf.FolioDesde || d.Folio > caf.FolioHasta {
		return nil, errFolio(fmt.Sprintf("El folio %d no está en el rango autorizado por el CAF activo [%d-%d].", d.Folio, caf.FolioDesde, caf.FolioHasta),
			map[string]any{"folio": d.Folio, "desde": caf.FolioDesde, "hasta": caf.FolioHasta})
	}
	if !auto {
		ok, err := c.Almacen.ConsumirFolio(rut, tipo, d.Folio)
		if err != nil || !ok {
			return nil, errConflicto(fmt.Sprintf("No se pudo consumir el folio %d en la base de datos (¿ya fue usado?).", d.Folio), map[string]any{"folio": d.Folio})
		}
	}
	// 5-8b. totales, TED, XML, firma, sobre, XSD
	p, err := preparar(c, d, caf)
	if err != nil {
		return nil, err
	}
	d = p.Documento
	pDoc, pEnv := "DTE", "EnvioDTE"
	if esBoleta(tipo) {
		pDoc, pEnv = "BOLETA", "EnvioBOLETA"
	}
	// 9-11. disco (bytes exactos que se firmaron)
	dtes := filepath.Join(c.StorageBase, "dtes")
	if err := os.MkdirAll(dtes, 0o755); err != nil {
		return nil, err
	}
	_ = os.MkdirAll(filepath.Join(c.StorageBase, "pdfs"), 0o755)
	xmlDTE, err := ted.Latin1(p.DTEFirmado)
	if err != nil {
		return nil, err
	}
	pathDTE := filepath.Join(dtes, fmt.Sprintf("%s_%d_%d.xml", pDoc, tipo, d.Folio))
	pathEnv := filepath.Join(dtes, fmt.Sprintf("%s_%d_%d.xml", pEnv, tipo, d.Folio))
	if err := os.WriteFile(pathDTE, xmlDTE, 0o644); err != nil {
		return nil, err
	}
	if err := os.WriteFile(pathEnv, p.Envio, 0o644); err != nil {
		return nil, err
	}
	// 12. BD (xml_firmado se guarda como texto decodificado de ISO-8859-1, igual que Python)
	id, err := c.Almacen.CrearDTE(almacen.DTE{TipoDTE: tipo, Folio: d.Folio, RutEmisor: rut,
		RutReceptor: d.Receptor.Rut, RazonSocialReceptor: d.Receptor.RazonSocial, FechaEmision: d.FechaEmision,
		MontoNeto: p.MontoNeto, MontoExento: p.MontoExento, IVA: p.IVA, MontoTotal: p.MontoTotal,
		XMLFirmado: p.DTEFirmado, Ambiente: c.Ambiente})
	if err != nil {
		return nil, err
	}
	return &Resultado{DTEID: id, Folio: d.Folio, TipoDTE: tipo, MontoTotal: p.MontoTotal,
		XMLDTEPath: pathDTE, XMLEnvioPath: pathEnv, Ambiente: c.Ambiente, Envio: p.Envio,
		Mensaje: fmt.Sprintf("DTE emitido exitosamente. Folio %d.", d.Folio)}, nil
}
