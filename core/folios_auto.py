"""
core/folios_auto.py — Gestión AUTOMÁTICA de folios (estilo TUU/Haulmer).

Cuando los folios disponibles de un `(rut, tipo)` caen bajo el umbral, el motor **pide un CAF
nuevo al SII por sí solo** (autenticando con el certificado del mandatario del negocio), lo
verifica y lo carga en la BD → la emisión **no se detiene**. Corre en un bucle asyncio dentro
del proceso (sin cron), independiente del RVD.

Notifica cada evento (repuesto / bloqueado / error) por un **webhook genérico**
(`settings.notif_webhook_url`) + log. El motor **no asume ningún canal**: el webhook lo cablea el
usuario a lo que quiera (su propio endpoint, un automatizador, un chat…). **Nunca correo**
(regla del proyecto: [[no-buscar-correo]]).

Salvaguardas anti-acaparamiento del SII (`CAF-3-517`): solo pide cuando está bajo, respeta un
**cooldown** por `(rut, tipo)`, y si el SII responde `bloqueado` lo notifica como "requiere
humano" en vez de reintentar en loop.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import List, Optional, Tuple

import httpx

from core import database, keystore
from core.caf import ManejadorCAF
from core.config import settings
from core.models import registrar_caf
from core.monitoreo import salud_caf
from core.sii_portal import BASE_CERTIFICACION, BASE_PRODUCCION, PortalSII, _UA

logger = logging.getLogger("dte.folios")

_LOGOUT_URL = "https://herculesr.sii.cl/cgi_AUT2000/autTermino.cgi"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS folios_gestion (
    clave         TEXT PRIMARY KEY,
    ultima_accion TEXT,
    ultimo_ts     TEXT,
    detalle       TEXT
);
"""


def _ahora() -> str:
    return datetime.now(timezone.utc).isoformat()


def _tipos_gestionados() -> List[int]:
    return [int(t) for t in str(settings.folios_auto_tipos).split(",") if t.strip().isdigit()]


def _base() -> str:
    return BASE_PRODUCCION if settings.sii_ambiente == "produccion" else BASE_CERTIFICACION


def folios_disponibles(rut: str, tipo: int) -> int:
    """Suma de folios restantes en los CAF activos y NO vencidos de ese `(rut, tipo)`."""
    return sum(c["restantes"] for c in salud_caf(rut)
               if c["tipo_dte"] == tipo and c["estado"] != "vencido")


def _pares_gestionables() -> List[Tuple[str, int]]:
    """`(rut, tipo)` con CAF activo, limitados a los tipos configurados (solo se repone lo que
    ya se usa)."""
    tipos = set(_tipos_gestionados())
    with database.get_db() as conn:
        conn.execute(_SCHEMA)
        filas = conn.execute(
            "SELECT DISTINCT rut_emisor, tipo_dte FROM cafs WHERE activo=1").fetchall()
    return [(f[0], f[1]) for f in filas if f[1] in tipos]


def _cert_de(rut: str, cuenta_id: int) -> Optional[int]:
    """`cert_id` del negocio (mandatario) para ese RUT. Si el negocio no lo tiene, cae al
    `folios_auto_cert_id` de config (respaldo para setups de una sola empresa). None si no hay."""
    try:
        with database.get_db() as conn:
            row = conn.execute(
                "SELECT cert_id FROM negocios WHERE rut=? AND cuenta_id=? AND cert_id IS NOT NULL "
                "ORDER BY id LIMIT 1", (rut, cuenta_id)).fetchone()
        if row and row["cert_id"]:
            return row["cert_id"]
    except Exception:  # noqa: BLE001
        pass
    return settings.folios_auto_cert_id or None


def _descargar_caf(rut: str, tipo: int, cantidad: int, cert_id: int, cuenta_id: int) -> dict:
    """Pide un CAF al SII (portal, con el cert), lo verifica y lo registra. Cierra la sesión
    del SII siempre. Devuelve {ok, rango, bloqueado, mensaje}. (Monkeypatcheable en tests.)"""
    cookies = None
    with keystore.pem_transitorio(cert_id, cuenta_id) as (cp, kp):
        portal = PortalSII(cert_pem=cp, key_pem=kp, base=_base(), max_folios_por_tipo=cantidad)
        try:
            cookies = portal.autenticar(referencia=f"{_base()}/of_solicita_folios")
            if not cookies:
                return {"ok": False, "bloqueado": False,
                        "mensaje": "Sesión SII vacía (tope de sesiones); reintenta luego."}
            caf, info = portal.solicitar_folios(rut, tipo_dte=tipo, cantidad=cantidad)
            if caf is None:
                return {"ok": False, "bloqueado": bool(info.get("bloqueado")),
                        "mensaje": info.get("mensaje") or str(info)}
            m = ManejadorCAF.desde_bytes(caf)
            if m.datos.tipo_dte != tipo or m.datos.rut_emisor.replace(".", "") not in (
                    rut, rut.replace("-", "")):
                return {"ok": False, "bloqueado": False,
                        "mensaje": f"CAF recibido no corresponde ({m.datos.rut_emisor}/{m.datos.tipo_dte})."}
            registrar_caf(tipo_dte=tipo, rut_emisor=rut, folio_desde=m.datos.folio_desde,
                          folio_hasta=m.datos.folio_hasta,
                          fecha_autorizacion=getattr(m.datos, "fecha_autorizacion", _ahora()[:10]),
                          caf_xml=caf.decode("ISO-8859-1"))
            return {"ok": True, "bloqueado": False,
                    "rango": [m.datos.folio_desde, m.datos.folio_hasta],
                    "mensaje": f"CAF {m.datos.folio_desde}-{m.datos.folio_hasta} cargado."}
        finally:
            if cookies:
                try:
                    with httpx.Client(verify=True, timeout=15, follow_redirects=True,
                                      cookies=cookies, headers=_UA) as c:
                        c.get(_LOGOUT_URL)
                except Exception:  # noqa: BLE001
                    pass


