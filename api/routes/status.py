"""
api/routes/status.py

Endpoints para consultar el estado de DTEs enviados al SII.
"""

import base64
from typing import Optional

from typing import List

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from core import keystore
from core.auth import requerir_autenticacion
from core.crypto import CertificadoDigital
from core.errors import CertificadoError, SIIError
from core.seguimiento import estados_lote
from core.sii import AmbienteSII, ClienteSII

router = APIRouter(prefix="/api/v1/estado", tags=["Estado DTE en SII"])


class ConsultarTrackRequest(BaseModel):
    """Request para consultar el estado de un envío por TrackID."""
    track_id: int
    rut_empresa: str
    dv_empresa: str
    certificado_p12_b64: str
    password_certificado: str
    ambiente: AmbienteSII = AmbienteSII.CERTIFICACION


class ConsultarTrackResponse(BaseModel):
    """Respuesta con el estado de un envío."""
    track_id: int
    estado: Optional[str]
    glosa: Optional[str]
    ambiente: str


class ConsultarDTERequest(BaseModel):
    """Request para consultar el estado de un DTE específico."""
    rut_emisor: str
    dv_emisor: str
    tipo_dte: int
    folio: int
    fecha_emision: str  # Formato: YYYYMMDD
    monto_total: int
    rut_receptor: str
    dv_receptor: str
    certificado_p12_b64: str
    password_certificado: str
    ambiente: AmbienteSII = AmbienteSII.CERTIFICACION


class ConsultarDTEResponse(BaseModel):
    """Respuesta con el estado de un DTE."""
    folio: int
    tipo_dte: int
    estado: Optional[str]
    glosa: Optional[str]
    ambiente: str


@router.post(
    "/track",
    response_model=ConsultarTrackResponse,
    summary="Consultar estado de envío por TrackID",
    description="""
    Consulta el estado de procesamiento de un envío de DTEs al SII
    usando el número de TrackID obtenido al enviar los documentos.

    **Estados posibles:**
    - `EPR`: Envío recibido y procesado sin errores.
    - `SOK`: Set OK, documentos aceptados.
    - `CRT`: Documentos con reparos (algunos rechazados).
    - `RFR`: Rechazado por error en el archivo de envío.
    - `FOK`: En proceso (esperando resultado).
    """,
)
async def consultar_estado_track(body: ConsultarTrackRequest) -> ConsultarTrackResponse:
    """Consulta el estado de un envío de DTE por TrackID."""
    try:
        cert_bytes = base64.b64decode(body.certificado_p12_b64)
        cert = CertificadoDigital(cert_bytes, body.password_certificado)
    except Exception as e:
        raise CertificadoError(f"No se pudo cargar el certificado: {e}")

    try:
        cliente = ClienteSII(cert, body.ambiente)
        resultado = cliente.consultar_estado_track(body.track_id, body.rut_empresa, body.dv_empresa)
    except Exception as e:
        raise SIIError(f"Error al consultar el SII: {e}")

    return ConsultarTrackResponse(
        track_id=body.track_id,
        estado=resultado.get("estado"),
        glosa=resultado.get("glosa"),
        ambiente=body.ambiente.value,
    )


class EstadoLoteRequest(BaseModel):
    """Request para consultar el estado de varios envíos por TrackID."""
    track_ids: List[int]
    rut_empresa: str  # con o sin DV (ej. 76111111-6 o 76111111)
    cert_id: int
    ambiente: AmbienteSII = AmbienteSII.CERTIFICACION


@router.post("/lote", summary="Estado de varios envíos por TrackID (con resumen)")
async def consultar_estado_lote(
    body: EstadoLoteRequest,
    usuario: dict = Depends(requerir_autenticacion),
) -> dict:
    """Consulta el estado de un LOTE de envíos al SII y devuelve un resumen accionable
    (aceptados/rechazados/pendientes/todos_resueltos) + detalle por TrackID. Cierra el
    ciclo emitir → enviar → confirmar. Usa el certificado del keystore (`cert_id`)."""
    cert = keystore.cargar_certificado(body.cert_id, usuario["id"])
    num, dv = (body.rut_empresa.split("-") if "-" in body.rut_empresa
               else (body.rut_empresa, ""))
    cliente = ClienteSII(cert, body.ambiente)
    try:
        return estados_lote(cliente, body.track_ids, num, dv)
    finally:
        cliente.close()


@router.post(
    "/dte",
    response_model=ConsultarDTEResponse,
    summary="Consultar estado de un DTE específico",
    description="""
    Consulta el estado de un DTE individual por sus datos identificadores:
    RUT emisor, tipo, folio, fecha de emisión y monto total.

    Útil para verificar si el SII tiene registrado y aceptado un documento específico.
    """,
)
async def consultar_estado_dte(body: ConsultarDTERequest) -> ConsultarDTEResponse:
    """Consulta el estado de un DTE específico en el SII."""
    try:
        cert_bytes = base64.b64decode(body.certificado_p12_b64)
        cert = CertificadoDigital(cert_bytes, body.password_certificado)
    except Exception as e:
        raise CertificadoError(f"No se pudo cargar el certificado: {e}")

    try:
        cliente = ClienteSII(cert, body.ambiente)
        resultado = cliente.consultar_estado_dte(
            rut_emisor=body.rut_emisor,
            dv_emisor=body.dv_emisor,
            tipo_dte=body.tipo_dte,
            folio=body.folio,
            fecha_emision=body.fecha_emision,
            monto_total=body.monto_total,
            rut_receptor=body.rut_receptor,
            dv_receptor=body.dv_receptor,
        )
    except Exception as e:
        raise SIIError(f"Error al consultar el SII: {e}")

    return ConsultarDTEResponse(
        folio=body.folio,
        tipo_dte=body.tipo_dte,
        estado=resultado.get("estado"),
        glosa=resultado.get("glosa"),
        ambiente=body.ambiente.value,
    )
