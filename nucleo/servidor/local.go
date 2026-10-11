package servidor

import (
	"bytes"
	"crypto/rand"
	"encoding/base64"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"regexp"
	"strings"

	"dtechile/nucleo/firma"
)

// Lo que los CLI y el servidor MCP necesitan del motor sin pasar por la red: el keystore,
// la rotación de claves y llamar a cualquier ruta en el mismo proceso (Llamar).

// Llamar ejecuta una ruta contra el handler del servidor, sin red, como la cuenta dueña
// (clave de la app). Devuelve status y cuerpo.
func (s *Servidor) Llamar(metodo, ruta string, cuerpo []byte) (int, []byte) {
	var body io.Reader
	if cuerpo != nil {
		body = bytes.NewReader(cuerpo)
	}
	req := httptest.NewRequest(metodo, ruta, body)
	if cuerpo != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	if s.cfg.AppShellKey != "" {
		req.Header.Set("Authorization", "Bearer "+s.cfg.AppShellKey)
	}
	rec := httptest.NewRecorder()
	s.Handler().ServeHTTP(rec, req)
	return rec.Code, rec.Body.Bytes()
}

// CertificadoInfo son los metadatos de un certificado del keystore (sin secretos).
type CertificadoInfo struct {
	ID          int64  `json:"id"`
	Rut         string `json:"rut"`
	Nombre      string `json:"nombre"`
	Alias       string `json:"alias"`
	Vencimiento string `json:"vencimiento"`
	Creado      string `json:"creado"`
}

// GuardarCertificado es keystore.guardar_certificado: valida el .p12 con su clave, y guarda
// ambos cifrados (upsert por cuenta+RUT, ids consecutivos).
func (s *Servidor) GuardarCertificado(cuenta int64, p12 []byte, clave, nombre, alias string) (*CertificadoInfo, error) {
	cert, err := firma.CargarP12(p12, clave)
	if err != nil {
		return nil, fmt.Errorf("certificado inválido o contraseña incorrecta: %w", err)
	}
	rut := rutDelCertificado(cert.Cert)
	vence := cert.Cert.NotAfter.UTC().Format("2006-01-02T15:04:05+00:00")
	p12Cif, err := s.fernet.Cifrar(p12)
	if err != nil {
		return nil, err
	}
	claveCif, err := s.fernet.Cifrar([]byte(clave))
	if err != nil {
		return nil, err
	}
	var n, a any
	if nombre != "" {
		n = nombre
	}
	if alias != "" {
		a = alias
	}
	ahora := ahoraUTC()
	var id int64
	if err := s.db.QueryRow(`SELECT id FROM certificados WHERE cuenta_id=? AND rut=?`, cuenta, rut).Scan(&id); err == nil {
		_, err = s.db.Exec(`UPDATE certificados SET nombre=?, alias=?, vencimiento=?, p12_cifrado=?, clave_cifrada=?, creado=? WHERE id=?`, n, a, vence, p12Cif, claveCif, ahora, id)
		if err != nil {
			return nil, err
		}
	} else {
		res, err := s.db.Exec(`INSERT INTO certificados (cuenta_id, rut, nombre, alias, vencimiento, p12_cifrado, clave_cifrada, creado) VALUES (?,?,?,?,?,?,?,?)`,
			cuenta, rut, n, a, vence, p12Cif, claveCif, ahora)
		if err != nil {
			return nil, err
		}
		id, _ = res.LastInsertId()
	}
	return &CertificadoInfo{ID: id, Rut: rut, Nombre: nombre, Alias: alias, Vencimiento: vence, Creado: ahora}, nil
}

// ListarCertificados es keystore.listar_certificados.
func (s *Servidor) ListarCertificados(cuenta int64) ([]CertificadoInfo, error) {
	rows, err := s.db.Query(`SELECT id, rut, COALESCE(nombre,''), COALESCE(alias,''), COALESCE(vencimiento,''), creado FROM certificados WHERE cuenta_id=? ORDER BY id`, cuenta)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []CertificadoInfo{}
	for rows.Next() {
		var c CertificadoInfo
		if err := rows.Scan(&c.ID, &c.Rut, &c.Nombre, &c.Alias, &c.Vencimiento, &c.Creado); err != nil {
			return nil, err
		}
		out = append(out, c)
	}
	return out, rows.Err()
}

