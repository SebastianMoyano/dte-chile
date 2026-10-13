//! El SII engine dentro de la app: `dtechile::siiengine` corre en este proceso para sincronizar
//! lo emitido en el sistema de facturación del SII, armar facturas exentas y notas de crédito.
//! Las claves vienen de la interfaz (memoria de la app) o, si la persona las recordó, del
//! keystore del motor vía `/api/v1/mipyme/contexto-siiengine/{rut}`. Nunca se escriben en
//! disco ni en el log. Transcripción de `app/siiengine.go`.

use crate::app::Compartido;
use dtechile::almacen::Almacen;
use dtechile::siiengine::{
    self,
    emision::{registrar_en_bd, Item, OpcionesEmitir, Receptor},
    importar::{importar, OpcionesImportar},
    Cliente,
};
use serde_json::{json, Value};
use std::time::Duration;

struct Contexto {
    rut_usuario: String,
    clave_tributaria: String,
    clave_certificado: String,
    database_path: String,
    storage_path: String,
}

fn contexto(c: &Compartido, rut_empresa: &str) -> Result<Contexto, String> {
    let r = c.api(
        "GET",
        &format!(
            "/api/v1/mipyme/contexto-siiengine/{}",
            dtechile::servidor::http::query_escape(rut_empresa)
        ),
        "",
    )?;
    if r.status != 200 {
        return Err(format!("contexto del SII engine: {}", r.cuerpo));
    }
    let v: Value = serde_json::from_str(&r.cuerpo).map_err(|e| e.to_string())?;
    let s = |k: &str| v[k].as_str().unwrap_or("").to_string();
    Ok(Contexto {
        rut_usuario: s("rut_usuario"),
        clave_tributaria: s("clave_tributaria"),
        clave_certificado: s("clave_certificado"),
        database_path: s("database_path"),
        storage_path: s("storage_path"),
    })
}

/// Lo que comparten los tres bindings: contexto, recordar claves, completar las que faltan.
fn preparar_claves(
    c: &Compartido,
    rut_empresa: &str,
    rut_usuario: &str,
    trib: &str,
    cert: &str,
    recordar: bool,
) -> Result<(Contexto, String, String, String), String> {
    let ctx = contexto(c, rut_empresa)?;
    if recordar && (!rut_usuario.is_empty() || !trib.is_empty() || !cert.is_empty()) {
        let cuerpo = json!({"rut_empresa": rut_empresa, "rut_usuario": rut_usuario, "clave_tributaria": trib, "clave_certificado": cert}).to_string();
        match c.api("PUT", "/api/v1/keystore/claves-sii", &cuerpo) {
            Ok(r) if r.status == 200 => {}
            Ok(r) => return Err(format!("no se pudieron recordar las claves ({})", r.cuerpo)),
            Err(e) => return Err(format!("no se pudieron recordar las claves ({e})")),
        }
    }
    let u = if rut_usuario.is_empty() {
        ctx.rut_usuario.clone()
    } else {
        rut_usuario.to_string()
    };
    let t = if trib.is_empty() {
        ctx.clave_tributaria.clone()
    } else {
        trib.to_string()
    };
    let ce = if cert.is_empty() {
        ctx.clave_certificado.clone()
    } else {
        cert.to_string()
    };
    Ok((ctx, u, t, ce))
}

fn sesion(
    ctx: &Contexto,
    rut_empresa: &str,
    u: &str,
    t: &str,
    ce: &str,
) -> Result<Cliente, String> {
    let mut cli = Cliente::nuevo(u, t, ce).map_err(|e| e.to_string())?;
    cli.raiz_storage = ctx.storage_path.clone();
    if let Err(e) = cli.iniciar_sesion() {
        let _ = cli.cerrar();
        return Err(e.to_string());
    }
    if let Err(e) = cli.seleccionar_empresa(rut_empresa) {
        let _ = cli.cerrar();
        return Err(e.to_string());
    }
    Ok(cli)
}

