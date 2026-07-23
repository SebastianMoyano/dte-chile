"""
core/monitoreo.py — Monitoreo operativo LOCAL (no toca el SII).

Salud de los CAF (folios) cargados de un emisor: detecta CAF **vencidos** (regla del SII
`CAF-3-517`: no usar un CAF más de 6 meses después de su autorización) y folios que se
están **agotando**. Todo se lee de la BD — cero llamadas al SII, sin bloqueos ni
rate-limit. Ataca los dos dolores que ya vivimos: CAF vencido y quedarse sin folios a
mitad del set de pruebas.
"""
from __future__ import annotations

from collections import Counter
from datetime import date
from typing import List, Optional

from core import database

REGLA_MESES_CAF = 6  # CAF-3-517: (Firma_DTE − FA_CAF) no debe superar 6 meses.


def _meses(desde: date, hoy: date) -> int:
    return (hoy.year - desde.year) * 12 + (hoy.month - desde.month)


def salud_caf(rut_emisor: str, hoy: Optional[date] = None) -> List[dict]:
    """Salud de cada CAF activo del emisor. 100% local (lee la BD).

    Cada item trae un ``estado``: ok | por_vencer | vencido | bajo | agotado, y un
    ``detalle`` legible con la acción sugerida.

    Nota: ``folio_siguiente``/``restantes`` reflejan el estado LOCAL de la BD; si se
    emitieron folios fuera de este programa (p.ej. por el portal del SII), el consumo
    real puede ser mayor.
    """
    hoy = hoy or date.today()
    filas = database.obtener_todos(
        "SELECT tipo_dte, folio_desde, folio_hasta, folio_siguiente, fecha_autorizacion "
        "FROM cafs WHERE rut_emisor=? AND activo=1 ORDER BY tipo_dte, folio_desde",
        (rut_emisor,))
    reporte: List[dict] = []
    for f in filas:
        d = dict(f)
        try:
            fa = date.fromisoformat(str(d["fecha_autorizacion"])[:10])
        except Exception:
            fa = hoy
        meses = _meses(fa, hoy)
        sig = d["folio_siguiente"] or d["folio_desde"]
        restantes = max(0, d["folio_hasta"] - sig + 1)
        total = d["folio_hasta"] - d["folio_desde"] + 1
        umbral_bajo = max(3, total // 10)

        # Prioridad: vencido > agotado > bajo > por_vencer > ok.
        if meses >= REGLA_MESES_CAF:
            estado = "vencido"
            detalle = (f"CAF de hace {meses} meses (máx {REGLA_MESES_CAF} por el SII). "
                       "No se puede usar; timbra folios nuevos.")
        elif restantes == 0:
            estado, detalle = "agotado", "Sin folios disponibles en este CAF."
        elif restantes <= umbral_bajo:
            estado = "bajo"
            detalle = f"Quedan {restantes} de {total} folios — pide más pronto."
        elif meses >= REGLA_MESES_CAF - 1:
            estado = "por_vencer"
            detalle = f"Vence este mes (tiene {meses} meses). Usa estos folios ya."
        else:
            estado, detalle = "ok", f"{restantes} de {total} folios disponibles."

        reporte.append({
            "tipo_dte": d["tipo_dte"],
            "rango": [d["folio_desde"], d["folio_hasta"]],
            "folio_siguiente": sig,
            "restantes": restantes,
            "total": total,
            "fecha_autorizacion": str(fa),
            "meses": meses,
            "estado": estado,
            "detalle": detalle,
        })
    return reporte


def resumen_salud(rut_emisor: str, hoy: Optional[date] = None) -> dict:
    """Resumen accionable: conteo por estado + veredicto global (ok/atencion/critico)."""
    cafs = salud_caf(rut_emisor, hoy)
    por_estado = Counter(c["estado"] for c in cafs)
    critico = por_estado["vencido"] + por_estado["agotado"]
    atencion = por_estado["bajo"] + por_estado["por_vencer"]
    verdict = "critico" if critico else ("atencion" if atencion else "ok")
    return {
        "rut": rut_emisor,
        "total_cafs": len(cafs),
        "por_estado": dict(por_estado),
        "verdict": verdict,
        "cafs": cafs,
    }


def salud_cartera(ruts: Optional[List[str]] = None, hoy: Optional[date] = None) -> dict:
    """Salud de folios de TODA la operación. Si `ruts` es None, escanea todas las empresas
    con CAF cargado. Ordena por urgencia (crítico → atención → ok). 100% local."""
    if ruts is None:
        filas = database.obtener_todos(
            "SELECT DISTINCT rut_emisor FROM cafs WHERE activo=1 ORDER BY rut_emisor")
        ruts = [dict(f)["rut_emisor"] for f in filas]
    empresas = [resumen_salud(r, hoy) for r in ruts]
    orden = {"critico": 0, "atencion": 1, "ok": 2}
    empresas.sort(key=lambda e: orden.get(e["verdict"], 3))
    return {
        "total_empresas": len(empresas),
        "requieren_atencion": [e["rut"] for e in empresas if e["verdict"] != "ok"],
        "empresas": empresas,
    }
