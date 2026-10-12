//! `core/sii_boleta.py::ClienteBoletaSII`: las boletas (39/41) NO comparten infraestructura
//! con las facturas (Res. Ex. SII N° 74 de 2020): servicios REST, servidores propios y token
//! propio (el de factura no sirve aquí).
//!
//! ⚠️ LOS HOSTS SON ASIMÉTRICOS, es el error que más tiempo cuesta:
//!
//! | paso                       | certificación  | producción  |
//! |----------------------------|----------------|-------------|
//! | semilla · token · consulta | apicert.sii.cl | api.sii.cl  |
//! | ENVÍO                      | pangal.sii.cl  | rahue.sii.cl|
//!
//! Mandar el ENVÍO a apicert/api devuelve un SOAP Fault "Acceso Denegado" con HTTP 500 que
//! parece un problema de permisos; pangal/rahue responden 400 "No trae TOKEN" → ésa es la ruta.

use super::http::{agente, ejecutar, ejecutar_get, multipart, Respuesta};
use super::{firma_get_token, USER_AGENT};
use crate::firma::Certificado;
use regex::Regex;
use serde_json::Value;
use std::sync::OnceLock;
use std::time::{Duration, Instant};

fn urls(ambiente: &str) -> Option<[&'static str; 4]> {
    // semilla, token, envio, estado
    match ambiente {
        "certificacion" => Some([
            "https://apicert.sii.cl/recursos/v1/boleta.electronica.semilla",
            "https://apicert.sii.cl/recursos/v1/boleta.electronica.token",
            "https://pangal.sii.cl/recursos/v1/boleta.electronica.envio",
            "https://apicert.sii.cl/recursos/v1/boleta.electronica.envio",
        ]),
        "produccion" => Some([
            "https://api.sii.cl/recursos/v1/boleta.electronica.semilla",
            "https://api.sii.cl/recursos/v1/boleta.electronica.token",
            "https://rahue.sii.cl/recursos/v1/boleta.electronica.envio",
            "https://api.sii.cl/recursos/v1/boleta.electronica.envio",
        ]),
        _ => None,
    }
}

/// El SII responde el ESTADO de semilla/token como DOS dígitos ("00"), no "0".
const ESTADO_OK: &str = "00";
/// EPR = "Envío Procesado", NO "aceptado": el veredicto por documento está en `estadistica`.
pub const ESTADO_PROCESADO: &str = "EPR";
pub const ESTADO_RECHAZADO: &str = "RCT";
/// Tope de boletas por sobre. NO está en el XSD: viene del Instructivo Técnico y es un tope
/// conservador nuestro.
pub const MAX_BOLETAS_POR_ENVIO: usize = 500;

/// `ClienteBoletaSII._firmar_semilla`: el mismo `<getToken>` firmado del flujo SOAP pero
/// compacto (sin saltos de línea) y mandado DIRECTO como body, sin escapar.
pub fn firmar_semilla_boleta(cert: &Certificado, semilla: &str) -> Result<String, String> {
    let doc = format!("<getToken><item><Semilla>{semilla}</Semilla></item></getToken>");
    let sig = firma_get_token(cert, &doc)?;
    Ok(format!("<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<getToken><item><Semilla>{semilla}</Semilla></item>{sig}</getToken>"))
}

static RE_ELEMENTO: OnceLock<Regex> = OnceLock::new();

/// El texto del primer elemento llamado `tag` (sin namespaces), como `core/sii_boleta.py::_texto`.
pub fn texto_de(xml: &str, tag: &str) -> String {
    let re = RE_ELEMENTO
        .get_or_init(|| Regex::new(r"<([A-Za-z_]+)>([^<]*)</[A-Za-z_]+>").expect("regex"));
    re.captures_iter(xml)
        .find(|m| &m[1] == tag)
        .map(|m| m[2].trim().to_string())
        .unwrap_or_default()
}

/// El SII respondió pero no recibió el envío (estado != REC).
#[derive(Debug)]
pub struct ErrRechazo {
    pub estado: String,
    pub detalle: Value,
}

impl std::fmt::Display for ErrRechazo {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(
            f,
            "el SII no recibió el envío de boletas (estado={})",
            self.estado
        )
    }
}

#[derive(Debug)]
pub enum ErrorBoleta {
    Rechazo(ErrRechazo),
    Otro(String),
}

impl std::fmt::Display for ErrorBoleta {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            ErrorBoleta::Rechazo(r) => write!(f, "{r}"),
            ErrorBoleta::Otro(s) => write!(f, "{s}"),
        }
    }
}

impl From<String> for ErrorBoleta {
    fn from(s: String) -> Self {
        ErrorBoleta::Otro(s)
    }
}

