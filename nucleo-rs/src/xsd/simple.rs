//! Tipos simples: los primitivos que usan los XSD del SII y XMLDSig, sus espacios de valor
//! (numérico exacto sobre el texto decimal, fechas con zona) y las facetas. Transcripción de
//! `nucleo/xsd/simple.go`; los números se comparan como decimales en texto, sin bignum.

use super::esquema::{Esquema, SimpleId};
use regex::Regex;
use std::cmp::Ordering;
use std::sync::OnceLock;

/// Uno nuevo en un esquema hace fallar la carga (y el test), en vez de validar a medias.
pub fn builtin_soportado(local: &str) -> bool {
    matches!(
        local,
        "string"
            | "normalizedString"
            | "token"
            | "anyURI"
            | "anySimpleType"
            | "ID"
            | "NCName"
            | "boolean"
            | "decimal"
            | "integer"
            | "long"
            | "int"
            | "nonNegativeInteger"
            | "positiveInteger"
            | "unsignedLong"
            | "unsignedInt"
            | "base64Binary"
            | "date"
            | "dateTime"
    )
}

pub fn colapsar(s: &str) -> String {
    s.split_whitespace().collect::<Vec<_>>().join(" ")
}

fn re(cache: &'static OnceLock<Regex>, pat: &str) -> &'static Regex {
    cache.get_or_init(|| Regex::new(pat).expect("regex"))
}
static RE_NCNAME: OnceLock<Regex> = OnceLock::new();
static RE_DECIMAL: OnceLock<Regex> = OnceLock::new();
static RE_FECHA: OnceLock<Regex> = OnceLock::new();

/// El valor canónico de un decimal: sin ceros a la izquierda ni a la derecha. Cero es
/// (`ent` y `frac` vacíos), sin signo.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct Numero {
    pub neg: bool,
    pub ent: String,
    pub frac: String,
}

pub fn parsear_numero(v: &str) -> Option<Numero> {
    let m = re(&RE_DECIMAL, r"^([+-]?)(\d*)(?:\.(\d*))?$").captures(v)?;
    let ent = m.get(2).map_or("", |x| x.as_str());
    let frac = m.get(3).map_or("", |x| x.as_str());
    if ent.is_empty() && frac.is_empty() {
        return None;
    }
    let ent = ent.trim_start_matches('0').to_string();
    let frac = frac.trim_end_matches('0').to_string();
    let neg = &m[1] == "-" && !(ent.is_empty() && frac.is_empty());
    Some(Numero { neg, ent, frac })
}

impl Numero {
    fn magnitud(&self, o: &Numero) -> Ordering {
        self.ent
            .len()
            .cmp(&o.ent.len())
            .then_with(|| self.ent.cmp(&o.ent))
            .then_with(|| self.frac.cmp(&o.frac))
    }

    pub fn comparar(&self, o: &Numero) -> Ordering {
        match (self.neg, o.neg) {
            (false, true) => Ordering::Greater,
            (true, false) => Ordering::Less,
            (false, false) => self.magnitud(o),
            (true, true) => o.magnitud(self),
        }
    }

