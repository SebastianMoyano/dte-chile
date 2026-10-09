package siiengine

import (
	"bytes"
	"encoding/json"
	"fmt"
	"html"
	"regexp"
	"strconv"
	"strings"
	"time"
)

// ---------------------------------------------------------------------------
// Historial de emitidos (mipeAdminDocsEmi.cgi): tabla paginada "Página N de M"; cada fila trae
// un enlace con `CODIGO=<DHDR>` y las celdas [RUT receptor, razón social, tipo (texto), folio,
// fecha, monto, estado]. OJO: el monto del listado es la LÍNEA, no el total firmado.
// ---------------------------------------------------------------------------

// DocumentoEmitido es una fila del historial (mismos nombres JSON que el dataclass Python).
type DocumentoEmitido struct {
	DHDR          string `json:"dhdr"`
	TipoTexto     string `json:"tipo_texto"`
	Folio         int    `json:"folio"`
	Fecha         string `json:"fecha"` // YYYY-MM-DD
	Monto         int64  `json:"monto"`
	Estado        string `json:"estado"`
	ReceptorRut   string `json:"receptor_rut"`
	ReceptorRazon string `json:"receptor_razon"`
}

// Tipo es tipo_desde_texto sobre la celda de tipo; 0 si no se reconoce.
func (d DocumentoEmitido) Tipo() int { return TipoDesdeTexto(d.TipoTexto) }

var tiposTexto = []struct {
	re   *regexp.Regexp
	tipo int
}{
	{regexp.MustCompile(`NOTA\s+DE\s+CR[EÉ]DITO`), 61}, {regexp.MustCompile(`NOTA\s+DE\s+D[EÉ]BITO`), 56},
	{regexp.MustCompile(`GU[IÍ]A\s+DE\s+DESPACHO`), 52}, {regexp.MustCompile(`FACTURA\s+DE\s+COMPRA`), 46},
	{regexp.MustCompile(`EXENTA|NO\s+AFECTA`), 34}, {regexp.MustCompile(`FACTURA`), 33},
}

var (
	reTipoNum   = regexp.MustCompile(`\b(33|34|39|41|46|52|56|61)\b`)
	reNoDigito  = regexp.MustCompile(`[^\d]`)
	reFechaCL   = regexp.MustCompile(`^(\d{1,2})[/-](\d{1,2})[/-](\d{4})`)
	reFechaISO  = regexp.MustCompile(`^(\d{4})-(\d{2})-(\d{2})`)
	reEspacios  = regexp.MustCompile(`\s+`)
	reCodigo    = regexp.MustCompile(`[?&]CODIGO=(\d+)`)
	rePaginaDe  = regexp.MustCompile(`[Pp][áa]gina\s+\d+\s+(?:de|/)\s+(\d+)`)
	reTextarea  = regexp.MustCompile(`(?is)<textarea\b[^>]*id=["']txtPlainText["'][^>]*>([\s\S]*?)</textarea>`)
	reXMLInicio = regexp.MustCompile(`(?i)^\s*<\?xml|^\s*<DTE\b`)
	reWhile1    = regexp.MustCompile(`^while\s*\(\s*1\s*\)\s*;?`)
	reObjJS     = regexp.MustCompile(`(?s)\{.*\}`)
	reStatusJS  = regexp.MustCompile(`(?i)\b(?:statusCode|status)\b\s*:\s*(\d+)`)
	reTextJS    = regexp.MustCompile(`(?is)\btext\b\s*:\s*["']([\s\S]*?)["']\s*(?:,|\})`)
)

// TipoDesdeTexto: el listado muestra el tipo como texto ("FACTURA NO AFECTA O EXENTA ELECTRONICA").
func TipoDesdeTexto(texto string) int {
	t := strings.ToUpper(texto)
	if m := reTipoNum.FindStringSubmatch(t); m != nil {
		n, _ := strconv.Atoi(m[1])
		return n
	}
	for _, p := range tiposTexto {
		if p.re.MatchString(t) {
			return p.tipo
		}
	}
	return 0
}

