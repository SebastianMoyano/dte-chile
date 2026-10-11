package portal

import (
	"fmt"
	"strings"
)

// core/onboarding.py — diagnóstico automático de una empresa (solo lectura) y plan de pasos.

const (
	ModoAuto           = "auto"
	ModoConsentimiento = "consentimiento"
	ModoHumano         = "humano"
)

type Chequeo struct {
	ID      string `json:"id"`
	Titulo  string `json:"titulo"`
	Estado  string `json:"estado"` // ok | falta | atencion | desconocido
	Detalle string `json:"detalle"`
}

type Accion struct {
	Titulo  string `json:"titulo"`
	Detalle string `json:"detalle"`
	Modo    string `json:"modo"`
	Hecho   bool   `json:"hecho"`
	Urgente bool   `json:"urgente"`
}

type Diagnostico struct {
	Rut             string    `json:"rut"`
	RazonSocial     string    `json:"razon_social"`
	Estado          string    `json:"estado"` // emitiendo | externo | certificado | certificando | sin_propio
	Etiqueta        string    `json:"etiqueta"`
	Resumen         string    `json:"resumen"`
	ListoParaEmitir bool      `json:"listo_para_emitir"`
	Chequeos        []Chequeo `json:"chequeos"`
	Acciones        []Accion  `json:"acciones"`
	Notas           []string  `json:"notas"`
}

// Lector es lo que el diagnóstico necesita del portal (el Cliente real o un doble en tests).
type Lector interface {
	ConsultarEmpresaAutorizada(rut, base string) (*EmpresaAutorizadaDTE, error)
	DatosSoftwareDe(rut, base string) (DatosSoftware, error)
	SituacionFolios(rut string, tipos []int) (map[int]SituacionTipo, error)
	EmpresasAsociadas() ([]Empresa, error)
}

// EsNuestroSoftware es es_nuestro_software: compara con el nombre registrado por el motor y
// con NOMBRE_SOFTWARE (lista separada por coma). nil = no hay con qué comparar.
func EsNuestroSoftware(nombre, registrado, nombreSoftwareConfig string) *bool {
	var nuestros []string
	if strings.TrimSpace(registrado) != "" {
		nuestros = append(nuestros, strings.ToLower(strings.TrimSpace(registrado)))
	}
	for _, n := range strings.Split(nombreSoftwareConfig, ",") {
		if strings.TrimSpace(n) != "" {
			nuestros = append(nuestros, strings.ToLower(strings.TrimSpace(n)))
		}
	}
	if len(nuestros) == 0 || nombre == "" {
		return nil
	}
	n := strings.ToLower(nombre)
	r := false
	for _, x := range nuestros {
		if strings.Contains(n, x) || strings.Contains(x, n) {
			r = true
		}
	}
	return &r
}

// ClasificarSoftware es clasificar_software: (estado, etiqueta) de cómo emite la empresa hoy.
func ClasificarSoftware(prod, cert DatosSoftware, registrado, nombreSoftwareConfig string) (string, string) {
	sw := strings.TrimSpace(prod.Software)
	if prod.Propio {
		if es := EsNuestroSoftware(sw, registrado, nombreSoftwareConfig); es != nil && !*es {
			return "externo", fmt.Sprintf("Emite con «%s» (otro proveedor)", sw)
		}
		if sw != "" {
			return "emitiendo", fmt.Sprintf("Emite en producción con «%s»", sw)
		}
		return "emitiendo", "Emitiendo en producción con software propio"
	}
	if cert.Propio && cert.Certificado {
		return "certificado", "Software propio certificado — falta activarlo en producción"
	}
	if cert.Propio {
		return "certificando", "En certificación del software propio"
	}
	return "sin_propio", "Emite por el gratuito del SII"
}

