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
