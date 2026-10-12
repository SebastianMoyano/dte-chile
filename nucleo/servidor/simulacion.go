package servidor

// /api/v1/simulacion/*: la práctica con EMPRESA DEMO SPA, réplica de api/routes/simulacion.py
// y core/simulacion.py, emitiendo con el núcleo Go (nucleo/emision) y dibujando el PDF con
// nucleo/pdf y la validación XSD con nucleo/xsd. Nada se le pide ya al motor
// Python, con la misma autorización de la petición; sin motor Python, la práctica emite sin XSD.

import (
	"bytes"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	"dtechile/nucleo/emision"
	"dtechile/nucleo/xmlgen"
	"dtechile/nucleo/xsd"
)

func (s *Servidor) rutasSimulacion(mux *http.ServeMux) {
	mux.HandleFunc("GET /api/v1/simulacion/estado", s.protegido(s.simEstado))
	mux.HandleFunc("POST /api/v1/simulacion/emitir", s.protegido(s.simEmitir))
	mux.HandleFunc("POST /api/v1/simulacion/anular/{id}", s.protegido(s.simAnular))
	mux.HandleFunc("GET /api/v1/simulacion/documentos/{id}", s.protegido(s.simVer))
	mux.HandleFunc("POST /api/v1/simulacion/reiniciar", s.protegido(s.simReiniciar))
}

func (s *Servidor) carpetaDemo() string { return filepath.Join(s.cfg.StoragePath, "simulacion") }

// asegurarMundo es asegurar_mundo: carpeta, y un CAF por tipo si falta.
func (s *Servidor) asegurarMundo() error {
	if err := os.MkdirAll(s.carpetaDemo(), 0o755); err != nil {
		return err
	}
	for _, t := range tiposDemo {
		c, err := s.alm.CAFActivo(rutDemo, t)
		if err != nil {
			return err
		}
		if c != nil {
			continue
		}
		xml, err := cafFicticio(t, 1, foliosPorTipo)
		if err != nil {
			return err
		}
		if _, err := s.alm.RegistrarCAF(t, rutDemo, 1, foliosPorTipo, hoyISO(), xml); err != nil {
			return err
		}
	}
	return nil
}

// motorPython hace una llamada interna al motor Python con la autorización de la petición.
func (s *Servidor) motorPython(r *http.Request, metodo, ruta string, cuerpo []byte) (int, []byte, error) {
	if s.cfg.MotorPython == "" {
		return 0, nil, fmt.Errorf("sin motor Python")
	}
	req, err := http.NewRequest(metodo, strings.TrimRight(s.cfg.MotorPython, "/")+ruta, bytes.NewReader(cuerpo))
	if err != nil {
		return 0, nil, err
	}
	req.Header.Set("Authorization", r.Header.Get("Authorization"))
	req.Header.Set("Accept", "application/json")
	if cuerpo != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	resp, err := (&http.Client{Timeout: 120 * time.Second}).Do(req)
	if err != nil {
		return 0, nil, err
	}
	defer resp.Body.Close()
	b, _ := io.ReadAll(resp.Body)
	return resp.StatusCode, b, nil
}

// resultadoDemo es _resultado: la fila del documento más el PDF en base64 si existe.
func (s *Servidor) resultadoDemo(id int64) (map[string]any, error) {
	d, err := s.dtePorID(id)
	if err != nil || d == nil {
		return nil, fmt.Errorf("documento %d no existe", id)
	}
	out := map[string]any{
		"dte_id": d["id"], "tipo_dte": d["tipo_dte"], "folio": d["folio"], "fecha_emision": d["fecha_emision"],
		"receptor": d["rut_receptor"], "razon_social_receptor": d["razon_social_receptor"],
		"monto_neto": d["monto_neto"], "monto_exento": d["monto_exento"], "iva": d["iva"], "monto_total": d["monto_total"],
		"ambiente": d["ambiente"], "estado": d["estado"], "pdf_path": d["pdf_path"], "pdf_b64": nil,
	}
	if pp := s.rutaDesdeBD(texto(d, "pdf_path")); existeArchivo(pp) {
		if b, err := os.ReadFile(pp); err == nil {
			out["pdf_b64"] = base64.StdEncoding.EncodeToString(b)
		}
	}
	return out, nil
}

