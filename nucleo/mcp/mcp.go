// Package mcp: el servidor MCP del motor (mcp_server.py) en Go. Expone el toolkit del SII como
// herramientas para una IA (Claude, Cursor, Codex, Gemini u otro cliente MCP): consultar
// autorización de empresas, folios (timbrar/anular), estado de envíos, previsualizar y emitir.
// Corre el motor (nucleo/servidor) EN EL MISMO PROCESO y llama a sus rutas sin red; las
// credenciales nunca viajan por el protocolo: cada herramienta recibe un cert_id del keystore.
//
// Transportes: ServirStdio (JSON-RPC por líneas, el de los clientes locales) y Handler (HTTP:
// POST /mcp con Authorization: Bearer). Lo usan nucleo-mcp y la app de escritorio (--mcp).
package mcp

import (
	"bufio"
	"crypto/subtle"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"

	"dtechile/nucleo/servidor"
)

// Version del servidor MCP (serverInfo.version).
const Version = "1.0.0"

// Instrucciones que el servidor entrega al cliente en initialize.
var Instrucciones = "Motor de facturación electrónica DTE para el SII de Chile. Usa estas " +
	"herramientas para consultar autorización de empresas, gestionar folios " +
	"(timbrar/anular), y consultar el estado de envíos. Los tipos de DTE son: 33 " +
	"Factura, 34 Factura Exenta, 39/41 Boletas, 52 Guía, 56 Nota Débito, 61 Nota " +
	"Crédito. Los RUT van con guión y dígito verificador (ej. 76111111-6). El " +
	"'ambiente' es 'certificacion' (pruebas, Maullín) o 'produccion' (Palena)."

type herramienta struct {
	Nombre      string
	Descripcion string
	Esquema     map[string]any
	Ejecutar    func(args map[string]any) (any, error)
}

// Servidor es el servidor MCP sobre un motor en proceso.
type Servidor struct {
	s           *servidor.Servidor
	cuenta      int64
	ambiente    string
	herramienta []herramienta
}

func prop(tipo, desc string) map[string]any { return map[string]any{"type": tipo, "description": desc} }

func esquema(req []string, props map[string]any) map[string]any {
	e := map[string]any{"type": "object", "properties": props}
	if len(req) > 0 {
		e["required"] = req
	}
	return e
}

func texto(a map[string]any, k, def string) string {
	if v, ok := a[k]; ok && v != nil {
		if s, es := v.(string); es && s != "" {
			return s
		}
		return fmt.Sprint(v)
	}
	return def
}

func entero(a map[string]any, k string, def int) int {
	switch v := a[k].(type) {
	case float64:
		return int(v)
	case string:
		var n int
		fmt.Sscan(v, &n)
		return n
	}
	return def
}

// llamar ejecuta una ruta del motor en proceso; los errores del envoltorio salen como error de tool.
func (m *Servidor) llamar(metodo, ruta string, cuerpo any) (any, error) {
	var b []byte
	if cuerpo != nil {
		b, _ = json.Marshal(cuerpo)
	}
	st, resp := m.s.Llamar(metodo, ruta, b)
	var v any
	if err := json.Unmarshal(resp, &v); err != nil {
		return nil, fmt.Errorf("respuesta no JSON (%d): %.300s", st, string(resp))
	}
	if st >= 400 {
		if mm, ok := v.(map[string]any); ok {
			if e, ok := mm["error"].(map[string]any); ok {
				return nil, fmt.Errorf("[%v] %v", e["codigo"], e["mensaje"])
			}
		}
		return nil, fmt.Errorf("HTTP %d: %.300s", st, string(resp))
	}
	return v, nil
}

