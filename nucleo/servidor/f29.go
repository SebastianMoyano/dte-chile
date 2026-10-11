package servidor

import (
	"net/http"
	"strconv"

	"dtechile/nucleo/portal"
	"dtechile/nucleo/rcv"
)

// f29Negocio es GET /api/v1/keystore/negocios/{id}/f29?periodo=YYYYMM&ppm=&remanente_anterior=:
// baja el RCV del período desde PRODUCCIÓN con la sesión del certificado del negocio, agrega y
// mapea a los casilleros del F29. Solo lectura: NO declara nada al SII.
func (s *Servidor) f29Negocio(w http.ResponseWriter, r *http.Request) {
	q := r.URL.Query()
	periodo := q.Get("periodo")
	if periodo == "" {
		errorQuery(w, r, "periodo", "Field required", "missing")
		return
	}
	ppm, ok := enteroQuery(w, r, "ppm", 0, -1<<62, 0)
	if !ok {
		return
	}
	rem, ok := enteroQuery(w, r, "remanente_anterior", 0, -1<<62, 0)
	if !ok {
		return
	}
	neg, cuenta, ok := s.negocioO404(w, r)
	if !ok {
		return
	}
	p, err := s.portalDelNegocio(neg, cuenta, portal.BaseProduccion)
	if err != nil {
		responderError(w, r, 502, "sii_comunicacion", "No se pudo bajar el RCV del SII: "+err.Error(), nil)
		return
	}
	cli := rcv.Nuevo(p.Cookies["TOKEN"], nil)
	sync, err := cli.SincronizarPeriodo(s.db, neg.Rut, periodo)
	if err != nil {
		responderError(w, r, 502, "sii_comunicacion", "No se pudo bajar el RCV del SII: "+err.Error(), nil)
		return
	}
	d, err := rcv.CalcularDesglose(s.db, neg.Rut, periodo, int64(ppm), int64(rem))
	if err != nil {
		responderError(w, r, 500, "error_interno", "Ocurrió un error interno. Reporta el request_id al soporte.", nil)
		return
	}
	lineas := rcv.MapearAF29(d)
	cas := make([]map[string]any, 0, len(lineas))
	for _, l := range lineas {
		cas = append(cas, map[string]any{"codigo": l.Codigo, "glosa": l.Glosa, "valor": l.Valor})
	}
	responderJSON(w, 200, map[string]any{
		"rut": neg.Rut, "razon_social": neg.RazonSocial.valor(), "periodo": periodo, "documentos": sync,
		"sin_datos": sync["compras"]+sync["ventas"] == 0, "ppm": ppm, "remanente_anterior": rem,
		"total_debitos": d.TotalDebitos, "total_creditos": d.TotalCreditos, "iva_determinado": d.IVADeterminado(),
		"remanente_siguiente": d.RemanenteSiguiente(), "total_a_pagar": d.TotalAPagar(), "casilleros": cas,
	})
}

var _ = strconv.Itoa
