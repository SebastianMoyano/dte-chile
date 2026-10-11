// Package almacen es el acceso a la MISMA base SQLite del motor Python (mismo archivo,
// mismo esquema; el esquema lo crea Python en `core/database.py::init_db`, aquí solo se usa).
//
// Lo importante está en ConsumirSiguienteFolio: réplica de core/models.py::
// consumir_siguiente_folio, una sola transacción `BEGIN IMMEDIATE` que lee y avanza el
// folio. Separar la lectura del avance reintroduce la carrera TOCTOU (dos emisiones con el
// mismo folio) que ese candado evita. Python y Go pueden emitir alternados o a la vez sobre
// la misma base sin repetir ni saltar folios: eso lo prueba test_fase2.py.
package almacen

import (
	"database/sql"
	"errors"
	"fmt"
	"strings"
	"time"

	_ "modernc.org/sqlite"
)

type Almacen struct{ db *sql.DB }

type CAF struct {
	ID             int64
	TipoDTE        int
	RutEmisor      string
	FolioDesde     int
	FolioHasta     int
	FolioSiguiente int
	XML            string
}

func Abrir(ruta string) (*Almacen, error) {
	db, err := sql.Open("sqlite", ruta+"?_pragma=busy_timeout(5000)&_pragma=journal_mode(WAL)&_pragma=foreign_keys(ON)")
	if err != nil {
		return nil, err
	}
	if err := db.Ping(); err != nil {
		return nil, err
	}
	return &Almacen{db: db}, nil
}

func (a *Almacen) Cerrar() error { return a.db.Close() }

// CAFActivo es obtener_caf_activo: el CAF activo de mayor folio_desde.
func (a *Almacen) CAFActivo(rut string, tipo int) (*CAF, error) {
	c := &CAF{}
	err := a.db.QueryRow(
		"SELECT id, tipo_dte, rut_emisor, folio_desde, folio_hasta, folio_siguiente, caf_xml FROM cafs "+
			"WHERE rut_emisor=? AND tipo_dte=? AND activo=1 ORDER BY folio_desde DESC LIMIT 1", rut, tipo).
		Scan(&c.ID, &c.TipoDTE, &c.RutEmisor, &c.FolioDesde, &c.FolioHasta, &c.FolioSiguiente, &c.XML)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, nil
	}
	return c, err
}

// ErrSinFolios: no hay CAF activo o se agotó su rango.
var ErrSinFolios = errors.New("no hay folios disponibles")

// ConsumirSiguienteFolio toma y avanza el folio en una transacción BEGIN IMMEDIATE
// (reintenta hasta 3 veces si la base está bloqueada, 50 ms entre intentos, como Python).
func (a *Almacen) ConsumirSiguienteFolio(rut string, tipo int) (int, error) {
	var ultimo error
	for intento := 0; intento < 3; intento++ {
		folio, err := a.consumir(rut, tipo)
		if err == nil || errors.Is(err, ErrSinFolios) {
			return folio, err
		}
		ultimo = err
		if !strings.Contains(err.Error(), "locked") && !strings.Contains(err.Error(), "busy") {
			return 0, err
		}
		time.Sleep(50 * time.Millisecond)
	}
	return 0, ultimo
}

func (a *Almacen) consumir(rut string, tipo int) (int, error) {
	conn, err := a.db.Conn(ctxBG)
	if err != nil {
		return 0, err
	}
	defer conn.Close()
	if _, err := conn.ExecContext(ctxBG, "BEGIN IMMEDIATE"); err != nil {
		return 0, err
	}
	var id int64
	var siguiente, hasta int
	err = conn.QueryRowContext(ctxBG,
		"SELECT id, folio_siguiente, folio_hasta FROM cafs WHERE rut_emisor=? AND tipo_dte=? AND activo=1 "+
			"ORDER BY folio_desde DESC LIMIT 1", rut, tipo).Scan(&id, &siguiente, &hasta)
	if errors.Is(err, sql.ErrNoRows) || (err == nil && siguiente > hasta) {
		_, _ = conn.ExecContext(ctxBG, "COMMIT")
		return 0, ErrSinFolios
	}
	if err != nil {
		_, _ = conn.ExecContext(ctxBG, "ROLLBACK")
		return 0, err
	}
	if _, err := conn.ExecContext(ctxBG, "UPDATE cafs SET folio_siguiente=? WHERE id=?", siguiente+1, id); err != nil {
		_, _ = conn.ExecContext(ctxBG, "ROLLBACK")
		return 0, err
	}
	if _, err := conn.ExecContext(ctxBG, "COMMIT"); err != nil {
		return 0, err
	}
	return siguiente, nil
}

