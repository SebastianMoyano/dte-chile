"""
api/routes/dte.py

Endpoints para generar, firmar y enviar DTEs al SII de Chile.

Manejo de errores: las rutas levantan **errores de dominio** (`core/errors`) para los
fallos esperados (datos inválidos, CAF/folio, cert, rechazo del SII). Los fallos
inesperados NO se capturan: los normaliza el handler global (`api/errors`) a un 500
uniforme con la traza en el log. No hay `except Exception → HTTPException` ad-hoc.
"""

import base64
import json
from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, File, Form, UploadFile
from api.util import leer_upload
from fastapi.responses import Response
from pydantic import BaseModel

from core.auth import requerir_autenticacion
from core.caf import ManejadorCAF
from core.config import settings
from core.crypto import CertificadoDigital
from core.sobre import firmar_documento_standalone
from core.dte import DTEInput, GeneradorDTE, TipoDTE, calcular_totales
from core.errors import CAFError, CertificadoError, FolioError, SIIError, SIIRechazoError, ValidacionError
from core.orchestrator import emitir_documento
from core.pdf_gen import generar_pdf_dte
from core.preview import previsualizar_dte as _previsualizar_dte
from core.sii import AmbienteSII, ClienteSII
from core import keystore
from core.models import listar_dtes, obtener_caf_activo, obtener_dte

router = APIRouter(prefix="/api/v1/dte", tags=["DTE - Documentos Tributarios"])


# ---- Modelos de respuesta ----

class GenerarDTEResponse(BaseModel):
    """Resultado de la generación de un DTE."""
    folio: int
    tipo_dte: int
    monto_total: int
    xml_b64: str  # XML del DTE firmado codificado en Base64
    mensaje: str


class EnviarDTERequest(BaseModel):
    """Request para enviar un DTE ya generado al SII."""
    xml_envio_b64: str
    certificado_p12_b64: str
    password_certificado: str
    rut_empresa: str
    dv_empresa: str
    tipo_dte: int = 33
    ambiente: AmbienteSII = AmbienteSII.CERTIFICACION


class EnviarDTEResponse(BaseModel):
    """Resultado del envío de un DTE al SII."""
    track_id: int
    mensaje: str
    ambiente: str


class ValidarXMLRequest(BaseModel):
    """Request para validar XML contra esquema XSD del SII."""
    xml_b64: str  # XML del DTE o EnvioDTE en Base64


class ValidarXMLResponse(BaseModel):
    """Resultado de la validación XSD."""
    valido: bool
    tipo_xml: str
    errores: List[str]
    mensaje: str


# ---- Helpers ----

def _cargar_cert(cert_bytes: bytes, password: str) -> CertificadoDigital:
    """Carga un certificado o levanta `CertificadoError` (→ 422)."""
    try:
        return CertificadoDigital(cert_bytes, password)
    except Exception as e:
        raise CertificadoError(f"No se pudo cargar el certificado: {e}")


def _decode_b64(data: str, que: str) -> bytes:
    """Decodifica Base64 o levanta `ValidacionError` (→ 422)."""
    try:
        return base64.b64decode(data)
    except Exception as e:
        raise ValidacionError(f"{que} no es Base64 válido: {e}")


def _parse_dte_input(dte_json: str) -> DTEInput:
    """Parsea el JSON del DTE a `DTEInput` o levanta `ValidacionError`."""
    try:
        return DTEInput(**json.loads(dte_json))
    except Exception as e:
        raise ValidacionError(f"Datos del DTE inválidos: {e}")


# ---- Endpoints ----

@router.get("/documentos", summary="Últimos documentos emitidos (folio, estado, TrackID)")
async def listar_documentos(
    limite: int = 25,
    tipo_dte: Optional[int] = None,
    estado: Optional[str] = None,
    rut_emisor: Optional[str] = None,
) -> dict:
    """Lista los documentos emitidos, del más reciente al más antiguo.

    Es la vista "¿qué fue de mi última boleta?": folio, montos, estado
    (generado/enviado/aceptado/rechazado) y TrackID, sin tener que mirar la BD.
    El XML no se incluye (para eso está `/consulta/xml` o la BD).
    """
    from pathlib import Path
    docs = listar_dtes(rut_emisor=rut_emisor, tipo_dte=tipo_dte, estado=estado,
                       limite=max(1, min(limite, 200)))
    for d in docs:
        d["tiene_xml"] = bool(d.pop("xml_firmado", None))
        d["tiene_pdf"] = bool(d.get("pdf_path")) and Path(d["pdf_path"]).exists()
        d["canal"] = "mipyme" if (d.get("estado") or "").endswith("_mipyme") else "motor"
    return {"total": len(docs), "documentos": docs}


