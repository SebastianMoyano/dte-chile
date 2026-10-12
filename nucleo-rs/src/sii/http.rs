//! El cliente SOAP/DTEUpload del SII (Maullín/Palena) y lo que comparten todos los clientes
//! HTTP del núcleo: un agente `ureq` sin convertir los estados HTTP en errores, y un armador
//! de multipart/form-data como el de Go (`mime/multipart`).

use super::{firmar_semilla, host, valor, Error, Estado, USER_AGENT};
use crate::firma::Certificado;
use std::time::{Duration, Instant};

/// Un agente HTTP con tiempo máximo global y sin seguir redirecciones si `redirigir` es false.
pub fn agente(timeout: Duration, redirigir: bool) -> ureq::Agent {
    let config = ureq::Agent::config_builder()
        .timeout_global(Some(timeout))
        .http_status_as_error(false)
        .max_redirects(if redirigir { 10 } else { 0 })
        .max_redirects_will_error(false)
        .build();
    config.into()
}

/// Respuesta HTTP ya leída.
pub struct Respuesta {
    pub status: u16,
    pub cuerpo: Vec<u8>,
    pub headers: Vec<(String, String)>,
}

impl Respuesta {
    pub fn header(&self, nombre: &str) -> Option<&str> {
        self.headers
            .iter()
            .find(|(k, _)| k.eq_ignore_ascii_case(nombre))
            .map(|(_, v)| v.as_str())
    }

    pub fn texto(&self) -> String {
        String::from_utf8_lossy(&self.cuerpo).into_owned()
    }
}

/// Ejecuta una petición ya armada y lee el cuerpo entero.
pub fn ejecutar(
    req: ureq::RequestBuilder<ureq::typestate::WithBody>,
    cuerpo: &[u8],
) -> Result<Respuesta, String> {
    let mut r = req.send(cuerpo).map_err(|e| e.to_string())?;
    let status = r.status().as_u16();
    let headers = r
        .headers()
        .iter()
        .map(|(k, v)| {
            (
                k.to_string(),
                String::from_utf8_lossy(v.as_bytes()).into_owned(),
            )
        })
        .collect();
    let cuerpo = r
        .body_mut()
        .with_config()
        .limit(64 << 20)
        .read_to_vec()
        .map_err(|e| e.to_string())?;
    Ok(Respuesta {
        status,
        cuerpo,
        headers,
    })
}

pub fn ejecutar_get(
    req: ureq::RequestBuilder<ureq::typestate::WithoutBody>,
) -> Result<Respuesta, String> {
    let mut r = req.call().map_err(|e| e.to_string())?;
    let status = r.status().as_u16();
    let headers = r
        .headers()
        .iter()
        .map(|(k, v)| {
            (
                k.to_string(),
                String::from_utf8_lossy(v.as_bytes()).into_owned(),
            )
        })
        .collect();
    let cuerpo = r
        .body_mut()
        .with_config()
        .limit(64 << 20)
        .read_to_vec()
        .map_err(|e| e.to_string())?;
    Ok(Respuesta {
        status,
        cuerpo,
        headers,
    })
}

/// multipart/form-data como lo arma `mime/multipart` de Go: campos de texto y un archivo con
/// su nombre y tipo. Devuelve `(content-type, cuerpo)`.
pub fn multipart(campos: &[(&str, &str)], archivo: (&str, &str, &str, &[u8])) -> (String, Vec<u8>) {
    let boundary: String = {
        let mut b = String::with_capacity(60);
        let semilla = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_nanos())
            .unwrap_or(0);
        let mut x = semilla ^ 0x9E37_79B9_7F4A_7C15_u128;
        while b.len() < 60 {
            x ^= x << 13;
            x ^= x >> 7;
            x ^= x << 17;
            b.push_str(&format!("{:016x}", (x as u64)));
        }
        b.truncate(60);
        b
    };
    let mut out = Vec::new();
    for (k, v) in campos {
        out.extend(
            format!("--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n")
                .into_bytes(),
        );
    }
    let (campo, nombre, tipo, datos) = archivo;
    out.extend(format!("--{boundary}\r\nContent-Disposition: form-data; name=\"{campo}\"; filename=\"{nombre}\"\r\nContent-Type: {tipo}\r\n\r\n").into_bytes());
    out.extend_from_slice(datos);
    out.extend(format!("\r\n--{boundary}--\r\n").into_bytes());
    (format!("multipart/form-data; boundary={boundary}"), out)
}

