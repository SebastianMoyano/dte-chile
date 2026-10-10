package servidor

// /api/v1/keystore/*: certificados (cifrados con Fernet), claves del SII recordadas, negocios y
// el contexto de emisión para el núcleo. Réplica de api/routes/keystore.py y core/keystore.py.
// Lo que consulta el portal del SII (alta de negocio, timbraje, estado, f29, empresas del
// certificado) sigue en Python mientras no se porte sii_portal: esas rutas se reenvían.

import (
	"crypto/x509"
	"database/sql"
	"encoding/asn1"
	"encoding/pem"
	"fmt"
	"io"
	"net/http"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"time"

	"dtechile/nucleo/firma"
)

const maxUpload = 5 * 1024 * 1024 // api/util.py::MAX_UPLOAD_BYTES

type nullString struct{ sql.NullString }

func (n nullString) valor() any {
	if n.Valid {
		return n.String
	}
	return nil
}

func ahoraUTC() string { return time.Now().UTC().Format("2006-01-02T15:04:05.000000+00:00") }

func (s *Servidor) rutasKeystore(mux *http.ServeMux) {
	mux.HandleFunc("POST /api/v1/keystore/certificados", s.protegido(s.subirCertificado))
	mux.HandleFunc("GET /api/v1/keystore/certificados", s.protegido(s.listarCertificados))
	mux.HandleFunc("DELETE /api/v1/keystore/certificados/{id}", s.protegido(s.eliminarCertificado))
	mux.HandleFunc("GET /api/v1/keystore/negocios", s.protegido(s.listarNegocios))
	mux.HandleFunc("DELETE /api/v1/keystore/negocios/{id}", s.protegido(s.eliminarNegocio))
	mux.HandleFunc("GET /api/v1/keystore/negocios/{id}/contexto-emision", s.protegido(s.contextoEmision))
	mux.HandleFunc("PUT /api/v1/keystore/claves-sii", s.protegido(s.guardarClavesSII))
	mux.HandleFunc("GET /api/v1/keystore/claves-sii/{rut}", s.protegido(s.estadoClavesSII))
	mux.HandleFunc("DELETE /api/v1/keystore/claves-sii/{rut}", s.protegido(s.olvidarClavesSII))
	mux.HandleFunc("GET /api/v1/mipyme/contexto-siiengine/{rut}", s.protegido(s.contextoSIIEngine))
}

func (s *Servidor) cuentaID(w http.ResponseWriter, r *http.Request) (int64, bool) {
	u := usuarioDe(r)
	if u.Tipo != "usuario" {
		// Python: usuario["id"] es None para API keys → las consultas no encuentran nada.
		return 0, true
	}
	return u.ID, true
}

// ------------------------------------------------------------------ certificados

var reRut = regexp.MustCompile(`(\d{7,8}-[\dkK])`)

// rutDelCertificado es CertificadoDigital.rut_emisor: el RUT del CN o, si no, del otherName
// del SAN con el OID chileno 1.3.6.1.4.1.8321.1. "SIN-RUT" si no aparece.
func rutDelCertificado(c *x509.Certificate) string {
	cn := c.Subject.CommonName
	if m := reRut.FindStringSubmatch(cn); m != nil {
		return m[1]
	}
	if partes := strings.Split(cn, "-"); len(partes) >= 2 {
		num, dv := partes[len(partes)-2], partes[len(partes)-1]
		if _, err := strconv.Atoi(num); err == nil && len(dv) == 1 {
			return num + "-" + dv
		}
	}
	for _, ext := range c.Extensions {
		if !ext.Id.Equal(asn1.ObjectIdentifier{2, 5, 29, 17}) {
			continue
		}
		var seq asn1.RawValue
		if _, err := asn1.Unmarshal(ext.Value, &seq); err != nil {
			continue
		}
		resto := seq.Bytes
		for len(resto) > 0 {
			var gn asn1.RawValue
			var err error
			resto, err = asn1.Unmarshal(resto, &gn)
			if err != nil {
				break
			}
			if gn.Class != asn1.ClassContextSpecific || gn.Tag != 0 { // otherName
				continue
			}
			var oid asn1.ObjectIdentifier
			tras, err := asn1.Unmarshal(gn.Bytes, &oid)
			if err != nil || !oid.Equal(asn1.ObjectIdentifier{1, 3, 6, 1, 4, 1, 8321, 1}) {
				continue
			}
			if m := reRut.FindStringSubmatch(string(tras)); m != nil {
				return m[1]
			}
		}
	}
	return "SIN-RUT"
}

