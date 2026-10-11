package servidor

import (
	"database/sql"
	"fmt"
	"net/http"
	"os"
	"path/filepath"
	"sync"
	"time"
	_ "time/tzdata" // la zona America/Santiago también donde el sistema no trae tzdata (Windows)

	"dtechile/nucleo/firma"
	"dtechile/nucleo/rvd"
	"dtechile/nucleo/sii"
)

// Estados de rvd_envios (core/scheduler.py).
const (
	rvdGenerado      = "generado"
	rvdEnviado       = "enviado"
	rvdError         = "error"
	rvdPendienteRuta = "pendiente_ruta"
)

var zonaChile = func() *time.Location {
	if l, err := time.LoadLocation("America/Santiago"); err == nil {
		return l
	}
	return time.FixedZone("CLT", -3*3600)
}()

// hoyChile es scheduler.hoy_chile: el día de hoy en Chile, sin importar dónde corra el servidor.
func hoyChile() time.Time { return time.Now().In(zonaChile) }

// programadorRVD es ProgramadorRVD: una goroutine que cada `intervalo` revisa si hay RVD
// pendientes y los genera/envía. El proceso servidor es el reloj (sin cron): igual en Windows,
// macOS y Linux. Solo corre cuando el Go está solo (sin motor Python reenviado), para no
// mandar el reporte dos veces desde la misma base.
type programadorRVD struct {
	mu              sync.Mutex
	activo          bool
	intervalo       time.Duration
	diasAtras       int
	ultimaCorrida   time.Time
	ultimoResultado []map[string]any
	parar           chan struct{}
}

func (s *Servidor) rutasRVD(mux *http.ServeMux) {
	mux.HandleFunc("GET /api/v1/rvd/estado", s.protegido(s.rvdEstado))
	mux.HandleFunc("POST /api/v1/rvd/procesar", s.protegido(s.rvdProcesar))
	mux.HandleFunc("GET /api/v1/rvd/registros/{rut}", s.protegido(s.rvdRegistros))
}

func (s *Servidor) iniciarProgramadorRVD() {
	s.rvd = &programadorRVD{intervalo: time.Duration(s.cfg.RVDIntervaloSeg) * time.Second, diasAtras: 7, parar: make(chan struct{})}
	if !s.cfg.RVDSchedulerActivo || s.cfg.MotorPython != "" {
		return
	}
	s.rvd.activo = true
	go func() {
		for {
			res := s.procesarPendientes(1, s.rvd.diasAtras, hoyChile())
			s.rvd.mu.Lock()
			s.rvd.ultimaCorrida, s.rvd.ultimoResultado = time.Now().In(zonaChile), res
			s.rvd.mu.Unlock()
			hechos := 0
			for _, r := range res {
				if om, _ := r["omitido"].(bool); !om {
					hechos++
				}
			}
			if hechos > 0 {
				s.log("RVD: %d día(s) procesado(s)", hechos)
			}
			select {
			case <-s.rvd.parar:
				return
			case <-time.After(s.rvd.intervalo):
			}
		}
	}()
	s.log("Programador de RVD iniciado (cada %ds, catch-up de %d días)", s.cfg.RVDIntervaloSeg, s.rvd.diasAtras)
}

func (s *Servidor) detenerProgramadorRVD() {
	if s.rvd != nil && s.rvd.activo {
		close(s.rvd.parar)
		s.rvd.activo = false
	}
}

// procesarPendientes es scheduler.procesar_pendientes: recorre las empresas y genera el RVD de
// los días con boletas aún no reportados, mirando `diasAtras` hacia atrás (catch-up). No
// incluye hoy: aún puede recibir boletas.
func (s *Servidor) procesarPendientes(cuenta int64, diasAtras int, hoy time.Time) []map[string]any {
	hasta := hoy.AddDate(0, 0, -1).Format("2006-01-02")
	desde := hoy.AddDate(0, 0, -diasAtras).Format("2006-01-02")
	var out []map[string]any
	negs, err := s.negociosDe(cuenta)
	if err != nil {
		return []map[string]any{{"estado": rvdError, "detalle": err.Error()}}
	}
	for _, n := range negs {
		if n.Rut == "" {
			continue
		}
		dias, err := rvd.DiasConBoletas(s.db, n.Rut, desde, hasta, s.cfg.SIIAmbiente)
		if err != nil {
			out = append(out, map[string]any{"rut": n.Rut, "estado": rvdError, "detalle": err.Error()})
			continue
		}
		for _, d := range dias {
			out = append(out, s.procesarDia(n.Rut, n.CertID, d, cuenta))
		}
	}
	return out
}

func (s *Servidor) rutaRVD(rut, dia string) string {
	carpeta := filepath.Join(s.cfg.StoragePath, "rvd")
	_ = os.MkdirAll(carpeta, 0o755)
	return filepath.Join(carpeta, fmt.Sprintf("RVD_%s_%s.xml", rut, dia))
}

