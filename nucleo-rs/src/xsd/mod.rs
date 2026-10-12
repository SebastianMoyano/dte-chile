//! Valida XML contra los esquemas oficiales del SII (`core/xsd`, embebidos aquí) sin libxml2:
//! un intérprete del subconjunto de XSD que esos esquemas usan (sequence, choice,
//! simpleContent/extension, atributos fijos, restricciones con enumeration, length, pattern,
//! totalDigits, fractionDigits, min/maxInclusive sobre string, decimal, la familia integer,
//! base64Binary, date, dateTime, ID y anyURI). Cualquier constructo fuera del subconjunto hace
//! fallar la carga del esquema, nunca pasa en silencio. Transcripción de `nucleo/xsd` (Go).
//!
//! El veredicto (válido / inválido) y el elemento del primer error deben coincidir con los de
//! lxml: `paridad_con_lxml` lo exige sobre `testdata/vectores.json.gz`
//! (`tools/generar_xsd_vectores.py`).

mod arbol;
mod esquema;
mod simple;
mod validar;

use std::collections::HashMap;
use std::fmt;
use std::sync::OnceLock;

pub use arbol::QName;

/// Igual que `core/schema_validator.py`: la raíz elige el esquema; una raíz desconocida se
/// valida contra EnvioDTE (donde, por ejemplo, un `<Signature>` suelto es válido).
fn xsd_por_tipo(raiz: &str) -> Option<&'static str> {
    match raiz {
        "EnvioBOLETA" => Some("EnvioBOLETA_v11.xsd"),
        "ConsumoFolios" => Some("ConsumoFolio_v10.xsd"),
        "EnvioDTE" | "DTE" => Some("EnvioDTE_v10.xsd"),
        _ => None,
    }
}

const ESQUEMA_POR_DEFECTO: &str = "EnvioDTE_v10.xsd";

static ESQUEMAS: OnceLock<Result<HashMap<&'static str, esquema::Esquema>, String>> =
    OnceLock::new();

fn esquemas() -> &'static Result<HashMap<&'static str, esquema::Esquema>, String> {
    ESQUEMAS.get_or_init(|| {
        let mut m = HashMap::new();
        for archivo in [
            "EnvioDTE_v10.xsd",
            "EnvioBOLETA_v11.xsd",
            "ConsumoFolio_v10.xsd",
        ] {
            let e = esquema::cargar_esquema(archivo).map_err(|e| format!("xsd: {archivo}: {e}"))?;
            m.insert(archivo, e);
        }
        Ok(m)
    })
}

/// Un hallazgo de la validación. `elemento` es el nombre local del elemento al que libxml2 se
/// lo atribuiría (el inesperado, el que falta hijos, el dueño del atributo).
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct Error {
    pub linea: usize,
    pub elemento: String,
    pub atributo: String,
    pub mensaje: String,
}

impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        if self.elemento.is_empty() {
            return write!(f, "{}", self.mensaje);
        }
        write!(f, "Línea {}: Elemento '{}'", self.linea, self.elemento)?;
        if !self.atributo.is_empty() {
            write!(f, ", atributo '{}'", self.atributo)?;
        }
        write!(f, ": {}", self.mensaje)
    }
}

/// Espejo de `ValidationResult` (valido, errores, tipo_xml).
#[derive(Debug, Clone, Default)]
pub struct Resultado {
    pub valido: bool,
    pub tipo_xml: String,
    pub errores: Vec<Error>,
}

impl Resultado {
    /// Los errores como texto ("Línea N: Elemento 'X': …"), el formato de la API.
    pub fn mensajes(&self) -> Vec<String> {
        self.errores.iter().map(|e| e.to_string()).collect()
    }
}

/// Valida un XML (ISO-8859-1 o UTF-8, con o sin declaración) contra el XSD que le corresponde
/// por su raíz. Un documento mal formado es inválido con tipo "desconocido".
pub fn validar(raw: &[u8]) -> Resultado {
    let esqs = match esquemas() {
        Ok(m) => m,
        Err(e) => {
            return Resultado {
                tipo_xml: "desconocido".into(),
                errores: vec![Error {
                    mensaje: e.clone(),
                    ..Default::default()
                }],
                ..Default::default()
            }
        }
    };
    let raiz = match arbol::parsear_arbol(raw) {
        Ok(r) => r,
        Err(e) => {
            return Resultado {
                tipo_xml: "desconocido".into(),
                errores: vec![Error {
                    mensaje: format!("Error de sintaxis XML: {e}"),
                    ..Default::default()
                }],
                ..Default::default()
            }
        }
    };
    let (tipo, archivo) = match xsd_por_tipo(&raiz.nombre.local) {
        Some(a) => (raiz.nombre.local.clone(), a),
        None => ("desconocido".to_string(), ESQUEMA_POR_DEFECTO),
    };
    let esq = &esqs[archivo];
    let Some(&decl) = esq.elementos.get(&raiz.nombre) else {
        return Resultado {
            tipo_xml: tipo,
            errores: vec![Error {
                linea: raiz.linea,
                elemento: raiz.nombre.local.clone(),
                mensaje: format!(
                    "No hay una declaración global para la raíz '{}'.",
                    raiz.nombre
                ),
                ..Default::default()
            }],
            ..Default::default()
        };
    };
    let mut c = validar::Contexto::default();
    c.validar_elemento(esq, &raiz, decl);
    Resultado {
        valido: c.errores.is_empty(),
        tipo_xml: tipo,
        errores: c.errores,
    }
}

