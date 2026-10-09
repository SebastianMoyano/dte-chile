package siiengine

import (
	"fmt"
	"html"
	"net/http"
	"net/url"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"time"

	"dtechile/nucleo/almacen"
)

// ---------------------------------------------------------------------------
// Segmentos 2-4 del SII engine: armado del payload (puro), "Validar y visualizar", NC de
// anulación y de corrección de montos, y la emisión real (GenXMLFirma → firma central →
// mipeSendXML → PDF). Réplica de core/sii_mipyme.py; la vara son los cuerpos byte a byte de
// la factura 63 y la NC 60 (storage/mipyme_fallidos/…).
// ---------------------------------------------------------------------------

// Receptor es ReceptorMipyme.
type Receptor struct {
	Rut, RazonSocial, Giro, Direccion, Ciudad, Comuna string
}

func (r Receptor) validar() error {
	if !ValidarRut(r.Rut) {
		return fmt.Errorf("%w: RUT de receptor inválido: %s", ErrValidacion, r.Rut)
	}
	return nil
}

// Item es ItemMipyme.
type Item struct {
	Nombre      string
	Precio      int64
	Cantidad    int
	Descripcion string
}

// Subtotal es precio × cantidad.
func (i Item) Subtotal() int64 { return i.Precio * int64(i.Cantidad) }

func sumaItems(items []Item) int64 {
	var t int64
	for _, i := range items {
		t += i.Subtotal()
	}
	return t
}

// Referencia es una referencia a otro documento (NC/ND).
type Referencia struct {
	Tipo   int
	Folio  int
	Fecha  string // YYYY-MM-DD
	Codigo string // "" → CodigoRefAnula
	Razon  string // "" → RazonRefAnula
}

// Payload es PayloadMipyme: listo para mipeGenXMLFirma, en el orden del schema (o del HTML en
// las notas). CamposNuevos es el drift: inputs que el HTML trae y el schema no conoce.
type Payload struct {
	Tipo           int
	Pares          []Par
	CamposNuevos   []string
	refererEmision string
}

// Valor devuelve el valor de un campo ("" si no está).
func (p *Payload) Valor(nombre string) string {
	for _, par := range p.Pares {
		if par.Nombre == nombre {
			return par.Valor
		}
	}
	return ""
}

// MontoTotal es EFXP_MNT_TOTAL como entero.
func (p *Payload) MontoTotal() int64 {
	n, _ := strconv.ParseInt(p.Valor("EFXP_MNT_TOTAL"), 10, 64)
	return n
}

func hoy() string { return time.Now().Format("2006-01-02") }

// ArmarPayload es armar_payload: payload = schema (orden) + valores del HTML fresco +
// sustituciones nuestras. Los montos van SIEMPRE alineados (PRC/SUBT de cada ítem y los 3
// totales salen del mismo número; HED-2-220 si no). En las notas el navegador manda el form
// PreViewDTE tal cual (orden y campos del HTML, incluidos los que el schema no conoce) con
// nuestras sustituciones encima, y lo que el HTML no trae pero el schema exige va al final.
func ArmarPayload(form Form, tipo int, receptor Receptor, items []Item, fecha, formaPago string,
	referencias []Referencia, respetarHTML []string) (*Payload, error) {
	if len(items) == 0 {
		return nil, fmt.Errorf("%w: la factura necesita al menos un ítem", ErrValidacion)
	}
	if len(items) > 10 {
		return nil, fmt.Errorf("%w: el form del portal admite hasta 10 ítems", ErrValidacion)
	}
	if err := receptor.validar(); err != nil {
		return nil, err
	}
	if fecha == "" {
		fecha = hoy()
	}
	rutN, dv := SepararRut(receptor.Rut)
	total := sumaItems(items)
	subs := map[string]string{
		"INDICA_PRIMERA_EJECUCION": "1", "ES_BORR": "FALSE",
		"PTDC_CODIGO": strconv.Itoa(tipo), "EFXP_FMA_PAGO": formaPago,
		"EFXP_FCH_EMIS":  fecha,
		"EFXP_RUT_RECEP": rutN, "EFXP_DV_RECEP": dv,
		"EFXP_RZN_SOC_RECEP": receptor.RazonSocial, "EFXP_GIRO_RECEP": receptor.Giro,
		"EFXP_DIR_RECEP": receptor.Direccion, "EFXP_CIUDAD_RECEP": receptor.Ciudad,
		"EFXP_CMNA_RECEP": receptor.Comuna,
	}
	for i := 1; i <= 10; i++ { // limpiar los 10 ítems que el form pre-llena "igual al último"
		for _, c := range camposItem {
			subs[fmt.Sprintf("EFXP_%s_%02d", c, i)] = ""
		}
	}
	esNota := tipo == TipoNotaCredito || tipo == TipoNotaDebito
	if !esNota {
		for i := 1; i <= 3; i++ { // una factura nueva no hereda referencias del último documento
			for _, c := range camposRef {
				subs[fmt.Sprintf("EFXP_%s_%03d", c, i)] = ""
			}
		}
		subs["EFXP_PCT_DESC"] = "0"
		subs["EFXP_MNT_DESC"] = "0"
	}
	for n, it := range items {
		k := fmt.Sprintf("%02d", n+1)
		subs["EFXP_NMB_"+k] = it.Nombre
		subs["EFXP_QTY_"+k] = strconv.Itoa(it.Cantidad)
		subs["EFXP_PRC_"+k] = strconv.FormatInt(it.Precio, 10)
		subs["EFXP_SUBT_"+k] = strconv.FormatInt(it.Subtotal(), 10)
		subs["EFXP_DSC_ITEM_"+k] = it.Descripcion
	}
	for _, c := range camposMontoTotal {
		subs[c] = strconv.FormatInt(total, 10)
	}
	for n, ref := range referencias {
		k := fmt.Sprintf("%03d", n+1)
		codigo, razon := ref.Codigo, ref.Razon
		if codigo == "" {
			codigo = CodigoRefAnula
		}
		if razon == "" {
			razon = RazonRefAnula
		}
		subs["EFXP_TPO_DOC_REF_"+k] = strconv.Itoa(ref.Tipo)
		subs["EFXP_FOLIO_REF_"+k] = strconv.Itoa(ref.Folio)
		subs["EFXP_FCH_REF_"+k] = ref.Fecha
		subs["EFXP_CODIGO_REF_"+k] = codigo
		subs["EFXP_RAZON_REF_"+k] = razon
	}
	for _, n := range respetarHTML { // campos que NO se sobreescriben
		if v, ok := form.Campos[n]; ok {
			subs[n] = v
		}
	}
	var pares []Par
	if esNota {
		for _, n := range form.Orden {
			if n == "btnSign" || n == "btnVolver" {
				continue
			}
			v, ok := subs[n]
			if !ok {
				v = form.Campos[n]
			}
			pares = append(pares, Par{n, v})
		}
		for _, n := range SchemaCampos {
			if _, ok := form.Campos[n]; !ok {
				pares = append(pares, Par{n, subs[n]})
			}
		}
	} else {
		for _, n := range SchemaCampos {
			v, ok := subs[n]
			if !ok {
				v = form.Campos[n]
			}
			pares = append(pares, Par{n, v})
		}
	}
	var nuevos []string
	for n := range form.Campos {
		if !enSchema[n] && !EsCampoHelper(n) {
			nuevos = append(nuevos, n)
		}
	}
	sort.Strings(nuevos)
	return &Payload{Tipo: tipo, Pares: pares, CamposNuevos: nuevos}, nil
}