func (s *Servidor) subirCertificado(w http.ResponseWriter, r *http.Request) {
	cuenta, _ := s.cuentaID(w, r)
	if err := r.ParseMultipartForm(maxUpload + 1024); err != nil {
		responderError(w, r, 422, "validacion", "Los datos enviados no son válidos.", nil)
		return
	}
	f, _, err := r.FormFile("archivo")
	var faltanCampos []string
	if err != nil {
		faltanCampos = append(faltanCampos, "archivo")
	}
	if _, ok := r.MultipartForm.Value["password"]; !ok {
		faltanCampos = append(faltanCampos, "password")
	}
	if faltan(w, r, faltanCampos...) {
		return
	}
	defer f.Close()
	p12, err := io.ReadAll(io.LimitReader(f, maxUpload+1))
	if err != nil || len(p12) > maxUpload {
		responderError(w, r, 422, "validacion", "Archivo demasiado grande (máximo 5 MB).", nil)
		return
	}
	password := r.FormValue("password")
	cert, err := firma.CargarP12(p12, password)
	if err != nil {
		responderError(w, r, 422, "certificado", "Certificado inválido o contraseña incorrecta: "+err.Error(), nil)
		return
	}
	rut := rutDelCertificado(cert.Cert)
	vence := cert.Cert.NotAfter.UTC().Format("2006-01-02T15:04:05+00:00")
	p12Cif, err1 := s.fernet.Cifrar(p12)
	claveCif, err2 := s.fernet.Cifrar([]byte(password))
	if err1 != nil || err2 != nil {
		responderError(w, r, 500, "error_interno", "Ocurrió un error interno. Reporta el request_id al soporte.", nil)
		return
	}
	nombre, alias := formONulo(r, "nombre"), formONulo(r, "alias")
	ahora := ahoraUTC()
	var id int64
	err = s.db.QueryRow(`SELECT id FROM certificados WHERE cuenta_id=? AND rut=?`, cuenta, rut).Scan(&id)
	if err == nil {
		s.db.Exec(`UPDATE certificados SET nombre=?, alias=?, vencimiento=?, p12_cifrado=?, clave_cifrada=?, creado=? WHERE id=?`, nombre, alias, vence, p12Cif, claveCif, ahora, id)
	} else {
		res, err := s.db.Exec(`INSERT INTO certificados (cuenta_id, rut, nombre, alias, vencimiento, p12_cifrado, clave_cifrada, creado) VALUES (?,?,?,?,?,?,?,?)`,
			cuenta, rut, nombre, alias, vence, p12Cif, claveCif, ahora)
		if err != nil {
			responderError(w, r, 500, "error_interno", "Ocurrió un error interno. Reporta el request_id al soporte.", nil)
			return
		}
		id, _ = res.LastInsertId()
	}
	responderJSON(w, 201, map[string]any{"id": id, "cuenta_id": cuenta, "rut": rut, "nombre": nombre, "alias": alias, "vencimiento": vence})
}

func formONulo(r *http.Request, k string) any {
	if vs, ok := r.MultipartForm.Value[k]; ok && len(vs) > 0 {
		return vs[0]
	}
	return nil
}

func (s *Servidor) listarCertificados(w http.ResponseWriter, r *http.Request) {
	cuenta, _ := s.cuentaID(w, r)
	rows, err := s.db.Query(`SELECT id, rut, nombre, alias, vencimiento, creado FROM certificados WHERE cuenta_id=? ORDER BY id`, cuenta)
	if err != nil {
		responderError(w, r, 500, "error_interno", "Ocurrió un error interno. Reporta el request_id al soporte.", nil)
		return
	}
	defer rows.Close()
	out := []map[string]any{}
	for rows.Next() {
		var id int64
		var rut, creado string
		var nombre, alias, vence nullString
		rows.Scan(&id, &rut, &nombre, &alias, &vence, &creado)
		out = append(out, map[string]any{"id": id, "rut": rut, "nombre": nombre.valor(), "alias": alias.valor(), "vencimiento": vence.valor(), "creado": creado})
	}
	responderJSON(w, 200, out)
}