// procesarDia es scheduler.procesar_dia: genera (y guarda) el RVD de un día. Idempotente: solo
// se omite lo que ya llegó al SII; un día `generado` (XML listo, no enviado) SÍ se reintenta.
func (s *Servidor) procesarDia(rut string, certID sql.NullInt64, dia string, cuenta int64) map[string]any {
	res := map[string]any{"rut": rut, "dia": dia}
	if ya, _ := rvd.Registrado(s.db, rut, dia); ya != nil && (ya.Estado == rvdEnviado || ya.Estado == rvdPendienteRuta) {
		res["estado"], res["omitido"] = "ya_estaba", true
		return res
	}
	falla := func(estado, detalle string, extra map[string]any) map[string]any {
		_ = rvd.Registrar(s.db, rut, dia, estado, 1, "", fmt.Sprint(extra["xml_path"]), detalle)
		res["estado"], res["detalle"] = estado, detalle
		for k, v := range extra {
			res[k] = v
		}
		return res
	}
	if !certID.Valid {
		return falla(rvdError, "El negocio no tiene certificado asociado: no se puede firmar el RVD.", nil)
	}
	p12, clave, err := s.descifrarCertificado(certID.Int64, cuenta)
	if err != nil {
		return falla(rvdError, "certificado: "+err.Error(), nil)
	}
	cert, err := firma.CargarP12(p12, clave)
	if err != nil {
		return falla(rvdError, "certificado: "+err.Error(), nil)
	}
	rutEnvia, err := cert.RutEmisor()
	if err != nil {
		return falla(rvdError, "certificado sin RUT: "+err.Error(), nil)
	}
	docs, err := rvd.BoletasDelDia(s.db, rut, dia, s.cfg.SIIAmbiente)
	if err != nil {
		return falla(rvdError, "boletas del día: "+err.Error(), nil)
	}
	fecha, num := s.resolucionEmisor(rut, s.cfg.SIIAmbiente)
	xml, err := rvd.GenerarFirmado(cert, rvd.Parametros{RutEmisor: rut, RutEnvia: rutEnvia, FechaResolucion: fecha, NumeroResolucion: num,
		Dia: dia, Tipos: rvd.TiposConsumo, SecEnvio: 1, Marca: s.marca(), Documentos: docs})
	if err != nil {
		s.log("RVD %s %s falló al generar: %v", rut, dia, err)
		return falla(rvdError, err.Error(), nil)
	}
	ruta := s.rutaRVD(rut, dia)
	if err := os.WriteFile(ruta, xml, 0o644); err != nil {
		return falla(rvdError, "escribir XML: "+err.Error(), nil)
	}
	// Envío por el canal de FACTURAS (DTEUpload + token SOAP), no por el REST de boletas.
	cli, err := sii.Nuevo(s.cfg.SIIAmbiente, cert)
	if err != nil {
		return falla(rvdGenerado, err.Error(), map[string]any{"xml_path": ruta})
	}
	track, _, err := rvd.Enviar(cli, xml, rut)
	if err != nil {
		s.log("RVD %s %s generado pero NO enviado: %v", rut, dia, err)
		return falla(rvdGenerado, err.Error(), map[string]any{"xml_path": ruta})
	}
	_ = rvd.Registrar(s.db, rut, dia, rvdEnviado, 1, fmt.Sprint(track), ruta, fmt.Sprintf("Enviado por DTEUpload (%s).", s.cfg.SIIAmbiente))
	s.log("RVD %s %s enviado → TrackID %d", rut, dia, track)
	res["estado"], res["track_id"], res["xml_path"] = rvdEnviado, fmt.Sprint(track), ruta
	return res
}

func (s *Servidor) rvdEstado(w http.ResponseWriter, r *http.Request) {
	p := s.rvd
	p.mu.Lock()
	defer p.mu.Unlock()
	var ultima any
	if !p.ultimaCorrida.IsZero() {
		ultima = p.ultimaCorrida.Format(time.RFC3339)
	}
	res := p.ultimoResultado
	if res == nil {
		res = []map[string]any{}
	}
	responderJSON(w, 200, map[string]any{"activo": p.activo, "intervalo_seg": int(p.intervalo / time.Second), "dias_atras": p.diasAtras,
		"zona_horaria": zonaChile.String(), "hoy_chile": hoyChile().Format("2006-01-02"), "ultima_corrida": ultima, "ultimo_resultado": res})
}

// rvdProcesar corre el catch-up a pedido (lo que el programador hace solo): útil para mandar
// hoy lo de ayer sin esperar el intervalo.
func (s *Servidor) rvdProcesar(w http.ResponseWriter, r *http.Request) {
	var cuerpo struct {
		DiasAtras int `json:"dias_atras"`
	}
	if r.ContentLength > 0 && !leerJSON(w, r, &cuerpo) {
		return
	}
	if cuerpo.DiasAtras <= 0 {
		cuerpo.DiasAtras = 7
	}
	cuenta, _ := s.cuentaID(w, r)
	if cuenta == 0 {
		cuenta = 1
	}
	res := s.procesarPendientes(cuenta, cuerpo.DiasAtras, hoyChile())
	if res == nil {
		res = []map[string]any{}
	}
	responderJSON(w, 200, map[string]any{"resultados": res})
}

func (s *Servidor) rvdRegistros(w http.ResponseWriter, r *http.Request) {
	rut := r.PathValue("rut")
	rows, err := s.db.Query(`SELECT id, rut_emisor, fecha, sec_envio, estado, COALESCE(track_id,''), COALESCE(xml_path,''), COALESCE(detalle,'') FROM rvd_envios WHERE rut_emisor=? ORDER BY fecha DESC, sec_envio DESC LIMIT 200`, rut)
	if err != nil {
		responderError(w, r, 500, "error_interno", "Ocurrió un error interno. Reporta el request_id al soporte.", nil)
		return
	}
	defer rows.Close()
	out := []rvd.Registro{}
	for rows.Next() {
		var x rvd.Registro
		if err := rows.Scan(&x.ID, &x.RutEmisor, &x.Fecha, &x.SecEnvio, &x.Estado, &x.TrackID, &x.XMLPath, &x.Detalle); err == nil {
			out = append(out, x)
		}
	}
	responderJSON(w, 200, map[string]any{"rut": rut, "registros": out})
}
