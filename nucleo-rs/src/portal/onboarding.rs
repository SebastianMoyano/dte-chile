//! `core/onboarding.py`: diagnóstico automático de una empresa (solo lectura) y plan de pasos.

use super::{
    DatosSoftware, DocumentoAutorizado, Empresa, EmpresaAutorizadaDTE, SituacionTipo,
    BASE_CERTIFICACION, BASE_PRODUCCION,
};
use std::collections::BTreeMap;

pub const MODO_AUTO: &str = "auto";
pub const MODO_CONSENTIMIENTO: &str = "consentimiento";
pub const MODO_HUMANO: &str = "humano";

#[derive(Debug, Clone, Default, PartialEq, serde::Serialize)]
pub struct Chequeo {
    pub id: String,
    pub titulo: String,
    /// ok | falta | atencion | desconocido
    pub estado: String,
    pub detalle: String,
}

#[derive(Debug, Clone, Default, PartialEq, serde::Serialize)]
pub struct Accion {
    pub titulo: String,
    pub detalle: String,
    pub modo: String,
    pub hecho: bool,
    pub urgente: bool,
}

#[derive(Debug, Clone, Default, PartialEq, serde::Serialize)]
pub struct Diagnostico {
    pub rut: String,
    pub razon_social: String,
    /// emitiendo | externo | certificado | certificando | sin_propio
    pub estado: String,
    pub etiqueta: String,
    pub resumen: String,
    pub listo_para_emitir: bool,
    pub chequeos: Vec<Chequeo>,
    pub acciones: Vec<Accion>,
    pub notas: Vec<String>,
}

/// Lo que el diagnóstico necesita del portal (el Cliente real o un doble en tests).
pub trait Lector {
    fn consultar_empresa_autorizada(
        &mut self,
        rut: &str,
        base: &str,
    ) -> Result<Option<EmpresaAutorizadaDTE>, String>;
    fn datos_software_de(&mut self, rut: &str, base: &str) -> Result<DatosSoftware, String>;
    fn situacion_folios(
        &mut self,
        rut: &str,
        tipos: &[i32],
    ) -> Result<BTreeMap<i32, SituacionTipo>, String>;
    fn empresas_asociadas(&mut self) -> Result<Vec<Empresa>, String>;
}

/// `es_nuestro_software`: compara con el nombre registrado por el motor y con NOMBRE_SOFTWARE
/// (lista separada por coma). `None` = no hay con qué comparar.
pub fn es_nuestro_software(
    nombre: &str,
    registrado: &str,
    nombre_software_config: &str,
) -> Option<bool> {
    let mut nuestros: Vec<String> = Vec::new();
    if !registrado.trim().is_empty() {
        nuestros.push(registrado.trim().to_lowercase());
    }
    for n in nombre_software_config.split(',') {
        if !n.trim().is_empty() {
            nuestros.push(n.trim().to_lowercase());
        }
    }
    if nuestros.is_empty() || nombre.is_empty() {
        return None;
    }
    let n = nombre.to_lowercase();
    Some(
        nuestros
            .iter()
            .any(|x| n.contains(x.as_str()) || x.contains(n.as_str())),
    )
}

/// `clasificar_software`: (estado, etiqueta) de cómo emite la empresa hoy.
pub fn clasificar_software(
    prod: &DatosSoftware,
    cert: &DatosSoftware,
    registrado: &str,
    nombre_software_config: &str,
) -> (String, String) {
    let sw = prod.software.trim();
    if prod.propio {
        if es_nuestro_software(sw, registrado, nombre_software_config) == Some(false) {
            return (
                "externo".into(),
                format!("Emite con «{sw}» (otro proveedor)"),
            );
        }
        if !sw.is_empty() {
            return (
                "emitiendo".into(),
                format!("Emite en producción con «{sw}»"),
            );
        }
        return (
            "emitiendo".into(),
            "Emitiendo en producción con software propio".into(),
        );
    }
    if cert.propio && cert.certificado {
        return (
            "certificado".into(),
            "Software propio certificado — falta activarlo en producción".into(),
        );
    }
    if cert.propio {
        return (
            "certificando".into(),
            "En certificación del software propio".into(),
        );
    }
    ("sin_propio".into(), "Emite por el gratuito del SII".into())
}

fn ternario<'a>(c: bool, a: &'a str, b: &'a str) -> &'a str {
    if c {
        a
    } else {
        b
    }
}