// Diagnosticar es diagnosticar(): la batería de lecturas del SII + el plan. `registrado` es
// negocios.software_registrado(rut) (vacío si no hay) y `nombreSoftware` es NOMBRE_SOFTWARE.
func Diagnosticar(p Lector, rut, nombreSistema, registrado, nombreSoftware string) (*Diagnostico, error) {
	if nombreSistema == "" {
		nombreSistema = "tu software propio"
	}
	emp, err := p.ConsultarEmpresaAutorizada(rut, BaseProduccion)
	if err != nil {
		return nil, err
	}
	swProd, err := p.DatosSoftwareDe(rut, BaseProduccion)
	if err != nil {
		return nil, err
	}
	swCert, err := p.DatosSoftwareDe(rut, BaseCertificacion)
	if err != nil {
		return nil, err
	}
	sitCert, err := p.SituacionFolios(rut, []int{33, 61})
	if err != nil {
		return nil, err
	}
	razon := rut
	var autorizados []DocumentoAutorizado
	if emp != nil {
		if emp.RazonSocial != "" {
			razon = emp.RazonSocial
		}
		for _, d := range emp.Documentos {
			if d.DesautorizadoDesde == "" {
				autorizados = append(autorizados, d)
			}
		}
	}
	codigos := map[string]bool{}
	var listaCod []string
	for _, d := range autorizados {
		codigos[fmt.Sprint(d.Codigo)] = true
		listaCod = append(listaCod, fmt.Sprint(d.Codigo))
	}
	swActual := swProd.Software
	if swActual == "" {
		swActual = "el sistema gratuito del SII"
	}
	var bloqueados []int
	for _, t := range []int{33, 61} {
		if sitCert[t].Bloqueado {
			bloqueados = append(bloqueados, t)
		}
	}
	notas := []string{}
	if codigos["34"] && !codigos["33"] && !swProd.Propio {
		notas = append(notas, "Hoy estás autorizada a Factura Exenta (34) pero NO a Factura Afecta (33), "+
			"y emites por el sistema gratuito del SII. Eso es válido, pero para pasar a "+
			"software propio (o de mercado) la certificación del SET BÁSICO agrega la "+
			"Factura Afecta (33). No te obliga a emitir afectas — solo queda habilitada. "+
			"Por eso proveedores como Haulmer piden 'factura' aunque solo emitas exenta.")
	}
	estado, etiqueta := ClasificarSoftware(swProd, swCert, registrado, nombreSoftware)
	if estado == "externo" {
		notas = append(notas, fmt.Sprintf("Esta empresa emite hoy con «%s», otro proveedor de facturación. Mientras "+
			"siga así, NO emitas facturas con %s: los folios del CAF los administra "+
			"ese proveedor y se chocarían. Para migrar hay que cambiar el software registrado en el "+
			"SII y traspasar (o anular) los folios que le queden.", swActual, nombreSistema))
	}
	nombresBloq := func() string {
		var xs []string
		for _, t := range bloqueados {
			if t == 33 {
				xs = append(xs, "Factura(33)")
			} else {
				xs = append(xs, "NotaCrédito(61)")
			}
		}
		return strings.Join(xs, ", ")
	}
	chequeos := []Chequeo{
		{"empresa", "Empresa reconocida en el SII", ternario(emp != nil, "ok", "desconocido"), ternario(emp != nil, razon, fmt.Sprintf("El RUT %s no aparece en el SII.", rut))},
		{"facturador", "Inscrita como facturadora electrónica", ternario(len(autorizados) > 0, "ok", "falta"),
			ternario(len(autorizados) > 0, "Autorizada a emitir: "+strings.Join(listaCod, ", "), "No aparece autorizada a emitir DTE todavía.")},
		{"software", "Software de facturación actual", ternario(swProd.Propio, "ok", "atencion"),
			fmt.Sprintf("Emite con «%s»", swActual) + ternario(swProd.Propio, "", fmt.Sprintf(" — hay que cambiarlo a %s.", nombreSistema))},
		{"certificacion", "Certificación del software propio", ternario(swCert.Certificado, "ok", ternario(swCert.Propio, "atencion", "falta")),
			ternario(swCert.Certificado, "Certificado", ternario(swCert.Propio, "En curso", "No iniciada"))},
		{"folios", "Folios / timbraje para el set de pruebas", ternario(len(bloqueados) > 0, "atencion", "ok"),
			ternario(len(bloqueados) > 0, "Bloqueado en: "+nombresBloq(), "Sin bloqueos detectados")},
	}
	acciones := []Accion{}
	if estado == "emitiendo" {
		acciones = append(acciones, Accion{"Todo listo", fmt.Sprintf("Ya emites en producción con %s.", nombreSistema), ModoAuto, true, false})
	} else {
		if len(autorizados) == 0 {
			acciones = append(acciones, Accion{"Inscribir como facturador electrónico",
				"Declarar ante el SII que la empresa emitirá DTE. Requiere tu autorización (se hace con tu certificado).", ModoConsentimiento, false, false})
		}
		if estado == "sin_propio" {
			acciones = append(acciones, Accion{"Registrar tu software en el SII",
				fmt.Sprintf("Declarar «%s» como tu software de facturación (Actualización de datos del contribuyente).", nombreSistema), ModoConsentimiento, false, false})
		}
		if len(bloqueados) > 0 {
			acciones = append(acciones, Accion{"Destrabar folios de prueba", "El timbraje está bloqueado por anti-acaparamiento. Se gestiona con la Mesa de Ayuda del SII (600 330 3000).", ModoHumano, false, true})
		}
		acciones = append(acciones, Accion{"Completar el set de pruebas", "Emitir y validar los documentos del set de certificación (el sistema lo hace).", ModoAuto, estado == "certificado", false})
		acciones = append(acciones, Accion{"Obtener la resolución del SII", "Al terminar el set, el SII emite la resolución que autoriza tu software.", ModoAuto, estado == "certificado", false})
		acciones = append(acciones, Accion{"Activar en producción",
			fmt.Sprintf("Cambiar el software de facturación de «%s» a %s (Actualización de datos). Requiere tu autorización.", swActual, nombreSistema), ModoConsentimiento, false, false})
	}
	if codigos["39"] || codigos["41"] {
		acciones = append(acciones, Accion{"Declarar el modelo de emisión de boletas (si cobras con tarjeta)",
			"Hazlo UNA vez por empresa, con RUT y Clave de la EMPRESA (no la persona) en " +
				"www4.sii.cl/actatributointernetui: marca «Siempre emito Boleta… aún cuando " +
				"reciba un pago electrónico» (Modelo 1). Ojo: sin declarar, el SII asume que " +
				"el voucher de la tarjeta ES tu boleta (Modelo 2) y tus ventas quedarían " +
				"contadas doble. Guía paso a paso: docs/MODELO-EMISION.md.", ModoHumano, false, false})
	}
	resumen := fmt.Sprintf("%s: %s.", razon, strings.ToLower(etiqueta))
	if len(bloqueados) > 0 {
		resumen += " Hay folios bloqueados que destrabar."
	}
	return &Diagnostico{Rut: rut, RazonSocial: razon, Estado: estado, Etiqueta: etiqueta, Resumen: resumen,
		ListoParaEmitir: estado == "emitiendo", Chequeos: chequeos, Acciones: acciones, Notas: notas}, nil
}

func ternario(c bool, a, b string) string {
	if c {
		return a
	}
	return b
}

// DiagnosticarCartera es diagnosticar_cartera: todas las empresas del certificado (una sesión);
// una empresa que falle se omite. `registradoDe` entrega negocios.software_registrado(rut).
func DiagnosticarCartera(p Lector, ruts []string, nombreSistema string, registradoDe func(string) string, nombreSoftware string) ([]*Diagnostico, error) {
	if ruts == nil {
		emps, err := p.EmpresasAsociadas()
		if err != nil {
			return nil, err
		}
		for _, e := range emps {
			ruts = append(ruts, e.Rut)
		}
	}
	out := []*Diagnostico{}
	for _, r := range ruts {
		reg := ""
		if registradoDe != nil {
			reg = registradoDe(r)
		}
		d, err := Diagnosticar(p, r, nombreSistema, reg, nombreSoftware)
		if err != nil {
			continue
		}
		out = append(out, d)
	}
	return out, nil
}
