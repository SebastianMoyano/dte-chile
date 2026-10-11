package servidor

import (
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"os"
	"regexp"
	"strconv"
	"strings"
	"time"

	"dtechile/nucleo/emision"
	"dtechile/nucleo/firma"
	"dtechile/nucleo/pdf"
	"dtechile/nucleo/sii"
	"dtechile/nucleo/ted"
	"dtechile/nucleo/xsd"
)

// Rutas del motor propio (api/routes/dte.py y status.py): emitir, previsualizar, enviar y
// consultar estado; más el REST de boletas, que Python solo tenía en core (sin ruta).
func (s *Servidor) rutasEmision(mux *http.ServeMux) {
	mux.HandleFunc("POST /api/v1/dte/emitir", s.protegido(s.emitirDTE))
	mux.HandleFunc("POST /api/v1/dte/previsualizar", s.protegido(s.previsualizarDTE))
	mux.HandleFunc("POST /api/v1/dte/enviar", s.protegido(s.enviarDTE))
	mux.HandleFunc("POST /api/v1/estado/track", s.protegido(s.estadoTrack))
	mux.HandleFunc("POST /api/v1/estado/dte", s.protegido(s.estadoDTE))
	mux.HandleFunc("POST /api/v1/boletas/enviar", s.protegido(s.enviarBoletas))
	mux.HandleFunc("POST /api/v1/boletas/estado", s.protegido(s.estadoBoletas))
}

// marca es core/reloj.py::marca: RELOJ_FIJO o ahora.
func (s *Servidor) marca() string {
	if s.cfg.RelojFijo != "" {
		return s.cfg.RelojFijo
	}
	return time.Now().Format("2006-01-02T15:04:05")
}

func faltaCampo(campo string) map[string]any {
	return map[string]any{"errores": []map[string]any{{"loc": []any{"body", campo}, "msg": "Field required", "type": "missing"}}}
}

// responderDominio escribe un emision.Error con su código y status (o 500 si no es de dominio).
func responderDominio(w http.ResponseWriter, r *http.Request, err error) {
	var e *emision.Error
	if errors.As(err, &e) {
		responderError(w, r, e.Status, e.Codigo, e.Mensaje, e.Detalle)
		return
	}
	responderError(w, r, 500, "error_interno", "Ocurrió un error interno. Reporta el request_id al soporte.", nil)
}

// certificadoDesdeB64 es _cargar_cert: p12 en base64 + clave → 422 validacion/certificado.
func certificadoDesdeB64(p12b64, clave string) (*firma.Certificado, error) {
	raw, err := base64.StdEncoding.DecodeString(p12b64)
	if err != nil {
		return nil, emision.ErrValidacion("El certificado no es Base64 válido: " + err.Error())
	}
	cert, err := firma.CargarP12(raw, clave)
	if err != nil {
		return nil, emision.ErrCertificado("No se pudo cargar el certificado: " + err.Error())
	}
	return cert, nil
}

// certificadoEmision es OrquestadorDTE._obtener_certificado: el de la petición; si no, el del
// .env (CERTIFICADO_PATH/PASSWORD); si no, firma.pfx (DTE_CERT_PATH) con la clave del setup;
// si no, 422 certificado.
func (s *Servidor) certificadoEmision(p12b64, clave string) (*firma.Certificado, error) {
	if p12b64 != "" && clave != "" {
		return certificadoDesdeB64(p12b64, clave)
	}
	if s.cfg.CertificadoPath != "" && s.cfg.CertificadoPassword != "" {
		raw, err := os.ReadFile(s.cfg.CertificadoPath)
		if err == nil {
			if cert, err := firma.CargarP12(raw, s.cfg.CertificadoPassword); err == nil {
				return cert, nil
			}
		}
		return nil, emision.ErrCertificado(fmt.Sprintf("Error al cargar el certificado digital desde el archivo configurado [%s]", s.cfg.CertificadoPath))
	}
	ruta := os.Getenv("DTE_CERT_PATH")
	if ruta == "" {
		ruta = "firma.pfx"
	}
	if raw, err := os.ReadFile(ruta); err == nil {
		if cert, err := firma.CargarP12(raw, "12345678"); err == nil {
			return cert, nil
		}
	}
	return nil, emision.ErrCertificado("Certificado digital no provisto en la petición y tampoco configurado en .env (CERTIFICADO_PATH y CERTIFICADO_PASSWORD son requeridos).")
}