type itemDemo struct {
	Nombre         *string  `json:"nombre"`
	PrecioUnitario *float64 `json:"precio_unitario"`
	Cantidad       *float64 `json:"cantidad"`
	Exento         bool     `json:"exento"`
}

type receptorDemo struct {
	Rut             *string `json:"rut"`
	RazonSocial     *string `json:"razon_social"`
	Giro            string  `json:"giro"`
	Direccion       string  `json:"direccion"`
	Comuna          string  `json:"comuna"`
	Ciudad          string  `json:"ciudad"`
	EsContribuyente *bool   `json:"es_contribuyente"`
}

// emitirDemo es simulacion.emitir: arma el documento, emite con el núcleo (XSD por Python si
// hay), marca simulado y pide el PDF a Python. Devuelve el id.
func (s *Servidor) emitirDemo(r *http.Request, tipo int, items []itemDemo, receptor *receptorDemo, refs []map[string]any, fecha string) (int64, error) {
	if err := s.asegurarMundo(); err != nil {
		return 0, err
	}
	cert, err := s.certificadoDemo()
	if err != nil {
		return 0, err
	}
	esBoleta := tipo == 39 || tipo == 41
	exentoForzado := tipo == 34 || tipo == 41
	doc := map[string]any{"tipo_dte": tipo, "folio": 0, "fecha_emision": fecha, "emisor": emisorDemo, "forma_pago": 1}
	its := []map[string]any{}
	for i, it := range items {
		nombre := "Venta"
		if it.Nombre != nil && *it.Nombre != "" {
			nombre = *it.Nombre
		}
		if rs := []rune(nombre); len(rs) > 80 {
			nombre = string(rs[:80])
		}
		cant, prc := 1.0, 0.0
		if it.Cantidad != nil && *it.Cantidad != 0 {
			cant = *it.Cantidad
		}
		if it.PrecioUnitario != nil {
			prc = *it.PrecioUnitario
		}
		its = append(its, map[string]any{"numero_linea": i + 1, "nombre": nombre, "cantidad": cant, "precio_unitario": prc, "exento": it.Exento || exentoForzado})
	}
	doc["items"] = its
	switch {
	case receptor != nil:
		doc["receptor"] = map[string]any{"rut": *receptor.Rut, "razon_social": *receptor.RazonSocial, "giro": receptor.Giro,
			"direccion": receptor.Direccion, "comuna": receptor.Comuna, "ciudad": receptor.Ciudad}
	case esBoleta:
		doc["receptor"] = map[string]any{"rut": rutConsumidorFinal, "razon_social": "CONSUMIDOR FINAL"}
	default:
		doc["receptor"] = clienteDemo
	}
	if len(refs) > 0 {
		doc["referencias"] = refs
	}
	raw, _ := json.Marshal(doc)
	d, err := emision.DocumentoDesdeJSON(raw)
	if err != nil {
		return 0, err
	}
	res, err := emision.Emitir(emision.Contexto{Almacen: s.alm, Cert: cert, StorageBase: s.carpetaDemo(), Ambiente: ambienteDemo,
		FechaResolucion: "2026-01-01", NumeroResolucion: 0, Marca: time.Now().Format("2006-01-02T15:04:05"), Validar: xsd.ValidarError}, d)
	if err != nil {
		return 0, err
	}
	s.db.Exec(`UPDATE dtes SET ambiente=?, estado=? WHERE id=?`, ambienteDemo, estadoDemo, res.DTEID)
	// PDF desde el XML firmado, con nucleo/pdf (como el orquestador Python).
	if d, err := s.dtePorID(res.DTEID); err == nil && d != nil {
		if _, err := s.regenerarPDF(d); err != nil {
			s.log("práctica: PDF del documento %d no generado: %v", res.DTEID, err)
		}
	}
	return res.DTEID, nil
}

func (s *Servidor) simEstado(w http.ResponseWriter, r *http.Request) {
	if err := s.asegurarMundo(); err != nil {
		responderError(w, r, 500, "error_interno", "Ocurrió un error interno. Reporta el request_id al soporte.", nil)
		return
	}
	folios := map[string]any{}
	for _, t := range tiposDemo {
		c, _ := s.alm.CAFActivo(rutDemo, t)
		if c != nil {
			folios[strconv.Itoa(t)] = map[string]any{"siguiente": c.FolioSiguiente, "hasta": c.FolioHasta}
		} else {
			folios[strconv.Itoa(t)] = nil
		}
	}
	var n int
	s.db.QueryRow(`SELECT COUNT(*) FROM dtes WHERE rut_emisor=?`, rutDemo).Scan(&n)
	responderJSON(w, 200, map[string]any{"empresa": emisorDemo, "documentos": n, "folios": folios, "ambiente": ambienteDemo})
}

