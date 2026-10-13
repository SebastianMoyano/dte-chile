//! nucleo-siiengine: el SII engine del núcleo (portal MIPYME del SII). PRODUCCIÓN, sin sandbox.
//!
//! Solo lectura (no gastan folios):
//!
//!     nucleo-siiengine sesion   --usuario 12.345.678-5 --empresa 77.777.777-7
//!     nucleo-siiengine listar   --usuario … --empresa … [--desde 2026-01-01 --hasta 2026-12-31] [--tipo 34]
//!     nucleo-siiengine importar --usuario … --empresa … --db dte_chile.db [--sin-pdf] [--xml] [--storage storage]
//!
//! Emisión (dry-run por defecto; --emitir gasta el folio; --guardar lo registra en --db; mientras
//! el tipo no esté en las cadenas verificadas exige --acepto-riesgo-folio):
//!
//!     nucleo-siiengine factura    --usuario … --empresa … --receptor 76.111.111-6 --razon "CLIENTE SPA" --giro SALUD \
//!                                 --dir "CAMINO 1" --ciudad Chillan --comuna CHILLAN --glosa Arriendo --precio 1000 \
//!                                 [--detalle "…"] [--fecha 2026-10-08] [--forma-pago 1] [--emitir --acepto-riesgo-folio --guardar --db …]
//!     nucleo-siiengine nc-anular  … --dhdr <DHDR> --tipo-ref 34 --folio-ref 63 --fecha-ref 2026-10-08
//!     nucleo-siiengine nc-corregir … --dhdr <DHDR> --tipo-ref 34 --folio-ref 57 --fecha-ref 2026-09-06
//!
//! --trazas <dir> guarda las páginas crudas del dry-run (form, vista previa) como fixtures.
//! Claves (nunca por argumento): NUCLEO_CLAVE_TRIBUTARIA y NUCLEO_CLAVE_CERTIFICADO, o el
//! Llavero de macOS (servicios sii-clave-tributaria y sii-clave-certificado, cuenta = RUT).

use dtechile::almacen::Almacen;
use dtechile::cliutil::{clave_sii, fatal, Flags};
use dtechile::siiengine::{
    self,
    emision::{registrar_en_bd, Item, OpcionesEmitir, Payload, Receptor},
    importar::{importar, OpcionesImportar},
    Cliente,
};
use std::collections::BTreeMap;
use std::time::{Duration, Instant};

const CAMPOS_CLAVE: [&str; 20] = [
    "PTDC_CODIGO",
    "EHDR_CODIGO",
    "PTES_ESTADO",
    "EFXP_DOC_REF_RAIZ",
    "ES_BORR",
    "EFXP_FMA_PAGO",
    "EFXP_FCH_EMIS",
    "EFXP_NMB_01",
    "EFXP_QTY_01",
    "EFXP_PRC_01",
    "EFXP_SUBT_01",
    "EFXP_DSC_ITEM_01",
    "EFXP_SUBTOTAL",
    "EFXP_MNT_NETO",
    "EFXP_MNT_TOTAL",
    "EFXP_TPO_DOC_REF_001",
    "EFXP_FOLIO_REF_001",
    "EFXP_FCH_REF_001",
    "EFXP_CODIGO_REF_001",
    "EFXP_RAZON_REF_001",
];

fn imprimir<T: serde::Serialize>(v: &T) {
    println!("{}", serde_json::to_string_pretty(v).unwrap_or_default());
}

