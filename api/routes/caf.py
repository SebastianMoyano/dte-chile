"""
api/routes/caf.py

Endpoints para gestión de CAF (Código de Autorización de Folios).
"""

from fastapi import APIRouter, UploadFile, File
from api.util import leer_upload
from pydantic import BaseModel
from typing import Annotated

from core.caf import ManejadorCAF
from core.errors import CAFError, ValidacionError

router = APIRouter(prefix="/api/v1/caf", tags=["CAF - Folios"])


class CAFInfoResponse(BaseModel):
    """Información del CAF cargado."""
    tipo_dte: int
    rut_emisor: str
    folio_desde: int
    folio_hasta: int
    fecha_autorizacion: str
    total_folios: int
    mensaje: str


class ValidarFolioRequest(BaseModel):
    """Request para validar un folio contra un CAF en Base64."""
    caf_xml_b64: str
    folio: int


class ValidarFolioResponse(BaseModel):
    """Respuesta de validación de folio."""
    folio: int
    valido: bool
    mensaje: str


@router.post(
    "/info",
    response_model=CAFInfoResponse,
    summary="Obtener información de un archivo CAF",
    description="""
    Carga un archivo CAF XML entregado por el SII y retorna su información:
    tipo de DTE, rango de folios autorizados y fecha de autorización.

    El CAF es el archivo que el SII entrega al contribuyente para que pueda
    numerar y timbrar sus documentos tributarios electrónicos.
    """,
)
async def info_caf(
    archivo: Annotated[UploadFile, File(description="Archivo CAF en formato XML")],
) -> CAFInfoResponse:
    """
    Retorna la información de un archivo CAF.
    """
    if not archivo.filename or not archivo.filename.lower().endswith(".xml"):
        raise ValidacionError("El archivo debe ser un CAF en formato XML.")

    contenido = await leer_upload(archivo)

    try:
        caf = ManejadorCAF(contenido)
    except ValueError as e:
        raise CAFError(f"No se pudo parsear el CAF: {e}")

    d = caf.datos
    total_folios = d.folio_hasta - d.folio_desde + 1

    return CAFInfoResponse(
        tipo_dte=d.tipo_dte,
        rut_emisor=d.rut_emisor,
        folio_desde=d.folio_desde,
        folio_hasta=d.folio_hasta,
        fecha_autorizacion=d.fecha_autorizacion.isoformat(),
        total_folios=total_folios,
        mensaje=f"CAF válido para {total_folios} folios del tipo DTE {d.tipo_dte}.",
    )


@router.post(
    "/validar-folio",
    response_model=ValidarFolioResponse,
    summary="Validar si un folio está autorizado en un CAF",
)
async def validar_folio(body: ValidarFolioRequest) -> ValidarFolioResponse:
    """
    Verifica si un número de folio está dentro del rango autorizado por el CAF.
    """
    import base64
    try:
        caf_bytes = base64.b64decode(body.caf_xml_b64)
        caf = ManejadorCAF(caf_bytes)
    except Exception as e:
        raise CAFError(f"No se pudo procesar el CAF: {e}")

    es_valido = caf.es_folio_valido(body.folio)

    return ValidarFolioResponse(
        folio=body.folio,
        valido=es_valido,
        mensaje=(
            f"El folio {body.folio} está autorizado en el CAF."
            if es_valido
            else f"El folio {body.folio} está FUERA del rango [{caf.datos.folio_desde}-{caf.datos.folio_hasta}] del CAF."
        ),
    )