func (m *Servidor) registrar() {
	amb := m.ambiente
	certID := prop("integer", "id del certificado en el keystore (ver listar_certificados)")
	ambiente := prop("string", "certificacion | produccion (default: el del .env)")
	m.herramienta = []herramienta{
		{"salud", "Estado del servidor MCP: ambiente por defecto, cuenta y nº de certificados.", esquema(nil, map[string]any{}), func(a map[string]any) (any, error) {
			v, err := m.llamar("GET", "/api/v1/keystore/certificados", nil)
			if err != nil {
				return nil, err
			}
			n := 0
			if l, ok := v.([]any); ok {
				n = len(l)
			}
			return map[string]any{"servicio": "dte-chile-mcp", "motor": "go", "ambiente_defecto": amb, "cuenta_id": m.cuenta, "certificados": n}, nil
		}},
		{"listar_certificados", "Lista los certificados cargados en el keystore (id, RUT, nombre, vencimiento). Usa el id como cert_id en las demás herramientas. NUNCA expone la clave privada.", esquema(nil, map[string]any{}), func(a map[string]any) (any, error) {
			return m.llamar("GET", "/api/v1/keystore/certificados", nil)
		}},
		{"listar_negocios", "Lista los negocios (empresas) registrados en la cuenta con su cert asociado.", esquema(nil, map[string]any{}), func(a map[string]any) (any, error) {
			return m.llamar("GET", "/api/v1/keystore/negocios", nil)
		}},
		{"empresa_autorizada", "¿Qué DTE está autorizada a emitir una empresa? (consulta PÚBLICA, sin cert). Devuelve razón social, nº/fecha de resolución y los tipos autorizados; o null si no aparece autorizada.", esquema([]string{"rut"}, map[string]any{"rut": prop("string", "RUT con guión y DV"), "ambiente": ambiente}), func(a map[string]any) (any, error) {
			v, err := m.llamar("GET", "/api/v1/keystore/empresa?rut="+texto(a, "rut", "")+"&ambiente="+texto(a, "ambiente", amb), nil)
			if err != nil && strings.HasPrefix(err.Error(), "[no_encontrado]") {
				return nil, nil
			}
			return v, err
		}},
		{"diagnostico", "Investigación automática (SOLO LECTURA) del estado de una empresa en el SII + plan de acciones (modo auto/consentimiento/humano). Primer paso del onboarding.", esquema([]string{"rut", "cert_id"}, map[string]any{"rut": prop("string", "RUT con guión"), "cert_id": certID, "nombre_sistema": prop("string", "cómo llamar al software propio")}), func(a map[string]any) (any, error) {
			return m.llamar("GET", fmt.Sprintf("/api/v1/onboarding/diagnostico?cert_id=%d&rut=%s&nombre_sistema=%s", entero(a, "cert_id", 0), texto(a, "rut", ""), texto(a, "nombre_sistema", "tu software propio")), nil)
		}},
		{"diagnostico_cartera", "Diagnostica TODAS las empresas asociadas a un certificado (resumen por empresa). Solo lectura.", esquema([]string{"cert_id"}, map[string]any{"cert_id": certID, "nombre_sistema": prop("string", "cómo llamar al software propio")}), func(a map[string]any) (any, error) {
			return m.llamar("GET", fmt.Sprintf("/api/v1/onboarding/cartera?cert_id=%d&nombre_sistema=%s", entero(a, "cert_id", 0), texto(a, "nombre_sistema", "tu software propio")), nil)
		}},
		{"salud_folios", "Salud de folios/CAF de una empresa — LOCAL, sin tocar el SII: CAF vencidos (6 meses, CAF-3-517) y folios agotándose, con veredicto ok/atencion/critico.", esquema([]string{"rut"}, map[string]any{"rut": prop("string", "RUT con guión")}), func(a map[string]any) (any, error) {
			return m.llamar("GET", "/api/v1/monitoreo/folios?rut="+texto(a, "rut", ""), nil)
		}},
		{"salud_folios_cartera", "Salud de folios/CAF de TODAS las empresas cargadas — LOCAL, sin SII, ordenadas por urgencia.", esquema(nil, map[string]any{}), func(a map[string]any) (any, error) {
			return m.llamar("GET", "/api/v1/monitoreo/folios/cartera", nil)
		}},
		{"situacion_folios", "Situación de folios por tipo: si puede timbrar y si está bloqueado (anti-acaparamiento). Requiere cert_id.", esquema([]string{"rut", "cert_id"}, map[string]any{"rut": prop("string", ""), "cert_id": certID, "tipos": map[string]any{"type": "array", "items": map[string]any{"type": "integer"}, "description": "tipos de DTE (ej. [33, 61]); si se omite, los habituales"}, "ambiente": ambiente}), func(a map[string]any) (any, error) {
			return m.llamar("POST", "/api/v1/portal/situacion", map[string]any{"cert_id": entero(a, "cert_id", 0), "rut": texto(a, "rut", ""), "tipos": a["tipos"], "ambiente": texto(a, "ambiente", amb)})
		}},
		{"timbrajes", "Rangos de folios ya autorizados (timbrados) para un RUT y tipo de DTE.", esquema([]string{"rut", "tipo_dte", "cert_id"}, map[string]any{"rut": prop("string", ""), "tipo_dte": prop("integer", ""), "cert_id": certID, "ambiente": ambiente}), func(a map[string]any) (any, error) {
			return m.llamar("POST", "/api/v1/portal/timbrajes", map[string]any{"cert_id": entero(a, "cert_id", 0), "rut": texto(a, "rut", ""), "tipo_dte": entero(a, "tipo_dte", 33), "ambiente": texto(a, "ambiente", amb)})
		}},
		{"datos_software", "Software de emisión registrado y resolución del contribuyente en el SII.", esquema([]string{"rut", "cert_id"}, map[string]any{"rut": prop("string", ""), "cert_id": certID, "ambiente": ambiente}), func(a map[string]any) (any, error) {
			return m.llamar("POST", "/api/v1/portal/software", map[string]any{"cert_id": entero(a, "cert_id", 0), "rut": texto(a, "rut", ""), "ambiente": texto(a, "ambiente", amb)})
		}},
		{"empresas_del_certificado", "Empresas a las que está asociado el titular de un certificado (mandatario).", esquema([]string{"cert_id"}, map[string]any{"cert_id": certID, "ambiente": ambiente}), func(a map[string]any) (any, error) {
			return m.llamar("POST", "/api/v1/portal/empresas", map[string]any{"cert_id": entero(a, "cert_id", 0), "ambiente": texto(a, "ambiente", amb)})
		}},
		{"folios_anulables", "Rangos de folios que se pueden ANULAR (no recepcionados) para un tipo de DTE.", esquema([]string{"rut", "tipo_dte", "cert_id"}, map[string]any{"rut": prop("string", ""), "tipo_dte": prop("integer", ""), "cert_id": certID, "ambiente": ambiente}), func(a map[string]any) (any, error) {
			return m.llamar("POST", "/api/v1/portal/anulables", map[string]any{"cert_id": entero(a, "cert_id", 0), "rut": texto(a, "rut", ""), "tipo_dte": entero(a, "tipo_dte", 33), "ambiente": texto(a, "ambiente", amb)})
		}},
		{"estado_envio", "Estado de un envío al SII por su TrackID (EPR/aceptado/rechazado + glosa).", esquema([]string{"track_id", "rut", "cert_id"}, map[string]any{"track_id": prop("integer", ""), "rut": prop("string", "RUT con guión"), "cert_id": certID, "ambiente": ambiente}), func(a map[string]any) (any, error) {
			v, err := m.llamar("POST", "/api/v1/estado/lote", map[string]any{"track_ids": []int{entero(a, "track_id", 0)}, "rut_empresa": texto(a, "rut", ""), "cert_id": entero(a, "cert_id", 0), "ambiente": texto(a, "ambiente", amb)})
			if err != nil {
				return nil, err
			}
			if mm, ok := v.(map[string]any); ok {
				if d, ok := mm["detalles"].([]any); ok && len(d) == 1 {
					return d[0], nil
				}
			}
			return v, nil
		}},
		{"estado_envios", "Estado de VARIOS envíos al SII de una vez (por TrackID) + resumen accionable (aceptados/rechazados/pendientes/todos_resueltos).", esquema([]string{"track_ids", "rut", "cert_id"}, map[string]any{"track_ids": map[string]any{"type": "array", "items": map[string]any{"type": "integer"}}, "rut": prop("string", ""), "cert_id": certID, "ambiente": ambiente}), func(a map[string]any) (any, error) {
			return m.llamar("POST", "/api/v1/estado/lote", map[string]any{"track_ids": a["track_ids"], "rut_empresa": texto(a, "rut", ""), "cert_id": entero(a, "cert_id", 0), "ambiente": texto(a, "ambiente", amb)})
		}},
		{"solicitar_folios", "TIMBRA (solicita) folios nuevos al SII. ACCIÓN REAL: consume cupo de timbraje. Verifica bloqueo antes; forzar=true solo si sabes lo que haces. Devuelve {obtenido, info, caf_xml}.", esquema([]string{"rut", "tipo_dte", "cert_id"}, map[string]any{"rut": prop("string", ""), "tipo_dte": prop("integer", ""), "cert_id": certID, "cantidad": prop("integer", "default 1"), "ambiente": ambiente, "forzar": prop("boolean", "saltar el tope por sesión")}), func(a map[string]any) (any, error) {
			f, _ := a["forzar"].(bool)
			return m.llamar("POST", "/api/v1/portal/solicitar", map[string]any{"cert_id": entero(a, "cert_id", 0), "rut": texto(a, "rut", ""), "tipo_dte": entero(a, "tipo_dte", 33), "cantidad": entero(a, "cantidad", 1), "ambiente": texto(a, "ambiente", amb), "forzar": f})
		}},
		{"anular_folios", "ANULA un rango de folios NO recepcionados. ACCIÓN REAL E IRREVERSIBLE. Solo con el mandatario que los timbró.", esquema([]string{"rut", "tipo_dte", "folio_desde", "folio_hasta", "cert_id"}, map[string]any{"rut": prop("string", ""), "tipo_dte": prop("integer", ""), "folio_desde": prop("integer", ""), "folio_hasta": prop("integer", ""), "cert_id": certID, "motivo": prop("string", ""), "ambiente": ambiente}), func(a map[string]any) (any, error) {
			return m.llamar("POST", "/api/v1/portal/anular", map[string]any{"cert_id": entero(a, "cert_id", 0), "rut": texto(a, "rut", ""), "tipo_dte": entero(a, "tipo_dte", 33), "folio_desde": entero(a, "folio_desde", 0), "folio_hasta": entero(a, "folio_hasta", 0), "motivo": texto(a, "motivo", ""), "ambiente": texto(a, "ambiente", amb)})
		}},
		{"enviar_dte", "ENVÍA un EnvioDTE (o EnvioBOLETA con tipo_dte 39/41) firmado al SII. ACCIÓN REAL. Devuelve el TrackID; luego consulta estado_envio.", esquema([]string{"xml_envio_b64", "rut_empresa", "cert_id"}, map[string]any{"xml_envio_b64": prop("string", "el sobre en base64 (el xml_envio_b64 de emitir_dte)"), "rut_empresa": prop("string", "RUT con guión"), "cert_id": certID, "tipo_dte": prop("integer", "default 33"), "ambiente": ambiente}), func(a map[string]any) (any, error) {
			return m.llamar("POST", "/api/v1/dte/enviar-keystore", map[string]any{"xml_envio_b64": texto(a, "xml_envio_b64", ""), "rut_empresa": texto(a, "rut_empresa", ""), "cert_id": entero(a, "cert_id", 0), "tipo_dte": entero(a, "tipo_dte", 33), "ambiente": texto(a, "ambiente", amb)})
		}},
		{"previsualizar_dte", "Previsualiza un DTE: FIRMADO + timbrado + XSD + PDF, SIN enviarlo ni consumir folios. Devuelve totales, XSD y XML/PDF en base64.", esquema([]string{"dte", "cert_id"}, map[string]any{"dte": map[string]any{"type": "object", "description": "DTEInput: tipo_dte, folio (0 = el primero del CAF), fecha_emision, emisor, receptor, items, referencias"}, "cert_id": certID}), func(a map[string]any) (any, error) {
			return m.llamar("POST", "/api/v1/dte/previsualizar", map[string]any{"dte": a["dte"], "cert_id": entero(a, "cert_id", 0)})
		}},
		{"emitir_dte", "EMITE un DTE o BOLETA completo. ACCIÓN REAL: consume un folio, firma, genera PDF y persiste. NO envía al SII (usa enviar_dte con el xml_envio_b64 que devuelve). cert_id del keystore; si se omite, el certificado del .env.", esquema([]string{"dte"}, map[string]any{"dte": map[string]any{"type": "object", "description": "DTEInput (folio 0 = automático)"}, "cert_id": certID}), func(a map[string]any) (any, error) {
			cuerpo := map[string]any{"dte": a["dte"]}
			if _, ok := a["cert_id"]; ok {
				cuerpo["cert_id"] = entero(a, "cert_id", 0)
			}
			return m.llamar("POST", "/api/v1/dte/emitir", cuerpo)
		}},
	}
}