func (s *Servidor) contextoDe(cert *firma.Certificado, rut string) emision.Contexto {
	fecha, num := s.resolucionEmisor(rut, s.cfg.SIIAmbiente)
	return emision.Contexto{Almacen: s.alm, Cert: cert, StorageBase: s.cfg.StoragePath, Ambiente: s.cfg.SIIAmbiente,
		FechaResolucion: fecha, NumeroResolucion: num, Marca: s.marca(), Validar: xsd.ValidarError}
}

// emitirDTE es POST /api/v1/dte/emitir: folio → TED → firma → sobre → XSD → disco → BD → PDF.
func (s *Servidor) emitirDTE(w http.ResponseWriter, r *http.Request) {
	var cuerpo struct {
		DTE      json.RawMessage `json:"dte"`
		P12B64   string          `json:"certificado_p12_b64"`
		Password string          `json:"password_certificado"`
	}
	if !leerJSON(w, r, &cuerpo) {
		return
	}
	if len(cuerpo.DTE) == 0 {
		responderError(w, r, 422, "validacion", "Los datos enviados no son válidos.", faltaCampo("dte"))
		return
	}
	doc, err := emision.DocumentoDesdeJSON(cuerpo.DTE)
	if err != nil {
		responderError(w, r, 422, "validacion", "Los datos enviados no son válidos.", map[string]any{"errores": []map[string]any{{"loc": []any{"body", "dte"}, "msg": err.Error(), "type": "value_error"}}})
		return
	}
	cert, err := s.certificadoEmision(cuerpo.P12B64, cuerpo.Password)
	if err != nil {
		responderDominio(w, r, err)
		return
	}
	res, err := emision.Emitir(s.contextoDe(cert, doc.Emisor.Rut), doc)
	if err != nil {
		responderDominio(w, r, err)
		return
	}
	pdfPath := ""
	if d, err := s.dtePorID(res.DTEID); err == nil && d != nil {
		if ruta, err := s.regenerarPDF(d); err == nil {
			pdfPath = ruta
		} else {
			s.log("emitir: PDF del documento %d no generado: %v", res.DTEID, err)
		}
	}
	responderJSON(w, 200, map[string]any{
		"dte_id": res.DTEID, "folio": res.Folio, "tipo_dte": res.TipoDTE, "monto_total": res.MontoTotal,
		"xml_dte_path": res.XMLDTEPath, "pdf_path": pdfPath, "xml_envio_path": res.XMLEnvioPath,
		"xml_envio_b64": base64.StdEncoding.EncodeToString(res.Envio), "ambiente": res.Ambiente, "mensaje": res.Mensaje,
	})
}

