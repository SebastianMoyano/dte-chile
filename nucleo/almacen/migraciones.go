package almacen

// Migraciones del esquema. Desde la fase 7 del port el esquema lo define Go: archivos SQL
// numerados en migraciones/ (embebidos), aplicados en orden y registrados en la tabla
// `migraciones`. Cada archivo corre en una transacción; un error deja la base como estaba.
//
// Compatibilidad: 0001_base es literalmente lo que Python creaba al arrancar (todo con
// IF NOT EXISTS), así que una base creada por Python se "adopta" sin cambios y una creada por
// Go es idéntica a la de Python (tools/esquema_dorado.py lo comprueba). Python sigue corriendo
// sus CREATE TABLE IF NOT EXISTS mientras exista; la tabla `migraciones` le es indiferente.

import (
	"embed"
	"fmt"
	"io/fs"
	"sort"
	"strings"
	"time"
)

//go:embed migraciones/*.sql
var archivosMigraciones embed.FS

// Migracion es un archivo numerado: "0001_base.sql" → Version 1, Nombre "base".
type Migracion struct {
	Version int
	Nombre  string
	SQL     string
}

// Migraciones devuelve las migraciones embebidas, ordenadas por versión.
func Migraciones() ([]Migracion, error) {
	entradas, err := fs.ReadDir(archivosMigraciones, "migraciones")
	if err != nil {
		return nil, err
	}
	var out []Migracion
	for _, e := range entradas {
		nombre := e.Name()
		var v int
		var resto string
		if _, err := fmt.Sscanf(nombre, "%04d_%s", &v, &resto); err != nil || v <= 0 {
			return nil, fmt.Errorf("migración con nombre inválido: %s (se espera NNNN_nombre.sql)", nombre)
		}
		b, err := archivosMigraciones.ReadFile("migraciones/" + nombre)
		if err != nil {
			return nil, err
		}
		out = append(out, Migracion{Version: v, Nombre: strings.TrimSuffix(resto, ".sql"), SQL: string(b)})
	}
	sort.Slice(out, func(i, j int) bool { return out[i].Version < out[j].Version })
	for i := range out {
		if out[i].Version != i+1 {
			return nil, fmt.Errorf("las migraciones deben ser consecutivas: falta la %04d", i+1)
		}
	}
	return out, nil
}

// Migrar aplica las migraciones pendientes. Devuelve las versiones aplicadas en esta corrida.
func (a *Almacen) Migrar() ([]int, error) {
	if _, err := a.db.Exec(`CREATE TABLE IF NOT EXISTS migraciones (
		version INTEGER PRIMARY KEY, nombre TEXT NOT NULL, aplicada TEXT NOT NULL)`); err != nil {
		return nil, fmt.Errorf("tabla migraciones: %w", err)
	}
	todas, err := Migraciones()
	if err != nil {
		return nil, err
	}
	var aplicadas []int
	for _, m := range todas {
		var n int
		if err := a.db.QueryRow(`SELECT COUNT(*) FROM migraciones WHERE version=?`, m.Version).Scan(&n); err != nil {
			return aplicadas, err
		}
		if n > 0 {
			continue
		}
		tx, err := a.db.Begin()
		if err != nil {
			return aplicadas, err
		}
		if _, err := tx.Exec(m.SQL); err != nil {
			tx.Rollback()
			return aplicadas, fmt.Errorf("migración %04d_%s: %w", m.Version, m.Nombre, err)
		}
		if _, err := tx.Exec(`INSERT INTO migraciones (version, nombre, aplicada) VALUES (?, ?, ?)`,
			m.Version, m.Nombre, time.Now().UTC().Format(time.RFC3339)); err != nil {
			tx.Rollback()
			return aplicadas, err
		}
		if err := tx.Commit(); err != nil {
			return aplicadas, err
		}
		aplicadas = append(aplicadas, m.Version)
	}
	if err := a.asegurarColumnas(); err != nil {
		return aplicadas, err
	}
	return aplicadas, nil
}

// columnasGarantizadas replica los ALTER TABLE … ADD COLUMN que Python hace al arrancar
// (core/negocios.py::_COLS_ESTADO): se agregan solo si faltan, así una base adoptada de Python
// y una creada por Go quedan con el mismo esquema (tools/esquema_dorado.py). Las columnas
// nuevas de verdad van en migraciones numeradas; esto es solo compatibilidad.
var columnasGarantizadas = []struct{ tabla, columna, ddl string }{
	{"negocios", "estado", "TEXT"}, {"negocios", "estado_etiqueta", "TEXT"}, {"negocios", "usa_sw_propio", "INTEGER"},
	{"negocios", "estado_ts", "TEXT"}, {"negocios", "software_registrado", "TEXT"},
}

func (a *Almacen) asegurarColumnas() error {
	for _, c := range columnasGarantizadas {
		rows, err := a.db.Query(fmt.Sprintf("PRAGMA table_info(%s)", c.tabla))
		if err != nil {
			return err
		}
		existe := false
		for rows.Next() {
			var cid int
			var nombre, tipo string
			var notnull, pk int
			var def any
			if err := rows.Scan(&cid, &nombre, &tipo, &notnull, &def, &pk); err == nil && nombre == c.columna {
				existe = true
			}
		}
		rows.Close()
		if !existe {
			if _, err := a.db.Exec(fmt.Sprintf("ALTER TABLE %s ADD COLUMN %s %s", c.tabla, c.columna, c.ddl)); err != nil {
				return fmt.Errorf("columna %s.%s: %w", c.tabla, c.columna, err)
			}
		}
	}
	return nil
}

// VersionEsquema es la última migración aplicada (0 si ninguna).
func (a *Almacen) VersionEsquema() (int, error) {
	var v int
	err := a.db.QueryRow(`SELECT COALESCE(MAX(version), 0) FROM migraciones`).Scan(&v)
	if err != nil && strings.Contains(err.Error(), "no such table") {
		return 0, nil
	}
	return v, err
}

// AbrirYMigrar abre la base y aplica las migraciones pendientes (lo que hace el servidor y la
// app al arrancar).
func AbrirYMigrar(ruta string) (*Almacen, error) {
	a, err := Abrir(ruta)
	if err != nil {
		return nil, err
	}
	if _, err := a.Migrar(); err != nil {
		a.Cerrar()
		return nil, err
	}
	return a, nil
}