type rpcReq struct {
	JSONRPC string          `json:"jsonrpc"`
	ID      json.RawMessage `json:"id"`
	Method  string          `json:"method"`
	Params  json.RawMessage `json:"params"`
}

func respuesta(id json.RawMessage, result any) map[string]any {
	return map[string]any{"jsonrpc": "2.0", "id": id, "result": result}
}

func errorRPC(id json.RawMessage, code int, msg string) map[string]any {
	return map[string]any{"jsonrpc": "2.0", "id": id, "error": map[string]any{"code": code, "message": msg}}
}

// Atender resuelve un mensaje JSON-RPC del protocolo MCP (nil = notificación sin respuesta).
func (m *Servidor) Atender(raw []byte) any {
	var req rpcReq
	if err := json.Unmarshal(raw, &req); err != nil {
		return errorRPC(nil, -32700, "JSON inválido")
	}
	switch req.Method {
	case "initialize":
		return respuesta(req.ID, map[string]any{"protocolVersion": "2025-06-18", "capabilities": map[string]any{"tools": map[string]any{}},
			"serverInfo": map[string]any{"name": "dte-chile", "version": Version}, "instructions": Instrucciones})
	case "notifications/initialized", "notifications/cancelled":
		return nil
	case "ping":
		return respuesta(req.ID, map[string]any{})
	case "tools/list":
		var lista []map[string]any
		for _, h := range m.herramienta {
			lista = append(lista, map[string]any{"name": h.Nombre, "description": h.Descripcion, "inputSchema": h.Esquema})
		}
		return respuesta(req.ID, map[string]any{"tools": lista})
	case "tools/call":
		var p struct {
			Name      string         `json:"name"`
			Arguments map[string]any `json:"arguments"`
		}
		_ = json.Unmarshal(req.Params, &p)
		if p.Arguments == nil {
			p.Arguments = map[string]any{}
		}
		for _, h := range m.herramienta {
			if h.Nombre != p.Name {
				continue
			}
			v, err := h.Ejecutar(p.Arguments)
			if err != nil {
				return respuesta(req.ID, map[string]any{"content": []map[string]any{{"type": "text", "text": err.Error()}}, "isError": true})
			}
			b, _ := json.Marshal(v)
			return respuesta(req.ID, map[string]any{"content": []map[string]any{{"type": "text", "text": string(b)}}, "structuredContent": v})
		}
		return errorRPC(req.ID, -32602, "herramienta desconocida: "+p.Name)
	}
	if req.ID == nil {
		return nil
	}
	return errorRPC(req.ID, -32601, "método no soportado: "+req.Method)
}

