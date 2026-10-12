//! `core/sii_portal.py`: el PORTAL web del SII (cvc_cgi/dte) para timbraje y folios,
//! autenticado por certificado digital (mutual-TLS contra herculesr CAutInicio.cgi) o por
//! RUT + clave. Scraping por HTTP puro, sin navegador. Las páginas se parsean con funciones
//! puras (`parsear_*`), medidas contra Python con `tests/dorado/portal/`. Transcripción de
//! `nucleo/portal` (Go).

pub mod onboarding;

use crate::htmlent::unescape;
use crate::sii::http::{ejecutar, ejecutar_get, Respuesta};
use regex::Regex;
use std::collections::BTreeMap;
use std::sync::OnceLock;
use std::time::Duration;

pub const USER_AGENT: &str = "Mozilla/5.0 (compatible; DTE-Portal/1.0)";
const URL_AUTH_CERT: &str = "https://herculesr.sii.cl/cgi_AUT2000/CAutInicio.cgi";
const URL_AUTH_CLAVE: &str = "https://zeusr.sii.cl/cgi_AUT2000/CAutInicio.cgi";
pub const BASE_CERTIFICACION: &str = "https://maullin.sii.cl/cvc_cgi/dte";
pub const BASE_PRODUCCION: &str = "https://palena.sii.cl/cvc_cgi/dte";
const URL_SEL_EMPRESA: &str = "https://www1.sii.cl/cgi-bin/Portal001/mipeSelEmpresa.cgi";

/// La base del portal para un ambiente.
pub fn base_de(ambiente: &str) -> &'static str {
    if ambiente == "produccion" {
        BASE_PRODUCCION
    } else {
        BASE_CERTIFICACION
    }
}