func (s *Servidor) simEmitir(w http.ResponseWriter, r *http.Request) {
	var in struct {
		TipoDTE  *int          `json:"tipo_dte"`
		Items    *[]itemDemo   `json:"items"`
		Receptor *receptorDemo `json:"receptor"`
		Fecha    *string       `json:"fecha"`
	}
	if !leerJSON(w, r, &in) {
		return
	}
	var f []string
	if in.TipoDTE == nil {
		f = append(f, "tipo_dte")
	}
	if in.Items == nil {
		f = append(f, "items")
	}
	if faltan(w, r, f...) {
		return
	}
	for _, it := range *in.Items {
		if it.Nombre == nil || it.PrecioUnitario == nil || *it.PrecioUnitario < 0 || (it.Cantidad != nil && *it.Cantidad < 0) || len([]rune(*it.Nombre)) > 80 {
			responderError(w, r, 422, "validacion", "Los datos enviados no son válidos.", map[string]any{"errores": []map[string]any{{"loc": []any{"body", "items"}, "msg": "ítem inválido", "type": "value_error"}}})
			return
		}
	}
	if in.Receptor != nil && (in.Receptor.Rut == nil || in.Receptor.RazonSocial == nil) {
		responderError(w, r, 422, "validacion", "Los datos enviados no son válidos.", map[string]any{"errores": []map[string]any{{"loc": []any{"body", "receptor"}, "msg": "Field required", "type": "missing"}}})
		return
	}
	esDemo := false
	for _, t := range tiposDemo {
		if t == *in.TipoDTE {
			esDemo = true
		}
	}
	if !esDemo {
		responderError(w, r, 422, "validacion", "La simulación solo emite tipos (33, 34, 39, 41, 56, 61)", map[string]any{"tipo_dte": *in.TipoDTE})
		return
	}
	if len(*in.Items) == 0 {
		responderError(w, r, 422, "validacion", "Hace falta al menos un ítem", nil)
		return
	}
	fecha := hoyISO()
	if in.Fecha != nil && *in.Fecha != "" {
		if !fechaValida(*in.Fecha) {
			responderError(w, r, 422, "validacion", "Los datos enviados no son válidos.", map[string]any{"errores": []map[string]any{{"loc": []any{"body", "fecha"}, "msg": "fecha inválida", "type": "date_parsing"}}})
			return
		}
		fecha = *in.Fecha
	}
	id, err := s.emitirDemo(r, *in.TipoDTE, *in.Items, in.Receptor, nil, fecha)
	if err != nil {
		responderError(w, r, 422, "validacion", err.Error(), nil)
		return
	}
	out, err := s.resultadoDemo(id)
	if err != nil {
		responderError(w, r, 500, "error_interno", "Ocurrió un error interno. Reporta el request_id al soporte.", nil)
		return
	}
	responderJSON(w, 200, out)
}

