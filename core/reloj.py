"""
core/reloj.py — La única fuente de hora del pipeline de firma.

Todo lo que el SII ve con hora (TmstFirma del DTE, TmstFirma del TED, TmstFirmaEnv de la
carátula) sale de aquí. En operación normal es `datetime.now()`. Con `RELOJ_FIJO` definido
(ISO, p. ej. `2026-01-15T10:30:00`) devuelve siempre esa hora: así la salida completa del
motor (TED, DTE firmado, sobre) es **reproducible byte a byte**, que es lo que permite el
corpus dorado (`test_dorado.py`) y comparar cualquier port contra esta implementación.

Nunca definas RELOJ_FIJO en una instalación que emite de verdad.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from core.config import settings

_FORMATO_SII = "%Y-%m-%dT%H:%M:%S"
_fijo_proceso: Optional[datetime] = None


def fijar(iso: Optional[str]) -> None:
    """Fija (o libera con None) la hora SOLO en este proceso. Para pruebas; tiene prioridad
    sobre `settings.reloj_fijo`."""
    global _fijo_proceso
    _fijo_proceso = datetime.fromisoformat(iso) if iso else None


def ahora() -> datetime:
    if _fijo_proceso is not None:
        return _fijo_proceso
    if settings.reloj_fijo:
        return datetime.fromisoformat(settings.reloj_fijo)
    return datetime.now()


def marca() -> str:
    """La hora en el formato que usa el SII en todos los timestamps: `YYYY-MM-DDTHH:MM:SS`."""
    return ahora().strftime(_FORMATO_SII)
