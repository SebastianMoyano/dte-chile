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

// evitar imports sin uso si el cascarón se compila sin estas rutas
var _ = os.Getenv
var _ = strings.TrimSpace