/// `validar` como error (`Ok(())` si es válido): para el hook de validación de la emisión.
pub fn validar_error(raw: &[u8]) -> Result<(), String> {
    let r = validar(raw);
    if r.valido {
        return Ok(());
    }
    let mut msgs = r.mensajes();
    if msgs.len() > 5 {
        let resto = r.errores.len() - 5;
        msgs.truncate(5);
        msgs.push(format!("… y {resto} más"));
    }
    Err(format!(
        "el XML no cumple el esquema XSD del SII: {}",
        msgs.join("; ")
    ))
}

#[cfg(test)]
mod tests {
    use super::*;
    use base64::Engine;
    use std::io::Read;

    #[test]
    fn carga_esquemas() {
        let m = esquemas().as_ref().expect("los tres esquemas cargan");
        assert_eq!(m.len(), 3);
    }

    /// Los XSD embebidos son copias exactas de core/xsd (la fuente oficial).
    #[test]
    fn esquemas_iguales_a_core() {
        for (nombre, mio) in esquema::ARCHIVOS {
            let ruta = format!("{}/../core/xsd/{}", env!("CARGO_MANIFEST_DIR"), nombre);
            let Ok(fuente) = std::fs::read(&ruta) else {
                eprintln!("sin core/xsd al lado: {ruta}");
                return;
            };
            assert_eq!(
                *mio, fuente,
                "{nombre} difiere de core/xsd: copiarlo de nuevo"
            );
        }
    }

    /// Todos los sobres del corpus dorado son válidos (lxml también lo dice).
    #[test]
    fn corpus_dorado_valido() {
        let dir = format!("{}/../tests/dorado/esperado", env!("CARGO_MANIFEST_DIR"));
        let Ok(entradas) = std::fs::read_dir(&dir) else {
            eprintln!("sin corpus dorado al lado");
            return;
        };
        let mut n = 0;
        for e in entradas.flatten() {
            let p = e.path().join("envio.xml");
            if let Ok(raw) = std::fs::read(&p) {
                let r = validar(&raw);
                assert!(r.valido, "{}: inválido: {:?}", p.display(), r.mensajes());
                n += 1;
            }
        }
        assert!(n >= 15, "se esperaban 15 sobres, hay {n}");
    }

    #[derive(serde::Deserialize)]
    struct Vector {
        nombre: String,
        base: String,
        xml_b64: String,
        valido: bool,
        tipo_xml: String,
        #[serde(default)]
        primer_elemento: String,
        #[serde(default)]
        primer_error: String,
        #[serde(default)]
        excepcion: bool,
    }

    /// Mismo veredicto, mismo tipo_xml y mismo elemento del primer error que lxml para cada
    /// vector (tools/generar_xsd_vectores.py). L15: si difiere, el error está aquí.
    #[test]
    fn paridad_con_lxml() {
        let ruta = format!("{}/testdata/vectores.json.gz", env!("CARGO_MANIFEST_DIR"));
        let f = std::fs::File::open(ruta).expect("testdata/vectores.json.gz");
        let mut gz = flate2::read::GzDecoder::new(f);
        let mut json = Vec::new();
        gz.read_to_end(&mut json).unwrap();
        let vectores: Vec<Vector> = serde_json::from_slice(&json).unwrap();
        let mut fallos = Vec::new();
        let mut ok = 0;
        for v in &vectores {
            let raw = base64::engine::general_purpose::STANDARD
                .decode(&v.xml_b64)
                .unwrap();
            let r = validar(&raw);
            if v.excepcion {
                if r.valido {
                    fallos.push(format!(
                        "{}/{}: lxml lanzó excepción y Rust lo da por válido",
                        v.base, v.nombre
                    ));
                } else {
                    ok += 1;
                }
                continue;
            }
            if r.valido != v.valido || r.tipo_xml != v.tipo_xml {
                fallos.push(format!(
                    "{}/{}: Rust valido={} tipo={}; lxml valido={} tipo={}\n  lxml: {}\n  rust: {}",
                    v.base,
                    v.nombre,
                    r.valido,
                    r.tipo_xml,
                    v.valido,
                    v.tipo_xml,
                    v.primer_error,
                    r.mensajes().join(" | ")
                ));
                continue;
            }
            if !v.valido
                && !v.primer_elemento.is_empty()
                && r.errores.first().map(|e| e.elemento.as_str())
                    != Some(v.primer_elemento.as_str())
            {
                fallos.push(format!(
                    "{}/{}: primer error en distinto elemento\n  lxml: {}\n  rust: {}",
                    v.base,
                    v.nombre,
                    v.primer_error,
                    r.mensajes().join(" | ")
                ));
                continue;
            }
            ok += 1;
        }
        eprintln!("vectores en paridad: {ok} de {}", vectores.len());
        assert!(
            fallos.is_empty(),
            "{} vectores fuera de paridad:\n{}",
            fallos.len(),
            fallos.join("\n")
        );
    }
}
