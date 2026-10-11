package servidor

import (
	"crypto"
	"crypto/rand"
	"crypto/rsa"
	"crypto/sha1"
	"encoding/base64"
	"fmt"
	"io"
	"net/http"
	"strings"

	"dtechile/nucleo/firma"
	"dtechile/nucleo/ted"
)

// Rutas de api/routes/caf.py y certificado.py: utilidades sin estado sobre un CAF o un .p12.
func (s *Servidor) rutasCAF(mux *http.ServeMux) {
	mux.HandleFunc("POST /api/v1/caf/info", s.protegido(s.cafInfo))
	mux.HandleFunc("POST /api/v1/caf/validar-folio", s.protegido(s.cafValidarFolio))
	mux.HandleFunc("POST /api/v1/certificado/validar", s.protegido(s.certificadoValidar))
	mux.HandleFunc("POST /api/v1/certificado/firmar-datos", s.protegido(s.certificadoFirmarDatos))
}

const maxUploadForm = 10 << 20

// leerArchivoForm es api/util.leer_upload para un campo de multipart: contenido y nombre.
// Sin el campo → 422 "Field required" (como FastAPI).
func leerArchivoForm(w http.ResponseWriter, r *http.Request, campo string) ([]byte, string, bool) {
	if err := r.ParseMultipartForm(maxUploadForm + 1024); err != nil {
		responderError(w, r, 422, "validacion", "Los datos enviados no son válidos.", map[string]any{"errores": []map[string]any{{"loc": []any{"body", campo}, "msg": "Field required", "type": "missing"}}})
		return nil, "", false
	}
	f, h, err := r.FormFile(campo)
	if err != nil {
		responderError(w, r, 422, "validacion", "Los datos enviados no son válidos.", map[string]any{"errores": []map[string]any{{"loc": []any{"body", campo}, "msg": "Field required", "type": "missing"}}})
		return nil, "", false
	}
	defer f.Close()
	b, err := io.ReadAll(io.LimitReader(f, maxUploadForm+1))
	if err != nil {
		responderError(w, r, 422, "validacion", "No se pudo leer el archivo.", nil)
		return nil, "", false
	}
	if len(b) > maxUploadForm {
		responderError(w, r, 422, "validacion", fmt.Sprintf("Archivo demasiado grande (máximo %d MB).", maxUploadForm>>20), nil)
		return nil, "", false
	}
	return b, h.Filename, true
}

func (s *Servidor) cafInfo(w http.ResponseWriter, r *http.Request) {
	contenido, nombre, ok := leerArchivoForm(w, r, "archivo")
	if !ok {
		return
	}
	if nombre == "" || !strings.HasSuffix(strings.ToLower(nombre), ".xml") {
		responderError(w, r, 422, "validacion", "El archivo debe ser un CAF en formato XML.", nil)
		return
	}
	caf, err := ted.ParsearCAF(string(contenido))
	if err != nil {
		responderError(w, r, 422, "caf", "No se pudo parsear el CAF: "+err.Error(), nil)
		return
	}
	total := caf.FolioHasta - caf.FolioDesde + 1
	responderJSON(w, 200, map[string]any{"tipo_dte": caf.TipoDTE, "rut_emisor": caf.RutEmisor, "folio_desde": caf.FolioDesde, "folio_hasta": caf.FolioHasta,
		"fecha_autorizacion": caf.FechaAutorizacion, "total_folios": total,
		"mensaje": fmt.Sprintf("CAF válido para %d folios del tipo DTE %d.", total, caf.TipoDTE)})
}

