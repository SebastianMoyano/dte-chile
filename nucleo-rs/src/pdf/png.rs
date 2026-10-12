//! Un codificador PNG mínimo (gris de 8 bits, sin filtro) para el timbre: IHDR + IDAT (zlib
//! vía flate2) + IEND, con el CRC32 de cada chunk.

use std::io::Write as _;

fn crc32(datos: &[u8]) -> u32 {
    let mut c = 0xFFFF_FFFFu32;
    for &b in datos {
        c ^= b as u32;
        for _ in 0..8 {
            c = if c & 1 != 0 {
                0xEDB8_8320 ^ (c >> 1)
            } else {
                c >> 1
            };
        }
    }
    c ^ 0xFFFF_FFFF
}

fn chunk(out: &mut Vec<u8>, tipo: &[u8; 4], datos: &[u8]) {
    out.extend((datos.len() as u32).to_be_bytes());
    let mut cuerpo = tipo.to_vec();
    cuerpo.extend(datos);
    out.extend(&cuerpo);
    out.extend(crc32(&cuerpo).to_be_bytes());
}

/// PNG en escala de grises (8 bits) de `ancho`×`alto` con los píxeles por filas.
pub fn gris(ancho: usize, alto: usize, pix: &[u8]) -> Vec<u8> {
    let mut crudo = Vec::with_capacity((ancho + 1) * alto);
    for fila in pix.chunks(ancho) {
        crudo.push(0); // filtro None
        crudo.extend(fila);
    }
    let mut enc = flate2::write::ZlibEncoder::new(Vec::new(), flate2::Compression::default());
    let _ = enc.write_all(&crudo);
    let idat = enc.finish().unwrap_or_default();
    let mut out = b"\x89PNG\r\n\x1a\n".to_vec();
    let mut ihdr = Vec::with_capacity(13);
    ihdr.extend((ancho as u32).to_be_bytes());
    ihdr.extend((alto as u32).to_be_bytes());
    ihdr.extend([8, 0, 0, 0, 0]); // 8 bits, gris, deflate, filtro adaptativo, sin entrelazado
    chunk(&mut out, b"IHDR", &ihdr);
    chunk(&mut out, b"IDAT", &idat);
    chunk(&mut out, b"IEND", &[]);
    out
}

#[cfg(test)]
mod tests {
    #[test]
    fn crc_conocido() {
        assert_eq!(super::crc32(b"IEND"), 0xAE42_6082);
    }
}