@router.get("/emisor", summary="Datos del emisor configurado en el motor (EMPRESA_* del .env)")
async def emisor_configurado() -> dict:
    """Los datos fijos del emisor que el motor usa para armar un DTE (giro, código de actividad,
    dirección). Son los de `.env` (`EMPRESA_*`). La app de escritorio los lee para no pedirlos
    en cada emisión; `configurada` es False si faltan RUT o razón social."""
    return {
        "configurada": settings.empresa_configurada,
        "rut": settings.empresa_rut, "razon_social": settings.empresa_razon_social,
        "giro": settings.empresa_giro, "codigo_actividad": settings.empresa_codigo_actividad,
        "direccion": settings.empresa_direccion, "comuna": settings.empresa_comuna,
        "ciudad": settings.empresa_ciudad, "email": settings.empresa_email or None,
        "telefono": settings.empresa_telefono or None,
    }


@router.get("/documentos/emisores", summary="Empresas emisoras presentes en la BD (para filtrar)")
async def emisores_documentos() -> dict:
    """RUT emisor distinto con cuántos documentos tiene y su razón social si está registrada
    como negocio. Sirve para que la vista de documentos no mezcle empresas."""
    from core.database import obtener_todos
    filas = obtener_todos(
        "SELECT rut_emisor, COUNT(*) AS n, MAX(fecha_emision) AS ultimo FROM dtes "
        "GROUP BY rut_emisor ORDER BY ultimo DESC")
    nombres = {}
    try:
        nombres = {r["rut"]: r["razon_social"] for r in obtener_todos("SELECT rut, razon_social FROM negocios")}
    except Exception:  # noqa: BLE001 — sin tabla de negocios seguimos con el RUT a secas
        pass
    return {"emisores": [{"rut": f["rut_emisor"], "razon_social": nombres.get(f["rut_emisor"]),
                          "documentos": f["n"], "ultimo": f["ultimo"]} for f in filas]}


@router.get("/documentos/{dte_id}/pdf", summary="PDF de un documento (motor o canal MIPYME)")
async def pdf_documento(dte_id: int) -> Response:
    """Sirve el PDF guardado en disco (el del motor, o el que bajó el importador MIPYME)."""
    from pathlib import Path
    from core.errors import RecursoNoEncontrado
    d = obtener_dte(dte_id)
    if not d:
        raise RecursoNoEncontrado(f"Documento {dte_id} no existe")
    pp = d.get("pdf_path")
    if not pp or not Path(pp).exists():
        raise RecursoNoEncontrado("Este documento no tiene PDF guardado")
    raiz = Path("storage").resolve()
    if raiz not in Path(pp).resolve().parents:   # nunca servir algo fuera de storage/
        raise RecursoNoEncontrado("Ruta de PDF fuera del almacenamiento del motor")
    return Response(Path(pp).read_bytes(), media_type="application/pdf", headers={
        "Content-Disposition": f'inline; filename="dte_{d["tipo_dte"]}_{d["folio"]}.pdf"'})


@router.get("/documentos/{dte_id}/xml", summary="XML firmado de un documento")
async def xml_documento(dte_id: int) -> Response:
    """El XML firmado tal como se guardó (ISO-8859-1). Los importados del historial MIPYME
    no lo tienen: el portal solo entregó el PDF."""
    from core.errors import RecursoNoEncontrado
    d = obtener_dte(dte_id)
    if not d:
        raise RecursoNoEncontrado(f"Documento {dte_id} no existe")
    if not d.get("xml_firmado"):
        raise RecursoNoEncontrado("Este documento no tiene XML guardado")
    return Response(d["xml_firmado"].encode("iso-8859-1", "replace"), media_type="application/xml",
                    headers={"Content-Disposition": f'attachment; filename="dte_{d["tipo_dte"]}_{d["folio"]}.xml"'})


@router.post("/generar", response_model=GenerarDTEResponse,
             summary="Generar un DTE (XML estructurado y firmado)")