func montoDesdeTexto(texto string) int64 {
	d := reNoDigito.ReplaceAllString(strings.SplitN(texto, ",", 2)[0], "")
	n, _ := strconv.ParseInt(d, 10, 64)
	return n
}

func fechaISO(texto string) string {
	t := strings.TrimSpace(texto)
	if m := reFechaCL.FindStringSubmatch(t); m != nil {
		mes, _ := strconv.Atoi(m[2])
		dia, _ := strconv.Atoi(m[1])
		return fmt.Sprintf("%s-%02d-%02d", m[3], mes, dia)
	}
	if m := reFechaISO.FindString(t); m != "" {
		return m
	}
	return t
}

// ParsearListado es parsear_listado: `(documentos, última_página)` de una página del historial.
func ParsearListado(doc string) ([]DocumentoEmitido, int) {
	var docs []DocumentoEmitido
	for _, f := range parsearFilas(doc) {
		dhdr := ""
		for _, h := range f.hrefs {
			if m := reCodigo.FindStringSubmatch(h); m != nil {
				dhdr = m[1]
				break
			}
		}
		var celdas []string
		for _, c := range f.celdas {
			if c = strings.TrimSpace(reEspacios.ReplaceAllString(c, " ")); c != "" {
				celdas = append(celdas, c)
			}
		}
		if dhdr == "" || len(celdas) < 7 {
			continue
		}
		folio, err := strconv.Atoi(reNoDigito.ReplaceAllString(celdas[3], ""))
		if err != nil {
			continue
		}
		docs = append(docs, DocumentoEmitido{DHDR: dhdr, TipoTexto: celdas[2], Folio: folio, Fecha: fechaISO(celdas[4]),
			Monto: montoDesdeTexto(celdas[5]), Estado: celdas[6], ReceptorRut: strings.ReplaceAll(celdas[0], ".", ""),
			ReceptorRazon: celdas[1]})
	}
	ultima := 1
	if m := rePaginaDe.FindStringSubmatch(doc); m != nil {
		ultima, _ = strconv.Atoi(m[1])
	}
	return docs, ultima
}

// ListarEmitidos es listar_emitidos: todas las páginas del historial (hasta pagMax=20).
// tipo, desde y hasta son los filtros del portal (vacío = todos). Solo lectura.
func (c *Cliente) ListarEmitidos(tipo, desde, hasta string) ([]DocumentoEmitido, error) {
	if err := c.requiereEmpresa(); err != nil {
		return nil, err
	}
	const pagMax = 20
	orden := []string{}
	todos := map[string]DocumentoEmitido{}
	ultima := 1
	for pag := 1; pag <= pagMax; pag++ {
		r, err := c.req("GET", Base+"/mipeAdminDocsEmi.cgi", opciones{navegacion: true, referer: Base + "/mipeSelEmpresa.cgi",
			params: []Par{{"RUT_RECP", ""}, {"FOLIO", ""}, {"RZN_SOC", ""}, {"FEC_DESDE", desde}, {"FEC_HASTA", hasta},
				{"TPO_DOC", tipo}, {"ESTADO", ""}, {"ORDEN", ""}, {"NUM_PAG", strconv.Itoa(pag)}}})
		if err != nil {
			return nil, err
		}
		if r.rechazado() {
			return nil, fmt.Errorf("%w: el portal no entregó el historial de emitidos (http %d, página %d)", ErrRechazo, r.Status, pag)
		}
		var docs []DocumentoEmitido
		docs, ultima = ParsearListado(r.Texto())
		nuevos := 0
		for _, d := range docs {
			if _, ok := todos[d.DHDR]; !ok {
				todos[d.DHDR] = d
				orden = append(orden, d.DHDR)
				nuevos++
			}
		}
		if pag >= max(ultima, 1) || nuevos == 0 {
			break
		}
		time.Sleep(c.Pausa)
	}
	out := make([]DocumentoEmitido, 0, len(orden))
	for _, k := range orden {
		out = append(out, todos[k])
	}
	return out, nil
}