func (s *Servidor) eliminarCertificado(w http.ResponseWriter, r *http.Request) {
	cuenta, _ := s.cuentaID(w, r)
	id, err := strconv.ParseInt(r.PathValue("id"), 10, 64)
	if err != nil {
		responderError(w, r, 422, "validacion", "Los datos enviados no son válidos.", nil)
		return
	}
	res, _ := s.db.Exec(`DELETE FROM certificados WHERE id=? AND cuenta_id=?`, id, cuenta)
	if n, _ := res.RowsAffected(); n == 0 {
		responderError(w, r, 404, "no_encontrado", "Certificado no encontrado", nil)
		return
	}
	responderJSON(w, 200, map[string]any{"eliminado": true, "id": id})
}

// descifrarCertificado es keystore._descifrar.
func (s *Servidor) descifrarCertificado(certID, cuenta int64) ([]byte, string, error) {
	var p12Cif, claveCif []byte
	err := s.db.QueryRow(`SELECT p12_cifrado, clave_cifrada FROM certificados WHERE id=? AND cuenta_id=?`, certID, cuenta).Scan(&p12Cif, &claveCif)
	if err == sql.ErrNoRows {
		return nil, "", fmt.Errorf("Certificado %d no encontrado", certID)
	}
	if err != nil {
		return nil, "", err
	}
	p12, err := s.fernet.Descifrar(p12Cif)
	if err != nil {
		return nil, "", err
	}
	clave, err := s.fernet.Descifrar(claveCif)
	if err != nil {
		return nil, "", err
	}
	return p12, string(clave), nil
}

// ------------------------------------------------------------------ negocios

type filaNegocio struct {
	ID                     int64
	Rut                    string
	RazonSocial            nullString
	CertID                 sql.NullInt64
	Ambiente               nullString
	Creado                 string
	Estado, EstadoEtiqueta nullString
	UsaSwPropio            sql.NullInt64
	EstadoTS               nullString
}

func (s *Servidor) negociosDe(cuenta int64) ([]filaNegocio, error) {
	rows, err := s.db.Query(`SELECT id, rut, razon_social, cert_id, ambiente, creado, estado, estado_etiqueta, usa_sw_propio, estado_ts FROM negocios WHERE cuenta_id=? ORDER BY id`, cuenta)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []filaNegocio
	for rows.Next() {
		var n filaNegocio
		if err := rows.Scan(&n.ID, &n.Rut, &n.RazonSocial, &n.CertID, &n.Ambiente, &n.Creado, &n.Estado, &n.EstadoEtiqueta, &n.UsaSwPropio, &n.EstadoTS); err != nil {
			return nil, err
		}
		out = append(out, n)
	}
	return out, nil
}

func (n filaNegocio) mapa() map[string]any {
	var cert, usa any
	if n.CertID.Valid {
		cert = n.CertID.Int64
	}
	if n.UsaSwPropio.Valid {
		usa = n.UsaSwPropio.Int64
	}
	return map[string]any{"id": n.ID, "rut": n.Rut, "razon_social": n.RazonSocial.valor(), "cert_id": cert, "ambiente": n.Ambiente.valor(), "creado": n.Creado,
		"estado": n.Estado.valor(), "estado_etiqueta": n.EstadoEtiqueta.valor(), "usa_sw_propio": usa, "estado_ts": n.EstadoTS.valor()}
}

func (s *Servidor) listarNegocios(w http.ResponseWriter, r *http.Request) {
	cuenta, _ := s.cuentaID(w, r)
	negs, err := s.negociosDe(cuenta)
	if err != nil {
		responderError(w, r, 500, "error_interno", "Ocurrió un error interno. Reporta el request_id al soporte.", nil)
		return
	}
	out := []map[string]any{}
	for _, n := range negs {
		out = append(out, n.mapa())
	}
	responderJSON(w, 200, out)
}

func (s *Servidor) eliminarNegocio(w http.ResponseWriter, r *http.Request) {
	cuenta, _ := s.cuentaID(w, r)
	id, err := strconv.ParseInt(r.PathValue("id"), 10, 64)
	if err != nil {
		responderError(w, r, 422, "validacion", "Los datos enviados no son válidos.", nil)
		return
	}
	res, _ := s.db.Exec(`DELETE FROM negocios WHERE id=? AND cuenta_id=?`, id, cuenta)
	if n, _ := res.RowsAffected(); n == 0 {
		responderError(w, r, 404, "no_encontrado", "Negocio no encontrado", nil)
		return
	}
	responderJSON(w, 200, map[string]any{"eliminado": true, "id": id})
}

