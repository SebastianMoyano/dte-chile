"""
core/resolucion.py — Resolución (FchResol / NroResol) de la carátula, POR EMPRESA.

La carátula del sobre (EnvioDTE / EnvioBOLETA / ConsumoFolios) debe llevar la resolución del
**EMISOR**: el SII la valida contra su registro por RUT y rechaza el sobre entero con
`CRT-3-19 "Fecha/Numero Resolucion Invalido"` si no coincide. Cada empresa tiene la suya —
en certificación es la fecha del inicio de SU proceso (NroResol=0); en producción, su
resolución real.

Antes esto salía de un **default global** (`settings.resolucion`), que solo servía para la
empresa cuya fecha estaba en config; para cualquier otra daba CRT-3-19. Le pasó a una segunda
empresa del mismo operador (fecha real distinta), rechazada porque la global era la de la
primera empresa. Ver [[resolucion-por-ambiente]].

`resolucion_emisor(rut)` toma la fecha/número del **registro público del SII** (`info_empresa`,
la misma consulta del alta de negocios), lo cachea (memoria + BD) y, si la consulta falla o el
RUT no aparece, **cae al default de config** — nunca rompe la emisión.
"""
from __future__ import annotations

import logging
from typing import Optional, Tuple

from core import database
from core.config import settings

logger = logging.getLogger(__name__)

_CACHE_SCHEMA = """
CREATE TABLE IF NOT EXISTS resolucion_cache (
    rut       TEXT NOT NULL,
    ambiente  TEXT NOT NULL,
    fecha_iso TEXT NOT NULL,
    numero    INTEGER NOT NULL,
    ts        TEXT NOT NULL,
    PRIMARY KEY (rut, ambiente)
);
"""

# Espejo en proceso del caché de BD (evita pegarle a la BD/portal en cada emisión).
_MEM: dict = {}


def _iso(fecha: str) -> Optional[str]:
    """Normaliza la fecha del portal (`DD-MM-YYYY`) a ISO (`YYYY-MM-DD`).

    Acepta una fecha ya-ISO. Devuelve None si no la reconoce (para caer al fallback).
    """
    fecha = (fecha or "").strip()
    if len(fecha) == 10 and fecha[4] == "-" and fecha[7] == "-":
        return fecha  # ya viene ISO
    if len(fecha) == 10 and fecha[2] == "-" and fecha[5] == "-":
        d, m, y = fecha.split("-")
        return f"{y}-{m}-{d}"
    return None


def _cache_get(rut: str, ambiente: str) -> Optional[Tuple[str, int]]:
    key = (rut, ambiente)
    if key in _MEM:
        return _MEM[key]
    try:
        with database.get_db() as conn:
            conn.execute(_CACHE_SCHEMA)
            row = conn.execute(
                "SELECT fecha_iso, numero FROM resolucion_cache WHERE rut=? AND ambiente=?",
                (rut, ambiente)).fetchone()
        if row:
            val = (row["fecha_iso"], int(row["numero"]))
            _MEM[key] = val
            return val
    except Exception:  # noqa: BLE001 — el caché nunca debe tumbar la emisión
        pass
    return None


def _cache_put(rut: str, ambiente: str, fecha_iso: str, numero: int) -> None:
    from datetime import datetime, timezone
    _MEM[(rut, ambiente)] = (fecha_iso, numero)
    try:
        with database.get_db() as conn:
            conn.execute(_CACHE_SCHEMA)
            conn.execute(
                "INSERT INTO resolucion_cache (rut, ambiente, fecha_iso, numero, ts) "
                "VALUES (?,?,?,?,?) ON CONFLICT(rut, ambiente) DO UPDATE SET "
                "fecha_iso=excluded.fecha_iso, numero=excluded.numero, ts=excluded.ts",
                (rut, ambiente, fecha_iso, numero,
                 datetime.now(timezone.utc).isoformat()))
    except Exception:  # noqa: BLE001
        pass


def resolucion_emisor(rut: str, ambiente: Optional[str] = None,
                      refrescar: bool = False) -> Tuple[str, int]:
    """`(FchResol_iso, NroResol)` de la carátula para el EMISOR `rut`.

    Preferencia: registro público del SII (cacheado) → default de config. **Nunca lanza**: si
    la consulta falla o el RUT no está, devuelve `settings.resolucion` (el default del
    ambiente activo) para no bloquear la emisión.

    Args:
        rut: RUT del emisor con DV (ej. "78111111-2").
        ambiente: "certificacion"/"produccion". Por defecto, el ambiente activo.
        refrescar: fuerza re-consulta al SII (ignora el caché). Úsalo si la resolución de
            una empresa cambió (p. ej. pasó a producción).
    """
    ambiente = ambiente or settings.sii_ambiente
    rut = (rut or "").strip()
    if rut and not refrescar:
        hit = _cache_get(rut, ambiente)
        if hit:
            return hit
    if rut:
        try:
            from core.negocios import info_empresa
            info = info_empresa(rut, ambiente)
            if info and info.get("resolucion"):
                fecha_iso = _iso(info["resolucion"].get("fecha", ""))
                if fecha_iso is not None:
                    try:
                        numero = int(str(info["resolucion"].get("numero", "")).strip() or 0)
                    except ValueError:
                        numero = 0
                    _cache_put(rut, ambiente, fecha_iso, numero)
                    return (fecha_iso, numero)
        except Exception as e:  # noqa: BLE001 — fallback seguro, la emisión sigue
            logger.warning("resolucion_emisor(%s): consulta SII falló (%s); uso el default", rut, e)
    return settings.resolucion