// ---------------------------------------------------------------------------
// La página de firma (respuesta de mipeGenXMLFirma) y el cuerpo de mipeSendXML
// ---------------------------------------------------------------------------

// FormFirma es el `<form name="frmSign">` que devuelve mipeGenXMLFirma: lo que el navegador
// manda a mipeSendXML (más txtSignText y los datos de firma). Crudos es la lista en orden
// del HTML, CON duplicados (el frmSign real trae EFXP_FMA_PAGO dos veces y el navegador
// manda las dos; captura 2026-10-08, factura 62).
type FormFirma struct {
	Action string
	Campos map[string]string
	Crudos []Par
}

var (
	reFormTag   = regexp.MustCompile(`(?is)<form\b([^>]*)>([\s\S]*?)</form>`)
	reAttrName  = regexp.MustCompile(`(?i)name=["']([^"']+)`)
	reAttrAct   = regexp.MustCompile(`(?i)action=["']([^"']*)`)
	reAttrValue = regexp.MustCompile(`(?i)value=["']([^"']*)`)
	reInputTag  = regexp.MustCompile(`(?i)<input\b([^>]*)>`)
	reTextareaT = regexp.MustCompile(`(?is)<textarea\b([^>]*)>([\s\S]*?)</textarea>`)
	reXMLDTE    = regexp.MustCompile(`(?s)<\?xml.*?</DTE>`)
	reVarXML    = regexp.MustCompile(`(?s)var\s+\w*[Xx][Mm][Ll]\w*\s*=\s*['"](.*?)['"];`)
	reFolio     = regexp.MustCompile(`<Folio>(\d+)</Folio>`)
	reTmstFirma = regexp.MustCompile(`<TmstFirma>([^<]+)</TmstFirma>`)
	reMntTotal  = regexp.MustCompile(`<MntTotal>(\d+)</MntTotal>`)
	reCodigoSII = regexp.MustCompile(`CODIGO:\s*([\d.]+)`)
	reDHDR      = regexp.MustCompile(`DHDR_CODIGO=(\d+)`)
	reExito     = regexp.MustCompile(`(?i)Firmado y Enviado|ENVIADO EXITOSAMENTE|Documento\s+enviado`)
	reFirmaNo   = regexp.MustCompile(`(?i)Firma\s+no\s+reconocida`)
)

// ExtraerFormFirma es extraer_form_firma. nil si la página no trae frmSign.
func ExtraerFormFirma(doc string) *FormFirma {
	for _, m := range reFormTag.FindAllStringSubmatch(doc, -1) {
		attrs, inner := m[1], m[2]
		nombre := reAttrName.FindStringSubmatch(attrs)
		if nombre == nil || strings.ToLower(nombre[1]) != "frmsign" {
			continue
		}
		f := &FormFirma{Campos: ParsearForm("<form>" + inner + "</form>")}
		if a := reAttrAct.FindStringSubmatch(attrs); a != nil {
			f.Action = a[1]
		}
		type enc struct {
			pos int
			par Par
		}
		var encontrados []enc
		for _, im := range reInputTag.FindAllStringSubmatchIndex(inner, -1) {
			attrsIn := inner[im[2]:im[3]]
			n := reAttrName.FindStringSubmatch(attrsIn)
			if n == nil {
				continue
			}
			v := ""
			if vm := reAttrValue.FindStringSubmatch(attrsIn); vm != nil {
				v = html.UnescapeString(vm[1])
			}
			encontrados = append(encontrados, enc{im[0], Par{n[1], v}})
		}
		for _, tm := range reTextareaT.FindAllStringSubmatchIndex(inner, -1) {
			n := reAttrName.FindStringSubmatch(inner[tm[2]:tm[3]])
			if n == nil {
				continue
			}
			encontrados = append(encontrados, enc{tm[0], Par{n[1], html.UnescapeString(inner[tm[4]:tm[5]])}})
		}
		sort.SliceStable(encontrados, func(i, j int) bool { return encontrados[i].pos < encontrados[j].pos })
		for _, e := range encontrados {
			f.Crudos = append(f.Crudos, e.par)
		}
		return f
	}
	return nil
}