// resolucionEmisor es core/resolucion.py::resolucion_emisor sin la consulta al portal del SII
// (sii_portal no está portado): caché en BD → default del ambiente. Python, ante un caché
// vacío, consulta el registro público; aquí queda el default hasta que se porte el portal.
func (s *Servidor) resolucionEmisor(rut, ambiente string) (string, int) {
	var fecha string
	var numero int
	if err := s.db.QueryRow(`SELECT fecha_iso, numero FROM resolucion_cache WHERE rut=? AND ambiente=?`, rut, ambiente).Scan(&fecha, &numero); err == nil {
		return fecha, numero
	}
	if ambiente == "produccion" {
		return s.cfg.ResolucionFecha, s.cfg.ResolucionNumero
	}
	return s.cfg.ResolucionFechaCert, s.cfg.ResolucionNumeroCert
}

func (s *Servidor) contextoEmision(w http.ResponseWriter, r *http.Request) {
	cuenta, _ := s.cuentaID(w, r)
	id, err := strconv.ParseInt(r.PathValue("id"), 10, 64)
	if err != nil {
		responderError(w, r, 422, "validacion", "Los datos enviados no son válidos.", nil)
		return
	}
	negs, err := s.negociosDe(cuenta)
	if err != nil {
		responderError(w, r, 500, "error_interno", "Ocurrió un error interno. Reporta el request_id al soporte.", nil)
		return
	}
	var neg *filaNegocio
	for i := range negs {
		if negs[i].ID == id {
			neg = &negs[i]
		}
	}
	if neg == nil {
		responderError(w, r, 404, "no_encontrado", "Negocio no encontrado", nil)
		return
	}
	if !neg.CertID.Valid || neg.CertID.Int64 == 0 {
		responderError(w, r, 422, "validacion", "El negocio no tiene un certificado asociado", nil)
		return
	}
	p12, clave, err := s.descifrarCertificado(neg.CertID.Int64, cuenta)
	if err != nil {
		responderError(w, r, 404, "no_encontrado", err.Error(), nil)
		return
	}
	cert, err := firma.CargarP12(p12, clave)
	if err != nil {
		responderError(w, r, 422, "certificado", "El certificado guardado no se pudo abrir: "+err.Error(), nil)
		return
	}
	certPEM := pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: cert.Cert.Raw})
	keyPEM := pem.EncodeToMemory(&pem.Block{Type: "RSA PRIVATE KEY", Bytes: x509.MarshalPKCS1PrivateKey(cert.Clave)})
	ambiente := s.cfg.SIIAmbiente
	if neg.Ambiente.Valid && neg.Ambiente.String != "" {
		ambiente = neg.Ambiente.String
	}
	fecha, numero := s.resolucionEmisor(neg.Rut, ambiente)
	db, _ := filepath.Abs(s.cfg.DatabasePath)
	st, _ := filepath.Abs(s.cfg.StoragePath)
	responderJSON(w, 200, map[string]any{
		"negocio_id": neg.ID, "rut": neg.Rut, "razon_social": neg.RazonSocial.valor(), "ambiente": ambiente,
		"resolucion": map[string]any{"fecha": fecha, "numero": numero},
		"cert_pem":   string(certPEM), "key_pem": string(keyPEM), "database_path": db, "storage_path": st,
	})
}

// ------------------------------------------------------------------ claves del SII

func (s *Servidor) estadoClaves(cuenta int64, rut string) map[string]any {
	var usuario nullString
	var trib, cert []byte
	var act nullString
	err := s.db.QueryRow(`SELECT rut_usuario, tributaria_cifrada, certificado_cifrada, actualizado FROM claves_sii WHERE cuenta_id=? AND rut_empresa=?`, cuenta, rut).
		Scan(&usuario, &trib, &cert, &act)
	if err != nil {
		return map[string]any{"rut_empresa": rut, "rut_usuario": nil, "tiene_tributaria": false, "tiene_certificado": false, "actualizado": nil}
	}
	return map[string]any{"rut_empresa": rut, "rut_usuario": usuario.valor(), "tiene_tributaria": len(trib) > 0, "tiene_certificado": len(cert) > 0, "actualizado": act.valor()}
}

