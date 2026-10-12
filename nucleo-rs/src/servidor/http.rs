//! La capa HTTP del servidor: petición/respuesta propias (para atender por red con `tiny_http`
//! y en el mismo proceso sin red, como `Llamar` en Go), el enrutador con los patrones de
//! `http.ServeMux` de Go (`GET /api/v1/x/{id}`, `{$}`, prefijos con `/` final), la query, los
//! formularios (urlencoded y multipart) y el servidor de red.

use std::collections::BTreeMap;

/// Una petición ya leída completa (método, ruta, query, cabeceras, cuerpo).
#[derive(Debug, Clone, Default)]
pub struct Peticion {
    pub metodo: String,
    /// solo la ruta, decodificada (`r.URL.Path`)
    pub ruta: String,
    /// la query cruda, sin `?`
    pub query: String,
    pub cabeceras: Vec<(String, String)>,
    pub cuerpo: Vec<u8>,
    pub host: String,
    /// X-Request-ID (lo pone el middleware)
    pub request_id: String,
    /// los comodines del patrón (`{id}` → "7")
    pub params: BTreeMap<String, String>,
    /// quién llama (lo pone `protegido`)
    pub usuario: Option<super::auth::Usuario>,
}

impl Peticion {
    pub fn nueva(metodo: &str, url: &str, cuerpo: Vec<u8>) -> Peticion {
        let (ruta, query) = match url.split_once('?') {
            Some((r, q)) => (r.to_string(), q.to_string()),
            None => (url.to_string(), String::new()),
        };
        Peticion {
            metodo: metodo.to_uppercase(),
            ruta: percent_decode(&ruta),
            query,
            cuerpo,
            ..Default::default()
        }
    }

    /// `r.Header.Get(k)` (sin distinguir mayúsculas; vacío si no está).
    pub fn cabecera(&self, k: &str) -> &str {
        self.cabeceras
            .iter()
            .find(|(n, _)| n.eq_ignore_ascii_case(k))
            .map(|(_, v)| v.as_str())
            .unwrap_or("")
    }

    pub fn param(&self, k: &str) -> &str {
        self.params.get(k).map(|s| s.as_str()).unwrap_or("")
    }

    /// `r.URL.Query()` como pares (primer valor de cada clave).
    pub fn consulta(&self) -> BTreeMap<String, String> {
        parsear_urlencoded(self.query.as_bytes())
    }

    /// `q.Get(k)`: "" si no está.
    pub fn q(&self, k: &str) -> String {
        primer_valor(self.query.as_bytes(), k).unwrap_or_default()
    }

    pub fn es_json(&self) -> bool {
        self.cabecera("Content-Type")
            .to_ascii_lowercase()
            .starts_with("application/json")
    }
}

/// Una respuesta lista para escribir.
#[derive(Debug, Clone, Default)]
pub struct Respuesta {
    pub status: u16,
    pub cabeceras: Vec<(String, String)>,
    pub cuerpo: Vec<u8>,
}

impl Respuesta {
    pub fn nueva(status: u16) -> Respuesta {
        Respuesta {
            status,
            ..Default::default()
        }
    }
    pub fn con(mut self, k: &str, v: &str) -> Respuesta {
        self.cabeceras.push((k.to_string(), v.to_string()));
        self
    }
    pub fn cuerpo(mut self, b: Vec<u8>) -> Respuesta {
        self.cuerpo = b;
        self
    }
    pub fn cabecera(&self, k: &str) -> &str {
        self.cabeceras
            .iter()
            .find(|(n, _)| n.eq_ignore_ascii_case(k))
            .map(|(_, v)| v.as_str())
            .unwrap_or("")
    }
    /// `w.Header().Set`: reemplaza si ya estaba.
    pub fn poner(&mut self, k: &str, v: &str) {
        self.cabeceras.retain(|(n, _)| !n.eq_ignore_ascii_case(k));
        self.cabeceras.push((k.to_string(), v.to_string()));
    }
    pub fn texto(status: u16, tipo: &str, t: &str) -> Respuesta {
        Respuesta::nueva(status)
            .con("Content-Type", tipo)
            .cuerpo(t.as_bytes().to_vec())
    }
    pub fn html(h: &str) -> Respuesta {
        Respuesta::texto(200, "text/html; charset=utf-8", h)
    }
    pub fn binario(status: u16, tipo: &str, b: Vec<u8>) -> Respuesta {
        Respuesta::nueva(status).con("Content-Type", tipo).cuerpo(b)
    }
}

// ---------------------------------------------------------------- codificación