/// `ClienteSII`: semilla → token (cacheado 50 min) → DTEUpload → estado.
pub struct Cliente {
    pub ambiente: String,
    pub cert: Certificado,
    agente: ureq::Agent,
    token: Option<(String, Instant)>,
}

impl Cliente {
    pub fn nuevo(ambiente: &str, cert: Certificado) -> Result<Cliente, String> {
        host(ambiente).ok_or_else(|| {
            format!("ambiente desconocido {ambiente:?} (certificacion | produccion)")
        })?;
        Ok(Cliente {
            ambiente: ambiente.to_string(),
            cert,
            agente: agente(Duration::from_secs(90), true),
            token: None,
        })
    }

    fn url(&self, ruta: &str) -> String {
        format!("{}{}", host(&self.ambiente).unwrap_or(""), ruta)
    }

    /// POST SOAP con hasta 3 intentos ante 5xx o error de red (Maullín devuelve 503
    /// intermitentes; core/sii.py usa ClienteReintentos por lo mismo).
    fn soap(&self, ruta: &str, cuerpo: &str) -> Result<String, Error> {
        let mut ultimo = String::new();
        for intento in 0..3 {
            if intento > 0 {
                std::thread::sleep(Duration::from_secs(2 * intento as u64));
            }
            let req = self
                .agente
                .post(&self.url(ruta))
                .header("Content-Type", "text/xml; charset=UTF-8")
                .header("SOAPAction", "")
                .header("User-Agent", USER_AGENT);
            match ejecutar(req, cuerpo.as_bytes()) {
                Err(e) => ultimo = e,
                Ok(r) if r.status >= 500 => {
                    ultimo = format!("SII {ruta} → HTTP {}: {:.200}", r.status, r.texto())
                }
                Ok(r) if r.status >= 400 => {
                    return Err(Error::Comunicacion(format!(
                        "SII {ruta} → HTTP {}: {:.300}",
                        r.status,
                        r.texto()
                    )))
                }
                Ok(r) => return Ok(r.texto()),
            }
        }
        Err(Error::Comunicacion(format!("tras 3 intentos: {ultimo}")))
    }

    pub fn semilla(&self) -> Result<String, Error> {
        let resp = self.soap(
            "/DTEWS/CrSeed.jws",
            "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<soapenv:Envelope xmlns:soapenv=\"http://schemas.xmlsoap.org/soap/envelope/\">\n  <soapenv:Body>\n    <getSeed/>\n  </soapenv:Body>\n</soapenv:Envelope>",
        )?;
        let s = valor(&resp, "SEMILLA");
        if s.is_empty() {
            return Err(Error::Respuesta(format!(
                "No se pudo obtener la semilla del SII. Respuesta: {resp:.300}"
            )));
        }
        Ok(s)
    }

    /// semilla → firma → token, cacheado 50 minutos (como Python).
    pub fn token(&mut self) -> Result<String, Error> {
        if let Some((t, hasta)) = &self.token {
            if Instant::now() < *hasta {
                return Ok(t.clone());
            }
        }
        let sem = self.semilla()?;
        let firmada = firmar_semilla(&self.cert, &sem).map_err(Error::Respuesta)?;
        let esc = firmada
            .replace('&', "&amp;")
            .replace('<', "&lt;")
            .replace('>', "&gt;");
        let resp = self.soap(
            "/DTEWS/GetTokenFromSeed.jws",
            &format!("<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<soapenv:Envelope xmlns:soapenv=\"http://schemas.xmlsoap.org/soap/envelope/\">\n  <soapenv:Body>\n    <getToken>\n      <pszXml>{esc}</pszXml>\n    </getToken>\n  </soapenv:Body>\n</soapenv:Envelope>"),
        )?;
        let t = valor(&resp, "TOKEN");
        if t.is_empty() {
            return Err(Error::Respuesta(format!(
                "No se pudo obtener el token del SII. Respuesta: {resp:.300}"
            )));
        }
        self.token = Some((t.clone(), Instant::now() + Duration::from_secs(50 * 60)));
        Ok(t)
    }

