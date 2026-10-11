package servidor

import (
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"mime/multipart"
	"net/http"

	"dtechile/nucleo/emision"
	"dtechile/nucleo/firma"
	"dtechile/nucleo/pdf"
	"dtechile/nucleo/ted"
	"dtechile/nucleo/totales"
	"dtechile/nucleo/xmlgen"
)

// Rutas "sueltas" de api/routes/dte.py: generar un DTE firmado sin tocar la BD, y el PDF
// desde los datos (sin pasar por la emisión).
func (s *Servidor) rutasGenerar(mux *http.ServeMux) {
	mux.HandleFunc("POST /api/v1/dte/generar", s.protegido(s.generarDTE))
	mux.HandleFunc("POST /api/v1/dte/generar-simple", s.protegido(s.generarSimple))
	mux.HandleFunc("POST /api/v1/dte/pdf", s.protegido(s.pdfDesdeDatos))
	mux.HandleFunc("POST /api/v1/dte/pdf-simple", s.protegido(s.pdfSimple))
}

func montoTotalDe(d xmlgen.Documento) int64 {
	its := make([]totales.Item, len(d.Items))
	for i, it := range d.Items {
		its[i] = totales.Item{Cantidad: it.Cantidad, PrecioUnitario: it.PrecioUnitario, DescuentoPct: it.DescuentoPct, DescuentoMonto: it.DescuentoMonto, Exento: it.Exento}
	}
	return totales.Calcular(its, d.TipoDTE).MontoTotal
}

// documentoDesdeForm es _parse_dte_input sobre el campo `dte_json` del multipart.
func (s *Servidor) documentoDesdeForm(w http.ResponseWriter, r *http.Request) (xmlgen.Documento, bool) {
	vals, hay := r.MultipartForm.Value["dte_json"]
	if !hay || len(vals) == 0 {
		faltan(w, r, "dte_json")
		return xmlgen.Documento{}, false
	}
	d, err := emision.DocumentoDesdeJSON([]byte(vals[0]))
	if err != nil {
		responderError(w, r, 422, "validacion", "Datos del DTE inválidos: "+err.Error(), nil)
		return xmlgen.Documento{}, false
	}
	return d, true
}

// generarDTE es POST /dte/generar: multipart con dte_json, certificado_p12, password_certificado
// y caf_xml (opcional, para el TED). Firma por core/sobre.py (standalone, #T{tipo}F{folio}).
func (s *Servidor) generarDTE(w http.ResponseWriter, r *http.Request) {
	p12, _, ok := leerArchivoForm(w, r, "certificado_p12")
	if !ok {
		return
	}
	d, ok := s.documentoDesdeForm(w, r)
	if !ok {
		return
	}
	pw, hay := r.MultipartForm.Value["password_certificado"]
	if !hay || len(pw) == 0 {
		faltan(w, r, "password_certificado")
		return
	}
	cert, err := firma.CargarP12(p12, pw[0])
	if err != nil {
		responderError(w, r, 422, "certificado", "No se pudo cargar el certificado: "+err.Error(), nil)
		return
	}
	d.Marca = s.marca()
	if f, h, err := r.FormFile("caf_xml"); err == nil && h.Filename != "" {
		contenido, _ := leerTodo(f)
		caf, err := ted.ParsearCAF(string(contenido))
		if err != nil {
			responderError(w, r, 422, "caf", "No se pudo procesar el CAF: "+err.Error(), nil)
			return
		}
		if caf.TipoDTE != d.TipoDTE {
			responderError(w, r, 422, "caf", fmt.Sprintf("El CAF es para el tipo %d pero el DTE es tipo %d.", caf.TipoDTE, d.TipoDTE), nil)
			return
		}
		if d.Folio < caf.FolioDesde || d.Folio > caf.FolioHasta {
			responderError(w, r, 409, "folio", fmt.Sprintf("El folio %d no está en el rango del CAF [%d-%d].", d.Folio, caf.FolioDesde, caf.FolioHasta), nil)
			return
		}
		primer := "Sin Items"
		if len(d.Items) > 0 {
			primer = d.Items[0].Nombre
		}
		d.TED, err = ted.Generar(caf, ted.Datos{Folio: d.Folio, RutEmisor: d.Emisor.Rut, RutReceptor: d.Receptor.Rut, TipoDTE: d.TipoDTE,
			FechaEmision: d.FechaEmision, MontoTotal: montoTotalDe(d), RazonSocialReceptor: d.Receptor.RazonSocial, PrimerItem: primer, Marca: d.Marca})
		if err != nil {
			responderError(w, r, 422, "caf", "No se pudo generar el TED: "+err.Error(), nil)
			return
		}
	}
	arbol := xmlgen.GenerarDTE(d)
	firmado, err := cert.FirmarDTE(arbol.String(), arbol.Hijos[0].String(), d.TipoDTE, d.Folio)
	if err != nil {
		responderError(w, r, 422, "certificado", "No se pudo firmar el DTE: "+err.Error(), nil)
		return
	}
	responderJSON(w, 200, map[string]any{"folio": d.Folio, "tipo_dte": d.TipoDTE, "monto_total": montoTotalDe(d),
		"xml_b64": base64.StdEncoding.EncodeToString(bytesLatin1(firmado)),
		"mensaje": fmt.Sprintf("DTE Tipo %d Folio %d generado y firmado.", d.TipoDTE, d.Folio)})
}