pub fn percent_decode(s: &str) -> String {
    let b = s.as_bytes();
    let mut out = Vec::with_capacity(b.len());
    let mut i = 0;
    while i < b.len() {
        if b[i] == b'%' && i + 2 < b.len() {
            if let (Some(h), Some(l)) = (hex(b[i + 1]), hex(b[i + 2])) {
                out.push(h * 16 + l);
                i += 3;
                continue;
            }
        }
        out.push(b[i]);
        i += 1;
    }
    String::from_utf8_lossy(&out).into_owned()
}

fn hex(c: u8) -> Option<u8> {
    match c {
        b'0'..=b'9' => Some(c - b'0'),
        b'a'..=b'f' => Some(c - b'a' + 10),
        b'A'..=b'F' => Some(c - b'A' + 10),
        _ => None,
    }
}

fn decode_form(s: &[u8]) -> String {
    let mut t = Vec::with_capacity(s.len());
    for &c in s {
        t.push(if c == b'+' { b' ' } else { c });
    }
    percent_decode(&String::from_utf8_lossy(&t))
}

/// `url.Values` → primer valor por clave.
pub fn parsear_urlencoded(b: &[u8]) -> BTreeMap<String, String> {
    let mut out = BTreeMap::new();
    for par in b.split(|&c| c == b'&') {
        if par.is_empty() {
            continue;
        }
        let (k, v) = match par.iter().position(|&c| c == b'=') {
            Some(i) => (&par[..i], &par[i + 1..]),
            None => (par, &b""[..]),
        };
        out.entry(decode_form(k)).or_insert_with(|| decode_form(v));
    }
    out
}

fn primer_valor(b: &[u8], k: &str) -> Option<String> {
    parsear_urlencoded(b).remove(k)
}

/// `url.Values.Encode()`: claves ordenadas, `QueryEscape`.
pub fn query_encode(pares: &[(&str, &str)]) -> String {
    let mut ps: Vec<&(&str, &str)> = pares.iter().collect();
    ps.sort();
    ps.iter()
        .map(|(k, v)| format!("{}={}", query_escape(k), query_escape(v)))
        .collect::<Vec<_>>()
        .join("&")
}

pub fn query_escape(s: &str) -> String {
    let mut out = String::new();
    for &c in s.as_bytes() {
        match c {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'-' | b'_' | b'.' | b'~' => {
                out.push(c as char)
            }
            b' ' => out.push('+'),
            _ => out.push_str(&format!("%{c:02X}")),
        }
    }
    out
}

// ---------------------------------------------------------------- formularios

/// Un archivo subido por multipart.
#[derive(Debug, Clone, Default)]
pub struct Archivo {
    pub campo: String,
    pub nombre: String,
    pub datos: Vec<u8>,
}

/// `r.MultipartForm`: valores (sin filename) y archivos (con filename).
#[derive(Debug, Clone, Default)]
pub struct Formulario {
    pub valores: Vec<(String, String)>,
    pub archivos: Vec<Archivo>,
}

impl Formulario {
    pub fn tiene(&self, k: &str) -> bool {
        self.valores.iter().any(|(n, _)| n == k)
    }
    /// `r.FormValue(k)`: el primer valor o "".
    pub fn valor(&self, k: &str) -> String {
        self.valores
            .iter()
            .find(|(n, _)| n == k)
            .map(|(_, v)| v.clone())
            .unwrap_or_default()
    }
    pub fn archivo(&self, campo: &str) -> Option<&Archivo> {
        self.archivos.iter().find(|a| a.campo == campo)
    }
}

/// `ParseMultipartForm` / `ParseForm`: multipart o urlencoded según el Content-Type. `None`
/// si el cuerpo no es ninguno de los dos (en Go, el error de ParseMultipartForm).
pub fn parsear_formulario(p: &Peticion) -> Option<Formulario> {
    let ct = p.cabecera("Content-Type").to_string();
    let ctl = ct.to_ascii_lowercase();
    if ctl.starts_with("multipart/form-data") {
        let limite = ct
            .split(';')
            .map(|x| x.trim())
            .find_map(|x| x.strip_prefix("boundary="))
            .map(|b| b.trim_matches('"').to_string())?;
        return parsear_multipart(&p.cuerpo, &limite);
    }
    if ctl.starts_with("application/x-www-form-urlencoded") {
        let mut f = Formulario::default();
        for (k, v) in parsear_urlencoded(&p.cuerpo) {
            f.valores.push((k, v));
        }
        return Some(f);
    }
    None
}

