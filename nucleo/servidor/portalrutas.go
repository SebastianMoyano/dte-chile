package servidor

import (
	"encoding/base64"
	"fmt"
	"net/http"

	"dtechile/nucleo/portal"
	"dtechile/nucleo/sii"
	"dtechile/nucleo/xsd"
)

// Rutas solo-Go del portal con el certificado del keystore (lo que el MCP de Python hacía
// con core/ directamente): timbrajes, situación, software, empresas del certificado,
// anulables, anular y solicitar folios. Todas POST con JSON {cert_id, rut, …, ambiente}.
func (s *Servidor) rutasPortalKeystore(mux *http.ServeMux) {
	mux.HandleFunc("POST /api/v1/portal/timbrajes", s.protegido(s.portalTimbrajes))
	mux.HandleFunc("POST /api/v1/portal/situacion", s.protegido(s.portalSituacion))
	mux.HandleFunc("POST /api/v1/portal/software", s.protegido(s.portalSoftware))
	mux.HandleFunc("POST /api/v1/portal/empresas", s.protegido(s.portalEmpresas))
	mux.HandleFunc("POST /api/v1/portal/anulables", s.protegido(s.portalAnulables))
	mux.HandleFunc("POST /api/v1/portal/anular", s.protegido(s.portalAnular))
	mux.HandleFunc("POST /api/v1/portal/solicitar", s.protegido(s.portalSolicitar))
	mux.HandleFunc("POST /api/v1/dte/enviar-keystore", s.protegido(s.enviarDTEKeystore))
}

type portalIn struct {
	CertID     *int64 `json:"cert_id"`
	Rut        string `json:"rut"`
	TipoDTE    int    `json:"tipo_dte"`
	Tipos      []int  `json:"tipos"`
	Ambiente   string `json:"ambiente"`
	FolioDesde int    `json:"folio_desde"`
	FolioHasta int    `json:"folio_hasta"`
	Motivo     string `json:"motivo"`
	Cantidad   int    `json:"cantidad"`
	Forzar     bool   `json:"forzar"`
}

// portalAbierto lee el cuerpo, saca el certificado del keystore y abre sesión en el portal.
func (s *Servidor) portalAbierto(w http.ResponseWriter, r *http.Request, exigeRut bool) (*portalIn, *portal.Cliente, bool) {
	var in portalIn
	if !leerJSON(w, r, &in) {
		return nil, nil, false
	}
	if in.CertID == nil {
		faltan(w, r, "cert_id")
		return nil, nil, false
	}
	if exigeRut && in.Rut == "" {
		faltan(w, r, "rut")
		return nil, nil, false
	}
	if in.Ambiente == "" {
		in.Ambiente = s.cfg.SIIAmbiente
	}
	cuenta, _ := s.cuentaID(w, r)
	certPEM, keyPEM, err := s.pemDeCertificado(*in.CertID, cuenta)
	if err != nil {
		responderError(w, r, 404, "no_encontrado", err.Error(), nil)
		return nil, nil, false
	}
	p, err := portal.Nuevo(certPEM, keyPEM, portal.BaseDe(in.Ambiente))
	if err == nil {
		_, err = p.Autenticar("")
	}
	if err != nil {
		responderError(w, r, 502, "sii_comunicacion", "No se pudo abrir sesión en el SII: "+err.Error(), nil)
		return nil, nil, false
	}
	return &in, p, true
}

func responderPortal(w http.ResponseWriter, r *http.Request, v any, err error) {
	if err != nil {
		responderError(w, r, 502, "sii_comunicacion", "No se pudo consultar el SII: "+err.Error(), nil)
		return
	}
	responderJSON(w, 200, v)
}

func (s *Servidor) portalTimbrajes(w http.ResponseWriter, r *http.Request) {
	in, p, ok := s.portalAbierto(w, r, true)
	if !ok {
		return
	}
	v, err := p.ConsultarTimbrajes(in.Rut, in.TipoDTE)
	responderPortal(w, r, v, err)
}

func (s *Servidor) portalSituacion(w http.ResponseWriter, r *http.Request) {
	in, p, ok := s.portalAbierto(w, r, true)
	if !ok {
		return
	}
	v, err := p.SituacionFolios(in.Rut, in.Tipos)
	responderPortal(w, r, v, err)
}

func (s *Servidor) portalSoftware(w http.ResponseWriter, r *http.Request) {
	in, p, ok := s.portalAbierto(w, r, true)
	if !ok {
		return
	}
	v, err := p.DatosSoftwareDe(in.Rut, portal.BaseDe(in.Ambiente))
	responderPortal(w, r, v, err)
}

func (s *Servidor) portalEmpresas(w http.ResponseWriter, r *http.Request) {
	_, p, ok := s.portalAbierto(w, r, false)
	if !ok {
		return
	}
	v, err := p.EmpresasAsociadas()
	responderPortal(w, r, v, err)
}

