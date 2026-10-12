//! Validación del árbol contra el esquema: atributos, contenido simple, modelos de contenido
//! (sequence/choice, greedy) y el "se esperaba (…)" del error. Transcripción de
//! `nucleo/xsd/validar.go`.

use super::arbol::{es_blanco, Nodo, QName, NS_XSI};
use super::esquema::{Clase, ElemId, Esquema, Particula, TipoRef};
use super::simple::{colapsar, mismo_valor, validar_simple};
use super::Error;
use std::collections::{HashMap, HashSet};

#[derive(Default)]
pub struct Contexto {
    pub errores: Vec<Error>,
    /// xs:ID vistos: libxml2 exige unicidad en el documento
    ids: HashSet<String>,
}

impl Contexto {
    fn error(&mut self, n: &Nodo, msg: String) {
        self.errores.push(Error {
            linea: n.linea,
            elemento: n.nombre.local.clone(),
            atributo: String::new(),
            mensaje: msg,
        });
    }

    fn error_attr(&mut self, n: &Nodo, attr: &str, msg: String) {
        self.errores.push(Error {
            linea: n.linea,
            elemento: n.nombre.local.clone(),
            atributo: attr.to_string(),
            mensaje: msg,
        });
    }

    pub fn validar_elemento(&mut self, esq: &Esquema, n: &Nodo, decl: ElemId) {
        match esq.elems[decl].tipo.expect("elemento resuelto") {
            TipoRef::Simple(t) => {
                self.validar_atributos(esq, n, &[]);
                if !n.hijos.is_empty() {
                    self.error(
                        n,
                        "No se permiten elementos hijos, porque el tipo es simple.".into(),
                    );
                    return;
                }
                for m in validar_simple(esq, t, &n.texto) {
                    self.error(n, m);
                }
            }
            TipoRef::Complejo(c) => {
                let tc = &esq.complejos[c];
                self.validar_atributos(esq, n, &tc.attrs);
                if let Some(s) = tc.simple {
                    if !n.hijos.is_empty() {
                        self.error(n, "No se permiten elementos hijos, porque el contenido es de tipo simple.".into());
                        return;
                    }
                    for m in validar_simple(esq, s, &n.texto) {
                        self.error(n, m);
                    }
                } else if let Some(p) = tc.particula {
                    if !es_blanco(&n.texto) {
                        self.error(n, "No se permite texto que no sea blanco, porque el contenido es solo de elementos.".into());
                    }
                    self.validar_contenido(esq, n, p);
                } else {
                    if !n.hijos.is_empty() {
                        self.error(
                            n,
                            "No se permiten elementos hijos, porque el contenido es vacío.".into(),
                        );
                    }
                    if !n.texto.is_empty() {
                        self.error(
                            n,
                            "No se permite texto, porque el contenido es vacío.".into(),
                        );
                    }
                }
            }
        }
    }

    fn validar_atributos(
        &mut self,
        esq: &Esquema,
        n: &Nodo,
        decls: &[super::esquema::AtributoDecl],
    ) {
        let mut vistos: HashSet<&str> = HashSet::new();
        for a in &n.attrs {
            if a.nombre.ns == NS_XSI {
                if a.nombre.local == "schemaLocation"
                    || a.nombre.local == "noNamespaceSchemaLocation"
                {
                    continue;
                }
                let nombre = format!("xsi:{}", a.nombre.local);
                self.error_attr(
                    n,
                    &nombre,
                    format!("El atributo '{nombre}' no está permitido aquí."),
                );
                continue;
            }
            let d = if a.nombre.ns.is_empty() {
                decls.iter().find(|x| x.nombre == a.nombre.local)
            } else {
                None
            };
            let Some(d) = d else {
                self.error_attr(
                    n,
                    &a.nombre.to_string(),
                    format!("El atributo '{}' no está permitido.", a.nombre),
                );
                continue;
            };
            vistos.insert(d.nombre.as_str());
            let t = d.tipo.expect("atributo resuelto");
            let errs = validar_simple(esq, t, &a.valor);
            for m in &errs {
                self.error_attr(n, &d.nombre, m.clone());
            }
            if errs.is_empty() && esq.simples[esq.raiz_builtin(t)].builtin == "ID" {
                let id = colapsar(&a.valor);
                if !self.ids.insert(id) {
                    self.error_attr(n, &d.nombre, format!("'{}' no es un valor válido del tipo 'xs:ID' (repetido en el documento).", a.valor));
                }
            }
            if let Some(fijo) = &d.fijo {
                if errs.is_empty() && !mismo_valor(esq, t, &a.valor, fijo) {
                    self.error_attr(
                        n,
                        &d.nombre,
                        format!(
                            "El valor '{}' no coincide con el valor fijo '{}'.",
                            a.valor, fijo
                        ),
                    );
                }
            }
        }
        for d in decls {
            if d.req && !vistos.contains(d.nombre.as_str()) {
                self.error(n, format!("Falta el atributo obligatorio '{}'.", d.nombre));
            }
        }
    }