fn buscar(hay: &[u8], aguja: &[u8], desde: usize) -> Option<usize> {
    if aguja.is_empty() || hay.len() < aguja.len() {
        return None;
    }
    (desde..=hay.len() - aguja.len()).find(|&i| &hay[i..i + aguja.len()] == aguja)
}

fn parsear_multipart(cuerpo: &[u8], limite: &str) -> Option<Formulario> {
    let sep = format!("--{limite}").into_bytes();
    let mut f = Formulario::default();
    let mut pos = buscar(cuerpo, &sep, 0)? + sep.len();
    loop {
        // tras el separador: "--" (fin) o CRLF
        if cuerpo.len() >= pos + 2 && &cuerpo[pos..pos + 2] == b"--" {
            break;
        }
        if cuerpo.len() >= pos + 2 && &cuerpo[pos..pos + 2] == b"\r\n" {
            pos += 2;
        } else if cuerpo.len() > pos && cuerpo[pos] == b'\n' {
            pos += 1;
        }
        let fin_cab = buscar(cuerpo, b"\r\n\r\n", pos)
            .map(|i| (i, 4))
            .or_else(|| buscar(cuerpo, b"\n\n", pos).map(|i| (i, 2)))?;
        let cab = String::from_utf8_lossy(&cuerpo[pos..fin_cab.0]).into_owned();
        let ini = fin_cab.0 + fin_cab.1;
        let sig = buscar(cuerpo, &sep, ini)?;
        let mut fin = sig;
        if fin >= 2 && &cuerpo[fin - 2..fin] == b"\r\n" {
            fin -= 2;
        } else if fin >= 1 && cuerpo[fin - 1] == b'\n' {
            fin -= 1;
        }
        let datos = cuerpo[ini..fin].to_vec();
        let (mut nombre, mut archivo) = (String::new(), None::<String>);
        for linea in cab.lines() {
            let l = linea.trim();
            if l.to_ascii_lowercase().starts_with("content-disposition:") {
                for parte in l.split(';').map(|x| x.trim()) {
                    if let Some(v) = parte.strip_prefix("name=") {
                        nombre = v.trim_matches('"').to_string();
                    } else if let Some(v) = parte.strip_prefix("filename=") {
                        archivo = Some(v.trim_matches('"').to_string());
                    }
                }
            }
        }
        match archivo {
            Some(fn_) => f.archivos.push(Archivo {
                campo: nombre,
                nombre: fn_,
                datos,
            }),
            None => f
                .valores
                .push((nombre, String::from_utf8_lossy(&datos).into_owned())),
        }
        pos = sig + sep.len();
    }
    Some(f)
}

// ---------------------------------------------------------------- enrutador

#[derive(Debug, Clone, PartialEq, Eq)]
enum Seg {
    Literal(String),
    Comodin(String),
}

/// (parámetros, especificidad) de una coincidencia.
type Coincidencia = (BTreeMap<String, String>, (usize, usize, usize));

/// Un patrón de `http.ServeMux`: `[MÉTODO ]/ruta`, con `{nombre}` por segmento, `{$}` para
/// exigir el final con barra y una barra final suelta para un prefijo (subárbol).
#[derive(Debug, Clone)]
pub struct Patron {
    metodo: String,
    segs: Vec<Seg>,
    /// termina en `{$}`: solo esa ruta con barra final
    exacto_barra: bool,
    /// termina en `/`: todo el subárbol
    prefijo: bool,
}

impl Patron {
    pub fn parsear(p: &str) -> Patron {
        let (metodo, ruta) = match p.split_once(' ') {
            Some((m, r)) => (m.to_uppercase(), r),
            None => (String::new(), p),
        };
        let mut segs = Vec::new();
        let (mut exacto_barra, mut prefijo) = (false, false);
        let partes: Vec<&str> = ruta.trim_start_matches('/').split('/').collect();
        for (i, s) in partes.iter().enumerate() {
            let ultimo = i + 1 == partes.len();
            if ultimo && *s == "{$}" {
                exacto_barra = true;
            } else if ultimo && s.is_empty() {
                prefijo = true;
            } else if s.starts_with('{') && s.ends_with('}') {
                segs.push(Seg::Comodin(s[1..s.len() - 1].to_string()));
            } else {
                segs.push(Seg::Literal(s.to_string()));
            }
        }
        if ruta == "/" {
            segs.clear();
            prefijo = true;
        }
        Patron {
            metodo,
            segs,
            exacto_barra,
            prefijo,
        }
    }

