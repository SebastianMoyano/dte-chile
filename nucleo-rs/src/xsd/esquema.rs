//! Carga de los XSD embebidos (include/import, tipos, elementos, atributos, partículas) y
//! resolución de referencias. Transcripción de `nucleo/xsd/esquema.go` con un arena de índices
//! en vez de punteros.

use super::arbol::{parsear_arbol, Nodo, QName, NS_XSD};
use super::simple::builtin_soportado;
use regex::Regex;
use std::collections::{HashMap, HashSet};

/// Copias byte a byte de core/xsd/*.xsd (el test `esquemas_iguales_a_core` lo exige): los XSD
/// oficiales del SII más el de XMLDSig que importan.
pub const ARCHIVOS: [(&str, &[u8]); 6] = [
    (
        "ConsumoFolio_v10.xsd",
        include_bytes!("../../esquemas/ConsumoFolio_v10.xsd"),
    ),
    ("DTE_v10.xsd", include_bytes!("../../esquemas/DTE_v10.xsd")),
    (
        "EnvioBOLETA_v11.xsd",
        include_bytes!("../../esquemas/EnvioBOLETA_v11.xsd"),
    ),
    (
        "EnvioDTE_v10.xsd",
        include_bytes!("../../esquemas/EnvioDTE_v10.xsd"),
    ),
    (
        "SiiTypes_v10.xsd",
        include_bytes!("../../esquemas/SiiTypes_v10.xsd"),
    ),
    (
        "xmldsignature_v10.xsd",
        include_bytes!("../../esquemas/xmldsignature_v10.xsd"),
    ),
];

pub type SimpleId = usize;
pub type ComplejoId = usize;
pub type ElemId = usize;
pub type PartId = usize;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TipoRef {
    Simple(SimpleId),
    Complejo(ComplejoId),
}

#[derive(Debug)]
pub struct Faceta {
    pub clase: String,
    pub valor: String,
    pub patron: Option<Regex>,
}

/// Un xs:simpleType (nombrado o anónimo) o un tipo primitivo de XSD (`builtin` no vacío).
#[derive(Debug, Default)]
pub struct TipoSimple {
    pub nombre: QName,
    pub base: Option<SimpleId>,
    pub base_ref: Option<QName>,
    pub builtin: String,
    pub facetas: Vec<Faceta>,
}

#[derive(Debug, Default)]
pub struct AtributoDecl {
    pub nombre: String,
    pub tipo: Option<SimpleId>,
    pub tipo_ref: Option<QName>,
    pub req: bool,
    pub fijo: Option<String>,
}

