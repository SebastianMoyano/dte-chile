"""
api/routes/db.py

Endpoints para consultar y gestionar datos persistentes:
- Listar DTEs emitidos
- Gestionar CAFs
- Consultar logs de auditoría
- Obtener siguiente folio disponible
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query, UploadFile, File
from api.util import leer_upload
from pydantic import BaseModel, Field

from core.auth import requerir_autenticacion
from core.caf import ManejadorCAF
from core.errors import CAFError, RecursoNoEncontrado, ValidacionError
from core.models import (
    listar_dtes,
    contar_dtes,
    obtener_dte,
    obtener_dte_por_folio,
    listar_cafs,
    obtener_caf_activo,
    obtener_siguiente_folio,
    registrar_caf,
    listar_logs,
)

router = APIRouter(prefix="/api/v1/db", tags=["Base de Datos"])


# ---- Modelos de respuesta ----

class DTEResponse(BaseModel):
    id: int
    tipo_dte: int
    folio: int
    rut_emisor: str
    rut_receptor: str
    razon_social_receptor: Optional[str]
    fecha_emision: str
    monto_neto: int
    monto_exento: int
    iva: int
    monto_total: int
    estado: str
    track_id: Optional[int]
    pdf_path: Optional[str]
    ambiente: str
    creado_en: str


class DTEListResponse(BaseModel):
    total: int
    dtes: list[DTEResponse]


class CAFResponse(BaseModel):
    id: int
    tipo_dte: int
    rut_emisor: str
    folio_desde: int
    folio_hasta: int
    folio_siguiente: int
    fecha_autorizacion: str
    activo: bool
    creado_en: str


class FolioDisponibleResponse(BaseModel):
    rut_emisor: str
    tipo_dte: int
    folio_disponible: Optional[int]
    folio_desde: Optional[int]
    folio_hasta: Optional[int]
    mensaje: str


class LogResponse(BaseModel):
    id: int
    accion: str
    tipo_dte: Optional[int]
    folio: Optional[int]
    rut_emisor: Optional[str]
    detalle: Optional[str]
    creado_en: str


class RegistrarCAFRequest(BaseModel):
    tipo_dte: int
    rut_emisor: str
    folio_desde: int
    folio_hasta: int
    fecha_autorizacion: str
    caf_xml: str


# ---- Endpoints DTEs ----

@router.get("/dtes", response_model=DTEListResponse, summary="Listar DTEs emitidos")
async def get_dtes(
    rut_emisor: Optional[str] = Query(None, description="Filtrar por RUT emisor"),
    tipo_dte: Optional[int] = Query(None, description="Filtrar por tipo DTE"),
    estado: Optional[str] = Query(None, description="Filtrar por estado"),
    fecha_desde: Optional[str] = Query(None, description="Fecha desde (YYYY-MM-DD)"),
    fecha_hasta: Optional[str] = Query(None, description="Fecha hasta (YYYY-MM-DD)"),
    limite: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    usuario: dict = Depends(requerir_autenticacion),
) -> DTEListResponse:
    """Lista los DTEs emitidos con filtros opcionales."""
    dtes = listar_dtes(
        rut_emisor=rut_emisor,
        tipo_dte=tipo_dte,
        estado=estado,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        limite=limite,
        offset=offset,
    )
    total = contar_dtes(rut_emisor=rut_emisor, tipo_dte=tipo_dte, estado=estado)

    return DTEListResponse(
        total=total,
        dtes=[DTEResponse(**d) for d in dtes],
    )


@router.get("/dtes/{dte_id}", response_model=DTEResponse, summary="Obtener DTE por ID")
async def get_dte(
    dte_id: int,
    usuario: dict = Depends(requerir_autenticacion),
) -> DTEResponse:
    """Obtiene un DTE específico por su ID."""
    dte = obtener_dte(dte_id)
    if not dte:
        raise RecursoNoEncontrado("DTE no encontrado")
    return DTEResponse(**dte)


@router.get(
    "/dtes/buscar/{rut_emisor}/{tipo_dte}/{folio}",
    response_model=DTEResponse,
    summary="Buscar DTE por emisor, tipo y folio",
)
async def buscar_dte(
    rut_emisor: str,
    tipo_dte: int,
    folio: int,
    usuario: dict = Depends(requerir_autenticacion),
) -> DTEResponse:
    """Busca un DTE por RUT emisor, tipo y folio."""
    dte = obtener_dte_por_folio(rut_emisor, tipo_dte, folio)
    if not dte:
        raise RecursoNoEncontrado("DTE no encontrado")
    return DTEResponse(**dte)


# ---- Endpoints CAFs ----

@router.get("/cafs", response_model=list[CAFResponse], summary="Listar CAFs registrados")
async def get_cafs(
    rut_emisor: Optional[str] = Query(None),
    tipo_dte: Optional[int] = Query(None),
    usuario: dict = Depends(requerir_autenticacion),
) -> list[CAFResponse]:
    """Lista los CAFs registrados."""
    cafs = listar_cafs(rut_emisor=rut_emisor, tipo_dte=tipo_dte)
    return [
        CAFResponse(
            id=c["id"],
            tipo_dte=c["tipo_dte"],
            rut_emisor=c["rut_emisor"],
            folio_desde=c["folio_desde"],
            folio_hasta=c["folio_hasta"],
            folio_siguiente=c["folio_siguiente"],
            fecha_autorizacion=c["fecha_autorizacion"],
            activo=bool(c["activo"]),
            creado_en=c["creado_en"],
        )
        for c in cafs
    ]


@router.get(
    "/cafs/activo/{rut_emisor}/{tipo_dte}",
    response_model=CAFResponse,
    summary="Obtener CAF activo",
)
async def get_caf_activo(
    rut_emisor: str,
    tipo_dte: int,
    usuario: dict = Depends(requerir_autenticacion),
) -> CAFResponse:
    """Obtiene el CAF activo para un emisor y tipo de DTE."""
    caf = obtener_caf_activo(rut_emisor, tipo_dte)
    if not caf:
        raise RecursoNoEncontrado("No hay CAF activo para estos parámetros")
    return CAFResponse(
        id=caf["id"],
        tipo_dte=caf["tipo_dte"],
        rut_emisor=caf["rut_emisor"],
        folio_desde=caf["folio_desde"],
        folio_hasta=caf["folio_hasta"],
        folio_siguiente=caf["folio_siguiente"],
        fecha_autorizacion=caf["fecha_autorizacion"],
        activo=bool(caf["activo"]),
        creado_en=caf["creado_en"],
    )


@router.post(
    "/cafs",
    response_model=CAFResponse,
    summary="Registrar un nuevo CAF subiendo el XML",
    description="Sube un archivo CAF XML descargado del SII y lo registra de forma persistente en la BD.",
)
async def post_registrar_caf(
    archivo: UploadFile = File(..., description="Archivo CAF XML"),
    usuario: dict = Depends(requerir_autenticacion),
) -> CAFResponse:
    """Registra un nuevo CAF leyendo sus metadatos del XML."""
    if not archivo.filename or not archivo.filename.lower().endswith(".xml"):
        raise ValidacionError("El archivo debe ser un CAF en formato XML.")

    contenido = await leer_upload(archivo)

    try:
        caf = ManejadorCAF(contenido)
    except ValueError as e:
        raise CAFError(f"No se pudo parsear el CAF: {e}")

    d = caf.datos

    # Desactivar cualquier CAF activo anterior del mismo tipo y emisor
    # (El sistema requiere sólo un CAF activo por tipo y emisor)
    try:
        from core.database import ejecutar
        ejecutar(
            "UPDATE cafs SET activo=0 WHERE rut_emisor=? AND tipo_dte=?",
            (d.rut_emisor, d.tipo_dte),
        )
    except Exception as e:
        pass

    # Fallo al guardar → 500 vía el handler global (traza al log).
    caf_id = registrar_caf(
        tipo_dte=d.tipo_dte,
        rut_emisor=d.rut_emisor,
        folio_desde=d.folio_desde,
        folio_hasta=d.folio_hasta,
        fecha_autorizacion=d.fecha_autorizacion.isoformat(),
        caf_xml=contenido.decode("utf-8", errors="ignore"),
    )

    # Buscar el CAF recién registrado para retornar la respuesta
    caf_registrado = obtener_caf_activo(d.rut_emisor, d.tipo_dte)
    if not caf_registrado:
        raise RuntimeError("CAF registrado pero no se pudo recuperar para la respuesta.")

    return CAFResponse(
        id=caf_registrado["id"],
        tipo_dte=caf_registrado["tipo_dte"],
        rut_emisor=caf_registrado["rut_emisor"],
        folio_desde=caf_registrado["folio_desde"],
        folio_hasta=caf_registrado["folio_hasta"],
        folio_siguiente=caf_registrado["folio_siguiente"],
        fecha_autorizacion=caf_registrado["fecha_autorizacion"],
        activo=bool(caf_registrado["activo"]),
        creado_en=caf_registrado["creado_en"],
    )


@router.get(
    "/folios/siguiente/{rut_emisor}/{tipo_dte}",
    response_model=FolioDisponibleResponse,
    summary="Obtener siguiente folio disponible",
)
async def get_siguiente_folio(
    rut_emisor: str,
    tipo_dte: int,
    usuario: dict = Depends(requerir_autenticacion),
) -> FolioDisponibleResponse:
    """Obtiene el siguiente folio disponible para emitir."""
    folio = obtener_siguiente_folio(rut_emisor, tipo_dte)
    caf = obtener_caf_activo(rut_emisor, tipo_dte)

    if not caf:
        return FolioDisponibleResponse(
            rut_emisor=rut_emisor,
            tipo_dte=tipo_dte,
            folio_disponible=None,
            folio_desde=None,
            folio_hasta=None,
            mensaje="No hay CAF activo. Debe registrar un CAF primero.",
        )

    if folio is None:
        return FolioDisponibleResponse(
            rut_emisor=rut_emisor,
            tipo_dte=tipo_dte,
            folio_disponible=None,
            folio_desde=caf["folio_desde"],
            folio_hasta=caf["folio_hasta"],
            mensaje="Rango de folios agotado. Debe solicitar nuevos folios al SII.",
        )

    return FolioDisponibleResponse(
        rut_emisor=rut_emisor,
        tipo_dte=tipo_dte,
        folio_disponible=folio,
        folio_desde=caf["folio_desde"],
        folio_hasta=caf["folio_hasta"],
        mensaje=f"Siguiente folio disponible: {folio}",
    )


# ---- Endpoints Logs ----

@router.get("/logs", response_model=list[LogResponse], summary="Consultar logs de auditoría")
async def get_logs(
    accion: Optional[str] = Query(None),
    rut_emisor: Optional[str] = Query(None),
    fecha_desde: Optional[str] = Query(None),
    limite: int = Query(100, ge=1, le=1000),
    usuario: dict = Depends(requerir_autenticacion),
) -> list[LogResponse]:
    """Consulta los logs de auditoría."""
    logs = listar_logs(
        accion=accion,
        rut_emisor=rut_emisor,
        fecha_desde=fecha_desde,
        limite=limite,
    )
    return [
        LogResponse(
            id=log["id"],
            accion=log["accion"],
            tipo_dte=log.get("tipo_dte"),
            folio=log.get("folio"),
            rut_emisor=log.get("rut_emisor"),
            detalle=log.get("detalle"),
            creado_en=log["creado_en"],
        )
        for log in logs
    ]
