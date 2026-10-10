package servidor

// /api/v1/auth/*: login (sha256_crypt de passlib + JWT HS256), registro, usuarios, me.
// Réplica de api/routes/auth.py y core/auth.py / core/models.py.

import (
	"database/sql"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/GehirnInc/crypt/common"
	"github.com/GehirnInc/crypt/sha256_crypt"
)

const roundsPasslib = 535000 // sha256_crypt.default_rounds de passlib

func hashPassword(clave string) (string, error) {
	salt := (&common.Salt{MagicPrefix: []byte("$5$"), SaltLenMax: 16, SaltLenMin: 1, RoundsDefault: 5000, RoundsMin: 1000, RoundsMax: 999999999}).GenerateWRounds(16, roundsPasslib)
	return sha256_crypt.New().Generate([]byte(clave), salt)
}

func verificarPassword(clave, hash string) bool {
	return sha256_crypt.New().Verify(hash, []byte(clave)) == nil
}

func ahoraPython() string { return time.Now().Format("2006-01-02T15:04:05.000000") }

// crearJWT es crear_access_token({"sub": username}).
func (s *Servidor) crearJWT(username string) string {
	cab := base64.RawURLEncoding.EncodeToString([]byte(`{"alg":"HS256","typ":"JWT"}`))
	exp := time.Now().UTC().Add(time.Duration(s.cfg.JWTExpiraMin) * time.Minute).Unix()
	cuerpo, _ := json.Marshal(map[string]any{"sub": username, "exp": exp})
	b := base64.RawURLEncoding.EncodeToString(cuerpo)
	firma := firmaHS256(s.cfg.JWTSecret, cab+"."+b)
	return cab + "." + b + "." + firma
}

func (s *Servidor) registrarLog(accion, detalle string) {
	s.db.Exec(`INSERT INTO audit_log (accion, tipo_dte, folio, rut_emisor, detalle, ip_origen, creado_en) VALUES (?, NULL, NULL, NULL, ?, NULL, ?)`,
		accion, detalle, ahoraPython())
}

func leerJSON(w http.ResponseWriter, r *http.Request, v any) bool {
	if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 1<<20)).Decode(v); err != nil {
		responderError(w, r, 422, "validacion", "Los datos enviados no son válidos.", map[string]any{"errores": []map[string]any{{"loc": []any{"body"}, "msg": "JSON inválido", "type": "json_invalid"}}})
		return false
	}
	return true
}

func faltan(w http.ResponseWriter, r *http.Request, campos ...string) bool {
	if len(campos) == 0 {
		return false
	}
	errs := []map[string]any{}
	for _, c := range campos {
		errs = append(errs, map[string]any{"loc": []any{"body", c}, "msg": "Field required", "type": "missing"})
	}
	responderError(w, r, 422, "validacion", "Los datos enviados no son válidos.", map[string]any{"errores": errs})
	return true
}

func (s *Servidor) rutasAuth(mux *http.ServeMux) {
	mux.HandleFunc("POST /api/v1/auth/login", s.login)
	mux.HandleFunc("POST /api/v1/auth/registro", s.registro)
	mux.HandleFunc("GET /api/v1/auth/usuarios", s.protegido(s.listarUsuarios))
	mux.HandleFunc("DELETE /api/v1/auth/usuarios/{id}", s.protegido(s.desactivarUsuario))
	mux.HandleFunc("GET /api/v1/auth/me", s.protegido(s.perfil))
}

type filaUsuario struct {
	ID                    int64
	Username, Hash        string
	NombreCompleto, Email sql.NullString
	CreadoEn              string
	UltimoAcceso          sql.NullString
}

func (s *Servidor) usuarioCompleto(username string) (*filaUsuario, error) {
	var u filaUsuario
	err := s.db.QueryRow(`SELECT id, username, hashed_password, nombre_completo, email, creado_en, ultimo_acceso FROM usuarios WHERE username=? AND activo=1`, username).
		Scan(&u.ID, &u.Username, &u.Hash, &u.NombreCompleto, &u.Email, &u.CreadoEn, &u.UltimoAcceso)
	if err == sql.ErrNoRows {
		return nil, nil
	}
	return &u, err
}

func nulo(s sql.NullString) any {
	if s.Valid {
		return s.String
	}
	return nil
}

func (s *Servidor) login(w http.ResponseWriter, r *http.Request) {
	var in struct {
		Username *string `json:"username"`
		Password *string `json:"password"`
	}
	if !leerJSON(w, r, &in) {
		return
	}
	var f []string
	if in.Username == nil {
		f = append(f, "username")
	}
	if in.Password == nil {
		f = append(f, "password")
	}
	if faltan(w, r, f...) {
		return
	}
	u, err := s.usuarioCompleto(*in.Username)
	if err != nil {
		responderError(w, r, 500, "error_interno", "Ocurrió un error interno. Reporta el request_id al soporte.", nil)
		return
	}
	if u == nil || !verificarPassword(*in.Password, u.Hash) {
		responderError(w, r, 401, "autenticacion", "Credenciales inválidas", nil)
		return
	}
	s.registrarLog("login", "Login exitoso: "+u.Username)
	responderJSON(w, 200, map[string]any{"access_token": s.crearJWT(u.Username), "token_type": "bearer", "username": u.Username, "nombre_completo": nulo(u.NombreCompleto)})
}

