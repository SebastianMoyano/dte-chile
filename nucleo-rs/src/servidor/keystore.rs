//! /api/v1/keystore/*: certificados (cifrados con Fernet), claves del SII recordadas, negocios
//! y el contexto de emisión para el núcleo. Réplica de api/routes/keystore.py y core/keystore.py.

use super::errores::{json, ok, ErrorHTTP, Res};
use super::http::{parsear_formulario, Peticion};
use super::local::{rut_del_certificado, vencimiento};
use super::{ahora_utc, entero, ruta_real, texto, Json, Prot, Servidor};
use crate::firma;
use rusqlite::types::Value as Sql;
use serde_json::{json, Map, Value};

/// api/util.py::MAX_UPLOAD_BYTES
pub const MAX_UPLOAD: usize = 5 * 1024 * 1024;

pub fn rutas(s: &mut Servidor) {
    s.ruta(
        "POST /api/v1/keystore/certificados",
        Prot::Protegida,
        subir_certificado,
    );
    s.ruta(
        "GET /api/v1/keystore/certificados",
        Prot::Protegida,
        listar_certificados,
    );
    s.ruta(
        "DELETE /api/v1/keystore/certificados/{id}",
        Prot::Protegida,
        eliminar_certificado,
    );
    s.ruta(
        "GET /api/v1/keystore/negocios",
        Prot::Protegida,
        listar_negocios,
    );
    s.ruta(
        "PUT /api/v1/keystore/negocios/{id}",
        Prot::Protegida,
        actualizar_negocio,
    );
    s.ruta(
        "DELETE /api/v1/keystore/negocios/{id}",
        Prot::Protegida,
        eliminar_negocio,
    );
    s.ruta(
        "GET /api/v1/keystore/negocios/{id}/contexto-emision",
        Prot::Protegida,
        contexto_emision,
    );
    s.ruta(
        "PUT /api/v1/keystore/claves-sii",
        Prot::Protegida,
        guardar_claves_sii,
    );
    s.ruta(
        "GET /api/v1/keystore/claves-sii/{rut}",
        Prot::Protegida,
        estado_claves_sii,
    );
    s.ruta(
        "DELETE /api/v1/keystore/claves-sii/{rut}",
        Prot::Protegida,
        olvidar_claves_sii,
    );
    s.ruta(
        "GET /api/v1/mipyme/contexto-siiengine/{rut}",
        Prot::Protegida,
        contexto_siiengine,
    );
}

/// `strconv.ParseInt(r.PathValue(k))` → 422 "Los datos enviados no son válidos." sin detalle.
pub fn id_de(p: &Peticion, k: &str) -> Result<i64, ErrorHTTP> {
    p.param(k).parse().map_err(|_| ErrorHTTP::datos_invalidos())
}

fn subir_certificado(s: &Servidor, p: &mut Peticion) -> Res {
    let cuenta = s.cuenta_id(p);
    let Some(f) = parsear_formulario(p) else {
        return Err(ErrorHTTP::datos_invalidos());
    };
    let mut faltan = Vec::new();
    if f.archivo("archivo").is_none() {
        faltan.push("archivo");
    }
    if !f.tiene("password") {
        faltan.push("password");
    }
    if !faltan.is_empty() {
        return Err(ErrorHTTP::faltan(&faltan));
    }
    let p12 = &f.archivo("archivo").expect("archivo").datos;
    if p12.len() > MAX_UPLOAD {
        return Err(ErrorHTTP::validacion(
            "Archivo demasiado grande (máximo 5 MB).",
        ));
    }
    let password = f.valor("password");
    let cert = firma::cargar_p12(p12, &password).map_err(|e| {
        ErrorHTTP::certificado(format!("Certificado inválido o contraseña incorrecta: {e}"))
    })?;
    let rut = rut_del_certificado(&cert);
    let vence = vencimiento(&cert);
    let nombre = if f.tiene("nombre") {
        Value::String(f.valor("nombre"))
    } else {
        Value::Null
    };
    let alias = if f.tiene("alias") {
        Value::String(f.valor("alias"))
    } else {
        Value::Null
    };
    let a_sql = |v: &Value| match v {
        Value::String(x) => Sql::Text(x.clone()),
        _ => Sql::Null,
    };
    let id = s.guardar_certificado_cifrado(
        cuenta,
        &rut,
        &vence,
        p12,
        &password,
        a_sql(&nombre),
        a_sql(&alias),
    )?;
    Ok(json(
        201,
        &json!({"id": id, "cuenta_id": cuenta, "rut": rut, "nombre": nombre, "alias": alias, "vencimiento": vence}),
    ))
}