/// `SIIEngineSincronizar`: entra al SII como la persona, lista lo emitido por la empresa e
/// importa PDF (y XML si hay clave del certificado) a la misma base del motor. Solo lectura.
pub fn sincronizar(
    c: &Compartido,
    rut_empresa: &str,
    rut_usuario: &str,
    trib: &str,
    cert: &str,
    recordar: bool,
) -> Result<String, String> {
    let (ctx, u, t, ce) = preparar_claves(c, rut_empresa, rut_usuario, trib, cert, recordar)?;
    if u.is_empty() || t.is_empty() {
        return Err("faltan el RUT de la persona autorizada y/o su clave tributaria".into());
    }
    let mut cli = sesion(&ctx, rut_empresa, &u, &t, &ce)?;
    let r = (|| -> Result<Value, String> {
        let form = cli
            .leer_form(siiengine::TIPO_FACTURA_EXENTA)
            .map_err(|e| e.to_string())?;
        let docs = cli.listar_emitidos("", "", "").map_err(|e| e.to_string())?;
        let alm = Almacen::abrir(&ctx.database_path).map_err(|e| e.to_string())?;
        let op = OpcionesImportar {
            con_pdf: true,
            con_xml: !ce.is_empty(),
            carpeta: ctx.storage_path.clone(),
            pausa: Duration::from_millis(500),
        };
        let res = importar(&mut cli, &alm, rut_empresa, &docs, &op).map_err(|e| e.1.to_string())?;
        let g = |k: &str| form.campos.get(k).cloned().unwrap_or_default();
        let mut v = serde_json::to_value(&res).map_err(|e| e.to_string())?;
        if v.get("avisos").is_none() {
            v["avisos"] = json!([]);
        }
        v["ambiente"] = json!("produccion");
        v["motor"] = json!("rust");
        v["emisor_segun_portal"] = json!({"razon_social": g("EFXP_RZN_SOC"), "giro": g("EFXP_GIRO_EMIS"), "acteco": g("EFXP_ACTECO"), "comuna": g("EFXP_CMNA_ORIGEN")});
        v["nota"] = json!("Solo lectura en el SII: sesión comprobada, historial listado y PDF descargados. Nada se emitió.");
        Ok(v)
    })();
    let _ = cli.cerrar();
    Ok(r?.to_string())
}