// previsualizarDTE es POST /api/v1/dte/previsualizar: firmado + timbrado + XSD + PDF sin enviar
// ni consumir folios; certificado del keystore (cert_id) y CAF activo de la BD.
func (s *Servidor) previsualizarDTE(w http.ResponseWriter, r *http.Request) {
	var cuerpo struct {
		DTE    json.RawMessage `json:"dte"`
		CertID json.RawMessage `json:"cert_id"`
	}
	if !leerJSON(w, r, &cuerpo) {
		return
	}
	if len(cuerpo.DTE) == 0 || len(cuerpo.CertID) == 0 {
		campo := "dte"
		if len(cuerpo.DTE) != 0 {
			campo = "cert_id"
		}
		responderError(w, r, 422, "validacion", "Los datos enviados no son válidos.", faltaCampo(campo))
		return
	}
	// pydantic acepta el entero como número o como texto de dígitos
	certID, err := strconv.ParseInt(strings.Trim(string(cuerpo.CertID), `"`), 10, 64)
	if err != nil {
		responderError(w, r, 422, "validacion", "Los datos enviados no son válidos.", map[string]any{"errores": []map[string]any{{"loc": []any{"body", "cert_id"}, "msg": "Input should be a valid integer", "type": "int_parsing"}}})
		return
	}
	doc, err := emision.DocumentoDesdeJSON(cuerpo.DTE)
	if err != nil {
		responderError(w, r, 422, "validacion", "Los datos enviados no son válidos.", map[string]any{"errores": []map[string]any{{"loc": []any{"body", "dte"}, "msg": err.Error(), "type": "value_error"}}})
		return
	}
	cuenta, _ := s.cuentaID(w, r)
	p12, clave, err := s.descifrarCertificado(certID, cuenta)
	if err != nil {
		responderError(w, r, 404, "no_encontrado", fmt.Sprintf("Certificado %d no encontrado", certID), nil)
		return
	}
	cert, err := firma.CargarP12(p12, clave)
	if err != nil {
		responderError(w, r, 422, "certificado", "No se pudo cargar el certificado: "+err.Error(), nil)
		return
	}
	cafDB, err := s.alm.CAFActivo(doc.Emisor.Rut, doc.TipoDTE)
	if err != nil {
		responderError(w, r, 500, "error_interno", "Ocurrió un error interno. Reporta el request_id al soporte.", nil)
		return
	}
	if cafDB == nil {
		responderError(w, r, 409, "folio", fmt.Sprintf("No hay CAF activo para %s tipo %d. Carga un CAF primero.", doc.Emisor.Rut, doc.TipoDTE), nil)
		return
	}
	caf, err := ted.ParsearCAF(cafDB.XML)
	if err != nil {
		responderError(w, r, 422, "caf", "No se pudo procesar el CAF: "+err.Error(), nil)
		return
	}
	// La previsualización valida el XSD pero no corta: devuelve valido_xsd/errores_xsd.
	ctx := s.contextoDe(cert, doc.Emisor.Rut)
	ctx.Validar = nil
	p, err := emision.Previsualizar(ctx, doc, caf)
	if err != nil {
		responderDominio(w, r, err)
		return
	}
	val := xsd.Validar(p.Envio)
	docPDF, tedXML, err := pdf.DesdeXML(bytesLatin1(p.DTEFirmado))
	var pdfB64 string
	if err == nil {
		var b []byte
		if doc.TipoDTE == 39 || doc.TipoDTE == 41 {
			b, err = pdf.Boleta80mm(docPDF, tedXML)
		} else {
			b, err = pdf.Carta(docPDF, tedXML, pdf.Opciones{Ambiente: s.cfg.SIIAmbiente, ResolucionFecha: ctx.FechaResolucion, ResolucionNum: ctx.NumeroResolucion})
		}
		if err == nil {
			pdfB64 = base64.StdEncoding.EncodeToString(b)
		}
	}
	if err != nil {
		s.log("previsualizar: PDF no generado: %v", err)
	}
	responderJSON(w, 200, map[string]any{
		"es_preview": true, "aviso": "Previsualización — NO enviada al SII, no consume folios.",
		"folio": p.Documento.Folio, "tipo_dte": doc.TipoDTE, "monto_neto": p.MontoNeto, "monto_exento": p.MontoExento,
		"iva": p.IVA, "monto_total": p.MontoTotal, "valido_xsd": val.Valido, "errores_xsd": val.Mensajes(),
		"xml_b64": base64.StdEncoding.EncodeToString(bytesLatin1(p.DTEFirmado)), "pdf_b64": pdfB64,
	})
}

