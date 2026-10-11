package servidor

import (
	"fmt"
	"net/http"
	"sort"
	"time"
)

// core/monitoreo.py — salud LOCAL de los CAF (sin tocar el SII): CAF vencidos (regla CAF-3-517,
// 6 meses desde la autorización) y folios agotándose.
const reglaMesesCAF = 6

func (s *Servidor) rutasMonitoreo(mux *http.ServeMux) {
	mux.HandleFunc("GET /api/v1/monitoreo/folios", s.protegido(s.monitoreoFolios))
	mux.HandleFunc("GET /api/v1/monitoreo/folios/cartera", s.protegido(s.monitoreoCartera))
}

func meses(desde, hoy time.Time) int {
	return (hoy.Year()-desde.Year())*12 + int(hoy.Month()) - int(desde.Month())
}

// saludCAF es salud_caf: un item por CAF activo con estado ok|por_vencer|vencido|bajo|agotado.
func (s *Servidor) saludCAF(rut string, hoy time.Time) ([]map[string]any, error) {
	rows, err := s.db.Query(`SELECT tipo_dte, folio_desde, folio_hasta, COALESCE(folio_siguiente,0), COALESCE(fecha_autorizacion,'') FROM cafs WHERE rut_emisor=? AND activo=1 ORDER BY tipo_dte, folio_desde`, rut)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []map[string]any{}
	for rows.Next() {
		var tipo, desde, hasta, sig int
		var faTxt string
		if err := rows.Scan(&tipo, &desde, &hasta, &sig, &faTxt); err != nil {
			return nil, err
		}
		fa := hoy
		if len(faTxt) >= 10 {
			if t, err := time.Parse("2006-01-02", faTxt[:10]); err == nil {
				fa = t
			}
		}
		m := meses(fa, hoy)
		if sig == 0 {
			sig = desde
		}
		restantes := hasta - sig + 1
		if restantes < 0 {
			restantes = 0
		}
		total := hasta - desde + 1
		umbralBajo := total / 10
		if umbralBajo < 3 {
			umbralBajo = 3
		}
		var estado, detalle string
		switch {
		case m >= reglaMesesCAF:
			estado = "vencido"
			detalle = fmt.Sprintf("CAF de hace %d meses (máx %d por el SII). No se puede usar; timbra folios nuevos.", m, reglaMesesCAF)
		case restantes == 0:
			estado, detalle = "agotado", "Sin folios disponibles en este CAF."
		case restantes <= umbralBajo:
			estado = "bajo"
			detalle = fmt.Sprintf("Quedan %d de %d folios — pide más pronto.", restantes, total)
		case m >= reglaMesesCAF-1:
			estado = "por_vencer"
			detalle = fmt.Sprintf("Vence este mes (tiene %d meses). Usa estos folios ya.", m)
		default:
			estado, detalle = "ok", fmt.Sprintf("%d de %d folios disponibles.", restantes, total)
		}
		out = append(out, map[string]any{"tipo_dte": tipo, "rango": []int{desde, hasta}, "folio_siguiente": sig, "restantes": restantes,
			"total": total, "fecha_autorizacion": fa.Format("2006-01-02"), "meses": m, "estado": estado, "detalle": detalle})
	}
	return out, rows.Err()
}

func (s *Servidor) resumenSalud(rut string, hoy time.Time) (map[string]any, error) {
	cafs, err := s.saludCAF(rut, hoy)
	if err != nil {
		return nil, err
	}
	porEstado := map[string]int{}
	for _, c := range cafs {
		porEstado[c["estado"].(string)]++
	}
	critico := porEstado["vencido"] + porEstado["agotado"]
	atencion := porEstado["bajo"] + porEstado["por_vencer"]
	verdict := "ok"
	if critico > 0 {
		verdict = "critico"
	} else if atencion > 0 {
		verdict = "atencion"
	}
	return map[string]any{"rut": rut, "total_cafs": len(cafs), "por_estado": porEstado, "verdict": verdict, "cafs": cafs}, nil
}

func (s *Servidor) monitoreoFolios(w http.ResponseWriter, r *http.Request) {
	rut := r.URL.Query().Get("rut")
	if rut == "" {
		errorQuery(w, r, "rut", "Field required", "missing")
		return
	}
	res, err := s.resumenSalud(rut, time.Now())
	if err != nil {
		responderError(w, r, 500, "error_interno", "Ocurrió un error interno. Reporta el request_id al soporte.", nil)
		return
	}
	responderJSON(w, 200, res)
}

// monitoreoCartera es salud_cartera: todas las empresas con CAF activo, ordenadas por urgencia.
func (s *Servidor) monitoreoCartera(w http.ResponseWriter, r *http.Request) {
	rows, err := s.db.Query(`SELECT DISTINCT rut_emisor FROM cafs WHERE activo=1 ORDER BY rut_emisor`)
	if err != nil {
		responderError(w, r, 500, "error_interno", "Ocurrió un error interno. Reporta el request_id al soporte.", nil)
		return
	}
	var ruts []string
	for rows.Next() {
		var x string
		if rows.Scan(&x) == nil {
			ruts = append(ruts, x)
		}
	}
	rows.Close()
	hoy := time.Now()
	empresas := make([]map[string]any, 0, len(ruts))
	for _, rut := range ruts {
		e, err := s.resumenSalud(rut, hoy)
		if err == nil {
			empresas = append(empresas, e)
		}
	}
	orden := map[string]int{"critico": 0, "atencion": 1, "ok": 2}
	sort.SliceStable(empresas, func(i, j int) bool {
		return orden[empresas[i]["verdict"].(string)] < orden[empresas[j]["verdict"].(string)]
	})
	atencion := []string{}
	for _, e := range empresas {
		if e["verdict"] != "ok" {
			atencion = append(atencion, e["rut"].(string))
		}
	}
	responderJSON(w, 200, map[string]any{"total_empresas": len(empresas), "requieren_atencion": atencion, "empresas": empresas})
}
