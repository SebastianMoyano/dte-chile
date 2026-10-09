package servidor

// Autenticación, réplica de core/auth.py::requerir_autenticacion: acepta un JWT (HS256 con
// JWT_SECRET_KEY, claim `sub` = username), la clave efímera de la app (APP_SHELL_KEY, actúa
// como el usuario dueño: el de menor id) o una API key (`dte_…`, sha256 en api_keys). 401 con
// el mismo mensaje y envoltorio que Python.

import (
	"context"
	"crypto/hmac"
	"crypto/sha256"
	"crypto/subtle"
	"database/sql"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"net/http"
	"strings"
	"time"
)

// Usuario es lo que las rutas reciben (el dict de Python: id, username, tipo…).
type Usuario struct {
	ID       int64
	Username string
	Tipo     string // "usuario" | "apikey"
	APIKeyID int64
}

const ctxUsuario claveCtx = "usuario"

func contextoCon(ctx context.Context, k claveCtx, v any) context.Context {
	return context.WithValue(ctx, k, v)
}

func usuarioDe(r *http.Request) *Usuario {
	u, _ := r.Context().Value(ctxUsuario).(*Usuario)
	return u
}

var errNoAutenticado = errors.New("Se requiere un JWT o una API key válidos (Authorization: Bearer).")

func (s *Servidor) autenticar(r *http.Request) (*Usuario, error) {
	auth := r.Header.Get("Authorization")
	if !strings.HasPrefix(strings.ToLower(auth), "bearer ") {
		return nil, errNoAutenticado
	}
	token := strings.TrimSpace(auth[7:])
	if token == "" {
		return nil, errNoAutenticado
	}
	if username, ok := s.verificarJWT(token); ok {
		if u, err := s.usuarioPorUsername(username); err == nil && u != nil {
			s.tocarUltimoAcceso(u.ID)
			return u, nil
		}
	}
	if len(s.cfg.AppShellKey) >= 24 && subtle.ConstantTimeCompare([]byte(token), []byte(s.cfg.AppShellKey)) == 1 {
		if u, err := s.usuarioDueno(); err == nil && u != nil {
			s.tocarUltimoAcceso(u.ID)
			return u, nil
		}
	}
	if strings.HasPrefix(token, "dte_") {
		if u, err := s.verificarAPIKey(token); err == nil && u != nil {
			return u, nil
		}
	}
	return nil, errNoAutenticado
}

// verificarJWT valida firma HS256 y expiración; devuelve el `sub`.
func (s *Servidor) verificarJWT(token string) (string, bool) {
	partes := strings.Split(token, ".")
	if len(partes) != 3 || s.cfg.JWTSecret == "" {
		return "", false
	}
	dec := func(p string) ([]byte, error) { return base64.RawURLEncoding.DecodeString(strings.TrimRight(p, "=")) }
	cab, err := dec(partes[0])
	if err != nil {
		return "", false
	}
	var h struct {
		Alg string `json:"alg"`
	}
	if json.Unmarshal(cab, &h) != nil || h.Alg != "HS256" {
		return "", false
	}
	firma, err := dec(partes[2])
	if err != nil {
		return "", false
	}
	mac := hmac.New(sha256.New, []byte(s.cfg.JWTSecret))
	mac.Write([]byte(partes[0] + "." + partes[1]))
	if !hmac.Equal(firma, mac.Sum(nil)) {
		return "", false
	}
	cuerpo, err := dec(partes[1])
	if err != nil {
		return "", false
	}
	var c struct {
		Sub string  `json:"sub"`
		Exp float64 `json:"exp"`
	}
	if json.Unmarshal(cuerpo, &c) != nil || c.Sub == "" {
		return "", false
	}
	if c.Exp != 0 && time.Now().Unix() >= int64(c.Exp) {
		return "", false
	}
	return c.Sub, true
}

func (s *Servidor) usuarioPorUsername(username string) (*Usuario, error) {
	var u Usuario
	err := s.db.QueryRow(`SELECT id, username FROM usuarios WHERE username=? AND activo=1`, username).Scan(&u.ID, &u.Username)
	if err == sql.ErrNoRows {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	u.Tipo = "usuario"
	return &u, nil
}

func (s *Servidor) usuarioDueno() (*Usuario, error) {
	var u Usuario
	err := s.db.QueryRow(`SELECT id, username FROM usuarios ORDER BY id LIMIT 1`).Scan(&u.ID, &u.Username)
	if err == sql.ErrNoRows {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	u.Tipo = "usuario"
	return &u, nil
}

func (s *Servidor) tocarUltimoAcceso(id int64) {
	s.db.Exec(`UPDATE usuarios SET ultimo_acceso=? WHERE id=?`, time.Now().Format("2006-01-02T15:04:05.000000"), id)
}

func (s *Servidor) verificarAPIKey(token string) (*Usuario, error) {
	h := sha256.Sum256([]byte(token))
	kh := hex.EncodeToString(h[:])
	var id int64
	var nombre string
	err := s.db.QueryRow(`SELECT id, nombre FROM api_keys WHERE key_hash=? AND activo=1`, kh).Scan(&id, &nombre)
	if err == sql.ErrNoRows {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	s.db.Exec(`UPDATE api_keys SET ultimo_uso=? WHERE id=?`, time.Now().Format("2006-01-02T15:04:05.000000"), id)
	return &Usuario{Username: "apikey:" + nombre, Tipo: "apikey", APIKeyID: id}, nil
}

// protegido envuelve un handler exigiendo autenticación (401 con el envoltorio de Python).
func (s *Servidor) protegido(h http.HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		u, err := s.autenticar(r)
		if err != nil {
			responderError(w, r, 401, "autenticacion", err.Error(), nil)
			return
		}
		h(w, r.WithContext(contextoCon(r.Context(), ctxUsuario, u)))
	}
}