func (s *Servidor) simAnular(w http.ResponseWriter, r *http.Request) {
	id, err := strconv.ParseInt(r.PathValue("id"), 10, 64)
	if err != nil {
		responderError(w, r, 422, "validacion", "Los datos enviados no son válidos.", nil)
		return
	}
	motivo := "Anula documento"
	if r.ContentLength != 0 {
		var in struct {
			Motivo *string `json:"motivo"`
		}
		if !leerJSON(w, r, &in) {
			return
		}
		if in.Motivo != nil {
			if len([]rune(*in.Motivo)) > 90 {
				responderError(w, r, 422, "validacion", "Los datos enviados no son válidos.", nil)
				return
			}
			motivo = *in.Motivo
		}
	}
	d, err := s.dtePorID(id)
	if err != nil {
		responderError(w, r, 500, "error_interno", "Ocurrió un error interno. Reporta el request_id al soporte.", nil)
		return
	}
	if d == nil || texto(d, "rut_emisor") != rutDemo || texto(d, "ambiente") != ambienteDemo {
		responderError(w, r, 404, "no_encontrado", "Ese documento no es de la simulación", nil)
		return
	}
	tipo := int(numero(d["tipo_dte"]))
	if tipo == 56 || tipo == 61 {
		responderError(w, r, 422, "validacion", "Una nota de crédito o débito no se anula con otra nota de crédito en este curso", nil)
		return
	}
	if texto(d, "estado") == "anulado_simulado" {
		responderError(w, r, 422, "validacion", "Ese documento ya fue anulado", nil)
		return
	}
	nombre := nombreTipo(tipo)
	folio := int(numero(d["folio"]))
	var items []itemDemo
	if neto := numero(d["monto_neto"]); neto != 0 {
		n, p := fmt.Sprintf("Anula %s folio %d", nombre, folio), float64(neto)
		items = append(items, itemDemo{Nombre: &n, PrecioUnitario: &p})
	}
	if ex := numero(d["monto_exento"]); ex != 0 {
		n, p := fmt.Sprintf("Anula %s folio %d (exento)", nombre, folio), float64(ex)
		items = append(items, itemDemo{Nombre: &n, PrecioUnitario: &p, Exento: true})
	}
	rutRec := texto(d, "rut_receptor")
	razon := texto(d, "razon_social_receptor")
	if razon == "" {
		razon = "CONSUMIDOR FINAL"
	}
	rec := &receptorDemo{Rut: &rutRec, RazonSocial: &razon}
	if rs := []rune(motivo); len(rs) > 90 {
		motivo = string(rs[:90])
	}
	refs := []map[string]any{{"numero_linea": 1, "tipo_doc_ref": tipo, "folio_ref": folio,
		"fecha_doc_ref": texto(d, "fecha_emision")[:10], "codigo_ref": 1, "razon_ref": motivo}}
	ncID, err := s.emitirDemo(r, 61, items, rec, refs, hoyISO())
	if err != nil {
		responderError(w, r, 422, "validacion", err.Error(), nil)
		return
	}
	s.db.Exec(`UPDATE dtes SET estado='anulado_simulado' WHERE id=?`, id)
	out, _ := s.resultadoDemo(ncID)
	responderJSON(w, 200, out)
}

func (s *Servidor) simVer(w http.ResponseWriter, r *http.Request) {
	id, err := strconv.ParseInt(r.PathValue("id"), 10, 64)
	if err != nil {
		responderError(w, r, 422, "validacion", "Los datos enviados no son válidos.", nil)
		return
	}
	d, _ := s.dtePorID(id)
	if d == nil || texto(d, "rut_emisor") != rutDemo {
		responderError(w, r, 404, "no_encontrado", "Ese documento no es de la simulación", nil)
		return
	}
	out, _ := s.resultadoDemo(id)
	responderJSON(w, 200, out)
}

func (s *Servidor) simReiniciar(w http.ResponseWriter, r *http.Request) {
	ra, _ := s.db.Exec(`DELETE FROM dtes WHERE rut_emisor=?`, rutDemo)
	rb, _ := s.db.Exec(`DELETE FROM cafs WHERE rut_emisor=?`, rutDemo)
	a, _ := ra.RowsAffected()
	b, _ := rb.RowsAffected()
	os.RemoveAll(s.carpetaDemo())
	if err := s.asegurarMundo(); err != nil {
		responderError(w, r, 500, "error_interno", "Ocurrió un error interno. Reporta el request_id al soporte.", nil)
		return
	}
	responderJSON(w, 200, map[string]any{"documentos_borrados": a, "cafs_borrados": b})
}

func numero(v any) int64 {
	switch x := v.(type) {
	case int64:
		return x
	case int:
		return int64(x)
	case float64:
		return int64(x)
	case string:
		n, _ := strconv.ParseInt(x, 10, 64)
		return n
	}
	return 0
}

func nombreTipo(t int) string {
	switch t {
	case 33:
		return "factura"
	case 34:
		return "factura exenta"
	case 39:
		return "boleta"
	case 41:
		return "boleta exenta"
	case 52:
		return "guía"
	case 56:
		return "nota de débito"
	case 61:
		return "nota de crédito"
	}
	return fmt.Sprintf("tipo %d", t)
}

var _ xmlgen.Documento