var reTipoFolio = regexp.MustCompile(`<TipoDTE>(\d+)</TipoDTE>\s*<Folio>(\d+)</Folio>`)
var reRutEmisorXML = regexp.MustCompile(`<RutEmisor>([^<]+)</RutEmisor>`)

// marcarEnviadosPorXML es core/models.py::marcar_enviados_por_xml: los (TipoDTE, Folio) del
// sobre recién enviado quedan `enviado` con su TrackID (no pisa estados posteriores ni un
// track ya grabado). Best-effort: el envío YA fue exitoso.
func (s *Servidor) marcarEnviadosPorXML(xmlEnvio []byte, trackID, ambiente string) int64 {
	texto := string(xmlEnvio)
	m := reRutEmisorXML.FindStringSubmatch(texto)
	if m == nil {
		return 0
	}
	rut := strings.TrimSpace(m[1])
	ahora := time.Now().Format("2006-01-02T15:04:05.000000")
	var filas int64
	vistos := map[string]bool{}
	for _, par := range reTipoFolio.FindAllStringSubmatch(texto, -1) {
		k := par[1] + "/" + par[2]
		if vistos[k] {
			continue
		}
		vistos[k] = true
		q := `UPDATE dtes SET estado = CASE WHEN estado='generado' THEN 'enviado' ELSE estado END, track_id = COALESCE(track_id, ?), actualizado_en=? WHERE rut_emisor=? AND tipo_dte=? AND folio=?`
		args := []any{trackID, ahora, rut, par[1], par[2]}
		if ambiente != "" {
			q += " AND ambiente=?"
			args = append(args, ambiente)
		}
		if res, err := s.db.Exec(q, args...); err == nil {
			n, _ := res.RowsAffected()
			filas += n
		}
	}
	return filas
}

func ambienteValido(a string) bool { return a == "certificacion" || a == "produccion" }

// enviarDTE es POST /api/v1/dte/enviar: EnvioDTE firmado → XSD → DTEUpload → TrackID.
func (s *Servidor) enviarDTE(w http.ResponseWriter, r *http.Request) {
	var cuerpo struct {
		XMLB64     *string `json:"xml_envio_b64"`
		P12B64     *string `json:"certificado_p12_b64"`
		Password   *string `json:"password_certificado"`
		RutEmpresa *string `json:"rut_empresa"`
		DVEmpresa  *string `json:"dv_empresa"`
		TipoDTE    int     `json:"tipo_dte"`
		Ambiente   string  `json:"ambiente"`
	}
	if !leerJSON(w, r, &cuerpo) {
		return
	}
	for campo, v := range map[string]*string{"xml_envio_b64": cuerpo.XMLB64, "certificado_p12_b64": cuerpo.P12B64, "password_certificado": cuerpo.Password, "rut_empresa": cuerpo.RutEmpresa, "dv_empresa": cuerpo.DVEmpresa} {
		if v == nil {
			responderError(w, r, 422, "validacion", "Los datos enviados no son válidos.", faltaCampo(campo))
			return
		}
	}
	if cuerpo.Ambiente == "" {
		cuerpo.Ambiente = "certificacion"
	}
	if !ambienteValido(cuerpo.Ambiente) {
		responderError(w, r, 422, "validacion", "Los datos enviados no son válidos.", map[string]any{"errores": []map[string]any{{"loc": []any{"body", "ambiente"}, "msg": "Input should be 'certificacion' or 'produccion'", "type": "enum"}}})
		return
	}
	cert, err := certificadoDesdeB64(*cuerpo.P12B64, *cuerpo.Password)
	if err != nil {
		responderDominio(w, r, err)
		return
	}
	xmlEnvio, err := base64.StdEncoding.DecodeString(*cuerpo.XMLB64)
	if err != nil {
		responderError(w, r, 422, "validacion", "El XML de envío no es Base64 válido: "+err.Error(), nil)
		return
	}
	if err := xsd.ValidarError(xmlEnvio); err != nil {
		responderError(w, r, 422, "validacion", "El XML no cumple el esquema XSD del SII: "+err.Error(), nil)
		return
	}
	if cuerpo.TipoDTE == 39 || cuerpo.TipoDTE == 41 {
		// Python levanta ValidacionError DENTRO del try del envío y su `except Exception` lo
		// convierte en SIIError (502). Se copia tal cual para que el contrato sea idéntico.
		responderError(w, r, 502, "sii_comunicacion", fmt.Sprintf("Error de comunicación con el SII: El tipo %d es una boleta y no se envía por este cliente. Usar core.sii_boleta.ClienteBoletaSII (REST, token propio).", cuerpo.TipoDTE), nil)
		return
	}
	cli, err := sii.Nuevo(cuerpo.Ambiente, cert)
	if err != nil {
		responderError(w, r, 422, "validacion", err.Error(), nil)
		return
	}
	track, _, err := cli.EnviarDTE(xmlEnvio, *cuerpo.RutEmpresa, *cuerpo.DVEmpresa)
	if err != nil {
		var resp *sii.ErrRespuesta
		if errors.As(err, &resp) { // ValueError en Python → sii_rechazo
			responderError(w, r, 422, "sii_rechazo", "El SII rechazó el documento: "+err.Error(), nil)
			return
		}
		responderError(w, r, 502, "sii_comunicacion", "Error de comunicación con el SII: "+err.Error(), nil)
		return
	}
	s.marcarEnviadosPorXML(xmlEnvio, fmt.Sprint(track), cuerpo.Ambiente)
	responderJSON(w, 200, map[string]any{"track_id": track, "mensaje": fmt.Sprintf("Envío exitoso. TrackID: %d", track), "ambiente": cuerpo.Ambiente})
}

