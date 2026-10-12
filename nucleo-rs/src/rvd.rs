//! `core/rvd.py`: el Registro de Ventas Diario (RVD, antes RCOF) de boletas, el
//! `<ConsumoFolios>` que quien emite boletas debe mandar TODOS los días (Res. Ex. SII N° 74 de
//! 2020, dentro de las 12 horas del día siguiente, incluso en cero). Transcripción de
//! `nucleo/rvd` (Go).
//!
//! Viaja por el canal de FACTURAS (DTEUpload + token SOAP, maullin/palena), NO por el REST de
//! boletas: lo dice el OpenAPI oficial del SII y lo confirma el Instructivo Técnico.

use crate::almacen::{self, Almacen};
use crate::c14n::Alcance;
use crate::firma::Certificado;
use crate::sii;
use crate::xsd;
use rusqlite::params;
use std::fmt::Write as _;

const NS_SII: &str = "http://www.sii.cl/SiiDte";
const NS_XSI: &str = "http://www.w3.org/2001/XMLSchema-instance";
const XSD_REF: &str = "http://www.sii.cl/SiiDte ConsumoFolio_v10.xsd";
const TASA_IVA: i64 = 19;
const DECL_ISO: &str = "<?xml version=\"1.0\" encoding=\"ISO-8859-1\"?>\n";

/// El XSD (TipoConsumoType) solo acepta estos tres; por eso Resumen tiene maxOccurs=3.
pub const TIPOS_CONSUMO: [i32; 3] = [39, 41, 61];

/// Una fila de `dtes` del día (tipo, folio, montos, estado).
#[derive(Debug, Clone, Default, serde::Deserialize)]
#[serde(default)]
pub struct Boleta {
    pub tipo_dte: i32,
    pub folio: i32,
    pub monto_neto: i64,
    pub iva: i64,
    pub monto_exento: i64,
    pub monto_total: i64,
    pub estado: String,
}

/// Parámetros de `generar_consumo_folios`.
#[derive(Debug, Clone, Default, serde::Deserialize)]
#[serde(default)]
pub struct Parametros {
    pub rut_emisor: String,
    pub rut_envia: String,
    pub fecha_resolucion: String,
    pub numero_resolucion: i64,
    /// YYYY-MM-DD
    pub dia: String,
    /// los que no tuvieron movimiento igual van, en cero
    pub tipos: Vec<i32>,
    /// 1 la primera vez; para CORREGIR se reenvía completo con +1
    pub sec_envio: i32,
    pub correlativo: Option<i64>,
    /// TmstFirmaEnv (reloj único)
    pub marca: String,
    pub documentos: Vec<Boleta>,
}

/// `agrupar_rangos`: folios ordenados → rangos [inicial, final] consecutivos.
pub fn agrupar_rangos(folios: &[i32]) -> Vec<(i32, i32)> {
    if folios.is_empty() {
        return Vec::new();
    }
    let mut f = folios.to_vec();
    f.sort_unstable();
    let mut out = Vec::new();
    let (mut ini, mut fin) = (f[0], f[0]);
    for &x in &f[1..] {
        if x == fin || x == fin + 1 {
            fin = x;
            continue;
        }
        out.push((ini, fin));
        ini = x;
        fin = x;
    }
    out.push((ini, fin));
    out
}

fn txt(b: &mut String, tag: &str, v: impl std::fmt::Display) {
    let _ = write!(b, "<{tag}>{v}</{tag}>");
}