func (s *Servidor) registro(w http.ResponseWriter, r *http.Request) {
	var in struct {
		Username       *string `json:"username"`
		Password       *string `json:"password"`
		NombreCompleto *string `json:"nombre_completo"`
		Email          *string `json:"email"`
	}
	if !leerJSON(w, r, &in) {
		return
	}
	var f []string
	if in.Username == nil {
		f = append(f, "username")
	}
	if in.Password == nil {
		f = append(f, "password")
	}
	if faltan(w, r, f...) {
		return
	}
	if l := len([]rune(*in.Username)); l < 3 || l > 50 || len([]rune(*in.Password)) < 6 {
		responderError(w, r, 422, "validacion", "Los datos enviados no son válidos.", map[string]any{"errores": []map[string]any{{"loc": []any{"body"}, "msg": "username 3-50 y password ≥ 6", "type": "value_error"}}})
		return
	}
	var n int
	s.db.QueryRow(`SELECT COUNT(*) FROM usuarios WHERE username=? AND activo=1`, *in.Username).Scan(&n)
	if n > 0 {
		responderError(w, r, 409, "conflicto", fmt.Sprintf("El usuario '%s' ya existe", *in.Username), nil)
		return
	}
	h, err := hashPassword(*in.Password)
	if err != nil {
		responderError(w, r, 500, "error_interno", "Ocurrió un error interno. Reporta el request_id al soporte.", nil)
		return
	}
	res, err := s.db.Exec(`INSERT INTO usuarios (username, hashed_password, nombre_completo, email, creado_en) VALUES (?, ?, ?, ?, ?)`,
		*in.Username, h, textoONulo(in.NombreCompleto), textoONulo(in.Email), ahoraPython())
	if err != nil {
		responderError(w, r, 409, "conflicto", fmt.Sprintf("El usuario '%s' ya existe", *in.Username), nil)
		return
	}
	id, _ := res.LastInsertId()
	s.registrarLog("registro_usuario", "Nuevo usuario registrado: "+*in.Username)
	responderJSON(w, 201, map[string]any{"id": id, "username": *in.Username, "mensaje": fmt.Sprintf("Usuario '%s' registrado correctamente", *in.Username)})
}

func textoONulo(p *string) any {
	if p == nil {
		return nil
	}
	return *p
}

func (s *Servidor) listarUsuarios(w http.ResponseWriter, r *http.Request) {
	rows, err := s.db.Query(`SELECT id, username, nombre_completo, email, activo, creado_en, ultimo_acceso FROM usuarios WHERE activo=1`)
	if err != nil {
		responderError(w, r, 500, "error_interno", "Ocurrió un error interno. Reporta el request_id al soporte.", nil)
		return
	}
	defer rows.Close()
	out := []map[string]any{}
	for rows.Next() {
		var id int64
		var username, creado string
		var nombre, email, ultimo sql.NullString
		var activo int
		rows.Scan(&id, &username, &nombre, &email, &activo, &creado, &ultimo)
		out = append(out, map[string]any{"id": id, "username": username, "nombre_completo": nulo(nombre), "email": nulo(email), "creado_en": creado, "ultimo_acceso": nulo(ultimo)})
	}
	responderJSON(w, 200, out)
}

func (s *Servidor) desactivarUsuario(w http.ResponseWriter, r *http.Request) {
	id, err := strconv.ParseInt(r.PathValue("id"), 10, 64)
	if err != nil {
		responderError(w, r, 422, "validacion", "Los datos enviados no son válidos.", map[string]any{"errores": []map[string]any{{"loc": []any{"path", "user_id"}, "msg": "Input should be a valid integer", "type": "int_parsing"}}})
		return
	}
	u := usuarioDe(r)
	if u.Tipo == "usuario" && u.ID == id {
		responderError(w, r, 422, "validacion", "No puedes desactivar tu propio usuario", nil)
		return
	}
	s.db.Exec(`UPDATE usuarios SET activo=0 WHERE id=?`, id)
	s.registrarLog("desactivar_usuario", fmt.Sprintf("Usuario %d desactivado por %s", id, u.Username))
	responderJSON(w, 200, map[string]any{"mensaje": fmt.Sprintf("Usuario %d desactivado correctamente", id)})
}

func (s *Servidor) perfil(w http.ResponseWriter, r *http.Request) {
	u := usuarioDe(r)
	if u.Tipo != "usuario" {
		// Python devuelve el dict de la API key (id None, sin creado_en → KeyError 500); aquí un 422 claro.
		responderError(w, r, 422, "validacion", "El perfil es de usuarios (JWT), no de API keys.", nil)
		return
	}
	f, err := s.usuarioCompleto(u.Username)
	if err != nil || f == nil {
		responderError(w, r, 404, "no_encontrado", "Usuario no encontrado", nil)
		return
	}
	responderJSON(w, 200, map[string]any{"id": f.ID, "username": f.Username, "nombre_completo": nulo(f.NombreCompleto), "email": nulo(f.Email), "creado_en": f.CreadoEn, "ultimo_acceso": nulo(f.UltimoAcceso)})
}

var _ = strings.TrimSpace
