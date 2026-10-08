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


@router.get("/historico", summary="Tabla mensual de un año: UF y dólar al día 1 (vigentes) y UTM del mes")
async def historico(anio: int = Query(..., ge=2000, le=2100)) -> dict:
    meses = []
    for m in range(1, 13):
        f = f"{anio:04d}-{m:02d}-01"
        fila = {"mes": f[:7]}
        for k in INDICADORES:
            v = _vigente(k, f)
            # al día 1 el valor vigente puede ser de fin del mes anterior (incluso del año anterior)
            fila[k] = v["valor"] if v and v["rezago_dias"] <= 7 else None
        # cierre de mes para UF y dólar: último valor del mes
        for k in ("uf", "dolar"):
            fin = database.obtenerUno("SELECT valor, fecha FROM valores WHERE indicador=? AND fecha LIKE ? ORDER BY fecha DESC LIMIT 1", (k, f[:7] + "%"))
            fila[k + "_fin"] = fin["valor"] if fin else None
        meses.append(fila)
    anios = database.obtener_todos("SELECT DISTINCT substr(fecha,1,4) AS a FROM valores ORDER BY a")
    return {"anio": anio, "meses": meses, "anios_disponibles": [r["a"] for r in anios]}


@router.get("/{indicador}/serie", summary="Serie diaria/mensual de un indicador entre dos fechas")
async def serie(indicador: str, desde: str = Query(...), hasta: str = Query(...)) -> dict:
    if indicador not in INDICADORES:
        raise ValidacionError(f"Indicador desconocido: {indicador}")
    filas = database.obtener_todos("SELECT fecha, valor FROM valores WHERE indicador=? AND fecha BETWEEN ? AND ? ORDER BY fecha", (indicador, desde, hasta))
    return {"indicador": indicador, "desde": desde, "hasta": hasta, "serie": [{"fecha": r["fecha"], "valor": r["valor"]} for r in filas]}


@router.get("/{indicador}", summary="Un indicador vigente a una fecha, con la fecha real del valor")
async def valor_vigente(indicador: str, fecha: Optional[str] = Query(None)) -> dict:
    if indicador not in INDICADORES:
        raise ValidacionError(f"Indicador desconocido: {indicador} (uf | utm | dolar)")
    f = fecha or date.today().isoformat()
    v = _vigente(indicador, f)
    if not v:
        raise RecursoNoEncontrado(f"Sin {indicador} cacheado en o antes de {f}")
    return v