fn re(cache: &'static OnceLock<Regex>, pat: &str) -> &'static Regex {
    cache.get_or_init(|| Regex::new(pat).expect("regex"))
}

static RE_TAGS: OnceLock<Regex> = OnceLock::new();
static RE_BLANCOS: OnceLock<Regex> = OnceLock::new();

/// `_texto`: HTML → texto plano colapsado.
pub fn texto(h: &str) -> String {
    let sin = re(&RE_TAGS, r"<[^>]+>").replace_all(h, " ");
    re(&RE_BLANCOS, r"\s+").replace_all(&sin, " ").into_owned()
}

/// Un rango de folios autorizado (timbraje) para un tipo.
#[derive(Debug, Clone, Default, PartialEq, serde::Serialize)]
pub struct RangoFolios {
    pub tipo_dte: i32,
    pub folio_desde: i64,
    pub folio_hasta: i64,
    pub cantidad: i64,
    pub dia: String,
    pub mes: String,
    pub ano: String,
    pub mandatario: String,
}

impl RangoFolios {
    pub fn fecha(&self) -> String {
        format!("{}-{}-{}", self.dia, self.mes, self.ano)
    }
}

#[derive(Debug, Clone, Default, PartialEq, serde::Serialize)]
pub struct ResultadoAnulacion {
    pub ok: bool,
    pub mensaje: String,
    pub folio_desde: i64,
    pub folio_hasta: i64,
}

/// Un tipo de DTE que un contribuyente está autorizado a emitir.
#[derive(Debug, Clone, Default, PartialEq, serde::Serialize)]
pub struct DocumentoAutorizado {
    pub codigo: i32,
    pub descripcion: String,
    pub autorizado_desde: String,
    pub desautorizado_desde: String,
}

/// Resumen de autorización DTE (consulta pública ee_empresa_rut).
#[derive(Debug, Clone, Default, PartialEq, serde::Serialize)]
pub struct EmpresaAutorizadaDTE {
    pub rut: String,
    pub razon_social: String,
    pub nro_resolucion: String,
    pub fecha_resolucion: String,
    pub direccion_regional: String,
    pub documentos: Vec<DocumentoAutorizado>,
}

impl EmpresaAutorizadaDTE {
    pub fn autoriza(&self, tipo: i32) -> bool {
        self.documentos
            .iter()
            .find(|d| d.codigo == tipo)
            .map(|d| d.desautorizado_desde.is_empty())
            .unwrap_or(false)
    }
}

/// Lo que ad_empresa2 muestra del software de emisión registrado.
#[derive(Debug, Clone, Default, PartialEq, serde::Serialize)]
pub struct DatosSoftware {
    pub software: String,
    pub resolucion: String,
    pub fecha_resolucion: String,
    pub mail_admin: String,
    /// SII = sistema gratuito
    pub propio: bool,
    /// resolución "0" = certificación sin finalizar
    pub certificado: bool,
}

#[derive(Debug, Clone, Default, PartialEq, serde::Serialize)]
pub struct Empresa {
    pub rut: String,
    pub razon_social: String,
}

/// `situacion_folios[tipo]`.
#[derive(Debug, Clone, Copy, Default, PartialEq, serde::Serialize)]
pub struct SituacionTipo {
    pub bloqueado: bool,
    pub puede_timbrar: bool,
}

pub fn separar_rut(rut: &str) -> (String, String) {
    let r = rut.replace('.', "");
    match r.split_once('-') {
        Some((n, dv)) => (n.to_string(), dv.to_string()),
        None => (r, String::new()),
    }
}

// ---------------------------------------------------------------- timbrajes

static RE_TIMBRAJE: OnceLock<Regex> = OnceLock::new();

/// El parseo de `consultar_timbrajes` sobre el texto plano. (Python usa un lookahead; aquí el
/// terminador se captura y la búsqueda sigue desde él.)
pub fn parsear_timbrajes(h: &str, tipo: i32) -> Vec<RangoFolios> {
    let p = texto(h);
    let rx = re(
        &RE_TIMBRAJE,
        r"(\d{2})-(\d{2})-(\d{4})\s+(\d+)\s+(\d+)\s+(\d+)\s+([A-ZÑÁÉÍÓÚ ]+?)(\d{2}-\d{2}-\d{4}|Anterior|Siguiente|$)",
    );
    let mut rangos = Vec::new();
    let mut pos = 0;
    while pos <= p.len() {
        let Some(m) = rx.captures(&p[pos..]) else {
            break;
        };
        let g = |i: usize| m.get(i).map(|x| x.as_str()).unwrap_or("");
        rangos.push(RangoFolios {
            tipo_dte: tipo,
            folio_desde: g(5).parse().unwrap_or(0),
            folio_hasta: g(6).parse().unwrap_or(0),
            cantidad: g(4).parse().unwrap_or(0),
            dia: g(1).into(),
            mes: g(2).into(),
            ano: g(3).into(),
            mandatario: g(7).trim().to_string(),
        });
        // seguir desde el terminador (no consumido, como el lookahead)
        let term = m.get(8).unwrap();
        if term.start() == term.end() {
            break;
        }
        pos += term.start();
    }
    let mut vistos = std::collections::HashSet::new();
    let mut out: Vec<RangoFolios> = rangos
        .into_iter()
        .filter(|r| vistos.insert((r.folio_desde, r.folio_hasta)))
        .collect();
    out.sort_by_key(|r| r.folio_desde);
    out
}

// ------------------------------------------------------ empresa autorizada

static RE_DOC_AUTORIZADO: OnceLock<Regex> = OnceLock::new();

/// El parseo de `consultar_empresa_autorizada` (`None` si no está autorizada). Los rótulos se
/// buscan con las mismas expresiones (y sus alternancias) que Python.
pub fn parsear_empresa_autorizada(h: &str, rut: &str) -> Option<EmpresaAutorizadaDTE> {
    let (n, dv) = separar_rut(rut);
    let p = unescape(&texto(h));
    if !p.to_lowercase().contains("autorizada la emisi") {
        return None;
    }
    let campo = |rotulo: &str, sig: &str| -> String {
        let rx = Regex::new(&format!(r"{rotulo}\s+(.+?)\s+{sig}")).expect("regex");
        rx.captures(&p)
            .and_then(|m| m.get(1))
            .map(|x| x.as_str().trim().to_string())
            .unwrap_or_default()
    };
    let razon = campo("Nombres", "N°|Nro|Resoluci");
    let nrores = campo(r"N°?\s*Resoluci[oó]n", "Fecha");
    let fchres = campo(r"Fecha\s+Resoluci[oó]n", "Direcci");
    let dirreg = campo(r"Direcci[oó]n\s+Regional", "El contribuyente|autorizada");
    let seg: &str = match p.to_lowercase().find("siguientes documentos") {
        Some(i) => &p[i..],
        None => {
            // find() == -1 → p[-1:] (el último carácter)
            let ult = p.char_indices().next_back().map(|(i, _)| i).unwrap_or(0);
            &p[ult..]
        }
    };
    let rx = re(
        &RE_DOC_AUTORIZADO,
        r#"\b(\d{2,3})\s+([A-ZÑ][A-ZÑ0-9 ./'"]+?)\s+(\d{2}-\d{2}-\d{4})\s*(\d{2}-\d{2}-\d{4})?"#,
    );
    let documentos = rx
        .captures_iter(seg)
        .map(|m| DocumentoAutorizado {
            codigo: m[1].parse().unwrap_or(0),
            descripcion: m[2].trim().to_string(),
            autorizado_desde: m[3].to_string(),
            desautorizado_desde: m.get(4).map(|x| x.as_str().to_string()).unwrap_or_default(),
        })
        .collect();
    Some(EmpresaAutorizadaDTE {
        rut: format!("{n}-{dv}"),
        razon_social: razon,
        nro_resolucion: nrores,
        fecha_resolucion: fchres,
        direccion_regional: dirreg,
        documentos,
    })
}

// ------------------------------------------------------------- software

const RE_RESOL: &str = r"Resoluci(?:&oacute;|[oó])n";

fn valor_etiqueta(h: &str, label: &str) -> String {
    let rx = Regex::new(&format!(r"(?i)<font[^>]*>\s*{label}[^<]*</font>\s*</td>\s*<td[^>]*>\s*<font[^>]*>\s*(?:&nbsp;)?\s*([^<]*?)\s*</font>")).expect("regex");
    rx.captures(h)
        .map(|m| unescape(m[1].trim()))
        .unwrap_or_default()
}

/// El parseo de `datos_software` (ad_empresa2).
pub fn parsear_datos_software(h: &str) -> DatosSoftware {
    let sw = valor_etiqueta(h, r"Nombre del Software \(\*\)");
    let res = valor_etiqueta(h, RE_RESOL);
    DatosSoftware {
        propio: !sw.is_empty() && sw.to_uppercase() != "SII",
        certificado: !res.is_empty() && res != "0",
        fecha_resolucion: valor_etiqueta(h, &format!("Fecha {RE_RESOL}")),
        mail_admin: valor_etiqueta(h, "Mail Contacto"),
        software: sw,
        resolucion: res,
    }
}

// ------------------------------------------------------ empresas asociadas

static RE_OPTION: OnceLock<Regex> = OnceLock::new();
static RE_RUT_EXACTO: OnceLock<Regex> = OnceLock::new();
static RE_COLA_RUT: OnceLock<Regex> = OnceLock::new();

/// El parseo de `empresas_asociadas` (mipeSelEmpresa).
pub fn parsear_empresas_asociadas(h: &str) -> Vec<Empresa> {
    let rx = re(
        &RE_OPTION,
        r#"(?i)<option[^>]*value="?([\dkK.\-]+)"?[^>]*>([^<]+)"#,
    );
    let exacto = re(&RE_RUT_EXACTO, r"^\d{7,8}-[\dkK]$");
    let cola = re(&RE_COLA_RUT, r"[\s,]*\d[\d.\-kK]*\s*$");
    rx.captures_iter(h)
        .filter_map(|m| {
            let rut = m[1].trim().to_string();
            if !exacto.is_match(&rut) {
                return None;
            }
            let razon = cola
                .replace(&m[2], "")
                .trim()
                .trim_end_matches(',')
                .trim()
                .to_string();
            Some(Empresa {
                rut,
                razon_social: razon,
            })
        })
        .collect()
}

// ------------------------------------------------------------- anulables

static RE_FORMS: OnceLock<Regex> = OnceLock::new();
static RE_INPUT_NV: OnceLock<Regex> = OnceLock::new();

/// El parseo de `listar_anulables` (af_anular2).
pub fn parsear_anulables(h: &str, tipo: i32) -> Vec<RangoFolios> {
    let forms = re(&RE_FORMS, r"(?is)<form\b.*?</form>");
    let inputs = re(
        &RE_INPUT_NV,
        r#"(?i)<input[^>]*name=["']?(\w+)["']?[^>]*?value=["']?([^"'>]*)"#,
    );
    let mut out: Vec<RangoFolios> = forms
        .find_iter(h)
        .filter_map(|f| {
            let d: BTreeMap<String, String> = inputs
                .captures_iter(f.as_str())
                .map(|m| (m[1].to_string(), m[2].to_string()))
                .collect();
            let (ini, fin) = (d.get("FOLIO_INI")?, d.get("FOLIO_FIN")?);
            let v = |k: &str| d.get(k).cloned().unwrap_or_default();
            Some(RangoFolios {
                tipo_dte: tipo,
                folio_desde: ini.parse().unwrap_or(0),
                folio_hasta: fin.parse().unwrap_or(0),
                cantidad: v("CANT_DOCTOS").parse().unwrap_or(0),
                dia: v("DIA"),
                mes: v("MES"),
                ano: v("ANO"),
                mandatario: String::new(),
            })
        })
        .collect();
    out.sort_by_key(|r| r.folio_desde);
    out
}

/// La lectura de la respuesta de af_anular.
pub fn interpretar_anulacion(h: &str, desde: i64, hasta: i64) -> ResultadoAnulacion {
    let p = texto(h).to_lowercase();
    let (ok, mensaje) = if p.contains("ha autorizado la anulaci") {
        (true, "Anulación autorizada por el SII")
    } else if p.contains("recepcionado") {
        (false, "Al menos un folio fue recepcionado (no anulable)")
    } else if p.contains("anulado anteriormente") {
        (false, "El rango ya fue anulado anteriormente")
    } else {
        (false, "Respuesta no reconocida del SII")
    };
    ResultadoAnulacion {
        ok,
        mensaje: mensaje.into(),
        folio_desde: desde,
        folio_hasta: hasta,
    }
}

// ------------------------------------------------------ situación de folios

pub const TIPOS_SITUACION: [i32; 9] = [33, 34, 39, 41, 43, 46, 52, 56, 61];

/// ¿La página dice NO SE AUTORIZA?
pub fn bloqueado(h: &str) -> bool {
    texto(h).to_uppercase().contains("NO SE AUTORIZA")
}

// ------------------------------------------------------ solicitar/generar CAF

static RE_INPUT_ATTRS: OnceLock<Regex> = OnceLock::new();
static RE_NOMBRE: OnceLock<Regex> = OnceLock::new();
static RE_VALOR: OnceLock<Regex> = OnceLock::new();

/// `_campos_form`: {name: value} de los `<input>` del `<form>` cuyo action contiene el texto
/// (`None` si no hay tal form).
pub fn campos_form(h: &str, action_contiene: &str) -> Option<BTreeMap<String, String>> {
    let rx = Regex::new(&format!(
        r"(?is)<form\b[^>]*{}[^>]*>(.*?)</form>",
        regex::escape(action_contiene)
    ))
    .expect("regex");
    let m = rx.captures(h)?;
    let attrs = re(&RE_INPUT_ATTRS, r"(?i)<input\b([^>]*)>");
    let nombre = re(&RE_NOMBRE, r#"name=["']?(\w+)"#);
    let valor = re(&RE_VALOR, r#"value=["']?([^"'>]*)"#);
    let mut campos = BTreeMap::new();
    for im in attrs.captures_iter(&m[1]) {
        let Some(nm) = nombre.captures(&im[1]) else {
            continue;
        };
        let v = valor
            .captures(&im[1])
            .map(|x| x[1].to_string())
            .unwrap_or_default();
        campos.insert(nm[1].to_string(), v);
    }
    Some(campos)
}

/// El `info` de `solicitar_folios`.
#[derive(Debug, Clone, Default, PartialEq, serde::Serialize)]
pub struct InfoSolicitud {
    #[serde(skip_serializing_if = "std::ops::Not::not")]
    pub rate_limited: bool,
    #[serde(skip_serializing_if = "es_cero")]
    pub solicitados_en_sesion: i64,
    #[serde(skip_serializing_if = "es_cero")]
    pub max: i64,
    pub bloqueado: bool,
    #[serde(skip_serializing_if = "String::is_empty")]
    pub mensaje: String,
    #[serde(skip_serializing_if = "String::is_empty")]
    pub error: String,
    #[serde(skip_serializing_if = "String::is_empty")]
    pub folio: String,
    #[serde(skip_serializing_if = "es_cero")]
    pub folio_desde: i64,
    #[serde(skip_serializing_if = "es_cero")]
    pub folio_hasta: i64,
    #[serde(skip_serializing_if = "es_cero")]
    pub caf_bytes: i64,
}

fn es_cero(v: &i64) -> bool {
    *v == 0
}

// ---------------------------------------------------------------- cliente

/// `PortalSII`: sesión por cookies (se mandan a todos los hosts, como Python).
pub struct Cliente {
    pub base: String,
    pub max_folios_por_tipo: i64,
    pub cookies: BTreeMap<String, String>,
    pub rut_sesion: String,
    agente: ureq::Agent,
    con_cert: bool,
    solicitudes: BTreeMap<String, i64>,
}

/// `resp.text` de httpx: el portal responde en ISO-8859-1 (lo diga o no el Content-Type), así
/// que los bytes que no sean UTF-8 válido se leen como Latin-1. Sin esto, `N°` y las tildes de
/// las páginas no calzan con las expresiones regulares.
pub fn decodificar(b: &[u8], content_type: &str) -> String {
    let ct = content_type.to_lowercase();
    let latin = ct.contains("iso-8859-1") || ct.contains("windows-1252") || ct.contains("latin");
    if !latin {
        if let Ok(s) = std::str::from_utf8(b) {
            return s.to_string();
        }
        if ct.contains("utf-8") {
            return String::from_utf8_lossy(b).into_owned();
        }
    }
    b.iter().map(|&c| c as char).collect()
}

fn form_urlencoded(datos: &[(String, String)]) -> Vec<u8> {
    let mut out = String::new();
    for (i, (k, v)) in datos.iter().enumerate() {
        if i > 0 {
            out.push('&');
        }
        out.push_str(&url_encode(k));
        out.push('=');
        out.push_str(&url_encode(v));
    }
    out.into_bytes()
}

/// `url.Values.Encode()`: percent-encoding sobre UTF-8, espacio como `+`.
fn url_encode(s: &str) -> String {
    const HEX: &[u8; 16] = b"0123456789ABCDEF";
    let mut out = String::with_capacity(s.len());
    for &c in s.as_bytes() {
        match c {
            b'a'..=b'z' | b'A'..=b'Z' | b'0'..=b'9' | b'-' | b'_' | b'.' | b'~' => {
                out.push(c as char)
            }
            b' ' => out.push('+'),
            _ => {
                out.push('%');
                out.push(HEX[(c >> 4) as usize] as char);
                out.push(HEX[(c & 15) as usize] as char);
            }
        }
    }
    out
}

impl Cliente {
    /// Crea el cliente; `cert_pem`/`key_pem` pueden ir vacíos si solo se usa clave.
    pub fn nuevo(cert_pem: &[u8], key_pem: &[u8], base: &str) -> Result<Cliente, String> {
        let base = if base.is_empty() {
            BASE_CERTIFICACION
        } else {
            base
        };
        let mut config = ureq::Agent::config_builder()
            .timeout_global(Some(Duration::from_secs(40)))
            .http_status_as_error(false)
            .max_redirects(10)
            .max_redirects_will_error(false);
        let con_cert = !cert_pem.is_empty() && !key_pem.is_empty();
        if con_cert {
            let cert = ureq::tls::Certificate::from_pem(cert_pem)
                .map_err(|e| format!("certificado PEM: {e}"))?;
            let key =
                ureq::tls::PrivateKey::from_pem(key_pem).map_err(|e| format!("clave PEM: {e}"))?;
            let tls = ureq::tls::TlsConfig::builder()
                .client_cert(Some(ureq::tls::ClientCert::new_with_certs(&[cert], key)))
                .build();
            config = config.tls_config(tls);
        }
        Ok(Cliente {
            base: base.to_string(),
            max_folios_por_tipo: 3,
            cookies: BTreeMap::new(),
            rut_sesion: String::new(),
            agente: config.build().into(),
            con_cert,
            solicitudes: BTreeMap::new(),
        })
    }

    /// La petición con reintentos ante 429/5xx o red (ClienteReintentos) y absorbe las cookies
    /// que lleguen (de cualquier host: las de .sii.cl sirven en maullin, palena y www1).
    fn pedir(
        &mut self,
        metodo: &str,
        u: &str,
        form: Option<&[(String, String)]>,
    ) -> Result<(u16, Vec<u8>), String> {
        let mut ultimo = String::new();
        for intento in 0..4 {
            let cookie = if self.cookies.is_empty() {
                None
            } else {
                Some(
                    self.cookies
                        .iter()
                        .map(|(k, v)| format!("{k}={v}"))
                        .collect::<Vec<_>>()
                        .join("; "),
                )
            };
            let r: Result<Respuesta, String> = if metodo == "POST" {
                let cuerpo = form.map(form_urlencoded).unwrap_or_default();
                let mut req = self.agente.post(u).header("User-Agent", USER_AGENT);
                if form.is_some() {
                    req = req.header("Content-Type", "application/x-www-form-urlencoded");
                }
                if let Some(c) = &cookie {
                    req = req.header("Cookie", c);
                }
                ejecutar(req, &cuerpo)
            } else {
                let mut req = self.agente.get(u).header("User-Agent", USER_AGENT);
                if let Some(c) = &cookie {
                    req = req.header("Cookie", c);
                }
                ejecutar_get(req)
            };
            match r {
                Err(e) => ultimo = e,
                Ok(r) => {
                    let ct = r.header("Content-Type").unwrap_or("").to_string();
                    for (k, v) in &r.headers {
                        if k.eq_ignore_ascii_case("set-cookie") {
                            if let Some((nombre, valor)) =
                                v.split(';').next().and_then(|p| p.split_once('='))
                            {
                                self.cookies
                                    .insert(nombre.trim().to_string(), valor.trim().to_string());
                            }
                        }
                    }
                    if r.status != 429 && r.status < 500 {
                        return Ok((r.status, decodificar(&r.cuerpo, &ct).into_bytes()));
                    }
                    ultimo = format!("HTTP {} en {u}", r.status);
                }
            }
            if intento < 3 {
                std::thread::sleep(Duration::from_millis(500 * (1 << intento)));
            }
        }
        Err(ultimo)
    }

    fn post(&mut self, u: &str, datos: &[(&str, &str)]) -> Result<String, String> {
        let f: Vec<(String, String)> = datos
            .iter()
            .map(|(k, v)| (k.to_string(), v.to_string()))
            .collect();
        let (_, b) = self.pedir("POST", u, Some(&f))?;
        Ok(String::from_utf8_lossy(&b).into_owned())
    }

    /// `autenticar()`: login por certificado (mutual-TLS) → cookies de sesión.
    pub fn autenticar(&mut self, referencia: &str) -> Result<BTreeMap<String, String>, String> {
        if !self.con_cert {
            return Err("Se requiere certificado (cert_pem/key_pem) para autenticar por firma. Usa AutenticarConClave() si sólo tienes RUT+clave.".into());
        }
        let referencia = if referencia.is_empty() {
            format!("{}/of_solicita_folios", self.base)
        } else {
            referencia.to_string()
        };
        self.post(URL_AUTH_CERT, &[("referencia", &referencia)])?;
        self.rut_sesion = self.cookies.get("RUT_NS").cloned().unwrap_or_default();
        Ok(self.cookies.clone())
    }

    /// `autenticar_con_clave()`: RUT + clave tributaria (Mi SII).
    pub fn autenticar_con_clave(
        &mut self,
        rut: &str,
        clave: &str,
        referencia: &str,
    ) -> Result<BTreeMap<String, String>, String> {
        let rut = rut.replace('.', "");
        let (n, dv) = rut
            .split_once('-')
            .ok_or_else(|| format!("RUT sin DV: {rut:?}"))?;
        let referencia = if referencia.is_empty() {
            "https://misiir.sii.cl/cgi_misii/siihome.cgi"
        } else {
            referencia
        };
        self.post(
            URL_AUTH_CLAVE,
            &[
                ("rut", n),
                ("dv", dv),
                ("rutcntr", &rut),
                ("clave", clave),
                ("referencia", referencia),
                ("411", ""),
            ],
        )?;
        self.rut_sesion = self.cookies.get("RUT_NS").cloned().unwrap_or_default();
        if self.rut_sesion.is_empty() {
            self.rut_sesion = n.to_string();
        }
        Ok(self.cookies.clone())
    }

    fn sesion(&mut self) -> Result<(), String> {
        if self.cookies.is_empty() {
            self.autenticar("")?;
        }
        Ok(())
    }

    /// `consultar_timbrajes`: historial de rangos por tipo (of_consulta2_folio).
    pub fn consultar_timbrajes(
        &mut self,
        rut: &str,
        tipo: i32,
    ) -> Result<Vec<RangoFolios>, String> {
        self.sesion()?;
        let (n, dv) = separar_rut(rut);
        let h = self.post(
            &format!("{}/of_consulta2_folio", self.base),
            &[
                ("RUT_EMP", &n),
                ("DV_EMP", &dv),
                ("PAGINA", "1"),
                ("COD_DOCTO", &tipo.to_string()),
                ("ACEPTAR", "Consultar"),
            ],
        )?;
        Ok(parsear_timbrajes(&h, tipo))
    }

    /// `consultar_empresa_autorizada` (PÚBLICA, sin sesión).
    pub fn consultar_empresa_autorizada(
        &mut self,
        rut: &str,
        base: &str,
    ) -> Result<Option<EmpresaAutorizadaDTE>, String> {
        let base = if base.is_empty() {
            self.base.clone()
        } else {
            base.to_string()
        };
        let (n, dv) = separar_rut(rut);
        let mut publico = Cliente::nuevo(&[], &[], &base)?;
        let h = publico.post(
            &format!("{base}/ee_empresa_rut"),
            &[
                ("CNSLT", "R"),
                ("RUT_EMP", &n),
                ("DV_EMP", &dv),
                ("ACEPTAR", "Consultar"),
            ],
        )?;
        Ok(parsear_empresa_autorizada(&h, rut))
    }

    /// `datos_software`: requiere sesión; `base` permite otro ambiente con las mismas cookies.
    pub fn datos_software_de(&mut self, rut: &str, base: &str) -> Result<DatosSoftware, String> {
        self.sesion()?;
        let base = if base.is_empty() {
            self.base.clone()
        } else {
            base.to_string()
        };
        let (n, dv) = separar_rut(rut);
        let h = self.post(
            &format!("{base}/ad_empresa2"),
            &[("RUT_EMP", &n), ("DV_EMP", &dv)],
        )?;
        Ok(parsear_datos_software(&h))
    }

    /// Todas las empresas que el titular de la sesión puede operar.
    pub fn empresas_asociadas(&mut self) -> Result<Vec<Empresa>, String> {
        self.sesion()?;
        let (_, b) = self.pedir("GET", URL_SEL_EMPRESA, None)?;
        Ok(parsear_empresas_asociadas(&String::from_utf8_lossy(&b)))
    }

    pub fn listar_anulables(&mut self, rut: &str, tipo: i32) -> Result<Vec<RangoFolios>, String> {
        self.sesion()?;
        let (n, dv) = separar_rut(rut);
        let h = self.post(
            &format!("{}/af_anular2", self.base),
            &[
                ("RUT_EMP", &n),
                ("DV_EMP", &dv),
                ("PAGINA", "1"),
                ("COD_DOCTO", &tipo.to_string()),
                ("ACEPTAR", "Consultar"),
            ],
        )?;
        Ok(parsear_anulables(&h, tipo))
    }

    /// Anula el sub-rango [desde, hasta] (todos NO recepcionados; sesión del mandatario).
    pub fn anular_folios(
        &mut self,
        rut: &str,
        tipo: i32,
        desde: i64,
        hasta: i64,
        motivo: &str,
    ) -> Result<ResultadoAnulacion, String> {
        let motivo = if motivo.is_empty() {
            "Folios no utilizados"
        } else {
            motivo
        };
        let rangos = self.listar_anulables(rut, tipo)?;
        let Some(padre) = rangos
            .iter()
            .find(|r| r.folio_desde <= desde && hasta <= r.folio_hasta)
            .cloned()
        else {
            return Ok(ResultadoAnulacion {
                ok: false,
                mensaje: "No hay rango anulable que contenga esos folios".into(),
                folio_desde: desde,
                folio_hasta: hasta,
            });
        };
        let (n, dv) = separar_rut(rut);
        let t = tipo.to_string();
        let (pd, ph, pc) = (
            padre.folio_desde.to_string(),
            padre.folio_hasta.to_string(),
            padre.cantidad.to_string(),
        );
        self.post(
            &format!("{}/af_anular3", self.base),
            &[
                ("RUT_EMP", &n),
                ("DV_EMP", &dv),
                ("DIA", &padre.dia),
                ("MES", &padre.mes),
                ("ANO", &padre.ano),
                ("COD_DOCTO", &t),
                ("FOLIO_INI", &pd),
                ("FOLIO_FIN", &ph),
                ("CANT_DOCTOS", &pc),
            ],
        )?;
        let (d, h_) = (desde.to_string(), hasta.to_string());
        let h = self.post(
            &format!("{}/af_anular", self.base),
            &[
                ("FOLIO_INI_A", &d),
                ("FOLIO_FIN_A", &h_),
                ("MOTIVO", motivo),
                ("RUT_EMP", &n),
                ("DV_EMP", &dv),
                ("COD_DOCTO", &t),
                ("FOLIO_INI", &pd),
                ("FOLIO_FIN", &ph),
            ],
        )?;
        Ok(interpretar_anulacion(&h, desde, hasta))
    }

    /// Usa el paso de PROCESAMIENTO real (of_solicita_folios_dcto), donde el SII aplica el
    /// control de stock (of_confirma_folio es preview y engaña).
    pub fn situacion_folios(
        &mut self,
        rut: &str,
        tipos: &[i32],
    ) -> Result<BTreeMap<i32, SituacionTipo>, String> {
        self.sesion()?;
        let tipos: Vec<i32> = if tipos.is_empty() {
            TIPOS_SITUACION.to_vec()
        } else {
            tipos.to_vec()
        };
        let (n, dv) = separar_rut(rut);
        let mut out = BTreeMap::new();
        for tp in tipos {
            let h = self.post(
                &format!("{}/of_solicita_folios_dcto", self.base),
                &[
                    ("RUT_EMP", &n),
                    ("DV_EMP", &dv),
                    ("COD_DOCTO", &tp.to_string()),
                    ("FOLIO_INICIAL", ""),
                    ("CANT_DOCTOS", ""),
                ],
            )?;
            let b = bloqueado(&h);
            out.insert(
                tp,
                SituacionTipo {
                    bloqueado: b,
                    puede_timbrar: !b,
                },
            );
        }
        Ok(out)
    }

    /// Solicita, genera y descarga un CAF (100% HTTP). Devuelve `(caf, info)`; `caf` None con la
    /// razón en `info`. Guardarraíles anti-acaparamiento: tope blando por (rut, tipo) por sesión
    /// (`forzar` lo salta) y chequeo previo de bloqueo (`verificar_bloqueo`).
    pub fn solicitar_folios(
        &mut self,
        rut: &str,
        tipo: i32,
        cantidad: i64,
        verificar_bloqueo: bool,
        forzar: bool,
    ) -> Result<(Option<Vec<u8>>, InfoSolicitud), String> {
        let cantidad = cantidad.max(1);
        let clave = format!("{rut}/{tipo}");
        let ya = *self.solicitudes.get(&clave).unwrap_or(&0);
        if !forzar && ya + cantidad > self.max_folios_por_tipo {
            return Ok((
                None,
                InfoSolicitud {
                    rate_limited: true,
                    solicitados_en_sesion: ya,
                    max: self.max_folios_por_tipo,
                    mensaje: format!("Tope de {} folios T{tipo}/sesión alcanzado. El SII bloquea el timbraje si acumulas folios sin usar: emítelos o anúlalos antes de pedir más (o usa forzar=True bajo tu responsabilidad).", self.max_folios_por_tipo),
                    ..Default::default()
                },
            ));
        }
        if verificar_bloqueo {
            let sit = self.situacion_folios(rut, &[tipo])?;
            if sit.get(&tipo).map(|s| s.bloqueado).unwrap_or(false) {
                return Ok((None, InfoSolicitud { bloqueado: true, mensaje: format!("El SII ya bloquea el timbraje T{tipo} (anti-acaparamiento). Emite o anula folios sin usar de ese tipo antes de reintentar."), ..Default::default() }));
            }
        }
        self.sesion()?;
        let (n, dv) = separar_rut(rut);
        let t = tipo.to_string();
        let cant = cantidad.to_string();
        let mut conf = self.post(
            &format!("{}/of_confirma_folio", self.base),
            &[
                ("RUT_EMP", &n),
                ("DV_EMP", &dv),
                ("COD_DOCTO", &t),
                ("CANT_DOCTOS", &cant),
                ("FOLIO_INICIAL", ""),
                ("AFECTO_IVA", ""),
                ("ANOTACION", ""),
                ("CON_CREDITO", ""),
                ("CON_AJUSTE", ""),
                ("FACTOR", ""),
            ],
        )?;
        let mut campos = campos_form(&conf, "of_genera_folio").unwrap_or_default();
        // BOLETAS (y a veces facturas): paso intermedio "Confirmar Folio Inicial" que postea de
        // nuevo a of_confirma_folio; recién ese responde el form de generación.
        if !campos.contains_key("FOLIO_INI") {
            if let Some(mut inter) = campos_form(&conf, "of_confirma_folio") {
                if !inter
                    .get("FOLIO_INICIAL")
                    .unwrap_or(&String::new())
                    .is_empty()
                    && inter
                        .get("ACEPTAR")
                        .map(|a| a.contains("Confirmar"))
                        .unwrap_or(false)
                {
                    inter
                        .entry("CON_CREDITO".into())
                        .or_insert_with(|| "0".into());
                    inter
                        .entry("CON_AJUSTE".into())
                        .or_insert_with(|| "0".into());
                    let pares: Vec<(&str, &str)> = inter
                        .iter()
                        .map(|(k, v)| (k.as_str(), v.as_str()))
                        .collect();
                    conf = self.post(&format!("{}/of_confirma_folio", self.base), &pares)?;
                    campos = campos_form(&conf, "of_genera_folio").unwrap_or_default();
                }
            }
        }
        if !campos.contains_key("FOLIO_INI") {
            return Ok((
                None,
                InfoSolicitud {
                    bloqueado: bloqueado(&conf),
                    error: "of_confirma_folio no ofreció folio".into(),
                    ..Default::default()
                },
            ));
        }
        // el navegador agrega estos dos; el form del confirma no los expone.
        campos
            .entry("CON_CREDITO".into())
            .or_insert_with(|| "0".into());
        campos
            .entry("CON_AJUSTE".into())
            .or_insert_with(|| "0".into());
        let pares: Vec<(&str, &str)> = campos
            .iter()
            .map(|(k, v)| (k.as_str(), v.as_str()))
            .collect();
        let gen = self.post(&format!("{}/of_genera_folio", self.base), &pares)?;
        let folio_ini = campos.get("FOLIO_INI").cloned().unwrap_or_default();
        if bloqueado(&gen) {
            return Ok((
                None,
                InfoSolicitud {
                    bloqueado: true,
                    folio: folio_ini,
                    ..Default::default()
                },
            ));
        }
        let Some(arch) = campos_form(&gen, "of_genera_archivo") else {
            return Ok((
                None,
                InfoSolicitud {
                    error: "of_genera_folio no devolvió el form de descarga".into(),
                    folio: folio_ini,
                    ..Default::default()
                },
            ));
        };
        let f: Vec<(String, String)> = arch.iter().map(|(k, v)| (k.clone(), v.clone())).collect();
        let (_, caf) = self.pedir(
            "POST",
            &format!("{}/of_genera_archivo", self.base),
            Some(&f),
        )?;
        self.solicitudes.insert(clave, ya + cantidad);
        let info = InfoSolicitud {
            folio_desde: arch
                .get("FOLIO_INI")
                .and_then(|x| x.parse().ok())
                .unwrap_or(0),
            folio_hasta: arch
                .get("FOLIO_FIN")
                .and_then(|x| x.parse().ok())
                .unwrap_or(0),
            caf_bytes: caf.len() as i64,
            ..Default::default()
        };
        if !caf.windows(4).any(|w| w == b"<CAF") {
            return Ok((None, info));
        }
        Ok((Some(caf), info))
    }
}

impl onboarding::Lector for Cliente {
    fn consultar_empresa_autorizada(
        &mut self,
        rut: &str,
        base: &str,
    ) -> Result<Option<EmpresaAutorizadaDTE>, String> {
        Cliente::consultar_empresa_autorizada(self, rut, base)
    }
    fn datos_software_de(&mut self, rut: &str, base: &str) -> Result<DatosSoftware, String> {
        Cliente::datos_software_de(self, rut, base)
    }
    fn situacion_folios(
        &mut self,
        rut: &str,
        tipos: &[i32],
    ) -> Result<BTreeMap<i32, SituacionTipo>, String> {
        Cliente::situacion_folios(self, rut, tipos)
    }
    fn empresas_asociadas(&mut self) -> Result<Vec<Empresa>, String> {
        Cliente::empresas_asociadas(self)
    }
}

#[cfg(test)]
mod tests {
    use super::onboarding::*;
    use super::*;
    use serde_json::{json, Map, Value};

    /// Parsers y diagnóstico sobre el mismo HTML sintético y los mismos dobles que
    /// tests/dorado/portal/generar_esperado.py. L15.
    #[test]
    fn paridad_con_python() {
        let base = format!("{}/../tests/dorado/portal", env!("CARGO_MANIFEST_DIR"));
        let Ok(raw) = std::fs::read(format!("{base}/html.json")) else {
            return;
        };
        let h: Map<String, Value> = serde_json::from_slice(&raw).unwrap();
        let hs = |k: &str| h.get(k).and_then(|v| v.as_str()).unwrap_or("").to_string();
        let esp: Map<String, Value> =
            serde_json::from_slice(&std::fs::read(format!("{base}/esperado.json")).unwrap())
                .unwrap();
        let mut got: Map<String, Value> = Map::new();
        got.insert(
            "empresa_autorizada".into(),
            json!(parsear_empresa_autorizada(
                &hs("ee_empresa_rut"),
                "77.777.777-7"
            )),
        );
        got.insert(
            "empresa_no_autorizada".into(),
            json!(parsear_empresa_autorizada(
                &hs("ee_empresa_rut_no"),
                "77777777-7"
            )),
        );
        if h.contains_key("ee_empresa_rut_real") {
            got.insert(
                "empresa_autorizada_real".into(),
                json!(parsear_empresa_autorizada(
                    &hs("ee_empresa_rut_real"),
                    "77777777-7"
                )),
            );
        }
        got.insert(
            "software".into(),
            json!(parsear_datos_software(&hs("ad_empresa2"))),
        );
        got.insert(
            "software_sii".into(),
            json!(parsear_datos_software(&hs("ad_empresa2_sii"))),
        );
        got.insert(
            "empresas_asociadas".into(),
            json!(parsear_empresas_asociadas(&hs("mipeSelEmpresa"))),
        );
        got.insert(
            "timbrajes".into(),
            json!(parsear_timbrajes(&hs("of_consulta2_folio"), 33)),
        );
        got.insert(
            "anulables".into(),
            json!(parsear_anulables(&hs("af_anular2"), 33)),
        );
        let mut anul = Map::new();
        for k in [
            "af_anular_ok",
            "af_anular_recep",
            "af_anular_antes",
            "af_anular_raro",
        ] {
            anul.insert(k.into(), json!(interpretar_anulacion(&hs(k), 7, 9)));
        }
        anul.insert(
            "sin_padre".into(),
            json!(ResultadoAnulacion {
                ok: false,
                mensaje: "No hay rango anulable que contenga esos folios".into(),
                folio_desde: 100,
                folio_hasta: 101
            }),
        );
        got.insert("anulacion".into(), Value::Object(anul));
        let b = bloqueado(&hs("bloqueado"));
        got.insert("situacion_bloqueada".into(), json!({"33": SituacionTipo{bloqueado: b, puede_timbrar: !b}, "61": SituacionTipo{bloqueado: b, puede_timbrar: !b}}));
        let l = bloqueado(&hs("libre"));
        got.insert(
            "situacion_libre".into(),
            json!({"39": SituacionTipo{bloqueado: l, puede_timbrar: !l}}),
        );
        got.insert(
            "campos_form".into(),
            json!(campos_form(&hs("of_confirma_folio"), "of_genera_folio")),
        );
        got.insert(
            "campos_form_none".into(),
            json!(campos_form(&hs("of_confirma_folio"), "no_existe")),
        );

        // onboarding con dobles
        let sw = |nombre: &str, res: &str| DatosSoftware {
            software: nombre.into(),
            resolucion: res.into(),
            propio: !nombre.is_empty() && nombre != "SII" && nombre != "sii",
            certificado: !res.is_empty() && res != "0",
            ..Default::default()
        };
        let doc = |c: i32, d: &str, a: &str, de: &str| DocumentoAutorizado {
            codigo: c,
            descripcion: d.into(),
            autorizado_desde: a.into(),
            desautorizado_desde: de.into(),
        };
        let emp_full = EmpresaAutorizadaDTE {
            rut: "77777777-7".into(),
            razon_social: "EMPRESA DEMO SPA".into(),
            nro_resolucion: "80".into(),
            fecha_resolucion: "22-08-2014".into(),
            direccion_regional: "SANTIAGO".into(),
            documentos: vec![
                doc(33, "FACTURA ELECTRONICA", "01-02-2026", ""),
                doc(39, "BOLETA ELECTRONICA", "05-02-2026", ""),
                doc(
                    61,
                    "NOTA DE CREDITO ELECTRONICA",
                    "01-02-2026",
                    "15-03-2026",
                ),
            ],
        };
        let emp_exenta = EmpresaAutorizadaDTE {
            documentos: vec![
                doc(
                    34,
                    "FACTURA NO AFECTA O EXENTA ELECTRONICA",
                    "01-02-2026",
                    "",
                ),
                doc(41, "BOLETA EXENTA ELECTRONICA", "05-02-2026", ""),
            ],
            ..emp_full.clone()
        };
        let bloq = |ts: &[i32]| {
            ts.iter()
                .map(|t| (*t, true))
                .collect::<BTreeMap<i32, bool>>()
        };
        let casos: Vec<(&str, Doble)> = vec![
            (
                "sin_propio_exenta",
                Doble {
                    emp: Some(emp_exenta.clone()),
                    prod: sw("SII", "0"),
                    cert: sw("", "0"),
                    bloq: BTreeMap::new(),
                    asociadas: vec![],
                },
            ),
            (
                "externo",
                Doble {
                    emp: Some(emp_full.clone()),
                    prod: sw("Haulmer Facturación", "500"),
                    cert: sw("", "0"),
                    bloq: BTreeMap::new(),
                    asociadas: vec![],
                },
            ),
            (
                "emitiendo_nuestro",
                Doble {
                    emp: Some(emp_full.clone()),
                    prod: sw("DTE Chile v2", "500"),
                    cert: sw("DTE Chile v2", "500"),
                    bloq: BTreeMap::new(),
                    asociadas: vec![],
                },
            ),
            (
                "certificando_bloqueada",
                Doble {
                    emp: Some(emp_full.clone()),
                    prod: sw("SII", "0"),
                    cert: sw("Motor Demo", "0"),
                    bloq: bloq(&[33]),
                    asociadas: vec![],
                },
            ),
            (
                "certificado",
                Doble {
                    emp: Some(emp_full.clone()),
                    prod: sw("SII", "0"),
                    cert: sw("Motor Demo", "77"),
                    bloq: BTreeMap::new(),
                    asociadas: vec![],
                },
            ),
            (
                "desconocida",
                Doble {
                    emp: None,
                    prod: sw("", "0"),
                    cert: sw("", "0"),
                    bloq: bloq(&[61]),
                    asociadas: vec![],
                },
            ),
        ];
        const NOMBRE_SOFTWARE: &str = "DTE Chile, Motor Demo";
        let mut diags = Map::new();
        for (k, mut p) in casos {
            diags.insert(
                k.into(),
                json!(
                    diagnosticar(&mut p, "77777777-7", "Motor Demo", "", NOMBRE_SOFTWARE).unwrap()
                ),
            );
        }
        got.insert("diagnosticos".into(), Value::Object(diags));
        let mut cartera = Doble {
            emp: Some(emp_full.clone()),
            prod: sw("SII", "0"),
            cert: sw("", "0"),
            bloq: BTreeMap::new(),
            asociadas: vec![
                Empresa {
                    rut: "77777777-7".into(),
                    razon_social: "EMPRESA DEMO SPA".into(),
                },
                Empresa {
                    rut: "76111111-6".into(),
                    razon_social: "CLIENTE".into(),
                },
            ],
        };
        got.insert(
            "cartera".into(),
            json!(
                diagnosticar_cartera(&mut cartera, None, "Motor Demo", None, NOMBRE_SOFTWARE)
                    .unwrap()
            ),
        );
        let (e1, l1) = clasificar_software(
            &sw("Otro Soft", "9"),
            &sw("", "0"),
            "Mi Registro",
            NOMBRE_SOFTWARE,
        );
        let (e2, l2) = clasificar_software(
            &sw("mi registro pro", "9"),
            &sw("", "0"),
            "Mi Registro",
            NOMBRE_SOFTWARE,
        );
        let (e3, l3) = clasificar_software(&sw("X", "9"), &sw("", "0"), "", NOMBRE_SOFTWARE);
        got.insert("clasificar".into(), json!({"externo_registrado": [e1, l1], "nuestro_registrado": [e2, l2], "propio_sin_config": [e3, l3]}));

        let mut fallos = Vec::new();
        for (k, esperado) in &esp {
            let g = got.get(k).cloned().unwrap_or(Value::Null);
            if &g != esperado {
                fallos.push(format!("{k} difiere\n  python: {esperado}\n  rust:   {g}"));
            }
        }
        assert!(fallos.is_empty(), "{}", fallos.join("\n"));
    }

    /// El `_Portal` del generador: respuestas fijas.
    struct Doble {
        emp: Option<EmpresaAutorizadaDTE>,
        prod: DatosSoftware,
        cert: DatosSoftware,
        bloq: BTreeMap<i32, bool>,
        asociadas: Vec<Empresa>,
    }

    impl Lector for Doble {
        fn consultar_empresa_autorizada(
            &mut self,
            _rut: &str,
            _base: &str,
        ) -> Result<Option<EmpresaAutorizadaDTE>, String> {
            Ok(self.emp.clone())
        }
        fn datos_software_de(&mut self, _rut: &str, base: &str) -> Result<DatosSoftware, String> {
            Ok(if base == BASE_PRODUCCION {
                self.prod.clone()
            } else {
                self.cert.clone()
            })
        }
        fn situacion_folios(
            &mut self,
            _rut: &str,
            tipos: &[i32],
        ) -> Result<BTreeMap<i32, SituacionTipo>, String> {
            Ok(tipos
                .iter()
                .map(|t| {
                    let b = *self.bloq.get(t).unwrap_or(&false);
                    (
                        *t,
                        SituacionTipo {
                            bloqueado: b,
                            puede_timbrar: !b,
                        },
                    )
                })
                .collect())
        }
        fn empresas_asociadas(&mut self) -> Result<Vec<Empresa>, String> {
            Ok(self.asociadas.clone())
        }
    }
}
