package valores

import (
	"database/sql"
	"errors"
	"fmt"
	"time"

	_ "modernc.org/sqlite"
)

// Cache guarda los indicadores en el MISMO SQLite del motor. La tabla `valores` es una tabla de
// referencia independiente del esquema DTE (dtes/cafs/folios): se crea con IF NOT EXISTS aquí,
// así Go la puede poblar sin depender de que Python la haya creado. No toca el contrato de folios.
type Cache struct{ db *sql.DB }

const ddl = `CREATE TABLE IF NOT EXISTS valores (
  indicador   TEXT NOT NULL,
  fecha       TEXT NOT NULL,   -- YYYY-MM-DD
  valor       REAL NOT NULL,
  actualizado TEXT NOT NULL,
  PRIMARY KEY (indicador, fecha)
);`

func AbrirCache(ruta string) (*Cache, error) {
	db, err := sql.Open("sqlite", ruta+"?_pragma=busy_timeout(5000)&_pragma=journal_mode(WAL)")
	if err != nil {
		return nil, err
	}
	if err := db.Ping(); err != nil {
		return nil, err
	}
	if _, err := db.Exec(ddl); err != nil {
		return nil, fmt.Errorf("creando tabla valores: %w", err)
	}
	return &Cache{db: db}, nil
}

func (c *Cache) Cerrar() error { return c.db.Close() }

// Guardar hace upsert de los valores (mismo indicador+fecha → actualiza). Devuelve cuántos escribió.
func (c *Cache) Guardar(vs []Valor) (int, error) {
	tx, err := c.db.Begin()
	if err != nil {
		return 0, err
	}
	defer tx.Rollback()
	st, err := tx.Prepare(`INSERT INTO valores(indicador,fecha,valor,actualizado) VALUES(?,?,?,?)
		ON CONFLICT(indicador,fecha) DO UPDATE SET valor=excluded.valor, actualizado=excluded.actualizado`)
	if err != nil {
		return 0, err
	}
	defer st.Close()
	ahora := time.Now().UTC().Format(time.RFC3339)
	n := 0
	for _, v := range vs {
		if _, err := st.Exec(v.Indicador, v.Fecha, v.Valor, ahora); err != nil {
			return n, err
		}
		n++
	}
	return n, tx.Commit()
}

// ErrSinValor: no hay valor cacheado para ese indicador/fecha.
var ErrSinValor = errors.New("sin valor cacheado")

// Get devuelve el valor exacto de un indicador en una fecha (YYYY-MM-DD).
func (c *Cache) Get(indicador, fecha string) (float64, error) {
	var v float64
	err := c.db.QueryRow("SELECT valor FROM valores WHERE indicador=? AND fecha=?", indicador, fecha).Scan(&v)
	if errors.Is(err, sql.ErrNoRows) {
		return 0, ErrSinValor
	}
	return v, err
}

// Vigente devuelve el último valor conocido en o antes de `fecha` (UF/dólar de fin de semana o
// feriado heredan el último hábil; UTM vale todo el mes).
func (c *Cache) Vigente(indicador, fecha string) (Valor, error) {
	var out Valor
	err := c.db.QueryRow(
		"SELECT indicador,fecha,valor FROM valores WHERE indicador=? AND fecha<=? ORDER BY fecha DESC LIMIT 1",
		indicador, fecha).Scan(&out.Indicador, &out.Fecha, &out.Valor)
	if errors.Is(err, sql.ErrNoRows) {
		return out, ErrSinValor
	}
	return out, err
}

// AnioMinimo devuelve el primer año con datos del indicador (0 si no hay).
func (c *Cache) AnioMinimo(indicador string) (int, error) {
	var f sql.NullString
	if err := c.db.QueryRow("SELECT MIN(fecha) FROM valores WHERE indicador=?", indicador).Scan(&f); err != nil {
		return 0, err
	}
	if !f.Valid || len(f.String) < 4 {
		return 0, nil
	}
	var a int
	fmt.Sscan(f.String[:4], &a)
	return a, nil
}

// CargarHistorico trae y guarda todos los años [desde, hasta] de los tres indicadores. Se
// usa UNA vez (el histórico no cambia); el refresco diario solo toca el año en curso. Devuelve
// cuántos valores guardó por indicador y los errores por año (no se detiene en el primero).
func CargarHistorico(c *Cache, desde, hasta int, logf func(string, ...any)) map[string]int {
	tot := map[string]int{}
	for anio := desde; anio <= hasta; anio++ {
		for _, ind := range []string{"uf", "utm", "dolar"} {
			vs, fuente, err := Fetch(ind, anio)
			if err != nil {
				if logf != nil {
					logf("valores: %s %d falló: %v", ind, anio, err)
				}
				continue
			}
			n, err := c.Guardar(vs)
			if err != nil {
				if logf != nil {
					logf("valores: %s %d no se guardó: %v", ind, anio, err)
				}
				continue
			}
			tot[ind] += n
			if logf != nil {
				logf("valores: %s %d → %d (fuente: %s)", ind, anio, n, fuente)
			}
		}
	}
	return tot
}