    /// Sube el sobre (EnvioDTE) por DTEUpload. Boletas NO van por aquí (otra API). Devuelve
    /// `(track_id, respuesta cruda)`.
    pub fn enviar_dte(
        &mut self,
        xml_envio: &[u8],
        rut_empresa: &str,
        dv_empresa: &str,
    ) -> Result<(i64, String), Error> {
        let cabeza = &xml_envio[..xml_envio.len().min(200)];
        if cabeza.windows(11).any(|w| w == b"EnvioBOLETA") {
            return Err(Error::Respuesta(
                "las boletas no se envían por DTEUpload".into(),
            ));
        }
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
                &format!("{rut_empresa}-{dv_empresa}_envio.xml"),
                "application/xml",
                xml_envio,
            ),
        );
        let req = self
            .agente
            .post(&self.url("/cgi_dte/UPL/DTEUpload"))
            .header("Content-Type", &ct)
            .header("User-Agent", USER_AGENT)
            .header("Cookie", &format!("TOKEN={tok}"));
        let r = ejecutar(req, &cuerpo).map_err(Error::Comunicacion)?;
        let resp = r.texto();
        if r.status >= 400 {
            return Err(Error::Comunicacion(format!(
                "DTEUpload HTTP {}: {resp:.300}",
                r.status
            )));
        }
        let estado = valor(&resp, "STATUS");
        let track: i64 = valor(&resp, "TRACKID").parse().unwrap_or(0);
        if estado != "0" {
            return Err(Error::Respuesta(format!(
                "El SII rechazó el envío. Estado: {estado}. Respuesta: {resp:.300}"
            )));
        }
        Ok((track, resp))
    }

    pub fn estado_track(
        &mut self,
        track: i64,
        rut_empresa: &str,
        dv_empresa: &str,
    ) -> Result<Estado, Error> {
        let tok = self.token()?;
        let resp = self.soap(
            "/DTEWS/QueryEstUp.jws",
            &format!("<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<soapenv:Envelope xmlns:soapenv=\"http://schemas.xmlsoap.org/soap/envelope/\">\n  <soapenv:Body>\n    <getEstUp>\n      <Rut>{rut_empresa}</Rut>\n      <Dv>{dv_empresa}</Dv>\n      <TrackId>{track}</TrackId>\n      <Token>{tok}</Token>\n    </getEstUp>\n  </soapenv:Body>\n</soapenv:Envelope>"),
        )?;
        let mut e = Estado {
            track_id: track,
            estado: valor(&resp, "ESTADO"),
            glosa: valor(&resp, "GLOSA"),
            crudo: resp.clone(),
            ..Default::default()
        };
        e.informados = valor(&resp, "INFORMADOS").parse().unwrap_or(0);
        e.aceptados = valor(&resp, "ACEPTADOS").parse().unwrap_or(0);
        e.rechazados = valor(&resp, "RECHAZADOS").parse().unwrap_or(0);
        e.reparos = valor(&resp, "REPAROS").parse().unwrap_or(0);
        if e.estado.is_empty() {
            e.estado = "DESCONOCIDO".into();
        }
        Ok(e)
    }

    /// `consultar_estado_dte`: estado de un documento por sus datos (getEstDte). `fecha_emision`
    /// va como YYYYMMDD.
    #[allow(clippy::too_many_arguments)]
    pub fn estado_dte(
        &mut self,
        rut_emisor: &str,
        dv_emisor: &str,
        tipo: i32,
        folio: i32,
        fecha_emision: &str,
        monto_total: i64,
        rut_receptor: &str,
        dv_receptor: &str,
    ) -> Result<Estado, Error> {
        let tok = self.token()?;
        let resp = self.soap(
            "/DTEWS/services/wsDTECorreo",
            &format!("<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<soapenv:Envelope xmlns:soapenv=\"http://schemas.xmlsoap.org/soap/envelope/\">\n  <soapenv:Body>\n    <getEstDte>\n      <RutEmisor>{rut_emisor}</RutEmisor>\n      <DvEmisor>{dv_emisor}</DvEmisor>\n      <TipoDte>{tipo}</TipoDte>\n      <FolioDte>{folio}</FolioDte>\n      <FechaEmisionDte>{fecha_emision}</FechaEmisionDte>\n      <MontoDte>{monto_total}</MontoDte>\n      <RutReceptor>{rut_receptor}</RutReceptor>\n      <DvReceptor>{dv_receptor}</DvReceptor>\n      <Token>{tok}</Token>\n    </getEstDte>\n  </soapenv:Body>\n</soapenv:Envelope>"),
        )?;
        let mut e = Estado {
            estado: valor(&resp, "ESTADO"),
            glosa: valor(&resp, "GLOSA"),
            crudo: resp.clone(),
            ..Default::default()
        };
        if e.estado.is_empty() {
            e.estado = valor(&resp, "estado");
            e.glosa = valor(&resp, "glosa");
        }
        Ok(e)
    }
}
