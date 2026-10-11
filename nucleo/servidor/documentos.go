package servidor

// /api/v1/dte/documentos* y /api/v1/dte/emisor (solo lectura), réplica de api/routes/dte.py.
// La (re)generación del PDF (POST …/pdf) sigue en Python mientras el PDF no esté en Go.

import (
	"database/sql"
	"fmt"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"strings"
)

func (s *Servidor) rutasDocumentos(mux *http.ServeMux) {
	mux.HandleFunc("GET /api/v1/dte/documentos", s.protegido(s.listarDocumentos))
	mux.HandleFunc("GET /api/v1/dte/documentos/emisores", s.protegido(s.emisoresDocumentos))
	mux.HandleFunc("GET /api/v1/dte/documentos/{id}/pdf", s.protegido(s.pdfDocumento))
	mux.HandleFunc("GET /api/v1/dte/documentos/{id}/xml", s.protegido(s.xmlDocumento))
	mux.HandleFunc("GET /api/v1/dte/emisor", s.protegido(s.emisorConfigurado))
}

// filaDTE es SELECT * FROM dtes como dict (los NULL salen null, como en Python).
type filaDTE map[string]any

func (s *Servidor) dtePorID(id int64) (filaDTE, error) {
	rows, err := s.db.Query(`SELECT * FROM dtes WHERE id=?`, id)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	filas, err := filasComoMapas(rows)
	if err != nil || len(filas) == 0 {
		return nil, err
	}
	return filas[0], nil
}

func filasComoMapas(rows *sql.Rows) ([]filaDTE, error) {
	cols, err := rows.Columns()
	if err != nil {
		return nil, err
	}
	var out []filaDTE
	for rows.Next() {
		vals := make([]any, len(cols))
		ptrs := make([]any, len(cols))
		for i := range vals {
			ptrs[i] = &vals[i]
		}
		if err := rows.Scan(ptrs...); err != nil {
			return nil, err
		}
		m := filaDTE{}
		for i, c := range cols {
			switch v := vals[i].(type) {
			case []byte:
				m[c] = string(v)
			default:
				m[c] = v
			}
		}
		out = append(out, m)
	}
	return out, rows.Err()
}

func texto(m filaDTE, k string) string {
	if v, ok := m[k].(string); ok {
		return v
	}
	return ""
}

func existeArchivo(p string) bool {
	if p == "" {
		return false
	}
	_, err := os.Stat(p)
	return err == nil
}

// listarDocumentos es listar_documentos: filtros, orden por creado_en DESC, límite 1..200.
func (s *Servidor) listarDocumentos(w http.ResponseWriter, r *http.Request) {
	q := r.URL.Query()
	limite := 25
	if v := q.Get("limite"); v != "" {
		n, err := strconv.Atoi(v)
		if err != nil {
			responderError(w, r, 422, "validacion", "Los datos enviados no son válidos.", map[string]any{"errores": []map[string]any{{"loc": []any{"query", "limite"}, "msg": "Input should be a valid integer", "type": "int_parsing"}}})
			return
		}
		limite = n
	}
	if limite < 1 {
		limite = 1
	}
	if limite > 200 {
		limite = 200
	}
	var cond []string
	var args []any
	if v := q.Get("rut_emisor"); v != "" {
		cond = append(cond, "rut_emisor=?")
		args = append(args, v)
	}
	if v := q.Get("tipo_dte"); v != "" {
		n, err := strconv.Atoi(v)
		if err != nil {
			responderError(w, r, 422, "validacion", "Los datos enviados no son válidos.", map[string]any{"errores": []map[string]any{{"loc": []any{"query", "tipo_dte"}, "msg": "Input should be a valid integer", "type": "int_parsing"}}})
			return
		}
		if n != 0 {
			cond = append(cond, "tipo_dte=?")
			args = append(args, n)
		}
	}
	if v := q.Get("estado"); v != "" {
		cond = append(cond, "estado=?")
		args = append(args, v)
	}
	where := "1=1"
	if len(cond) > 0 {
		where = strings.Join(cond, " AND ")
	}
	args = append(args, limite, 0)
	rows, err := s.db.Query(`SELECT * FROM dtes WHERE `+where+` ORDER BY creado_en DESC LIMIT ? OFFSET ?`, args...)
	if err != nil {
		responderError(w, r, 500, "error_interno", "Ocurrió un error interno. Reporta el request_id al soporte.", nil)
		return
	}
	defer rows.Close()
	filas, err := filasComoMapas(rows)
	if err != nil {
		responderError(w, r, 500, "error_interno", "Ocurrió un error interno. Reporta el request_id al soporte.", nil)
		return
	}
	docs := []filaDTE{}
	for _, d := range filas {
		xml := texto(d, "xml_firmado")
		delete(d, "xml_firmado")
		d["tiene_xml"] = xml != ""
		d["tiene_pdf"] = existeArchivo(texto(d, "pdf_path"))
		if strings.HasSuffix(texto(d, "estado"), "_mipyme") {
			d["canal"] = "mipyme"
		} else {
			d["canal"] = "motor"
		}
		docs = append(docs, d)
	}
	responderJSON(w, 200, map[string]any{"total": len(docs), "documentos": docs})
}