// ExtraerXMLDTE es extraer_xml_dte: el XML del DTE embebido en la página de GenXMLFirma.
func ExtraerXMLDTE(doc string) string {
	if m := reXMLDTE.FindString(doc); m != "" {
		return m
	}
	if m := reVarXML.FindStringSubmatch(doc); m != nil {
		return m[1]
	}
	return ""
}

func crlf(t string) string {
	return strings.ReplaceAll(strings.ReplaceAll(t, "\r\n", "\n"), "\n", "\r\n")
}

// ArmarSendXMLDesdeForm es armar_send_xml_desde_form: el body de mipeSendXML tal como lo manda
// el navegador (captura completa de la factura 62): TODOS los inputs del frmSign (con
// duplicados) más lo que el JS rellena (txtSignText, nombre, clave, nodo, nodoId, nameSpace;
// TMST_SIGN como venga en la página), los dos XML con CRLF, y el conjunto ordenado por nombre
// en orden ASCII (orden estable: los duplicados conservan su orden relativo).
func ArmarSendXMLDesdeForm(f *FormFirma, xmlFirmado, claveCert, tmstFirma string) []Par {
	crudos := f.Crudos
	if crudos == nil {
		for n, v := range f.Campos {
			crudos = append(crudos, Par{n, v})
		}
	}
	omitir := map[string]bool{"btnSign": true, "btnVolver": true, "txtSignText": true, "nombre": true,
		"clave": true, "nodo": true, "nodoId": true, "nameSpace": true}
	var pares []Par
	tieneTmst := false
	for _, p := range crudos {
		if omitir[p.Nombre] {
			continue
		}
		if p.Nombre == "TMST_SIGN" && p.Valor != "" {
			tieneTmst = true
		}
		pares = append(pares, p)
	}
	if !tieneTmst {
		var sin []Par
		for _, p := range pares {
			if p.Nombre != "TMST_SIGN" {
				sin = append(sin, p)
			}
		}
		pares = append(sin, Par{"TMST_SIGN", tmstFirma})
	}
	o := func(k, def string) string {
		if v := f.Campos[k]; v != "" {
			return v
		}
		return def
	}
	pares = append(pares, Par{"txtSignText", xmlFirmado}, Par{"nombre", o("nombre", "1")}, Par{"clave", claveCert},
		Par{"nodo", o("nodo", "dte:DTE")}, Par{"nodoId", o("nodoId", "dte:Documento")},
		Par{"nameSpace", o("nameSpace", "http://www.sii.cl/SiiDte")})
	for i, p := range pares {
		if p.Nombre == "txtPlainText" || p.Nombre == "txtSignText" {
			pares[i].Valor = crlf(p.Valor)
		}
	}
	sort.SliceStable(pares, func(i, j int) bool { return pares[i].Nombre < pares[j].Nombre })
	return pares
}

// ---------------------------------------------------------------------------
// Dry-runs (no gastan folio: el folio se asigna recién en GenXMLFirma)
// ---------------------------------------------------------------------------

func codigoSII(doc string) string {
	if m := reCodigoSII.FindStringSubmatch(doc); m != nil {
		return m[1]
	}
	return ""
}

func (c *Cliente) traza(nombre, contenido string) {
	if c.Trazas != nil {
		c.Trazas[nombre] = contenido
	}
}

