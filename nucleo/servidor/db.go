package servidor

import (
	"fmt"
	"net/http"
	"strconv"
	"strings"

	"dtechile/nucleo/ted"
)

// Rutas de api/routes/db.py: consultas directas a las tablas (dtes, cafs, audit_log).
func (s *Servidor) rutasDB(mux *http.ServeMux) {
	mux.HandleFunc("GET /api/v1/db/dtes", s.protegido(s.dbDTEs))
	mux.HandleFunc("GET /api/v1/db/dtes/buscar/{rut}/{tipo}/{folio}", s.protegido(s.dbBuscarDTE))
	mux.HandleFunc("GET /api/v1/db/dtes/{id}", s.protegido(s.dbDTE))
	mux.HandleFunc("GET /api/v1/db/cafs", s.protegido(s.dbCAFs))
	mux.HandleFunc("GET /api/v1/db/cafs/activo/{rut}/{tipo}", s.protegido(s.dbCAFActivo))
	mux.HandleFunc("POST /api/v1/db/cafs", s.protegido(s.dbRegistrarCAF))
	mux.HandleFunc("GET /api/v1/db/folios/siguiente/{rut}/{tipo}", s.protegido(s.dbFolioSiguiente))
	mux.HandleFunc("GET /api/v1/db/logs", s.protegido(s.dbLogs))
}

// errorQuery es el 422 de pydantic para un parámetro de consulta.
func errorQuery(w http.ResponseWriter, r *http.Request, campo, msg, tipo string) {
	responderError(w, r, 422, "validacion", "Los datos enviados no son válidos.", map[string]any{"errores": []map[string]any{{"loc": []any{"query", campo}, "msg": msg, "type": tipo}}})
}

func errorPath(w http.ResponseWriter, r *http.Request, campo string) {
	responderError(w, r, 422, "validacion", "Los datos enviados no son válidos.", map[string]any{"errores": []map[string]any{{"loc": []any{"path", campo}, "msg": "Input should be a valid integer, unable to parse string as an integer", "type": "int_parsing"}}})
}

// enteroQuery lee un entero opcional de la query con los límites de `Query(ge=, le=)`.
func enteroQuery(w http.ResponseWriter, r *http.Request, campo string, def, min, max int) (int, bool) {
	v := r.URL.Query().Get(campo)
	if v == "" {
		return def, true
	}
	n, err := strconv.Atoi(v)
	if err != nil {
		errorQuery(w, r, campo, "Input should be a valid integer, unable to parse string as an integer", "int_parsing")
		return 0, false
	}
	if n < min {
		errorQuery(w, r, campo, fmt.Sprintf("Input should be greater than or equal to %d", min), "greater_than_equal")
		return 0, false
	}
	if max > 0 && n > max {
		errorQuery(w, r, campo, fmt.Sprintf("Input should be less than or equal to %d", max), "less_than_equal")
		return 0, false
	}
	return n, true
}

// dteResponse es DTEResponse: el subconjunto de columnas que expone la ruta.
func dteResponse(d filaDTE) map[string]any {
	out := map[string]any{}
	for _, k := range []string{"id", "tipo_dte", "folio", "rut_emisor", "rut_receptor", "razon_social_receptor", "fecha_emision",
		"monto_neto", "monto_exento", "iva", "monto_total", "estado", "track_id", "pdf_path", "ambiente", "creado_en"} {
		v, ok := d[k]
		if !ok {
			v = nil
		}
		if k == "track_id" { // Optional[int]: Python convierte "123" → 123
			if t, es := v.(string); es {
				if n, err := strconv.ParseInt(strings.TrimSpace(t), 10, 64); err == nil {
					v = n
				} else if t == "" {
					v = nil
				}
			}
		}
		out[k] = v
	}
	for _, k := range []string{"monto_neto", "monto_exento", "iva", "monto_total"} {
		if out[k] == nil {
			out[k] = int64(0)
		}
	}
	return out
}

