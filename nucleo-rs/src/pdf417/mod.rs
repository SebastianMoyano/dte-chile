//! Codificador PDF417, port fiel de pdf417gen (Python), la librería con que el motor dibuja el
//! timbre del SII, vía `nucleo/pdf417` (Go). Las tablas (`tablas.rs`) se generan desde
//! pdf417gen, y el test exige que las filas de códigos sean idénticas a las de Python para un
//! juego de entradas (`testdata/pdf417.json`): mismo timbre, módulo por módulo.
//!
//! Por qué un port y no una librería: la guía del SII pide nivel de corrección 5 y el timbre se
//! lee con cualquier lector; con el port, el timbre es el mismo que el de Python, que sí se lee
//! (verificado con pdf417decoder).

mod tablas;

use tablas::{CARACTERES, CODIGOS, FACTORES_EC, SWITCH_CODES};

const INICIO: u32 = 0x1fea8;
const FIN: u32 = 0x3fa29;
const RELLENO: u32 = 900;
const MAX_PALABRAS: usize = 928;
const MIN_FILAS: usize = 3;
const MAX_FILAS: usize = 90;
const LATCH_TEXTO: u32 = 900;
const LATCH_BYTES: u32 = 901;
const LATCH_BYTES6: u32 = 924;
const LATCH_NUMEROS: u32 = 902;
const PAD_INTERINO: i32 = 29;

const UPPER: usize = 0;
const LOWER: usize = 1;
const MIXED: usize = 2;
const PUNCT: usize = 3;

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
enum Modo {
    Texto,
    Numeros,
    Bytes,
}

fn tabla_texto(c: u8) -> Option<[i32; 4]> {
    if c < 128 {
        CARACTERES[c as usize]
    } else {
        None
    }
}

fn modo_optimo(c: u8) -> Modo {
    if c.is_ascii_digit() {
        return Modo::Numeros;
    }
    if tabla_texto(c).is_some() {
        return Modo::Texto;
    }
    Modo::Bytes
}

/// `pdf417gen.compaction.compact`.
fn compactar(datos: &[u8]) -> Vec<u32> {
    // trozos por modo óptimo (groupby)
    let mut trozos: Vec<(Vec<u8>, Modo)> = Vec::new();
    for &c in datos {
        let m = modo_optimo(c);
        match trozos.last_mut() {
            Some((d, fm)) if *fm == m => d.push(c),
            _ => trozos.push((vec![c], m)),
        }
    }
    // numéricos cortos (<13) pegados a texto pasan a texto (se mira la lista ORIGINAL)
    let mut reemplazados = trozos.clone();
    for i in 0..trozos.len() {
        if trozos[i].1 == Modo::Numeros && trozos[i].0.len() < 13 {
            let bordea = (i > 0 && trozos[i - 1].1 == Modo::Texto)
                || (i + 1 < trozos.len() && trozos[i + 1].1 == Modo::Texto);
            if bordea {
                reemplazados[i].1 = Modo::Texto;
            }
        }
    }
    // fusionar consecutivos del mismo modo
    let mut fusionados: Vec<(Vec<u8>, Modo)> = Vec::new();
    for (d, m) in reemplazados {
        match fusionados.last_mut() {
            Some((fd, fm)) if *fm == m => fd.extend(d),
            _ => fusionados.push((d, m)),
        }
    }
    let mut out = Vec::new();
    for (i, (d, m)) in fusionados.iter().enumerate() {
        if i > 0 || *m != Modo::Texto {
            out.push(match m {
                Modo::Texto => LATCH_TEXTO,
                Modo::Bytes => {
                    if d.len() % 6 == 0 {
                        LATCH_BYTES6
                    } else {
                        LATCH_BYTES
                    }
                }
                Modo::Numeros => LATCH_NUMEROS,
            });
        }
        match m {
            Modo::Texto => out.extend(compactar_texto(d)),
            Modo::Numeros => out.extend(compactar_numeros(d)),
            Modo::Bytes => out.extend(compactar_bytes(d)),
        }
    }
    out
}

fn submodo_de(c: u8) -> usize {
    let v = tabla_texto(c).unwrap_or([-1; 4]);
    for m in [LOWER, UPPER, MIXED, PUNCT] {
        // preferencia de pdf417gen
        if v[m] >= 0 {
            return m;
        }
    }
    UPPER
}

fn compactar_texto(datos: &[u8]) -> Vec<u32> {
    let mut interinos: Vec<i32> = Vec::new();
    let mut sub = UPPER;
    for &c in datos {
        let v = tabla_texto(c).unwrap_or([-1; 4]);
        if v[sub] < 0 {
            let prev = sub;
            sub = submodo_de(c);
            interinos.extend_from_slice(SWITCH_CODES[prev][sub]);
        }
        interinos.push(v[sub]);
    }
    let mut out = Vec::new();
    let mut i = 0;
    while i < interinos.len() {
        let a = interinos[i];
        let b = if i + 1 < interinos.len() {
            interinos[i + 1]
        } else {
            PAD_INTERINO
        };
        out.push((30 * a + b) as u32);
        i += 2;
    }
    out
}