async def generar_dte(
    dte_json: Annotated[str, Form(description="Datos del DTE en JSON (modelo DTEInput)")],
    certificado_p12: Annotated[UploadFile, File(description="Archivo .p12 del certificado")],
    password_certificado: Annotated[str, Form(description="Contraseña del certificado")],
    caf_xml: Annotated[Optional[UploadFile], File(description="CAF XML (opcional, para el TED)")] = None,
) -> GenerarDTEResponse:
    """Genera y firma un DTE completo (con TED si se provee el CAF)."""
    dte_input = _parse_dte_input(dte_json)
    cert = _cargar_cert(await leer_upload(certificado_p12), password_certificado)

    # CAF opcional → TED
    ted_xml: Optional[str] = None
    if caf_xml and caf_xml.filename:
        try:
            caf_manejador = ManejadorCAF(await leer_upload(caf_xml))
        except Exception as e:
            raise CAFError(f"No se pudo procesar el CAF: {e}")
        if caf_manejador.datos.tipo_dte != dte_input.tipo_dte.value:
            raise CAFError(
                f"El CAF es para el tipo {caf_manejador.datos.tipo_dte} pero el DTE es "
                f"tipo {dte_input.tipo_dte.value}.")
        if not caf_manejador.es_folio_valido(dte_input.folio):
            raise FolioError(
                f"El folio {dte_input.folio} no está en el rango del CAF "
                f"[{caf_manejador.datos.folio_desde}-{caf_manejador.datos.folio_hasta}].")
        totales = calcular_totales(dte_input.items, dte_input.tipo_dte)
        ted_xml = caf_manejador.generar_ted(
            folio=dte_input.folio, rut_emisor=dte_input.emisor.rut,
            rut_receptor=dte_input.receptor.rut, tipo_dte=dte_input.tipo_dte.value,
            fecha_emision_dte=dte_input.fecha_emision, monto_total=totales.monto_total,
            razon_social_receptor=dte_input.receptor.razon_social,
            primer_item=dte_input.items[0].nombre if dte_input.items else "Sin Items")

    # Generar + firmar. Se firma con `core/sobre.py` (standalone, uri="#T{tipo}F{folio}"):
    # `firmar_documento_xml` es SOLO para la semilla del getToken — usarla en un DTE produce
    # una firma que el SII rechaza con DTE-3-505. Los bytes devueltos son los que se firmaron:
    # el llamador debe insertarlos VERBATIM en el sobre, sin re-serializar.
    generador = GeneradorDTE()
    dte_elem = generador.generar_documento_xml(dte_input, ted_xml=ted_xml)
    xml_firmado = firmar_documento_standalone(dte_elem, cert, dte_input.tipo_dte.value,
                                              dte_input.folio)
    xml_b64 = base64.b64encode(xml_firmado.encode("ISO-8859-1")).decode("ascii")

    totales = calcular_totales(dte_input.items, dte_input.tipo_dte)
    return GenerarDTEResponse(
        folio=dte_input.folio, tipo_dte=dte_input.tipo_dte.value,
        monto_total=totales.monto_total, xml_b64=xml_b64,
        mensaje=f"DTE Tipo {dte_input.tipo_dte.value} Folio {dte_input.folio} generado y firmado.")


@router.post("/generar-simple", response_model=GenerarDTEResponse,
             summary="Generar DTE desde JSON (sin archivos, para pruebas)")
async def generar_dte_simple(body: DTEInput) -> GenerarDTEResponse:
    """Genera un DTE sin firma real (para desarrollo y pruebas estructurales)."""
    generador = GeneradorDTE()
    dte_elem = generador.generar_documento_xml(body, ted_xml=None)
    xml_b64 = base64.b64encode(generador.to_xml_bytes(dte_elem)).decode("ascii")
    totales = calcular_totales(body.items, body.tipo_dte)
    return GenerarDTEResponse(
        folio=body.folio, tipo_dte=body.tipo_dte.value, monto_total=totales.monto_total,
        xml_b64=xml_b64,
        mensaje=f"DTE Tipo {body.tipo_dte.value} Folio {body.folio} generado (sin firma real).")


@router.post("/enviar", response_model=EnviarDTEResponse, summary="Enviar DTE firmado al SII")
async def enviar_dte(body: EnviarDTERequest) -> EnviarDTEResponse:
    """Envía un EnvioDTE firmado al SII y retorna el TrackID."""
    from core.schema_validator import validar_xml_dte_strict

    cert = _cargar_cert(_decode_b64(body.certificado_p12_b64, "El certificado"),
                        body.password_certificado)
    xml_bytes = _decode_b64(body.xml_envio_b64, "El XML de envío")

    # Validar contra el XSD del SII antes de enviar
    try:
        validar_xml_dte_strict(xml_bytes)
    except ValueError as e:
        raise ValidacionError(f"El XML no cumple el esquema XSD del SII: {e}")

    try:
        cliente = ClienteSII(cert, body.ambiente)
        track_id, mensaje = cliente.enviar_dte(
            xml_bytes, rut_empresa=body.rut_empresa, dv_empresa=body.dv_empresa,
            tipo_dte=body.tipo_dte)
    except ValueError as e:
        raise SIIRechazoError(f"El SII rechazó el documento: {e}")
    except SIIError:
        raise
    except Exception as e:
        raise SIIError(f"Error de comunicación con el SII: {e}")

    return EnviarDTEResponse(track_id=track_id, mensaje=mensaje, ambiente=body.ambiente.value)


