//! `importar_emitidos`: mete el historial del SII engine en `dtes` (estado `emitido_mipyme`,
//! DHDR en `track_id`, ambiente producción; idempotente por rut/tipo/folio) y baja el PDF (y el
//! XML si se pide) de lo que no lo tenga.

use super::lectura::DocumentoEmitido;
use super::{formatear_rut, latin1, validar_rut, Cliente, Resultado};
use crate::almacen::{self, Almacen};
use regex::Regex;
use std::path::PathBuf;
use std::sync::OnceLock;
use std::time::Duration;

/// Lo que `importar` necesita del cliente (un trait para probar sin red).
pub trait Lector {
    fn descargar_pdf(&mut self, dhdr: &str) -> Resultado<Vec<u8>>;
    fn obtener_envio_xml(
        &mut self,
        dhdr: &str,
        tipo: i32,
        rut_receptor: &str,
    ) -> Resultado<Vec<u8>>;
}

impl Lector for Cliente {
    fn descargar_pdf(&mut self, dhdr: &str) -> Resultado<Vec<u8>> {
        Cliente::descargar_pdf(self, dhdr)
    }
    fn obtener_envio_xml(
        &mut self,
        dhdr: &str,
        tipo: i32,
        rut_receptor: &str,
    ) -> Resultado<Vec<u8>> {
        Cliente::obtener_envio_xml(self, dhdr, tipo, rut_receptor)
    }
}

/// Los parámetros de `importar_emitidos`.
#[derive(Debug, Clone, Default)]
pub struct OpcionesImportar {
    pub con_pdf: bool,
    /// exige la clave del certificado en el cliente
    pub con_xml: bool,
    /// raíz de storage (default "storage"): pdfs/mipyme/<rut>/ y dtes/mipyme/<rut>/
    pub carpeta: String,
    /// entre descargas
    pub pausa: Duration,
}

/// Cada entrada de `documentos` del resumen.
#[derive(Debug, Clone, Default, serde::Serialize)]
pub struct DocumentoImportado {
    pub tipo: i32,
    pub folio: i32,
    pub fecha: String,
    pub monto: i64,
    pub estado: String,
    pub dhdr: String,
    pub receptor: String,
}

/// El dict que devuelve `importar_emitidos` (mismas claves).
#[derive(Debug, Clone, Default, serde::Serialize)]
pub struct Resumen {
    pub listados: usize,
    pub importados: usize,
    pub ya_existian: usize,
    pub sin_tipo: usize,
    pub pdf_ok: usize,
    pub pdf_falta: usize,
    pub xml_ok: usize,
    pub xml_falta: usize,
    pub documentos: Vec<DocumentoImportado>,
    #[serde(skip_serializing_if = "Vec::is_empty")]
    pub avisos: Vec<String>,
}

static RE_FECHA_SEGURA: OnceLock<Regex> = OnceLock::new();

#[derive(Debug)]
pub enum ErrorImportar {
    Almacen(almacen::Error),
    Io(std::io::Error),
}

impl std::fmt::Display for ErrorImportar {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            ErrorImportar::Almacen(e) => write!(f, "{e}"),
            ErrorImportar::Io(e) => write!(f, "{e}"),
        }
    }
}

impl From<almacen::Error> for ErrorImportar {
    fn from(e: almacen::Error) -> Self {
        ErrorImportar::Almacen(e)
    }
}
impl From<std::io::Error> for ErrorImportar {
    fn from(e: std::io::Error) -> Self {
        ErrorImportar::Io(e)
    }
}