/// Convierte un número decimal (dígitos ASCII) a dígitos en base 900, el más significativo
/// primero (división larga sobre el texto: hasta 45 dígitos, más que un u128).
fn decimal_a_base900(digitos: &[u8]) -> Vec<u32> {
    let mut num: Vec<u32> = digitos
        .iter()
        .skip_while(|&&d| d == b'0')
        .map(|d| (d - b'0') as u32)
        .collect();
    let mut out = Vec::new();
    while !num.is_empty() {
        let mut resto = 0u32;
        let mut cociente = Vec::with_capacity(num.len());
        for &d in &num {
            let cur = resto * 10 + d;
            let q = cur / 900;
            resto = cur % 900;
            if !(cociente.is_empty() && q == 0) {
                cociente.push(q);
            }
        }
        out.push(resto);
        num = cociente;
    }
    out.reverse();
    out
}

fn compactar_numeros(datos: &[u8]) -> Vec<u32> {
    let mut out = Vec::new();
    for tr in datos.chunks(44) {
        let mut con_uno = Vec::with_capacity(tr.len() + 1);
        con_uno.push(b'1');
        con_uno.extend_from_slice(tr);
        out.extend(decimal_a_base900(&con_uno));
    }
    out
}

fn compactar_bytes(datos: &[u8]) -> Vec<u32> {
    let mut out = Vec::new();
    for tr in datos.chunks(6) {
        if tr.len() == 6 {
            let mut v: u64 = 0;
            for &b in tr {
                v = (v << 8) | b as u64;
            }
            let mut d = Vec::new();
            while v > 0 {
                d.push((v % 900) as u32);
                v /= 900;
            }
            d.reverse();
            while d.len() < 5 {
                d.insert(0, 0);
            }
            out.extend(d);
        } else {
            out.extend(tr.iter().map(|&c| c as u32));
        }
    }
    out
}

/// `compute_error_correction_code_words` (Reed-Solomon sobre GF(929)).
fn correccion(palabras: &[u32], nivel: usize) -> Vec<u32> {
    let f = FACTORES_EC[nivel];
    let n = 1usize << (nivel + 1);
    let mut ec = vec![0i64; n];
    for &p in palabras {
        let t = (p as i64 + ec[n - 1]) % 929;
        for x in (0..n).rev() {
            let w = if x > 0 { ec[x - 1] } else { 0 };
            ec[x] = (w + 929 - (t * f[x] as i64) % 929) % 929;
        }
    }
    (0..n)
        .map(|i| {
            let v = ec[n - 1 - i];
            (if v > 0 { 929 - v } else { v }) as u32
        })
        .collect()
}

fn indicador_izq(fila: usize, filas: usize, cols: usize, nivel: usize) -> usize {
    let x = match fila % 3 {
        0 => (filas - 1) / 3,
        1 => nivel * 3 + (filas - 1) % 3,
        _ => cols - 1,
    };
    30 * (fila / 3) + x
}

fn indicador_der(fila: usize, filas: usize, cols: usize, nivel: usize) -> usize {
    let x = match fila % 3 {
        0 => cols - 1,
        1 => (filas - 1) / 3,
        _ => nivel * 3 + (filas - 1) % 3,
    };
    30 * (fila / 3) + x
}

/// `pdf417gen.encode`: filas de códigos de bajo nivel (patrones de barras), con `columnas`
/// columnas de datos (1-30) y nivel de seguridad 0-8.
pub fn codificar(datos: &[u8], columnas: usize, nivel: usize) -> Result<Vec<Vec<u32>>, String> {
    if !(1..=30).contains(&columnas) {
        return Err(format!(
            "'columns' must be between 1 and 30. Given: {columnas}"
        ));
    }
    if nivel > 8 {
        return Err(format!(
            "'security_level' must be between 1 and 8. Given: {nivel}"
        ));
    }
    let palabras = compactar(datos);
    let ec_n = 1usize << (nivel + 1);
    let total = palabras.len() + ec_n + 1;
    let pad = match total % columnas {
        0 => 0,
        m => columnas - m,
    };
    let descriptor = palabras.len() + pad + 1;
    let filas = (palabras.len() + ec_n + pad + 1).div_ceil(columnas);
    if descriptor > MAX_PALABRAS {
        return Err("Data too long".into());
    }
    if filas < MIN_FILAS {
        return Err(format!("Generated bar code has {filas} rows. Minimum is {MIN_FILAS} rows. Try decreasing column count."));
    }
    if filas > MAX_FILAS {
        return Err(format!("Generated bar code has {filas} rows. Maximum is {MAX_FILAS} rows. Try increasing column count."));
    }
    let mut ext = Vec::with_capacity(descriptor + ec_n);
    ext.push(descriptor as u32);
    ext.extend_from_slice(&palabras);
    ext.extend(std::iter::repeat_n(RELLENO, pad));
    let ec = correccion(&ext, nivel);
    ext.extend(ec);
    let mut out = Vec::with_capacity(filas);
    for r in 0..filas {
        let tabla = &CODIGOS[r % 3];
        let mut fila = Vec::with_capacity(columnas + 4);
        fila.push(INICIO);
        fila.push(tabla[indicador_izq(r, filas, columnas, nivel)]);
        for c in 0..columnas {
            fila.push(tabla[ext[r * columnas + c] as usize]);
        }
        fila.push(tabla[indicador_der(r, filas, columnas, nivel)]);
        fila.push(FIN);
        out.push(fila);
    }
    Ok(out)
}