fn listar_certificados(s: &Servidor, p: &mut Peticion) -> Res {
    let cuenta = s.cuenta_id(p);
    let filas = s.filas(
        "SELECT id, rut, nombre, alias, vencimiento, creado FROM certificados WHERE cuenta_id=? ORDER BY id",
        &sql![cuenta],
    )?;
    ok(Value::Array(filas.into_iter().map(Value::Object).collect()))
}

fn eliminar_certificado(s: &Servidor, p: &mut Peticion) -> Res {
    let cuenta = s.cuenta_id(p);
    let id = id_de(p, "id")?;
    let n = s.ejecutar(
        "DELETE FROM certificados WHERE id=? AND cuenta_id=?",
        &sql![id, cuenta],
    )?;
    if n == 0 {
        return Err(ErrorHTTP::no_encontrado("Certificado no encontrado"));
    }
    ok(json!({"eliminado": true, "id": id}))
}

// ------------------------------------------------------------------ negocios

/// Una fila de `negocios` (los NULL como null).
pub type Negocio = Map<String, Value>;

pub fn negocios_de(s: &Servidor, cuenta: i64) -> Result<Vec<Negocio>, ErrorHTTP> {
    Ok(s.filas(
        "SELECT id, rut, razon_social, cert_id, ambiente, creado, estado, estado_etiqueta, usa_sw_propio, estado_ts, giro, codigo_actividad, direccion, comuna, ciudad, email, telefono FROM negocios WHERE cuenta_id=? ORDER BY id",
        &sql![cuenta],
    )?)
}

/// `api/routes/keystore.py::DatosNegocioIn`: campo → largo máximo (los del XSD del SII);
/// `codigo_actividad` (largo 0) es entero. En el orden de los errores de pydantic.
const CAMPOS_DATOS_NEGOCIO: [(&str, usize); 8] = [
    ("razon_social", 100),
    ("giro", 80),
    ("codigo_actividad", 0),
    ("direccion", 70),
    ("comuna", 20),
    ("ciudad", 20),
    ("email", 80),
    ("telefono", 20),
];

/// PUT /api/v1/keystore/negocios/{id}: los datos fijos del emisor (giro, código de actividad,
/// dirección…) que antes vivían en EMPRESA_* del .env, ahora por negocio. Solo cambia los
/// campos que vienen en el cuerpo; "" deja la columna en NULL.
fn actualizar_negocio(s: &Servidor, p: &mut Peticion) -> Res {
    let id: i64 = p
        .param("id")
        .parse()
        .map_err(|_| ErrorHTTP::path("negocio_id"))?;
    let j = Json::leer(p)?;
    let mut errs: Vec<Value> = Vec::new();
    let mut sets: Vec<String> = Vec::new();
    let mut args: Vec<Sql> = Vec::new();
    let err = |campo: &str, msg: &str, tipo: &str| json!({"loc": ["body", campo], "msg": msg, "type": tipo});
    for (campo, largo) in CAMPOS_DATOS_NEGOCIO {
        let Some(v) = j.get(campo) else { continue };
        if campo == "codigo_actividad" {
            match v {
                Value::Number(n) => match n.as_i64().or_else(|| n.as_f64().filter(|f| f.fract() == 0.0).map(|f| f as i64)) {
                    Some(x) => {
                        sets.push("codigo_actividad=?".into());
                        args.push(Sql::Integer(x));
                    }
                    None => errs.push(err(campo, "Input should be a valid integer, got a number with a fractional part", "int_from_float")),
                },
                Value::String(_) => errs.push(err(campo, "Input should be a valid integer, unable to parse string as an integer", "int_parsing")),
                _ => errs.push(err(campo, "Input should be a valid integer", "int_type")),
            }
            continue;
        }
        let Value::String(t) = v else {
            errs.push(err(campo, "Input should be a valid string", "string_type"));
            continue;
        };
        if t.chars().count() > largo {
            let mut e = err(campo, &format!("String should have at most {largo} characters"), "string_too_long");
            e["ctx"] = json!({"max_length": largo});
            errs.push(e);
            continue;
        }
        sets.push(format!("{campo}=?"));
        let t = t.trim();
        args.push(if t.is_empty() { Sql::Null } else { Sql::Text(t.to_string()) });
    }
    if !errs.is_empty() {
        return Err(ErrorHTTP::datos_invalidos().detalle(json!({"errores": errs})));
    }
    let cuenta = s.cuenta_id(p);
    if !sets.is_empty() {
        args.push(Sql::Integer(id));
        args.push(Sql::Integer(cuenta));
        let n = s.ejecutar(
            &format!("UPDATE negocios SET {} WHERE id=? AND cuenta_id=?", sets.join(", ")),
            &args,
        )?;
        if n == 0 {
            return Err(ErrorHTTP::no_encontrado("Negocio no encontrado"));
        }
    }
    match negocios_de(s, cuenta)?.into_iter().find(|n| entero(&n["id"]) == id) {
        Some(n) => ok(Value::Object(n)),
        None => Err(ErrorHTTP::no_encontrado("Negocio no encontrado")),
    }
}

