//! El RVD diario de boletas: rutas /api/v1/rvd/* y el programador (`core/scheduler.py`): un hilo
//! que cada `intervalo` revisa si hay RVD pendientes y los genera/envía. El proceso servidor es
//! el reloj (sin cron). Solo corre cuando el servidor está solo (sin motor Python reenviado).

use super::errores::{ok, Res};
use super::http::Peticion;
use super::keystore::{cert_id_de, negocios_de};
use super::{entero, log, texto, Json, Prot, Servidor};
use crate::firma;
use crate::rvd;
use crate::sii;
use serde_json::{json, Value};
use std::sync::atomic::Ordering;
use std::sync::Arc;
use std::time::Duration;

const RVD_GENERADO: &str = "generado";
const RVD_ENVIADO: &str = "enviado";
const RVD_ERROR: &str = "error";
const RVD_PENDIENTE_RUTA: &str = "pendiente_ruta";

pub struct EstadoRVD {
    pub activo: bool,
    pub intervalo_seg: i64,
    pub dias_atras: i64,
    pub ultima_corrida: Option<String>,
    pub ultimo_resultado: Vec<Value>,
}

impl EstadoRVD {
    pub fn nuevo(intervalo_seg: i64) -> EstadoRVD {
        EstadoRVD {
            activo: false,
            intervalo_seg,
            dias_atras: 7,
            ultima_corrida: None,
            ultimo_resultado: Vec::new(),
        }
    }
}

pub fn rutas(s: &mut Servidor) {
    s.ruta("GET /api/v1/rvd/estado", Prot::Protegida, rvd_estado);
    s.ruta("POST /api/v1/rvd/procesar", Prot::Protegida, rvd_procesar);
    s.ruta(
        "GET /api/v1/rvd/registros/{rut}",
        Prot::Protegida,
        rvd_registros,
    );
}

// ---------------------------------------------------------------- hora de Chile

fn dias_desde_civil(a: i64, m: i64, d: i64) -> i64 {
    let (y, mm) = if m <= 2 { (a - 1, m + 9) } else { (a, m - 3) };
    let era = y.div_euclid(400);
    let yoe = y - era * 400;
    let doy = (153 * mm + 2) / 5 + d - 1;
    let doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    era * 146097 + doe - 719468
}

/// Primer domingo de un mes, en días desde 1970 (día de la semana: 1970-01-01 fue jueves).
fn primer_domingo(a: i64, m: i64) -> i64 {
    let d1 = dias_desde_civil(a, m, 1);
    let dow = (d1 + 4).rem_euclid(7); // 0 = domingo
    d1 + (7 - dow) % 7
}

/// America/Santiago (Chile continental): horario de verano (UTC-3) desde el primer domingo de
/// septiembre hasta el primer domingo de abril; el resto del año UTC-4.
pub fn desfase_chile(segundos_utc: i64) -> i64 {
    let dias = segundos_utc.div_euclid(86400);
    let (a, _, _) = crate::almacen::civil_desde_dias(dias);
    // las transiciones son a las 00:00 locales = 04:00/03:00 UTC: se aproximan a las 04:00 UTC
    let fin_verano = primer_domingo(a, 4) * 86400 + 3 * 3600;
    let inicio_verano = primer_domingo(a, 9) * 86400 + 4 * 3600;
    if segundos_utc < fin_verano || segundos_utc >= inicio_verano {
        -3 * 3600
    } else {
        -4 * 3600
    }
}

/// `scheduler.hoy_chile`: (fecha ISO, hora RFC3339 con desfase) de ahora en Chile.
pub fn ahora_chile() -> (String, String) {
    let utc = super::auth::ahora_unix();
    let off = desfase_chile(utc);
    let local = super::fecha_hora_utc(utc + off);
    let signo = if off < 0 { '-' } else { '+' };
    let h = off.abs() / 3600;
    (local[..10].to_string(), format!("{local}{signo}{h:02}:00"))
}

/// `fecha + n días` (YYYY-MM-DD).
pub fn sumar_dias(fecha: &str, n: i64) -> String {
    let (a, m, d) = (
        fecha[..4].parse::<i64>().unwrap_or(1970),
        fecha[5..7].parse::<i64>().unwrap_or(1),
        fecha[8..10].parse::<i64>().unwrap_or(1),
    );
    let (aa, mm, dd) = crate::almacen::civil_desde_dias(dias_desde_civil(a, m, d) + n);
    format!("{aa:04}-{mm:02}-{dd:02}")
}

// ---------------------------------------------------------------- programador