fn fecha_emision(p: &Payload) -> String {
    let f = p.valor("EFXP_FCH_EMIS");
    if f.is_empty() {
        dtechile::almacen::ahora_iso()[..10].to_string()
    } else {
        f
    }
}

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let Some(cmd) = args.first().cloned() else {
        eprintln!(
            "uso: nucleo-siiengine sesion|listar|importar|factura|nc-anular|nc-corregir|nd-anular [opciones]"
        );
        std::process::exit(2);
    };
    let f = Flags::parsear(
        &args[1..],
        &[
            "sin-pdf",
            "xml",
            "sin-verificar-monto",
            "emitir",
            "acepto-riesgo-folio",
            "guardar",
        ],
    );
    let (usuario, empresa) = (f.texto("usuario", ""), f.texto("empresa", ""));
    if usuario.is_empty() || empresa.is_empty() {
        fatal("error", "faltan --usuario y --empresa");
    }
    let es_emision = matches!(cmd.as_str(), "factura" | "nc-anular" | "nc-corregir" | "nd-anular");
    let emitir = f.logico("emitir");
    let necesita_cert = f.logico("xml") || emitir || (es_emision && cmd != "factura");
    let clave_trib = clave_sii("NUCLEO_CLAVE_TRIBUTARIA", "sii-clave-tributaria", &usuario);
    if clave_trib.is_empty() {
        fatal("error", format!("sin clave tributaria: exporta NUCLEO_CLAVE_TRIBUTARIA o guárdala en el Llavero:\n  security add-generic-password -s sii-clave-tributaria -a {}", siiengine::formatear_rut(&usuario, false)));
    }
    let mut clave_cert = String::new();
    if necesita_cert {
        clave_cert = clave_sii(
            "NUCLEO_CLAVE_CERTIFICADO",
            "sii-clave-certificado",
            &usuario,
        );
        if clave_cert.is_empty() {
            fatal("error", "este comando exige la clave del certificado: NUCLEO_CLAVE_CERTIFICADO o el Llavero (sii-clave-certificado)");
        }
    }
    let mut cli =
        Cliente::nuevo(&usuario, &clave_trib, &clave_cert).unwrap_or_else(|e| fatal("error", e));
    let storage = f.texto("storage", "storage");
    cli.raiz_storage = storage.clone();
    cli.log = Some(Box::new(|m: &str| eprintln!("{m}")));
    let trazas = f.texto("trazas", "");
    if !trazas.is_empty() {
        cli.trazas = Some(BTreeMap::new());
    }
    let t0 = Instant::now();
    let r = (|| -> Result<(), String> {
        cli.iniciar_sesion().map_err(|e| e.to_string())?;
        cli.seleccionar_empresa(&empresa)
            .map_err(|e| e.to_string())?;
        eprintln!(
            "SII engine → PRODUCCIÓN. Usuario {}, empresa {} (sesión en {:?})",
            cli.rut_usuario,
            cli.empresa,
            t0.elapsed()
        );
        let db = f.texto("db", "");
        match cmd.as_str() {
            "sesion" => {
                let form = cli
                    .leer_form(siiengine::TIPO_FACTURA_EXENTA)
                    .map_err(|e| e.to_string())?;
                let g = |k: &str| form.campos.get(k).cloned().unwrap_or_default();
                imprimir(&serde_json::json!({
                    "ambiente": "produccion",
                    "emisor_segun_portal": {"razon_social": g("EFXP_RZN_SOC"), "giro": g("EFXP_GIRO_EMIS"), "acteco": g("EFXP_ACTECO"), "comuna": g("EFXP_CMNA_ORIGEN"), "ciudad": g("EFXP_CIUDAD_ORIGEN")},
                    "form": {"campos_en_html": form.campos.len()},
                    "menu": cli.resumen_menu(),
                    "enlaces": cli.enlaces_menu().len(),
                    "nota": "Solo lectura en el SII: sesión comprobada y form leído. Nada se emitió.",
                }));
            }
            "listar" => imprimir(
                &cli.listar_emitidos(
                    &f.texto("tipo", ""),
                    &f.texto("desde", ""),
                    &f.texto("hasta", ""),
                )
                .map_err(|e| e.to_string())?,
            ),
            "importar" => {
                if db.is_empty() {
                    return Err("importar exige --db".into());
                }
                let al = Almacen::abrir(&db).map_err(|e| e.to_string())?;
                let docs = cli
                    .listar_emitidos("", &f.texto("desde", ""), &f.texto("hasta", ""))
                    .map_err(|e| e.to_string())?;
                let op = OpcionesImportar {
                    con_pdf: !f.logico("sin-pdf"),
                    con_xml: f.logico("xml"),
                    carpeta: storage.clone(),
                    pausa: Duration::from_millis(500),
                };
                let res =
                    importar(&mut cli, &al, &empresa, &docs, &op).map_err(|e| e.1.to_string())?;
                imprimir(&res);
            }
            _ => {
                let (receptor, razon, glosa, precio) = (
                    f.texto("receptor", ""),
                    f.texto("razon", ""),
                    f.texto("glosa", ""),
                    f.entero("precio", 0),
                );
                if receptor.is_empty() || razon.is_empty() || glosa.is_empty() || precio <= 0 {
                    return Err("faltan --receptor, --razon, --glosa o --precio".into());
                }
                let rec = Receptor {
                    rut: receptor,
                    razon_social: razon,
                    giro: f.texto("giro", ""),
                    direccion: f.texto("dir", ""),
                    ciudad: f.texto("ciudad", ""),
                    comuna: f.texto("comuna", ""),
                };
                let items = vec![Item {
                    nombre: glosa,
                    precio,
                    cantidad: 1,
                    descripcion: f.texto("detalle", ""),
                }];
                let fecha = f.texto("fecha", "");
                let (dhdr, tipo_ref, folio_ref, fecha_ref) = (
                    f.texto("dhdr", ""),
                    f.entero("tipo-ref", 34) as i32,
                    f.entero("folio-ref", 0),
                    f.texto("fecha-ref", ""),
                );
                let verificar = !f.logico("sin-verificar-monto");
                let p = match cmd.as_str() {
                    "factura" => cli.preparar(
                        siiengine::TIPO_FACTURA_EXENTA,
                        &rec,
                        &items,
                        &fecha,
                        &f.texto("forma-pago", "1"),
                    ),
                    "nc-anular" => {
                        if dhdr.is_empty() || folio_ref == 0 || fecha_ref.is_empty() {
                            return Err("nc-anular exige --dhdr, --folio-ref y --fecha-ref".into());
                        }
                        cli.preparar_nc_anulacion(
                            &dhdr, tipo_ref, folio_ref, &fecha_ref, &rec, &items, &fecha, verificar,
                        )
                    }
                    "nd-anular" => {
                        // deja sin efecto la NC --dhdr/--folio-ref (ND 56, código 1); cadena sin corrida real: exige --acepto-riesgo-folio
                        if dhdr.is_empty() || folio_ref == 0 || fecha_ref.is_empty() {
                            return Err("nd-anular exige --dhdr, --folio-ref y --fecha-ref (los de la nota de crédito)".into());
                        }
                        cli.preparar_nd_anulacion(
                            &dhdr, folio_ref, &fecha_ref, &rec, &items, &fecha, verificar,
                        )
                    }
                    _ => {
                        if dhdr.is_empty() || folio_ref == 0 || fecha_ref.is_empty() {
                            return Err(
                                "nc-corregir exige --dhdr, --folio-ref y --fecha-ref".into()
                            );
                        }
                        cli.preparar_nc_correccion_montos(
                            &dhdr, tipo_ref, folio_ref, &fecha_ref, &rec, &items, &fecha, verificar,
                        )
                    }
                }
                .map_err(|e| e.to_string())?;
                if let Some(t) = cli.trazas.as_mut() {
                    if let Ok(b) = siiengine::codificar_latin1(&p.pares) {
                        t.insert("body_genxml.txt".into(), siiengine::latin1(&b));
                    }
                }
                eprintln!(
                    "\nTipo {} | receptor {} {} | total ${} | {} campos",
                    p.tipo,
                    siiengine::formatear_rut(&rec.rut, false),
                    rec.razon_social,
                    p.monto_total(),
                    p.pares.len()
                );
                if !p.campos_nuevos.is_empty() {
                    eprintln!(
                        "⚠️ el form del SII trae campos que el schema no conoce: {:?}",
                        p.campos_nuevos
                    );
                }
                eprintln!("Campos clave del documento:");
                for k in CAMPOS_CLAVE {
                    eprintln!("  {k:<24} = {:?}", p.valor(k));
                }
                if !emitir {
                    eprintln!("\n[DRY-RUN] no se emitió nada. Agrega --emitir para gastar el folio y emitir.");
                    return Ok(());
                }
                let res = cli
                    .emitir(
                        &p,
                        OpcionesEmitir {
                            confirmar: true,
                            con_pdf: true,
                            aceptar_riesgo_folio: f.logico("acepto-riesgo-folio"),
                        },
                    )
                    .map_err(|e| e.to_string())?;
                let mut salida = serde_json::json!({"tipo": res.tipo, "folio": res.folio, "dhdr": res.dhdr, "monto_total": res.monto_total});
                if !res.pdf.is_empty() {
                    let ruta = format!(
                        "{storage}/pdfs/mipyme_T{}_F{}_{}.pdf",
                        res.tipo,
                        res.folio,
                        fecha_emision(&p)
                    );
                    let _ = std::fs::create_dir_all(format!("{storage}/pdfs"));
                    if std::fs::write(&ruta, &res.pdf).is_ok() {
                        salida["pdf"] = serde_json::json!(ruta);
                    }
                }
                if f.logico("guardar") {
                    if db.is_empty() {
                        return Err("--guardar exige --db".into());
                    }
                    let al = Almacen::abrir(&db).map_err(|e| e.to_string())?;
                    let id = registrar_en_bd(&al, &res, &empresa, &rec, &fecha_emision(&p))
                        .map_err(|e| e.to_string())?;
                    if let Some(ruta) = salida.get("pdf").and_then(|v| v.as_str()) {
                        let _ = al.guardar_pdf(id, ruta);
                    }
                    salida["db_id"] = serde_json::json!(id);
                }
                eprintln!(
                    "\n✅ EMITIDO: tipo {} folio {} DHDR={}",
                    res.tipo, res.folio, res.dhdr
                );
                imprimir(&salida);
            }
        }
        Ok(())
    })();
    if let Err(e) = cli.cerrar() {
        eprintln!("aviso: {e}");
    }
    if !trazas.is_empty() {
        if let Some(t) = &cli.trazas {
            let _ = std::fs::create_dir_all(&trazas);
            for (nombre, contenido) in t {
                if let Ok(b) = siiengine::html::a_bytes_latin1(contenido) {
                    let _ = std::fs::write(format!("{trazas}/{nombre}"), b);
                }
            }
            eprintln!("trazas: {} página(s) en {trazas}", t.len());
        }
    }
    if let Err(e) = r {
        fatal("error", e);
    }
}
