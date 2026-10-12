package servidor

import (
	"bytes"
	"embed"
	"fmt"
	"html"
	"net/http"
	"net/url"
	"os"
	"strconv"
	"strings"

	"dtechile/nucleo/pdf"
)

// Copias byte a byte de static/*.html (TestStaticIgual lo exige): las páginas del panel web
// (certificados, onboarding, apikeys, documentos), que hablan con la API por JWT.
//
//go:embed static/*.html
var staticFS embed.FS

// api/routes/consulta.py — buscador PÚBLICO de boletas para el receptor (sin login). Exige los
// 5 datos de la boleta (RUT emisor, tipo, folio, fecha y monto total) para no permitir
// enumeración; solo lee la base local. Y las páginas del panel + favicon de main.py.
func (s *Servidor) rutasConsulta(mux *http.ServeMux) {
	mux.HandleFunc("GET /consulta", s.consultaFormulario)
	mux.HandleFunc("GET /consulta/{$}", s.consultaFormulario)
	mux.HandleFunc("POST /consulta", s.consultaPOST)
	mux.HandleFunc("POST /consulta/{$}", s.consultaPOST)
	mux.HandleFunc("GET /consulta/api", s.consultaAPI)
	mux.HandleFunc("GET /consulta/xml", s.consultaXML)
	mux.HandleFunc("GET /consulta/pdf", s.consultaPDF)
	for _, p := range []string{"certificados", "onboarding", "apikeys", "documentos"} {
		pagina := p
		mux.HandleFunc("GET /"+pagina, func(w http.ResponseWriter, r *http.Request) {
			b, err := staticFS.ReadFile("static/" + pagina + ".html")
			if err != nil {
				http.NotFound(w, r)
				return
			}
			w.Header().Set("Content-Type", "text/html; charset=utf-8")
			w.Header().Set("Cache-Control", "no-cache")
			_, _ = w.Write(b)
		})
	}
	mux.HandleFunc("GET /static/{archivo}", func(w http.ResponseWriter, r *http.Request) {
		b, err := staticFS.ReadFile("static/" + r.PathValue("archivo"))
		if err != nil {
			http.NotFound(w, r)
			return
		}
		w.Header().Set("Content-Type", "text/html; charset=utf-8")
		_, _ = w.Write(b)
	})
	mux.HandleFunc("GET /favicon.ico", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "image/svg+xml")
		w.Header().Set("Cache-Control", "public, max-age=86400")
		_, _ = w.Write([]byte(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#2563eb" stroke-width="2" stroke-linejoin="round"><path d="M12 2l7 3v6c0 4.4-3 8.3-7 9-4-.7-7-4.6-7-9V5l7-3z"/><path d="M9 12l2 2 4-4" stroke-linecap="round"/></svg>`))
	})
}

var tiposConsulta = []struct {
	codigo int
	nombre string
}{{39, "Boleta Electrónica"}, {41, "Boleta Exenta Electrónica"}}

func nombreTipoConsulta(t int) string {
	for _, x := range tiposConsulta {
		if x.codigo == t {
			return x.nombre
		}
	}
	return ""
}

func normRut(rut string) string {
	return strings.ToUpper(strings.TrimSpace(strings.ReplaceAll(rut, ".", "")))
}

