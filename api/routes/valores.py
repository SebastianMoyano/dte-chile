"""
api/routes/valores.py — UF, UTM y dólar del día (solo lectura).

La tabla `valores` la llena el núcleo Go desde las páginas oficiales del SII
(`nucleo-valores actualizar|demonio`, o la app de escritorio al arrancar). Aquí solo se lee.
`vigente` = último valor conocido en o antes de la fecha (fin de semana hereda el viernes; la UTM
vale todo el mes). El dólar de la página oficial llega con rezago: `fecha_valor` dice de cuándo es.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query

from core import database
from core.auth import requerir_autenticacion
from core.errors import RecursoNoEncontrado, ValidacionError

router = APIRouter(prefix="/api/v1/valores", tags=["Valores (UF, UTM, dólar)"],
                   dependencies=[Depends(requerir_autenticacion)])
INDICADORES = ("uf", "utm", "dolar")


def _vigente(indicador: str, fecha: str) -> Optional[dict]:
    fila = database.obtenerUno(
        "SELECT indicador, fecha, valor, actualizado FROM valores WHERE indicador=? AND fecha<=? "
        "ORDER BY fecha DESC LIMIT 1", (indicador, fecha))
    if not fila:
        return None
    rezago = (date.fromisoformat(fecha) - date.fromisoformat(fila["fecha"])).days
    if indicador == "utm" and fecha[:7] == fila["fecha"][:7]:
        rezago = 0   # la UTM es mensual: el valor del día 1 vale todo el mes, no es rezago
    return {"indicador": indicador, "fecha": fecha, "valor": fila["valor"], "fecha_valor": fila["fecha"],
            "actualizado": fila["actualizado"], "rezago_dias": rezago}


@router.get("", summary="UF, UTM y dólar vigentes a una fecha (hoy por defecto)")
async def valores_vigentes(fecha: Optional[str] = Query(None, description="YYYY-MM-DD")) -> dict:
    f = fecha or date.today().isoformat()
    try:
        date.fromisoformat(f)
    except ValueError:
        raise ValidacionError(f"Fecha inválida: {f}")
    out = {k: _vigente(k, f) for k in INDICADORES}
    if not any(out.values()):
        raise RecursoNoEncontrado("No hay indicadores cacheados: corre `nucleo-valores actualizar` (o abre la app)")
    return {"fecha": f, **out}


@router.get("/{indicador}", summary="Un indicador vigente a una fecha, con la fecha real del valor")
async def valor_vigente(indicador: str, fecha: Optional[str] = Query(None)) -> dict:
    if indicador not in INDICADORES:
        raise ValidacionError(f"Indicador desconocido: {indicador} (uf | utm | dolar)")
    f = fecha or date.today().isoformat()
    v = _vigente(indicador, f)
    if not v:
        raise RecursoNoEncontrado(f"Sin {indicador} cacheado en o antes de {f}")
    return v
