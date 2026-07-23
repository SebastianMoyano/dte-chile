"""
api/routes/certificado.py

Endpoints para gestión del certificado digital del contribuyente.
"""

import base64
from typing import Annotated

from fastapi import APIRouter, UploadFile, File, Form
from api.util import leer_upload
from pydantic import BaseModel

from core.crypto import CertificadoDigital
from core.errors import CertificadoError, ValidacionError

router = APIRouter(prefix="/api/v1/certificado", tags=["Certificado Digital"])


class CertificadoInfoResponse(BaseModel):
    """Información básica del certificado cargado."""
    rut_emisor: str
    certificado_b64: str  # Primeros 100 chars del certificado público (para validación visual)
    mensaje: str


@router.post(
    "/validar",
    response_model=CertificadoInfoResponse,
    summary="Validar y cargar un certificado digital",
    description="""
    Sube un archivo de certificado digital (.p12 / .pfx) y valida que sea legible
    con la contraseña proporcionada.

    Retorna información básica del certificado como el RUT del emisor
    y los primeros caracteres del certificado público para validación visual.

    **Importante**: Por seguridad, el certificado NO se almacena en el servidor.
    Para operaciones de firma, debe enviarse en cada petición.
    """,
)
async def validar_certificado(
    archivo: Annotated[UploadFile, File(description="Archivo .p12 o .pfx del certificado digital")],
    password: Annotated[str, Form(description="Contraseña del certificado")],
) -> CertificadoInfoResponse:
    """
    Valida un certificado digital .p12/.pfx con su contraseña.
    """
    if not archivo.filename or not archivo.filename.lower().endswith((".p12", ".pfx")):
        raise ValidacionError("El archivo debe ser un certificado digital .p12 o .pfx")

    contenido = await leer_upload(archivo)
    if len(contenido) == 0:
        raise ValidacionError("El archivo está vacío.")

    try:
        cert = CertificadoDigital(contenido, password)
    except ValueError as e:
        raise CertificadoError(f"No se pudo cargar el certificado: {e}")

    cert_b64_preview = cert.certificado_b64[:80] + "..."

    return CertificadoInfoResponse(
        rut_emisor=cert.rut_emisor,
        certificado_b64=cert_b64_preview,
        mensaje=f"Certificado cargado correctamente para el emisor {cert.rut_emisor}.",
    )


class FirmarDatosRequest(BaseModel):
    """Request para firmar datos crudos con el certificado."""
    datos_b64: str
    password: str
    certificado_p12_b64: str


class FirmarDatosResponse(BaseModel):
    """Respuesta con la firma digital de los datos."""
    firma_b64: str
    algoritmo: str = "RSA-SHA1"


@router.post(
    "/firmar-datos",
    response_model=FirmarDatosResponse,
    summary="Firmar datos crudos con el certificado",
    description="Firma datos arbitrarios en Base64 con el certificado digital. Útil para pruebas de firma.",
)
async def firmar_datos(body: FirmarDatosRequest) -> FirmarDatosResponse:
    """
    Firma datos enviados en Base64 con el certificado digital.
    """
    try:
        cert_bytes = base64.b64decode(body.certificado_p12_b64)
        cert = CertificadoDigital(cert_bytes, body.password)
    except Exception as e:
        raise CertificadoError(f"No se pudo cargar el certificado: {e}")

    try:
        datos = base64.b64decode(body.datos_b64)
    except Exception as e:
        raise ValidacionError(f"Los datos no son Base64 válido: {e}")

    firma = cert.firmar_datos(datos)  # fallo inesperado → 500 global
    firma_b64 = base64.b64encode(firma).decode("ascii")
    return FirmarDatosResponse(firma_b64=firma_b64)