// buscarBoleta es _buscar: la fila si coinciden TODOS los datos, o nil.
func (s *Servidor) buscarBoleta(rut string, tipo, folio int, monto int64, fecha string) (filaDTE, error) {
	if nombreTipoConsulta(tipo) == "" {
		return nil, nil
	}
	q := `SELECT * FROM dtes WHERE rut_emisor=? AND tipo_dte=? AND folio=? AND monto_total=?`
	args := []any{normRut(rut), tipo, folio, monto}
	if fecha != "" {
		q += " AND fecha_emision=?"
		args = append(args, strings.TrimSpace(fecha))
	}
	rows, err := s.db.Query(q, args...)
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

// qsConsulta es _qs: los 5 datos como query string (mismo candado para las descargas).
func qsConsulta(rut string, tipo, folio int, monto int64, fecha string) string {
	v := url.Values{}
	v.Set("rut", normRut(rut))
	v.Set("tipo", strconv.Itoa(tipo))
	v.Set("folio", strconv.Itoa(folio))
	v.Set("monto", strconv.FormatInt(monto, 10))
	if fecha != "" {
		v.Set("fecha", fecha)
	}
	return v.Encode()
}

// paginaConsulta es _pagina: la página autocontenida (tema claro/oscuro, sin dependencias).
func paginaConsulta(cuerpo, rut, folio, monto string, tipo int, fecha string) string {
	var op strings.Builder
	for _, t := range tiposConsulta {
		sel := ""
		if t.codigo == tipo {
			sel = " selected"
		}
		fmt.Fprintf(&op, `<option value="%d"%s>%s</option>`, t.codigo, sel, t.nombre)
	}
	return `<!doctype html><html lang="es"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Consulta de Boleta Electrónica</title>
<style>
  :root { --bg:#f4f5f7; --card:#fff; --fg:#1a1c1f; --mut:#5c636e; --acc:#1f6feb; --bd:#dfe3e8; }
  @media (prefers-color-scheme: dark) {
    :root { --bg:#0f1216; --card:#181c22; --fg:#e8eaed; --mut:#9aa3ad; --acc:#4c8dff; --bd:#2a2f37; } }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--fg); font:15px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif; }
  .wrap { max-width:560px; margin:0 auto; padding:32px 20px; }
  h1 { font-size:1.35rem; margin:0 0 4px; }
  .sub { color:var(--mut); margin:0 0 24px; font-size:.92rem; }
  .card { background:var(--card); border:1px solid var(--bd); border-radius:12px; padding:22px; }
  label { display:block; font-weight:600; font-size:.82rem; margin:14px 0 5px; }
  input,select { width:100%; padding:10px 12px; border:1px solid var(--bd); border-radius:8px;
    background:transparent; color:var(--fg); font-size:1rem; }
  button { margin-top:20px; width:100%; padding:12px; border:0; border-radius:8px;
    background:var(--acc); color:#fff; font-size:1rem; font-weight:600; cursor:pointer; }
  table { width:100%; border-collapse:collapse; margin-top:6px; }
  td { padding:8px 4px; border-bottom:1px solid var(--bd); }
  td:first-child { color:var(--mut); width:44%; }
  td:last-child { text-align:right; font-variant-numeric:tabular-nums; }
  .ok { color:#1a7f37; font-weight:600; } .no { color:#b3261e; font-weight:600; }
  .dl { display:flex; gap:10px; margin-top:18px; }
  .dl a { flex:1; text-align:center; padding:11px; border:1px solid var(--acc); border-radius:8px;
    color:var(--acc); text-decoration:none; font-weight:600; font-size:.92rem; }
  .foot { color:var(--mut); font-size:.82rem; margin-top:18px; text-align:center; }
  .foot a { color:var(--acc); }
</style></head><body><div class="wrap">
<h1>Consulta de Boleta Electrónica</h1>
<p class="sub">Ingrese los datos de su boleta para verificarla.</p>
<div class="card">
<form method="post" action="/consulta">
  <label>RUT del emisor</label>
  <input name="rut_emisor" placeholder="76111111-6" value="` + html.EscapeString(rut) + `" required>
  <label>Tipo de documento</label>
  <select name="tipo_dte">` + op.String() + `</select>
  <label>Folio</label>
  <input name="folio" inputmode="numeric" placeholder="1" value="` + html.EscapeString(folio) + `" required>
  <label>Fecha de emisión</label>
  <input name="fecha_emision" type="date" value="` + html.EscapeString(fecha) + `" required>
  <label>Monto total ($)</label>
  <input name="monto_total" inputmode="numeric" placeholder="29800" value="` + html.EscapeString(monto) + `" required>
  <button type="submit">Consultar boleta</button>
</form>
` + cuerpo + `
</div>
<p class="foot">Verifique también la autenticidad en <a href="https://www.sii.cl" rel="noopener">www.sii.cl</a></p>
</div></body></html>`
}

func responderHTML(w http.ResponseWriter, h string) {
	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	_, _ = w.Write([]byte(h))
}

func (s *Servidor) consultaFormulario(w http.ResponseWriter, r *http.Request) {
	responderHTML(w, paginaConsulta("", "", "", "", 39, ""))
}

// parametrosConsulta lee rut, tipo, folio, monto (obligatorios) y fecha (opcional) de la query.
func parametrosConsulta(w http.ResponseWriter, r *http.Request) (rut string, tipo, folio int, monto int64, fecha string, ok bool) {
	q := r.URL.Query()
	rut = q.Get("rut")
	for _, campo := range []string{"rut", "tipo", "folio", "monto"} {
		if q.Get(campo) == "" {
			errorQuery(w, r, campo, "Field required", "missing")
			return
		}
	}
	var err error
	if tipo, err = strconv.Atoi(q.Get("tipo")); err != nil {
		errorQuery(w, r, "tipo", "Input should be a valid integer, unable to parse string as an integer", "int_parsing")
		return
	}
	if folio, err = strconv.Atoi(q.Get("folio")); err != nil {
		errorQuery(w, r, "folio", "Input should be a valid integer, unable to parse string as an integer", "int_parsing")
		return
	}
	if monto, err = strconv.ParseInt(q.Get("monto"), 10, 64); err != nil {
		errorQuery(w, r, "monto", "Input should be a valid integer, unable to parse string as an integer", "int_parsing")
		return
	}
	return rut, tipo, folio, monto, q.Get("fecha"), true
}

// consultaAPI es GET /consulta/api: la consulta en JSON (integración con otra app).
func (s *Servidor) consultaAPI(w http.ResponseWriter, r *http.Request) {
	rut, tipo, folio, monto, fecha, ok := parametrosConsulta(w, r)
	if !ok {
		return
	}
	if nombreTipoConsulta(tipo) == "" {
		responderJSON(w, 400, map[string]any{"encontrada": false, "error": "tipo_no_valido"})
		return
	}
	d, err := s.buscarBoleta(rut, tipo, folio, monto, fecha)
	if err != nil {
		responderError(w, r, 500, "error_interno", "Ocurrió un error interno. Reporta el request_id al soporte.", nil)
		return
	}
	if d == nil {
		responderJSON(w, 200, map[string]any{"encontrada": false})
		return
	}
	qs := qsConsulta(rut, tipo, folio, monto, fecha)
	responderJSON(w, 200, map[string]any{"encontrada": true, "documento": map[string]any{
		"tipo": tipo, "tipo_nombre": nombreTipoConsulta(tipo), "folio": d["folio"], "rut_emisor": d["rut_emisor"], "rut_receptor": d["rut_receptor"],
		"fecha_emision": d["fecha_emision"], "monto_neto": d["monto_neto"], "monto_exento": d["monto_exento"], "iva": d["iva"],
		"monto_total": d["monto_total"], "track_id": d["track_id"]},
		"links": map[string]any{"pdf": "/consulta/pdf?" + qs, "xml": "/consulta/xml?" + qs}})
}

func (s *Servidor) consultaXML(w http.ResponseWriter, r *http.Request) {
	rut, tipo, folio, monto, fecha, ok := parametrosConsulta(w, r)
	if !ok {
		return
	}
	d, err := s.buscarBoleta(rut, tipo, folio, monto, fecha)
	if err != nil {
		responderError(w, r, 500, "error_interno", "Ocurrió un error interno. Reporta el request_id al soporte.", nil)
		return
	}
	if d == nil || texto(d, "xml_firmado") == "" {
		responderJSON(w, 404, map[string]any{"error": "no_encontrada"})
		return
	}
	w.Header().Set("Content-Type", "application/xml")
	w.Header().Set("Content-Disposition", fmt.Sprintf(`attachment; filename="boleta_%d_%d.xml"`, tipo, folio))
	_, _ = w.Write(bytesLatin1(texto(d, "xml_firmado")))
}

// consultaPDF sirve el PDF guardado o lo regenera desde el XML (TED verbatim).
func (s *Servidor) consultaPDF(w http.ResponseWriter, r *http.Request) {
	rut, tipo, folio, monto, fecha, ok := parametrosConsulta(w, r)
	if !ok {
		return
	}
	d, err := s.buscarBoleta(rut, tipo, folio, monto, fecha)
	if err != nil {
		responderError(w, r, 500, "error_interno", "Ocurrió un error interno. Reporta el request_id al soporte.", nil)
		return
	}
	if d == nil {
		responderJSON(w, 404, map[string]any{"error": "no_encontrada"})
		return
	}
	disp := fmt.Sprintf(`inline; filename="boleta_%d_%d.pdf"`, tipo, folio)
	if pp := s.rutaDesdeBD(texto(d, "pdf_path")); pp != "" {
		if b, err := os.ReadFile(pp); err == nil {
			w.Header().Set("Content-Type", "application/pdf")
			w.Header().Set("Content-Disposition", disp)
			_, _ = w.Write(b)
			return
		}
	}
	xml := texto(d, "xml_firmado")
	if xml == "" {
		responderJSON(w, 404, map[string]any{"error": "sin_xml"})
		return
	}
	doc, ted, err := pdf.DesdeXML(bytesLatin1(xml))
	var b []byte
	if err == nil {
		b, err = pdf.Boleta80mm(doc, ted)
	}
	if err != nil {
		responderJSON(w, 500, map[string]any{"error": "pdf_no_disponible", "detalle": err.Error()})
		return
	}
	w.Header().Set("Content-Type", "application/pdf")
	w.Header().Set("Content-Disposition", disp)
	_, _ = w.Write(b)
}

func dinero(v any) string {
	n := int64(numero(v))
	s := strconv.FormatInt(n, 10)
	neg := strings.HasPrefix(s, "-")
	s = strings.TrimPrefix(s, "-")
	var out []byte
	for i, c := range []byte(s) {
		if i > 0 && (len(s)-i)%3 == 0 {
			out = append(out, '.')
		}
		out = append(out, c)
	}
	if neg {
		return "$-" + string(out)
	}
	return "$" + string(out)
}

// consultaPOST es el formulario: verifica contra la base y muestra el resultado.
func (s *Servidor) consultaPOST(w http.ResponseWriter, r *http.Request) {
	if err := r.ParseForm(); err != nil {
		responderError(w, r, 422, "validacion", "Los datos enviados no son válidos.", nil)
		return
	}
	rut, folioTxt, montoTxt := r.PostFormValue("rut_emisor"), r.PostFormValue("folio"), r.PostFormValue("monto_total")
	tipoTxt, fch := r.PostFormValue("tipo_dte"), strings.TrimSpace(r.PostFormValue("fecha_emision"))
	for campo, v := range map[string]string{"rut_emisor": rut, "tipo_dte": tipoTxt, "folio": folioTxt, "monto_total": montoTxt} {
		if _, hay := r.PostForm[campo]; !hay || v == "" && campo != "rut_emisor" && campo != "folio" && campo != "monto_total" {
			responderError(w, r, 422, "validacion", "Los datos enviados no son válidos.", map[string]any{"errores": []map[string]any{{"loc": []any{"body", campo}, "msg": "Field required", "type": "missing"}}})
			return
		}
	}
	tipo, err := strconv.Atoi(strings.TrimSpace(tipoTxt))
	if err != nil {
		responderError(w, r, 422, "validacion", "Los datos enviados no son válidos.", map[string]any{"errores": []map[string]any{{"loc": []any{"body", "tipo_dte"}, "msg": "Input should be a valid integer, unable to parse string as an integer", "type": "int_parsing"}}})
		return
	}
	folio, err1 := strconv.Atoi(strings.TrimSpace(folioTxt))
	monto, err2 := strconv.ParseInt(strings.TrimSpace(strings.ReplaceAll(strings.ReplaceAll(montoTxt, ".", ""), "$", "")), 10, 64)
	if err1 != nil || err2 != nil {
		responderHTML(w, paginaConsulta(`<p class="no" style="margin-top:16px">Folio y monto deben ser números.</p>`, rut, folioTxt, montoTxt, tipo, fch))
		return
	}
	if nombreTipoConsulta(tipo) == "" {
		responderHTML(w, paginaConsulta(`<p class="no" style="margin-top:16px">Tipo de documento no válido.</p>`, rut, folioTxt, montoTxt, 39, fch))
		return
	}
	d, err := s.buscarBoleta(rut, tipo, folio, monto, fch)
	if err != nil {
		responderError(w, r, 500, "error_interno", "Ocurrió un error interno. Reporta el request_id al soporte.", nil)
		return
	}
	if d == nil {
		responderHTML(w, paginaConsulta(`<p class="no" style="margin-top:16px">No se encontró una boleta con esos datos. Verifique el RUT, tipo, folio, fecha y monto.</p>`, rut, folioTxt, montoTxt, tipo, fch))
		return
	}
	recep := texto(d, "rut_receptor")
	if recep == "" {
		recep = "—"
	}
	filas := [][2]string{
		{"Documento", fmt.Sprintf("%s N° %d", nombreTipoConsulta(tipo), int(numero(d["folio"])))},
		{"RUT emisor", texto(d, "rut_emisor")}, {"RUT receptor", recep}, {"Fecha de emisión", texto(d, "fecha_emision")},
		{"Monto neto", dinero(d["monto_neto"])}, {"Monto exento", dinero(d["monto_exento"])}, {"IVA", dinero(d["iva"])}, {"Monto total", dinero(d["monto_total"])},
	}
	var tabla bytes.Buffer
	for _, f := range filas {
		fmt.Fprintf(&tabla, "<tr><td>%s</td><td>%s</td></tr>", html.EscapeString(f[0]), html.EscapeString(f[1]))
	}
	qs := qsConsulta(rut, tipo, folio, monto, fch)
	cuerpo := `<p class="ok" style="margin-top:18px">✓ Boleta encontrada y válida.</p><table>` + tabla.String() + `</table>` +
		`<div class="dl"><a href="/consulta/pdf?` + qs + `">Descargar PDF</a><a href="/consulta/xml?` + qs + `">Descargar XML</a></div>`
	responderHTML(w, paginaConsulta(cuerpo, rut, folioTxt, montoTxt, tipo, fch))
}

// dominioPublico es el middleware de main.py: si el Host es DOMINIO_PUBLICO_BOLETAS, "/" va a
// /consulta y todo lo que no sea /consulta* o /static/* es 404 (Internet entra solo por ahí).
func (s *Servidor) dominioPublico(next http.Handler) http.Handler {
	hostPub := strings.ToLower(strings.TrimSpace(s.cfg.DominioPublicoBoletas))
	if hostPub == "" {
		return next
	}
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		host := strings.ToLower(strings.Split(r.Host, ":")[0])
		if host == hostPub {
			p := r.URL.Path
			if p == "/" {
				http.Redirect(w, r, "/consulta", http.StatusFound)
				return
			}
			if !(p == "/consulta" || strings.HasPrefix(p, "/consulta/") || strings.HasPrefix(p, "/static/")) {
				responderJSON(w, 404, map[string]any{"detail": "No disponible"})
				return
			}
		}
		next.ServeHTTP(w, r)
	})
}