func (s *Servidor) portalAnulables(w http.ResponseWriter, r *http.Request) {
	in, p, ok := s.portalAbierto(w, r, true)
	if !ok {
		return
	}
	v, err := p.ListarAnulables(in.Rut, in.TipoDTE)
	responderPortal(w, r, v, err)
}

// portalAnular: ACCIÓN REAL E IRREVERSIBLE sobre folios no recepcionados.
func (s *Servidor) portalAnular(w http.ResponseWriter, r *http.Request) {
	in, p, ok := s.portalAbierto(w, r, true)
	if !ok {
		return
	}
	if in.FolioDesde == 0 || in.FolioHasta == 0 {
		faltan(w, r, "folio_desde", "folio_hasta")
		return
	}
	v, err := p.AnularFolios(in.Rut, in.TipoDTE, in.FolioDesde, in.FolioHasta, in.Motivo)
	responderPortal(w, r, v, err)
}

// portalSolicitar: TIMBRA folios (consume cupo). Devuelve {obtenido, info, caf_xml}.
func (s *Servidor) portalSolicitar(w http.ResponseWriter, r *http.Request) {
	in, p, ok := s.portalAbierto(w, r, true)
	if !ok {
		return
	}
	caf, info, err := p.SolicitarFolios(in.Rut, in.TipoDTE, in.Cantidad, true, in.Forzar)
	if err != nil {
		responderError(w, r, 502, "sii_comunicacion", "No se pudo consultar el SII: "+err.Error(), nil)
		return
	}
	var cafXML any
	if caf != nil {
		cafXML = string(caf)
	}
	responderJSON(w, 200, map[string]any{"obtenido": caf != nil, "info": info, "caf_xml": cafXML})
}

// enviarDTEKeystore es /dte/enviar con el certificado del keystore (cert_id) en vez del .p12.
func (s *Servidor) enviarDTEKeystore(w http.ResponseWriter, r *http.Request) {
	var in struct {
		XMLB64     *string `json:"xml_envio_b64"`
		RutEmpresa *string `json:"rut_empresa"`
		CertID     *int64  `json:"cert_id"`
		TipoDTE    int     `json:"tipo_dte"`
		Ambiente   string  `json:"ambiente"`
	}
	if !leerJSON(w, r, &in) {
		return
	}
	if in.XMLB64 == nil || in.RutEmpresa == nil || in.CertID == nil {
		var f []string
		for k, v := range map[string]bool{"xml_envio_b64": in.XMLB64 == nil, "rut_empresa": in.RutEmpresa == nil, "cert_id": in.CertID == nil} {
			if v {
				f = append(f, k)
			}
		}
		faltan(w, r, f...)
		return
	}
	if in.Ambiente == "" {
		in.Ambiente = s.cfg.SIIAmbiente
	}
	cuenta, _ := s.cuentaID(w, r)
	cert, err := s.CertificadoDelKeystore(*in.CertID, cuenta)
	if err != nil {
		responderError(w, r, 404, "no_encontrado", err.Error(), nil)
		return
	}
	xml, err := base64.StdEncoding.DecodeString(*in.XMLB64)
	if err != nil {
		responderError(w, r, 422, "validacion", "xml_envio_b64 no es base64 válido: "+err.Error(), nil)
		return
	}
	if err := xsd.ValidarError(xml); err != nil {
		responderError(w, r, 422, "validacion", "El XML no cumple el esquema XSD del SII: "+err.Error(), nil)
		return
	}
	num, dv := portal.SepararRut(*in.RutEmpresa)
	if in.TipoDTE == 39 || in.TipoDTE == 41 {
		cli, err := sii.NuevoBoleta(in.Ambiente, cert)
		if err != nil {
			responderError(w, r, 422, "validacion", err.Error(), nil)
			return
		}
		track, _, err := cli.Enviar(xml, num, dv)
		if err != nil {
			responderError(w, r, 502, "sii_comunicacion", err.Error(), nil)
			return
		}
		s.marcarEnviadosPorXML(xml, track, in.Ambiente)
		responderJSON(w, 200, map[string]any{"track_id": track, "mensaje": "Envío de boletas recibido. TrackID: " + track, "ambiente": in.Ambiente})
		return
	}
	cli, err := sii.Nuevo(in.Ambiente, cert)
	if err != nil {
		responderError(w, r, 422, "validacion", err.Error(), nil)
		return
	}
	track, _, err := cli.EnviarDTE(xml, num, dv)
	if err != nil {
		responderError(w, r, 502, "sii_comunicacion", "Error de comunicación con el SII: "+err.Error(), nil)
		return
	}
	s.marcarEnviadosPorXML(xml, fmt.Sprint(track), in.Ambiente)
	responderJSON(w, 200, map[string]any{"track_id": track, "mensaje": fmt.Sprintf("Envío exitoso. TrackID: %d", track), "ambiente": in.Ambiente})
}