pub fn cert_id_de(n: &Negocio) -> Option<i64> {
    match n.get("cert_id") {
        Some(Value::Number(x)) => x.as_i64().filter(|v| *v != 0),
        _ => None,
    }
}

fn listar_negocios(s: &Servidor, p: &mut Peticion) -> Res {
    let cuenta = s.cuenta_id(p);
    ok(Value::Array(
        negocios_de(s, cuenta)?
            .into_iter()
            .map(Value::Object)
            .collect(),
    ))
}

fn eliminar_negocio(s: &Servidor, p: &mut Peticion) -> Res {
    let cuenta = s.cuenta_id(p);
    let id = id_de(p, "id")?;
    let n = s.ejecutar(
        "DELETE FROM negocios WHERE id=? AND cuenta_id=?",
        &sql![id, cuenta],
    )?;
    if n == 0 {
        return Err(ErrorHTTP::no_encontrado("Negocio no encontrado"));
    }
    ok(json!({"eliminado": true, "id": id}))
}

fn contexto_emision(s: &Servidor, p: &mut Peticion) -> Res {
    let cuenta = s.cuenta_id(p);
    let id = id_de(p, "id")?;
    let negs = negocios_de(s, cuenta)?;
    let Some(neg) = negs.into_iter().find(|n| entero(&n["id"]) == id) else {
        return Err(ErrorHTTP::no_encontrado("Negocio no encontrado"));
    };
    let Some(cert_id) = cert_id_de(&neg) else {
        return Err(ErrorHTTP::validacion(
            "El negocio no tiene un certificado asociado",
        ));
    };
    let (p12, clave) = s
        .descifrar_certificado(cert_id, cuenta)
        .map_err(ErrorHTTP::no_encontrado)?;
    let cert = firma::cargar_p12(&p12, &clave).map_err(|e| {
        ErrorHTTP::certificado(format!("El certificado guardado no se pudo abrir: {e}"))
    })?;
    let mut ambiente = s.cfg.sii_ambiente.clone();
    if let Some(Value::String(a)) = neg.get("ambiente") {
        if !a.is_empty() {
            ambiente = a.clone();
        }
    }
    let rut = texto(&neg["rut"]);
    let (fecha, numero) = s.resolucion_emisor(&rut, &ambiente);
    ok(json!({
        "negocio_id": neg["id"], "rut": rut, "razon_social": neg["razon_social"], "ambiente": ambiente,
        "resolucion": {"fecha": fecha, "numero": numero},
        "cert_pem": cert.cert_pem(), "key_pem": cert.key_pem()?, "database_path": ruta_real(&s.cfg.database_path), "storage_path": ruta_real(&s.cfg.storage_path),
    }))
}

// ------------------------------------------------------------------ claves del SII

pub fn estado_claves(s: &Servidor, cuenta: i64, rut: &str) -> Value {
    let f = s.filas(
        "SELECT rut_usuario, length(tributaria_cifrada) AS t, length(certificado_cifrada) AS c, actualizado FROM claves_sii WHERE cuenta_id=? AND rut_empresa=?",
        &sql![cuenta, rut],
    );
    match f.ok().and_then(|v| v.into_iter().next()) {
        None => {
            json!({"rut_empresa": rut, "rut_usuario": null, "tiene_tributaria": false, "tiene_certificado": false, "actualizado": null})
        }
        Some(f) => {
            json!({"rut_empresa": rut, "rut_usuario": f["rut_usuario"], "tiene_tributaria": entero(&f["t"]) > 0,
            "tiene_certificado": entero(&f["c"]) > 0, "actualizado": f["actualizado"]})
        }
    }
}

fn estado_claves_sii(s: &Servidor, p: &mut Peticion) -> Res {
    let cuenta = s.cuenta_id(p);
    ok(estado_claves(s, cuenta, p.param("rut")))
}

fn olvidar_claves_sii(s: &Servidor, p: &mut Peticion) -> Res {
    let cuenta = s.cuenta_id(p);
    let n = s.ejecutar(
        "DELETE FROM claves_sii WHERE cuenta_id=? AND rut_empresa=?",
        &sql![cuenta, p.param("rut")],
    )?;
    ok(json!({"olvidadas": n > 0}))
}

