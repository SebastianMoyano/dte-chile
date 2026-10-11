package servidor

import (
	"encoding/json"
	"errors"
	"net/http"
	"regexp"
	"time"

	"dtechile/nucleo/siiengine"
)

// Rutas de api/routes/mipyme.py con nucleo/siiengine: entrar al portal MIPYME (PRODUCCIÓN,
// sin sandbox), leer el formulario y el menú, listar el historial e importarlo a `dtes`.
// Solo lectura: nada de esto emite ni gasta folio.
func (s *Servidor) rutasMipyme(mux *http.ServeMux) {
	mux.HandleFunc("POST /api/v1/mipyme/diagnostico", s.protegido(s.mipymeDiagnostico))
	mux.HandleFunc("POST /api/v1/mipyme/importar", s.protegido(s.mipymeImportar))
	mux.HandleFunc("POST /api/v1/mipyme/sincronizar", s.protegido(s.mipymeSincronizar))
}

var receptorPrueba = siiengine.Receptor{Rut: "11111111-1", RazonSocial: "PRUEBA", Giro: "PRUEBA", Direccion: "-", Ciudad: "-", Comuna: "-"}

type mipymeIn struct {
	RutEmpresa       *string `json:"rut_empresa"`
	RutUsuario       string  `json:"rut_usuario"`
	ClaveTributaria  string  `json:"clave_tributaria"`
	Recordar         bool    `json:"recordar"`
	ClaveCertificado string  `json:"clave_certificado"`
	ConXML           bool    `json:"con_xml"`
	Desde            string  `json:"desde"`
	Hasta            string  `json:"hasta"`
	ConPDF           *bool   `json:"con_pdf"`
}

// resolverClaves es _resolver_claves: lo que viene en el cuerpo manda; lo que falta se toma del
// keystore (cifrado); con `recordar` se guarda lo que vino. Nada se registra en logs.
func (s *Servidor) resolverClaves(w http.ResponseWriter, r *http.Request, d *mipymeIn) bool {
	cuenta, _ := s.cuentaID(w, r)
	if d.Recordar && (d.ClaveTributaria != "" || d.ClaveCertificado != "" || d.RutUsuario != "") {
		if err := s.guardarClaves(cuenta, *d.RutEmpresa, d.RutUsuario, d.ClaveTributaria, d.ClaveCertificado); err != nil {
			responderError(w, r, 500, "error_interno", "Ocurrió un error interno. Reporta el request_id al soporte.", nil)
			return false
		}
	}
	usuario, trib, cert := s.clavesGuardadas(cuenta, *d.RutEmpresa)
	if d.RutUsuario == "" {
		d.RutUsuario = usuario
	}
	if d.ClaveTributaria == "" {
		d.ClaveTributaria = trib
	}
	if d.ClaveCertificado == "" {
		d.ClaveCertificado = cert
	}
	if d.RutUsuario == "" || d.ClaveTributaria == "" {
		faltanCampos := []string{}
		if d.RutUsuario == "" {
			faltanCampos = append(faltanCampos, "rut_usuario")
		}
		if d.ClaveTributaria == "" {
			faltanCampos = append(faltanCampos, "clave_tributaria")
		}
		responderError(w, r, 422, "validacion", "Faltan el RUT de la persona autorizada y/o su clave tributaria (no vienen en la petición ni están recordadas para esta empresa)",
			map[string]any{"rut_empresa": *d.RutEmpresa, "faltan": faltanCampos})
		return false
	}
	return true
}

// clavesGuardadas descifra las claves del SII recordadas para (cuenta, empresa).
func (s *Servidor) clavesGuardadas(cuenta int64, rut string) (usuario, tributaria, certificado string) {
	var u nullString
	var trib, cert []byte
	s.db.QueryRow(`SELECT rut_usuario, tributaria_cifrada, certificado_cifrada FROM claves_sii WHERE cuenta_id=? AND rut_empresa=?`, cuenta, rut).Scan(&u, &trib, &cert)
	descifrar := func(b []byte) string {
		if len(b) == 0 {
			return ""
		}
		v, err := s.fernet.Descifrar(b)
		if err != nil {
			return ""
		}
		return string(v)
	}
	if u.Valid {
		usuario = u.String
	}
	return usuario, descifrar(trib), descifrar(cert)
}