    /// Para los límites de la familia integer: un entero (sin fracción) contra un límite dado
    /// como texto decimal.
    fn cabe(&self, min: &str, max: &str) -> bool {
        let (Some(a), Some(b)) = (parsear_numero(min), parsear_numero(max)) else {
            return false;
        };
        self.comparar(&a) != Ordering::Less && self.comparar(&b) != Ordering::Greater
    }
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct Instante {
    segundos: i64,
    frac: String,
}

impl Instante {
    pub fn comparar(&self, o: &Instante) -> Ordering {
        self.segundos.cmp(&o.segundos).then_with(|| {
            self.frac
                .trim_end_matches('0')
                .cmp(o.frac.trim_end_matches('0'))
        })
    }
}

fn dias_del_mes(y: i64, m: u32) -> u32 {
    match m {
        2 => {
            if y % 4 == 0 && (y % 100 != 0 || y % 400 == 0) {
                29
            } else {
                28
            }
        }
        4 | 6 | 9 | 11 => 30,
        _ => 31,
    }
}

/// Días desde 1970-01-01 (algoritmo de Howard Hinnant, válido para cualquier año).
fn dias_desde_civil(y: i64, m: u32, d: u32) -> i64 {
    let y = if m <= 2 { y - 1 } else { y };
    let era = if y >= 0 { y } else { y - 399 } / 400;
    let yoe = y - era * 400;
    let mp = (m as i64 + 9) % 12;
    let doy = (153 * mp + 2) / 5 + d as i64 - 1;
    let doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    era * 146097 + doe - 719468
}

/// Acepta date (`con_hora=false`) o dateTime. Reglas de libxml2: año de 4 dígitos sin cero
/// inicial sobrante, día válido en el mes, hora 24 solo como 24:00:00, zona hasta ±14:00.
pub fn parsear_fecha(v: &str, con_hora: bool) -> Option<Instante> {
    let m = re(
        &RE_FECHA,
        r"^(-?)(\d{4,})-(\d{2})-(\d{2})(?:T(\d{2}):(\d{2}):(\d{2})(\.\d+)?)?(Z|[+-]\d{2}:\d{2})?$",
    )
    .captures(v)?;
    let hora = m.get(5).is_some();
    if hora != con_hora {
        return None;
    }
    let anio = &m[2];
    if anio.len() > 4 && anio.starts_with('0') {
        return None;
    }
    let mut y: i64 = anio.parse().ok()?;
    if &m[1] == "-" {
        y = -y;
    }
    let mes: u32 = m[3].parse().ok()?;
    let dia: u32 = m[4].parse().ok()?;
    if !(1..=12).contains(&mes) || dia < 1 || dia > dias_del_mes(y, mes) {
        return None;
    }
    let (mut h, mut mi, mut s) = (0i64, 0i64, 0i64);
    let frac = m.get(8).map_or("", |x| x.as_str());
    if con_hora {
        h = m[5].parse().ok()?;
        mi = m[6].parse().ok()?;
        s = m[7].parse().ok()?;
        if mi > 59
            || s > 59
            || h > 24
            || (h == 24 && (mi != 0 || s != 0 || !frac.trim_matches(['.', '0']).is_empty()))
        {
            return None;
        }
    }
    let mut off = 0i64;
    if let Some(z) = m.get(9).map(|x| x.as_str()) {
        if z != "Z" {
            let zh: i64 = z[1..3].parse().ok()?;
            let zm: i64 = z[4..6].parse().ok()?;
            if zh > 14 || zm > 59 || (zh == 14 && zm != 0) {
                return None;
            }
            off = zh * 3600 + zm * 60;
            if z.starts_with('-') {
                off = -off;
            }
        }
    }
    let segundos = dias_desde_civil(y, mes, dia) * 86400 + h * 3600 + mi * 60 + s - off;
    Some(Instante {
        segundos,
        frac: frac.trim_start_matches('.').to_string(),
    })
}

/// Reproduce a libxml2 (xmlschemastypes.c), que es lo que valida Python: los caracteres que no
/// son base64 se IGNORAN (blancos, '-', 'ñ'…); se cuentan los válidos hasta el primer '=',
/// después del cual no puede venir otro válido; a lo más dos '='; (válidos + '=') % 4 == 0; y
/// el último válido debe tener en cero los bits que cubre el relleno.
fn base64_valido(v: &str) -> bool {
    fn dec(c: u8) -> i32 {
        match c {
            b'A'..=b'Z' => (c - b'A') as i32,
            b'a'..=b'z' => (c - b'a') as i32 + 26,
            b'0'..=b'9' => (c - b'0') as i32 + 52,
            b'+' => 62,
            b'/' => 63,
            b'=' => 64,
            _ => -1,
        }
    }
    let b = v.as_bytes();
    let (mut i, mut pad, mut ultimo) = (0usize, 0usize, -1i32);
    let mut k = 0;
    while k < b.len() {
        let d = dec(b[k]);
        if d == 64 {
            break;
        }
        if d >= 0 {
            i += 1;
            ultimo = d;
        }
        k += 1;
    }
    while k < b.len() {
        let d = dec(b[k]);
        if (0..64).contains(&d) {
            return false;
        }
        if d == 64 {
            pad += 1;
        }
        k += 1;
    }
    if pad > 2 || (i + pad) % 4 != 0 {
        return false;
    }
    match pad {
        1 => ultimo & 0x03 == 0,
        2 => ultimo & 0x0f == 0,
        _ => true,
    }
}

/// ¿`v` (ya normalizado) es un valor del tipo primitivo?
pub fn lexico_valido(builtin: &str, v: &str) -> bool {
    match builtin {
        "string" | "normalizedString" | "token" | "anyURI" | "anySimpleType" => return true,
        "ID" | "NCName" => return re(&RE_NCNAME, r"^[\pL_][\pL\pN\pM._\-]*$").is_match(v),
        "boolean" => return matches!(v, "true" | "false" | "1" | "0"),
        "decimal" => return parsear_numero(v).is_some(),
        "base64Binary" => return base64_valido(v),
        "date" => return parsear_fecha(v, false).is_some(),
        "dateTime" => return parsear_fecha(v, true).is_some(),
        _ => {}
    }
    // familia integer: dígitos con signo opcional, nada más
    let s = v.strip_prefix('+').unwrap_or(v);
    let cuerpo = s.strip_prefix('-').unwrap_or(s);
    if cuerpo.is_empty() || !cuerpo.bytes().all(|c| c.is_ascii_digit()) {
        return false;
    }
    let Some(n) = parsear_numero(s) else {
        return false;
    };
    let cero = n.ent.is_empty();
    match builtin {
        "integer" => true,
        "nonNegativeInteger" => !n.neg,
        "positiveInteger" => !n.neg && !cero,
        "long" => n.cabe("-9223372036854775808", "9223372036854775807"),
        "int" => n.cabe("-2147483648", "2147483647"),
        "unsignedLong" => !n.neg && n.cabe("0", "18446744073709551615"),
        "unsignedInt" => !n.neg && n.cabe("0", "4294967295"),
        _ => false,
    }
}

pub fn es_numerico(builtin: &str) -> bool {
    matches!(
        builtin,
        "decimal"
            | "integer"
            | "long"
            | "int"
            | "nonNegativeInteger"
            | "positiveInteger"
            | "unsignedLong"
            | "unsignedInt"
    )
}

/// Blancos como libxml2: string y anySimpleType conservan; date/dateTime no toleran blancos
/// alrededor (los rechaza, medido); todo lo demás (anyURI, ID, numéricos, boolean, base64)
/// colapsa.
pub fn normalizar(builtin: &str, lexico: &str) -> String {
    match builtin {
        "string" | "normalizedString" | "anySimpleType" | "date" | "dateTime" => lexico.to_string(),
        _ => colapsar(lexico),
    }
}

/// Valida el texto `lexico` contra el tipo simple y devuelve los mensajes (sin el prefijo del
/// elemento).
pub fn validar_simple(esq: &Esquema, t: SimpleId, lexico: &str) -> Vec<String> {
    let raiz = esq.raiz_builtin(t);
    let builtin = esq.simples[raiz].builtin.as_str();
    let valor = normalizar(builtin, lexico);
    if !lexico_valido(builtin, &valor) {
        return vec![format!(
            "'{}' no es un valor válido del tipo '{}'.",
            lexico,
            esq.nombre_tipo(t)
        )];
    }
    // cadena de restricciones, de la más básica a la más derivada
    let mut cadena: Vec<SimpleId> = Vec::new();
    let mut x = t;
    while esq.simples[x].builtin.is_empty() {
        cadena.insert(0, x);
        x = esq.simples[x].base.expect("cadena resuelta");
    }
    let num = if es_numerico(builtin) {
        parsear_numero(valor.strip_prefix('+').unwrap_or(&valor))
    } else {
        None
    };
    let fecha = if builtin == "date" || builtin == "dateTime" {
        parsear_fecha(&valor, builtin == "dateTime")
    } else {
        None
    };
    let mut errores = Vec::new();
    for &x in &cadena {
        let mut enum_: Vec<&str> = Vec::new();
        let mut hay_enum = false;
        for f in &esq.simples[x].facetas {
            match f.clase.as_str() {
                "enumeration" => {
                    hay_enum = true;
                    enum_.push(&f.valor);
                }
                "length" | "minLength" | "maxLength" => {
                    let largo = valor.chars().count();
                    let lim: usize = f.valor.parse().unwrap_or(0);
                    match f.clase.as_str() {
                        "length" if largo != lim => errores.push(format!("[faceta 'length'] El valor tiene largo {largo}; se exige {lim}.")),
                        "minLength" if largo < lim => {
                            errores.push(format!("[faceta 'minLength'] El valor tiene largo {largo}; no alcanza el mínimo de {lim}."))
                        }
                        "maxLength" if largo > lim => {
                            errores.push(format!("[faceta 'maxLength'] El valor tiene largo {largo}; supera el máximo de {lim}."))
                        }
                        _ => {}
                    }
                }
                "pattern" => {
                    if let Some(p) = &f.patron {
                        if !p.is_match(&valor) {
                            errores.push(format!(
                                "[faceta 'pattern'] El valor '{}' no cumple el patrón '{}'.",
                                valor, f.valor
                            ));
                        }
                    }
                }
                "totalDigits" => {
                    let lim: usize = f.valor.parse().unwrap_or(0);
                    if let Some(n) = &num {
                        if n.ent.len() + n.frac.len() > lim {
                            errores.push(format!("[faceta 'totalDigits'] El valor '{valor}' tiene más dígitos que los permitidos ({lim})."));
                        }
                    }
                }
                "fractionDigits" => {
                    let lim: usize = f.valor.parse().unwrap_or(0);
                    if let Some(n) = &num {
                        if n.frac.len() > lim {
                            errores.push(format!("[faceta 'fractionDigits'] El valor '{valor}' tiene más decimales que los permitidos ({lim})."));
                        }
                    }
                }
                clase @ ("minInclusive" | "maxInclusive" | "minExclusive" | "maxExclusive") => {
                    let c = comparar(builtin, num.as_ref(), fecha.as_ref(), &f.valor);
                    let mal = match clase {
                        "minInclusive" => c == Ordering::Less,
                        "maxInclusive" => c == Ordering::Greater,
                        "minExclusive" => c != Ordering::Greater,
                        _ => c != Ordering::Less,
                    };
                    if mal {
                        let rel = if clase.starts_with("max") {
                            "mayor que el máximo"
                        } else {
                            "menor que el mínimo"
                        };
                        errores.push(format!(
                            "[faceta '{clase}'] El valor '{valor}' es {rel} permitido ('{}').",
                            f.valor
                        ));
                    }
                }
                _ => {}
            }
        }
        if hay_enum && !en_enum(builtin, &valor, num.as_ref(), fecha.as_ref(), &enum_) {
            errores.push(format!(
                "[faceta 'enumeration'] El valor '{}' no está en el conjunto {{'{}'}}.",
                valor,
                enum_.join("', '")
            ));
        }
    }
    errores
}

/// El signo de (valor - faceta) en el espacio de valores del tipo.
fn comparar(
    builtin: &str,
    num: Option<&Numero>,
    fecha: Option<&Instante>,
    faceta: &str,
) -> Ordering {
    if es_numerico(builtin) {
        return match (num, parsear_numero(faceta)) {
            (Some(n), Some(f)) => n.comparar(&f),
            _ => Ordering::Equal,
        };
    }
    if builtin == "date" || builtin == "dateTime" {
        return match (fecha, parsear_fecha(faceta, builtin == "dateTime")) {
            (Some(d), Some(f)) => d.comparar(&f),
            _ => Ordering::Equal,
        };
    }
    Ordering::Equal
}

fn en_enum(
    builtin: &str,
    valor: &str,
    num: Option<&Numero>,
    fecha: Option<&Instante>,
    enum_: &[&str],
) -> bool {
    enum_.iter().any(|e| {
        if es_numerico(builtin) {
            matches!((num, parsear_numero(e)), (Some(n), Some(f)) if f.comparar(n) == Ordering::Equal)
        } else if builtin == "date" || builtin == "dateTime" {
            matches!((fecha, parsear_fecha(e, builtin == "dateTime")), (Some(d), Some(f)) if f.comparar(d) == Ordering::Equal)
        } else {
            *e == valor
        }
    })
}

/// Compara en el espacio de valores: numérico para los tipos numéricos (1.00 == 1.0), lexical
/// para el resto (anySimpleType incluido: libxml2 rechaza '1.00' contra el fijo '1.0').
pub fn mismo_valor(esq: &Esquema, t: SimpleId, a: &str, b: &str) -> bool {
    let builtin = esq.simples[esq.raiz_builtin(t)].builtin.as_str();
    if es_numerico(builtin) {
        let ca = colapsar(a);
        let cb = colapsar(b);
        return match (
            parsear_numero(ca.strip_prefix('+').unwrap_or(&ca)),
            parsear_numero(cb.strip_prefix('+').unwrap_or(&cb)),
        ) {
            (Some(x), Some(y)) => x.comparar(&y) == Ordering::Equal,
            _ => false,
        };
    }
    normalizar(builtin, a) == normalizar(builtin, b)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn numeros() {
        let a = parsear_numero("0012.500").unwrap();
        assert_eq!(
            a,
            Numero {
                neg: false,
                ent: "12".into(),
                frac: "5".into()
            }
        );
        assert_eq!(
            parsear_numero("12.5")
                .unwrap()
                .comparar(&parsear_numero("12.50").unwrap()),
            Ordering::Equal
        );
        assert_eq!(
            parsear_numero("-1")
                .unwrap()
                .comparar(&parsear_numero("0").unwrap()),
            Ordering::Less
        );
        assert_eq!(
            parsear_numero("100")
                .unwrap()
                .comparar(&parsear_numero("99.999").unwrap()),
            Ordering::Greater
        );
        assert!(parsear_numero(".").is_none());
        assert!(lexico_valido("int", "2147483647"));
        assert!(!lexico_valido("int", "2147483648"));
        assert!(lexico_valido("long", "-9223372036854775808"));
        assert!(!lexico_valido("unsignedInt", "-1"));
        assert!(!lexico_valido("integer", "1 2"));
    }

    #[test]
    fn fechas() {
        assert!(parsear_fecha("2026-02-28", false).is_some());
        assert!(parsear_fecha("2026-02-30", false).is_none());
        assert!(parsear_fecha("2024-02-29", false).is_some());
        assert!(parsear_fecha("2026-01-01T24:00:00", true).is_some());
        assert!(parsear_fecha("2026-01-01T24:00:01", true).is_none());
        assert!(parsear_fecha("2026-01-01", true).is_none());
        let a = parsear_fecha("2026-01-01T12:00:00+03:00", true).unwrap();
        let b = parsear_fecha("2026-01-01T09:00:00Z", true).unwrap();
        assert_eq!(a.comparar(&b), Ordering::Equal);
    }

    #[test]
    fn base64() {
        assert!(base64_valido("aG9sYQ=="));
        assert!(base64_valido("aG9s YQ=="));
        assert!(!base64_valido("aG9sYQ=a"));
        assert!(!base64_valido("aG9sYQ="));
    }
}