// Preparar es preparar(): dry-run de una factura. Lee el form, hace el POST "Validar y
// visualizar" (mipeDisplayPreView, 54 campos, como el navegador) y arma el payload desde la
// página PreViewDTE que devuelve. Para una nota sin DHDR (56/61) arma el payload desde el
// form pre-llenado. NO gasta folio.
func (c *Cliente) Preparar(tipo int, receptor Receptor, items []Item, fecha, formaPago string) (*Payload, error) {
	if tipo == TipoNotaCredito || tipo == TipoNotaDebito {
		form, err := c.LeerForm(tipo)
		if err != nil {
			return nil, err
		}
		return ArmarPayload(form, tipo, receptor, items, fecha, formaPago, nil, nil)
	}
	if len(items) != 1 {
		return nil, fmt.Errorf("%w: el paso 'Validar y visualizar' de factura está calcado para 1 línea (el navegador manda EFXP_*_01); con más líneas hay que capturar ese flujo", ErrValidacion)
	}
	if err := receptor.validar(); err != nil {
		return nil, err
	}
	form, err := c.LeerForm(tipo)
	if err != nil {
		return nil, err
	}
	base := form.Campos
	if fecha == "" {
		fecha = hoy()
	}
	it := items[0]
	total := strconv.FormatInt(it.Subtotal(), 10)
	rutN, dv := SepararRut(receptor.Rut)
	dirOrigen := base["EFXP_DIR_ORIGEN"]
	if dirOrigen == "" {
		dirOrigen = base["EFXP_DIR_ORIGEN_DEFUALT"]
	}
	nuestros := map[string]string{
		"CANT_DET": "1", "DESCRIP_01": "DESCRIP_01", "EHDR_CODIGO": "", "ES_BORR": "FALSE",
		"PTDC_CODIGO": strconv.Itoa(tipo), "esCRED_EC": "FALSE", "esFACT_TUR": "FALSE",
		"EFXP_ACTECO_SELECT": base["EFXP_ACTECO"], "EFXP_TIPOCOMPRA_SELECT": "1", "EFXP_TIPOVENTA_SELECT": "1",
		"EFXP_FCH_EMIS": fecha, "EFXP_FMA_PAGO": formaPago,
		"EFXP_RUT_RECEP": rutN, "EFXP_DV_RECEP": dv, "EFXP_RZN_SOC_RECEP": receptor.RazonSocial,
		"EFXP_GIRO_RECEP": receptor.Giro, "EFXP_GIRO_RECEP_DEFUALT": receptor.Giro,
		// El JS del portal copia la dirección del campo auxiliar (_DEFUALT) al real y le deja
		// cuatro espacios al final; vacío → "Debe ingresar el campo: Direccion del contribuyente emisor".
		"EFXP_DIR_ORIGEN": strings.TrimRight(dirOrigen, " \t\r\n") + "    ",
		"EFXP_DIR_RECEP":  strings.TrimRight(receptor.Direccion, " \t\r\n") + "    ", "EFXP_DIR_RECEP_DEFUALT": receptor.Direccion,
		"EFXP_CIUDAD_RECEP": receptor.Ciudad, "EFXP_CMNA_RECEP": receptor.Comuna, "EFXP_CONTACTO": "",
		"EFXP_NMB_01": it.Nombre, "EFXP_QTY_01": strconv.Itoa(it.Cantidad), "EFXP_PRC_01": strconv.FormatInt(it.Precio, 10),
		"EFXP_SUBT_01": strconv.FormatInt(it.Subtotal(), 10), "EFXP_DSC_ITEM_01": it.Descripcion, "EFXP_UNMD_01": "", "EFXP_PCTD_01": "",
		"EFXP_PCT_DESC": "0", "EFXP_MNT_DESC": "0", "IVA_TEMP": "", "MNT_NETO_TEMP": total,
		"EFXP_SUBTOTAL": total, "EFXP_MNT_NETO": total, "EFXP_MNT_TOTAL": total,
	}
	pares := make([]Par, 0, len(CamposValidarFactura))
	for _, k := range CamposValidarFactura {
		v, ok := nuestros[k]
		if !ok {
			v = base[k]
		}
		pares = append(pares, Par{k, v})
	}
	cuerpo, err := CodificarLatin1(pares)
	if err != nil {
		return nil, fmt.Errorf("%w: %v", ErrValidacion, err)
	}
	c.traza("body_validar.txt", string(cuerpo))
	urlForm := fmt.Sprintf("%s/mipeGenFacEx.cgi?IGUAL=ULT_FAC&PTDC_CODIGO=%d&ES_BORR=FALSE&esCRED_EC=FALSE&esFACT_TUR=FALSE", Base, tipo)
	r, err := c.req("POST", Base+"/mipeDisplayPreView.cgi", opciones{navegacion: true, content: cuerpo, referer: urlForm, origin: "https://www1.sii.cl"})
	if err != nil {
		return nil, err
	}
	vista := r.Texto()
	c.traza("preview.html", vista)
	if r.rechazado() || !strings.Contains(vista, "PreViewDTE") {
		c.guardarEvidencia(tipo, 0, "validar", vista, "", pares, nil)
		return nil, fmt.Errorf("%w: el portal no aceptó 'Validar y visualizar' de la factura (http %d, %d bytes, código SII %q)", ErrRechazo, r.Status, len(vista), codigoSII(vista))
	}
	p, err := ArmarPayload(ParsearFormOrdenado(vista), tipo, receptor, items, fecha, formaPago, nil,
		[]string{"ES_BORR", "INDICA_PRIMERA_EJECUCION"})
	if err != nil {
		return nil, err
	}
	p.refererEmision = Base + "/mipeDisplayPreView.cgi"
	return p, nil
}

// TotalRegistrado es el TOTAL del documento tal como el SII lo registró, leído del XML del
// envío (firma central). Python lo lee del PDF; aquí se evita la dependencia de PDF: la NC
// exige la clave del certificado de todos modos. NO usar el monto del listado: en un
// documento inconsistente muestra la línea (factura 57: listado 3.270.323, total 3.068.005).
func (c *Cliente) TotalRegistrado(dhdr string, tipo int, rutReceptor string) (int64, error) {
	xml, err := c.ObtenerEnvioXML(dhdr, tipo, rutReceptor)
	if err != nil {
		return 0, err
	}
	m := reMntTotal.FindSubmatch(xml)
	if m == nil {
		return 0, fmt.Errorf("%w: el XML del documento %s no trae <MntTotal>", ErrSII, dhdr)
	}
	return strconv.ParseInt(string(m[1]), 10, 64)
}

// PrepararNCAnulacion es preparar_nc_anulacion: NC (61) que anula el documento dhdr. El portal
// pre-construye la NC en mipeDisplayPreView?EHDR_CODIGO&TIPO_NOTA=61; después es la misma
// cadena con PTDC_CODIGO=61 y la referencia código 1. Guardarraíl: la suma de items debe ser
// EXACTAMENTE el total registrado (si no, el SII la acepta con reparo REF-2-780 y el abono
// queda mal; costó la NC 56). NO gasta folio.
func (c *Cliente) PrepararNCAnulacion(dhdr string, tipoRef, folioRef int, fechaRef string, receptor Receptor,
	items []Item, fecha string, verificarMonto bool) (*Payload, error) {
	if err := c.requiereEmpresa(); err != nil {
		return nil, err
	}
	if err := receptor.validar(); err != nil {
		return nil, err
	}
	if verificarMonto {
		totalRef, err := c.TotalRegistrado(dhdr, tipoRef, receptor.Rut)
		if err != nil {
			return nil, err
		}
		if totalNC := sumaItems(items); totalNC != totalRef {
			return nil, fmt.Errorf("%w: la NC sumaría %d pero el documento %d/%d está registrado por %d: el SII la aceptaría con reparo REF-2-780 y el abono quedaría mal; usa el total registrado",
				ErrValidacion, totalNC, tipoRef, folioRef, totalRef)
		}
	}
	r, err := c.req("GET", Base+"/mipeDisplayPreView.cgi", opciones{navegacion: true,
		params:  []Par{{"EHDR_CODIGO", dhdr}, {"TIPO_NOTA", strconv.Itoa(TipoNotaCredito)}},
		referer: Base + "/mipeGesDocEmi.cgi?CODIGO=" + dhdr})
	if err != nil {
		return nil, err
	}
	vista := r.Texto()
	c.traza("nc_anulacion.html", vista)
	if r.rechazado() || len(r.Cuerpo) < 1000 {
		return nil, fmt.Errorf("%w: el portal no pre-construyó la NC de anulación (http %d, dhdr %s)", ErrRechazo, r.Status, dhdr)
	}
	ref := Referencia{Tipo: tipoRef, Folio: folioRef, Fecha: fechaRef, Codigo: CodigoRefAnula, Razon: RazonRefAnula}
	p, err := ArmarPayload(ParsearFormOrdenado(vista), TipoNotaCredito, receptor, items, fecha, "", []Referencia{ref},
		[]string{"ES_BORR", "EFXP_FMA_PAGO", "INDICA_PRIMERA_EJECUCION"})
	if err != nil {
		return nil, err
	}
	// El navegador firma desde la página de revisión: usarla como Referer en GenXMLFirma.
	p.refererEmision = fmt.Sprintf("%s/mipeDisplayPreView.cgi?EHDR_CODIGO=%s&TIPO_NOTA=%d", Base, dhdr, TipoNotaCredito)
	return p, nil
}

