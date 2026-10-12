//! El SII engine del núcleo: la app operando los sistemas del propio SII por la empresa (hoy
//! el portal MIPYME de facturas, `www1.sii.cl/cgi-bin/Portal001`; después eboleta). Réplica de
//! `core/sii_mipyme.py` vía `nucleo/siiengine` (Go), por segmentos (`docs/PLAN-PORT.md`).
//!
//! Segmento 1 (este archivo, `lectura` e `importar`): sesión por clave tributaria, selección de
//! empresa, cierre real de la sesión, historial de emitidos, PDF, XML por firma central, form
//! pre-llenado e importación al almacén. Todo de SOLO LECTURA en el SII: no gasta folios.
//!
//! PRODUCCIÓN: no hay sandbox. Reglas que se heredan de Python: una sesión por corrida y cerrar
//! siempre (tope ~10 por RUT, memoria `sii-cerrar-sesion`); nada se reintenta; las claves nunca
//! viajan por argumento ni se escriben en logs.

pub mod emision;
pub mod evidencia;
pub mod html;
pub mod importar;
pub mod lectura;
pub mod rut;
pub mod schema;

pub use html::{
    codificar_latin1, codificar_utf8, latin1, parsear_form, parsear_form_ordenado, Form, Par,
};
pub use rut::{digito_verificador, formatear_rut, separar_rut, validar_rut};
pub use schema::*;

use crate::sii::http::{ejecutar, ejecutar_get, Respuesta};
use regex::Regex;
use std::collections::BTreeMap;
use std::fmt;
use std::sync::OnceLock;
use std::time::Duration;

pub const BASE: &str = "https://www1.sii.cl/cgi-bin/Portal001";
const URL_LOGIN: &str = "https://zeusr.sii.cl/cgi_AUT2000/CAutInicio.cgi";
/// seguir el 302, si no la sesión sigue viva
const URL_LOGOUT: &str = "https://zeusr.sii.cl/cgi_AUT2000/autTermino.cgi";
const URL_SII_HOME: &str = "https://misiir.sii.cl/cgi_misii/siihome.cgi";
const REFERER_LOGIN: &str = "https://zeusr.sii.cl/AUT2000/InicioAutenticacion/IngresoRutClave.html";
const OPCION_EMISION: &str = "OPCION=34&TIPO=4";

pub const TIPO_FACTURA_EXENTA: i32 = 34;
pub const TIPO_NOTA_CREDITO: i32 = 61;
pub const TIPO_NOTA_DEBITO: i32 = 56;

/// Lo que el JS del portal (signXmlCompatible) inserta antes de `<Documento` al firmar.
pub const COMENTARIO_FIRMA: &str = "<!-- O MacIntel Chrome 154 central VERSION: v20170209 -->";

const UA: &str = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36";
const ACCEPT: &str = "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7";

/// Errores por clase (los de `core/errors.py` que usa el módulo Python).
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Error {
    Validacion(String),
    Autenticacion(String),
    /// el portal rechazó la petición
    Rechazo(String),
    /// portal MIPYME
    Sii(String),
}

impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Error::Validacion(s) => write!(f, "validación: {s}"),
            Error::Autenticacion(s) => write!(f, "autenticación: {s}"),
            Error::Rechazo(s) => write!(f, "el portal rechazó la petición: {s}"),
            Error::Sii(s) => write!(f, "portal MIPYME: {s}"),
        }
    }
}

impl std::error::Error for Error {}

pub type Resultado<T> = Result<T, Error>;

/// Receptor de avisos (lo que Python manda al logger). Nunca lleva claves.
pub type Logger = Box<dyn Fn(&str) + Send + Sync>;

/// Una sesión contra el portal. Patrón: `nuevo` → `iniciar_sesion` → `seleccionar_empresa` →
/// (lecturas) → `cerrar`, siempre.
pub struct Cliente {
    /// sin puntos, con DV
    pub rut_usuario: String,
    /// sin puntos, con DV; vacío hasta `seleccionar_empresa`
    pub empresa: String,
    pub timeout: Duration,
    /// entre páginas del historial y descargas (no martillar el portal)
    pub pausa: Duration,
    /// carpeta base de la evidencia (mipyme_fallidos/); "" = "storage"
    pub raiz_storage: String,
    /// recibe los avisos que Python manda al logger (`None` = silencio). Nunca lleva claves.
    pub log: Option<Logger>,
    /// si está, recibe las páginas crudas de los dry-runs (form.html, preview.html, …): sirven
    /// de fixtures de paridad.
    pub trazas: Option<BTreeMap<String, String>>,
    clave_trib: String,
    clave_cert: String,
    cookies: BTreeMap<String, String>,
    agente: ureq::Agent,
    autenticado: bool,
    menu_html: String,
}

