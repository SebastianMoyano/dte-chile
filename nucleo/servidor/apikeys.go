package servidor

// /api/v1/apikeys: crear, listar, revocar. Exige un USUARIO (JWT o clave de la app), no una
// API key: una key no puede crear más keys (api/routes/apikeys.py::requerir_usuario).

import (
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"net/http"
	"strconv"
	"strings"
)

func (s *Servidor) rutasAPIKeys(mux *http.ServeMux) {
	mux.HandleFunc("POST /api/v1/apikeys", s.requiereUsuario(s.crearAPIKey))
	mux.HandleFunc("GET /api/v1/apikeys", s.requiereUsuario(s.listarAPIKeys))
	mux.HandleFunc("DELETE /api/v1/apikeys/{id}", s.requiereUsuario(s.revocarAPIKey))
}

// requiereUsuario es requerir_usuario: SOLO un JWT de usuario (ni API key ni la clave de la app).
func (s *Servidor) requiereUsuario(h http.HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		u, err := s.autenticar(r)
		if err != nil || u.Via != "jwt" {
			responderError(w, r, 401, "autenticacion", "Esta acción requiere un usuario autenticado (JWT), no una API key.", nil)
			return
		}
		h(w, r.WithContext(contextoCon(r.Context(), ctxUsuario, u)))
	}
}

// generarAPIKey es crear_api_key: "dte_" + 32 bytes aleatorios en base64url (sin relleno).
func generarAPIKey() string {
	b := make([]byte, 32)
	rand.Read(b)
	return "dte_" + base64.RawURLEncoding.EncodeToString(b)
}

func (s *Servidor) crearAPIKey(w http.ResponseWriter, r *http.Request) {
	var in struct {
		Nombre *string `json:"nombre"`
	}
	if !leerJSON(w, r, &in) {
		return
	}
	if in.Nombre == nil {
		faltan(w, r, "nombre")
		return
	}
	nombre := strings.TrimSpace(*in.Nombre)
	if l := len([]rune(*in.Nombre)); l < 1 || l > 80 {
		responderError(w, r, 422, "validacion", "Los datos enviados no son válidos.", map[string]any{"errores": []map[string]any{{"loc": []any{"body", "nombre"}, "msg": "1-80 caracteres", "type": "value_error"}}})
		return
	}
	clave := generarAPIKey()
	h := sha256.Sum256([]byte(clave))
	ahora := ahoraPython()
	res, err := s.db.Exec(`INSERT INTO api_keys (nombre, prefijo, key_hash, activo, creado) VALUES (?,?,?,1,?)`, nombre, clave[:12], hex.EncodeToString(h[:]), ahora)
	if err != nil {
		responderError(w, r, 500, "error_interno", "Ocurrió un error interno. Reporta el request_id al soporte.", nil)
		return
	}
	id, _ := res.LastInsertId()
	responderJSON(w, 201, map[string]any{"api_key": clave, "aviso": "Guarda esta clave AHORA; no se vuelve a mostrar.",
		"id": id, "nombre": nombre, "prefijo": clave[:12], "creado": ahora, "activo": true})
}

func (s *Servidor) listarAPIKeys(w http.ResponseWriter, r *http.Request) {
	rows, err := s.db.Query(`SELECT id, nombre, prefijo, activo, creado, ultimo_uso FROM api_keys ORDER BY id DESC`)
	if err != nil {
		responderError(w, r, 500, "error_interno", "Ocurrió un error interno. Reporta el request_id al soporte.", nil)
		return
	}
	defer rows.Close()
	out := []map[string]any{}
	for rows.Next() {
		var id int64
		var nombre, prefijo, creado string
		var activo int
		var ultimo nullString
		rows.Scan(&id, &nombre, &prefijo, &activo, &creado, &ultimo)
		out = append(out, map[string]any{"id": id, "nombre": nombre, "prefijo": prefijo, "activo": activo, "creado": creado, "ultimo_uso": ultimo.valor()})
	}
	responderJSON(w, 200, out)
}

func (s *Servidor) revocarAPIKey(w http.ResponseWriter, r *http.Request) {
	id, err := strconv.ParseInt(r.PathValue("id"), 10, 64)
	if err != nil {
		responderError(w, r, 422, "validacion", "Los datos enviados no son válidos.", nil)
		return
	}
	res, _ := s.db.Exec(`UPDATE api_keys SET activo=0 WHERE id=?`, id)
	if n, _ := res.RowsAffected(); n == 0 {
		responderError(w, r, 404, "no_encontrado", "API key no encontrada", nil)
		return
	}
	responderJSON(w, 200, map[string]any{"revocada": id})
}