/// `SIIEngineFactura`: arma (y, con emitir, emite) una factura exenta por el SII engine. Sin
/// emitir es un dry-run real contra el portal. Emitir exige que la cadena esté verificada desde
/// este motor: la interfaz NO acepta el riesgo de folio por la persona (L10).
#[allow(clippy::too_many_arguments)]
pub fn factura(
    c: &Compartido,
    rut_empresa: &str,
    rut_usuario: &str,
    trib: &str,
    cert: &str,
    recordar: bool,
    doc_json: &str,
    emitir: bool,
) -> Result<String, String> {
    let d: Value =
        serde_json::from_str(doc_json).map_err(|e| format!("documento inválido: {e}"))?;
    let rs = |v: &Value, k: &str| v[k].as_str().unwrap_or("").to_string();
    let rec = Receptor {
        rut: rs(&d["receptor"], "rut"),
        razon_social: rs(&d["receptor"], "razon_social"),
        giro: rs(&d["receptor"], "giro"),
        direccion: rs(&d["receptor"], "direccion"),
        ciudad: rs(&d["receptor"], "ciudad"),
        comuna: rs(&d["receptor"], "comuna"),
    };
    let mut forma_pago = rs(&d, "forma_pago");
    if forma_pago.is_empty() {
        forma_pago = "1".into();
    }
    let (ctx, u, t, ce) = preparar_claves(c, rut_empresa, rut_usuario, trib, cert, recordar)?;
    if u.is_empty() || t.is_empty() {
        return Err("faltan el RUT de la persona autorizada y/o su clave tributaria".into());
    }
    let verificada = siiengine::cadenas_verificadas().contains_key(&siiengine::TIPO_FACTURA_EXENTA);
    if emitir && !verificada {
        return Err("la emisión por el SII engine desde este motor todavía no está verificada con una corrida real: por ahora se emite con el CLI nucleo-siiengine (ver docs/PLAN-PORT.md, fase 6)".into());
    }
    if emitir && ce.is_empty() {
        return Err("emitir exige la clave del certificado (firma central del SII)".into());
    }
    let mut cli = sesion(&ctx, rut_empresa, &u, &t, &ce)?;
    let r = (|| -> Result<Value, String> {
        let items = vec![Item {
            nombre: rs(&d["item"], "nombre"),
            precio: d["item"]["precio"].as_i64().unwrap_or(0),
            cantidad: 1,
            descripcion: rs(&d["item"], "descripcion"),
        }];
        let p = cli
            .preparar(
                siiengine::TIPO_FACTURA_EXENTA,
                &rec,
                &items,
                &rs(&d, "fecha"),
                &forma_pago,
            )
            .map_err(|e| e.to_string())?;
        let mut salida = json!({
            "dry_run": !emitir, "tipo": p.tipo, "monto_total": p.monto_total(), "campos_nuevos": p.campos_nuevos,
            "cadena_verificada": verificada, "fecha": p.valor("EFXP_FCH_EMIS"), "forma_pago": p.valor("EFXP_FMA_PAGO"),
            "receptor": {"rut": format!("{}-{}", p.valor("EFXP_RUT_RECEP"), p.valor("EFXP_DV_RECEP")), "razon_social": p.valor("EFXP_RZN_SOC_RECEP"),
                "direccion": p.valor("EFXP_DIR_RECEP").trim(), "comuna": p.valor("EFXP_CMNA_RECEP")},
            "item": {"nombre": p.valor("EFXP_NMB_01"), "precio": p.valor("EFXP_PRC_01"), "descripcion": p.valor("EFXP_DSC_ITEM_01")},
            "emisor": {"razon_social": p.valor("EFXP_RZN_SOC"), "giro": p.valor("EFXP_GIRO_EMIS")},
        });
        if !emitir {
            return Ok(salida);
        }
        let res = cli
            .emitir(
                &p,
                OpcionesEmitir {
                    confirmar: true,
                    con_pdf: true,
                    aceptar_riesgo_folio: false,
                },
            )
            .map_err(|e| e.to_string())?;
        let alm = Almacen::abrir(&ctx.database_path).map_err(|e| e.to_string())?;
        let fecha = p.valor("EFXP_FCH_EMIS");
        let id =
            registrar_en_bd(&alm, &res, rut_empresa, &rec, &fecha).map_err(|e| e.to_string())?;
        if !res.pdf.is_empty() {
            let ruta = format!(
                "{}/pdfs/mipyme_T{}_F{}_{fecha}.pdf",
                ctx.storage_path, res.tipo, res.folio
            );
            if std::fs::write(&ruta, &res.pdf).is_ok() {
                let _ = alm.guardar_pdf(id, &ruta);
                salida["pdf"] = json!(ruta);
            }
        }
        salida["folio"] = json!(res.folio);
        salida["dhdr"] = json!(res.dhdr);
        salida["dte_id"] = json!(id);
        Ok(salida)
    })();
    let _ = cli.cerrar();
    Ok(r?.to_string())
}

/// `SIIEngineNotaCredito`: arma (y, con emitir, emite) la nota de crédito que ANULA un documento
/// emitido por el SII engine (fila `dtes` con el DHDR en track_id). Sin emitir es un dry-run
/// real sin folio. Emitir exige la cadena 61 verificada desde este motor.
#[allow(clippy::too_many_arguments)]
pub fn nota_credito(
    c: &Compartido,
    rut_empresa: &str,
    rut_usuario: &str,
    trib: &str,
    cert: &str,
    recordar: bool,
    dte_id: i64,
    emitir: bool,
) -> Result<String, String> {
    nota_anulacion(c, rut_empresa, rut_usuario, trib, cert, recordar, dte_id, emitir, siiengine::TIPO_NOTA_CREDITO)
}

/// `SIIEngineNotaDebito`: la nota de débito que deja sin efecto una nota de crédito emitida por
/// el SII engine (misma cadena que la NC, con TIPO_NOTA=56). Sin emitir es un dry-run real sin
/// folio; emitir exige la cadena 56 verificada, que todavía no tiene corrida real.
#[allow(clippy::too_many_arguments)]
pub fn nota_debito(
    c: &Compartido,
    rut_empresa: &str,
    rut_usuario: &str,
    trib: &str,
    cert: &str,
    recordar: bool,
    dte_id: i64,
    emitir: bool,
) -> Result<String, String> {
    nota_anulacion(c, rut_empresa, rut_usuario, trib, cert, recordar, dte_id, emitir, siiengine::TIPO_NOTA_DEBITO)
}