func (s *Servidor) cafValidarFolio(w http.ResponseWriter, r *http.Request) {
	var cuerpo struct {
		CAFB64 *string `json:"caf_xml_b64"`
		Folio  *int    `json:"folio"`
	}
	if !leerJSON(w, r, &cuerpo) {
		return
	}
	if cuerpo.CAFB64 == nil {
		faltan(w, r, "caf_xml_b64")
		return
	}
	if cuerpo.Folio == nil {
		faltan(w, r, "folio")
		return
	}
	raw, err := base64.StdEncoding.DecodeString(*cuerpo.CAFB64)
	if err != nil {
		responderError(w, r, 422, "caf", "No se pudo procesar el CAF: "+err.Error(), nil)
		return
	}
	caf, err := ted.ParsearCAF(string(raw))
	if err != nil {
		responderError(w, r, 422, "caf", "No se pudo procesar el CAF: "+err.Error(), nil)
		return
	}
	valido := *cuerpo.Folio >= caf.FolioDesde && *cuerpo.Folio <= caf.FolioHasta
	msg := fmt.Sprintf("El folio %d está autorizado en el CAF.", *cuerpo.Folio)
	if !valido {
		msg = fmt.Sprintf("El folio %d está FUERA del rango [%d-%d] del CAF.", *cuerpo.Folio, caf.FolioDesde, caf.FolioHasta)
	}
	responderJSON(w, 200, map[string]any{"folio": *cuerpo.Folio, "valido": valido, "mensaje": msg})
}

func rutDelCert(c *firma.Certificado) string {
	if r, err := c.RutEmisor(); err == nil && r != "" {
		return r
	}
	return "SIN-RUT"
}

func (s *Servidor) certificadoValidar(w http.ResponseWriter, r *http.Request) {
	contenido, nombre, ok := leerArchivoForm(w, r, "archivo")
	if !ok {
		return
	}
	password := r.FormValue("password")
	if _, hay := r.MultipartForm.Value["password"]; !hay {
		faltan(w, r, "password")
		return
	}
	n := strings.ToLower(nombre)
	if nombre == "" || !(strings.HasSuffix(n, ".p12") || strings.HasSuffix(n, ".pfx")) {
		responderError(w, r, 422, "validacion", "El archivo debe ser un certificado digital .p12 o .pfx", nil)
		return
	}
	if len(contenido) == 0 {
		responderError(w, r, 422, "validacion", "El archivo está vacío.", nil)
		return
	}
	cert, err := firma.CargarP12(contenido, password)
	if err != nil {
		responderError(w, r, 422, "certificado", "No se pudo cargar el certificado: "+err.Error(), nil)
		return
	}
	rut := rutDelCert(cert)
	b64 := base64.StdEncoding.EncodeToString(cert.Cert.Raw)
	if len(b64) > 80 {
		b64 = b64[:80]
	}
	responderJSON(w, 200, map[string]any{"rut_emisor": rut, "certificado_b64": b64 + "...",
		"mensaje": fmt.Sprintf("Certificado cargado correctamente para el emisor %s.", rut)})
}

func (s *Servidor) certificadoFirmarDatos(w http.ResponseWriter, r *http.Request) {
	var cuerpo struct {
		DatosB64 *string `json:"datos_b64"`
		Password *string `json:"password"`
		P12B64   *string `json:"certificado_p12_b64"`
	}
	if !leerJSON(w, r, &cuerpo) {
		return
	}
	for campo, v := range map[string]*string{"datos_b64": cuerpo.DatosB64, "password": cuerpo.Password, "certificado_p12_b64": cuerpo.P12B64} {
		if v == nil {
			faltan(w, r, campo)
			return
		}
	}
	p12, err := base64.StdEncoding.DecodeString(*cuerpo.P12B64)
	if err != nil {
		responderError(w, r, 422, "certificado", "No se pudo cargar el certificado: "+err.Error(), nil)
		return
	}
	cert, err := firma.CargarP12(p12, *cuerpo.Password)
	if err != nil {
		responderError(w, r, 422, "certificado", "No se pudo cargar el certificado: "+err.Error(), nil)
		return
	}
	datos, err := base64.StdEncoding.DecodeString(*cuerpo.DatosB64)
	if err != nil {
		responderError(w, r, 422, "validacion", "Los datos no son Base64 válido: "+err.Error(), nil)
		return
	}
	h := sha1.Sum(datos)
	sig, err := rsa.SignPKCS1v15(rand.Reader, cert.Clave, crypto.SHA1, h[:])
	if err != nil {
		responderError(w, r, 500, "error_interno", "Ocurrió un error interno. Reporta el request_id al soporte.", nil)
		return
	}
	responderJSON(w, 200, map[string]any{"firma_b64": base64.StdEncoding.EncodeToString(sig), "algoritmo": "RSA-SHA1"})
}