// guardarClaves es keystore.guardar_claves_sii: upsert de lo que viene, conservando lo demás.
func (s *Servidor) guardarClaves(cuenta int64, rut, usuario, tributaria, certificado string) error {
	var usuarioPrev nullString
	var tribPrev, certPrev []byte
	s.db.QueryRow(`SELECT rut_usuario, tributaria_cifrada, certificado_cifrada FROM claves_sii WHERE cuenta_id=? AND rut_empresa=?`, cuenta, rut).Scan(&usuarioPrev, &tribPrev, &certPrev)
	trib, cert := tribPrev, certPrev
	if tributaria != "" {
		trib, _ = s.fernet.Cifrar([]byte(tributaria))
	}
	if certificado != "" {
		cert, _ = s.fernet.Cifrar([]byte(certificado))
	}
	u := usuarioPrev.valor()
	if usuario != "" {
		u = usuario
	}
	_, err := s.db.Exec(`INSERT INTO claves_sii (cuenta_id, rut_empresa, rut_usuario, tributaria_cifrada, certificado_cifrada, actualizado) VALUES (?,?,?,?,?,?)
		ON CONFLICT(cuenta_id, rut_empresa) DO UPDATE SET rut_usuario=excluded.rut_usuario, tributaria_cifrada=excluded.tributaria_cifrada,
		certificado_cifrada=excluded.certificado_cifrada, actualizado=excluded.actualizado`, cuenta, rut, u, trib, cert, ahoraUTC())
	return err
}

// responderErrorPortal traduce los errores de siiengine a los códigos de core/errors.py.
func responderErrorPortal(w http.ResponseWriter, r *http.Request, err error) {
	switch {
	case errors.Is(err, siiengine.ErrAutenticacion):
		responderError(w, r, 401, "autenticacion", err.Error(), nil)
	case errors.Is(err, siiengine.ErrRechazo):
		responderError(w, r, 422, "sii_rechazo", err.Error(), nil)
	case errors.Is(err, siiengine.ErrValidacion):
		responderError(w, r, 422, "validacion", err.Error(), nil)
	default:
		responderError(w, r, 502, "sii_comunicacion", err.Error(), nil)
	}
}

func (s *Servidor) leerMipyme(w http.ResponseWriter, r *http.Request) (*mipymeIn, bool) {
	var d mipymeIn
	if !leerJSON(w, r, &d) {
		return nil, false
	}
	if d.RutEmpresa == nil {
		faltan(w, r, "rut_empresa")
		return nil, false
	}
	if d.ConPDF == nil {
		t := true
		d.ConPDF = &t
	}
	return &d, s.resolverClaves(w, r, &d)
}

func (s *Servidor) sesionPortal(w http.ResponseWriter, r *http.Request, d *mipymeIn) (*siiengine.Cliente, bool) {
	cli, err := siiengine.Nuevo(d.RutUsuario, d.ClaveTributaria, d.ClaveCertificado)
	if err != nil {
		responderError(w, r, 422, "validacion", err.Error(), nil)
		return nil, false
	}
	cli.RaizStorage = s.cfg.StoragePath
	if err := cli.IniciarSesion(); err != nil {
		cli.Cerrar()
		responderErrorPortal(w, r, err)
		return nil, false
	}
	if err := cli.SeleccionarEmpresa(*d.RutEmpresa); err != nil {
		cli.Cerrar()
		responderErrorPortal(w, r, err)
		return nil, false
	}
	return cli, true
}

var reBoleta = regexp.MustCompile(`(?i)bolet`)
var reHistorial = regexp.MustCompile(`(?i)histor|emitid|consult`)

// lecturaPortal: enlaces, menú, form de la factura exenta y el drift del schema.
func lecturaPortal(cli *siiengine.Cliente) (enlaces []siiengine.Enlace, menu siiengine.ResumenMenu, campos map[string]string, form map[string]any, err error) {
	enlaces = cli.EnlacesMenu()
	if enlaces == nil {
		enlaces = []siiengine.Enlace{}
	}
	menu = cli.ResumenMenu()
	f, err := cli.LeerForm(siiengine.TipoFacturaExenta)
	if err != nil {
		return
	}
	campos = f.Campos
	// El drift se calcula con un receptor ficticio: ArmarPayload no toca la red.
	payload, perr := siiengine.ArmarPayload(f, siiengine.TipoFacturaExenta, receptorPrueba, []siiengine.Item{{Nombre: "x", Precio: 1, Cantidad: 1}}, "", "", nil, nil)
	nuevos := []string{}
	pares := 0
	if perr == nil {
		pares = len(payload.Pares)
		if payload.CamposNuevos != nil {
			nuevos = payload.CamposNuevos
		}
	}
	form = map[string]any{"campos_en_html": len(campos), "campos_del_schema": pares, "campos_nuevos": nuevos}
	return
}

