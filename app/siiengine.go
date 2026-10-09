package main

// El SII engine dentro de la app: `nucleo/siiengine` corre en este proceso (sin pasar por el
// motor Python) para sincronizar lo emitido en el sistema de facturación del SII. Las claves
// vienen de la interfaz (memoria de la app) o, si la persona las recordó, del keystore del
// motor vía `/api/v1/mipyme/contexto-siiengine/{rut}` (mismo modelo de confianza que
// contexto-emision). Nunca se escriben en disco ni en el log.

import (
	"encoding/json"
	"fmt"
	"net/url"
	"os"
	"strings"
	"time"

	"dtechile/nucleo/almacen"
	"dtechile/nucleo/siiengine"
)

type contextoSIIEngine struct {
	RutUsuario       string `json:"rut_usuario"`
	ClaveTributaria  string `json:"clave_tributaria"`
	ClaveCertificado string `json:"clave_certificado"`
	DatabasePath     string `json:"database_path"`
	StoragePath      string `json:"storage_path"`
}

func (a *App) contextoSIIEngine(rutEmpresa string) (*contextoSIIEngine, error) {
	r, err := a.API("GET", "/api/v1/mipyme/contexto-siiengine/"+url.PathEscape(rutEmpresa), "")
	if err != nil {
		return nil, err
	}
	if r.Status != 200 {
		return nil, fmt.Errorf("contexto del SII engine: %s", r.Cuerpo)
	}
	var c contextoSIIEngine
	if err := json.Unmarshal([]byte(r.Cuerpo), &c); err != nil {
		return nil, err
	}
	return &c, nil
}

// SIIEngineSincronizar entra al SII como la persona, lista lo emitido por la empresa e
// importa PDF (y XML si hay clave del certificado) a la misma base del motor. Solo lectura en
// el SII. Devuelve el mismo JSON que `/api/v1/mipyme/sincronizar`, más "motor": "go".
func (a *App) SIIEngineSincronizar(rutEmpresa, rutUsuario, claveTributaria, claveCertificado string, recordar bool) (string, error) {
	ctx, err := a.contextoSIIEngine(rutEmpresa)
	if err != nil {
		return "", err
	}
	if recordar && (rutUsuario != "" || claveTributaria != "" || claveCertificado != "") {
		cuerpo, _ := json.Marshal(map[string]any{"rut_empresa": rutEmpresa, "rut_usuario": rutUsuario,
			"clave_tributaria": claveTributaria, "clave_certificado": claveCertificado})
		if r, err := a.API("PUT", "/api/v1/keystore/claves-sii", string(cuerpo)); err != nil || r.Status != 200 {
			return "", fmt.Errorf("no se pudieron recordar las claves (%v)", err)
		}
	}
	if rutUsuario == "" {
		rutUsuario = ctx.RutUsuario
	}
	if claveTributaria == "" {
		claveTributaria = ctx.ClaveTributaria
	}
	if claveCertificado == "" {
		claveCertificado = ctx.ClaveCertificado
	}
	if rutUsuario == "" || claveTributaria == "" {
		return "", fmt.Errorf("faltan el RUT de la persona autorizada y/o su clave tributaria")
	}
	cli, err := siiengine.Nuevo(rutUsuario, claveTributaria, claveCertificado)
	if err != nil {
		return "", err
	}
	cli.RaizStorage = ctx.StoragePath
	defer cli.Cerrar()
	if err := cli.IniciarSesion(); err != nil {
		return "", err
	}
	if err := cli.SeleccionarEmpresa(rutEmpresa); err != nil {
		return "", err
	}
	form, err := cli.LeerForm(siiengine.TipoFacturaExenta)
	if err != nil {
		return "", err
	}
	docs, err := cli.ListarEmitidos("", "", "")
	if err != nil {
		return "", err
	}
	alm, err := almacen.Abrir(ctx.DatabasePath)
	if err != nil {
		return "", err
	}
	defer alm.Cerrar()
	res, err := siiengine.Importar(cli, alm, rutEmpresa, docs, siiengine.OpcionesImportar{
		ConPDF: true, ConXML: claveCertificado != "", Carpeta: ctx.StoragePath, Pausa: 500 * time.Millisecond})
	if err != nil {
		return "", err
	}
	campos := form.Campos
	salida := map[string]any{
		"listados": res.Listados, "importados": res.Importados, "ya_existian": res.YaExistian, "sin_tipo": res.SinTipo,
		"pdf_ok": res.PDFOk, "pdf_falta": res.PDFFalta, "xml_ok": res.XMLOk, "xml_falta": res.XMLFalta,
		"documentos": res.Documentos, "avisos": res.Avisos,
		"ambiente": "produccion", "motor": "go",
		"emisor_segun_portal": map[string]string{"razon_social": campos["EFXP_RZN_SOC"], "giro": campos["EFXP_GIRO_EMIS"],
			"acteco": campos["EFXP_ACTECO"], "comuna": campos["EFXP_CMNA_ORIGEN"]},
		"nota": "Solo lectura en el SII: sesión comprobada, historial listado y PDF descargados. Nada se emitió.",
	}
	out, _ := json.Marshal(salida)
	return string(out), nil
}

