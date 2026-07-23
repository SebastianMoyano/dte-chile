"""
api/routes/apikeys.py — Gestión de API keys (bearer estáticas para integraciones/agentes).

Crear/listar/revocar. Requiere **usuario real (JWT)**, no una API key, para que una key no pueda
crear más keys. La clave en claro se devuelve **una sola vez** al crearla.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from core import apikeys
from core.auth import requerir_usuario

router = APIRouter(prefix="/api/v1/apikeys", tags=["API Keys"])


class CrearKeyRequest(BaseModel):
    nombre: str = Field(..., min_length=1, max_length=80, description="Nombre para identificar la key")


@router.post("", status_code=status.HTTP_201_CREATED, summary="Crear una API key")
async def crear(body: CrearKeyRequest, usuario: dict = Depends(requerir_usuario)) -> dict:
    """Crea una API key nueva. Devuelve la clave en claro **una sola vez** — guárdala ya."""
    clave, reg = apikeys.crear_api_key(body.nombre.strip())
    return {"api_key": clave,
            "aviso": "Guarda esta clave AHORA; no se vuelve a mostrar.", **reg}


@router.get("", summary="Listar API keys")
async def listar(usuario: dict = Depends(requerir_usuario)) -> list:
    """Lista las keys (sin exponer la clave: solo el prefijo, estado y uso)."""
    return apikeys.listar_api_keys()


@router.delete("/{key_id}", summary="Revocar una API key")
async def revocar(key_id: int, usuario: dict = Depends(requerir_usuario)) -> dict:
    if not apikeys.revocar_api_key(key_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "API key no encontrada")
    return {"revocada": key_id}
