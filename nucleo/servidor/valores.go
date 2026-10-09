package servidor

// Rutas /api/v1/valores*, réplica de api/routes/valores.py (solo lectura de la tabla `valores`,
// que llena nucleo/valores). Mismos JSON, mismos códigos: contrato dorado con tools/contrato_api.py.

import (
	"database/sql"
	"fmt"
	"net/http"
	"strconv"
	"time"
)

var indicadores = []string{"uf", "utm", "dolar"}

func esIndicador(s string) bool {
	for _, i := range indicadores {
		if i == s {
			return true
		}
	}
	return false
}

func fechaValida(f string) bool {
	_, err := time.Parse("2006-01-02", f)
	return err == nil
}

func hoyISO() string { return time.Now().Format("2006-01-02") }

// vigente es _vigente: último valor en o antes de la fecha; la UTM del mismo mes no es rezago.
func (s *Servidor) vigente(indicador, fecha string) (map[string]any, error) {
	var ind, f string
	var valor float64
	var act string
	err := s.db.QueryRow(`SELECT indicador, fecha, valor, actualizado FROM valores WHERE indicador=? AND fecha<=? ORDER BY fecha DESC LIMIT 1`,
		indicador, fecha).Scan(&ind, &f, &valor, &act)
	if err == sql.ErrNoRows {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	a, _ := time.Parse("2006-01-02", fecha)
	b, _ := time.Parse("2006-01-02", f)
	rezago := int(a.Sub(b).Hours() / 24)
	if indicador == "utm" && fecha[:7] == f[:7] {
		rezago = 0
	}
	return map[string]any{"indicador": indicador, "fecha": fecha, "valor": valor, "fecha_valor": f, "actualizado": act, "rezago_dias": rezago}, nil
}

func (s *Servidor) rutasValores(mux *http.ServeMux) {
	mux.HandleFunc("GET /api/v1/valores", s.protegido(s.valoresVigentes))
	mux.HandleFunc("GET /api/v1/valores/{$}", s.protegido(s.valoresVigentes))
	mux.HandleFunc("GET /api/v1/valores/historico", s.protegido(s.valoresHistorico))
	mux.HandleFunc("GET /api/v1/valores/{indicador}/serie", s.protegido(s.valoresSerie))
	mux.HandleFunc("GET /api/v1/valores/{indicador}", s.protegido(s.valorVigente))
}

func (s *Servidor) valoresVigentes(w http.ResponseWriter, r *http.Request) {
	f := r.URL.Query().Get("fecha")
	if f == "" {
		f = hoyISO()
	}
	if !fechaValida(f) {
		responderError(w, r, 422, "validacion", "Fecha inválida: "+f, nil)
		return
	}
	out := map[string]any{"fecha": f}
	alguno := false
	for _, k := range indicadores {
		v, err := s.vigente(k, f)
		if err != nil {
			responderError(w, r, 500, "error_interno", "Ocurrió un error interno. Reporta el request_id al soporte.", nil)
			return
		}
		if v != nil {
			alguno = true
			out[k] = v
		} else {
			out[k] = nil
		}
	}
	if !alguno {
		responderError(w, r, 404, "no_encontrado", "No hay indicadores cacheados: corre `nucleo-valores actualizar` (o abre la app)", nil)
		return
	}
	responderJSON(w, 200, out)
}

func (s *Servidor) valoresHistorico(w http.ResponseWriter, r *http.Request) {
	anioTxt := r.URL.Query().Get("anio")
	anio, err := strconv.Atoi(anioTxt)
	if anioTxt == "" || err != nil || anio < 2000 || anio > 2100 {
		responderError(w, r, 422, "validacion", "Los datos enviados no son válidos.",
			map[string]any{"errores": []map[string]any{{"loc": []any{"query", "anio"}, "msg": "anio inválido", "type": "value_error"}}})
		return
	}
	meses := make([]map[string]any, 0, 12)
	for m := 1; m <= 12; m++ {
		f := fmt.Sprintf("%04d-%02d-01", anio, m)
		fila := map[string]any{"mes": f[:7]}
		for _, k := range indicadores {
			v, err := s.vigente(k, f)
			if err != nil {
				responderError(w, r, 500, "error_interno", "Ocurrió un error interno. Reporta el request_id al soporte.", nil)
				return
			}
			if v != nil && v["rezago_dias"].(int) <= 7 {
				fila[k] = v["valor"]
			} else {
				fila[k] = nil
			}
		}
		for _, k := range []string{"uf", "dolar"} {
			var valor float64
			var fecha string
			err := s.db.QueryRow(`SELECT valor, fecha FROM valores WHERE indicador=? AND fecha LIKE ? ORDER BY fecha DESC LIMIT 1`, k, f[:7]+"%").Scan(&valor, &fecha)
			if err == nil {
				fila[k+"_fin"] = valor
			} else {
				fila[k+"_fin"] = nil
			}
		}
		meses = append(meses, fila)
	}
	anios := []string{}
	rows, err := s.db.Query(`SELECT DISTINCT substr(fecha,1,4) AS a FROM valores ORDER BY a`)
	if err == nil {
		for rows.Next() {
			var a string
			rows.Scan(&a)
			anios = append(anios, a)
		}
		rows.Close()
	}
	responderJSON(w, 200, map[string]any{"anio": anio, "meses": meses, "anios_disponibles": anios})
}

func (s *Servidor) valoresSerie(w http.ResponseWriter, r *http.Request) {
	ind := r.PathValue("indicador")
	desde, hasta := r.URL.Query().Get("desde"), r.URL.Query().Get("hasta")
	if desde == "" || hasta == "" {
		faltan := []map[string]any{}
		for _, k := range []string{"desde", "hasta"} {
			if r.URL.Query().Get(k) == "" {
				faltan = append(faltan, map[string]any{"loc": []any{"query", k}, "msg": "Field required", "type": "missing"})
			}
		}
		responderError(w, r, 422, "validacion", "Los datos enviados no son válidos.", map[string]any{"errores": faltan})
		return
	}
	if !esIndicador(ind) {
		responderError(w, r, 422, "validacion", "Indicador desconocido: "+ind, nil)
		return
	}
	serie := []map[string]any{}
	rows, err := s.db.Query(`SELECT fecha, valor FROM valores WHERE indicador=? AND fecha BETWEEN ? AND ? ORDER BY fecha`, ind, desde, hasta)
	if err != nil {
		responderError(w, r, 500, "error_interno", "Ocurrió un error interno. Reporta el request_id al soporte.", nil)
		return
	}
	defer rows.Close()
	for rows.Next() {
		var f string
		var v float64
		rows.Scan(&f, &v)
		serie = append(serie, map[string]any{"fecha": f, "valor": v})
	}
	responderJSON(w, 200, map[string]any{"indicador": ind, "desde": desde, "hasta": hasta, "serie": serie})
}

func (s *Servidor) valorVigente(w http.ResponseWriter, r *http.Request) {
	ind := r.PathValue("indicador")
	if !esIndicador(ind) {
		responderError(w, r, 422, "validacion", "Indicador desconocido: "+ind+" (uf | utm | dolar)", nil)
		return
	}
	f := r.URL.Query().Get("fecha")
	if f == "" {
		f = hoyISO()
	}
	if !fechaValida(f) {
		responderError(w, r, 422, "validacion", "Fecha inválida: "+f, nil)
		return
	}
	v, err := s.vigente(ind, f)
	if err != nil {
		responderError(w, r, 500, "error_interno", "Ocurrió un error interno. Reporta el request_id al soporte.", nil)
		return
	}
	if v == nil {
		responderError(w, r, 404, "no_encontrado", fmt.Sprintf("Sin %s cacheado en o antes de %s", ind, f), nil)
		return
	}
	responderJSON(w, 200, v)
}