/// `clavesGuardadas`: descifra las claves del SII recordadas para (cuenta, empresa).
pub fn claves_guardadas(s: &Servidor, cuenta: i64, rut: &str) -> (String, String, String) {
    let mut usuario = String::new();
    let (mut trib, mut cert) = (String::new(), String::new());
    if let Ok(Some(f)) = s.fila(
        "SELECT rut_usuario FROM claves_sii WHERE cuenta_id=? AND rut_empresa=?",
        &sql![cuenta, rut],
    ) {
        usuario = texto(&f["rut_usuario"]);
    }
    if let Ok(Some(b)) = s.bytes_de(
        "SELECT tributaria_cifrada, certificado_cifrada FROM claves_sii WHERE cuenta_id=? AND rut_empresa=?",
        &sql![cuenta, rut],
    ) {
        let desc = |x: &Vec<u8>| -> String {
            if x.is_empty() {
                return String::new();
            }
            s.descifrar(x).map(|v| String::from_utf8_lossy(&v).into_owned()).unwrap_or_default()
        };
        trib = desc(&b[0]);
        cert = desc(&b[1]);
    }
    (usuario, trib, cert)
}

/// `keystore.guardar_claves_sii`: upsert de lo que viene, conservando lo demás.
pub fn guardar_claves(
    s: &Servidor,
    cuenta: i64,
    rut: &str,
    usuario: &str,
    tributaria: &str,
    certificado: &str,
) -> Result<(), ErrorHTTP> {
    let prev = s.bytes_de(
        "SELECT tributaria_cifrada, certificado_cifrada FROM claves_sii WHERE cuenta_id=? AND rut_empresa=?",
        &sql![cuenta, rut],
    )?;
    let usuario_prev = s
        .fila(
            "SELECT rut_usuario FROM claves_sii WHERE cuenta_id=? AND rut_empresa=?",
            &sql![cuenta, rut],
        )?
        .map(|f| f["rut_usuario"].clone())
        .unwrap_or(Value::Null);
    let (mut trib, mut cert) = match prev {
        Some(b) => (b[0].clone(), b[1].clone()),
        None => (Vec::new(), Vec::new()),
    };
    if !tributaria.is_empty() {
        trib = s.cifrar(tributaria.as_bytes());
    }
    if !certificado.is_empty() {
        cert = s.cifrar(certificado.as_bytes());
    }
    let u: Sql = if !usuario.is_empty() {
        usuario.to_string().into()
    } else {
        match usuario_prev {
            Value::String(x) => x.into(),
            _ => Sql::Null,
        }
    };
    let a_blob = |b: Vec<u8>| {
        if b.is_empty() {
            Sql::Null
        } else {
            Sql::Blob(b)
        }
    };
    s.ejecutar(
        "INSERT INTO claves_sii (cuenta_id, rut_empresa, rut_usuario, tributaria_cifrada, certificado_cifrada, actualizado) VALUES (?,?,?,?,?,?)
         ON CONFLICT(cuenta_id, rut_empresa) DO UPDATE SET rut_usuario=excluded.rut_usuario, tributaria_cifrada=excluded.tributaria_cifrada,
         certificado_cifrada=excluded.certificado_cifrada, actualizado=excluded.actualizado",
        &sql![cuenta, rut, u, a_blob(trib), a_blob(cert), ahora_utc()],
    )?;
    Ok(())
}

fn guardar_claves_sii(s: &Servidor, p: &mut Peticion) -> Res {
    let cuenta = s.cuenta_id(p);
    let j = Json::leer(p)?;
    let Some(rut) = j.texto("rut_empresa")? else {
        return Err(ErrorHTTP::faltan(&["rut_empresa"]));
    };
    guardar_claves(
        s,
        cuenta,
        &rut,
        &j.texto_o("rut_usuario", "")?,
        &j.texto_o("clave_tributaria", "")?,
        &j.texto_o("clave_certificado", "")?,
    )?;
    ok(estado_claves(s, cuenta, &rut))
}

/// api/routes/mipyme.py::contexto_siiengine (claves recordadas + rutas).
fn contexto_siiengine(s: &Servidor, p: &mut Peticion) -> Res {
    let cuenta = s.cuenta_id(p);
    let rut = p.param("rut").to_string();
    let (usuario, trib, cert) = claves_guardadas(s, cuenta, &rut);
    ok(
        json!({"rut_empresa": rut, "rut_usuario": usuario, "clave_tributaria": trib, "clave_certificado": cert,
        "database_path": ruta_real(&s.cfg.database_path), "storage_path": ruta_real(&s.cfg.storage_path)}),
    )
}