func emisorSegunPortal(campos map[string]string, conDireccion bool) map[string]string {
	m := map[string]string{"razon_social": campos["EFXP_RZN_SOC"], "giro": campos["EFXP_GIRO_EMIS"], "acteco": campos["EFXP_ACTECO"], "comuna": campos["EFXP_CMNA_ORIGEN"]}
	if conDireccion {
		m["direccion"] = campos["EFXP_DIR_ORIGEN"]
	}
	return m
}

func filtrarEnlaces(enlaces []siiengine.Enlace, re *regexp.Regexp) []siiengine.Enlace {
	out := []siiengine.Enlace{}
	for _, e := range enlaces {
		if re.MatchString(e.Texto + " " + e.Href) {
			out = append(out, e)
		}
	}
	return out
}

func (s *Servidor) mipymeDiagnostico(w http.ResponseWriter, r *http.Request) {
	d, ok := s.leerMipyme(w, r)
	if !ok {
		return
	}
	d.ClaveCertificado = ""
	cli, ok := s.sesionPortal(w, r, d)
	if !ok {
		return
	}
	defer cli.Cerrar()
	enlaces, menu, campos, form, err := lecturaPortal(cli)
	if err != nil {
		responderErrorPortal(w, r, err)
		return
	}
	responderJSON(w, 200, map[string]any{
		"ambiente": "produccion", "empresa": *d.RutEmpresa,
		"emisor_segun_portal": emisorSegunPortal(campos, true),
		"ultimo_receptor":     map[string]string{"rut": campos["EFXP_RUT_RECEP"] + "-" + campos["EFXP_DV_RECEP"], "razon_social": campos["EFXP_RZN_SOC_RECEP"]},
		"form":                form,
		"boleta_en_gratuito":  len(filtrarEnlaces(enlaces, reBoleta)) > 0,
		"enlaces_boleta":      filtrarEnlaces(enlaces, reBoleta),
		"enlaces_historial":   filtrarEnlaces(enlaces, reHistorial),
		"enlaces":             enlaces, "menu": menu,
		"nota": "Solo lectura: no se emitió nada ni se gastó folio. La sesión se cerró.",
	})
}

func (s *Servidor) importarPortal(cli *siiengine.Cliente, d *mipymeIn) (map[string]any, error) {
	docs, err := cli.ListarEmitidos("", d.Desde, d.Hasta)
	if err != nil {
		return nil, err
	}
	res, err := siiengine.Importar(cli, s.alm, *d.RutEmpresa, docs, siiengine.OpcionesImportar{
		ConPDF: *d.ConPDF, ConXML: d.ConXML && d.ClaveCertificado != "", Carpeta: s.cfg.StoragePath, Pausa: 500 * time.Millisecond})
	if err != nil {
		return nil, err
	}
	raw, _ := json.Marshal(res)
	var m map[string]any
	_ = json.Unmarshal(raw, &m)
	return m, nil
}

func (s *Servidor) mipymeImportar(w http.ResponseWriter, r *http.Request) {
	d, ok := s.leerMipyme(w, r)
	if !ok {
		return
	}
	cli, ok := s.sesionPortal(w, r, d)
	if !ok {
		return
	}
	defer cli.Cerrar()
	resumen, err := s.importarPortal(cli, d)
	if err != nil {
		responderErrorPortal(w, r, err)
		return
	}
	resumen["ambiente"] = "produccion"
	resumen["nota"] = "Solo lectura en el SII: se listó el historial y se bajaron PDF. Nada se emitió."
	responderJSON(w, 200, resumen)
}

func (s *Servidor) mipymeSincronizar(w http.ResponseWriter, r *http.Request) {
	d, ok := s.leerMipyme(w, r)
	if !ok {
		return
	}
	cli, ok := s.sesionPortal(w, r, d)
	if !ok {
		return
	}
	defer cli.Cerrar()
	enlaces, menu, campos, form, err := lecturaPortal(cli)
	if err != nil {
		responderErrorPortal(w, r, err)
		return
	}
	resumen, err := s.importarPortal(cli, d)
	if err != nil {
		responderErrorPortal(w, r, err)
		return
	}
	resumen["ambiente"] = "produccion"
	resumen["emisor_segun_portal"] = emisorSegunPortal(campos, false)
	resumen["form"] = form
	resumen["enlaces"] = enlaces
	resumen["menu"] = menu
	resumen["nota"] = "Solo lectura en el SII: sesión comprobada, historial listado y PDF descargados. Nada se emitió."
	responderJSON(w, 200, resumen)
}
