"""
api/routes/auth.py

Endpoints de autenticación: login, registro, gestión de usuarios.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field

from core.errors import AutenticacionError, ConflictoError, ValidacionError
from core.auth import (
    crear_access_token,
    hash_password,
    verify_password,
    requerir_autenticacion,
)
from core.models import (
    crear_usuario,
    obtener_usuario_por_username,
    listar_usuarios,
    desactivar_usuario,
    registrar_log,
)

router = APIRouter(prefix="/api/v1/auth", tags=["Autenticación"])


# ---- Modelos de request/response ----

class LoginRequest(BaseModel):
    username: str = Field(..., description="Nombre de usuario")
    password: str = Field(..., description="Contraseña")


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str
    nombre_completo: str | None = None


class RegistroRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=50, description="Nombre de usuario")
    password: str = Field(..., min_length=6, description="Contraseña")
    nombre_completo: str | None = Field(None, description="Nombre completo")
    email: str | None = Field(None, description="Email")


class RegistroResponse(BaseModel):
    id: int
    username: str
    mensaje: str


class UsuarioResponse(BaseModel):
    id: int
    username: str
    nombre_completo: str | None
    email: str | None
    creado_en: str
    ultimo_acceso: str | None


class MensajeResponse(BaseModel):
    mensaje: str


# ---- Endpoints ----

@router.post("/login", response_model=LoginResponse, summary="Iniciar sesión")
async def login(body: LoginRequest) -> LoginResponse:
    """
    Autentica un usuario y retorna un token JWT.

    El token debe incluirse en el header `Authorization: Bearer <token>`
    para acceder a endpoints protegidos.
    """
    usuario = obtener_usuario_por_username(body.username)

    if not usuario or not verify_password(body.password, usuario["hashed_password"]):
        raise AutenticacionError("Credenciales inválidas")

    token = crear_access_token(data={"sub": usuario["username"]})

    registrar_log(
        accion="login",
        detalle=f"Login exitoso: {usuario['username']}",
    )

    return LoginResponse(
        access_token=token,
        username=usuario["username"],
        nombre_completo=usuario.get("nombre_completo"),
    )


@router.post(
    "/registro",
    response_model=RegistroResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar nuevo usuario",
)
async def registro(body: RegistroRequest) -> RegistroResponse:
    """
    Registra un nuevo usuario en el sistema.
    Requiere autenticación si ya existe al menos un usuario (el primero es admin).
    """
    existente = obtener_usuario_por_username(body.username)
    if existente:
        raise ConflictoError(f"El usuario '{body.username}' ya existe")

    hashed = hash_password(body.password)
    user_id = crear_usuario(
        username=body.username,
        hashed_password=hashed,
        nombre_completo=body.nombre_completo,
        email=body.email,
    )

    registrar_log(
        accion="registro_usuario",
        detalle=f"Nuevo usuario registrado: {body.username}",
    )

    return RegistroResponse(
        id=user_id,
        username=body.username,
        mensaje=f"Usuario '{body.username}' registrado correctamente",
    )


@router.get("/usuarios", response_model=list[UsuarioResponse], summary="Listar usuarios")
async def listar_todos_usuarios(
    usuario_actual: dict = Depends(requerir_autenticacion),
) -> list[UsuarioResponse]:
    """Lista todos los usuarios activos. Requiere autenticación."""
    usuarios = listar_usuarios()
    return [
        UsuarioResponse(
            id=u["id"],
            username=u["username"],
            nombre_completo=u.get("nombre_completo"),
            email=u.get("email"),
            creado_en=u["creado_en"],
            ultimo_acceso=u.get("ultimo_acceso"),
        )
        for u in usuarios
    ]


@router.delete(
    "/usuarios/{user_id}",
    response_model=MensajeResponse,
    summary="Desactivar usuario",
)
async def eliminar_usuario(
    user_id: int,
    usuario_actual: dict = Depends(requerir_autenticacion),
) -> MensajeResponse:
    """Desactiva un usuario. Requiere autenticación."""
    if user_id == usuario_actual["id"]:
        raise ValidacionError("No puedes desactivar tu propio usuario")

    desactivar_usuario(user_id)

    registrar_log(
        accion="desactivar_usuario",
        detalle=f"Usuario {user_id} desactivado por {usuario_actual['username']}",
    )

    return MensajeResponse(mensaje=f"Usuario {user_id} desactivado correctamente")


@router.get("/me", summary="Obtener información del usuario actual")
async def obtener_perfil(
    usuario_actual: dict = Depends(requerir_autenticacion),
) -> dict:
    """Retorna la información del usuario autenticado."""
    return {
        "id": usuario_actual["id"],
        "username": usuario_actual["username"],
        "nombre_completo": usuario_actual.get("nombre_completo"),
        "email": usuario_actual.get("email"),
        "creado_en": usuario_actual["creado_en"],
        "ultimo_acceso": usuario_actual.get("ultimo_acceso"),
    }