// ConsumirFolio es consumir_folio (folio explícito): avanza folio_siguiente a folio+1.
func (a *Almacen) ConsumirFolio(rut string, tipo, folio int) (bool, error) {
	c, err := a.CAFActivo(rut, tipo)
	if err != nil || c == nil || folio < c.FolioDesde || folio > c.FolioHasta {
		return false, err
	}
	_, err = a.db.Exec("UPDATE cafs SET folio_siguiente=? WHERE id=?", folio+1, c.ID)
	return err == nil, err
}

type DTE struct {
	TipoDTE             int
	Folio               int
	RutEmisor           string
	RutReceptor         string
	RazonSocialReceptor string
	FechaEmision        string
	MontoNeto           int64
	MontoExento         int64
	IVA                 int64
	MontoTotal          int64
	XMLFirmado          string // ISO-8859-1 decodificado (como lo guarda Python)
	Ambiente            string
}

// CrearDTE es crear_dte: misma fila, estado 'generado', creado_en/actualizado_en ISO.
func (a *Almacen) CrearDTE(d DTE) (int64, error) {
	ahora := time.Now().Format("2006-01-02T15:04:05.000000")
	res, err := a.db.Exec(`INSERT INTO dtes
            (tipo_dte, folio, rut_emisor, rut_receptor, razon_social_receptor,
             fecha_emision, monto_neto, monto_exento, iva, monto_total,
             estado, xml_firmado, ambiente, creado_en, actualizado_en)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'generado', ?, ?, ?, ?)`,
		d.TipoDTE, d.Folio, d.RutEmisor, d.RutReceptor, d.RazonSocialReceptor, d.FechaEmision,
		d.MontoNeto, d.MontoExento, d.IVA, d.MontoTotal, d.XMLFirmado, d.Ambiente, ahora, ahora)
	if err != nil {
		return 0, fmt.Errorf("insertar dte: %w", err)
	}
	return res.LastInsertId()
}

// ---------------------------------------------------------------------------
// Lo que el SII engine (nucleo/siiengine) necesita para importar y marcar documentos: réplica
// de core/models.py::obtener_dte_por_folio / actualizar_estado_dte / guardar_pdf_dte y del
// UPDATE de xml_firmado de importar_emitidos.
// ---------------------------------------------------------------------------

// DTEFila es lo mínimo de una fila existente de `dtes`.
type DTEFila struct {
	ID       int64
	Estado   string
	PDFPath  string
	TieneXML bool
}

// DTEPorFolio devuelve la fila (rut_emisor, tipo, folio) o nil si no existe.
func (a *Almacen) DTEPorFolio(rut string, tipo, folio int) (*DTEFila, error) {
	var f DTEFila
	var pdf, xml sql.NullString
	err := a.db.QueryRow(`SELECT id, estado, pdf_path, xml_firmado FROM dtes WHERE rut_emisor=? AND tipo_dte=? AND folio=?`,
		rut, tipo, folio).Scan(&f.ID, &f.Estado, &pdf, &xml)
	if err == sql.ErrNoRows {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("leer dte: %w", err)
	}
	f.PDFPath = pdf.String
	f.TieneXML = xml.Valid && xml.String != ""
	return &f, nil
}