    /// Coincide la ruta: (parámetros, puntaje de especificidad).
    fn coincide(&self, ruta: &str) -> Option<Coincidencia> {
        let con_barra = ruta.ends_with('/') && ruta != "/";
        let partes: Vec<&str> = ruta
            .trim_start_matches('/')
            .split('/')
            .filter(|s| !s.is_empty())
            .collect();
        let mut params = BTreeMap::new();
        if self.prefijo {
            if partes.len() < self.segs.len() {
                return None;
            }
        } else if partes.len() != self.segs.len() {
            return None;
        }
        let mut literales = 0;
        for (seg, parte) in self.segs.iter().zip(partes.iter()) {
            match seg {
                Seg::Literal(l) => {
                    if l != parte {
                        return None;
                    }
                    literales += 1;
                }
                Seg::Comodin(n) => {
                    params.insert(n.clone(), parte.to_string());
                }
            }
        }
        if !self.prefijo {
            // "/x" no coincide con "/x/"; "{$}" solo con "/x/"
            if self.exacto_barra != con_barra && !(ruta == "/" && self.segs.is_empty()) {
                return None;
            }
        }
        let fijo = if self.prefijo { 0 } else { 1 };
        Some((params, (fijo, self.segs.len(), literales)))
    }

    fn metodo_ok(&self, m: &str) -> bool {
        self.metodo.is_empty() || self.metodo == m || (self.metodo == "GET" && m == "HEAD")
    }
}

/// (especificidad, manejador, parámetros) del mejor candidato.
type Mejor<'a, H> = ((usize, usize, usize), &'a H, BTreeMap<String, String>);

/// Resultado del enrutamiento.
pub enum Enrutado<H> {
    Encontrado(H, BTreeMap<String, String>),
    /// la ruta existe con otros métodos (405 + Allow)
    MetodoNoPermitido(String),
    NoEncontrado,
}

/// Un enrutador con los patrones de Go: el más específico gana.
pub struct Enrutador<H> {
    rutas: Vec<(Patron, H)>,
}

impl<H: Clone> Default for Enrutador<H> {
    fn default() -> Self {
        Enrutador { rutas: Vec::new() }
    }
}

impl<H: Clone> Enrutador<H> {
    pub fn registrar(&mut self, patron: &str, h: H) {
        self.rutas.push((Patron::parsear(patron), h));
    }

    pub fn resolver(&self, metodo: &str, ruta: &str) -> Enrutado<H> {
        let mut mejor: Option<Mejor<'_, H>> = None;
        let mut otros: Vec<String> = Vec::new();
        let mut mejor_otro: Option<(usize, usize, usize)> = None;
        for (p, h) in &self.rutas {
            if let Some((params, puntaje)) = p.coincide(ruta) {
                if p.metodo_ok(metodo) {
                    if mejor.as_ref().map(|m| puntaje > m.0).unwrap_or(true) {
                        mejor = Some((puntaje, h, params));
                    }
                } else if mejor_otro.map(|m| puntaje >= m).unwrap_or(true) {
                    if mejor_otro != Some(puntaje) {
                        otros.clear();
                    }
                    mejor_otro = Some(puntaje);
                    otros.push(p.metodo.clone());
                }
            }
        }
        match (mejor, mejor_otro) {
            (Some((pt, h, params)), Some(po)) if po > pt => {
                let _ = h;
                let _ = params;
                Enrutado::MetodoNoPermitido(otros.join(", "))
            }
            (Some((_, h, params)), _) => Enrutado::Encontrado(h.clone(), params),
            (None, Some(_)) => Enrutado::MetodoNoPermitido(otros.join(", ")),
            (None, None) => Enrutado::NoEncontrado,
        }
    }
}

// ---------------------------------------------------------------- red

/// Un servidor de red que se puede detener (`http.Server.Shutdown`): la app lo apaga al cerrar.
pub struct ServidorHTTP {
    srv: std::sync::Arc<tiny_http::Server>,
    hilo: Option<std::thread::JoinHandle<()>>,
}

impl ServidorHTTP {
    /// Escucha en `direccion` y atiende en un hilo propio (un hilo por petición).
    pub fn iniciar<F>(direccion: &str, atender: F) -> Result<ServidorHTTP, String>
    where
        F: Fn(Peticion) -> Respuesta + Send + Sync + 'static,
    {
        let srv = std::sync::Arc::new(
            tiny_http::Server::http(direccion)
                .map_err(|e| format!("escuchar en {direccion}: {e}"))?,
        );
        let s2 = srv.clone();
        let hilo = std::thread::spawn(move || atender_todo(&s2, atender));
        Ok(ServidorHTTP {
            srv,
            hilo: Some(hilo),
        })
    }

    /// Deja de aceptar conexiones y cierra el socket.
    pub fn detener(mut self) {
        self.srv.unblock();
        if let Some(h) = self.hilo.take() {
            let _ = h.join();
        }
    }
}

