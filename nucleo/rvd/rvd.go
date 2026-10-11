// Package rvd es core/rvd.py: el Registro de Ventas Diario (RVD, antes RCOF) de boletas, el
// <ConsumoFolios> que quien emite boletas debe mandar TODOS los días (Res. Ex. SII N° 74 de 2020,
// dentro de las 12 horas del día siguiente, incluso en cero).
//
// Viaja por el canal de FACTURAS (DTEUpload + token SOAP, maullin/palena), NO por el REST de
// boletas: lo dice el OpenAPI oficial del SII y lo confirma el Instructivo Técnico ("No hay
// cambios en el envío de RCOF"). Se perdió tiempo buscando una ruta REST inexistente.
package rvd

import (
	"database/sql"
	"fmt"
	"sort"
	"strings"
	"time"

	"dtechile/nucleo/firma"
	"dtechile/nucleo/sii"
	"dtechile/nucleo/xsd"
)

const (
	nsSii   = "http://www.sii.cl/SiiDte"
	nsXsi   = "http://www.w3.org/2001/XMLSchema-instance"
	xsdRef  = "http://www.sii.cl/SiiDte ConsumoFolio_v10.xsd"
	tasaIVA = 19
	declISO = "<?xml version=\"1.0\" encoding=\"ISO-8859-1\"?>\n"
)

// TiposConsumo: el XSD (TipoConsumoType) solo acepta estos tres; por eso Resumen tiene maxOccurs=3.
var TiposConsumo = []int{39, 41, 61}

// Boleta es una fila de `dtes` del día (tipo, folio, montos, estado).
type Boleta struct {
	TipoDTE     int
	Folio       int
	MontoNeto   int64
	IVA         int64
	MontoExento int64
	MontoTotal  int64
	Estado      string
}

// Parametros de generar_consumo_folios.
type Parametros struct {
	RutEmisor        string
	RutEnvia         string
	FechaResolucion  string
	NumeroResolucion int
	Dia              string // YYYY-MM-DD
	Tipos            []int  // los que no tuvieron movimiento igual van, en cero
	SecEnvio         int    // 1 la primera vez; para CORREGIR se reenvía completo con +1
	Correlativo      *int
	Marca            string // TmstFirmaEnv (reloj único)
	Documentos       []Boleta
}

func enTipos(t int) bool {
	for _, x := range TiposConsumo {
		if x == t {
			return true
		}
	}
	return false
}

// AgruparRangos es agrupar_rangos: folios ordenados → rangos [inicial, final] consecutivos.
func AgruparRangos(folios []int) [][2]int {
	if len(folios) == 0 {
		return nil
	}
	f := append([]int{}, folios...)
	sort.Ints(f)
	var out [][2]int
	ini, fin := f[0], f[0]
	for _, x := range f[1:] {
		if x == fin || x == fin+1 {
			fin = x
			continue
		}
		out = append(out, [2]int{ini, fin})
		ini, fin = x, x
	}
	return append(out, [2]int{ini, fin})
}

func txt(b *strings.Builder, tag string, v any) {
	fmt.Fprintf(b, "<%s>%v</%s>", tag, v, tag)
}

func resumen(b *strings.Builder, tipo int, docs []Boleta) {
	var emitidos, anulados []Boleta
	for _, d := range docs {
		if strings.ToLower(d.Estado) == "anulado" {
			anulados = append(anulados, d)
		} else {
			emitidos = append(emitidos, d)
		}
	}
	var neto, iva, exento, total int64
	for _, d := range emitidos { // solo lo efectivamente emitido (lo anulado no vendió nada)
		neto += d.MontoNeto
		iva += d.IVA
		exento += d.MontoExento
		total += d.MontoTotal
	}
	b.WriteString("<Resumen>")
	txt(b, "TipoDocumento", tipo)
	if neto != 0 {
		txt(b, "MntNeto", neto)
	}
	if iva != 0 {
		txt(b, "MntIva", iva)
		txt(b, "TasaIVA", tasaIVA)
	}
	if exento != 0 {
		txt(b, "MntExento", exento)
	}
	txt(b, "MntTotal", total)
	txt(b, "FoliosEmitidos", len(emitidos))
	txt(b, "FoliosAnulados", len(anulados))
	txt(b, "FoliosUtilizados", len(emitidos)+len(anulados)) // los anulados igual consumieron folio
	folios := func(ds []Boleta) []int {
		var f []int
		for _, d := range ds {
			f = append(f, d.Folio)
		}
		return f
	}
	for _, r := range AgruparRangos(folios(emitidos)) {
		b.WriteString("<RangoUtilizados>")
		txt(b, "Inicial", r[0])
		txt(b, "Final", r[1])
		b.WriteString("</RangoUtilizados>")
	}
	for _, r := range AgruparRangos(folios(anulados)) {
		b.WriteString("<RangoAnulados>")
		txt(b, "Inicial", r[0])
		txt(b, "Final", r[1])
		b.WriteString("</RangoAnulados>")
	}
	b.WriteString("</Resumen>")
}

