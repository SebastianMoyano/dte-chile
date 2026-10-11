package servidor

import (
	"encoding/base64"
	"net/http"

	"dtechile/nucleo/xsd"
)

func (s *Servidor) rutasXSD(mux *http.ServeMux) {
	mux.HandleFunc("POST /api/v1/dte/validar-xml", s.protegido(s.validarXML))
}

// validarXML es POST /api/v1/dte/validar-xml de api/routes/dte.py, con nucleo/xsd en vez de
// lxml (mismo veredicto; los textos de los errores son los de Go).
func (s *Servidor) validarXML(w http.ResponseWriter, r *http.Request) {
	var cuerpo struct {
		XMLB64 *string `json:"xml_b64"`
	}
	if !leerJSON(w, r, &cuerpo) {
		return
	}
	if cuerpo.XMLB64 == nil {
		responderError(w, r, 422, "validacion", "Los datos enviados no son válidos.", map[string]any{"errores": []map[string]any{{"loc": []any{"body", "xml_b64"}, "msg": "Field required", "type": "missing"}}})
		return
	}
	raw, err := base64.StdEncoding.DecodeString(*cuerpo.XMLB64)
	if err != nil {
		responderError(w, r, 422, "validacion", "El XML no es Base64 válido: "+err.Error(), nil)
		return
	}
	res := xsd.Validar(raw)
	mensaje := "XML válido según esquema XSD del SII."
	if !res.Valido {
		mensaje = "XML inválido: " + itoa(len(res.Errores)) + " error(es)."
	}
	responderJSON(w, 200, map[string]any{"valido": res.Valido, "tipo_xml": res.TipoXML, "errores": res.Mensajes(), "mensaje": mensaje})
}

func itoa(n int) string {
	if n == 0 {
		return "0"
	}
	s := ""
	for n > 0 {
		s = string(rune('0'+n%10)) + s
		n /= 10
	}
	return s
}
