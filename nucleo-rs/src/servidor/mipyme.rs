//! Rutas de api/routes/mipyme.py con `crate::siiengine`: entrar al portal MIPYME (PRODUCCIÓN,
//! sin sandbox), leer el formulario y el menú, listar el historial e importarlo a `dtes`.
//! Solo lectura: nada de esto emite ni gasta folio.

use super::errores::{ok, ErrorHTTP, Res};
use super::http::Peticion;
use super::keystore::{claves_guardadas, guardar_claves};
use super::{Json, Prot, Servidor};
use crate::siiengine::{
    self,
    emision::{armar_payload, Item, Receptor},
    importar::{importar, OpcionesImportar},
    Cliente, Enlace,
};
use regex::Regex;
use serde_json::{json, Map, Value};
use std::time::Duration;

pub fn rutas(s: &mut Servidor) {
    s.ruta(
        "POST /api/v1/mipyme/diagnostico",
        Prot::Protegida,
        diagnostico,
    );
    s.ruta(
        "POST /api/v1/mipyme/importar",
        Prot::Protegida,
        importar_ruta,
    );
    s.ruta(
        "POST /api/v1/mipyme/sincronizar",
        Prot::Protegida,
        sincronizar,
    );
}

#[derive(Debug, Clone, Default)]
struct Entrada {
    rut_empresa: String,
    rut_usuario: String,
    clave_tributaria: String,
    clave_certificado: String,
    con_xml: bool,
    desde: String,
    hasta: String,
    con_pdf: bool,
}

/// `responderErrorPortal`: los errores de siiengine a los códigos de core/errors.py.
pub fn error_portal(e: siiengine::Error) -> ErrorHTTP {
    match e {
        siiengine::Error::Autenticacion(_) => ErrorHTTP::autenticacion(e.to_string()),
        siiengine::Error::Rechazo(_) => ErrorHTTP::sii_rechazo(e.to_string()),
        siiengine::Error::Validacion(_) => ErrorHTTP::validacion(e.to_string()),
        siiengine::Error::Sii(_) => ErrorHTTP::sii_comunicacion(e.to_string()),
    }
}

/// `leerMipyme` + `_resolver_claves`: lo que viene en el cuerpo manda; lo que falta se toma del
/// keystore (cifrado); con `recordar` se guarda lo que vino. Nada se registra en logs.
fn leer(s: &Servidor, p: &Peticion) -> Result<Entrada, ErrorHTTP> {
    let j = Json::leer(p)?;
    let Some(rut_empresa) = j.texto("rut_empresa")? else {
        return Err(ErrorHTTP::faltan(&["rut_empresa"]));
    };
    let mut d = Entrada {
        rut_empresa,
        rut_usuario: j.texto_o("rut_usuario", "")?,
        clave_tributaria: j.texto_o("clave_tributaria", "")?,
        clave_certificado: j.texto_o("clave_certificado", "")?,
        con_xml: j.logico_o("con_xml", false)?,
        desde: j.texto_o("desde", "")?,
        hasta: j.texto_o("hasta", "")?,
        con_pdf: j.logico_o("con_pdf", true)?,
    };
    let recordar = j.logico_o("recordar", false)?;
    let cuenta = s.cuenta_id(p);
    if recordar
        && (!d.clave_tributaria.is_empty()
            || !d.clave_certificado.is_empty()
            || !d.rut_usuario.is_empty())
    {
        guardar_claves(
            s,
            cuenta,
            &d.rut_empresa,
            &d.rut_usuario,
            &d.clave_tributaria,
            &d.clave_certificado,
        )?;
    }
    let (usuario, trib, cert) = claves_guardadas(s, cuenta, &d.rut_empresa);
    if d.rut_usuario.is_empty() {
        d.rut_usuario = usuario;
    }
    if d.clave_tributaria.is_empty() {
        d.clave_tributaria = trib;
    }
    if d.clave_certificado.is_empty() {
        d.clave_certificado = cert;
    }
    if d.rut_usuario.is_empty() || d.clave_tributaria.is_empty() {
        let mut faltan = Vec::new();
        if d.rut_usuario.is_empty() {
            faltan.push("rut_usuario");
        }
        if d.clave_tributaria.is_empty() {
            faltan.push("clave_tributaria");
        }
        return Err(ErrorHTTP::validacion("Faltan el RUT de la persona autorizada y/o su clave tributaria (no vienen en la petición ni están recordadas para esta empresa)")
            .detalle(json!({"rut_empresa": d.rut_empresa, "faltan": faltan})));
    }
    Ok(d)
}

fn sesion(s: &Servidor, d: &Entrada) -> Result<Cliente, ErrorHTTP> {
    let mut cli = Cliente::nuevo(&d.rut_usuario, &d.clave_tributaria, &d.clave_certificado)
        .map_err(|e| ErrorHTTP::validacion(e.to_string()))?;
    cli.raiz_storage = s.cfg.storage_path.clone();
    if let Err(e) = cli.iniciar_sesion() {
        let _ = cli.cerrar();
        return Err(error_portal(e));
    }
    if let Err(e) = cli.seleccionar_empresa(&d.rut_empresa) {
        let _ = cli.cerrar();
        return Err(error_portal(e));
    }
    Ok(cli)
}

fn receptor_prueba() -> Receptor {
    Receptor {
        rut: "11111111-1".into(),
        razon_social: "PRUEBA".into(),
        giro: "PRUEBA".into(),
        direccion: "-".into(),
        ciudad: "-".into(),
        comuna: "-".into(),
    }
}

/// enlaces, menú, form de la factura exenta y el drift del schema.
/// (enlaces, menú, campos del form, drift del schema).
type Lectura = (
    Vec<Enlace>,
    Value,
    std::collections::BTreeMap<String, String>,
    Value,
);

