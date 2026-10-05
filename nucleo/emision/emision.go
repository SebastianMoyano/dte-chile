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
}

func esBoleta(t int) bool { return t == 39 || t == 41 }

// Emitir procesa un documento. Si d.Folio == 0 lo asigna atómicamente desde el CAF activo.
func Emitir(c Contexto, d xmlgen.Documento) (*Resultado, error) {
	rut, tipo := d.Emisor.Rut, d.TipoDTE
	// 1-2. folio (auto: atómico) y CAF activo
	auto := d.Folio <= 0
	if auto {
		f, err := c.Almacen.ConsumirSiguienteFolio(rut, tipo)
		if errors.Is(err, almacen.ErrSinFolios) {
			return nil, fmt.Errorf("no hay folios disponibles para el emisor %s y tipo DTE %d", rut, tipo)
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
		return nil, fmt.Errorf("no se encontró un CAF activo para el emisor %s y tipo DTE %d", rut, tipo)
	}
	caf, err := ted.ParsearCAF(cafDB.XML)
	if err != nil {
		return nil, err
	}
	if d.Folio < caf.FolioDesde || d.Folio > caf.FolioHasta {
		return nil, fmt.Errorf("el folio %d no está en el rango del CAF activo [%d-%d]", d.Folio, caf.FolioDesde, caf.FolioHasta)
	}
	if !auto {
		ok, err := c.Almacen.ConsumirFolio(rut, tipo, d.Folio)
		if err != nil || !ok {
			return nil, fmt.Errorf("no se pudo consumir el folio %d (¿ya fue usado?)", d.Folio)
		}
	}
	// 5-6. totales y TED
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
	d.TED, err = ted.Generar(caf, ted.Datos{Folio: d.Folio, RutEmisor: rut, RutReceptor: d.Receptor.Rut,
		TipoDTE: tipo, FechaEmision: d.FechaEmision, MontoTotal: tot.MontoTotal,
		RazonSocialReceptor: d.Receptor.RazonSocial, PrimerItem: primer, Marca: c.Marca})
	if err != nil {
		return nil, err
	}
	// 7-8. XML, firma standalone, sobre por string
	var arbol *xmlgen.Nodo
	if esBoleta(tipo) {
		arbol = xmlgen.GenerarBoleta(d)
	} else {
		arbol = xmlgen.GenerarDTE(d)
	}
	firmado, err := c.Cert.FirmarDTE(arbol.String(), arbol.Hijos[0].String(), tipo, d.Folio)
	if err != nil {
		return nil, err
	}
	rutEnvia, err := c.Cert.RutEmisor()
	if err != nil {
		return nil, err
	}
	raiz, pDoc, pEnv := "EnvioDTE", "DTE", "EnvioDTE"
	if esBoleta(tipo) {
		raiz, pDoc, pEnv = "EnvioBOLETA", "BOLETA", "EnvioBOLETA"
	}
	envio, err := c.Cert.Sobre([]string{firmado}, map[int]int{tipo: 1}, rut, rutEnvia,
		c.FechaResolucion, c.NumeroResolucion, raiz, c.Marca)
	if err != nil {
		return nil, err
	}
	// 8b. XSD (por el motor Python), antes de tocar disco o BD.
	if c.Validar != nil {
		if err := c.Validar(envio); err != nil {
			return nil, fmt.Errorf("el sobre no valida contra el XSD del SII: %w", err)
		}
	}
	// 9-11. disco (bytes exactos que se firmaron)
	dtes := filepath.Join(c.StorageBase, "dtes")
	if err := os.MkdirAll(dtes, 0o755); err != nil {
		return nil, err
	}
	_ = os.MkdirAll(filepath.Join(c.StorageBase, "pdfs"), 0o755)
	xmlDTE, err := ted.Latin1(firmado)
	if err != nil {
		return nil, err
	}
	pathDTE := filepath.Join(dtes, fmt.Sprintf("%s_%d_%d.xml", pDoc, tipo, d.Folio))
	pathEnv := filepath.Join(dtes, fmt.Sprintf("%s_%d_%d.xml", pEnv, tipo, d.Folio))
	if err := os.WriteFile(pathDTE, xmlDTE, 0o644); err != nil {
		return nil, err
	}
	if err := os.WriteFile(pathEnv, envio, 0o644); err != nil {
		return nil, err
	}
	// 12. BD (xml_firmado se guarda como texto decodificado de ISO-8859-1, igual que Python)
	id, err := c.Almacen.CrearDTE(almacen.DTE{TipoDTE: tipo, Folio: d.Folio, RutEmisor: rut,
		RutReceptor: d.Receptor.Rut, RazonSocialReceptor: d.Receptor.RazonSocial, FechaEmision: d.FechaEmision,
		MontoNeto: tot.MontoNeto, MontoExento: tot.MontoExento, IVA: tot.IvaMonto, MontoTotal: tot.MontoTotal,
		XMLFirmado: firmado, Ambiente: c.Ambiente})
	if err != nil {
		return nil, err
	}
	return &Resultado{DTEID: id, Folio: d.Folio, TipoDTE: tipo, MontoTotal: tot.MontoTotal,
		XMLDTEPath: pathDTE, XMLEnvioPath: pathEnv, Ambiente: c.Ambiente,
		Mensaje: fmt.Sprintf("DTE emitido exitosamente. Folio %d.", d.Folio)}, nil
}