// IDDocumento es el ID del <DocumentoConsumoFolios> ("RVD" + YYYYMMDD).
func IDDocumento(dia string) string { return "RVD" + strings.ReplaceAll(dia, "-", "") }

// Generar es generar_consumo_folios serializado como lxml (sin declaración): el XML SIN firmar.
func Generar(p Parametros) (string, error) {
	tipos := p.Tipos
	if len(tipos) == 0 {
		tipos = TiposConsumo
	}
	for _, t := range tipos {
		if !enTipos(t) {
			return "", fmt.Errorf("el consumo de folios solo admite los tipos %v; recibido: %d", TiposConsumo, t)
		}
	}
	if p.Dia == "" {
		return "", fmt.Errorf("sin documentos no se puede deducir el día del consumo: pasar Dia")
	}
	sec := p.SecEnvio
	if sec == 0 {
		sec = 1
	}
	var b strings.Builder
	b.WriteString(`<ConsumoFolios xmlns="` + nsSii + `" xmlns:xsi="` + nsXsi + `" version="1.0" xsi:schemaLocation="` + xsdRef + `">`)
	b.WriteString(`<DocumentoConsumoFolios ID="` + IDDocumento(p.Dia) + `">`)
	b.WriteString(`<Caratula version="1.0">`)
	txt(&b, "RutEmisor", p.RutEmisor)
	txt(&b, "RutEnvia", p.RutEnvia)
	txt(&b, "FchResol", p.FechaResolucion)
	txt(&b, "NroResol", p.NumeroResolucion)
	txt(&b, "FchInicio", p.Dia)
	txt(&b, "FchFinal", p.Dia)
	if p.Correlativo != nil {
		txt(&b, "Correlativo", *p.Correlativo)
	}
	txt(&b, "SecEnvio", sec)
	txt(&b, "TmstFirmaEnv", p.Marca)
	b.WriteString("</Caratula>")
	for _, t := range tipos {
		var docs []Boleta
		for _, d := range p.Documentos {
			if d.TipoDTE == t {
				docs = append(docs, d)
			}
		}
		resumen(&b, t, docs)
	}
	b.WriteString("</DocumentoConsumoFolios></ConsumoFolios>")
	return b.String(), nil
}

// Firmar es firmar_xml_sii(raiz, cert, uri="#RVD…") + la declaración con comillas DOBLES
// (la de lxml va con simples y DTEUpload la rechaza con CHR-00001). Devuelve ISO-8859-1.
func Firmar(cert *firma.Certificado, sinFirma string) ([]byte, error) {
	ini := strings.Index(sinFirma, "<DocumentoConsumoFolios ")
	fin := strings.Index(sinFirma, "</DocumentoConsumoFolios>")
	if ini < 0 || fin < 0 {
		return nil, fmt.Errorf("no se encontró <DocumentoConsumoFolios>")
	}
	doc := sinFirma[ini : fin+len("</DocumentoConsumoFolios>")]
	id := doc[strings.Index(doc, `ID="`)+4:]
	id = id[:strings.Index(id, `"`)]
	// El SII (Santuario) canonicaliza el subárbol con los namespaces EN ALCANCE heredados en el
	// ápice (SiiDte y xsi): es `_c14n_reparse`; el SignedInfo cuelga de <Signature xmlns=dsig>
	// bajo la raíz con xsi. Mismo método que el sobre, verificado contra el SII vivo.
	sig, err := cert.Signature("#"+id, doc, map[string]string{"": nsSii, "xsi": nsXsi}, map[string]string{"xsi": nsXsi})
	if err != nil {
		return nil, err
	}
	cierre := "</ConsumoFolios>"
	if !strings.HasSuffix(sinFirma, cierre) {
		return nil, fmt.Errorf("el XML no termina en %s", cierre)
	}
	final := sinFirma[:len(sinFirma)-len(cierre)] + sig + cierre
	out := []byte(declISO)
	for _, r := range final {
		if r > 0xFF {
			return nil, fmt.Errorf("carácter %q no representable en ISO-8859-1", r)
		}
		out = append(out, byte(r))
	}
	return out, nil
}

// GenerarFirmado genera, firma y valida contra el XSD (ConsumoFolio_v10.xsd).
func GenerarFirmado(cert *firma.Certificado, p Parametros) ([]byte, error) {
	sinFirma, err := Generar(p)
	if err != nil {
		return nil, err
	}
	xml, err := Firmar(cert, sinFirma)
	if err != nil {
		return nil, err
	}
	if err := xsd.ValidarError(xml); err != nil {
		return nil, err
	}
	return xml, nil
}

// Enviar sube el RVD por DTEUpload (canal de FACTURAS) y devuelve el TrackID.
func Enviar(cli *sii.Cliente, xmlRVD []byte, rutEmisor string) (int64, string, error) {
	n, dv, ok := strings.Cut(rutEmisor, "-")
	if !ok {
		return 0, "", fmt.Errorf("RUT sin DV: %q", rutEmisor)
	}
	track, resp, err := cli.EnviarDTE(xmlRVD, n, dv)
	if err != nil {
		return track, resp, err
	}
	return track, fmt.Sprintf("RVD recibido. TrackID: %d", track), nil
}