// estadoTrack es POST /api/v1/estado/track (api/routes/status.py).
func (s *Servidor) estadoTrack(w http.ResponseWriter, r *http.Request) {
	var cuerpo struct {
		TrackID    *int64  `json:"track_id"`
		RutEmpresa *string `json:"rut_empresa"`
		DVEmpresa  *string `json:"dv_empresa"`
		P12B64     *string `json:"certificado_p12_b64"`
		Password   *string `json:"password_certificado"`
		Ambiente   string  `json:"ambiente"`
	}
	if !leerJSON(w, r, &cuerpo) {
		return
	}
	if cuerpo.TrackID == nil {
		responderError(w, r, 422, "validacion", "Los datos enviados no son válidos.", faltaCampo("track_id"))
		return
	}
	for campo, v := range map[string]*string{"rut_empresa": cuerpo.RutEmpresa, "dv_empresa": cuerpo.DVEmpresa, "certificado_p12_b64": cuerpo.P12B64, "password_certificado": cuerpo.Password} {
		if v == nil {
			responderError(w, r, 422, "validacion", "Los datos enviados no son válidos.", faltaCampo(campo))
			return
		}
	}
	if cuerpo.Ambiente == "" {
		cuerpo.Ambiente = "certificacion"
	}
	cert, err := certificadoDesdeB64(*cuerpo.P12B64, *cuerpo.Password)
	if err != nil {
		responderError(w, r, 422, "certificado", "No se pudo cargar el certificado: "+err.Error(), nil)
		return
	}
	cli, err := sii.Nuevo(cuerpo.Ambiente, cert)
	if err != nil {
		responderError(w, r, 422, "validacion", err.Error(), nil)
		return
	}
	e, err := cli.EstadoTrack(*cuerpo.TrackID, *cuerpo.RutEmpresa, *cuerpo.DVEmpresa)
	if err != nil {
		responderError(w, r, 502, "sii_comunicacion", "Error al consultar el SII: "+err.Error(), nil)
		return
	}
	responderJSON(w, 200, map[string]any{"track_id": *cuerpo.TrackID, "estado": e.Estado, "glosa": e.Glosa, "ambiente": cuerpo.Ambiente})
}