    fn validar_contenido(&mut self, esq: &Esquema, n: &Nodo, p: usize) {
        let mut m = Emparejador {
            c: self,
            esq,
            hijos: &n.hijos,
            esperados: HashMap::new(),
        };
        let top = Particula {
            clase: Clase::Secuencia,
            min: 1,
            max: 1,
            hijos: vec![p],
            elem: None,
            ref_: None,
        };
        let (np, ok) = m.aceptar(&top, 0);
        if ok && np == n.hijos.len() {
            return;
        }
        // posición donde se trabó: la más lejana que se probó
        let pos = m.esperados.keys().copied().fold(np, usize::max);
        let esperados = m.esperados.remove(&pos).unwrap_or_default();
        if pos >= n.hijos.len() {
            self.error(
                n,
                format!("Faltan elementos hijos.{}", se_esperaba(&esperados)),
            );
            return;
        }
        let hijo = &n.hijos[pos];
        self.error(
            hijo,
            format!(
                "Este elemento no se esperaba aquí.{}",
                se_esperaba(&esperados)
            ),
        );
    }
}

/// Recorre los hijos con el modelo de contenido (greedy: los XSD cumplen la regla de
/// atribución única, así que no hace falta retroceder) y anota, por posición, qué elementos se
/// probaron sin éxito: con eso se arma el "se esperaba (…)" del error.
struct Emparejador<'a> {
    c: &'a mut Contexto,
    esq: &'a Esquema,
    hijos: &'a [Nodo],
    esperados: HashMap<usize, Vec<String>>,
}

impl Emparejador<'_> {
    fn esperado(&mut self, pos: usize, q: &QName) {
        let v = self.esperados.entry(pos).or_default();
        if !v.contains(&q.local) {
            v.push(q.local.clone());
        }
    }

    fn aceptar(&mut self, p: &Particula, pos: usize) -> (usize, bool) {
        match p.clase {
            Clase::Elemento => {
                let el = p.elem.expect("partícula resuelta");
                let nombre = &self.esq.elems[el].nombre;
                if pos < self.hijos.len() && self.hijos[pos].nombre == *nombre {
                    self.c.validar_elemento(self.esq, &self.hijos[pos], el);
                    return (pos + 1, true);
                }
                let q = nombre.clone();
                self.esperado(pos, &q);
                (pos, false)
            }
            Clase::Secuencia => {
                let mut cur = pos;
                for &hid in &p.hijos {
                    let h = &self.esq.particulas[hid];
                    let mut n = 0;
                    while h.max < 0 || n < h.max {
                        let (np, ok) = self.aceptar(h, cur);
                        if !ok {
                            break;
                        }
                        if np == cur {
                            // el grupo admite vacío: cuenta como satisfecho
                            n = h.min;
                            break;
                        }
                        cur = np;
                        n += 1;
                    }
                    if n < h.min {
                        return (pos, false);
                    }
                }
                (cur, true)
            }
            Clase::Eleccion => {
                let mut vacio_ok = false;
                for &hid in &p.hijos {
                    let h = &self.esq.particulas[hid];
                    let (np, ok) = self.aceptar(h, pos);
                    if ok && np > pos {
                        return (np, true);
                    }
                    if ok {
                        vacio_ok = true;
                    }
                }
                (pos, vacio_ok)
            }
        }
    }
}

fn se_esperaba(nombres: &[String]) -> String {
    match nombres.len() {
        0 => String::new(),
        1 => format!(" Se esperaba ( {} ).", nombres[0]),
        _ => format!(" Se esperaba uno de ( {} ).", nombres.join(", ")),
    }
}