#[allow(clippy::too_many_arguments)]
fn nota_anulacion(
    c: &Compartido,
    rut_empresa: &str,
    rut_usuario: &str,
    trib: &str,
    cert: &str,
    recordar: bool,
    dte_id: i64,
    emitir: bool,
    tipo_nota: i32,
) -> Result<String, String> {
    let es_nd = tipo_nota == siiengine::TIPO_NOTA_DEBITO;
    let nombre = if es_nd { "nota de débito" } else { "nota de crédito" };
    let (ctx, u, t, ce) = preparar_claves(c, rut_empresa, rut_usuario, trib, cert, recordar)?;
    if u.is_empty() || t.is_empty() || ce.is_empty() {
        return Err(format!("la {nombre} exige el RUT de la persona autorizada, su clave tributaria y la del certificado"));
    }
    let verificada = siiengine::cadenas_verificadas().contains_key(&tipo_nota);
    if emitir && !verificada {
        return Err(format!("la {nombre} por el SII engine desde este motor todavía no está verificada con una corrida real: por ahora se emite con el CLI nucleo-siiengine {} (docs/PLAN-PORT.md, fase 6)", if es_nd { "nd-anular --acepto-riesgo-folio" } else { "nc-anular" }));
    }
    let alm = Almacen::abrir(&ctx.database_path).map_err(|e| e.to_string())?;
    let Some(doc) = alm.dte_por_id(dte_id).map_err(|e| e.to_string())? else {
        return Err(format!("el documento {dte_id} no es del SII engine (sin DHDR): solo se anulan por aquí los emitidos en el sistema del SII"));
    };
    if doc.track_id == 0 || !doc.estado.ends_with("_mipyme") {
        return Err(format!("el documento {dte_id} no es del SII engine (sin DHDR): solo se anulan por aquí los emitidos en el sistema del SII"));
    }
    if siiengine::formatear_rut(&doc.rut_emisor, false)
        != siiengine::formatear_rut(rut_empresa, false)
    {
        return Err(format!(
            "el documento {dte_id} es de {}, no de {rut_empresa}",
            doc.rut_emisor
        ));
    }
    if es_nd && doc.tipo_dte != siiengine::TIPO_NOTA_CREDITO {
        return Err(format!("el documento {dte_id} no es una nota de crédito: la nota de débito solo deja sin efecto una nota de crédito"));
    }
    let mut cli = sesion(&ctx, rut_empresa, &u, &t, &ce)?;
    let r = (|| -> Result<Value, String> {
        let dhdr = doc.track_id.to_string();
        let (p, rec, items) = if es_nd {
            cli.preparar_nd_anulacion_desde_portal(&dhdr, doc.folio as i64, &doc.fecha_emision, "", true)
        } else {
            cli.preparar_nc_anulacion_desde_portal(&dhdr, doc.tipo_dte, doc.folio as i64, &doc.fecha_emision, "", true)
        }
        .map_err(|e| e.to_string())?;
        let mut salida = json!({
            "dry_run": !emitir, "tipo": p.tipo, "monto_total": p.monto_total(), "campos_nuevos": p.campos_nuevos,
            "cadena_verificada": verificada, "fecha": p.valor("EFXP_FCH_EMIS"),
            "anula": {"tipo": doc.tipo_dte, "folio": doc.folio, "fecha": doc.fecha_emision, "dhdr": dhdr},
            "receptor": {"rut": rec.rut, "razon_social": rec.razon_social},
            "items": items,
        });
        if !emitir {
            return Ok(salida);
        }
        let res = cli
            .emitir(
                &p,
                OpcionesEmitir {
                    confirmar: true,
                    con_pdf: true,
                    aceptar_riesgo_folio: false,
                },
            )
            .map_err(|e| e.to_string())?;
        let fecha = p.valor("EFXP_FCH_EMIS");
        let id =
            registrar_en_bd(&alm, &res, rut_empresa, &rec, &fecha).map_err(|e| e.to_string())?;
        if !res.pdf.is_empty() {
            let ruta = format!(
                "{}/pdfs/mipyme_T{}_F{}_{fecha}.pdf",
                ctx.storage_path, res.tipo, res.folio
            );
            if std::fs::write(&ruta, &res.pdf).is_ok() {
                let _ = alm.guardar_pdf(id, &ruta);
                salida["pdf"] = json!(ruta);
            }
        }
        salida["folio"] = json!(res.folio);
        salida["dhdr"] = json!(res.dhdr);
        salida["dte_id"] = json!(id);
        Ok(salida)
    })();
    let _ = cli.cerrar();
    Ok(r?.to_string())
}