pub fn iniciar_programador(s: &Arc<Servidor>) {
    if !s.cfg.rvd_scheduler_activo || !s.cfg.motor_python.is_empty() {
        return;
    }
    {
        let mut e = s.rvd.lock().expect("rvd");
        e.activo = true;
    }
    let srv = Arc::clone(s);
    std::thread::spawn(move || loop {
        let (hoy, ahora) = ahora_chile();
        let res = srv.procesar_pendientes(1, 7, &hoy);
        let hechos = res
            .iter()
            .filter(|r| !r.get("omitido").and_then(Value::as_bool).unwrap_or(false))
            .count();
        {
            let mut e = srv.rvd.lock().expect("rvd");
            e.ultima_corrida = Some(ahora);
            e.ultimo_resultado = res;
        }
        if hechos > 0 {
            log(&format!("RVD: {hechos} día(s) procesado(s)"));
        }
        let espera = srv.cfg.rvd_intervalo_seg.max(1) as u64;
        for _ in 0..espera {
            if srv.parar_rvd.load(Ordering::SeqCst) {
                return;
            }
            std::thread::sleep(Duration::from_secs(1));
        }
    });
    log(&format!(
        "Programador de RVD iniciado (cada {}s, catch-up de 7 días)",
        s.cfg.rvd_intervalo_seg
    ));
}

impl Servidor {
    /// `scheduler.procesar_pendientes`: recorre las empresas y genera el RVD de los días con
    /// boletas aún no reportados, mirando `dias_atras` hacia atrás (catch-up). No incluye hoy.
    pub fn procesar_pendientes(&self, cuenta: i64, dias_atras: i64, hoy: &str) -> Vec<Value> {
        let hasta = sumar_dias(hoy, -1);
        let desde = sumar_dias(hoy, -dias_atras);
        let negs = match negocios_de(self, cuenta) {
            Ok(n) => n,
            Err(e) => return vec![json!({"estado": RVD_ERROR, "detalle": e.mensaje})],
        };
        let mut out = Vec::new();
        for n in negs {
            let rut = texto(&n["rut"]);
            if rut.is_empty() {
                continue;
            }
            match rvd::dias_con_boletas(&self.alm, &rut, &desde, &hasta, &self.cfg.sii_ambiente) {
                Err(e) => {
                    out.push(json!({"rut": rut, "estado": RVD_ERROR, "detalle": e.to_string()}))
                }
                Ok(dias) => {
                    for d in dias {
                        out.push(self.procesar_dia(&rut, cert_id_de(&n), &d, cuenta));
                    }
                }
            }
        }
        out
    }

    fn ruta_rvd(&self, rut: &str, dia: &str) -> String {
        let carpeta = std::path::Path::new(&self.cfg.storage_path).join("rvd");
        let _ = std::fs::create_dir_all(&carpeta);
        carpeta
            .join(format!("RVD_{rut}_{dia}.xml"))
            .to_string_lossy()
            .into_owned()
    }