def _notificar(evento: dict) -> None:
    """Log + POST al webhook genérico (si está configurado). Nunca lanza."""
    nivel = logging.INFO if evento.get("evento") == "folios_repuestos" else logging.WARNING
    logger.log(nivel, "%s — %s tipo %s: %s", evento.get("evento"), evento.get("rut"),
               evento.get("tipo_dte"), evento.get("detalle") or evento.get("mensaje", ""))
    url = (settings.notif_webhook_url or "").strip()
    if not url:
        return
    try:
        httpx.post(url, json=evento, timeout=10)
    except Exception as e:  # noqa: BLE001
        logger.warning("No se pudo notificar al webhook (%s): %s", url, e)


def _en_cooldown(clave: str) -> bool:
    with database.get_db() as conn:
        conn.execute(_SCHEMA)
        row = conn.execute("SELECT ultimo_ts FROM folios_gestion WHERE clave=?", (clave,)).fetchone()
    if not row or not row["ultimo_ts"]:
        return False
    try:
        prev = datetime.fromisoformat(row["ultimo_ts"])
        return (datetime.now(timezone.utc) - prev).total_seconds() < settings.folios_auto_cooldown_seg
    except Exception:  # noqa: BLE001
        return False


def _registrar_gestion(clave: str, accion: str, detalle: str) -> None:
    with database.get_db() as conn:
        conn.execute(_SCHEMA)
        conn.execute(
            "INSERT INTO folios_gestion (clave, ultima_accion, ultimo_ts, detalle) VALUES (?,?,?,?) "
            "ON CONFLICT(clave) DO UPDATE SET ultima_accion=excluded.ultima_accion, "
            "ultimo_ts=excluded.ultimo_ts, detalle=excluded.detalle",
            (clave, accion, _ahora(), detalle))


def gestionar_folios(cuenta_id: int = 1) -> List[dict]:
    """Revisa cada `(rut, tipo)` gestionable y repone los que estén bajo el umbral. Devuelve
    los eventos ocurridos (repuesto/bloqueado/error/omitido). El chequeo es LOCAL; solo pega al
    SII cuando efectivamente hay que reponer."""
    eventos: List[dict] = []
    umbral, cantidad = settings.folios_auto_umbral, settings.folios_auto_cantidad
    for rut, tipo in _pares_gestionables():
        disp = folios_disponibles(rut, tipo)
        if disp > umbral:
            continue
        clave = f"{rut}|{tipo}"
        if _en_cooldown(clave):
            logger.info("folios %s tipo %s bajo (%s) pero en cooldown; no repongo aún", rut, tipo, disp)
            continue
        cert_id = _cert_de(rut, cuenta_id)
        if cert_id is None:
            ev = {"evento": "folios_error", "rut": rut, "tipo_dte": tipo, "disponibles": disp,
                  "detalle": "No hay certificado (negocio) asociado para pedir folios.",
                  "requiere_humano": True, "ts": _ahora()}
            _notificar(ev); _registrar_gestion(clave, "error", ev["detalle"]); eventos.append(ev)
            continue
        try:
            r = _descargar_caf(rut, tipo, cantidad, cert_id, cuenta_id)
        except Exception as e:  # noqa: BLE001
            r = {"ok": False, "bloqueado": False, "mensaje": f"{type(e).__name__}: {e}"}
        if r.get("ok"):
            ev = {"evento": "folios_repuestos", "rut": rut, "tipo_dte": tipo,
                  "disponibles_antes": disp, "rango": r.get("rango"), "cantidad": cantidad,
                  "detalle": r.get("mensaje"), "ts": _ahora()}
            _registrar_gestion(clave, "repuesto", ev["detalle"])
        else:
            ev = {"evento": "folios_bloqueado" if r.get("bloqueado") else "folios_error",
                  "rut": rut, "tipo_dte": tipo, "disponibles": disp,
                  "detalle": r.get("mensaje"), "requiere_humano": True, "ts": _ahora()}
            _registrar_gestion(clave, ev["evento"], ev["detalle"])
        _notificar(ev); eventos.append(ev)
    return eventos


class ProgramadorFolios:
    """Bucle asyncio in-process que gestiona (repone) folios cada `intervalo_seg`."""

    def __init__(self, intervalo_seg: int = 1800):
        self.intervalo_seg = intervalo_seg
        self._task: Optional[asyncio.Task] = None

    async def _bucle(self) -> None:
        while True:
            try:
                await asyncio.to_thread(gestionar_folios)
            except Exception as e:  # noqa: BLE001
                logger.warning("Gestión de folios falló: %s", e)
            await asyncio.sleep(self.intervalo_seg)

    def iniciar(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._bucle())
            logger.info("Gestión automática de folios activa (cada %ss, umbral %s, lote %s)",
                        self.intervalo_seg, settings.folios_auto_umbral, settings.folios_auto_cantidad)

    async def detener(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass


programador_folios = ProgramadorFolios()