fn atender_todo<F>(srv: &tiny_http::Server, atender: F)
where
    F: Fn(Peticion) -> Respuesta + Send + Sync + 'static,
{
    let atender = std::sync::Arc::new(atender);
    for mut req in srv.incoming_requests() {
        let at = atender.clone();
        std::thread::spawn(move || {
            let mut cuerpo = Vec::new();
            let _ = std::io::Read::read_to_end(req.as_reader(), &mut cuerpo);
            let mut p = Peticion::nueva(req.method().as_str(), req.url(), cuerpo);
            for h in req.headers() {
                p.cabeceras
                    .push((h.field.as_str().to_string(), h.value.as_str().to_string()));
            }
            p.host = p.cabecera("Host").to_string();
            let r = at(p);
            let mut resp = tiny_http::Response::from_data(r.cuerpo).with_status_code(r.status);
            for (k, v) in &r.cabeceras {
                if let Ok(h) = tiny_http::Header::from_bytes(k.as_bytes(), v.as_bytes()) {
                    resp = resp.with_header(h);
                }
            }
            let _ = req.respond(resp);
        });
    }
}

/// Sirve por red con `tiny_http` hasta que el proceso muera.
pub fn servir<F>(direccion: &str, atender: F) -> Result<(), String>
where
    F: Fn(Peticion) -> Respuesta + Send + Sync + 'static,
{
    let srv =
        tiny_http::Server::http(direccion).map_err(|e| format!("escuchar en {direccion}: {e}"))?;
    atender_todo(&srv, atender);
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn patrones_como_go() {
        let mut r: Enrutador<&'static str> = Enrutador::default();
        r.registrar("GET /api/v1/valores", "vigentes");
        r.registrar("GET /api/v1/valores/{$}", "vigentes/");
        r.registrar("GET /api/v1/valores/historico", "historico");
        r.registrar("GET /api/v1/valores/{indicador}/serie", "serie");
        r.registrar("GET /api/v1/valores/{indicador}", "uno");
        r.registrar("/app/", "app");
        r.registrar("/", "raiz");
        r.registrar("GET /{$}", "salud");
        let ok = |m: &str, ruta: &str| match r.resolver(m, ruta) {
            Enrutado::Encontrado(h, p) => format!("{h} {p:?}"),
            Enrutado::MetodoNoPermitido(a) => format!("405 {a}"),
            Enrutado::NoEncontrado => "404".into(),
        };
        assert_eq!(ok("GET", "/api/v1/valores"), "vigentes {}");
        assert_eq!(ok("GET", "/api/v1/valores/"), "vigentes/ {}");
        assert_eq!(ok("GET", "/api/v1/valores/historico"), "historico {}");
        assert_eq!(
            ok("GET", "/api/v1/valores/uf"),
            "uno {\"indicador\": \"uf\"}"
        );
        assert_eq!(
            ok("GET", "/api/v1/valores/uf/serie"),
            "serie {\"indicador\": \"uf\"}"
        );
        assert_eq!(ok("GET", "/app/x/y.js"), "app {}");
        assert_eq!(ok("GET", "/otra"), "raiz {}");
        assert_eq!(ok("GET", "/"), "salud {}");
        assert_eq!(ok("PUT", "/api/v1/valores/uf"), "405 GET");
    }

    #[test]
    fn multipart_y_query() {
        let cuerpo = b"--X\r\nContent-Disposition: form-data; name=\"password\"\r\n\r\ndemo\r\n--X\r\nContent-Disposition: form-data; name=\"archivo\"; filename=\"a.xml\"\r\nContent-Type: text/xml\r\n\r\n<a/>\r\n--X--\r\n".to_vec();
        let mut p = Peticion::nueva("POST", "/x?rut=77.777.777-7&monto=1+2&a=%C3%B1", cuerpo);
        p.cabeceras.push((
            "Content-Type".into(),
            "multipart/form-data; boundary=X".into(),
        ));
        let f = parsear_formulario(&p).unwrap();
        assert_eq!(f.valor("password"), "demo");
        assert_eq!(f.archivo("archivo").unwrap().datos, b"<a/>");
        assert_eq!(f.archivo("archivo").unwrap().nombre, "a.xml");
        assert_eq!(p.q("rut"), "77.777.777-7");
        assert_eq!(p.q("monto"), "1 2");
        assert_eq!(p.q("a"), "ñ");
        assert_eq!(
            query_encode(&[("tipo", "39"), ("rut", "7-7 x")]),
            "rut=7-7+x&tipo=39"
        );
    }
}