/// Resultado de la consulta por TrackID (`core/sii_boleta.py::consultar_estado`).
#[derive(Debug, Clone, Default, serde::Serialize)]
pub struct EstadoBoleta {
    pub track_id: String,
    pub estado: String,
    pub glosa: String,
    pub procesado: bool,
    pub informados: i64,
    pub aceptados: i64,
    pub rechazados: i64,
    pub reparos: i64,
    pub todo_aceptado: bool,
    pub resuelto: bool,
    pub detalle: Value,
    pub respuesta_raw: Value,
}

pub struct ClienteBoleta {
    pub ambiente: String,
    pub cert: Certificado,
    agente: ureq::Agent,
    token: Option<(String, Instant)>,
}

fn entero(v: Option<&Value>) -> i64 {
    match v {
        Some(Value::Number(n)) => n.as_f64().unwrap_or(0.0) as i64,
        Some(Value::String(s)) => s.trim().parse().unwrap_or(0),
        _ => 0,
    }
}

impl ClienteBoleta {
    pub fn nuevo(ambiente: &str, cert: Certificado) -> Result<ClienteBoleta, String> {
        urls(ambiente).ok_or_else(|| format!("ambiente desconocido: {ambiente:?}"))?;
        Ok(ClienteBoleta {
            ambiente: ambiente.to_string(),
            cert,
            agente: agente(Duration::from_secs(60), true),
            token: None,
        })
    }