// PrepararNCCorreccionMontos es preparar_nc_correccion_montos: NC (61) código 3 sobre el
// documento dhdr, calcada del flujo real de la NC 59 (2026-10-04): GET del form IGUAL=CORR_MNT
// → POST "Validar y visualizar" con los 60 campos exactos → página PreViewDTE. Una NC por el
// total registrado deja el documento en cero. NO gasta folio.
func (c *Cliente) PrepararNCCorreccionMontos(dhdr string, tipoRef, folioRef int, fechaRef string, receptor Receptor,
	items []Item, fecha string, verificarMonto bool) (*Payload, error) {
	if err := c.requiereEmpresa(); err != nil {
		return nil, err
	}
	if err := receptor.validar(); err != nil {
		return nil, err
	}
	if len(items) > 3 {
		return nil, fmt.Errorf("%w: el formulario de corrección admite hasta 3 líneas", ErrValidacion)
	}
	urlForm := fmt.Sprintf("%s/mipeGenFacEx.cgi?IGUAL=CORR_MNT&VALOR=%s&PTDC_CODIGO=%d", Base, dhdr, TipoNotaCredito)
	r, err := c.req("GET", Base+"/mipeGenFacEx.cgi", opciones{navegacion: true,
		referer: Base + "/mipeGesDocEmi.cgi?ALL_PAGE_ANT=2&CODIGO=" + dhdr,
		params:  []Par{{"IGUAL", "CORR_MNT"}, {"VALOR", dhdr}, {"PTDC_CODIGO", strconv.Itoa(TipoNotaCredito)}}})
	if err != nil {
		return nil, err
	}
	doc := r.Texto()
	c.traza("corr_form.html", doc)
	if r.rechazado() || len(doc) < 5000 {
		return nil, fmt.Errorf("%w: el portal no entregó el formulario de corrección de montos (dhdr %s, http %d)", ErrRechazo, dhdr, r.Status)
	}
	base := ParsearForm(doc)
	totalTxt := base["EFXP_MNT_TOTAL"]
	if totalTxt == "" {
		totalTxt = base["MNT_TOTAL_ORI"]
	}
	totalRef, _ := strconv.ParseInt(reNoDigito.ReplaceAllString(totalTxt, ""), 10, 64)
	totalNC := sumaItems(items)
	if verificarMonto && (totalRef <= 0 || totalNC > totalRef) {
		return nil, fmt.Errorf("%w: la NC de corrección sumaría %d y el documento está registrado por %d", ErrValidacion, totalNC, totalRef)
	}
	if fecha == "" {
		fecha = hoy()
	}
	rutN, dv := SepararRut(receptor.Rut)
	tr := strconv.FormatInt(totalRef, 10)
	tn := strconv.FormatInt(totalNC, 10)
	nuestros := map[string]string{
		"CANT_DET": "3", "DESCRIP_01": "DESCRIP_01", "REF_SI_NO": "SiChecked", "TIPO_PLANTILLA": "CORR_MNT_V_NC",
		"esCRED_EC": "FALSE", "IVA_TEMP": "", "MNT_NETO_TEMP": tr, "MNT_TOTAL_ORI": tr,
		"EHDR_CODIGO": dhdr, "PTDC_CODIGO": strconv.Itoa(TipoNotaCredito), "EFXP_FCH_EMIS": fecha,
		"EFXP_RUT_RECEP": rutN, "EFXP_DV_RECEP": dv, "EFXP_RZN_SOC_RECEP": receptor.RazonSocial,
		"EFXP_GIRO_RECEP": receptor.Giro, "EFXP_DIR_RECEP": receptor.Direccion, "EFXP_CIUDAD_RECEP": receptor.Ciudad,
		"EFXP_CMNA_RECEP": receptor.Comuna, "EFXP_PCT_DESC": "0", "EFXP_MNT_DESC": "0",
		"EFXP_SUBTOTAL": tn, "EFXP_MNT_NETO": tn, "EFXP_MNT_TOTAL": tn,
		"EFXP_TPO_DOC_REF_001": strconv.Itoa(tipoRef), "EFXP_FOLIO_REF_001": strconv.Itoa(folioRef), "EFXP_FCH_REF_001": fechaRef,
		"EFXP_CODIGO_REF_001": CodigoRefCorrigeMonto, "EFXP_RAZON_REF_001": RazonRefCorrigeMonto, "EFXP_IND_GLOBAL_001": "",
	}
	for i := 1; i <= 3; i++ {
		for _, cmp := range []string{"NMB", "QTY", "PRC", "SUBT", "UNMD", "PCTD"} {
			nuestros[fmt.Sprintf("EFXP_%s_%02d", cmp, i)] = ""
		}
	}
	nuestros["EFXP_DSC_ITEM_01"] = ""
	for n, it := range items {
		k := fmt.Sprintf("%02d", n+1)
		nuestros["EFXP_NMB_"+k] = it.Nombre
		nuestros["EFXP_QTY_"+k] = strconv.Itoa(it.Cantidad)
		nuestros["EFXP_PRC_"+k] = strconv.FormatInt(it.Precio, 10)
		nuestros["EFXP_SUBT_"+k] = strconv.FormatInt(it.Subtotal(), 10)
		if n == 0 {
			nuestros["EFXP_DSC_ITEM_01"] = it.Descripcion
		}
	}
	pares := make([]Par, 0, len(CamposValidarCorrMnt))
	for _, k := range CamposValidarCorrMnt {
		v, ok := nuestros[k]
		if !ok {
			v = base[k]
		}
		pares = append(pares, Par{k, v})
	}
	cuerpo, err := CodificarLatin1(pares)
	if err != nil {
		return nil, fmt.Errorf("%w: %v", ErrValidacion, err)
	}
	c.traza("body_corr_validar.txt", string(cuerpo))
	r, err = c.req("POST", Base+"/mipeDisplayPreView.cgi", opciones{navegacion: true, content: cuerpo, referer: urlForm, origin: "https://www1.sii.cl"})
	if err != nil {
		return nil, err
	}
	vista := r.Texto()
	c.traza("corr_preview.html", vista)
	if r.rechazado() || !strings.Contains(vista, "PreViewDTE") {
		return nil, fmt.Errorf("%w: el portal no aceptó 'Validar y visualizar' de la NC de corrección (dhdr %s, http %d, %d bytes, código SII %q)", ErrRechazo, dhdr, r.Status, len(vista), codigoSII(vista))
	}
	ref := Referencia{Tipo: tipoRef, Folio: folioRef, Fecha: fechaRef, Codigo: CodigoRefCorrigeMonto, Razon: RazonRefCorrigeMonto}
	p, err := ArmarPayload(ParsearFormOrdenado(vista), TipoNotaCredito, receptor, items, fecha, "", []Referencia{ref},
		[]string{"ES_BORR", "EFXP_FMA_PAGO", "INDICA_PRIMERA_EJECUCION"})
	if err != nil {
		return nil, err
	}
	p.refererEmision = Base + "/mipeDisplayPreView.cgi"
	return p, nil
}

