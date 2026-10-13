"""
api/routes/simulacion.py — El mundo de práctica (EMPRESA DEMO SPA) para la app y el curso.

Nada de aquí toca al SII ni a una empresa real. Ver core/simulacion.py.
"""
from __future__ import annotations

from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from core import simulacion
from core.auth import requerir_autenticacion

router = APIRouter(prefix="/api/v1/simulacion", tags=["Simulación (empresa de práctica)"],
                   dependencies=[Depends(requerir_autenticacion)])


class ItemIn(BaseModel):
    nombre: str = Field(..., max_length=80)
    precio_unitario: float = Field(..., ge=0)
    cantidad: float = Field(1, ge=0)
    exento: bool = False


class ReceptorIn(BaseModel):
    rut: str
    razon_social: str
    giro: Optional[str] = None
    direccion: Optional[str] = None
    comuna: Optional[str] = None
    ciudad: Optional[str] = None
    es_contribuyente: bool = True


class EmitirIn(BaseModel):
    tipo_dte: int = Field(..., description="33, 34, 39, 41, 56 o 61")
    items: List[ItemIn]
    receptor: Optional[ReceptorIn] = None
    fecha: Optional[date] = None


class AnularIn(BaseModel):
    motivo: str = Field("Anula documento", max_length=90)


class NotaDebitoIn(BaseModel):
    motivo: Optional[str] = Field(None, max_length=90)
    monto: Optional[int] = Field(None, gt=0, description="Cobro que faltó (neto; no va en la anulación de una NC)")
    nombre: Optional[str] = Field(None, max_length=80, description="Qué se cobra")


@router.get("/estado", summary="Empresa demo, documentos emitidos y folio siguiente por tipo")
async def estado() -> dict:
    return await run_in_threadpool(simulacion.estado)


@router.post("/emitir", summary="Emitir un documento ficticio (se firma y timbra, nunca se envía)")
async def emitir(body: EmitirIn) -> dict:
    return await run_in_threadpool(
        simulacion.emitir, body.tipo_dte, [i.model_dump() for i in body.items],
        body.receptor.model_dump() if body.receptor else None, None, body.fecha)


@router.post("/anular/{dte_id}", summary="Nota de crédito que anula por el total un documento demo")
async def anular(dte_id: int, body: AnularIn | None = None) -> dict:
    return await run_in_threadpool(simulacion.anular, dte_id, (body.motivo if body else "Anula documento"))


@router.post("/nota-debito/{dte_id}", summary="Nota de débito demo: anula una nota de crédito, o agrega un cobro que faltó a un documento")
async def nota_debito(dte_id: int, body: NotaDebitoIn | None = None) -> dict:
    b = body or NotaDebitoIn()
    return await run_in_threadpool(simulacion.nota_debito, dte_id, b.motivo, b.monto, b.nombre)


@router.get("/documentos/{dte_id}", summary="Un documento demo con su PDF en base64")
async def ver(dte_id: int) -> dict:
    return await run_in_threadpool(simulacion.ver, dte_id)


@router.post("/reiniciar", summary="Borrar todo lo de la empresa demo y volver al folio 1")
async def reiniciar() -> dict:
    return await run_in_threadpool(simulacion.reiniciar)