// LeerForm es leer_form: el formulario de emisión pre-llenado "igual al último emitido".
// De aquí salen los datos del emisor según el portal. NO gasta folio.
func (c *Cliente) LeerForm(tipo int) (map[string]string, error) {
	if err := c.requiereEmpresa(); err != nil {
		return nil, err
	}
	r, err := c.req("GET", Base+"/mipeGenFacEx.cgi", opciones{navegacion: true, referer: Base + "/mipeSelEmpresa.cgi",
		params: []Par{{"IGUAL", "ULT_FAC"}, {"PTDC_CODIGO", strconv.Itoa(tipo)}, {"ES_BORR", "FALSE"},
			{"esCRED_EC", "FALSE"}, {"esFACT_TUR", "FALSE"}}})
	if err != nil {
		return nil, err
	}
	if r.rechazado() || len(r.Cuerpo) < 5000 {
		return nil, fmt.Errorf("%w: el portal no entregó el formulario de emisión (¿sesión expirada, empresa sin documentos previos?; http %d)", ErrRechazo, r.Status)
	}
	return ParsearForm(r.Texto()), nil
}

// DescargarPDF es descargar_pdf: el PDF que el portal genera para un DHDR.
func (c *Cliente) DescargarPDF(dhdr string) ([]byte, error) {
	r, err := c.req("GET", Base+"/mipeDisplayPDF.cgi", opciones{navegacion: true,
		referer: Base + "/mipeGesDocEmi.cgi?ALL_PAGE_ANT=2&CODIGO=" + dhdr, params: []Par{{"DHDR_CODIGO", dhdr}}})
	if err != nil {
		return nil, err
	}
	if !bytes.HasPrefix(r.Cuerpo, []byte("%PDF")) {
		return nil, fmt.Errorf("%w: el portal no devolvió un PDF (dhdr %s, http %d)", ErrSII, dhdr, r.Status)
	}
	return r.Cuerpo, nil
}

// PrepararDatoFirma es preparar_dato_firma: el comentario que el JS del portal inserta antes
// de <Documento (o <Liquidacion/<Exportaciones) antes de mandar a firmar. Idempotente.
func PrepararDatoFirma(xml string) string {
	if strings.Contains(xml, "<!-- O ") {
		return xml
	}
	for _, tag := range []string{"<Documento ", "<Liquidacion ", "<Exportaciones "} {
		if strings.Contains(xml, tag) {
			return strings.Replace(xml, tag, ComentarioFirma+"\n"+tag, 1)
		}
	}
	return xml
}

// ParsearRespuestaFirma es parsear_respuesta_firma: `postFirmaDigital` responde JSON
// {"status"|"statusCode": n, "text": "<xml>"} (a veces con prefijo `while(1);`), un objeto
// estilo JS, o el XML directo. Devuelve (status, xml); 0 = OK, 2 = clave del certificado
// incorrecta, -1 = formato desconocido.
func ParsearRespuestaFirma(cruda string) (int, string) {
	t := strings.TrimSpace(cruda)
	t = strings.TrimSpace(reWhile1.ReplaceAllString(t, ""))
	if reXMLInicio.MatchString(t) {
		return 0, t
	}
	if st, txt, ok := jsonFirma(t); ok {
		return st, txt
	}
	if bloque := reObjJS.FindString(t); bloque != "" {
		if st, txt, ok := jsonFirma(bloque); ok {
			return st, txt
		}
		ms := reStatusJS.FindStringSubmatch(bloque)
		mt := reTextJS.FindStringSubmatch(bloque)
		if ms != nil && mt != nil {
			n, _ := strconv.Atoi(ms[1])
			return n, mt[1]
		}
	}
	return -1, ""
}

func jsonFirma(t string) (int, string, bool) {
	var obj map[string]any
	if err := json.Unmarshal([]byte(t), &obj); err != nil {
		return 0, "", false
	}
	v, ok := obj["statusCode"]
	if !ok {
		if v, ok = obj["status"]; !ok {
			return 0, "", false
		}
	}
	st := 0
	switch x := v.(type) {
	case float64:
		st = int(x)
	case string:
		st, _ = strconv.Atoi(x)
	}
	txt, _ := obj["text"].(string)
	return st, txt, true
}