func (s *Servidor) dbDTEs(w http.ResponseWriter, r *http.Request) {
	q := r.URL.Query()
	limite, ok := enteroQuery(w, r, "limite", 100, 1, 1000)
	if !ok {
		return
	}
	offset, ok := enteroQuery(w, r, "offset", 0, 0, 0)
	if !ok {
		return
	}
	var cond []string
	var args, argsConteo []any
	if v := q.Get("rut_emisor"); v != "" {
		cond = append(cond, "rut_emisor=?")
		args = append(args, v)
	}
	if v := q.Get("tipo_dte"); v != "" {
		n, err := strconv.Atoi(v)
		if err != nil {
			errorQuery(w, r, "tipo_dte", "Input should be a valid integer, unable to parse string as an integer", "int_parsing")
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
	argsConteo = append(argsConteo, args...)
	condConteo := append([]string{}, cond...)
	if v := q.Get("fecha_desde"); v != "" {
		cond = append(cond, "fecha_emision>=?")
		args = append(args, v)
	}
	if v := q.Get("fecha_hasta"); v != "" {
		cond = append(cond, "fecha_emision<=?")
		args = append(args, v)
	}
	where := strings.Join(cond, " AND ")
	if where == "" {
		where = "1=1"
	}
	whereConteo := strings.Join(condConteo, " AND ")
	if whereConteo == "" {
		whereConteo = "1=1"
	}
	rows, err := s.db.Query("SELECT * FROM dtes WHERE "+where+" ORDER BY creado_en DESC LIMIT ? OFFSET ?", append(args, limite, offset)...)
	if err != nil {
		responderError(w, r, 500, "error_interno", "Ocurrió un error interno. Reporta el request_id al soporte.", nil)
		return
	}
	filas, err := filasComoMapas(rows)
	rows.Close()
	if err != nil {
		responderError(w, r, 500, "error_interno", "Ocurrió un error interno. Reporta el request_id al soporte.", nil)
		return
	}
	var total int64
	_ = s.db.QueryRow("SELECT COUNT(*) FROM dtes WHERE "+whereConteo, argsConteo...).Scan(&total)
	dtes := make([]map[string]any, 0, len(filas))
	for _, f := range filas {
		dtes = append(dtes, dteResponse(f))
	}
	responderJSON(w, 200, map[string]any{"total": total, "dtes": dtes})
}

func (s *Servidor) dbDTE(w http.ResponseWriter, r *http.Request) {
	id, err := strconv.ParseInt(r.PathValue("id"), 10, 64)
	if err != nil {
		errorPath(w, r, "dte_id")
		return
	}
	d, err := s.dtePorID(id)
	if err != nil {
		responderError(w, r, 500, "error_interno", "Ocurrió un error interno. Reporta el request_id al soporte.", nil)
		return
	}
	if d == nil {
		responderError(w, r, 404, "no_encontrado", "DTE no encontrado", nil)
		return
	}
	responderJSON(w, 200, dteResponse(d))
}

func (s *Servidor) dbBuscarDTE(w http.ResponseWriter, r *http.Request) {
	tipo, err := strconv.Atoi(r.PathValue("tipo"))
	if err != nil {
		errorPath(w, r, "tipo_dte")
		return
	}
	folio, err := strconv.Atoi(r.PathValue("folio"))
	if err != nil {
		errorPath(w, r, "folio")
		return
	}
	rows, err := s.db.Query(`SELECT * FROM dtes WHERE rut_emisor=? AND tipo_dte=? AND folio=?`, r.PathValue("rut"), tipo, folio)
	if err != nil {
		responderError(w, r, 500, "error_interno", "Ocurrió un error interno. Reporta el request_id al soporte.", nil)
		return
	}
	filas, _ := filasComoMapas(rows)
	rows.Close()
	if len(filas) == 0 {
		responderError(w, r, 404, "no_encontrado", "DTE no encontrado", nil)
		return
	}
	responderJSON(w, 200, dteResponse(filas[0]))
}

func cafResponse(c filaDTE) map[string]any {
	activo := false
	if n, ok := c["activo"].(int64); ok {
		activo = n != 0
	}
	return map[string]any{"id": c["id"], "tipo_dte": c["tipo_dte"], "rut_emisor": c["rut_emisor"], "folio_desde": c["folio_desde"],
		"folio_hasta": c["folio_hasta"], "folio_siguiente": c["folio_siguiente"], "fecha_autorizacion": c["fecha_autorizacion"],
		"activo": activo, "creado_en": c["creado_en"]}
}

func (s *Servidor) cafActivoFila(rut string, tipo int) (filaDTE, error) {
	rows, err := s.db.Query(`SELECT * FROM cafs WHERE rut_emisor=? AND tipo_dte=? AND activo=1 ORDER BY folio_desde DESC LIMIT 1`, rut, tipo)
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

func (s *Servidor) dbCAFs(w http.ResponseWriter, r *http.Request) {
	q := r.URL.Query()
	var cond []string
	var args []any
	if v := q.Get("rut_emisor"); v != "" {
		cond = append(cond, "rut_emisor=?")
		args = append(args, v)
	}
	if v := q.Get("tipo_dte"); v != "" {
		n, err := strconv.Atoi(v)
		if err != nil {
			errorQuery(w, r, "tipo_dte", "Input should be a valid integer, unable to parse string as an integer", "int_parsing")
			return
		}
		if n != 0 {
			cond = append(cond, "tipo_dte=?")
			args = append(args, n)
		}
	}
	where := strings.Join(cond, " AND ")
	if where == "" {
		where = "1=1"
	}
	rows, err := s.db.Query("SELECT * FROM cafs WHERE "+where+" ORDER BY creado_en DESC", args...)
	if err != nil {
		responderError(w, r, 500, "error_interno", "Ocurrió un error interno. Reporta el request_id al soporte.", nil)
		return
	}
	filas, _ := filasComoMapas(rows)
	rows.Close()
	out := make([]map[string]any, 0, len(filas))
	for _, f := range filas {
		out = append(out, cafResponse(f))
	}
	responderJSON(w, 200, out)
}

func (s *Servidor) dbCAFActivo(w http.ResponseWriter, r *http.Request) {
	tipo, err := strconv.Atoi(r.PathValue("tipo"))
	if err != nil {
		errorPath(w, r, "tipo_dte")
		return
	}
	c, err := s.cafActivoFila(r.PathValue("rut"), tipo)
	if err != nil {
		responderError(w, r, 500, "error_interno", "Ocurrió un error interno. Reporta el request_id al soporte.", nil)
		return
	}
	if c == nil {
		responderError(w, r, 404, "no_encontrado", "No hay CAF activo para estos parámetros", nil)
		return
	}
	responderJSON(w, 200, cafResponse(c))
}

// dbRegistrarCAF es post_registrar_caf: sube el XML, desactiva los CAF anteriores del mismo
// emisor+tipo y registra el nuevo (folio_siguiente = folio_desde).
func (s *Servidor) dbRegistrarCAF(w http.ResponseWriter, r *http.Request) {
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
	_, _ = s.db.Exec(`UPDATE cafs SET activo=0 WHERE rut_emisor=? AND tipo_dte=?`, caf.RutEmisor, caf.TipoDTE)
	if _, err := s.alm.RegistrarCAF(caf.TipoDTE, caf.RutEmisor, caf.FolioDesde, caf.FolioHasta, caf.FechaAutorizacion, string(contenido)); err != nil {
		responderError(w, r, 500, "error_interno", "Ocurrió un error interno. Reporta el request_id al soporte.", nil)
		return
	}
	c, err := s.cafActivoFila(caf.RutEmisor, caf.TipoDTE)
	if err != nil || c == nil {
		responderError(w, r, 500, "error_interno", "Ocurrió un error interno. Reporta el request_id al soporte.", nil)
		return
	}
	responderJSON(w, 200, cafResponse(c))
}

func (s *Servidor) dbFolioSiguiente(w http.ResponseWriter, r *http.Request) {
	rut := r.PathValue("rut")
	tipo, err := strconv.Atoi(r.PathValue("tipo"))
	if err != nil {
		errorPath(w, r, "tipo_dte")
		return
	}
	c, err := s.cafActivoFila(rut, tipo)
	if err != nil {
		responderError(w, r, 500, "error_interno", "Ocurrió un error interno. Reporta el request_id al soporte.", nil)
		return
	}
	if c == nil {
		responderJSON(w, 200, map[string]any{"rut_emisor": rut, "tipo_dte": tipo, "folio_disponible": nil, "folio_desde": nil, "folio_hasta": nil,
			"mensaje": "No hay CAF activo. Debe registrar un CAF primero."})
		return
	}
	sig, _ := c["folio_siguiente"].(int64)
	hasta, _ := c["folio_hasta"].(int64)
	if sig > hasta {
		responderJSON(w, 200, map[string]any{"rut_emisor": rut, "tipo_dte": tipo, "folio_disponible": nil, "folio_desde": c["folio_desde"], "folio_hasta": c["folio_hasta"],
			"mensaje": "Rango de folios agotado. Debe solicitar nuevos folios al SII."})
		return
	}
	responderJSON(w, 200, map[string]any{"rut_emisor": rut, "tipo_dte": tipo, "folio_disponible": sig, "folio_desde": c["folio_desde"], "folio_hasta": c["folio_hasta"],
		"mensaje": fmt.Sprintf("Siguiente folio disponible: %d", sig)})
}

func (s *Servidor) dbLogs(w http.ResponseWriter, r *http.Request) {
	q := r.URL.Query()
	limite, ok := enteroQuery(w, r, "limite", 100, 1, 1000)
	if !ok {
		return
	}
	var cond []string
	var args []any
	if v := q.Get("accion"); v != "" {
		cond = append(cond, "accion=?")
		args = append(args, v)
	}
	if v := q.Get("rut_emisor"); v != "" {
		cond = append(cond, "rut_emisor=?")
		args = append(args, v)
	}
	if v := q.Get("fecha_desde"); v != "" {
		cond = append(cond, "creado_en>=?")
		args = append(args, v)
	}
	where := strings.Join(cond, " AND ")
	if where == "" {
		where = "1=1"
	}
	rows, err := s.db.Query("SELECT * FROM audit_log WHERE "+where+" ORDER BY creado_en DESC LIMIT ?", append(args, limite)...)
	if err != nil {
		responderError(w, r, 500, "error_interno", "Ocurrió un error interno. Reporta el request_id al soporte.", nil)
		return
	}
	filas, _ := filasComoMapas(rows)
	rows.Close()
	out := make([]map[string]any, 0, len(filas))
	for _, f := range filas {
		m := map[string]any{}
		for _, k := range []string{"id", "accion", "tipo_dte", "folio", "rut_emisor", "detalle", "creado_en"} {
			v, ok := f[k]
			if !ok {
				v = nil
			}
			m[k] = v
		}
		out = append(out, m)
	}
	responderJSON(w, 200, out)
}
