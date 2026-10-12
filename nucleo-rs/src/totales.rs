//! Totales de un documento, idénticos en resultado a `core/dte.py::calcular_totales` y a
//! `nucleo/totales` (Go). Reglas (`docs/DORADO.md` §1): montos enteros en pesos; redondeo
//! half-up sobre la representación decimal más corta del float (como `Decimal(str(x))` en
//! Python); en boletas el precio es bruto (IVA incluido) y el neto se deriva; el descuento por
//! monto se resta sin redondear y el ítem entra al total truncado hacia cero (`int()`).

pub const TASA_IVA: i64 = 19;

#[derive(Debug, Clone, Copy, Default)]
pub struct Item {
    pub cantidad: f64,
    pub precio_unitario: f64,
    pub descuento_pct: f64,
    pub descuento_monto: f64,
    pub exento: bool,
}

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct Totales {
    pub monto_neto: i64,
    pub monto_exento: i64,
    pub iva_tasa: i64,
    pub iva_monto: i64,
    pub monto_total: i64,
}

impl Totales {
    /// El `totales.json` del corpus dorado: la forma exacta de `json.MarshalIndent(tot, "", " ")`.
    pub fn json(&self) -> String {
        format!(
            "{{\n \"monto_neto\": {},\n \"monto_exento\": {},\n \"iva_tasa\": {},\n \"iva_monto\": {},\n \"monto_total\": {}\n}}",
            self.monto_neto, self.monto_exento, self.iva_tasa, self.iva_monto, self.monto_total
        )
    }
}

/// `repr(float)` de Python: la representación decimal más corta que reconstruye el float.
/// `Debug` de f64 en Rust usa el mismo algoritmo y los mismos umbrales para la notación
/// exponencial (|x| < 1e-4 o >= 1e16); solo difiere en cómo escribe el exponente, y eso se
/// ajusta aquí ("1e16" → "1e+16", "1e-5" → "1e-05").
pub fn py_repr(v: f64) -> String {
    let s = format!("{:?}", v);
    match s.find('e') {
        None => s,
        Some(k) => {
            let (mant, exp) = s.split_at(k);
            let exp = &exp[1..];
            let (signo, digitos) = match exp.strip_prefix('-') {
                Some(d) => ("-", d),
                None => ("+", exp),
            };
            let digitos = if digitos.len() < 2 {
                format!("0{digitos}")
            } else {
                digitos.to_string()
            };
            // Python escribe la mantisa sin ".0" en notación exponencial.
            let mant = mant.strip_suffix(".0").unwrap_or(mant);
            format!("{mant}e{signo}{digitos}")
        }
    }
}

/// `int(Decimal(str(valor)).quantize(1, ROUND_HALF_UP))`: se parte de la representación
/// decimal más corta (la que imprime Python), no del binario del float.
pub fn redondear(v: f64) -> i64 {
    if !v.is_finite() {
        return 0;
    }
    let s = py_repr(v);
    if s.contains('e') {
        // |v| >= 1e16 es siempre entero exacto; |v| < 1e-4 redondea a 0.
        return if v.abs() >= 1.0 { v as i64 } else { 0 };
    }
    let (neg, s) = match s.strip_prefix('-') {
        Some(r) => (true, r),
        None => (false, s.as_str()),
    };
    let (entero, frac) = s.split_once('.').unwrap_or((s, ""));
    let mut n: i64 = entero.parse().unwrap_or(0);
    if frac.as_bytes().first().is_some_and(|d| *d >= b'5') {
        n += 1;
    }
    if neg {
        -n
    } else {
        n
    }
}

fn monto_item(it: &Item) -> f64 {
    redondear(it.cantidad * it.precio_unitario) as f64
}

fn monto_descuento(it: &Item) -> f64 {
    let m = monto_item(it);
    if it.descuento_monto > 0.0 {
        return it.descuento_monto;
    }
    if it.descuento_pct > 0.0 {
        return redondear(m * it.descuento_pct / 100.0) as f64;
    }
    0.0
}

/// `monto_item - monto_descuento` (float, sin redondear), como la propiedad `ItemDTE.monto_neto`.
pub fn monto_neto_item(it: &Item) -> f64 {
    monto_item(it) - monto_descuento(it)
}

pub fn es_boleta(tipo: i32) -> bool {
    tipo == 39 || tipo == 41
}

fn aplica_iva(tipo: i32) -> bool {
    matches!(tipo, 33 | 39 | 56 | 61 | 52)
}

fn doc_exento(tipo: i32) -> bool {
    tipo == 34 || tipo == 41
}

pub fn calcular(items: &[Item], tipo: i32) -> Totales {
    let (mut neto, mut exento, mut bruto) = (0i64, 0i64, 0i64);
    for it in items {
        let m = monto_neto_item(it) as i64; // int(): trunca hacia cero
        if it.exento || doc_exento(tipo) {
            exento += m;
        } else if es_boleta(tipo) {
            bruto += m;
        } else {
            neto += m;
        }
    }
    let mut t = Totales {
        iva_tasa: TASA_IVA,
        monto_exento: exento,
        ..Default::default()
    };
    if es_boleta(tipo) && bruto > 0 {
        t.monto_neto = redondear(bruto as f64 / (1.0 + TASA_IVA as f64 / 100.0));
        t.iva_monto = bruto - t.monto_neto;
        t.monto_total = bruto + exento;
        return t;
    }
    t.monto_neto = neto;
    if aplica_iva(tipo) && neto > 0 {
        t.iva_monto = redondear((neto * TASA_IVA) as f64 / 100.0);
    }
    t.monto_total = neto + exento + t.iva_monto;
    t
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn repr_como_python() {
        assert_eq!(py_repr(1190.0), "1190.0");
        assert_eq!(py_repr(0.1 + 0.2), "0.30000000000000004");
        assert_eq!(py_repr(12.5), "12.5");
        assert_eq!(py_repr(1e16), "1e+16");
        assert_eq!(py_repr(1e-5), "1e-05");
    }

    #[test]
    fn redondeo_half_up_sobre_decimal() {
        assert_eq!(redondear(2.5), 3);
        assert_eq!(redondear(-2.5), -3);
        assert_eq!(redondear(1000.49), 1000);
        assert_eq!(redondear(1000.5), 1001);
        // 1.005 en binario es 1.00499…; Python parte del texto "1.005" → 1.01 → aquí quantize(1) = 1
        assert_eq!(redondear(1.005), 1);
        assert_eq!(redondear(0.5), 1);
        assert_eq!(redondear(2.675 * 100.0), 268); // 2.675*100 da 267.5 en binario: Python lo imprime "267.5" y sube
    }

    #[test]
    fn boleta_cafe() {
        let t = calcular(
            &[Item {
                cantidad: 1.0,
                precio_unitario: 1190.0,
                ..Default::default()
            }],
            39,
        );
        assert_eq!(
            t,
            Totales {
                monto_neto: 1000,
                monto_exento: 0,
                iva_tasa: 19,
                iva_monto: 190,
                monto_total: 1190
            }
        );
    }
}