// DocumentoSIIEngine es lo que la pantalla Cobrar manda para una factura exenta por el SII engine.
type DocumentoSIIEngine struct {
	Receptor struct {
		Rut, RazonSocial, Giro, Direccion, Ciudad, Comuna string
	} `json:"receptor"`
	Item struct {
		Nombre      string `json:"nombre"`
		Precio      int64  `json:"precio"`
		Descripcion string `json:"descripcion"`
	} `json:"item"`
	Fecha     string `json:"fecha"`
	FormaPago string `json:"forma_pago"`
}

// SIIEngineFactura arma (y, con emitir=true, emite) una factura exenta por el SII engine. Sin
// emitir es un dry-run real contra el portal: valida y devuelve la vista previa sin gastar
// folio. Emitir de verdad exige que la cadena esté verificada desde Go (CadenasVerificadas):
// la interfaz NO puede aceptar el riesgo de folio por la persona (ley L10 del repo); hasta
// entonces la emisión real se hace por el CLI nucleo-siiengine.
func (a *App) SIIEngineFactura(rutEmpresa, rutUsuario, claveTributaria, claveCertificado string, recordar bool, docJSON string, emitir bool) (string, error) {
	var d DocumentoSIIEngine
	if err := json.Unmarshal([]byte(docJSON), &d); err != nil {
		return "", fmt.Errorf("documento inválido: %v", err)
	}
	// claves JSON en snake_case para el receptor
	var crudo struct {
		Receptor map[string]string `json:"receptor"`
	}
	json.Unmarshal([]byte(docJSON), &crudo)
	rec := siiengine.Receptor{Rut: crudo.Receptor["rut"], RazonSocial: crudo.Receptor["razon_social"], Giro: crudo.Receptor["giro"],
		Direccion: crudo.Receptor["direccion"], Ciudad: crudo.Receptor["ciudad"], Comuna: crudo.Receptor["comuna"]}
	if d.FormaPago == "" {
		d.FormaPago = "1"
	}
	ctx, err := a.contextoSIIEngine(rutEmpresa)
	if err != nil {
		return "", err
	}
	if recordar && (rutUsuario != "" || claveTributaria != "" || claveCertificado != "") {
		cuerpo, _ := json.Marshal(map[string]any{"rut_empresa": rutEmpresa, "rut_usuario": rutUsuario,
			"clave_tributaria": claveTributaria, "clave_certificado": claveCertificado})
		if r, err := a.API("PUT", "/api/v1/keystore/claves-sii", string(cuerpo)); err != nil || r.Status != 200 {
			return "", fmt.Errorf("no se pudieron recordar las claves (%v)", err)
		}
	}
	if rutUsuario == "" {
		rutUsuario = ctx.RutUsuario
	}
	if claveTributaria == "" {
		claveTributaria = ctx.ClaveTributaria
	}
	if claveCertificado == "" {
		claveCertificado = ctx.ClaveCertificado
	}
	if rutUsuario == "" || claveTributaria == "" {
		return "", fmt.Errorf("faltan el RUT de la persona autorizada y/o su clave tributaria")
	}
	_, verificada := siiengine.CadenasVerificadas[siiengine.TipoFacturaExenta]
	if emitir && !verificada {
		return "", fmt.Errorf("la emisión por el SII engine desde Go todavía no está verificada con una corrida real: por ahora se emite con el CLI nucleo-siiengine (ver docs/PLAN-PORT.md, fase 6)")
	}
	if emitir && claveCertificado == "" {
		return "", fmt.Errorf("emitir exige la clave del certificado (firma central del SII)")
	}
	cli, err := siiengine.Nuevo(rutUsuario, claveTributaria, claveCertificado)
	if err != nil {
		return "", err
	}
	cli.RaizStorage = ctx.StoragePath
	defer cli.Cerrar()
	if err := cli.IniciarSesion(); err != nil {
		return "", err
	}
	if err := cli.SeleccionarEmpresa(rutEmpresa); err != nil {
		return "", err
	}
	items := []siiengine.Item{{Nombre: d.Item.Nombre, Precio: d.Item.Precio, Cantidad: 1, Descripcion: d.Item.Descripcion}}
	p, err := cli.Preparar(siiengine.TipoFacturaExenta, rec, items, d.Fecha, d.FormaPago)
	if err != nil {
		return "", err
	}
	salida := map[string]any{
		"dry_run": !emitir, "tipo": p.Tipo, "monto_total": p.MontoTotal(), "campos_nuevos": p.CamposNuevos,
		"cadena_verificada": verificada, "fecha": p.Valor("EFXP_FCH_EMIS"), "forma_pago": p.Valor("EFXP_FMA_PAGO"),
		"receptor": map[string]string{"rut": p.Valor("EFXP_RUT_RECEP") + "-" + p.Valor("EFXP_DV_RECEP"), "razon_social": p.Valor("EFXP_RZN_SOC_RECEP"),
			"direccion": strings.TrimSpace(p.Valor("EFXP_DIR_RECEP")), "comuna": p.Valor("EFXP_CMNA_RECEP")},
		"item":   map[string]string{"nombre": p.Valor("EFXP_NMB_01"), "precio": p.Valor("EFXP_PRC_01"), "descripcion": p.Valor("EFXP_DSC_ITEM_01")},
		"emisor": map[string]string{"razon_social": p.Valor("EFXP_RZN_SOC"), "giro": p.Valor("EFXP_GIRO_EMIS")},
	}
	if !emitir {
		out, _ := json.Marshal(salida)
		return string(out), nil
	}
	res, err := cli.Emitir(p, siiengine.OpcionesEmitir{Confirmar: true, ConPDF: true})
	if err != nil {
		return "", err
	}
	alm, err := almacen.Abrir(ctx.DatabasePath)
	if err != nil {
		return "", err
	}
	defer alm.Cerrar()
	fecha := p.Valor("EFXP_FCH_EMIS")
	id, err := siiengine.RegistrarEnBD(alm, res, rutEmpresa, rec, fecha)
	if err != nil {
		return "", err
	}
	if res.PDF != nil {
		ruta := fmt.Sprintf("%s/pdfs/mipyme_T%d_F%d_%s.pdf", ctx.StoragePath, res.Tipo, res.Folio, fecha)
		if err := os.WriteFile(ruta, res.PDF, 0o644); err == nil {
			alm.GuardarPDF(id, ruta)
			salida["pdf"] = ruta
		}
	}
	salida["folio"], salida["dhdr"], salida["dte_id"] = res.Folio, res.DHDR, id
	out, _ := json.Marshal(salida)
	return string(out), nil
}
