"""
api/routes/onboarding.py — Asistente de onboarding.

El paso de "investigación automática": dado un certificado (del keystore) y un RUT,
lee el estado de la empresa en el SII (SOLO LECTURA) y devuelve el diagnóstico + el plan
de pasos para llegar a emitir con software propio. No escribe nada en el SII.
"""
from fastapi import APIRouter, Depends, Query

from core import keystore
from core.auth import requerir_autenticacion
from core.errors import SIIError
from core.onboarding import diagnosticar, diagnosticar_cartera
from core.sii_portal import BASE_CERTIFICACION, PortalSII

router = APIRouter(prefix="/api/v1/onboarding", tags=["Onboarding"])


@router.get("/diagnostico")
async def diagnostico(
    cert_id: int = Query(..., description="ID del certificado en el keystore"),
    rut: str = Query(..., description="RUT de la empresa, ej: 76111111-6"),
    nombre_sistema: str = Query("tu software propio",
                                description="Cómo llamar al software propio en el plan"),
    usuario: dict = Depends(requerir_autenticacion),
) -> dict:
    """Investigación automática (solo lectura): estado de la empresa en el SII + plan.

    Devuelve `{estado, etiqueta, resumen, listo_para_emitir, chequeos[], acciones[]}`.
    Cada acción trae `modo`: `auto` (el sistema lo hace), `consentimiento` (escribe en el
    SII → pide autorización), o `humano` (gestión con el SII).
    """
    try:
        with keystore.pem_transitorio(cert_id, usuario["id"]) as (cert_pem, key_pem):
            portal = PortalSII(cert_pem, key_pem, base=BASE_CERTIFICACION)
            portal.autenticar()
            return diagnosticar(portal, rut, nombre_sistema).to_dict()
    except SIIError:
        raise
    except Exception as e:
        raise SIIError(f"No se pudo diagnosticar la empresa en el SII: {e}")


@router.get("/cartera")
async def cartera(
    cert_id: int = Query(..., description="ID del certificado en el keystore"),
    nombre_sistema: str = Query("tu software propio"),
    usuario: dict = Depends(requerir_autenticacion),
) -> list:
    """Vista de cartera: diagnostica TODAS las empresas asociadas al certificado.

    Devuelve un resumen por empresa (estado, si está lista, acciones pendientes). Para el
    detalle de una empresa usa `/diagnostico`. Solo lectura.
    """
    try:
        with keystore.pem_transitorio(cert_id, usuario["id"]) as (cert_pem, key_pem):
            portal = PortalSII(cert_pem, key_pem, base=BASE_CERTIFICACION)
            portal.autenticar()
            return [{"rut": d.rut, "razon_social": d.razon_social, "estado": d.estado,
                     "etiqueta": d.etiqueta, "listo_para_emitir": d.listo_para_emitir,
                     "acciones_pendientes": sum(1 for a in d.acciones if not a.hecho)}
                    for d in diagnosticar_cartera(portal, nombre_sistema=nombre_sistema)]
    except SIIError:
        raise
    except Exception as e:
        raise SIIError(f"No se pudo diagnosticar la cartera en el SII: {e}")