/// Atributos + (secuencia/elección | contenido simple | vacío).
#[derive(Debug, Default)]
pub struct TipoComplejo {
    pub nombre: QName,
    pub attrs: Vec<AtributoDecl>,
    pub particula: Option<PartId>,
    pub simple: Option<SimpleId>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Clase {
    Secuencia,
    Eleccion,
    Elemento,
}

#[derive(Debug)]
pub struct Particula {
    pub clase: Clase,
    pub min: i32,
    /// -1 = unbounded
    pub max: i32,
    pub hijos: Vec<PartId>,
    pub elem: Option<ElemId>,
    pub ref_: Option<QName>,
}

#[derive(Debug, Default)]
pub struct Elemento {
    pub nombre: QName,
    pub tipo: Option<TipoRef>,
    pub tipo_ref: Option<QName>,
}

#[derive(Debug, Default)]
pub struct Esquema {
    pub elementos: HashMap<QName, ElemId>,
    pub tipos: HashMap<QName, TipoRef>,
    pub simples: Vec<TipoSimple>,
    pub complejos: Vec<TipoComplejo>,
    pub elems: Vec<Elemento>,
    pub particulas: Vec<Particula>,
    builtins: HashMap<String, SimpleId>,
    archivos: HashSet<String>,
    pend_simples: Vec<SimpleId>,
    pend_elems: Vec<ElemId>,
    pend_attrs: Vec<(ComplejoId, usize)>,
    pend_parts: Vec<PartId>,
}

/// Carga un XSD embebido con sus include/import y resuelve las referencias.
pub fn cargar_esquema(archivo: &str) -> Result<Esquema, String> {
    let mut e = Esquema::default();
    e.cargar_archivo(archivo)?;
    e.resolver()?;
    Ok(e)
}

fn ocurrencias(n: &Nodo) -> Result<(i32, i32), String> {
    let (mut min, mut max) = (1, 1);
    if let Some(v) = n.attr("minOccurs") {
        min = v
            .parse()
            .map_err(|_| format!("minOccurs inválido: {v:?}"))?;
    }
    if let Some(v) = n.attr("maxOccurs") {
        max = if v == "unbounded" {
            -1
        } else {
            v.parse()
                .map_err(|_| format!("maxOccurs inválido: {v:?}"))?
        };
    }
    Ok((min, max))
}

impl Esquema {
    fn cargar_archivo(&mut self, archivo: &str) -> Result<(), String> {
        if !self.archivos.insert(archivo.to_string()) {
            return Ok(());
        }
        let (_, contenido) = ARCHIVOS
            .iter()
            .find(|(n, _)| *n == archivo)
            .ok_or_else(|| format!("esquema no embebido: {archivo}"))?;
        let raiz = parsear_arbol(contenido).map_err(|e| format!("{archivo}: {e}"))?;
        if raiz.nombre != QName::new(NS_XSD, "schema") {
            return Err(format!("{archivo}: la raíz no es xs:schema"));
        }
        let tns = raiz.attr("targetNamespace").unwrap_or("").to_string();
        for h in &raiz.hijos {
            if h.nombre.ns != NS_XSD {
                return Err(format!("{archivo}: nodo inesperado {}", h.nombre));
            }
            match h.nombre.local.as_str() {
                "include" | "import" => {
                    let loc = h.attr("schemaLocation").unwrap_or("");
                    let base = loc.rsplit('/').next().unwrap_or(loc).to_string();
                    self.cargar_archivo(&base)?;
                }
                "element" => {
                    let id = self
                        .parsear_elemento(h, &tns)
                        .map_err(|e| format!("{archivo}: {e}"))?;
                    let nombre = self.elems[id].nombre.clone();
                    self.elementos.insert(nombre, id);
                }
                "complexType" => {
                    let nombre = h.attr("name").unwrap_or("").to_string();
                    let id = self
                        .parsear_complejo(h, &tns)
                        .map_err(|e| format!("{archivo}: {e}"))?;
                    let q = QName {
                        ns: tns.clone(),
                        local: nombre,
                    };
                    self.complejos[id].nombre = q.clone();
                    self.tipos.insert(q, TipoRef::Complejo(id));
                }
                "simpleType" => {
                    let nombre = h.attr("name").unwrap_or("").to_string();
                    let id = self
                        .parsear_simple(h)
                        .map_err(|e| format!("{archivo}: {e}"))?;
                    let q = QName {
                        ns: tns.clone(),
                        local: nombre,
                    };
                    self.simples[id].nombre = q.clone();
                    self.tipos.insert(q, TipoRef::Simple(id));
                }
                "attribute" => {
                    // declaración global (SiiTypes declara una `version` que nadie referencia)
                    self.parsear_atributo(h)
                        .map_err(|e| format!("{archivo}: {e}"))?;
                }
                "annotation" => {}
                otro => return Err(format!("{archivo}: constructo XSD no soportado: {otro}")),
            }
        }
        Ok(())
    }

    fn parsear_elemento(&mut self, n: &Nodo, tns: &str) -> Result<ElemId, String> {
        let nombre = n.attr("name").unwrap_or("").to_string();
        let id = self.elems.len();
        self.elems.push(Elemento {
            nombre: QName {
                ns: tns.to_string(),
                local: nombre.clone(),
            },
            ..Default::default()
        });
        if let Some(t) = n.attr("type") {
            let q = n.qname(t)?;
            self.elems[id].tipo_ref = Some(q);
            self.pend_elems.push(id);
        }
        for h in &n.hijos {
            match h.nombre.local.as_str() {
                "complexType" => {
                    let t = self.parsear_complejo(h, tns)?;
                    self.elems[id].tipo = Some(TipoRef::Complejo(t));
                }
                "simpleType" => {
                    let t = self.parsear_simple(h)?;
                    self.elems[id].tipo = Some(TipoRef::Simple(t));
                }
                "annotation" => {}
                otro => return Err(format!("elemento {nombre}: hijo no soportado {otro}")),
            }
        }
        if self.elems[id].tipo.is_none() && self.elems[id].tipo_ref.is_none() {
            return Err(format!("elemento {nombre} sin tipo (anyType no soportado)"));
        }
        Ok(id)
    }

    /// Un xs:element dentro de un grupo: declaración local o ref.
    fn parsear_particula_elemento(&mut self, n: &Nodo, tns: &str) -> Result<PartId, String> {
        let (min, max) = ocurrencias(n)?;
        let id = self.particulas.len();
        self.particulas.push(Particula {
            clase: Clase::Elemento,
            min,
            max,
            hijos: vec![],
            elem: None,
            ref_: None,
        });
        if let Some(r) = n.attr("ref") {
            let q = n.qname(r)?;
            self.particulas[id].ref_ = Some(q);
            self.pend_parts.push(id);
            return Ok(id);
        }
        let el = self.parsear_elemento(n, tns)?;
        self.particulas[id].elem = Some(el);
        Ok(id)
    }

