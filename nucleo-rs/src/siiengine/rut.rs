//! `core/rut.py` para el SII engine: separar, validar y formatear RUT (módulo 11).

/// `separar_rut`: "12.345.678-9" → ("12345678", "9"). Sin DV → ("", "").
pub fn separar_rut(rut: &str) -> (String, String) {
    let s: String = rut
        .chars()
        .filter(|c| c.is_ascii_digit() || *c == 'k' || *c == 'K')
        .collect::<String>()
        .to_uppercase();
    if s.len() < 2 {
        return (String::new(), String::new());
    }
    (s[..s.len() - 1].to_string(), s[s.len() - 1..].to_string())
}

/// DV por módulo 11 (`core/rut.py::calcular_dv`).
pub fn digito_verificador(numero: &str) -> String {
    let (mut suma, mut mult) = (0u32, 2u32);
    for c in numero.bytes().rev() {
        suma += (c - b'0') as u32 * mult;
        mult += 1;
        if mult > 7 {
            mult = 2;
        }
    }
    match 11 - suma % 11 {
        11 => "0".into(),
        10 => "K".into(),
        r => r.to_string(),
    }
}

/// `core/rut.py::validar_rut`.
pub fn validar_rut(rut: &str) -> bool {
    let (n, dv) = separar_rut(rut);
    if n.is_empty() || !n.bytes().all(|c| c.is_ascii_digit()) {
        return false;
    }
    digito_verificador(&n) == dv
}

/// `core/rut.py::formatear_rut`: con puntos "12.345.678-9", sin puntos "12345678-9". Un RUT que
/// no se puede separar vuelve tal cual (como Python).
pub fn formatear_rut(rut: &str, con_puntos: bool) -> String {
    let (n, dv) = separar_rut(rut);
    if n.is_empty() {
        return rut.to_string();
    }
    if !con_puntos {
        return format!("{n}-{dv}");
    }
    let mut b = String::new();
    let len = n.len();
    for (i, c) in n.chars().enumerate() {
        if i > 0 && (len - i).is_multiple_of(3) {
            b.push('.');
        }
        b.push(c);
    }
    format!("{b}-{dv}")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rut() {
        assert_eq!(
            separar_rut("12.345.678-5"),
            ("12345678".to_string(), "5".to_string())
        );
        assert!(
            validar_rut("12.345.678-5")
                && validar_rut("77777777-7")
                && validar_rut("76111111-6")
                && !validar_rut("12345678-9")
        );
        assert_eq!(formatear_rut("12345678-5", true), "12.345.678-5");
        assert_eq!(formatear_rut("12.345.678-5", false), "12345678-5");
        assert_eq!(digito_verificador("77777777"), "7");
        assert_eq!(digito_verificador("12345678"), "5");
    }
}