// ActualizarEstado es actualizar_estado_dte; trackID 0 deja track_id como está.
func (a *Almacen) ActualizarEstado(id int64, estado string, trackID int64) error {
	ahora := time.Now().Format("2006-01-02T15:04:05.000000")
	var err error
	if trackID != 0 {
		_, err = a.db.Exec(`UPDATE dtes SET estado=?, track_id=?, actualizado_en=? WHERE id=?`, estado, trackID, ahora, id)
	} else {
		_, err = a.db.Exec(`UPDATE dtes SET estado=?, actualizado_en=? WHERE id=?`, estado, ahora, id)
	}
	if err != nil {
		return fmt.Errorf("actualizar estado: %w", err)
	}
	return nil
}

// GuardarPDF es guardar_pdf_dte.
func (a *Almacen) GuardarPDF(id int64, ruta string) error {
	ahora := time.Now().Format("2006-01-02T15:04:05.000000")
	if _, err := a.db.Exec(`UPDATE dtes SET pdf_path=?, actualizado_en=? WHERE id=?`, ruta, ahora, id); err != nil {
		return fmt.Errorf("guardar pdf: %w", err)
	}
	return nil
}

// GuardarXML guarda el XML firmado (decodificado ISO-8859-1, como lo guarda Python).
func (a *Almacen) GuardarXML(id int64, xml string) error {
	if _, err := a.db.Exec(`UPDATE dtes SET xml_firmado=?, actualizado_en=datetime('now') WHERE id=?`, xml, id); err != nil {
		return fmt.Errorf("guardar xml: %w", err)
	}
	return nil
}

// EjecutarDDL corre una sentencia de esquema. El esquema lo define Python (core/database.py,
// SCHEMA_SQL); esto existe para tests y migraciones mínimas, no para que Go lo redefina.
func (a *Almacen) EjecutarDDL(ddl string) error {
	_, err := a.db.Exec(ddl)
	return err
}

// DTEDetalle es lo que la app necesita de un documento para anularlo por el SII engine.
type DTEDetalle struct {
	ID                  int64
	TipoDTE             int
	Folio               int
	RutEmisor           string
	RutReceptor         string
	RazonSocialReceptor string
	FechaEmision        string
	MontoTotal          int64
	Estado              string
	TrackID             int64 // en el canal MIPYME es el DHDR del portal
}

// DTEPorID devuelve el documento o nil si no existe.
func (a *Almacen) DTEPorID(id int64) (*DTEDetalle, error) {
	var d DTEDetalle
	var razon, estado sql.NullString
	var track sql.NullInt64
	err := a.db.QueryRow(`SELECT id, tipo_dte, folio, rut_emisor, rut_receptor, razon_social_receptor, fecha_emision, monto_total, estado, track_id
		FROM dtes WHERE id=?`, id).Scan(&d.ID, &d.TipoDTE, &d.Folio, &d.RutEmisor, &d.RutReceptor, &razon, &d.FechaEmision, &d.MontoTotal, &estado, &track)
	if err == sql.ErrNoRows {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("leer dte %d: %w", id, err)
	}
	d.RazonSocialReceptor, d.Estado, d.TrackID = razon.String, estado.String, track.Int64
	return &d, nil
}

// RegistrarCAF es registrar_caf: inserta el CAF con folio_siguiente = folio_desde.
func (a *Almacen) RegistrarCAF(tipo int, rut string, desde, hasta int, fechaAutorizacion, cafXML string) (int64, error) {
	ahora := time.Now().Format("2006-01-02T15:04:05.000000")
	res, err := a.db.Exec(`INSERT INTO cafs (tipo_dte, rut_emisor, folio_desde, folio_hasta, folio_siguiente, fecha_autorizacion, caf_xml, creado_en)
		VALUES (?, ?, ?, ?, ?, ?, ?, ?)`, tipo, rut, desde, hasta, desde, fechaAutorizacion, cafXML, ahora)
	if err != nil {
		return 0, fmt.Errorf("registrar caf: %w", err)
	}
	return res.LastInsertId()
}
