//! /api/v1/auth/*: login (sha256_crypt de passlib + JWT HS256), registro, usuarios, me.
//! Réplica de api/routes/auth.py y core/auth.py / core/models.py.

use super::auth::{crear_jwt, hash_password, verificar_password};
use super::errores::{ok, ErrorHTTP, Res};
use super::http::Peticion;
use super::{ahora_python, entero, texto, Json, Prot, Servidor};
use serde_json::{json, Value};

pub fn rutas(s: &mut Servidor) {
    s.ruta("POST /api/v1/auth/login", Prot::Publica, login);
    s.ruta("POST /api/v1/auth/registro", Prot::Publica, registro);
    s.ruta("GET /api/v1/auth/usuarios", Prot::Protegida, listar);
    s.ruta(
        "DELETE /api/v1/auth/usuarios/{id}",
        Prot::Protegida,
        desactivar,
    );
    s.ruta("GET /api/v1/auth/me", Prot::Protegida, perfil);
}

fn usuario_completo(
    s: &Servidor,
    username: &str,
) -> Result<Option<serde_json::Map<String, Value>>, ErrorHTTP> {
    Ok(s.fila(
        "SELECT id, username, hashed_password, nombre_completo, email, creado_en, ultimo_acceso FROM usuarios WHERE username=? AND activo=1",
        &sql![username],
    )?)
}

fn login(s: &Servidor, p: &mut Peticion) -> Res {
    let j = Json::leer(p)?;
    let (username, password) = (j.texto("username")?, j.texto("password")?);
    let mut f = Vec::new();
    if username.is_none() {
        f.push("username");
    }
    if password.is_none() {
        f.push("password");
    }
    if !f.is_empty() {
        return Err(ErrorHTTP::faltan(&f));
    }
    let (username, password) = (username.unwrap_or_default(), password.unwrap_or_default());
    let u = usuario_completo(s, &username)?;
    let Some(u) = u.filter(|u| verificar_password(&password, &texto(&u["hashed_password"]))) else {
        return Err(ErrorHTTP::autenticacion("Credenciales inválidas"));
    };
    s.registrar_log("login", &format!("Login exitoso: {username}"));
    ok(
        json!({"access_token": crear_jwt(&s.cfg.jwt_secret, &username, s.cfg.jwt_expira_min), "token_type": "bearer",
        "username": username, "nombre_completo": u["nombre_completo"]}),
    )
}

fn registro(s: &Servidor, p: &mut Peticion) -> Res {
    let j = Json::leer(p)?;
    let (username, password) = (j.texto("username")?, j.texto("password")?);
    let mut f = Vec::new();
    if username.is_none() {
        f.push("username");
    }
    if password.is_none() {
        f.push("password");
    }
    if !f.is_empty() {
        return Err(ErrorHTTP::faltan(&f));
    }
    let (username, password) = (username.unwrap_or_default(), password.unwrap_or_default());
    let l = username.chars().count();
    if !(3..=50).contains(&l) || password.chars().count() < 6 {
        return Err(ErrorHTTP::pydantic(
            "body",
            "",
            "username 3-50 y password ≥ 6",
            "value_error",
        ));
    }
    let n: i64 = s
        .escalar(
            "SELECT COUNT(*) FROM usuarios WHERE username=? AND activo=1",
            &sql![username.clone()],
        )?
        .unwrap_or(0);
    if n > 0 {
        return Err(ErrorHTTP::conflicto(format!(
            "El usuario '{username}' ya existe"
        )));
    }
    let h = hash_password(&password);
    let nombre: rusqlite::types::Value = j
        .texto("nombre_completo")?
        .map(Into::into)
        .unwrap_or(rusqlite::types::Value::Null);
    let email: rusqlite::types::Value = j
        .texto("email")?
        .map(Into::into)
        .unwrap_or(rusqlite::types::Value::Null);
    let id = s
        .ejecutar_id(
            "INSERT INTO usuarios (username, hashed_password, nombre_completo, email, creado_en) VALUES (?, ?, ?, ?, ?)",
            &sql![username.clone(), h, nombre, email, ahora_python()],
        )
        .map_err(|_| ErrorHTTP::conflicto(format!("El usuario '{username}' ya existe")))?;
    s.registrar_log(
        "registro_usuario",
        &format!("Nuevo usuario registrado: {username}"),
    );
    Ok(super::errores::json(
        201,
        &json!({"id": id, "username": username, "mensaje": format!("Usuario '{username}' registrado correctamente")}),
    ))
}

fn listar(s: &Servidor, _p: &mut Peticion) -> Res {
    let filas = s.filas(
        "SELECT id, username, nombre_completo, email, activo, creado_en, ultimo_acceso FROM usuarios WHERE activo=1",
        &[],
    )?;
    let out: Vec<Value> = filas
        .into_iter()
        .map(|f| {
            json!({"id": f["id"], "username": f["username"], "nombre_completo": f["nombre_completo"], "email": f["email"],
                "creado_en": f["creado_en"], "ultimo_acceso": f["ultimo_acceso"]})
        })
        .collect();
    ok(Value::Array(out))
}

fn desactivar(s: &Servidor, p: &mut Peticion) -> Res {
    let id: i64 = p.param("id").parse().map_err(|_| {
        ErrorHTTP::pydantic(
            "path",
            "user_id",
            "Input should be a valid integer",
            "int_parsing",
        )
    })?;
    let u = p.usuario.clone().unwrap_or_default();
    if u.tipo == "usuario" && u.id == id {
        return Err(ErrorHTTP::validacion(
            "No puedes desactivar tu propio usuario",
        ));
    }
    s.ejecutar("UPDATE usuarios SET activo=0 WHERE id=?", &sql![id])?;
    s.registrar_log(
        "desactivar_usuario",
        &format!("Usuario {id} desactivado por {}", u.username),
    );
    ok(json!({"mensaje": format!("Usuario {id} desactivado correctamente")}))
}

fn perfil(s: &Servidor, p: &mut Peticion) -> Res {
    let u = p.usuario.clone().unwrap_or_default();
    if u.tipo != "usuario" {
        // Python devuelve el dict de la API key (id None, sin creado_en → KeyError 500); aquí un 422 claro.
        return Err(ErrorHTTP::validacion(
            "El perfil es de usuarios (JWT), no de API keys.",
        ));
    }
    let Some(f) = usuario_completo(s, &u.username)? else {
        return Err(ErrorHTTP::no_encontrado("Usuario no encontrado"));
    };
    let _ = entero(&f["id"]);
    ok(
        json!({"id": f["id"], "username": f["username"], "nombre_completo": f["nombre_completo"], "email": f["email"],
        "creado_en": f["creado_en"], "ultimo_acceso": f["ultimo_acceso"]}),
    )
}