@router.post("/validar-xml", response_model=ValidarXMLResponse,
             summary="Validar XML del DTE contra el esquema XSD oficial del SII")
async def validar_xml(body: ValidarXMLRequest) -> ValidarXMLResponse:
    """Valida un XML (DTE o EnvioDTE) contra los esquemas XSD del SII."""
    from core.schema_validator import validar_xml_dte

    xml_bytes = _decode_b64(body.xml_b64, "El XML")
    resultado = validar_xml_dte(xml_bytes)  # fallo inesperado → 500 global
    mensaje = ("XML válido según esquema XSD del SII." if resultado.valido
               else f"XML inválido: {len(resultado.errores)} error(es).")
    return ValidarXMLResponse(valido=resultado.valido, tipo_xml=resultado.tipo_xml,
                              errores=resultado.errores, mensaje=mensaje)


@router.post("/pdf", summary="Generar PDF de la representación gráfica del DTE",
             response_class=Response)
async def generar_pdf(
    dte_json: Annotated[str, Form(description="Datos del DTE en JSON")],
    ted_xml: Annotated[Optional[str], Form(description="XML del TED (opcional)")] = None,
) -> Response:
    """Genera el PDF del DTE con su timbre PDF417."""
    dte_input = _parse_dte_input(dte_json)
    pdf_bytes = generar_pdf_dte(dte_input, ted_xml=ted_xml)
    filename = f"DTE-{dte_input.tipo_dte.value}-{dte_input.folio}.pdf"
    return Response(content=pdf_bytes, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.post("/pdf-simple", summary="Generar PDF desde JSON directo", response_class=Response)
async def generar_pdf_simple(body: DTEInput) -> Response:
    """Genera el PDF del DTE recibiendo el DTEInput como JSON en el body."""
    pdf_bytes = generar_pdf_dte(body, ted_xml=None)
    filename = f"DTE-{body.tipo_dte.value}-{body.folio}.pdf"
    return Response(content=pdf_bytes, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


# ---- Emisión orquestada ----

class EmitirDTERequest(BaseModel):
    dte: DTEInput
    certificado_p12_b64: Optional[str] = None
    password_certificado: Optional[str] = None


class EmitirDTEResponse(BaseModel):
    dte_id: int
    folio: int
    tipo_dte: int
    monto_total: int
    xml_dte_path: str
    pdf_path: str
    xml_envio_path: str
    xml_envio_b64: str
    ambiente: str
    mensaje: str


class PrevisualizarRequest(BaseModel):
    dte: DTEInput
    cert_id: int


@router.post("/previsualizar", summary="Previsualizar un DTE (firmado+timbrado+PDF) sin enviarlo")
async def previsualizar(
    body: PrevisualizarRequest,
    usuario: dict = Depends(requerir_autenticacion),
) -> dict:
    """Genera un DTE FIRMADO + timbrado (TED) + validado XSD + PDF, **sin enviarlo al SII
    ni consumir folios**. Resuelve el certificado del keystore (`cert_id`) y el CAF activo
    de la BD para el emisor+tipo. Devuelve `{folio, totales, valido_xsd, xml_b64, pdf_b64}`.
    """
    cert = keystore.cargar_certificado(body.cert_id, usuario["id"])
    caf_db = obtener_caf_activo(body.dte.emisor.rut, body.dte.tipo_dte.value)
    if not caf_db:
        raise FolioError(
            f"No hay CAF activo para {body.dte.emisor.rut} tipo {body.dte.tipo_dte.value}. "
            "Carga un CAF primero.")
    caf = ManejadorCAF(caf_db["caf_xml"].encode("utf-8"))
    return _previsualizar_dte(body.dte, cert, caf)


@router.post("/emitir", response_model=EmitirDTEResponse, summary="Emitir DTE de forma orquestada")
async def emitir_dte_orquestado(
    body: EmitirDTERequest,
    usuario: dict = Depends(requerir_autenticacion),
) -> EmitirDTEResponse:
    """Emite un DTE o boleta orquestado: folio → TED → firma → PDF → sobre → BD.

    Rutea según el tipo: 39/41 salen como EnvioBOLETA (PDF 80mm), el resto como EnvioDTE.
    Los errores de dominio (sin folios, CAF, certificado) los levanta el orquestador y
    los normaliza el handler global con el status correcto.
    """
    cert = None
    if body.certificado_p12_b64 and body.password_certificado:
        cert = _cargar_cert(_decode_b64(body.certificado_p12_b64, "El certificado"),
                            body.password_certificado)
    resultado = emitir_documento(body.dte, certificado=cert)
    return EmitirDTEResponse(**resultado)