    fn parsear_grupo(&mut self, n: &Nodo, tns: &str) -> Result<PartId, String> {
        let (min, max) = ocurrencias(n)?;
        let clase = match n.nombre.local.as_str() {
            "sequence" => Clase::Secuencia,
            "choice" => Clase::Eleccion,
            otro => return Err(format!("grupo no soportado: {otro}")),
        };
        let id = self.particulas.len();
        self.particulas.push(Particula {
            clase,
            min,
            max,
            hijos: vec![],
            elem: None,
            ref_: None,
        });
        for h in &n.hijos {
            match h.nombre.local.as_str() {
                "element" => {
                    let c = self.parsear_particula_elemento(h, tns)?;
                    self.particulas[id].hijos.push(c);
                }
                "sequence" | "choice" => {
                    let c = self.parsear_grupo(h, tns)?;
                    self.particulas[id].hijos.push(c);
                }
                "annotation" => {}
                otro => return Err(format!("dentro de {}: {otro} no soportado", n.nombre.local)),
            }
        }
        Ok(id)
    }

    fn parsear_complejo(&mut self, n: &Nodo, tns: &str) -> Result<ComplejoId, String> {
        let id = self.complejos.len();
        self.complejos.push(TipoComplejo::default());
        for h in &n.hijos {
            match h.nombre.local.as_str() {
                "sequence" | "choice" => {
                    let p = self.parsear_grupo(h, tns)?;
                    self.complejos[id].particula = Some(p);
                }
                "simpleContent" => {
                    for x in &h.hijos {
                        if x.nombre.local != "extension" {
                            return Err(format!("simpleContent/{} no soportado", x.nombre.local));
                        }
                        let base = x.attr("base").unwrap_or("");
                        let q = x.qname(base)?;
                        let sid = self.simples.len();
                        self.simples.push(TipoSimple {
                            base_ref: Some(q),
                            ..Default::default()
                        });
                        self.pend_simples.push(sid);
                        self.complejos[id].simple = Some(sid);
                        for a in &x.hijos {
                            match a.nombre.local.as_str() {
                                "attribute" => {
                                    let ad = self.parsear_atributo(a)?;
                                    self.registrar_attr(id, ad);
                                }
                                "annotation" => {}
                                otro => return Err(format!("extension/{otro} no soportado")),
                            }
                        }
                    }
                }
                "attribute" => {
                    let ad = self.parsear_atributo(h)?;
                    self.registrar_attr(id, ad);
                }
                "annotation" => {}
                otro => return Err(format!("complexType/{otro} no soportado")),
            }
        }
        Ok(id)
    }

    fn registrar_attr(&mut self, complejo: ComplejoId, ad: AtributoDecl) {
        let pendiente = ad.tipo_ref.is_some();
        self.complejos[complejo].attrs.push(ad);
        if pendiente {
            let k = self.complejos[complejo].attrs.len() - 1;
            self.pend_attrs.push((complejo, k));
        }
    }

    fn parsear_atributo(&mut self, n: &Nodo) -> Result<AtributoDecl, String> {
        let mut a = AtributoDecl {
            nombre: n.attr("name").unwrap_or("").to_string(),
            ..Default::default()
        };
        if n.attr("use") == Some("required") {
            a.req = true;
        }
        if let Some(f) = n.attr("fixed") {
            a.fijo = Some(f.to_string());
        }
        if let Some(t) = n.attr("type") {
            a.tipo_ref = Some(n.qname(t)?);
        }
        for h in &n.hijos {
            match h.nombre.local.as_str() {
                "simpleType" => {
                    let t = self.parsear_simple(h)?;
                    a.tipo = Some(t);
                }
                "annotation" => {}
                otro => return Err(format!("attribute/{otro} no soportado")),
            }
        }
        if a.tipo.is_none() && a.tipo_ref.is_none() {
            a.tipo_ref = Some(QName::new(NS_XSD, "anySimpleType"));
        }
        Ok(a)
    }

