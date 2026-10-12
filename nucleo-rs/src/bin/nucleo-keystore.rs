//! nucleo-keystore: certificados del SII por cuenta en el almacén cifrado (keystore_cli.py)
//! y diagnóstico de un .p12 (diagnostico_cert.py).
//!
//!     nucleo-keystore add  firma.pfx --cuenta 1 --nombre rep-legal      (clave: NUCLEO_CLAVE_CERTIFICADO o prompt oculto)
//!     nucleo-keystore list --cuenta 1
//!     nucleo-keystore test 3 --cuenta 1          (carga el certificado y muestra RUT y vencimiento)
//!     nucleo-keystore portal 3 --cuenta 1 [--rut 77777777-7]   (autentica en el SII; situación de folios)
//!     nucleo-keystore remove 3 --cuenta 1
//!     nucleo-keystore info --p12 firma.pfx       (subject, RUT, issuer, vigencia; sin tocar la base)

use dtechile::cliutil::{clave_certificado, fatal, Flags};
use dtechile::firma;
use dtechile::portal::{self, Cliente};
use dtechile::servidor::{config, Servidor};

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let Some(cmd) = args.first().cloned() else {
        fatal(
            "error",
            "uso: nucleo-keystore add|list|test|portal|remove|info …",
        );
    };
    let f = Flags::parsear(&args[1..], &[]);
    let posicional = f.posicionales.first().cloned().unwrap_or_default();
    let cuenta = f.entero("cuenta", 1);
    if cmd == "info" {
        let mut ruta = f.texto("p12", "");
        if ruta.is_empty() {
            ruta = posicional.clone();
        }
        if ruta.is_empty() {
            ruta = std::env::var("DTE_CERT_PATH")
                .ok()
                .filter(|v| !v.is_empty())
                .unwrap_or_else(|| "firma.pfx".into());
        }
        let b = std::fs::read(&ruta).unwrap_or_else(|e| fatal("error", e));
        let cert =
            firma::cargar_p12(&b, &clave_certificado()).unwrap_or_else(|e| fatal("error", e));
        println!("=== Subject ===\n{}", cert.subject());
        println!(
            "\n=== RUT extraído ===\n{}",
            cert.rut_emisor().unwrap_or_default()
        );
        println!("\n=== Issuer ===\n{}", cert.issuer());
        println!(
            "\n=== Vigencia ===\n{} → {}",
            &cert.not_before()[..10],
            &cert.not_after()[..10]
        );
        return;
    }
    let mut cfg = config::cargar(&f.texto("env", ".env"));
    let db = f.texto("db", "");
    if !db.is_empty() {
        cfg.database_path = db;
    }
    cfg.rvd_scheduler_activo = false;
    let s = Servidor::nuevo(cfg).unwrap_or_else(|e| fatal("error", e));
    match cmd.as_str() {
        "add" => {
            if posicional.is_empty() {
                fatal("error", "falta la ruta del .p12");
            }
            let b = std::fs::read(&posicional).unwrap_or_else(|e| fatal("error", e));
            let info = s
                .guardar_certificado(
                    cuenta,
                    &b,
                    &clave_certificado(),
                    &f.texto("nombre", ""),
                    &f.texto("alias", ""),
                )
                .unwrap_or_else(|e| fatal("error", format!("no se pudo guardar: {e}")));
            println!(
                "✓ Certificado guardado (id={}): RUT {} · vence {:.10}",
                info.id, info.rut, info.vencimiento
            );
        }
        "list" => {
            let certs = s
                .listar_certificados(cuenta)
                .unwrap_or_else(|e| fatal("error", e));
            if certs.is_empty() {
                println!("(cuenta {cuenta} sin certificados)");
                return;
            }
            println!("Certificados de la cuenta {cuenta}:");
            for c in certs {
                println!(
                    "  [{}] RUT {:<12} {:<20} vence {:.10}",
                    c.id, c.rut, c.nombre, c.vencimiento
                );
            }
        }
        "test" | "portal" | "remove" => {
            let id: i64 = posicional
                .parse()
                .unwrap_or_else(|_| fatal("error", "falta el id del certificado"));
            match cmd.as_str() {
                "test" => {
                    let cert = s
                        .certificado_del_keystore(id, cuenta)
                        .unwrap_or_else(|e| fatal("error", e));
                    println!(
                        "✓ Certificado {id} cargado en memoria: RUT {}\n  vence: {}",
                        cert.rut_emisor().unwrap_or_default(),
                        cert.not_after().replace('T', " ")
                    );
                }
                "portal" => {
                    let (cert_pem, key_pem) = s
                        .pem_del_keystore(id, cuenta)
                        .unwrap_or_else(|e| fatal("error", e));
                    let mut p = Cliente::nuevo(
                        cert_pem.as_bytes(),
                        key_pem.as_bytes(),
                        portal::BASE_CERTIFICACION,
                    )
                    .unwrap_or_else(|e| fatal("error", e));
                    p.autenticar("").unwrap_or_else(|e| fatal("error", e));
                    println!("✓ Autenticado en el SII (sesión RUT {})", p.rut_sesion);
                    let rut = f.texto("rut", "");
                    if !rut.is_empty() {
                        let sit = p
                            .situacion_folios(&rut, &[33, 34, 52, 56, 61])
                            .unwrap_or_else(|e| fatal("error", e));
                        println!("  Situación de timbraje de {rut}:");
                        for t in [33, 34, 52, 56, 61] {
                            println!(
                                "    T{t}: {}",
                                if sit.get(&t).map(|x| x.bloqueado).unwrap_or(false) {
                                    "BLOQUEADO"
                                } else {
                                    "ok"
                                }
                            );
                        }
                    }
                }
                _ => {
                    let ok = s
                        .eliminar_certificado(cuenta, id)
                        .unwrap_or_else(|e| fatal("error", e));
                    println!(
                        "{}",
                        if ok {
                            "✓ Eliminado"
                        } else {
                            "✗ No encontrado"
                        }
                    );
                }
            }
        }
        _ => fatal("error", format!("subcomando desconocido: {cmd}")),
    }
}