// ---------------------------------------------------------------------------
// Emisión (PAGA: gasta un folio real en producción)
// ---------------------------------------------------------------------------

// OpcionesEmitir: Confirmar es obligatorio (no hay sandbox, L1); AceptarRiesgoFolio es
// obligatorio mientras el tipo no esté en CadenasVerificadas.
type OpcionesEmitir struct {
	Confirmar          bool
	ConPDF             bool
	AceptarRiesgoFolio bool
}

// Resultado es ResultadoMipyme.
type Resultado struct {
	Tipo       int    `json:"tipo"`
	Folio      int    `json:"folio"`
	DHDR       string `json:"dhdr"`        // id del documento en el portal (PDF y NC)
	XMLFirmado string `json:"xml_firmado"` // con la <Signature> puesta por el SII
	MontoTotal int64  `json:"monto_total"`
	PDF        []byte `json:"-"`
}

func (c *Cliente) log(format string, a ...any) {
	if c.Log != nil {
		c.Log(format, a...)
	}
}

// Emitir es emitir(): GenXMLFirma (gasta el folio) → firma central → mipeSendXML → PDF.
func (c *Cliente) Emitir(p *Payload, op OpcionesEmitir) (*Resultado, error) {
	if !op.Confirmar {
		return nil, fmt.Errorf("%w: Emitir gasta un folio real en PRODUCCIÓN: llámalo con Confirmar", ErrValidacion)
	}
	if _, ok := CadenasVerificadas[p.Tipo]; !ok && !op.AceptarRiesgoFolio {
		return nil, fmt.Errorf("%w: la cadena de emisión del tipo %d NO está verificada contra el SII desde Go; si falla después de GenXMLFirma se pierde un folio; para correrla igual: AceptarRiesgoFolio", ErrValidacion, p.Tipo)
	}
	if err := c.requiereEmpresa(); err != nil {
		return nil, err
	}
	if _, ok := CadenasVerificadas[p.Tipo]; !ok {
		c.log("SII engine: emitiendo tipo %d con cadena NO verificada desde Go (riesgo de folio aceptado)", p.Tipo)
	}
	if len(p.CamposNuevos) > 0 {
		c.log("emitiendo con drift del form (campos nuevos: %v)", p.CamposNuevos)
	}
	c.log("SII engine → PRODUCCIÓN: emitiendo tipo %d por $%d para la empresa %s", p.Tipo, p.MontoTotal(), c.Empresa)

	// 3. GenXMLFirma — desde aquí el folio ya está gastado
	cuerpo, err := CodificarLatin1(p.Pares)
	if err != nil {
		return nil, fmt.Errorf("%w: %v", ErrValidacion, err)
	}
	referer := p.refererEmision
	if referer == "" {
		referer = fmt.Sprintf("%s/mipeGenFacEx.cgi?IGUAL=ULT_FAC&PTDC_CODIGO=%d", Base, p.Tipo)
	}
	r, err := c.req("POST", Base+"/mipeGenXMLFirma.cgi", opciones{navegacion: false, content: cuerpo, referer: referer})
	if err != nil {
		return nil, err
	}
	doc := r.Texto()
	if r.rechazado() {
		return nil, fmt.Errorf("%w: mipeGenXMLFirma rechazado (¿payload incompleto?; http %d)", ErrRechazo, r.Status)
	}
	formFirma := ExtraerFormFirma(doc)
	extras := map[string]string{"respuesta_genxmlfirma.html": doc}
	xml := ""
	if formFirma != nil {
		xml = formFirma.Campos["txtPlainText"]
	}
	if xml == "" {
		xml = ExtraerXMLDTE(doc)
	}
	if xml == "" || !strings.Contains(xml, "<DTE") {
		c.guardarEvidencia(p.Tipo, 0, "genxml", doc, "", p.Pares, nil)
		return nil, fmt.Errorf("%w: mipeGenXMLFirma no devolvió el XML del DTE (código SII %q)", ErrSII, codigoSII(doc))
	}
	mf := reFolio.FindStringSubmatch(xml)
	if mf == nil {
		return nil, fmt.Errorf("%w: el XML del portal no trae <Folio>", ErrSII)
	}
	folio, _ := strconv.Atoi(mf[1])
	c.log("SII engine: folio %d asignado (tipo %d); frmSign %s", folio, p.Tipo, map[bool]string{true: "encontrado", false: "NO encontrado"}[formFirma != nil])

	// 4. Firma central — clave del CERTIFICADO. La cookie la pone el JS del portal.
	www1, _ := url.Parse("https://www1.sii.cl/")
	c.jar.SetCookies(www1, []*http.Cookie{{Name: "usa_firma_central", Value: "true", Path: "/", Domain: "www1.sii.cl"}})
	dato := xml
	if p.Tipo == TipoNotaCredito || p.Tipo == TipoNotaDebito {
		dato = PrepararDatoFirma(xml)
	}
	rf, cruda, err := c.firmaCentral(dato, "dte:DTE", "dte:Documento", Base+"/mipeGenXMLFirma.cgi")
	if err != nil {
		return nil, err
	}
	extras["respuesta_postfirma_cruda.txt"] = cruda
	estadoFirma, firmado := ParsearRespuestaFirma(cruda)
	if estadoFirma == 2 || regexp.MustCompile(`(?i)clave no corresponde`).MatchString(cruda) {
		c.guardarEvidencia(p.Tipo, folio, "firma", cruda, "", p.Pares, extras)
		return nil, fmt.Errorf("%w: la firma central rechazó la clave del certificado (folio %d gastado sin documento); es la clave del .p12, no la tributaria", ErrAutenticacion, folio)
	}
	if rf.Status != 200 || estadoFirma != 0 || !strings.Contains(firmado, "<Signature") {
		carpeta := c.guardarEvidencia(p.Tipo, folio, "firma", firmado, "", p.Pares, extras)
		return nil, fmt.Errorf("%w: la firma central falló para el folio %d (¿clave del certificado incorrecta?); el folio quedó gastado sin documento; evidencia en %s", ErrRechazo, folio, carpeta)
	}
	tmst := ""
	if m := reTmstFirma.FindStringSubmatch(firmado); m != nil {
		tmst = m[1]
	}

	// 5. Envío, SOLO con el frmSign real de la página de firma (lo único que manda el navegador).
	if formFirma == nil || formFirma.Campos["txtPlainText"] == "" {
		carpeta := c.guardarEvidencia(p.Tipo, folio, "sin_frmsign", doc, firmado, p.Pares, extras)
		return nil, fmt.Errorf("%w: mipeGenXMLFirma no devolvió el formulario de firma (frmSign); folio %d firmado y NO enviado; evidencia en %s", ErrSII, folio, carpeta)
	}
	pares := ArmarSendXMLDesdeForm(formFirma, firmado, c.claveCert, tmst)
	action := html.UnescapeString(formFirma.Action)
	if action == "" {
		action = "mipeSendXML.cgi"
	}
	baseURL, _ := url.Parse(Base + "/mipeGenXMLFirma.cgi")
	ref, err := url.Parse(action)
	if err != nil {
		return nil, fmt.Errorf("%w: action del frmSign inválido: %q", ErrSII, action)
	}
	urlEnvio := baseURL.ResolveReference(ref).String()
	c.log("SII engine: envío con frmSign (%d campos) → %s", len(pares), urlEnvio)
	cuerpoEnvio, err := CodificarLatin1(pares)
	if err != nil {
		return nil, fmt.Errorf("%w: %v", ErrValidacion, err)
	}
	re, err := c.req("POST", urlEnvio, opciones{navegacion: true, content: cuerpoEnvio, referer: Base + "/mipeGenXMLFirma.cgi", origin: "https://www1.sii.cl"})
	if err != nil {
		return nil, err
	}
	out := re.Texto()
	destino := re.Header.Get("Location")
	m := reDHDR.FindStringSubmatch(out)
	if m == nil {
		m = reDHDR.FindStringSubmatch(destino)
	}
	exito := m != nil || reExito.MatchString(out)
	if reFirmaNo.MatchString(out) {
		exito = false
	}
	rechazado := strings.Contains(out, "Request Rejected") || (re.Status != 200 && re.Status != 302)
	if rechazado || !exito {
		carpeta := c.guardarEvidencia(p.Tipo, folio, "envio", out, firmado, pares, extras)
		motivo := "respuesta inesperada"
		if strings.Contains(out, "Request Rejected") {
			motivo = "WAF: Request Rejected"
		}
		return nil, fmt.Errorf("%w: mipeSendXML no confirmó el envío del folio %d (%s); el folio ya está gastado y firmado: revisar en el portal si el documento quedó emitido antes de reintentar; evidencia en %s", ErrRechazo, folio, motivo, carpeta)
	}
	dhdr := ""
	if m != nil {
		dhdr = m[1]
	}
	c.guardarEvidencia(p.Tipo, folio, "ok", out, firmado, pares, extras)
	res := &Resultado{Tipo: p.Tipo, Folio: folio, DHDR: dhdr, XMLFirmado: firmado, MontoTotal: p.MontoTotal()}
	c.log("SII engine: tipo %d folio %d emitido, DHDR=%s", p.Tipo, folio, dhdr)
	if op.ConPDF && dhdr != "" {
		if pdf, err := c.DescargarPDF(dhdr); err != nil {
			c.log("PDF del DHDR %s no disponible: %v", dhdr, err)
		} else {
			res.PDF = pdf
		}
	}
	return res, nil
}