fn lectura(cli: &mut Cliente) -> Result<Lectura, siiengine::Error> {
    let enlaces = cli.enlaces_menu();
    let menu = serde_json::to_value(cli.resumen_menu()).unwrap_or(Value::Null);
    let f = cli.leer_form(siiengine::TIPO_FACTURA_EXENTA)?;
    let campos = f.campos.clone();
    let (mut pares, mut nuevos): (usize, Vec<String>) = (0, Vec::new());
    if let Ok(payload) = armar_payload(
        &f,
        siiengine::TIPO_FACTURA_EXENTA,
        &receptor_prueba(),
        &[Item {
            nombre: "x".into(),
            precio: 1,
            cantidad: 1,
            ..Default::default()
        }],
        "",
        "",
        &[],
        &[],
    ) {
        pares = payload.pares.len();
        nuevos = payload.campos_nuevos.clone();
    }
    let form = json!({"campos_en_html": campos.len(), "campos_del_schema": pares, "campos_nuevos": nuevos});
    Ok((enlaces, menu, campos, form))
}

fn emisor_segun_portal(
    campos: &std::collections::BTreeMap<String, String>,
    con_direccion: bool,
) -> Value {
    let g = |k: &str| campos.get(k).cloned().unwrap_or_default();
    let mut m = json!({"razon_social": g("EFXP_RZN_SOC"), "giro": g("EFXP_GIRO_EMIS"), "acteco": g("EFXP_ACTECO"), "comuna": g("EFXP_CMNA_ORIGEN")});
    if con_direccion {
        m["direccion"] = json!(g("EFXP_DIR_ORIGEN"));
    }
    m
}

fn filtrar(enlaces: &[Enlace], re: &Regex) -> Vec<Enlace> {
    enlaces
        .iter()
        .filter(|e| re.is_match(&format!("{} {}", e.texto, e.href)))
        .cloned()
        .collect()
}

fn diagnostico(s: &Servidor, p: &mut Peticion) -> Res {
    let mut d = leer(s, p)?;
    d.clave_certificado.clear();
    let mut cli = sesion(s, &d)?;
    let r = lectura(&mut cli);
    let _ = cli.cerrar();
    let (enlaces, menu, campos, form) = r.map_err(error_portal)?;
    let re_boleta = Regex::new("(?i)bolet").expect("re");
    let re_hist = Regex::new("(?i)histor|emitid|consult").expect("re");
    let g = |k: &str| campos.get(k).cloned().unwrap_or_default();
    ok(json!({
        "ambiente": "produccion", "empresa": d.rut_empresa,
        "emisor_segun_portal": emisor_segun_portal(&campos, true),
        "ultimo_receptor": {"rut": format!("{}-{}", g("EFXP_RUT_RECEP"), g("EFXP_DV_RECEP")), "razon_social": g("EFXP_RZN_SOC_RECEP")},
        "form": form,
        "boleta_en_gratuito": !filtrar(&enlaces, &re_boleta).is_empty(),
        "enlaces_boleta": filtrar(&enlaces, &re_boleta),
        "enlaces_historial": filtrar(&enlaces, &re_hist),
        "enlaces": enlaces, "menu": menu,
        "nota": "Solo lectura: no se emitió nada ni se gastó folio. La sesión se cerró.",
    }))
}

fn importar_portal(
    s: &Servidor,
    cli: &mut Cliente,
    d: &Entrada,
) -> Result<Map<String, Value>, ErrorHTTP> {
    let docs = cli
        .listar_emitidos("", &d.desde, &d.hasta)
        .map_err(error_portal)?;
    let op = OpcionesImportar {
        con_pdf: d.con_pdf,
        con_xml: d.con_xml && !d.clave_certificado.is_empty(),
        carpeta: s.cfg.storage_path.clone(),
        pausa: Duration::from_millis(500),
    };
    let res = importar(cli, &s.alm, &d.rut_empresa, &docs, &op)
        .map_err(|e| ErrorHTTP::sii_comunicacion(e.1.to_string()))?;
    match serde_json::to_value(res) {
        Ok(Value::Object(m)) => Ok(m),
        _ => Err(ErrorHTTP::interno()),
    }
}

fn importar_ruta(s: &Servidor, p: &mut Peticion) -> Res {
    let d = leer(s, p)?;
    let mut cli = sesion(s, &d)?;
    let r = importar_portal(s, &mut cli, &d);
    let _ = cli.cerrar();
    let mut resumen = r?;
    resumen.insert("ambiente".into(), json!("produccion"));
    resumen.insert(
        "nota".into(),
        json!("Solo lectura en el SII: se listó el historial y se bajaron PDF. Nada se emitió."),
    );
    ok(Value::Object(resumen))
}

fn sincronizar(s: &Servidor, p: &mut Peticion) -> Res {
    let d = leer(s, p)?;
    let mut cli = sesion(s, &d)?;
    let l = lectura(&mut cli);
    let (enlaces, menu, campos, form) = match l {
        Ok(v) => v,
        Err(e) => {
            let _ = cli.cerrar();
            return Err(error_portal(e));
        }
    };
    let r = importar_portal(s, &mut cli, &d);
    let _ = cli.cerrar();
    let mut resumen = r?;
    resumen.insert("ambiente".into(), json!("produccion"));
    resumen.insert(
        "emisor_segun_portal".into(),
        emisor_segun_portal(&campos, false),
    );
    resumen.insert("form".into(), form);
    resumen.insert("enlaces".into(), json!(enlaces));
    resumen.insert("menu".into(), menu);
    resumen.insert("nota".into(), json!("Solo lectura en el SII: sesión comprobada, historial listado y PDF descargados. Nada se emitió."));
    ok(Value::Object(resumen))
}