fn resumen(b: &mut String, tipo: i32, docs: &[&Boleta]) {
    let (emitidos, anulados): (Vec<&Boleta>, Vec<&Boleta>) = docs
        .iter()
        .partition(|d| d.estado.to_lowercase() != "anulado");
    let (mut neto, mut iva, mut exento, mut total) = (0i64, 0i64, 0i64, 0i64);
    for d in &emitidos {
        // solo lo efectivamente emitido (lo anulado no vendió nada)
        neto += d.monto_neto;
        iva += d.iva;
        exento += d.monto_exento;
        total += d.monto_total;
    }
    b.push_str("<Resumen>");
    txt(b, "TipoDocumento", tipo);
    if neto != 0 {
        txt(b, "MntNeto", neto);
    }
    if iva != 0 {
        txt(b, "MntIva", iva);
        txt(b, "TasaIVA", TASA_IVA);
    }
    if exento != 0 {
        txt(b, "MntExento", exento);
    }
    txt(b, "MntTotal", total);
    txt(b, "FoliosEmitidos", emitidos.len());
    txt(b, "FoliosAnulados", anulados.len());
    txt(b, "FoliosUtilizados", emitidos.len() + anulados.len()); // los anulados igual consumieron folio
    let folios = |ds: &[&Boleta]| ds.iter().map(|d| d.folio).collect::<Vec<_>>();
    for (ini, fin) in agrupar_rangos(&folios(&emitidos)) {
        b.push_str("<RangoUtilizados>");
        txt(b, "Inicial", ini);
        txt(b, "Final", fin);
        b.push_str("</RangoUtilizados>");
    }
    for (ini, fin) in agrupar_rangos(&folios(&anulados)) {
        b.push_str("<RangoAnulados>");
        txt(b, "Inicial", ini);
        txt(b, "Final", fin);
        b.push_str("</RangoAnulados>");
    }
    b.push_str("</Resumen>");
}

/// El ID del `<DocumentoConsumoFolios>` ("RVD" + YYYYMMDD).
pub fn id_documento(dia: &str) -> String {
    format!("RVD{}", dia.replace('-', ""))
}

/// `generar_consumo_folios` serializado como lxml (sin declaración): el XML SIN firmar.
pub fn generar(p: &Parametros) -> Result<String, String> {
    let tipos: Vec<i32> = if p.tipos.is_empty() {
        TIPOS_CONSUMO.to_vec()
    } else {
        p.tipos.clone()
    };
    for t in &tipos {
        if !TIPOS_CONSUMO.contains(t) {
            return Err(format!(
                "el consumo de folios solo admite los tipos {TIPOS_CONSUMO:?}; recibido: {t}"
            ));
        }
    }
    if p.dia.is_empty() {
        return Err("sin documentos no se puede deducir el día del consumo: pasar Dia".into());
    }
    let sec = if p.sec_envio == 0 { 1 } else { p.sec_envio };
    let mut b = String::new();
    let _ = write!(b, "<ConsumoFolios xmlns=\"{NS_SII}\" xmlns:xsi=\"{NS_XSI}\" version=\"1.0\" xsi:schemaLocation=\"{XSD_REF}\">");
    let _ = write!(
        b,
        "<DocumentoConsumoFolios ID=\"{}\">",
        id_documento(&p.dia)
    );
    b.push_str("<Caratula version=\"1.0\">");
    txt(&mut b, "RutEmisor", &p.rut_emisor);
    txt(&mut b, "RutEnvia", &p.rut_envia);
    txt(&mut b, "FchResol", &p.fecha_resolucion);
    txt(&mut b, "NroResol", p.numero_resolucion);
    txt(&mut b, "FchInicio", &p.dia);
    txt(&mut b, "FchFinal", &p.dia);
    if let Some(c) = p.correlativo {
        txt(&mut b, "Correlativo", c);
    }
    txt(&mut b, "SecEnvio", sec);
    txt(&mut b, "TmstFirmaEnv", &p.marca);
    b.push_str("</Caratula>");
    for t in tipos {
        let docs: Vec<&Boleta> = p.documentos.iter().filter(|d| d.tipo_dte == t).collect();
        resumen(&mut b, t, &docs);
    }
    b.push_str("</DocumentoConsumoFolios></ConsumoFolios>");
    Ok(b)
}

