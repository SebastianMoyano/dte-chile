//! /api/v1/apikeys: crear, listar, revocar. Exige un USUARIO (JWT), no una API key ni la clave
//! de la app: una key no puede crear más keys (api/routes/apikeys.py::requerir_usuario).

use super::auth::hex;
use super::errores::{ok, ErrorHTTP, Res};
use super::http::Peticion;
use super::{ahora_python, Json, Prot, Servidor};
use base64::Engine;
use serde_json::{json, Value};
use sha2::{Digest, Sha256};

pub fn rutas(s: &mut Servidor) {
    s.ruta("POST /api/v1/apikeys", Prot::Usuario, crear);
    s.ruta("GET /api/v1/apikeys", Prot::Usuario, listar);
    s.ruta("DELETE /api/v1/apikeys/{id}", Prot::Usuario, revocar);
}

/// `crear_api_key`: "dte_" + 32 bytes aleatorios en base64url (sin relleno).
pub fn generar_api_key() -> String {
    format!(
        "dte_{}",
        base64::engine::general_purpose::URL_SAFE_NO_PAD.encode(super::local::bytes_azar(32))
    )
}

fn crear(s: &Servidor, p: &mut Peticion) -> Res {
    let j = Json::leer(p)?;
    let Some(nombre_raw) = j.texto("nombre")? else {
        return Err(ErrorHTTP::faltan(&["nombre"]));
    };
    let nombre = nombre_raw.trim().to_string();
    let l = nombre_raw.chars().count();
    if !(1..=80).contains(&l) {
        return Err(ErrorHTTP::pydantic(
            "body",
            "nombre",
            "1-80 caracteres",
            "value_error",
        ));
    }
    let clave = generar_api_key();
    let h = hex(&Sha256::digest(clave.as_bytes()));
    let ahora = ahora_python();
    let id = s.ejecutar_id(
        "INSERT INTO api_keys (nombre, prefijo, key_hash, activo, creado) VALUES (?,?,?,1,?)",
        &[
            nombre.clone().into(),
            clave[..12].to_string().into(),
            h.into(),
            ahora.clone().into(),
        ],
    )?;
    Ok(super::errores::json(
        201,
        &json!({"api_key": clave, "aviso": "Guarda esta clave AHORA; no se vuelve a mostrar.",
            "id": id, "nombre": nombre, "prefijo": &clave[..12], "creado": ahora, "activo": true}),
    ))
}

fn listar(s: &Servidor, _p: &mut Peticion) -> Res {
    let filas = s.filas(
        "SELECT id, nombre, prefijo, activo, creado, ultimo_uso FROM api_keys ORDER BY id DESC",
        &[],
    )?;
    let out: Vec<Value> = filas
        .into_iter()
        .map(|f| json!({"id": f["id"], "nombre": f["nombre"], "prefijo": f["prefijo"], "activo": f["activo"], "creado": f["creado"], "ultimo_uso": f["ultimo_uso"]}))
        .collect();
    ok(Value::Array(out))
}

fn revocar(s: &Servidor, p: &mut Peticion) -> Res {
    let id: i64 = p
        .param("id")
        .parse()
        .map_err(|_| ErrorHTTP::datos_invalidos())?;
    let n = s.ejecutar("UPDATE api_keys SET activo=0 WHERE id=?", &sql![id])?;
    if n == 0 {
        return Err(ErrorHTTP::no_encontrado("API key no encontrada"));
    }
    ok(json!({"revocada": id}))
}