func (s *Servidor) emisoresDocumentos(w http.ResponseWriter, r *http.Request) {
	nombres := map[string]any{}
	if rows, err := s.db.Query(`SELECT rut, razon_social FROM negocios`); err == nil {
		for rows.Next() {
			var rut string
			var razon sql.NullString
			rows.Scan(&rut, &razon)
			if razon.Valid {
				nombres[rut] = razon.String
			} else {
				nombres[rut] = nil
			}
		}
		rows.Close()
	}
	rows, err := s.db.Query(`SELECT rut_emisor, COUNT(*) AS n, MAX(fecha_emision) AS ultimo FROM dtes GROUP BY rut_emisor ORDER BY ultimo DESC`)
	if err != nil {
		responderError(w, r, 500, "error_interno", "Ocurrió un error interno. Reporta el request_id al soporte.", nil)
		return
	}
	defer rows.Close()
	out := []map[string]any{}
	for rows.Next() {
		var rut string
		var n int
		var ultimo sql.NullString
		rows.Scan(&rut, &n, &ultimo)
		var razon any
		if v, ok := nombres[rut]; ok {
			razon = v
		}
		out = append(out, map[string]any{"rut": rut, "razon_social": razon, "documentos": n, "ultimo": nullString{ultimo}.valor()})
	}
	responderJSON(w, 200, map[string]any{"emisores": out})
}

func (s *Servidor) pdfDocumento(w http.ResponseWriter, r *http.Request) {
	id, err := strconv.ParseInt(r.PathValue("id"), 10, 64)
	if err != nil {
		responderError(w, r, 422, "validacion", "Los datos enviados no son válidos.", nil)
		return
	}
	d, err := s.dtePorID(id)
	if err != nil {
		responderError(w, r, 500, "error_interno", "Ocurrió un error interno. Reporta el request_id al soporte.", nil)
		return
	}
	if d == nil {
		responderError(w, r, 404, "no_encontrado", fmt.Sprintf("Documento %d no existe", id), nil)
		return
	}
	pp := texto(d, "pdf_path")
	if !existeArchivo(pp) {
		responderError(w, r, 404, "no_encontrado", "Este documento no tiene PDF guardado", nil)
		return
	}
	raiz, _ := filepath.Abs("storage")
	abs, _ := filepath.Abs(pp)
	if !strings.HasPrefix(abs, raiz+string(filepath.Separator)) { // nunca servir algo fuera de storage/
		responderError(w, r, 404, "no_encontrado", "Ruta de PDF fuera del almacenamiento del motor", nil)
		return
	}
	b, err := os.ReadFile(pp)
	if err != nil {
		responderError(w, r, 404, "no_encontrado", "Este documento no tiene PDF guardado", nil)
		return
	}
	w.Header().Set("Content-Type", "application/pdf")
	w.Header().Set("Content-Disposition", fmt.Sprintf(`inline; filename="dte_%v_%v.pdf"`, d["tipo_dte"], d["folio"]))
	w.WriteHeader(200)
	w.Write(b)
}

func (s *Servidor) xmlDocumento(w http.ResponseWriter, r *http.Request) {
	id, err := strconv.ParseInt(r.PathValue("id"), 10, 64)
	if err != nil {
		responderError(w, r, 422, "validacion", "Los datos enviados no son válidos.", nil)
		return
	}
	d, err := s.dtePorID(id)
	if err != nil {
		responderError(w, r, 500, "error_interno", "Ocurrió un error interno. Reporta el request_id al soporte.", nil)
		return
	}
	if d == nil {
		responderError(w, r, 404, "no_encontrado", fmt.Sprintf("Documento %d no existe", id), nil)
		return
	}
	xml := texto(d, "xml_firmado")
	if xml == "" {
		responderError(w, r, 404, "no_encontrado", "Este documento no tiene XML guardado", nil)
		return
	}
	// Guardado como texto decodificado de ISO-8859-1: se vuelve a esos bytes (errors="replace").
	out := make([]byte, 0, len(xml))
	for _, c := range xml {
		if c > 0xFF {
			out = append(out, '?')
		} else {
			out = append(out, byte(c))
		}
	}
	w.Header().Set("Content-Type", "application/xml")
	w.Header().Set("Content-Disposition", fmt.Sprintf(`attachment; filename="dte_%v_%v.xml"`, d["tipo_dte"], d["folio"]))
	w.WriteHeader(200)
	w.Write(out)
}

func (s *Servidor) emisorConfigurado(w http.ResponseWriter, r *http.Request) {
	v := s.cfg.Valores
	get := func(k string) string { return v[k] }
	var cod any
	if n, err := strconv.Atoi(get("EMPRESA_CODIGO_ACTIVIDAD")); err == nil {
		cod = n
	}
	oNulo := func(k string) any {
		if x := get(k); x != "" {
			return x
		}
		return nil
	}
	responderJSON(w, 200, map[string]any{
		"configurada": s.cfg.EmpresaConfigurada(), "rut": s.cfg.EmpresaRut, "razon_social": s.cfg.EmpresaRazonSocial,
		"giro": get("EMPRESA_GIRO"), "codigo_actividad": cod, "direccion": get("EMPRESA_DIRECCION"), "comuna": get("EMPRESA_COMUNA"),
		"ciudad": get("EMPRESA_CIUDAD"), "email": oNulo("EMPRESA_EMAIL"), "telefono": oNulo("EMPRESA_TELEFONO"),
	})
}
