package servidor

import (
	"html"
	"net/http"
	"regexp"
	"strconv"
	"strings"

	"dtechile/nucleo/firma"
	"dtechile/nucleo/sii"
)

// Estados de envío FINALES (core/seguimiento.py).
var estadosRechazo = map[string]bool{"RCH": true, "RSC": true, "RFR": true, "RCT": true, "RLV": true}

// campoLote es seguimiento._campo: int si es número, texto si no, nil si falta.
func campoLote(texto, tag string) any {
	m := regexp.MustCompile(`<` + tag + `>([^<]*)</` + tag + `>`).FindStringSubmatch(texto)
	if m == nil {
		return nil
	}
	v := strings.TrimSpace(m[1])
	if n, err := strconv.Atoi(v); err == nil {
		return n
	}
	return v
}

// estadoDetallado es seguimiento.estado_detallado: estado de UN envío con el desglose por DTE.
func estadoDetallado(cli *sii.Cliente, track int64, rut, dv string) (map[string]any, error) {
	e, err := cli.EstadoTrack(track, rut, dv)
	if err != nil {
		return nil, err
	}
	des := html.UnescapeString(e.Crudo)
	tieneBody := strings.Contains(des, "<TIPO_DOCTO>")
	return map[string]any{
		"track_id": track, "estado": e.Estado, "glosa": e.Glosa,
		"informados": campoLote(des, "INFORMADOS"), "aceptados": campoLote(des, "ACEPTADOS"),
		"rechazados": campoLote(des, "RECHAZADOS"), "reparos": campoLote(des, "REPAROS"),
		"resuelto": tieneBody || estadosRechazo[e.Estado],
	}, nil
}

// estadoLote es POST /api/v1/estado/lote: varios TrackID con el certificado del keystore y un
// resumen accionable (resueltos/pendientes/aceptados/rechazados). Un envío que falle no
// tumba el lote.
func (s *Servidor) estadoLote(w http.ResponseWriter, r *http.Request) {
	var cuerpo struct {
		TrackIDs   *[]int64 `json:"track_ids"`
		RutEmpresa *string  `json:"rut_empresa"`
		CertID     *int64   `json:"cert_id"`
		Ambiente   string   `json:"ambiente"`
	}
	if !leerJSON(w, r, &cuerpo) {
		return
	}
	if cuerpo.TrackIDs == nil {
		faltan(w, r, "track_ids")
		return
	}
	if cuerpo.RutEmpresa == nil {
		faltan(w, r, "rut_empresa")
		return
	}
	if cuerpo.CertID == nil {
		faltan(w, r, "cert_id")
		return
	}
	if cuerpo.Ambiente == "" {
		cuerpo.Ambiente = "certificacion"
	}
	cuenta, _ := s.cuentaID(w, r)
	p12, clave, err := s.descifrarCertificado(*cuerpo.CertID, cuenta)
	if err != nil {
		responderError(w, r, 404, "no_encontrado", "Certificado "+strconv.FormatInt(*cuerpo.CertID, 10)+" no encontrado", nil)
		return
	}
	cert, err := firma.CargarP12(p12, clave)
	if err != nil {
		responderError(w, r, 422, "certificado", "No se pudo cargar el certificado: "+err.Error(), nil)
		return
	}
	num, dv, _ := strings.Cut(*cuerpo.RutEmpresa, "-")
	cli, err := sii.Nuevo(cuerpo.Ambiente, cert)
	if err != nil {
		responderError(w, r, 422, "validacion", err.Error(), nil)
		return
	}
	detalles := make([]map[string]any, 0, len(*cuerpo.TrackIDs))
	for _, t := range *cuerpo.TrackIDs {
		d, err := estadoDetallado(cli, t, num, dv)
		if err != nil {
			d = map[string]any{"track_id": t, "error": err.Error(), "resuelto": false}
		}
		detalles = append(detalles, d)
	}
	suma := func(campo string) int {
		n := 0
		for _, d := range detalles {
			if v, ok := d[campo].(int); ok {
				n += v
			}
		}
		return n
	}
	resueltos := 0
	for _, d := range detalles {
		if ok, _ := d["resuelto"].(bool); ok {
			resueltos++
		}
	}
	responderJSON(w, 200, map[string]any{"total": len(detalles), "resueltos": resueltos, "pendientes": len(detalles) - resueltos,
		"aceptados": suma("aceptados"), "rechazados": suma("rechazados"), "reparos": suma("reparos"),
		"todos_resueltos": resueltos == len(detalles) && len(detalles) > 0, "detalles": detalles})
}
