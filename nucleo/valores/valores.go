// Package valores trae los indicadores públicos del SII (UF, UTM, dólar) desde las páginas
// oficiales de "Valores y Fechas" (www.sii.cl/valores_y_fechas/...), con mindicador.cl como
// fallback, y los cachea en el MISMO SQLite del motor (ver cache.go).
//
// Fuente PRIMARIA = oficial (SII). Esas páginas NO están tras el WAF Incapsula que frena otras
// (verificado 2026-10-08: HTTP 200 por httpx/curl), así que se bajan sin navegador. El HTML es
// ISO-8859-1 y una tabla por mes: <h2>Mes</h2> y pares <th>día</th><td>valor</td>. mindicador.cl
// (JSON) se usa solo si la oficial falla.
package valores

import (
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"regexp"
	"strconv"
	"strings"
	"time"
)

// Valor es un indicador en una fecha. Valor en pesos (UF, UTM, dólar observado).
type Valor struct {
	Indicador string  `json:"indicador"` // "uf" | "utm" | "dolar"
	Fecha     string  `json:"fecha"`     // YYYY-MM-DD
	Valor     float64 `json:"valor"`
}

const uaNavegador = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) " +
	"AppleWebKit/537.36 (KHTML, like Gecko) Chrome/154.0 Safari/537.36"

var meses = map[string]int{
	"enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
	"julio": 7, "agosto": 8, "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
}

var (
	reMes = regexp.MustCompile(`(?i)<h2>\s*([a-záéíóúñ]+)\s*</h2>`)
	rePar = regexp.MustCompile(`(?is)<th[^>]*>\s*(?:<strong>)?\s*(\d{1,2})\s*(?:</strong>)?\s*</th>\s*<td[^>]*>([^<]*)</td>`)
)

// latin1 decodifica ISO-8859-1 a string: cada byte 0x00-0xFF es su propio code point Unicode.
func latin1(b []byte) string {
	r := make([]rune, len(b))
	for i, c := range b {
		r[i] = rune(c)
	}
	return string(r)
}

// numeroCL parsea un número chileno ("41.065,38") a float64. "" o basura → (0, false).
func numeroCL(s string) (float64, bool) {
	s = strings.TrimSpace(s)
	if s == "" {
		return 0, false
	}
	s = strings.ReplaceAll(s, ".", "")
	s = strings.ReplaceAll(s, ",", ".")
	v, err := strconv.ParseFloat(s, 64)
	if err != nil {
		return 0, false
	}
	return v, true
}

// ParsearUF lee el HTML (ISO-8859-1) de la página UF de un año y devuelve los valores diarios.
// La página trae una tabla por mes; se recorre cada bloque <h2>Mes</h2> hasta el siguiente.
func ParsearUF(htmlBytes []byte, anio int) ([]Valor, error) {
	doc := latin1(htmlBytes)
	encabezados := reMes.FindAllStringSubmatchIndex(doc, -1)
	if len(encabezados) == 0 {
		return nil, fmt.Errorf("no se encontraron meses en la página UF %d", anio)
	}
	var out []Valor
	for i, h := range encabezados {
		nombreMes := strings.ToLower(doc[h[2]:h[3]])
		mes, ok := meses[nombreMes]
		if !ok {
			continue
		}
		fin := len(doc)
		if i+1 < len(encabezados) {
			fin = encabezados[i+1][0]
		}
		bloque := doc[h[1]:fin]
		for _, p := range rePar.FindAllStringSubmatch(bloque, -1) {
			dia, err := strconv.Atoi(strings.TrimSpace(p[1]))
			if err != nil || dia < 1 || dia > 31 {
				continue
			}
			v, ok := numeroCL(p[2])
			if !ok {
				continue // día sin valor (futuro o inexistente)
			}
			out = append(out, Valor{"uf", fmt.Sprintf("%04d-%02d-%02d", anio, mes, dia), v})
		}
	}
	if len(out) == 0 {
		return nil, fmt.Errorf("página UF %d sin valores parseables", anio)
	}
	return out, nil
}

func bajar(url string) ([]byte, error) {
	req, _ := http.NewRequest("GET", url, nil)
	req.Header.Set("User-Agent", uaNavegador)
	req.Header.Set("Accept-Language", "es-CL,es;q=0.9")
	cli := &http.Client{Timeout: 20 * time.Second}
	resp, err := cli.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 {
		return nil, fmt.Errorf("%s → HTTP %d", url, resp.StatusCode)
	}
	return io.ReadAll(resp.Body)
}

// FetchUF trae la UF del año: primero la página oficial del SII; si falla, mindicador.cl.
// Devuelve los valores y la fuente usada ("sii" | "mindicador").
func FetchUF(anio int) ([]Valor, string, error) {
	url := fmt.Sprintf("https://www.sii.cl/valores_y_fechas/uf/uf%d.htm", anio)
	if b, err := bajar(url); err == nil {
		if vs, err := ParsearUF(b, anio); err == nil {
			return vs, "sii", nil
		}
	}
	// Fallback: mindicador.cl/api/uf/<año> → {serie:[{fecha,valor}]}
	vs, err := fetchMindicador("uf", anio)
	if err != nil {
		return nil, "", fmt.Errorf("UF %d: falló SII y mindicador: %w", anio, err)
	}
	return vs, "mindicador", nil
}

func fetchMindicador(indicador string, anio int) ([]Valor, error) {
	b, err := bajar(fmt.Sprintf("https://mindicador.cl/api/%s/%d", indicador, anio))
	if err != nil {
		return nil, err
	}
	var payload struct {
		Serie []struct {
			Fecha string  `json:"fecha"`
			Valor float64 `json:"valor"`
		} `json:"serie"`
	}
	if err := json.Unmarshal(b, &payload); err != nil {
		return nil, err
	}
	var out []Valor
	for _, s := range payload.Serie {
		if len(s.Fecha) >= 10 {
			out = append(out, Valor{indicador, s.Fecha[:10], s.Valor})
		}
	}
	if len(out) == 0 {
		return nil, fmt.Errorf("mindicador %s %d sin serie", indicador, anio)
	}
	return out, nil
}