// RegistrarEnBD es registrar_en_bd: guarda el documento en `dtes` con ambiente producción y
// estado emitido_mipyme; el DHDR va en track_id. Idempotente por (rut, tipo, folio).
func RegistrarEnBD(al *almacen.Almacen, res *Resultado, rutEmisor string, receptor Receptor, fechaEmision string) (int64, error) {
	rut := FormatearRut(rutEmisor, false)
	track, _ := strconv.ParseInt(res.DHDR, 10, 64)
	if fila, err := al.DTEPorFolio(rut, res.Tipo, res.Folio); err != nil {
		return 0, err
	} else if fila != nil {
		return fila.ID, al.ActualizarEstado(fila.ID, "emitido_mipyme", track)
	}
	id, err := al.CrearDTE(almacen.DTE{TipoDTE: res.Tipo, Folio: res.Folio, RutEmisor: rut,
		RutReceptor: FormatearRut(receptor.Rut, false), RazonSocialReceptor: receptor.RazonSocial,
		FechaEmision: fechaEmision, MontoExento: res.MontoTotal, MontoTotal: res.MontoTotal,
		XMLFirmado: res.XMLFirmado, Ambiente: "produccion"})
	if err != nil {
		return 0, err
	}
	return id, al.ActualizarEstado(id, "emitido_mipyme", track)
}