    /// `scheduler.procesar_dia`: genera (y guarda) el RVD de un día. Idempotente: solo se omite
    /// lo que ya llegó al SII; un día `generado` (XML listo, no enviado) SÍ se reintenta.
    pub fn procesar_dia(&self, rut: &str, cert_id: Option<i64>, dia: &str, cuenta: i64) -> Value {
        if let Ok(Some(ya)) = rvd::registrado(&self.alm, rut, dia) {
            if ya.estado == RVD_ENVIADO || ya.estado == RVD_PENDIENTE_RUTA {
                return json!({"rut": rut, "dia": dia, "estado": "ya_estaba", "omitido": true});
            }
        }
        let falla = |estado: &str, detalle: String, xml_path: &str| -> Value {
            let _ = rvd::registrar(&self.alm, rut, dia, estado, 1, "", xml_path, &detalle);
            let mut r = json!({"rut": rut, "dia": dia, "estado": estado, "detalle": detalle});
            if !xml_path.is_empty() {
                r["xml_path"] = json!(xml_path);
            }
            r
        };
        let Some(cert_id) = cert_id else {
            return falla(
                RVD_ERROR,
                "El negocio no tiene certificado asociado: no se puede firmar el RVD.".into(),
                "",
            );
        };
        let (p12, clave) = match self.descifrar_certificado(cert_id, cuenta) {
            Ok(v) => v,
            Err(e) => return falla(RVD_ERROR, format!("certificado: {e}"), ""),
        };
        let cert = match firma::cargar_p12(&p12, &clave) {
            Ok(c) => c,
            Err(e) => return falla(RVD_ERROR, format!("certificado: {e}"), ""),
        };
        let rut_envia = match cert.rut_emisor() {
            Ok(r) => r,
            Err(e) => return falla(RVD_ERROR, format!("certificado sin RUT: {e}"), ""),
        };
        let docs = match rvd::boletas_del_dia(&self.alm, rut, dia, &self.cfg.sii_ambiente) {
            Ok(d) => d,
            Err(e) => return falla(RVD_ERROR, format!("boletas del día: {e}"), ""),
        };
        let (fecha, num) = self.resolucion_emisor(rut, &self.cfg.sii_ambiente);
        let params = rvd::Parametros {
            rut_emisor: rut.into(),
            rut_envia,
            fecha_resolucion: fecha,
            numero_resolucion: num,
            dia: dia.into(),
            tipos: rvd::TIPOS_CONSUMO.to_vec(),
            sec_envio: 1,
            marca: self.marca(),
            documentos: docs,
            ..Default::default()
        };
        let xml = match rvd::generar_firmado(&cert, &params) {
            Ok(x) => x,
            Err(e) => {
                log(&format!("RVD {rut} {dia} falló al generar: {e}"));
                return falla(RVD_ERROR, e, "");
            }
        };
        let ruta = self.ruta_rvd(rut, dia);
        if let Err(e) = std::fs::write(&ruta, &xml) {
            return falla(RVD_ERROR, format!("escribir XML: {e}"), "");
        }
        // Envío por el canal de FACTURAS (DTEUpload + token SOAP), no por el REST de boletas.
        let mut cli = match sii::http::Cliente::nuevo(&self.cfg.sii_ambiente, cert) {
            Ok(c) => c,
            Err(e) => return falla(RVD_GENERADO, e, &ruta),
        };
        match rvd::enviar(&mut cli, &xml, rut) {
            Err(e) => {
                log(&format!("RVD {rut} {dia} generado pero NO enviado: {e}"));
                falla(RVD_GENERADO, e, &ruta)
            }
            Ok((track, _)) => {
                let _ = rvd::registrar(
                    &self.alm,
                    rut,
                    dia,
                    RVD_ENVIADO,
                    1,
                    &track.to_string(),
                    &ruta,
                    &format!("Enviado por DTEUpload ({}).", self.cfg.sii_ambiente),
                );
                log(&format!("RVD {rut} {dia} enviado → TrackID {track}"));
                json!({"rut": rut, "dia": dia, "estado": RVD_ENVIADO, "track_id": track.to_string(), "xml_path": ruta})
            }
        }
    }
}

fn rvd_estado(s: &Servidor, _p: &mut Peticion) -> Res {
    let e = s.rvd.lock().expect("rvd");
    let (hoy, _) = ahora_chile();
    ok(
        json!({"activo": e.activo, "intervalo_seg": e.intervalo_seg, "dias_atras": e.dias_atras,
        "zona_horaria": "America/Santiago", "hoy_chile": hoy, "ultima_corrida": e.ultima_corrida, "ultimo_resultado": e.ultimo_resultado}),
    )
}

/// Corre el catch-up a pedido (lo que el programador hace solo).
fn rvd_procesar(s: &Servidor, p: &mut Peticion) -> Res {
    let mut dias = 0;
    if !p.cuerpo.is_empty() {
        dias = Json::leer(p)?.entero_o("dias_atras", 0)?;
    }
    if dias <= 0 {
        dias = 7;
    }
    let mut cuenta = s.cuenta_id(p);
    if cuenta == 0 {
        cuenta = 1;
    }
    let (hoy, _) = ahora_chile();
    ok(json!({"resultados": s.procesar_pendientes(cuenta, dias, &hoy)}))
}

fn rvd_registros(s: &Servidor, p: &mut Peticion) -> Res {
    let rut = p.param("rut").to_string();
    let filas = s.filas(
        "SELECT id, rut_emisor, fecha, sec_envio, estado, COALESCE(track_id,'') AS track_id, COALESCE(xml_path,'') AS xml_path, COALESCE(detalle,'') AS detalle FROM rvd_envios WHERE rut_emisor=? ORDER BY fecha DESC, sec_envio DESC LIMIT 200",
        &sql![rut.clone()],
    )?;
    let regs: Vec<Value> = filas
        .iter()
        .map(|f| json!({"id": f["id"], "rut_emisor": f["rut_emisor"], "fecha": f["fecha"], "sec_envio": f["sec_envio"], "estado": f["estado"],
            "track_id": texto(&f["track_id"]), "xml_path": texto(&f["xml_path"]), "detalle": texto(&f["detalle"])}))
        .collect();
    let _ = entero;
    ok(json!({"rut": rut, "registros": regs}))
}
