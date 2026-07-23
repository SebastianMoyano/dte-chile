"""
api/routes/monitoreo.py — Monitoreo operativo (local, sin tocar el SII).
"""
from fastapi import APIRouter, Depends, Query

from core.auth import requerir_autenticacion
from core.monitoreo import resumen_salud, salud_cartera

router = APIRouter(prefix="/api/v1/monitoreo", tags=["Monitoreo"])


@router.get("/folios")
async def folios(
    rut: str = Query(..., description="RUT del emisor, ej: 76111111-6"),
    usuario: dict = Depends(requerir_autenticacion),
) -> dict:
    """Salud de folios/CAF de una empresa (LOCAL): detecta CAF vencidos (regla de 6 meses
    del SII) y folios agotándose. Veredicto ok/atencion/critico + detalle por CAF."""
    return resumen_salud(rut)


@router.get("/folios/cartera")
async def folios_cartera(usuario: dict = Depends(requerir_autenticacion)) -> dict:
    """Salud de folios de TODAS las empresas cargadas, ordenadas por urgencia (LOCAL)."""
    return salud_cartera()