// ReceptorEItemsDesdeForm lee del formulario pre-construido por el portal (la NC de
// anulación de un documento) el receptor y las líneas del documento original, sin espacios
// de relleno. Sirve para anular "tal cual" sin que la persona vuelva a teclear nada.
func ReceptorEItemsDesdeForm(form Form) (Receptor, []Item) {
	c := form.Campos
	rec := Receptor{Rut: strings.TrimSpace(c["EFXP_RUT_RECEP"]) + "-" + strings.TrimSpace(c["EFXP_DV_RECEP"]),
		RazonSocial: strings.TrimSpace(c["EFXP_RZN_SOC_RECEP"]), Giro: strings.TrimSpace(c["EFXP_GIRO_RECEP"]),
		Direccion: strings.TrimSpace(c["EFXP_DIR_RECEP"]), Ciudad: strings.TrimSpace(c["EFXP_CIUDAD_RECEP"]),
		Comuna: strings.TrimSpace(c["EFXP_CMNA_RECEP"])}
	var items []Item
	for i := 1; i <= 10; i++ {
		k := fmt.Sprintf("%02d", i)
		nombre := strings.TrimSpace(c["EFXP_NMB_"+k])
		if nombre == "" {
			continue
		}
		qty, _ := strconv.Atoi(reNoDigito.ReplaceAllString(c["EFXP_QTY_"+k], ""))
		if qty <= 0 {
			qty = 1
		}
		prc, _ := strconv.ParseInt(reNoDigito.ReplaceAllString(c["EFXP_PRC_"+k], ""), 10, 64)
		items = append(items, Item{Nombre: nombre, Precio: prc, Cantidad: qty, Descripcion: strings.TrimSpace(c["EFXP_DSC_ITEM_"+k])})
	}
	return rec, items
}

// PrepararNCAnulacionDesdePortal es PrepararNCAnulacion tomando receptor e ítems del propio
// formulario que el portal pre-construye para anular el documento dhdr (lo que usa la app:
// la persona elige el documento y nada más). Mismo guardarraíl del total registrado.
func (c *Cliente) PrepararNCAnulacionDesdePortal(dhdr string, tipoRef, folioRef int, fechaRef, fecha string, verificarMonto bool) (*Payload, Receptor, []Item, error) {
	if err := c.requiereEmpresa(); err != nil {
		return nil, Receptor{}, nil, err
	}
	r, err := c.req("GET", Base+"/mipeDisplayPreView.cgi", opciones{navegacion: true,
		params:  []Par{{"EHDR_CODIGO", dhdr}, {"TIPO_NOTA", strconv.Itoa(TipoNotaCredito)}},
		referer: Base + "/mipeGesDocEmi.cgi?CODIGO=" + dhdr})
	if err != nil {
		return nil, Receptor{}, nil, err
	}
	vista := r.Texto()
	c.traza("nc_anulacion.html", vista)
	if r.rechazado() || len(r.Cuerpo) < 1000 {
		return nil, Receptor{}, nil, fmt.Errorf("%w: el portal no pre-construyó la NC de anulación (http %d, dhdr %s)", ErrRechazo, r.Status, dhdr)
	}
	form := ParsearFormOrdenado(vista)
	receptor, items := ReceptorEItemsDesdeForm(form)
	if err := receptor.validar(); err != nil {
		return nil, Receptor{}, nil, fmt.Errorf("%w (receptor según el portal: %q)", err, receptor.Rut)
	}
	if len(items) == 0 {
		return nil, Receptor{}, nil, fmt.Errorf("%w: el formulario de la NC no trae líneas del documento", ErrSII)
	}
	if verificarMonto {
		totalRef, err := c.TotalRegistrado(dhdr, tipoRef, receptor.Rut)
		if err != nil {
			return nil, Receptor{}, nil, err
		}
		if totalNC := sumaItems(items); totalNC != totalRef {
			return nil, Receptor{}, nil, fmt.Errorf("%w: las líneas del formulario suman %d pero el documento %d/%d está registrado por %d (documento inconsistente: anular a mano por el total registrado)",
				ErrValidacion, totalNC, tipoRef, folioRef, totalRef)
		}
	}
	ref := Referencia{Tipo: tipoRef, Folio: folioRef, Fecha: fechaRef, Codigo: CodigoRefAnula, Razon: RazonRefAnula}
	p, err := ArmarPayload(form, TipoNotaCredito, receptor, items, fecha, "", []Referencia{ref},
		[]string{"ES_BORR", "EFXP_FMA_PAGO", "INDICA_PRIMERA_EJECUCION"})
	if err != nil {
		return nil, Receptor{}, nil, err
	}
	p.refererEmision = fmt.Sprintf("%s/mipeDisplayPreView.cgi?EHDR_CODIGO=%s&TIPO_NOTA=%d", Base, dhdr, TipoNotaCredito)
	return p, receptor, items, nil
}
