package siiengine

import (
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"time"

	"dtechile/nucleo/almacen"
)

// Lector es lo que Importar necesita del cliente (una interfaz para probar sin red).
type Lector interface {
	DescargarPDF(dhdr string) ([]byte, error)
	ObtenerEnvioXML(dhdr string, tipo int, rutReceptor string) ([]byte, error)
}

// OpcionesImportar replica los parámetros de importar_emitidos.
type OpcionesImportar struct {
	ConPDF  bool
	ConXML  bool          // exige la clave del certificado en el cliente
	Carpeta string        // raíz de storage (default "storage"): pdfs/mipyme/<rut>/ y dtes/mipyme/<rut>/
	Pausa   time.Duration // entre descargas
}

// DocumentoImportado es cada entrada de `documentos` del resumen.
type DocumentoImportado struct {
	Tipo     int    `json:"tipo"`
	Folio    int    `json:"folio"`
	Fecha    string `json:"fecha"`
	Monto    int64  `json:"monto"`
	Estado   string `json:"estado"`
	DHDR     string `json:"dhdr"`
	Receptor string `json:"receptor"`
}

// Resumen es el dict que devuelve importar_emitidos (mismas claves).
type Resumen struct {
	Listados   int                  `json:"listados"`
	Importados int                  `json:"importados"`
	YaExistian int                  `json:"ya_existian"`
	SinTipo    int                  `json:"sin_tipo"`
	PDFOk      int                  `json:"pdf_ok"`
	PDFFalta   int                  `json:"pdf_falta"`
	XMLOk      int                  `json:"xml_ok"`
	XMLFalta   int                  `json:"xml_falta"`
	Documentos []DocumentoImportado `json:"documentos"`
	Avisos     []string             `json:"avisos,omitempty"`
}

var reFechaSegura = regexp.MustCompile(`[^0-9-]`)

// Importar es importar_emitidos: mete el historial del SII engine en `dtes` (estado
// `emitido_mipyme`, DHDR en `track_id`, ambiente producción; idempotente por rut/tipo/folio) y
// baja el PDF (y el XML si se pide) de lo que no lo tenga.
func Importar(cli Lector, al *almacen.Almacen, rutEmisor string, docs []DocumentoEmitido, op OpcionesImportar) (*Resumen, error) {
	rut := FormatearRut(rutEmisor, false)
	if op.Carpeta == "" {
		op.Carpeta = "storage"
	}
	rutDir := strings.ReplaceAll(rut, "-", "")
	destinoPDF := filepath.Join(op.Carpeta, "pdfs", "mipyme", rutDir)
	destinoXML := filepath.Join(op.Carpeta, "dtes", "mipyme", rutDir)
	res := &Resumen{Listados: len(docs), Documentos: []DocumentoImportado{}}
	for _, d := range docs {
		tipo := d.Tipo()
		if tipo == 0 {
			res.SinTipo++
			res.Avisos = append(res.Avisos, fmt.Sprintf("tipo no reconocido en el historial: %q (folio %d)", d.TipoTexto, d.Folio))
			continue
		}
		fila, err := al.DTEPorFolio(rut, tipo, d.Folio)
		if err != nil {
			return res, err
		}
		var id int64
		if fila != nil {
			res.YaExistian++
			id = fila.ID
		} else {
			receptor := d.ReceptorRut
			if ValidarRut(receptor) {
				receptor = FormatearRut(receptor, false)
			}
			exento := int64(0)
			if tipo == 34 || tipo == 61 {
				exento = d.Monto
			}
			id, err = al.CrearDTE(almacen.DTE{TipoDTE: tipo, Folio: d.Folio, RutEmisor: rut, RutReceptor: receptor,
				RazonSocialReceptor: d.ReceptorRazon, FechaEmision: d.Fecha, MontoExento: exento, MontoTotal: d.Monto,
				Ambiente: "produccion"})
			if err != nil {
				return res, err
			}
			track, _ := strconv.ParseInt(d.DHDR, 10, 64)
			if err := al.ActualizarEstado(id, "emitido_mipyme", track); err != nil {
				return res, err
			}
			res.Importados++
		}
		tienePDF := fila != nil && fila.PDFPath != "" && existe(fila.PDFPath)
		if op.ConPDF && !tienePDF {
			if pdf, err := cli.DescargarPDF(d.DHDR); err != nil {
				res.PDFFalta++
				res.Avisos = append(res.Avisos, fmt.Sprintf("sin PDF para DHDR %s: %v", d.DHDR, err))
			} else {
				os.MkdirAll(destinoPDF, 0o755)
				ruta := filepath.Join(destinoPDF, fmt.Sprintf("T%d_F%d_%s_D%s.pdf", tipo, d.Folio, reFechaSegura.ReplaceAllString(d.Fecha, "_"), d.DHDR))
				if err := os.WriteFile(ruta, pdf, 0o644); err != nil {
					return res, err
				}
				if err := al.GuardarPDF(id, ruta); err != nil {
					return res, err
				}
				res.PDFOk++
				time.Sleep(op.Pausa)
			}
		}
		if op.ConXML && !(fila != nil && fila.TieneXML) {
			if xml, err := cli.ObtenerEnvioXML(d.DHDR, tipo, d.ReceptorRut); err != nil {
				res.XMLFalta++
				res.Avisos = append(res.Avisos, fmt.Sprintf("sin XML para DHDR %s: %v", d.DHDR, err))
			} else {
				if err := al.GuardarXML(id, Latin1(xml)); err != nil {
					return res, err
				}
				os.MkdirAll(destinoXML, 0o755)
				if err := os.WriteFile(filepath.Join(destinoXML, fmt.Sprintf("T%d_F%d_D%s.xml", tipo, d.Folio, d.DHDR)), xml, 0o644); err != nil {
					return res, err
				}
				res.XMLOk++
				time.Sleep(op.Pausa)
			}
		}
		res.Documentos = append(res.Documentos, DocumentoImportado{Tipo: tipo, Folio: d.Folio, Fecha: d.Fecha, Monto: d.Monto,
			Estado: d.Estado, DHDR: d.DHDR, Receptor: d.ReceptorRazon})
	}
	return res, nil
}

func existe(ruta string) bool {
	_, err := os.Stat(ruta)
	return err == nil
}