    fn parsear_simple(&mut self, n: &Nodo) -> Result<SimpleId, String> {
        let id = self.simples.len();
        self.simples.push(TipoSimple::default());
        for h in &n.hijos {
            match h.nombre.local.as_str() {
                "restriction" => {
                    if let Some(b) = h.attr("base") {
                        let q = h.qname(b)?;
                        self.simples[id].base_ref = Some(q);
                        self.pend_simples.push(id);
                    }
                    for f in &h.hijos {
                        match f.nombre.local.as_str() {
                            "simpleType" => {
                                let b = self.parsear_simple(f)?;
                                self.simples[id].base = Some(b);
                            }
                            "annotation" => {}
                            clase @ ("enumeration" | "length" | "minLength" | "maxLength"
                            | "pattern" | "totalDigits" | "fractionDigits"
                            | "minInclusive" | "maxInclusive" | "minExclusive"
                            | "maxExclusive") => {
                                let v = f.attr("value").unwrap_or("").to_string();
                                let patron = if clase == "pattern" {
                                    Some(
                                        Regex::new(&format!("^(?:{v})$"))
                                            .map_err(|e| format!("patrón {v:?}: {e}"))?,
                                    )
                                } else {
                                    None
                                };
                                self.simples[id].facetas.push(Faceta {
                                    clase: clase.to_string(),
                                    valor: v,
                                    patron,
                                });
                            }
                            "whiteSpace" => return Err("faceta whiteSpace no soportada".into()),
                            otro => return Err(format!("faceta no soportada: {otro}")),
                        }
                    }
                }
                "annotation" => {}
                otro => return Err(format!("simpleType/{otro} no soportado (union/list)")),
            }
        }
        if self.simples[id].base.is_none() && self.simples[id].base_ref.is_none() {
            return Err("simpleType sin restriction/base".into());
        }
        Ok(id)
    }

    fn builtin(&mut self, local: &str) -> Result<SimpleId, String> {
        if let Some(&id) = self.builtins.get(local) {
            return Ok(id);
        }
        if !builtin_soportado(local) {
            return Err(format!("tipo primitivo xs:{local} no soportado"));
        }
        let id = self.simples.len();
        self.simples.push(TipoSimple {
            nombre: QName::new(NS_XSD, local),
            builtin: local.to_string(),
            ..Default::default()
        });
        self.builtins.insert(local.to_string(), id);
        Ok(id)
    }

    fn tipo_simple_por(&mut self, q: &QName) -> Result<SimpleId, String> {
        if q.ns == NS_XSD {
            return self.builtin(&q.local);
        }
        match self.tipos.get(q) {
            Some(TipoRef::Simple(id)) => Ok(*id),
            Some(TipoRef::Complejo(_)) => Err(format!("{q} no es un tipo simple")),
            None => Err(format!("tipo no declarado: {q}")),
        }
    }

    fn resolver(&mut self) -> Result<(), String> {
        for id in std::mem::take(&mut self.pend_simples) {
            let q = self.simples[id]
                .base_ref
                .clone()
                .expect("pendiente con base_ref");
            let b = self.tipo_simple_por(&q)?;
            self.simples[id].base = Some(b);
        }
        for id in std::mem::take(&mut self.pend_elems) {
            let q = self.elems[id]
                .tipo_ref
                .clone()
                .expect("pendiente con tipo_ref");
            if q.ns == NS_XSD {
                let b = self.builtin(&q.local)?;
                self.elems[id].tipo = Some(TipoRef::Simple(b));
                continue;
            }
            let t = *self.tipos.get(&q).ok_or_else(|| {
                format!("elemento {}: tipo no declarado {q}", self.elems[id].nombre)
            })?;
            self.elems[id].tipo = Some(t);
        }
        for (cid, k) in std::mem::take(&mut self.pend_attrs) {
            let q = self.complejos[cid].attrs[k]
                .tipo_ref
                .clone()
                .expect("pendiente con tipo_ref");
            let nombre = self.complejos[cid].attrs[k].nombre.clone();
            let t = self
                .tipo_simple_por(&q)
                .map_err(|e| format!("atributo {nombre}: {e}"))?;
            self.complejos[cid].attrs[k].tipo = Some(t);
        }
        for id in std::mem::take(&mut self.pend_parts) {
            let q = self.particulas[id].ref_.clone().expect("pendiente con ref");
            let el = *self
                .elementos
                .get(&q)
                .ok_or_else(|| format!("ref a elemento no declarado: {q}"))?;
            self.particulas[id].elem = Some(el);
        }
        Ok(())
    }

    /// El tipo primitivo en la raíz de la cadena de restricciones.
    pub fn raiz_builtin(&self, mut t: SimpleId) -> SimpleId {
        while self.simples[t].builtin.is_empty() {
            t = self.simples[t].base.expect("cadena resuelta");
        }
        t
    }

    /// El nombre del tipo nombrado más cercano (como lo muestra libxml2).
    pub fn nombre_tipo(&self, t: SimpleId) -> String {
        let mut cur = Some(t);
        while let Some(id) = cur {
            let s = &self.simples[id];
            if !s.nombre.local.is_empty() {
                if s.nombre.ns == NS_XSD {
                    return format!("xs:{}", s.nombre.local);
                }
                return s.nombre.to_string();
            }
            cur = s.base;
        }
        "?".into()
    }
}