/// Imagen en gris de 8 bits (0 = barra, 255 = fondo): ancho, alto y píxeles por filas.
pub struct Imagen {
    pub ancho: usize,
    pub alto: usize,
    pub pix: Vec<u8>,
}

/// `render_image`: módulo de `escala` px de ancho y `escala*razon` px de alto, con un margen
/// `margen` px en blanco.
pub fn imagen(filas: &[Vec<u32>], escala: usize, razon: usize, margen: usize) -> Imagen {
    let ancho_mod = filas.first().map_or(0, |f| f.len()) * 17 + 1;
    let ancho = ancho_mod * escala + 2 * margen;
    let alto = filas.len() * escala * razon + 2 * margen;
    let mut pix = vec![255u8; ancho * alto];
    for (y, fila) in filas.iter().enumerate() {
        let mut x = 0usize;
        for &v in fila {
            let nbits = 32 - v.leading_zeros() as usize;
            for b in (0..nbits).rev() {
                if v & (1 << b) != 0 {
                    for dy in 0..escala * razon {
                        let py = margen + y * escala * razon + dy;
                        for dx in 0..escala {
                            pix[py * ancho + margen + x * escala + dx] = 0;
                        }
                    }
                }
                x += 1;
            }
        }
    }
    Imagen { ancho, alto, pix }
}

/// Las barras de cada fila como tramos `(columna_inicio, largo)` en módulos: lo que el PDF
/// dibuja como rectángulos (barras contiguas en un solo rectángulo).
pub fn tramos(fila: &[u32]) -> Vec<(usize, usize)> {
    let mut out = Vec::new();
    let mut col = 0usize;
    for &v in fila {
        let nbits = 32 - v.leading_zeros() as usize;
        let mut b = nbits;
        while b > 0 {
            b -= 1;
            if v & (1 << b) != 0 {
                let ini = col;
                while b > 0 && v & (1 << (b - 1)) != 0 {
                    b -= 1;
                    col += 1;
                }
                out.push((ini, col - ini + 1));
            }
            col += 1;
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[derive(serde::Deserialize)]
    struct Vector {
        datos: String,
        columnas: usize,
        seguridad: usize,
        #[serde(default)]
        filas: Vec<Vec<u32>>,
        #[serde(default)]
        error: String,
    }

    /// Las filas de códigos deben ser idénticas a las de pdf417gen para cada vector
    /// (testdata/pdf417.json, generado por tools/generar_pdf417.py). L15.
    #[test]
    fn paridad_con_python() {
        let ruta = format!("{}/testdata/pdf417.json", env!("CARGO_MANIFEST_DIR"));
        let vec: Vec<Vector> = serde_json::from_slice(&std::fs::read(ruta).unwrap()).unwrap();
        let mut ok = 0;
        for (i, v) in vec.iter().enumerate() {
            let r = codificar(v.datos.as_bytes(), v.columnas, v.seguridad);
            if !v.error.is_empty() {
                assert!(
                    r.is_err(),
                    "vector {i}: Python falló ({}) y Rust no",
                    v.error
                );
                continue;
            }
            let filas = r.unwrap_or_else(|e| panic!("vector {i}: {e}"));
            assert_eq!(
                filas,
                v.filas,
                "vector {i} ({} bytes, {} cols, sec {}): filas distintas",
                v.datos.len(),
                v.columnas,
                v.seguridad
            );
            ok += 1;
        }
        eprintln!("vectores idénticos: {ok} de {}", vec.len());
        let img = imagen(&codificar(b"hola mundo", 12, 5).unwrap(), 2, 3, 20);
        assert_eq!(img.ancho, (16 * 17 + 1) * 2 + 40);
    }

    #[test]
    fn base900() {
        assert_eq!(decimal_a_base900(b"1234567"), vec![1, 471, 667]); // 1*810000 + 471*900 + 667
        assert_eq!(decimal_a_base900(b"0"), Vec::<u32>::new());
    }
}