// ---------------------------------------------------------------- base de datos

func marcadores(n int) string { return strings.TrimSuffix(strings.Repeat("?,", n), ",") }

// BoletasDelDia lee de `dtes` las boletas (39/41/61) de `rut` en `dia`, ordenadas por tipo y folio.
func BoletasDelDia(db *sql.DB, rut, dia, ambiente string) ([]Boleta, error) {
	q := "SELECT tipo_dte, folio, COALESCE(monto_neto,0), COALESCE(monto_exento,0), COALESCE(iva,0), COALESCE(monto_total,0), COALESCE(estado,'') FROM dtes WHERE rut_emisor=? AND fecha_emision=? AND tipo_dte IN (" + marcadores(len(TiposConsumo)) + ")"
	args := []any{rut, dia}
	for _, t := range TiposConsumo {
		args = append(args, t)
	}
	if ambiente != "" {
		q += " AND ambiente=?"
		args = append(args, ambiente)
	}
	q += " ORDER BY tipo_dte, folio"
	rows, err := db.Query(q, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []Boleta
	for rows.Next() {
		var b Boleta
		if err := rows.Scan(&b.TipoDTE, &b.Folio, &b.MontoNeto, &b.MontoExento, &b.IVA, &b.MontoTotal, &b.Estado); err != nil {
			return nil, err
		}
		out = append(out, b)
	}
	return out, rows.Err()
}

// DiasConBoletas: días (YYYY-MM-DD) entre desde y hasta, inclusive, con boletas de `rut`.
func DiasConBoletas(db *sql.DB, rut, desde, hasta, ambiente string) ([]string, error) {
	q := "SELECT DISTINCT fecha_emision FROM dtes WHERE rut_emisor=? AND fecha_emision BETWEEN ? AND ? AND tipo_dte IN (" + marcadores(len(TiposConsumo)) + ")"
	args := []any{rut, desde, hasta}
	for _, t := range TiposConsumo {
		args = append(args, t)
	}
	if ambiente != "" {
		q += " AND ambiente=?"
		args = append(args, ambiente)
	}
	q += " ORDER BY fecha_emision"
	rows, err := db.Query(q, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []string
	for rows.Next() {
		var d string
		if err := rows.Scan(&d); err != nil {
			return nil, err
		}
		if len(d) >= 10 {
			d = d[:10]
		}
		out = append(out, d)
	}
	return out, rows.Err()
}

// Registro es una fila de rvd_envios.
type Registro struct {
	ID        int64  `json:"id"`
	RutEmisor string `json:"rut_emisor"`
	Fecha     string `json:"fecha"`
	SecEnvio  int    `json:"sec_envio"`
	Estado    string `json:"estado"`
	TrackID   string `json:"track_id"`
	XMLPath   string `json:"xml_path"`
	Detalle   string `json:"detalle"`
}

// Registrado devuelve el último registro del día (mayor sec_envio) o nil.
func Registrado(db *sql.DB, rut, dia string) (*Registro, error) {
	var r Registro
	var track, xml, det sql.NullString
	err := db.QueryRow(`SELECT id, rut_emisor, fecha, sec_envio, estado, track_id, xml_path, detalle FROM rvd_envios WHERE rut_emisor=? AND fecha=? ORDER BY sec_envio DESC LIMIT 1`, rut, dia).
		Scan(&r.ID, &r.RutEmisor, &r.Fecha, &r.SecEnvio, &r.Estado, &track, &xml, &det)
	if err == sql.ErrNoRows {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	r.TrackID, r.XMLPath, r.Detalle = track.String, xml.String, det.String
	return &r, nil
}

// Registrar inserta o actualiza (UNIQUE rut, fecha, sec_envio): reintentar el mismo día
// actualiza la fila en vez de duplicar el reporte.
func Registrar(db *sql.DB, rut, dia, estado string, secEnvio int, trackID, xmlPath, detalle string) error {
	if secEnvio == 0 {
		secEnvio = 1
	}
	ahora := time.Now().Format("2006-01-02T15:04:05")
	_, err := db.Exec(`INSERT INTO rvd_envios (rut_emisor, fecha, sec_envio, estado, track_id, xml_path, detalle, creado_en, actualizado_en)
		VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(rut_emisor, fecha, sec_envio) DO UPDATE SET estado=excluded.estado,
		track_id=excluded.track_id, xml_path=excluded.xml_path, detalle=excluded.detalle, actualizado_en=excluded.actualizado_en`,
		rut, dia, secEnvio, estado, nilSi(trackID), nilSi(xmlPath), nilSi(detalle), ahora, ahora)
	return err
}

func nilSi(s string) any {
	if s == "" {
		return nil
	}
	return s
}