// EliminarCertificado es keystore.eliminar_certificado.
func (s *Servidor) EliminarCertificado(cuenta, id int64) (bool, error) {
	res, err := s.db.Exec(`DELETE FROM certificados WHERE id=? AND cuenta_id=?`, id, cuenta)
	if err != nil {
		return false, err
	}
	n, _ := res.RowsAffected()
	return n > 0, nil
}

// CertificadoDelKeystore es keystore.cargar_certificado: el certificado en memoria.
func (s *Servidor) CertificadoDelKeystore(certID, cuenta int64) (*firma.Certificado, error) {
	p12, clave, err := s.descifrarCertificado(certID, cuenta)
	if err != nil {
		return nil, err
	}
	return firma.CargarP12(p12, clave)
}

// PEMDelKeystore es keystore.pem_transitorio (en memoria): cert y clave en PEM.
func (s *Servidor) PEMDelKeystore(certID, cuenta int64) (certPEM, keyPEM []byte, err error) {
	return s.pemDeCertificado(certID, cuenta)
}

func clave64(n int) string {
	b := make([]byte, n)
	_, _ = rand.Read(b)
	return base64.RawURLEncoding.EncodeToString(b)
}

// RotarClaves es rotar_claves.py: descifra TODO lo cifrado con la clave actual (certificados y
// claves del SII), genera JWT_SECRET_KEY y DTE_MASTER_KEY nuevos, re-cifra, escribe el .env
// (y acota CORS_ORIGINS a localhost), resetea la clave de `admin` y verifica. Si algo falla
// antes de re-cifrar, no toca nada. Devuelve la clave nueva de admin.
func (s *Servidor) RotarClaves(rutaEnv, adminPassword string) (string, error) {
	type cert struct {
		id         int64
		p12, clave []byte
	}
	rows, err := s.db.Query(`SELECT id, p12_cifrado, clave_cifrada FROM certificados`)
	if err != nil {
		return "", err
	}
	var certs []cert
	for rows.Next() {
		var c cert
		var p12c, clc []byte
		if err := rows.Scan(&c.id, &p12c, &clc); err != nil {
			rows.Close()
			return "", err
		}
		if c.p12, err = s.fernet.Descifrar(p12c); err != nil {
			rows.Close()
			return "", fmt.Errorf("no se pudo descifrar el certificado id=%d con la clave actual: %w (abortado, no se cambió nada)", c.id, err)
		}
		if c.clave, err = s.fernet.Descifrar(clc); err != nil {
			rows.Close()
			return "", fmt.Errorf("no se pudo descifrar la clave del certificado id=%d: %w (abortado)", c.id, err)
		}
		certs = append(certs, c)
	}
	rows.Close()
	type claveSII struct {
		id         int64
		trib, cert []byte
	}
	rows, err = s.db.Query(`SELECT id, tributaria_cifrada, certificado_cifrada FROM claves_sii`)
	if err != nil {
		return "", err
	}
	var claves []claveSII
	for rows.Next() {
		var k claveSII
		var t, c []byte
		if err := rows.Scan(&k.id, &t, &c); err != nil {
			rows.Close()
			return "", err
		}
		if len(t) > 0 {
			if k.trib, err = s.fernet.Descifrar(t); err != nil {
				rows.Close()
				return "", fmt.Errorf("claves_sii id=%d: %w (abortado)", k.id, err)
			}
		}
		if len(c) > 0 {
			if k.cert, err = s.fernet.Descifrar(c); err != nil {
				rows.Close()
				return "", fmt.Errorf("claves_sii id=%d: %w (abortado)", k.id, err)
			}
		}
		claves = append(claves, k)
	}
	rows.Close()
	// secretos nuevos
	nuevoJWT := clave64(48)
	masterRaw := make([]byte, 32)
	_, _ = rand.Read(masterRaw)
	nuevoMaster := base64.URLEncoding.EncodeToString(masterRaw)
	nuevo, err := nuevoFernet(nuevoMaster, nuevoJWT)
	if err != nil {
		return "", err
	}
	tx, err := s.db.Begin()
	if err != nil {
		return "", err
	}
	for _, c := range certs {
		p, _ := nuevo.Cifrar(c.p12)
		k, _ := nuevo.Cifrar(c.clave)
		if _, err := tx.Exec(`UPDATE certificados SET p12_cifrado=?, clave_cifrada=? WHERE id=?`, p, k, c.id); err != nil {
			tx.Rollback()
			return "", err
		}
	}
	for _, k := range claves {
		var t, c any
		if k.trib != nil {
			t, _ = nuevo.Cifrar(k.trib)
		}
		if k.cert != nil {
			c, _ = nuevo.Cifrar(k.cert)
		}
		if _, err := tx.Exec(`UPDATE claves_sii SET tributaria_cifrada=?, certificado_cifrada=? WHERE id=?`, t, c, k.id); err != nil {
			tx.Rollback()
			return "", err
		}
	}
	if adminPassword == "" {
		adminPassword = clave64(12)
	}
	h, err := hashPassword(adminPassword)
	if err != nil {
		tx.Rollback()
		return "", err
	}
	if _, err := tx.Exec(`UPDATE usuarios SET hashed_password=? WHERE username='admin'`, h); err != nil {
		tx.Rollback()
		return "", err
	}
	if err := tx.Commit(); err != nil {
		return "", err
	}
	s.fernet = nuevo
	s.cfg.JWTSecret, s.cfg.MasterKey = nuevoJWT, nuevoMaster
	// .env
	t, _ := os.ReadFile(rutaEnv)
	texto := string(t)
	for k, v := range map[string]string{"JWT_SECRET_KEY": nuevoJWT, "DTE_MASTER_KEY": nuevoMaster, "CORS_ORIGINS": "http://localhost:8000,http://127.0.0.1:8000"} {
		re := regexp.MustCompile(`(?m)^` + k + `=.*$`)
		if re.MatchString(texto) {
			texto = re.ReplaceAllString(texto, k+"="+v)
		} else {
			texto = strings.TrimRight(texto, "\n") + "\n" + k + "=" + v + "\n"
		}
	}
	if err := os.WriteFile(rutaEnv, []byte(texto), 0o600); err != nil {
		return "", fmt.Errorf("la base ya está re-cifrada pero no se pudo escribir %s: %w. DTE_MASTER_KEY=%s JWT_SECRET_KEY=%s", rutaEnv, err, nuevoMaster, nuevoJWT)
	}
	// verificación
	for _, c := range certs {
		if _, err := s.CertificadoDelKeystore(c.id, 0); err != nil {
			if _, err2 := s.descifrarCualquiera(c.id); err2 != nil {
				return "", fmt.Errorf("verificación: el certificado id=%d no se descifra con la clave nueva: %w", c.id, err2)
			}
		}
	}
	return adminPassword, nil
}

func (s *Servidor) descifrarCualquiera(certID int64) (*firma.Certificado, error) {
	var p12c, clc []byte
	if err := s.db.QueryRow(`SELECT p12_cifrado, clave_cifrada FROM certificados WHERE id=?`, certID).Scan(&p12c, &clc); err != nil {
		return nil, err
	}
	p12, err := s.fernet.Descifrar(p12c)
	if err != nil {
		return nil, err
	}
	cl, err := s.fernet.Descifrar(clc)
	if err != nil {
		return nil, err
	}
	return firma.CargarP12(p12, string(cl))
}

var _ = http.StatusOK

// TokenValido: ¿es un JWT válido del proyecto o la clave de la app? (auth del MCP por HTTP).
func (s *Servidor) TokenValido(token string) bool {
	if s.cfg.AppShellKey != "" && token == s.cfg.AppShellKey {
		return true
	}
	_, ok := s.verificarJWT(token)
	return ok
}