/// `firmar_xml_sii(raiz, cert, uri="#RVD…")` + la declaración con comillas DOBLES (la de lxml
/// va con simples y DTEUpload la rechaza con CHR-00001). Devuelve ISO-8859-1.
pub fn firmar(cert: &Certificado, sin_firma: &str) -> Result<Vec<u8>, String> {
    let ini = sin_firma
        .find("<DocumentoConsumoFolios ")
        .ok_or("no se encontró <DocumentoConsumoFolios>")?;
    let fin = sin_firma
        .find("</DocumentoConsumoFolios>")
        .ok_or("no se encontró <DocumentoConsumoFolios>")?
        + "</DocumentoConsumoFolios>".len();
    let doc = &sin_firma[ini..fin];
    let id_ini = doc.find("ID=\"").ok_or("sin ID")? + 4;
    let id = &doc[id_ini..id_ini + doc[id_ini..].find('"').ok_or("ID sin cerrar")?];
    // El SII (Santuario) canonicaliza el subárbol con los namespaces EN ALCANCE heredados en el
    // ápice (SiiDte y xsi): es `_c14n_reparse`; el SignedInfo cuelga de <Signature xmlns=dsig>
    // bajo la raíz con xsi. Mismo método que el sobre, verificado contra el SII vivo.
    let mut ns_ref = Alcance::new();
    ns_ref.insert(String::new(), NS_SII.into());
    ns_ref.insert("xsi".into(), NS_XSI.into());
    let mut ns_si = Alcance::new();
    ns_si.insert("xsi".into(), NS_XSI.into());
    let sig = cert.signature(&format!("#{id}"), doc, &ns_ref, &ns_si)?;
    let cierre = "</ConsumoFolios>";
    let cuerpo = sin_firma
        .strip_suffix(cierre)
        .ok_or_else(|| format!("el XML no termina en {cierre}"))?;
    let final_ = format!("{cuerpo}{sig}{cierre}");
    let mut out = DECL_ISO.as_bytes().to_vec();
    out.extend(crate::ted::latin1(&final_)?);
    Ok(out)
}

/// Genera, firma y valida contra el XSD (ConsumoFolio_v10.xsd).
pub fn generar_firmado(cert: &Certificado, p: &Parametros) -> Result<Vec<u8>, String> {
    let sin_firma = generar(p)?;
    let xml = firmar(cert, &sin_firma)?;
    xsd::validar_error(&xml)?;
    Ok(xml)
}

/// Sube el RVD por DTEUpload (canal de FACTURAS) y devuelve `(TrackID, mensaje)`.
pub fn enviar(
    cli: &mut sii::http::Cliente,
    xml_rvd: &[u8],
    rut_emisor: &str,
) -> Result<(i64, String), String> {
    let (n, dv) = rut_emisor
        .split_once('-')
        .ok_or_else(|| format!("RUT sin DV: {rut_emisor:?}"))?;
    let (track, _) = cli.enviar_dte(xml_rvd, n, dv).map_err(|e| e.to_string())?;
    Ok((track, format!("RVD recibido. TrackID: {track}")))
}

// ---------------------------------------------------------------- base de datos

fn marcadores(n: usize) -> String {
    vec!["?"; n].join(",")
}

/// Lee de `dtes` las boletas (39/41/61) de `rut` en `dia`, ordenadas por tipo y folio.
pub fn boletas_del_dia(
    al: &Almacen,
    rut: &str,
    dia: &str,
    ambiente: &str,
) -> almacen::Resultado<Vec<Boleta>> {
    let mut q = format!(
        "SELECT tipo_dte, folio, COALESCE(monto_neto,0), COALESCE(monto_exento,0), COALESCE(iva,0), COALESCE(monto_total,0), COALESCE(estado,'') FROM dtes WHERE rut_emisor=? AND fecha_emision=? AND tipo_dte IN ({})",
        marcadores(TIPOS_CONSUMO.len())
    );
    let mut args: Vec<rusqlite::types::Value> =
        vec![rut.to_string().into(), dia.to_string().into()];
    for t in TIPOS_CONSUMO {
        args.push(t.into());
    }
    if !ambiente.is_empty() {
        q.push_str(" AND ambiente=?");
        args.push(ambiente.to_string().into());
    }
    q.push_str(" ORDER BY tipo_dte, folio");
    let c = al.conexion();
    let mut st = c.prepare(&q)?;
    let filas = st
        .query_map(rusqlite::params_from_iter(args), |r| {
            Ok(Boleta {
                tipo_dte: r.get(0)?,
                folio: r.get(1)?,
                monto_neto: r.get(2)?,
                monto_exento: r.get(3)?,
                iva: r.get(4)?,
                monto_total: r.get(5)?,
                estado: r.get(6)?,
            })
        })?
        .collect::<Result<Vec<_>, _>>()?;
    Ok(filas)
}