// Nuevo arma el servidor MCP sobre un motor ya levantado. cuenta = usuario dueño de los
// negocios (MCP_CUENTA_ID; 1 = admin); ambiente = el del .env, por defecto en cada tool.
func Nuevo(s *servidor.Servidor, cuenta int64, ambiente string) *Servidor {
	m := &Servidor{s: s, cuenta: cuenta, ambiente: ambiente}
	m.registrar()
	return m
}

// Herramientas: nombres de las tools registradas, en orden.
func (m *Servidor) Herramientas() []string {
	var n []string
	for _, h := range m.herramienta {
		n = append(n, h.Nombre)
	}
	return n
}

// ServirStdio atiende el transporte stdio: un mensaje JSON por línea, respuestas por línea.
// Vuelve cuando se cierra la entrada.
func (m *Servidor) ServirStdio(r io.Reader, w io.Writer) {
	lector := bufio.NewReaderSize(r, 1<<20)
	enc := json.NewEncoder(w)
	for {
		linea, err := lector.ReadBytes('\n')
		if len(strings.TrimSpace(string(linea))) > 0 {
			if resp := m.Atender(linea); resp != nil {
				_ = enc.Encode(resp)
			}
		}
		if err != nil {
			return
		}
	}
}

// Handler es el transporte HTTP (POST /mcp). Acepta el token fijo (MCP_AUTH_TOKEN) o un JWT
// del motor. Pensado para 127.0.0.1 o detrás de un proxy con TLS; nunca HTTP plano a internet.
func (m *Servidor) Handler(token string) http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("POST /mcp", func(w http.ResponseWriter, r *http.Request) {
		auth := r.Header.Get("Authorization")
		t := ""
		if strings.HasPrefix(strings.ToLower(auth), "bearer ") {
			t = strings.TrimSpace(auth[7:])
		}
		ok := t != "" && token != "" && subtle.ConstantTimeCompare([]byte(t), []byte(token)) == 1
		if !ok && t != "" {
			ok = m.s.TokenValido(t) // un JWT del proyecto
		}
		if !ok {
			w.Header().Set("Content-Type", "application/json")
			w.WriteHeader(401)
			_, _ = w.Write([]byte(`{"error":{"codigo":"autenticacion","mensaje":"Token MCP invalido o ausente (Authorization: Bearer)."}}`))
			return
		}
		b, _ := io.ReadAll(http.MaxBytesReader(w, r.Body, 4<<20))
		resp := m.Atender(b)
		w.Header().Set("Content-Type", "application/json")
		if resp == nil {
			w.WriteHeader(202)
			return
		}
		_ = json.NewEncoder(w).Encode(resp)
	})
	return mux
}
