//! nucleo-portal: el portal de timbraje del SII desde la terminal (`portal`).
//!
//!     nucleo-portal empresa   --rut 77777777-7 [--ambiente certificacion]           (pública, sin certificado)
//!     nucleo-portal timbrajes --rut … --tipo 33 --cert firma.pfx
//!     nucleo-portal situacion --rut … [--tipos 33,61] --cert …
//!     nucleo-portal software  --rut … [--ambiente produccion] --cert …
//!     nucleo-portal empresas  --cert …                                              (asociadas al certificado)
//!     nucleo-portal anulables --rut … --tipo 33 --cert …
//!     nucleo-portal anular    --rut … --tipo 33 --desde 5 --hasta 9 --cert …        (irreversible)
//!     nucleo-portal solicitar --rut … --tipo 61 [--cantidad 1] --cert … [--db dte_database.db]  (TIMBRA folios)
//!
//! Certificado: --cert ruta.p12 (clave por NUCLEO_CLAVE_CERTIFICADO, Llavero o prompt oculto) o
//! --cert-id N (el keystore cifrado del motor, con --env/--db). La clave NUNCA va por flag.

use dtechile::almacen::Almacen;
use dtechile::cliutil::{cargar_certificado, fatal, imprimir_json, Flags};
use dtechile::portal::{self, Cliente};
use dtechile::ted;

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let Some(cmd) = args.first().cloned() else {
        fatal("error", "falta el subcomando: empresa|timbrajes|situacion|software|empresas|anulables|anular|solicitar");
    };
    let f = Flags::parsear(&args[1..], &["json"]);
    let rut = f.texto("rut", "");
    let tipo = f.entero("tipo", 33) as i32;
    let ambiente = f.texto("ambiente", "certificacion");
    let base = portal::base_de(&ambiente);
    if cmd == "empresa" {
        let mut p = Cliente::nuevo(&[], &[], base).unwrap_or_else(|e| fatal("error", e));
        match p
            .consultar_empresa_autorizada(&rut, "")
            .unwrap_or_else(|e| fatal("error", e))
        {
            None => {
                println!("El RUT {rut} no aparece autorizado a emitir DTE en {ambiente}.");
                std::process::exit(1);
            }
            Some(e) => imprimir_json(&e),
        }
        return;
    }
    let db = f.texto("db", "");
    let cert = cargar_certificado(
        &f.texto("cert", &std::env::var("DTE_CERT_PATH").unwrap_or_default()),
        f.entero("cert-id", 0),
        f.entero("cuenta", 1),
        &f.texto("env", ".env"),
        &db,
    )
    .unwrap_or_else(|e| fatal("error", format!("certificado: {e}")));
    let key_pem = cert.key_pem().unwrap_or_else(|e| fatal("error", e));
    let mut p = Cliente::nuevo(cert.cert_pem().as_bytes(), key_pem.as_bytes(), base)
        .unwrap_or_else(|e| fatal("error", e));
    p.autenticar("")
        .unwrap_or_else(|e| fatal("error", format!("autenticación en el SII: {e}")));
    eprintln!("sesión por certificado abierta (RUT_NS {})", p.rut_sesion);
    match cmd.as_str() {
        "timbrajes" => imprimir_json(
            &p.consultar_timbrajes(&rut, tipo)
                .unwrap_or_else(|e| fatal("error", e)),
        ),
        "situacion" => {
            let ts: Vec<i32> = f
                .texto("tipos", "")
                .split(',')
                .filter_map(|t| t.trim().parse().ok())
                .collect();
            imprimir_json(
                &p.situacion_folios(&rut, &ts)
                    .unwrap_or_else(|e| fatal("error", e)),
            )
        }
        "software" => imprimir_json(
            &p.datos_software_de(&rut, base)
                .unwrap_or_else(|e| fatal("error", e)),
        ),
        "empresas" => imprimir_json(&p.empresas_asociadas().unwrap_or_else(|e| fatal("error", e))),
        "anulables" => imprimir_json(
            &p.listar_anulables(&rut, tipo)
                .unwrap_or_else(|e| fatal("error", e)),
        ),
        "anular" => {
            let (desde, hasta) = (f.entero("desde", 0), f.entero("hasta", 0));
            if desde == 0 || hasta == 0 {
                fatal("error", "faltan --desde y --hasta");
            }
            let r = p
                .anular_folios(&rut, tipo, desde, hasta, "")
                .unwrap_or_else(|e| fatal("error", e));
            imprimir_json(&r);
            if !r.ok {
                std::process::exit(1);
            }
        }
        "solicitar" => {
            let (caf, info) = p
                .solicitar_folios(&rut, tipo, f.entero("cantidad", 1), true, false)
                .unwrap_or_else(|e| fatal("error", e));
            imprimir_json(&info);
            let Some(caf) = caf else {
                std::process::exit(1)
            };
            let dir = f.texto("dir", "storage/cafs");
            let _ = std::fs::create_dir_all(&dir);
            let hoy = dtechile::almacen::ahora_iso()[..10].replace('-', "");
            let nombre = format!(
                "{dir}/CAF_{}_T{tipo}_{}-{}_{hoy}.xml",
                rut.replace('-', ""),
                info.folio_desde,
                info.folio_hasta
            );
            std::fs::write(&nombre, &caf).unwrap_or_else(|e| fatal("error", e));
            println!("CAF guardado: {nombre} ({} bytes)", caf.len());
            if !db.is_empty() {
                let txt = String::from_utf8_lossy(&caf).into_owned();
                let c = ted::parsear_caf(&txt).unwrap_or_else(|e| fatal("error", e));
                let alm = Almacen::abrir_y_migrar(&db).unwrap_or_else(|e| fatal("error", e));
                let id = alm
                    .registrar_caf(
                        c.tipo_dte,
                        &c.rut_emisor,
                        c.folio_desde,
                        c.folio_hasta,
                        &c.fecha_autorizacion,
                        &txt,
                    )
                    .unwrap_or_else(|e| fatal("error", e));
                println!("registrado en la base: id {id}");
            }
        }
        _ => fatal("error", format!("subcomando desconocido: {cmd}")),
    }
}