/// Días (YYYY-MM-DD) entre desde y hasta, inclusive, con boletas de `rut`.
pub fn dias_con_boletas(
    al: &Almacen,
    rut: &str,
    desde: &str,
    hasta: &str,
    ambiente: &str,
) -> almacen::Resultado<Vec<String>> {
    let mut q = format!("SELECT DISTINCT fecha_emision FROM dtes WHERE rut_emisor=? AND fecha_emision BETWEEN ? AND ? AND tipo_dte IN ({})", marcadores(TIPOS_CONSUMO.len()));
    let mut args: Vec<rusqlite::types::Value> = vec![
        rut.to_string().into(),
        desde.to_string().into(),
        hasta.to_string().into(),
    ];
    for t in TIPOS_CONSUMO {
        args.push(t.into());
    }
    if !ambiente.is_empty() {
        q.push_str(" AND ambiente=?");
        args.push(ambiente.to_string().into());
    }
    q.push_str(" ORDER BY fecha_emision");
    let c = al.conexion();
    let mut st = c.prepare(&q)?;
    let dias = st
        .query_map(rusqlite::params_from_iter(args), |r| r.get::<_, String>(0))?
        .map(|d| {
            d.map(|s| {
                if s.len() >= 10 {
                    s[..10].to_string()
                } else {
                    s
                }
            })
        })
        .collect::<Result<Vec<_>, _>>()?;
    Ok(dias)
}

/// Una fila de `rvd_envios`.
#[derive(Debug, Clone, Default, serde::Serialize)]
pub struct Registro {
    pub id: i64,
    pub rut_emisor: String,
    pub fecha: String,
    pub sec_envio: i32,
    pub estado: String,
    pub track_id: String,
    pub xml_path: String,
    pub detalle: String,
}

/// El último registro del día (mayor sec_envio) o `None`.
pub fn registrado(al: &Almacen, rut: &str, dia: &str) -> almacen::Resultado<Option<Registro>> {
    use rusqlite::OptionalExtension;
    let c = al.conexion();
    Ok(c.query_row(
        "SELECT id, rut_emisor, fecha, sec_envio, estado, track_id, xml_path, detalle FROM rvd_envios WHERE rut_emisor=?1 AND fecha=?2 ORDER BY sec_envio DESC LIMIT 1",
        params![rut, dia],
        |r| {
            Ok(Registro {
                id: r.get(0)?,
                rut_emisor: r.get(1)?,
                fecha: r.get(2)?,
                sec_envio: r.get(3)?,
                estado: r.get(4)?,
                track_id: r.get::<_, Option<String>>(5)?.unwrap_or_default(),
                xml_path: r.get::<_, Option<String>>(6)?.unwrap_or_default(),
                detalle: r.get::<_, Option<String>>(7)?.unwrap_or_default(),
            })
        },
    )
    .optional()?)
}