// generarSimple es POST /dte/generar-simple: el <DTE> sin firma ni TED (desarrollo), con la
// declaración con comillas dobles (GeneradorDTE.to_xml_bytes).
func (s *Servidor) generarSimple(w http.ResponseWriter, r *http.Request) {
	d, ok := s.documentoDesdeJSON(w, r)
	if !ok {
		return
	}
	d.Marca = s.marca()
	xml := "<?xml version=\"1.0\" encoding=\"ISO-8859-1\"?>\n" + xmlgen.GenerarDTE(d).String()
	responderJSON(w, 200, map[string]any{"folio": d.Folio, "tipo_dte": d.TipoDTE, "monto_total": montoTotalDe(d),
		"xml_b64": base64.StdEncoding.EncodeToString(bytesLatin1(xml)),
		"mensaje": fmt.Sprintf("DTE Tipo %d Folio %d generado (sin firma real).", d.TipoDTE, d.Folio)})
}

// documentoDesdeJSON lee un DTEInput del cuerpo JSON (422 pydantic-like si no sirve).
func (s *Servidor) documentoDesdeJSON(w http.ResponseWriter, r *http.Request) (xmlgen.Documento, bool) {
	raw, ok := leerCuerpo(w, r)
	if !ok {
		return xmlgen.Documento{}, false
	}
	d, err := emision.DocumentoDesdeJSON(raw)
	if err != nil {
		responderError(w, r, 422, "validacion", "Los datos enviados no son válidos.", map[string]any{"errores": []map[string]any{{"loc": []any{"body"}, "msg": err.Error(), "type": "value_error"}}})
		return xmlgen.Documento{}, false
	}
	return d, true
}

func (s *Servidor) responderPDF(w http.ResponseWriter, r *http.Request, d xmlgen.Documento, tedXML string) {
	fecha, num := s.resolucionEmisor(d.Emisor.Rut, s.cfg.SIIAmbiente)
	b, err := pdf.Carta(d, tedXML, pdf.Opciones{Ambiente: s.cfg.SIIAmbiente, ResolucionFecha: fecha, ResolucionNum: num})
	if err != nil {
		responderError(w, r, 422, "validacion", "No se pudo dibujar el PDF: "+err.Error(), nil)
		return
	}
	w.Header().Set("Content-Type", "application/pdf")
	w.Header().Set("Content-Disposition", fmt.Sprintf(`attachment; filename="DTE-%d-%d.pdf"`, d.TipoDTE, d.Folio))
	w.WriteHeader(200)
	_, _ = w.Write(b)
}

// pdfDesdeDatos es POST /dte/pdf: multipart dte_json + ted_xml (opcional) → PDF carta.
func (s *Servidor) pdfDesdeDatos(w http.ResponseWriter, r *http.Request) {
	if err := r.ParseMultipartForm(maxUploadForm + 1024); err != nil {
		faltan(w, r, "dte_json")
		return
	}
	d, ok := s.documentoDesdeForm(w, r)
	if !ok {
		return
	}
	tedXML := ""
	if v := r.MultipartForm.Value["ted_xml"]; len(v) > 0 {
		tedXML = v[0]
	}
	s.responderPDF(w, r, d, tedXML)
}

// pdfSimple es POST /dte/pdf-simple: DTEInput en JSON → PDF carta sin timbre.
func (s *Servidor) pdfSimple(w http.ResponseWriter, r *http.Request) {
	d, ok := s.documentoDesdeJSON(w, r)
	if !ok {
		return
	}
	s.responderPDF(w, r, d, "")
}

func leerTodo(f multipart.File) ([]byte, error) {
	defer f.Close()
	return io.ReadAll(io.LimitReader(f, maxUploadForm+1))
}

// leerCuerpo lee el cuerpo JSON crudo (para parsearlo con DocumentoDesdeJSON).
func leerCuerpo(w http.ResponseWriter, r *http.Request) ([]byte, bool) {
	raw, err := io.ReadAll(http.MaxBytesReader(w, r.Body, 1<<20))
	if err != nil || !json.Valid(raw) {
		responderError(w, r, 422, "validacion", "Los datos enviados no son válidos.", map[string]any{"errores": []map[string]any{{"loc": []any{"body"}, "msg": "JSON inválido", "type": "json_invalid"}}})
		return nil, false
	}
	return raw, true
}