// estadoDTE es POST /api/v1/estado/dte.
func (s *Servidor) estadoDTE(w http.ResponseWriter, r *http.Request) {
	var cuerpo struct {
		RutEmisor    *string `json:"rut_emisor"`
		DVEmisor     *string `json:"dv_emisor"`
		TipoDTE      *int    `json:"tipo_dte"`
		Folio        *int    `json:"folio"`
		FechaEmision *string `json:"fecha_emision"`
		MontoTotal   *int64  `json:"monto_total"`
		RutReceptor  *string `json:"rut_receptor"`
		DVReceptor   *string `json:"dv_receptor"`
		P12B64       *string `json:"certificado_p12_b64"`
		Password     *string `json:"password_certificado"`
		Ambiente     string  `json:"ambiente"`
	}
	if !leerJSON(w, r, &cuerpo) {
		return
	}
	faltan := map[string]bool{"rut_emisor": cuerpo.RutEmisor == nil, "dv_emisor": cuerpo.DVEmisor == nil, "tipo_dte": cuerpo.TipoDTE == nil,
		"folio": cuerpo.Folio == nil, "fecha_emision": cuerpo.FechaEmision == nil, "monto_total": cuerpo.MontoTotal == nil,
		"rut_receptor": cuerpo.RutReceptor == nil, "dv_receptor": cuerpo.DVReceptor == nil, "certificado_p12_b64": cuerpo.P12B64 == nil, "password_certificado": cuerpo.Password == nil}
	for campo, falta := range faltan {
		if falta {
			responderError(w, r, 422, "validacion", "Los datos enviados no son válidos.", faltaCampo(campo))
			return
		}
	}
	if cuerpo.Ambiente == "" {
		cuerpo.Ambiente = "certificacion"
	}
	cert, err := certificadoDesdeB64(*cuerpo.P12B64, *cuerpo.Password)
	if err != nil {
		responderError(w, r, 422, "certificado", "No se pudo cargar el certificado: "+err.Error(), nil)
		return
	}
	cli, err := sii.Nuevo(cuerpo.Ambiente, cert)
	if err != nil {
		responderError(w, r, 422, "validacion", err.Error(), nil)
		return
	}
	e, err := cli.EstadoDTE(*cuerpo.RutEmisor, *cuerpo.DVEmisor, *cuerpo.TipoDTE, *cuerpo.Folio, *cuerpo.FechaEmision, *cuerpo.MontoTotal, *cuerpo.RutReceptor, *cuerpo.DVReceptor)
	if err != nil {
		responderError(w, r, 502, "sii_comunicacion", "Error al consultar el SII: "+err.Error(), nil)
		return
	}
	responderJSON(w, 200, map[string]any{"folio": *cuerpo.Folio, "tipo_dte": *cuerpo.TipoDTE, "estado": e.Estado, "glosa": e.Glosa, "ambiente": cuerpo.Ambiente})
}