func (s *Servidor) estadoClavesSII(w http.ResponseWriter, r *http.Request) {
	cuenta, _ := s.cuentaID(w, r)
	responderJSON(w, 200, s.estadoClaves(cuenta, r.PathValue("rut")))
}

func (s *Servidor) olvidarClavesSII(w http.ResponseWriter, r *http.Request) {
	cuenta, _ := s.cuentaID(w, r)
	res, _ := s.db.Exec(`DELETE FROM claves_sii WHERE cuenta_id=? AND rut_empresa=?`, cuenta, r.PathValue("rut"))
	n, _ := res.RowsAffected()
	responderJSON(w, 200, map[string]any{"olvidadas": n > 0})
}

func (s *Servidor) guardarClavesSII(w http.ResponseWriter, r *http.Request) {
	cuenta, _ := s.cuentaID(w, r)
	var in struct {
		RutEmpresa       *string `json:"rut_empresa"`
		RutUsuario       *string `json:"rut_usuario"`
		ClaveTributaria  *string `json:"clave_tributaria"`
		ClaveCertificado *string `json:"clave_certificado"`
	}
	if !leerJSON(w, r, &in) {
		return
	}
	if in.RutEmpresa == nil {
		faltan(w, r, "rut_empresa")
		return
	}
	var usuarioPrev nullString
	var tribPrev, certPrev []byte
	s.db.QueryRow(`SELECT rut_usuario, tributaria_cifrada, certificado_cifrada FROM claves_sii WHERE cuenta_id=? AND rut_empresa=?`, cuenta, *in.RutEmpresa).Scan(&usuarioPrev, &tribPrev, &certPrev)
	trib, cert := tribPrev, certPrev
	if in.ClaveTributaria != nil && *in.ClaveTributaria != "" {
		trib, _ = s.fernet.Cifrar([]byte(*in.ClaveTributaria))
	}
	if in.ClaveCertificado != nil && *in.ClaveCertificado != "" {
		cert, _ = s.fernet.Cifrar([]byte(*in.ClaveCertificado))
	}
	usuario := usuarioPrev.valor()
	if in.RutUsuario != nil && *in.RutUsuario != "" {
		usuario = *in.RutUsuario
	}
	_, err := s.db.Exec(`INSERT INTO claves_sii (cuenta_id, rut_empresa, rut_usuario, tributaria_cifrada, certificado_cifrada, actualizado) VALUES (?,?,?,?,?,?)
		ON CONFLICT(cuenta_id, rut_empresa) DO UPDATE SET rut_usuario=excluded.rut_usuario, tributaria_cifrada=excluded.tributaria_cifrada,
		certificado_cifrada=excluded.certificado_cifrada, actualizado=excluded.actualizado`,
		cuenta, *in.RutEmpresa, usuario, trib, cert, ahoraUTC())
	if err != nil {
		responderError(w, r, 500, "error_interno", "Ocurrió un error interno. Reporta el request_id al soporte.", nil)
		return
	}
	responderJSON(w, 200, s.estadoClaves(cuenta, *in.RutEmpresa))
}

// contextoSIIEngine es api/routes/mipyme.py::contexto_siiengine (claves recordadas + rutas).
func (s *Servidor) contextoSIIEngine(w http.ResponseWriter, r *http.Request) {
	cuenta, _ := s.cuentaID(w, r)
	rut := r.PathValue("rut")
	var usuario nullString
	var trib, cert []byte
	s.db.QueryRow(`SELECT rut_usuario, tributaria_cifrada, certificado_cifrada FROM claves_sii WHERE cuenta_id=? AND rut_empresa=?`, cuenta, rut).Scan(&usuario, &trib, &cert)
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
	ru := ""
	if usuario.Valid {
		ru = usuario.String
	}
	db, _ := filepath.Abs(s.cfg.DatabasePath)
	st, _ := filepath.Abs(s.cfg.StoragePath)
	responderJSON(w, 200, map[string]any{"rut_empresa": rut, "rut_usuario": ru, "clave_tributaria": descifrar(trib), "clave_certificado": descifrar(cert),
		"database_path": db, "storage_path": st})
}