pub fn importar(
    cli: &mut dyn Lector,
    al: &Almacen,
    rut_emisor: &str,
    docs: &[DocumentoEmitido],
    op: &OpcionesImportar,
) -> Result<Resumen, Box<(Resumen, ErrorImportar)>> {
    let rut = formatear_rut(rut_emisor, false);
    let carpeta = if op.carpeta.is_empty() {
        "storage"
    } else {
        op.carpeta.as_str()
    };
    let rut_dir = rut.replace('-', "");
    let destino_pdf: PathBuf = [carpeta, "pdfs", "mipyme", &rut_dir].iter().collect();
    let destino_xml: PathBuf = [carpeta, "dtes", "mipyme", &rut_dir].iter().collect();
    let mut res = Resumen {
        listados: docs.len(),
        ..Default::default()
    };
    let fecha_segura = RE_FECHA_SEGURA.get_or_init(|| Regex::new(r"[^0-9-]").expect("regex"));
    macro_rules! intenta {
        ($e:expr) => {
            match $e {
                Ok(v) => v,
                Err(e) => return Err(Box::new((res, e.into()))),
            }
        };
    }
    for d in docs {
        let tipo = d.tipo();
        if tipo == 0 {
            res.sin_tipo += 1;
            res.avisos.push(format!(
                "tipo no reconocido en el historial: {:?} (folio {})",
                d.tipo_texto, d.folio
            ));
            continue;
        }
        let fila = intenta!(al.dte_por_folio(&rut, tipo, d.folio));
        let id = match &fila {
            Some(f) => {
                res.ya_existian += 1;
                f.id
            }
            None => {
                let receptor = if validar_rut(&d.receptor_rut) {
                    formatear_rut(&d.receptor_rut, false)
                } else {
                    d.receptor_rut.clone()
                };
                let exento = if tipo == 34 || tipo == 61 { d.monto } else { 0 };
                let id = intenta!(al.crear_dte(&almacen::Dte {
                    tipo_dte: tipo,
                    folio: d.folio,
                    rut_emisor: rut.clone(),
                    rut_receptor: receptor,
                    razon_social_receptor: d.receptor_razon.clone(),
                    fecha_emision: d.fecha.clone(),
                    monto_exento: exento,
                    monto_total: d.monto,
                    ambiente: "produccion".into(),
                    ..Default::default()
                }));
                let track: i64 = d.dhdr.parse().unwrap_or(0);
                intenta!(al.actualizar_estado(id, "emitido_mipyme", track));
                res.importados += 1;
                id
            }
        };
        let tiene_pdf = fila
            .as_ref()
            .map(|f| !f.pdf_path.is_empty() && std::path::Path::new(&f.pdf_path).exists())
            .unwrap_or(false);
        if op.con_pdf && !tiene_pdf {
            match cli.descargar_pdf(&d.dhdr) {
                Err(e) => {
                    res.pdf_falta += 1;
                    res.avisos
                        .push(format!("sin PDF para DHDR {}: {e}", d.dhdr));
                }
                Ok(pdf) => {
                    let _ = std::fs::create_dir_all(&destino_pdf);
                    let ruta = destino_pdf.join(format!(
                        "T{tipo}_F{}_{}_D{}.pdf",
                        d.folio,
                        fecha_segura.replace_all(&d.fecha, "_"),
                        d.dhdr
                    ));
                    intenta!(std::fs::write(&ruta, pdf));
                    intenta!(al.guardar_pdf(id, &ruta.to_string_lossy()));
                    res.pdf_ok += 1;
                    std::thread::sleep(op.pausa);
                }
            }
        }
        if op.con_xml && !fila.as_ref().map(|f| f.tiene_xml).unwrap_or(false) {
            match cli.obtener_envio_xml(&d.dhdr, tipo, &d.receptor_rut) {
                Err(e) => {
                    res.xml_falta += 1;
                    res.avisos
                        .push(format!("sin XML para DHDR {}: {e}", d.dhdr));
                }
                Ok(xml) => {
                    intenta!(al.guardar_xml(id, &latin1(&xml)));
                    let _ = std::fs::create_dir_all(&destino_xml);
                    intenta!(std::fs::write(
                        destino_xml.join(format!("T{tipo}_F{}_D{}.xml", d.folio, d.dhdr)),
                        &xml
                    ));
                    res.xml_ok += 1;
                    std::thread::sleep(op.pausa);
                }
            }
        }
        res.documentos.push(DocumentoImportado {
            tipo,
            folio: d.folio,
            fecha: d.fecha.clone(),
            monto: d.monto,
            estado: d.estado.clone(),
            dhdr: d.dhdr.clone(),
            receptor: d.receptor_razon.clone(),
        });
    }
    Ok(res)
}

#[cfg(test)]
mod tests {
    use super::super::lectura::parsear_listado;
    use super::super::Error;
    use super::*;

    struct LectorFalso;
    impl Lector for LectorFalso {
        fn descargar_pdf(&mut self, dhdr: &str) -> Result<Vec<u8>, Error> {
            Ok(format!("%PDF-1.4 fake {dhdr}").into_bytes())
        }
        fn obtener_envio_xml(&mut self, _d: &str, _t: i32, _r: &str) -> Result<Vec<u8>, Error> {
            Ok(b"<EnvioDTE>\xf1</EnvioDTE>".to_vec())
        }
    }

    const HTML_LISTADO: &str = r#"<table>
<tr><td>76.111.111-6</td><td>CLIENTE DEMO SPA</td><td>FACTURA NO AFECTA O EXENTA ELECTRONICA</td><td>59</td><td>06/09/2026</td><td>3.270.323</td><td>Aceptado</td><td><a href="mipeGesDocEmi.cgi?ALL_PAGE_ANT=2&CODIGO=2850540417">ver</a></td></tr>
<tr><td>76.111.111-6</td><td>CLIENTE DEMO SPA</td><td>NOTA DE CREDITO ELECTRONICA</td><td>56</td><td>2026-09-06</td><td>$3.068.005</td><td>Aceptado con Reparos</td><td><a href="mipeGesDocEmi.cgi?CODIGO=2850540999">ver</a></td></tr>
</table>"#;

    #[test]
    fn importa_idempotente() {
        let dir = std::env::temp_dir().join(format!("importar-{}", std::process::id()));
        let _ = std::fs::create_dir_all(&dir);
        let al = Almacen::abrir_y_migrar(dir.join("t.db").to_str().unwrap()).unwrap();
        let (docs, _) = parsear_listado(HTML_LISTADO);
        let mut op = OpcionesImportar {
            con_pdf: true,
            carpeta: dir.join("storage").to_string_lossy().into_owned(),
            ..Default::default()
        };
        let mut cli = LectorFalso;
        let r1 = importar(&mut cli, &al, "77.777.777-7", &docs, &op)
            .map_err(|e| e.1.to_string())
            .unwrap();
        assert_eq!((r1.importados, r1.pdf_ok, r1.listados), (2, 2, 2));
        let fila = al.dte_por_folio("77777777-7", 34, 59).unwrap().unwrap();
        assert_eq!(fila.estado, "emitido_mipyme");
        assert!(std::path::Path::new(&fila.pdf_path).exists());
        let r2 = importar(&mut cli, &al, "77777777-7", &docs, &op)
            .map_err(|e| e.1.to_string())
            .unwrap();
        assert_eq!((r2.importados, r2.ya_existian, r2.pdf_ok), (0, 2, 0));
        op.con_xml = true;
        let r3 = importar(&mut cli, &al, "77777777-7", &docs, &op)
            .map_err(|e| e.1.to_string())
            .unwrap();
        let fila = al.dte_por_folio("77777777-7", 61, 56).unwrap().unwrap();
        assert!(r3.xml_ok == 2 && fila.tiene_xml);
        let _ = std::fs::remove_dir_all(&dir);
    }
}