/// Inserta o actualiza (UNIQUE rut, fecha, sec_envio): reintentar el mismo día actualiza la
/// fila en vez de duplicar el reporte.
#[allow(clippy::too_many_arguments)]
pub fn registrar(
    al: &Almacen,
    rut: &str,
    dia: &str,
    estado: &str,
    sec_envio: i32,
    track_id: &str,
    xml_path: &str,
    detalle: &str,
) -> almacen::Resultado<()> {
    let sec = if sec_envio == 0 { 1 } else { sec_envio };
    let ahora = almacen::ahora_iso();
    let ahora = &ahora[..19];
    let nil = |s: &str| {
        if s.is_empty() {
            None
        } else {
            Some(s.to_string())
        }
    };
    al.conexion().execute(
        "INSERT INTO rvd_envios (rut_emisor, fecha, sec_envio, estado, track_id, xml_path, detalle, creado_en, actualizado_en) VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?8) ON CONFLICT(rut_emisor, fecha, sec_envio) DO UPDATE SET estado=excluded.estado, track_id=excluded.track_id, xml_path=excluded.xml_path, detalle=excluded.detalle, actualizado_en=excluded.actualizado_en",
        params![rut, dia, sec, estado, nil(track_id), nil(xml_path), nil(detalle), ahora],
    )?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn comparar(que: &str, got: &str, esperado: &str) {
        if got != esperado {
            let i = got
                .bytes()
                .zip(esperado.bytes())
                .take_while(|(a, b)| a == b)
                .count();
            let lo = i.saturating_sub(80);
            panic!(
                "{que} difiere en el byte {i}\nesperado: …{}…\nobtenido: …{}…",
                &esperado[lo..(i + 80).min(esperado.len())],
                &got[lo..(i + 80).min(got.len())]
            );
        }
    }

    /// El ConsumoFolios sin firmar y firmado deben ser byte a byte los de Python
    /// (tests/dorado/rvd/, hora fija, certificado y boletas ficticios). L15.
    #[test]
    fn rvd_igual_a_python() {
        let base = format!("{}/../tests/dorado", env!("CARGO_MANIFEST_DIR"));
        let Ok(raw) = std::fs::read(format!("{base}/rvd/entrada.json")) else {
            return;
        };
        let p: Parametros = serde_json::from_slice(&raw).unwrap();
        let sin_firma = generar(&p).unwrap();
        let esperado = std::fs::read(format!("{base}/rvd/consumo_sin_firma.xml")).unwrap();
        let esperado = crate::ted::desde_latin1(&esperado);
        // lxml.tostring(encoding=…) antepone su declaración (comillas simples); generar no la lleva.
        comparar(
            "sin firma",
            &sin_firma,
            esperado
                .strip_prefix("<?xml version='1.0' encoding='ISO-8859-1'?>\n")
                .unwrap_or(&esperado),
        );
        let p12 = std::fs::read(format!("{base}/fixtures/cert_demo.p12")).unwrap();
        let cert = crate::firma::cargar_p12(&p12, "demo").unwrap();
        let firmado = generar_firmado(&cert, &p).unwrap();
        let esperado_f = std::fs::read(format!("{base}/rvd/consumo_firmado.xml")).unwrap();
        comparar(
            "firmado",
            &crate::ted::desde_latin1(&firmado),
            &crate::ted::desde_latin1(&esperado_f),
        );
    }

    #[test]
    fn rangos() {
        assert_eq!(
            agrupar_rangos(&[5, 1, 2, 3, 7, 8, 10]),
            vec![(1, 3), (5, 5), (7, 8), (10, 10)]
        );
        assert!(agrupar_rangos(&[]).is_empty());
    }

    #[test]
    fn registro_en_base() {
        let dir = std::env::temp_dir().join(format!("rvd-{}", std::process::id()));
        let _ = std::fs::create_dir_all(&dir);
        let al = Almacen::abrir_y_migrar(dir.join("t.db").to_str().unwrap()).unwrap();
        registrar(&al, "77777777-7", "2026-01-23", "enviado", 0, "123", "", "").unwrap();
        registrar(
            &al,
            "77777777-7",
            "2026-01-23",
            "aceptado",
            1,
            "123",
            "x.xml",
            "ok",
        )
        .unwrap();
        let r = registrado(&al, "77777777-7", "2026-01-23")
            .unwrap()
            .unwrap();
        assert_eq!(
            (r.sec_envio, r.estado.as_str(), r.xml_path.as_str()),
            (1, "aceptado", "x.xml")
        );
        assert!(registrado(&al, "77777777-7", "2026-01-24")
            .unwrap()
            .is_none());
        al.crear_dte(&almacen::Dte {
            tipo_dte: 39,
            folio: 1,
            rut_emisor: "77777777-7".into(),
            rut_receptor: "66666666-6".into(),
            fecha_emision: "2026-01-23".into(),
            monto_total: 1190,
            monto_neto: 1000,
            iva: 190,
            ambiente: "certificacion".into(),
            ..Default::default()
        })
        .unwrap();
        assert_eq!(
            boletas_del_dia(&al, "77777777-7", "2026-01-23", "certificacion")
                .unwrap()
                .len(),
            1
        );
        assert_eq!(
            dias_con_boletas(&al, "77777777-7", "2026-01-01", "2026-01-31", "").unwrap(),
            vec!["2026-01-23".to_string()]
        );
        let _ = std::fs::remove_dir_all(&dir);
    }
}
