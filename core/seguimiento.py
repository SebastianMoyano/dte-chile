"""
core/seguimiento.py — Seguimiento de envíos al SII por lote.

Dado un conjunto de TrackIDs (de envíos hechos con `enviar_dte`), consulta el estado de
todos y arma un resumen: cuántos están resueltos vs. pendientes, y cuántos DTE fueron
aceptados/rechazados. Cierra el ciclo emitir → enviar → **confirmar**.

Cada consulta pasa por `ClienteSII` (que ya reintenta 429/5xx). Un TrackID que falle no
tumba el lote. OJO: consulta 1 vez por TrackID — con muchos, el SII puede rate-limitear;
llama de a lotes razonables.
"""
from __future__ import annotations

import html
import re
from typing import List

from core.sii import ClienteSII

# Estados de envío que son FINALES (ya no cambian).
_ESTADOS_RECHAZO = {"RCH", "RSC", "RFR", "RCT", "RLV"}


def _campo(texto: str, tag: str):
    m = re.search(rf"<{tag}>([^<]*)</{tag}>", texto)
    if not m:
        return None
    v = m.group(1).strip()
    try:
        return int(v)
    except ValueError:
        return v


def estado_detallado(cliente: ClienteSII, track_id: int, rut: str, dv: str) -> dict:
    """Estado de UN envío con el desglose por DTE (aceptados/rechazados/reparos)."""
    r = cliente.consultar_estado_track(int(track_id), rut, dv)
    des = html.unescape(r.get("respuesta_raw", "") or "")
    tiene_body = "<TIPO_DOCTO>" in des  # el SII ya procesó los DTE del envío
    estado = r.get("estado")
    resuelto = bool(tiene_body) or (estado in _ESTADOS_RECHAZO)
    return {
        "track_id": int(track_id),
        "estado": estado,
        "glosa": r.get("glosa"),
        "informados": _campo(des, "INFORMADOS"),
        "aceptados": _campo(des, "ACEPTADOS"),
        "rechazados": _campo(des, "RECHAZADOS"),
        "reparos": _campo(des, "REPAROS"),
        "resuelto": resuelto,
    }


def estados_lote(cliente: ClienteSII, track_ids: List[int], rut: str, dv: str) -> dict:
    """Consulta un lote de TrackIDs y devuelve detalle por envío + un resumen accionable."""
    detalles: List[dict] = []
    for t in track_ids:
        try:
            detalles.append(estado_detallado(cliente, t, rut, dv))
        except Exception as e:  # noqa: BLE001 - un envío no debe tumbar el lote
            detalles.append({"track_id": t, "error": str(e), "resuelto": False})

    def suma(campo: str) -> int:
        return sum(d.get(campo) or 0 for d in detalles if isinstance(d.get(campo), int))

    resueltos = [d for d in detalles if d.get("resuelto")]
    return {
        "total": len(detalles),
        "resueltos": len(resueltos),
        "pendientes": len(detalles) - len(resueltos),
        "aceptados": suma("aceptados"),
        "rechazados": suma("rechazados"),
        "reparos": suma("reparos"),
        "todos_resueltos": len(resueltos) == len(detalles) and bool(detalles),
        "detalles": detalles,
    }