    fn url(&self, i: usize) -> &'static str {
        urls(&self.ambiente).map(|u| u[i]).unwrap_or("")
    }

    /// Hasta 3 intentos ante 5xx o error de red.
    fn pedir(&self, armar: impl Fn() -> Result<Respuesta, String>) -> Result<Respuesta, String> {
        let mut ultimo = String::new();
        for intento in 0..3 {
            match armar() {
                Ok(r) if r.status < 500 => return Ok(r),
                Ok(r) => ultimo = format!("HTTP {}: {:.300}", r.status, r.texto()),
                Err(e) => ultimo = e,
            }
            std::thread::sleep(Duration::from_millis(500 * (intento + 1)));
        }
        Err(ultimo)
    }

    /// Pide una semilla (REST, sin autenticación).
    pub fn semilla(&self) -> Result<String, String> {
        let r = self
            .pedir(|| {
                ejecutar_get(
                    self.agente
                        .get(self.url(0))
                        .header("accept", "application/xml"),
                )
            })
            .map_err(|e| format!("no se pudo pedir la semilla de boleta al SII: {e}"))?;
        if r.status >= 400 {
            return Err(format!(
                "no se pudo pedir la semilla de boleta al SII: HTTP {}",
                r.status
            ));
        }
        let resp = r.texto();
        let (estado, semilla) = (texto_de(&resp, "ESTADO"), texto_de(&resp, "SEMILLA"));
        if estado != ESTADO_OK || semilla.is_empty() {
            return Err(format!(
                "el SII no entregó semilla de boleta (ESTADO={estado}, GLOSA={})",
                texto_de(&resp, "GLOSA")
            ));
        }
        Ok(semilla)
    }

    /// semilla → firma → token de boleta (cacheado 50 min).
    pub fn token(&mut self) -> Result<String, String> {
        if let Some((t, hasta)) = &self.token {
            if Instant::now() < *hasta {
                return Ok(t.clone());
            }
        }
        let sem = self.semilla()?;
        let cuerpo = firmar_semilla_boleta(&self.cert, &sem)?;
        let r = self
            .pedir(|| {
                ejecutar(
                    self.agente
                        .post(self.url(1))
                        .header("Content-Type", "application/xml")
                        .header("accept", "application/xml"),
                    cuerpo.as_bytes(),
                )
            })
            .map_err(|e| format!("no se pudo obtener el token de boleta: {e}"))?;
        if r.status >= 400 {
            return Err(format!(
                "no se pudo obtener el token de boleta: HTTP {}",
                r.status
            ));
        }
        let resp = r.texto();
        let tok = texto_de(&resp, "TOKEN");
        if tok.is_empty() {
            // El SII responde 200 aunque falle: el error viene en ESTADO/GLOSA.
            return Err(format!(
                "el SII no entregó token de boleta (ESTADO={}, GLOSA={})",
                texto_de(&resp, "ESTADO"),
                texto_de(&resp, "GLOSA")
            ));
        }
        self.token = Some((tok.clone(), Instant::now() + Duration::from_secs(50 * 60)));
        Ok(tok)
    }

    /// Sube un EnvioBOLETA firmado (ISO-8859-1) y devuelve `(TrackID, respuesta)`. El RUT va
    /// PARTIDO y sin guion en cuatro campos: quien envía (dueño del certificado) y la empresa.
    pub fn enviar(
        &mut self,
        xml_envio: &[u8],
        rut_empresa: &str,
        dv_empresa: &str,
    ) -> Result<(String, Value), ErrorBoleta> {
        let tok = self.token()?;
        let (rut_s, dv_s) = match self.cert.rut_emisor() {
            Ok(r) if r.contains('-') => {
                let (a, b) = r.split_once('-').unwrap();
                (a.to_string(), b.to_string())
            }
            _ => (rut_empresa.to_string(), dv_empresa.to_string()),
        };
        let (ct, cuerpo) = multipart(
            &[
                ("rutSender", &rut_s),
                ("dvSender", &dv_s),
                ("rutCompany", rut_empresa),
                ("dvCompany", dv_empresa),
            ],
            (
                "archivo",
                &format!("{rut_empresa}-{dv_empresa}_boletas.xml"),
                "text/xml",
                xml_envio,
            ),
        );
        let r = self
            .pedir(|| {
                ejecutar(
                    self.agente
                        .post(self.url(2))
                        .header("Content-Type", &ct)
                        .header("Cookie", &format!("TOKEN={tok}"))
                        .header("Accept", "application/json")
                        .header("User-Agent", USER_AGENT), // sin esto: 401 "NO ESTA AUTENTICADO" engañoso
                    &cuerpo,
                )
            })
            .map_err(|e| format!("falló el envío de boletas al SII: {e}"))?;
        if r.status >= 400 {
            return Err(format!(
                "falló el envío de boletas al SII: HTTP {}: {:.300}",
                r.status,
                r.texto()
            )
            .into());
        }
        let resp: Value = serde_json::from_slice(&r.cuerpo)
            .map_err(|_| format!("la respuesta del envío de boletas no es JSON (¿endpoint equivocado? el envío va a pangal/rahue): {:.300}", r.texto()))?;
        let estado = resp
            .get("estado")
            .map(|v| {
                v.as_str()
                    .map(str::to_string)
                    .unwrap_or_else(|| v.to_string())
            })
            .unwrap_or_default()
            .to_uppercase();
        if estado != "REC" {
            let mut det = serde_json::Map::new();
            if let Some(m) = resp.as_object() {
                for (k, v) in m {
                    if k != "archivo" {
                        det.insert(k.clone(), v.clone());
                    }
                }
            }
            return Err(ErrorBoleta::Rechazo(ErrRechazo {
                estado,
                detalle: Value::Object(det),
            }));
        }
        let track = resp
            .get("trackid")
            .map(|v| {
                v.as_str()
                    .map(str::to_string)
                    .unwrap_or_else(|| v.to_string())
            })
            .unwrap_or_default()
            .trim()
            .to_string();
        if track.is_empty() || track == "null" {
            return Err("el SII aceptó el envío pero no devolvió TrackID"
                .to_string()
                .into());
        }
        Ok((track, resp))
    }

    /// Consulta un envío: el TrackID va EN EL PATH pegado al RUT ({RUT}-{DV}-{TRACKID}).
    pub fn estado(
        &mut self,
        track_id: &str,
        rut_empresa: &str,
        dv_empresa: &str,
    ) -> Result<EstadoBoleta, String> {
        let tok = self.token()?;
        let u = format!("{}/{rut_empresa}-{dv_empresa}-{track_id}", self.url(3));
        let r = self
            .pedir(|| {
                ejecutar_get(
                    self.agente
                        .get(&u)
                        .header("Cookie", &format!("TOKEN={tok}"))
                        .header("Accept", "application/json")
                        .header("User-Agent", USER_AGENT),
                )
            })
            .map_err(|e| format!("no se pudo consultar el estado del envío {track_id}: {e}"))?;
        if r.status >= 400 {
            return Err(format!(
                "no se pudo consultar el estado del envío {track_id}: HTTP {}",
                r.status
            ));
        }
        let resp: Value = serde_json::from_slice(&r.cuerpo).map_err(|_| {
            format!(
                "la respuesta de estado del envío {track_id} no es JSON: {:.300}",
                r.texto()
            )
        })?;
        let mut e = EstadoBoleta {
            track_id: track_id.to_string(),
            estado: resp
                .get("estado")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_uppercase(),
            detalle: resp.get("detalle_rep_rech").cloned().unwrap_or(Value::Null),
            respuesta_raw: resp.clone(),
            ..Default::default()
        };
        for k in ["glosa", "descripcion"] {
            if let Some(v) = resp.get(k).and_then(|v| v.as_str()) {
                if !v.is_empty() {
                    e.glosa = v.to_string();
                    break;
                }
            }
        }
        if let Some(lista) = resp.get("estadistica").and_then(|v| v.as_array()) {
            for x in lista {
                e.informados += entero(x.get("informados"));
                e.aceptados += entero(x.get("aceptados"));
                e.rechazados += entero(x.get("rechazados"));
                e.reparos += entero(x.get("reparos"));
            }
        }
        e.procesado = e.estado == ESTADO_PROCESADO;
        e.todo_aceptado = e.procesado && e.informados > 0 && e.rechazados == 0 && e.reparos == 0;
        e.resuelto = matches!(
            e.estado.as_str(),
            ESTADO_PROCESADO | ESTADO_RECHAZADO | "RLV" | "RPR"
        );
        Ok(e)
    }
}