/// `diagnosticar()`: la batería de lecturas del SII + el plan. `registrado` es
/// `negocios.software_registrado(rut)` (vacío si no hay) y `nombre_software` es NOMBRE_SOFTWARE.
pub fn diagnosticar(
    p: &mut dyn Lector,
    rut: &str,
    nombre_sistema: &str,
    registrado: &str,
    nombre_software: &str,
) -> Result<Diagnostico, String> {
    let nombre_sistema = if nombre_sistema.is_empty() {
        "tu software propio"
    } else {
        nombre_sistema
    };
    let emp = p.consultar_empresa_autorizada(rut, BASE_PRODUCCION)?;
    let sw_prod = p.datos_software_de(rut, BASE_PRODUCCION)?;
    let sw_cert = p.datos_software_de(rut, BASE_CERTIFICACION)?;
    let sit_cert = p.situacion_folios(rut, &[33, 61])?;
    let mut razon = rut.to_string();
    let mut autorizados: Vec<DocumentoAutorizado> = Vec::new();
    if let Some(e) = &emp {
        if !e.razon_social.is_empty() {
            razon = e.razon_social.clone();
        }
        autorizados = e
            .documentos
            .iter()
            .filter(|d| d.desautorizado_desde.is_empty())
            .cloned()
            .collect();
    }
    let codigos: std::collections::HashSet<String> =
        autorizados.iter().map(|d| d.codigo.to_string()).collect();
    let lista_cod: Vec<String> = autorizados.iter().map(|d| d.codigo.to_string()).collect();
    let sw_actual = if sw_prod.software.is_empty() {
        "el sistema gratuito del SII".to_string()
    } else {
        sw_prod.software.clone()
    };
    let bloqueados: Vec<i32> = [33, 61]
        .into_iter()
        .filter(|t| sit_cert.get(t).map(|s| s.bloqueado).unwrap_or(false))
        .collect();
    let mut notas: Vec<String> = Vec::new();
    if codigos.contains("34") && !codigos.contains("33") && !sw_prod.propio {
        notas.push(
            "Hoy estás autorizada a Factura Exenta (34) pero NO a Factura Afecta (33), y emites por el sistema gratuito del SII. Eso es válido, pero para pasar a software propio (o de mercado) la certificación del SET BÁSICO agrega la Factura Afecta (33). No te obliga a emitir afectas — solo queda habilitada. Por eso proveedores como Haulmer piden 'factura' aunque solo emitas exenta."
                .into(),
        );
    }
    let (estado, etiqueta) = clasificar_software(&sw_prod, &sw_cert, registrado, nombre_software);
    if estado == "externo" {
        notas.push(format!(
            "Esta empresa emite hoy con «{sw_actual}», otro proveedor de facturación. Mientras siga así, NO emitas facturas con {nombre_sistema}: los folios del CAF los administra ese proveedor y se chocarían. Para migrar hay que cambiar el software registrado en el SII y traspasar (o anular) los folios que le queden."
        ));
    }
    let nombres_bloq = bloqueados
        .iter()
        .map(|t| {
            if *t == 33 {
                "Factura(33)"
            } else {
                "NotaCrédito(61)"
            }
        })
        .collect::<Vec<_>>()
        .join(", ");
    let chequeos = vec![
        Chequeo {
            id: "empresa".into(),
            titulo: "Empresa reconocida en el SII".into(),
            estado: ternario(emp.is_some(), "ok", "desconocido").into(),
            detalle: if emp.is_some() {
                razon.clone()
            } else {
                format!("El RUT {rut} no aparece en el SII.")
            },
        },
        Chequeo {
            id: "facturador".into(),
            titulo: "Inscrita como facturadora electrónica".into(),
            estado: ternario(!autorizados.is_empty(), "ok", "falta").into(),
            detalle: if !autorizados.is_empty() {
                format!("Autorizada a emitir: {}", lista_cod.join(", "))
            } else {
                "No aparece autorizada a emitir DTE todavía.".into()
            },
        },
        Chequeo {
            id: "software".into(),
            titulo: "Software de facturación actual".into(),
            estado: ternario(sw_prod.propio, "ok", "atencion").into(),
            detalle: format!(
                "Emite con «{sw_actual}»{}",
                if sw_prod.propio {
                    String::new()
                } else {
                    format!(" — hay que cambiarlo a {nombre_sistema}.")
                }
            ),
        },
        Chequeo {
            id: "certificacion".into(),
            titulo: "Certificación del software propio".into(),
            estado: ternario(
                sw_cert.certificado,
                "ok",
                ternario(sw_cert.propio, "atencion", "falta"),
            )
            .into(),
            detalle: ternario(
                sw_cert.certificado,
                "Certificado",
                ternario(sw_cert.propio, "En curso", "No iniciada"),
            )
            .into(),
        },
        Chequeo {
            id: "folios".into(),
            titulo: "Folios / timbraje para el set de pruebas".into(),
            estado: ternario(!bloqueados.is_empty(), "atencion", "ok").into(),
            detalle: if !bloqueados.is_empty() {
                format!("Bloqueado en: {nombres_bloq}")
            } else {
                "Sin bloqueos detectados".into()
            },
        },
    ];
    let mut acciones: Vec<Accion> = Vec::new();
    let acc = |t: &str, d: String, m: &str, hecho: bool, urgente: bool| Accion {
        titulo: t.into(),
        detalle: d,
        modo: m.into(),
        hecho,
        urgente,
    };
    if estado == "emitiendo" {
        acciones.push(acc(
            "Todo listo",
            format!("Ya emites en producción con {nombre_sistema}."),
            MODO_AUTO,
            true,
            false,
        ));
    } else {
        if autorizados.is_empty() {
            acciones.push(acc("Inscribir como facturador electrónico", "Declarar ante el SII que la empresa emitirá DTE. Requiere tu autorización (se hace con tu certificado).".into(), MODO_CONSENTIMIENTO, false, false));
        }
        if estado == "sin_propio" {
            acciones.push(acc("Registrar tu software en el SII", format!("Declarar «{nombre_sistema}» como tu software de facturación (Actualización de datos del contribuyente)."), MODO_CONSENTIMIENTO, false, false));
        }
        if !bloqueados.is_empty() {
            acciones.push(acc("Destrabar folios de prueba", "El timbraje está bloqueado por anti-acaparamiento. Se gestiona con la Mesa de Ayuda del SII (600 330 3000).".into(), MODO_HUMANO, false, true));
        }
        acciones.push(acc(
            "Completar el set de pruebas",
            "Emitir y validar los documentos del set de certificación (el sistema lo hace).".into(),
            MODO_AUTO,
            estado == "certificado",
            false,
        ));
        acciones.push(acc(
            "Obtener la resolución del SII",
            "Al terminar el set, el SII emite la resolución que autoriza tu software.".into(),
            MODO_AUTO,
            estado == "certificado",
            false,
        ));
        acciones.push(acc("Activar en producción", format!("Cambiar el software de facturación de «{sw_actual}» a {nombre_sistema} (Actualización de datos). Requiere tu autorización."), MODO_CONSENTIMIENTO, false, false));
    }
    if codigos.contains("39") || codigos.contains("41") {
        acciones.push(acc(
            "Declarar el modelo de emisión de boletas (si cobras con tarjeta)",
            "Hazlo UNA vez por empresa, con RUT y Clave de la EMPRESA (no la persona) en www4.sii.cl/actatributointernetui: marca «Siempre emito Boleta… aún cuando reciba un pago electrónico» (Modelo 1). Ojo: sin declarar, el SII asume que el voucher de la tarjeta ES tu boleta (Modelo 2) y tus ventas quedarían contadas doble. Guía paso a paso: docs/MODELO-EMISION.md.".into(),
            MODO_HUMANO,
            false,
            false,
        ));
    }
    let mut resumen = format!("{razon}: {}.", etiqueta.to_lowercase());
    if !bloqueados.is_empty() {
        resumen.push_str(" Hay folios bloqueados que destrabar.");
    }
    Ok(Diagnostico {
        rut: rut.into(),
        razon_social: razon,
        listo_para_emitir: estado == "emitiendo",
        estado,
        etiqueta,
        resumen,
        chequeos,
        acciones,
        notas,
    })
}

/// `diagnosticar_cartera`: todas las empresas del certificado (una sesión); una empresa que
/// falle se omite. `registrado_de` entrega `negocios.software_registrado(rut)`.
pub fn diagnosticar_cartera(
    p: &mut dyn Lector,
    ruts: Option<Vec<String>>,
    nombre_sistema: &str,
    registrado_de: Option<&dyn Fn(&str) -> String>,
    nombre_software: &str,
) -> Result<Vec<Diagnostico>, String> {
    let ruts = match ruts {
        Some(r) => r,
        None => p.empresas_asociadas()?.into_iter().map(|e| e.rut).collect(),
    };
    let mut out = Vec::new();
    for r in ruts {
        let reg = registrado_de.map(|f| f(&r)).unwrap_or_default();
        if let Ok(d) = diagnosticar(p, &r, nombre_sistema, &reg, nombre_software) {
            out.push(d);
        }
    }
    Ok(out)
}