// enviarBoletas es POST /api/v1/boletas/enviar (solo Go): EnvioBOLETA firmado → REST
// (pangal/rahue) → TrackID de 15 dígitos. Marca las boletas del sobre como enviadas.
func (s *Servidor) enviarBoletas(w http.ResponseWriter, r *http.Request) {
	var cuerpo struct {
		XMLB64     *string `json:"xml_envio_b64"`
		P12B64     *string `json:"certificado_p12_b64"`
		Password   *string `json:"password_certificado"`
		RutEmpresa *string `json:"rut_empresa"`
		DVEmpresa  *string `json:"dv_empresa"`
		Ambiente   string  `json:"ambiente"`
	}
	if !leerJSON(w, r, &cuerpo) {
		return
	}
	for campo, v := range map[string]*string{"xml_envio_b64": cuerpo.XMLB64, "certificado_p12_b64": cuerpo.P12B64, "password_certificado": cuerpo.Password, "rut_empresa": cuerpo.RutEmpresa, "dv_empresa": cuerpo.DVEmpresa} {
		if v == nil {
			responderError(w, r, 422, "validacion", "Los datos enviados no son válidos.", faltaCampo(campo))
			return
		}
	}
	if cuerpo.Ambiente == "" {
		cuerpo.Ambiente = s.cfg.SIIAmbiente
	}
	cert, err := certificadoDesdeB64(*cuerpo.P12B64, *cuerpo.Password)
	if err != nil {
		responderDominio(w, r, err)
		return
	}
	xmlEnvio, err := base64.StdEncoding.DecodeString(*cuerpo.XMLB64)
	if err != nil {
		responderError(w, r, 422, "validacion", "El XML de envío no es Base64 válido: "+err.Error(), nil)
		return
	}
	if err := xsd.ValidarError(xmlEnvio); err != nil {
		responderError(w, r, 422, "validacion", "El XML no cumple el esquema XSD del SII: "+err.Error(), nil)
		return
	}
	cli, err := sii.NuevoBoleta(cuerpo.Ambiente, cert)
	if err != nil {
		responderError(w, r, 422, "validacion", err.Error(), nil)
		return
	}
	track, resp, err := cli.Enviar(xmlEnvio, *cuerpo.RutEmpresa, *cuerpo.DVEmpresa)
	if err != nil {
		var rech *sii.ErrRechazoBoleta
		if errors.As(err, &rech) {
			responderError(w, r, 422, "sii_rechazo", err.Error(), rech.Detalle)
			return
		}
		responderError(w, r, 502, "sii_comunicacion", err.Error(), nil)
		return
	}
	filas := s.marcarEnviadosPorXML(xmlEnvio, track, cuerpo.Ambiente)
	responderJSON(w, 200, map[string]any{"track_id": track, "mensaje": "Envío de boletas recibido. TrackID: " + track, "ambiente": cuerpo.Ambiente, "marcados": filas, "respuesta": resp})
}

// estadoBoletas es POST /api/v1/boletas/estado (solo Go): estado del sobre y, lo que importa,
// aceptados/rechazados por documento.
func (s *Servidor) estadoBoletas(w http.ResponseWriter, r *http.Request) {
	var cuerpo struct {
		TrackID    *string `json:"track_id"`
		RutEmpresa *string `json:"rut_empresa"`
		DVEmpresa  *string `json:"dv_empresa"`
		P12B64     *string `json:"certificado_p12_b64"`
		Password   *string `json:"password_certificado"`
		Ambiente   string  `json:"ambiente"`
	}
	if !leerJSON(w, r, &cuerpo) {
		return
	}
	for campo, v := range map[string]*string{"track_id": cuerpo.TrackID, "rut_empresa": cuerpo.RutEmpresa, "dv_empresa": cuerpo.DVEmpresa, "certificado_p12_b64": cuerpo.P12B64, "password_certificado": cuerpo.Password} {
		if v == nil {
			responderError(w, r, 422, "validacion", "Los datos enviados no son válidos.", faltaCampo(campo))
			return
		}
	}
	if cuerpo.Ambiente == "" {
		cuerpo.Ambiente = s.cfg.SIIAmbiente
	}
	cert, err := certificadoDesdeB64(*cuerpo.P12B64, *cuerpo.Password)
	if err != nil {
		responderDominio(w, r, err)
		return
	}
	cli, err := sii.NuevoBoleta(cuerpo.Ambiente, cert)
	if err != nil {
		responderError(w, r, 422, "validacion", err.Error(), nil)
		return
	}
	e, err := cli.Estado(*cuerpo.TrackID, *cuerpo.RutEmpresa, *cuerpo.DVEmpresa)
	if err != nil {
		responderError(w, r, 502, "sii_comunicacion", err.Error(), nil)
		return
	}
	responderJSON(w, 200, e)
}