// firmaCentral es _firma_central: `postFirmaDigital` exactamente como el XHR del navegador
// (form UTF-8 con charset declarado, X-Requested-With, Accept text/plain). Responde el XML
// firmado en texto plano ISO-8859-1.
func (c *Cliente) firmaCentral(dato, nodo, nodoID, referer string) (*respuesta, string, error) {
	n, dv := SepararRut(c.RutUsuario)
	cuerpo := CodificarUTF8([]Par{{"nombre", "1"}, {"dato", dato}, {"rut", n}, {"dv", dv}, {"clave", c.claveCert},
		{"nodo", nodo}, {"nodoId", nodoID}, {"nameSpace", "http://www.sii.cl/SiiDte"}})
	r, err := c.req("POST", Base+"/postFirmaDigital.cgi", opciones{navegacion: false, content: cuerpo, referer: referer,
		origin: "https://www1.sii.cl", extra: map[string]string{"X-Requested-With": "XMLHttpRequest",
			"Accept": "text/plain, */*; q=0.01", "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"}})
	if err != nil {
		return nil, "", err
	}
	return r, r.Texto(), nil
}

// ObtenerEnvioXML es obtener_envio_xml: el EnvioDTE (con el DTE firmado adentro) de un
// documento emitido, botón "Obtener Envío" del portal: GET mipeGenDLNewEnvio → textarea
// txtPlainText → firma central del EnvioDTE (nodo dte:EnvioDTE / dte:SetDTE, clave del
// certificado) → POST mipeDownLoadNewEnvio → adjunto .xml (bytes ISO-8859-1). NO gasta folio.
func (c *Cliente) ObtenerEnvioXML(dhdr string, tipo int, rutReceptor string) ([]byte, error) {
	if err := c.requiereEmpresa(); err != nil {
		return nil, err
	}
	if c.claveCert == "" {
		return nil, fmt.Errorf("%w: obtener el XML exige la clave del certificado (firma central)", ErrValidacion)
	}
	rn, rdv := SepararRut(rutReceptor)
	r, err := c.req("GET", Base+"/mipeGenDLNewEnvio.cgi", opciones{navegacion: true,
		referer: Base + "/mipeGesDocEmi.cgi?ALL_PAGE_ANT=2&CODIGO=" + dhdr,
		params:  []Par{{"CODIGO", dhdr}, {"TPO_DOC", strconv.Itoa(tipo)}, {"RUT_RCP", rn}, {"DV_RCP", rdv}}})
	if err != nil {
		return nil, err
	}
	m := reTextarea.FindStringSubmatch(r.Texto())
	if r.rechazado() || m == nil {
		return nil, fmt.Errorf("%w: el portal no entregó el envío para firmar (dhdr %s, http %d)", ErrRechazo, dhdr, r.Status)
	}
	plano := html.UnescapeString(m[1])
	_, firmadoCrudo, err := c.firmaCentral(PrepararDatoFirma(plano), "dte:EnvioDTE", "dte:SetDTE", Base+"/mipeGenDLNewEnvio.cgi")
	if err != nil {
		return nil, err
	}
	estado, firmado := ParsearRespuestaFirma(firmadoCrudo)
	if estado != 0 || !strings.Contains(firmado, "<Signature") {
		return nil, fmt.Errorf("%w: la firma central del envío falló (¿clave del certificado?; dhdr %s, estado %d)", ErrRechazo, dhdr, estado)
	}
	cuerpo, err := CodificarLatin1([]Par{{"txtSignText", firmado}})
	if err != nil {
		return nil, fmt.Errorf("%w: %v", ErrValidacion, err)
	}
	r, err = c.req("POST", Base+"/mipeDownLoadNewEnvio.cgi", opciones{navegacion: true, content: cuerpo,
		referer: Base + "/mipeGenDLNewEnvio.cgi", origin: "https://www1.sii.cl"})
	if err != nil {
		return nil, err
	}
	if r.Status != 200 || !bytes.Contains(r.Cuerpo, []byte("<EnvioDTE")) {
		return nil, fmt.Errorf("%w: el portal no devolvió el XML del envío (dhdr %s, http %d)", ErrRechazo, dhdr, r.Status)
	}
	return r.Cuerpo, nil
}