pub(crate) struct RespuestaPortal {
    pub status: u16,
    pub cuerpo: Vec<u8>,
    pub location: String,
}

impl RespuestaPortal {
    pub fn texto(&self) -> String {
        latin1(&self.cuerpo)
    }
    pub fn rechazado(&self) -> bool {
        self.status != 200 || self.cuerpo.windows(16).any(|w| w == b"Request Rejected")
    }
}

#[derive(Default)]
pub(crate) struct Opciones<'a> {
    /// POST form, codificado latin-1 en orden
    pub data: Option<&'a [Par]>,
    /// POST crudo (gana sobre data)
    pub content: Option<&'a [u8]>,
    /// query string
    pub params: Option<&'a [Par]>,
    pub referer: &'a str,
    pub origin: &'a str,
    /// true = navegación de documento; false = XHR
    pub navegacion: bool,
    pub extra: Option<&'a [(&'a str, &'a str)]>,
}

fn re(cache: &'static OnceLock<Regex>, pat: &str) -> &'static Regex {
    cache.get_or_init(|| Regex::new(pat).expect("regex"))
}

impl Cliente {
    /// Valida el RUT y prepara la sesión. La clave del certificado solo hace falta para la firma
    /// central (XML de lo emitido); puede ir vacía para listar e importar PDF.
    pub fn nuevo(
        rut_usuario: &str,
        clave_tributaria: &str,
        clave_certificado: &str,
    ) -> Resultado<Cliente> {
        if !validar_rut(rut_usuario) {
            return Err(Error::Validacion(format!(
                "RUT de usuario inválido: {rut_usuario}"
            )));
        }
        let timeout = Duration::from_secs(40);
        // sin seguir redirects (como httpx follow_redirects=False)
        let agente = crate::sii::http::agente(timeout, false);
        Ok(Cliente {
            rut_usuario: formatear_rut(rut_usuario, false),
            empresa: String::new(),
            timeout,
            pausa: Duration::from_millis(700),
            raiz_storage: String::new(),
            log: None,
            trazas: None,
            clave_trib: clave_tributaria.to_string(),
            clave_cert: clave_certificado.to_string(),
            cookies: BTreeMap::new(),
            agente,
            autenticado: false,
            menu_html: String::new(),
        })
    }

    pub(crate) fn log(&self, msg: String) {
        if let Some(l) = &self.log {
            l(&msg);
        }
    }

    pub(crate) fn traza(&mut self, nombre: &str, contenido: &str) {
        if let Some(t) = self.trazas.as_mut() {
            t.insert(nombre.to_string(), contenido.to_string());
        }
    }

    /// Absorbe las cookies de la respuesta: el SII manda cookies con valor "None"; reenviarlas
    /// malforma el request, así que esas se borran (`_limpiar_cookies`).
    fn absorber_cookies(&mut self, r: &Respuesta) {
        for (k, v) in &r.headers {
            if !k.eq_ignore_ascii_case("set-cookie") {
                continue;
            }
            if let Some((nombre, valor)) = v.split(';').next().and_then(|p| p.split_once('=')) {
                let (nombre, valor) = (nombre.trim().to_string(), valor.trim().to_string());
                if valor.is_empty() || valor == "None" {
                    self.cookies.remove(&nombre);
                } else {
                    self.cookies.insert(nombre, valor);
                }
            }
        }
    }

    pub(crate) fn poner_cookie(&mut self, nombre: &str, valor: &str) {
        self.cookies.insert(nombre.to_string(), valor.to_string());
    }

    pub(crate) fn req(
        &mut self,
        metodo: &str,
        u: &str,
        o: Opciones<'_>,
    ) -> Resultado<RespuestaPortal> {
        let mut url = u.to_string();
        if let Some(params) = o.params {
            if !params.is_empty() {
                let q = codificar_latin1(params).map_err(Error::Validacion)?;
                url.push('?');
                url.push_str(&String::from_utf8_lossy(&q));
            }
        }
        let cuerpo: Option<Vec<u8>> = match (o.content, o.data) {
            (Some(c), _) => Some(c.to_vec()),
            (None, Some(d)) => Some(codificar_latin1(d).map_err(Error::Validacion)?),
            (None, None) => None,
        };
        let mut cab: Vec<(String, String)> = vec![
            ("User-Agent".into(), UA.into()),
            ("Accept".into(), ACCEPT.into()),
            ("Accept-Language".into(), "es-CL,es;q=0.9,en;q=0.8".into()),
            (
                "sec-ch-ua".into(),
                r#""Chromium";v="152", "Not?A_Brand";v="24", "Google Chrome";v="152""#.into(),
            ),
            ("sec-ch-ua-mobile".into(), "?0".into()),
            ("sec-ch-ua-platform".into(), r#""macOS""#.into()),
            ("Upgrade-Insecure-Requests".into(), "1".into()),
            ("Sec-Fetch-Site".into(), "same-origin".into()),
        ];
        if o.navegacion {
            cab.push(("Sec-Fetch-Mode".into(), "navigate".into()));
            cab.push(("Sec-Fetch-Dest".into(), "document".into()));
        } else {
            cab.push(("Sec-Fetch-Mode".into(), "cors".into()));
            cab.push(("Sec-Fetch-Dest".into(), "empty".into()));
        }
        if !o.origin.is_empty() {
            cab.push(("Origin".into(), o.origin.into()));
        }
        if !o.referer.is_empty() {
            cab.push(("Referer".into(), o.referer.into()));
        }
        if metodo == "POST" {
            cab.push((
                "Content-Type".into(),
                "application/x-www-form-urlencoded".into(),
            ));
            if o.navegacion {
                cab.push(("Cache-Control".into(), "max-age=0".into()));
                cab.push(("Sec-Fetch-User".into(), "?1".into()));
            }
        }
        if let Some(extra) = o.extra {
            for (k, v) in extra {
                cab.retain(|(ck, _)| !ck.eq_ignore_ascii_case(k));
                cab.push((k.to_string(), v.to_string()));
            }
        }
        if !self.cookies.is_empty() {
            let c = self
                .cookies
                .iter()
                .map(|(k, v)| format!("{k}={v}"))
                .collect::<Vec<_>>()
                .join("; ");
            cab.push(("Cookie".into(), c));
        }
        let r = if metodo == "POST" {
            let mut req = self.agente.post(&url);
            for (k, v) in &cab {
                req = req.header(k, v);
            }
            ejecutar(req, cuerpo.as_deref().unwrap_or(&[]))
        } else {
            let mut req = self.agente.get(&url);
            for (k, v) in &cab {
                req = req.header(k, v);
            }
            ejecutar_get(req)
        }
        .map_err(|e| Error::Sii(format!("sin respuesta ({e})")))?;
        self.absorber_cookies(&r);
        Ok(RespuestaPortal {
            status: r.status,
            location: r.header("Location").unwrap_or("").to_string(),
            cuerpo: r.cuerpo,
        })
    }

    fn tiene_sesion(&self) -> bool {
        self.cookies
            .keys()
            .any(|k| k.starts_with("NETSCAPE_LIVEWIRE"))
    }

    // ------------------------------------------------------------------------------- sesión

    /// Login por clave tributaria + entrada al menú de emisión. PRODUCCIÓN.
    pub fn iniciar_sesion(&mut self) -> Resultado<()> {
        let (n, dv) = separar_rut(&self.rut_usuario);
        let data = [
            Par::new("rut", n),
            Par::new("dv", dv),
            Par::new("referencia", URL_SII_HOME),
            Par::new("411", ""),
            Par::new("rutcntr", formatear_rut(&self.rut_usuario, true)),
            Par::new("clave", self.clave_trib.clone()),
        ];
        let r = self.req(
            "POST",
            URL_LOGIN,
            Opciones {
                navegacion: true,
                referer: REFERER_LOGIN,
                origin: "https://zeusr.sii.cl",
                data: Some(&data),
                ..Default::default()
            },
        )?;
        // El SII devuelve 200 con HTML de error, no un 401: mirar las cookies es lo fiable.
        if !self.tiene_sesion() {
            return Err(Error::Autenticacion(format!("el SII no abrió sesión (clave tributaria incorrecta o tope de sesiones concurrentes; http {})", r.status)));
        }
        self.autenticado = true;
        self.req(
            "GET",
            URL_SII_HOME,
            Opciones {
                navegacion: true,
                referer: REFERER_LOGIN,
                ..Default::default()
            },
        )?;
        let params = [Par::new("OPCION", "34"), Par::new("TIPO", "4")];
        self.req(
            "GET",
            &format!("{BASE}/mipeLaunchPage.cgi"),
            Opciones {
                navegacion: true,
                referer: URL_SII_HOME,
                params: Some(&params),
                ..Default::default()
            },
        )?;
        let params = [Par::new("DESDE_DONDE_URL", OPCION_EMISION)];
        self.req(
            "GET",
            &format!("{BASE}/mipeSelEmpresa.cgi"),
            Opciones {
                navegacion: true,
                referer: URL_SII_HOME,
                params: Some(&params),
                ..Default::default()
            },
        )?;
        Ok(())
    }

    /// Elige la empresa a operar. El RUT va COMPLETO con DV: sin él, el WAF responde `Request
    /// Rejected` y toda la cadena hereda el rechazo.
    pub fn seleccionar_empresa(&mut self, rut_empresa: &str) -> Resultado<()> {
        if !validar_rut(rut_empresa) {
            return Err(Error::Validacion(format!(
                "RUT de empresa inválido: {rut_empresa}"
            )));
        }
        let rut = formatear_rut(rut_empresa, false);
        let data = [
            Par::new("DESDE_DONDE_URL", OPCION_EMISION),
            Par::new("RUT_EMP", rut.clone()),
        ];
        let r = self.req(
            "POST",
            &format!("{BASE}/mipeSelEmpresa.cgi"),
            Opciones {
                navegacion: true,
                origin: "https://www1.sii.cl",
                referer: &format!(
                    "{BASE}/mipeSelEmpresa.cgi?DESDE_DONDE_URL=OPCION%3D34%26TIPO%3D4"
                ),
                data: Some(&data),
                ..Default::default()
            },
        )?;
        if r.rechazado() || r.cuerpo.len() < 400 {
            return Err(Error::Rechazo(format!(
                "el portal no aceptó la selección de empresa (http {}, rut {rut})",
                r.status
            )));
        }
        self.empresa = rut;
        self.menu_html = r.texto();
        Ok(())
    }

    pub(crate) fn requiere_empresa(&self) -> Resultado<()> {
        if self.empresa.is_empty() {
            return Err(Error::Validacion(
                "primero iniciar_sesion() y seleccionar_empresa()".into(),
            ));
        }
        Ok(())
    }

    /// `enlaces_menu`: los CGI que el menú de la empresa expone (anclas, frames, forms, options
    /// y JS), sin duplicados. Solo lectura; sirve para descubrir sin adivinar.
    pub fn enlaces_menu(&self) -> Vec<Enlace> {
        static RE_ANCHOR: OnceLock<Regex> = OnceLock::new();
        static RE_FRAME: OnceLock<Regex> = OnceLock::new();
        static RE_FORM_ACT: OnceLock<Regex> = OnceLock::new();
        static RE_OPTION_CG: OnceLock<Regex> = OnceLock::new();
        static RE_JS_CGI: OnceLock<Regex> = OnceLock::new();
        static RE_ONCLICK: OnceLock<Regex> = OnceLock::new();
        let h = &self.menu_html;
        let mut enlaces: Vec<Enlace> = Vec::new();
        for m in re(
            &RE_ANCHOR,
            r#"(?is)<a\b[^>]*href=["']([^"']+)["'][^>]*>(.*?)</a>"#,
        )
        .captures_iter(h)
        {
            enlaces.push(Enlace {
                texto: sin_tags(&m[2]),
                href: m[1].to_string(),
            });
        }
        for m in re(&RE_FRAME, r#"(?i)<i?frame\b[^>]*src=["']([^"']+)"#).captures_iter(h) {
            enlaces.push(Enlace {
                texto: "[frame]".into(),
                href: m[1].to_string(),
            });
        }
        for m in re(&RE_FORM_ACT, r#"(?i)<form\b[^>]*action=["']([^"']+)"#).captures_iter(h) {
            enlaces.push(Enlace {
                texto: "[form]".into(),
                href: m[1].to_string(),
            });
        }
        for m in re(
            &RE_OPTION_CG,
            r#"(?is)<option\b[^>]*value=["']([^"']*\.cgi[^"']*)["'][^>]*>(.*?)</option>"#,
        )
        .captures_iter(h)
        {
            enlaces.push(Enlace {
                texto: format!("[option] {}", sin_tags(&m[2])),
                href: m[1].to_string(),
            });
        }
        for m in re(&RE_JS_CGI, r#"(?i)(?:location(?:\.href)?\s*=|window\.open\(|\.submit\(|href=)\s*["']([^"']*\.cgi[^"']*)"#).captures_iter(h) {
            enlaces.push(Enlace { texto: "[js]".into(), href: m[1].to_string() });
        }
        for m in re(
            &RE_ONCLICK,
            r#"(?is)onclick=["'][^"']*?["']([^"']*\.cgi[^"']*)["'][^"']*["'][^>]*>(.*?)<"#,
        )
        .captures_iter(h)
        {
            enlaces.push(Enlace {
                texto: format!("[onclick] {}", sin_tags(&m[2])),
                href: m[1].to_string(),
            });
        }
        let mut vistos = std::collections::HashSet::new();
        enlaces
            .into_iter()
            .filter(|e| vistos.insert((e.texto.clone(), e.href.clone())))
            .collect()
    }

    /// `resumen_menu`: qué contiene la página del menú, sin exponer su HTML.
    pub fn resumen_menu(&self) -> ResumenMenu {
        static RE_TITLE: OnceLock<Regex> = OnceLock::new();
        static RE_CGI: OnceLock<Regex> = OnceLock::new();
        static RE_IFRAME: OnceLock<Regex> = OnceLock::new();
        static RE_FORM: OnceLock<Regex> = OnceLock::new();
        static RE_A: OnceLock<Regex> = OnceLock::new();
        static RE_SCRIPT: OnceLock<Regex> = OnceLock::new();
        let h = &self.menu_html;
        let mut r = ResumenMenu {
            bytes: h.len(),
            frames: re(&RE_IFRAME, r"(?i)<i?frame\b").find_iter(h).count(),
            forms: re(&RE_FORM, r"(?i)<form\b").find_iter(h).count(),
            anchors: re(&RE_A, r"(?i)<a\b").find_iter(h).count(),
            scripts: re(&RE_SCRIPT, r"(?i)<script\b").find_iter(h).count(),
            ..Default::default()
        };
        if let Some(m) = re(&RE_TITLE, r"(?is)<title>(.*?)</title>").captures(h) {
            r.titulo = m[1].trim().to_string();
        }
        let set: std::collections::BTreeSet<String> = re(&RE_CGI, r"([A-Za-z0-9_]+\.cgi)")
            .captures_iter(h)
            .map(|m| m[1].to_string())
            .collect();
        r.cgis_mencionados = set.into_iter().collect();
        r
    }

    /// Cierra la sesión en el SII (best-effort). Sigue el 302 de autTermino: el GET a secas deja
    /// la sesión viva y así se llegó al tope el 2026-10-08. Devuelve error solo si el SII no
    /// borró las cookies de sesión (aviso, no fallo).
    pub fn cerrar(&mut self) -> Resultado<()> {
        if !self.autenticado {
            return Ok(());
        }
        self.autenticado = false;
        let cookie = self
            .cookies
            .iter()
            .map(|(k, v)| format!("{k}={v}"))
            .collect::<Vec<_>>()
            .join("; ");
        let req = self
            .agente
            .get(URL_LOGOUT)
            .config()
            .max_redirects(10)
            .max_redirects_will_error(false)
            .build()
            .header("User-Agent", UA)
            .header("Referer", &format!("{BASE}/mipeSelEmpresa.cgi"))
            .header("Cookie", &cookie);
        let r =
            ejecutar_get(req).map_err(|e| Error::Sii(format!("autTermino sin respuesta ({e})")))?;
        self.absorber_cookies(&r);
        if self.tiene_sesion() {
            return Err(Error::Sii(
                "autTermino no cerró la sesión (cookies de sesión siguen vivas)".into(),
            ));
        }
        Ok(())
    }
}

/// Un `(texto, href)` del menú de la empresa.
#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize)]
pub struct Enlace {
    pub texto: String,
    pub href: String,
}

#[derive(Debug, Clone, Default, serde::Serialize)]
pub struct ResumenMenu {
    pub bytes: usize,
    pub titulo: String,
    pub frames: usize,
    pub forms: usize,
    pub anchors: usize,
    pub scripts: usize,
    pub cgis_mencionados: Vec<String>,
}

static RE_TAGS_HTML: OnceLock<Regex> = OnceLock::new();

fn sin_tags(s: &str) -> String {
    re(&RE_TAGS_HTML, r"<[^>]+>")
        .replace_all(s, "")
        .trim()
        .to_string()
}
