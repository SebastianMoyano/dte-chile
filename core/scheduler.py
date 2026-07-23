"""
core/scheduler.py — Programador in-process del RVD diario (OPCIONAL).

**El RVD ya NO es obligatorio en producción** (Res. Ex. SII N° 53 de 2022, desde 2022-08-01):
verificado en vivo por el reparo del SII *"RVD no es obligatorio desde 2022-08-01"*. El Registro
de Ventas se arma directo con las boletas recibidas; correcciones vía Nota de Crédito (tipo 61).
Por eso este módulo es **opcional** — se activa con `RVD_SCHEDULER_ACTIVO` (default off en
producción). Se conserva porque el flujo de **certificación** aún incluye el RVD en el set (y por
si el SII vuelve a exigirlo). ⚠️ Hay una FAQ 2025 que aún lo declara obligatorio; ver la lección
reconciliada en `docs/LECCIONES-SII.md` (se da más peso al reparo en vivo + la Res. 53/2022).

Decisiones de diseño, todas por PORTABILIDAD (esto se empaqueta y se despliega como
servidor en Windows, macOS y Linux):

  - **Sin cron / launchd / Task Scheduler.** El programador vive DENTRO del proceso, como
    una tarea asyncio arrancada por el lifespan de FastAPI. Un `cron` habría atado el
    producto a Unix y habría exigido instalación aparte en cada máquina.
  - **Sin dependencias nuevas** (nada de APScheduler): un bucle `asyncio.sleep` alcanza y
    se comporta igual en los tres sistemas operativos.
  - **La zona horaria es la de CHILE, no la del servidor.** El "día" del RVD lo define el
    SII. Un servidor en UTC o en Europa cerraría el día a otra hora y reportaría mal.
    ⚠️ Windows NO trae base de datos de zonas horarias: `zoneinfo` depende del paquete
    `tzdata` (está en requirements.txt justamente por eso).
  - **El servidor NO está 24/7.** Si estuvo apagado, al arrancar se hace *catch-up*: se
    revisan los últimos `dias_atras` días y se genera lo que falte. Un scheduler que solo
    dispara "a las 23:59" perdería el reporte de todo día en que el equipo estuvo apagado.
  - **Idempotente**: el UNIQUE(rut, fecha, sec_envio) de `rvd_envios` evita reportar dos
    veces el mismo día aunque el bucle corra de más o el proceso se reinicie.

El RVD viaja por el **canal de FACTURAS** (`DTEUpload` en maullin/palena, con el token SOAP
de factura), NO por el REST de boletas — lo dice el OpenAPI oficial del SII; el detalle y la
cita están en `core/rvd.py`. Por eso aquí se usa `ClienteSII`, no `ClienteBoletaSII`.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, Optional
from zoneinfo import ZoneInfo

from core import keystore, negocios
from core.config import settings
from core.resolucion import resolucion_emisor
from core.rvd import (dias_con_boletas, enviar_rvd, generar_rvd_firmado,
                      registrar_rvd, rvd_registrado)
from core.sii import AmbienteSII, ClienteSII

logger = logging.getLogger("dte.scheduler")

TZ_CHILE = ZoneInfo("America/Santiago")

# Estados de una fila de rvd_envios.
ESTADO_GENERADO = "generado"          # XML firmado y válido, guardado en disco (no enviado)
ESTADO_ENVIADO = "enviado"            # el SII lo recibió y dio TrackID
ESTADO_ERROR = "error"
# Histórico: mientras se creyó que el RVD iba por una ruta REST inexistente, los días se
# marcaban `pendiente_ruta`. Ya no se produce, pero se reconoce para no reprocesar lo viejo.
ESTADO_PENDIENTE_RUTA = "pendiente_ruta"


def hoy_chile() -> date:
    """El día de hoy en Chile, sin importar dónde corra el servidor."""
    return datetime.now(TZ_CHILE).date()


def _ruta_xml(rut: str, dia: date) -> Path:
    carpeta = Path(settings.storage_path) / "rvd"
    carpeta.mkdir(parents=True, exist_ok=True)
    return carpeta / f"RVD_{rut}_{dia.isoformat()}.xml"


def procesar_dia(rut: str, cert_id: Optional[int], dia: date,
                 cuenta_id: int = 1) -> dict:
    """Genera (y guarda) el RVD de un día para un emisor. Idempotente.

    Returns:
        dict con `rut`, `dia`, `estado` y, si aplica, `detalle`.
    """
    ya = rvd_registrado(rut, dia)
    # Solo se omite lo que ya llegó al SII. Un día `generado` (XML listo pero no enviado)
    # SÍ se reintenta: si no, un fallo de red dejaría el reporte sin mandar para siempre.
    if ya and ya["estado"] in (ESTADO_ENVIADO, ESTADO_PENDIENTE_RUTA):
        return {"rut": rut, "dia": dia.isoformat(), "estado": "ya_estaba", "omitido": True}

    if cert_id is None:
        detalle = "El negocio no tiene certificado asociado: no se puede firmar el RVD."
        registrar_rvd(rut, dia, ESTADO_ERROR, detalle=detalle)
        return {"rut": rut, "dia": dia.isoformat(), "estado": ESTADO_ERROR, "detalle": detalle}

    try:
        cert = keystore.cargar_certificado(cert_id, cuenta_id)
        # Resolución POR-EMPRESA (el SII la valida por RUT; la de otra da CRT-3-19). El RVD
        # comparte la carátula del sobre de boletas de esa empresa. Ver core/resolucion.py.
        fch_resol, nro_resol = resolucion_emisor(rut, settings.sii_ambiente)
        xml = generar_rvd_firmado(
            rut_emisor=rut,
            cert=cert,
            dia=dia,
            fecha_resolucion=fch_resol,
            numero_resolucion=nro_resol,
            ambiente=settings.sii_ambiente,
        )
    except Exception as e:  # noqa: BLE001 — se registra y se sigue con los demás días
        detalle = f"{type(e).__name__}: {e}"
        logger.warning("RVD %s %s falló al generar: %s", rut, dia, detalle)
        registrar_rvd(rut, dia, ESTADO_ERROR, detalle=detalle)
        return {"rut": rut, "dia": dia.isoformat(), "estado": ESTADO_ERROR, "detalle": detalle}

    ruta = _ruta_xml(rut, dia)
    ruta.write_bytes(xml)

    # Envío por el canal de FACTURAS (DTEUpload + token SOAP), no por el REST de boletas.
    try:
        with ClienteSII(cert, AmbienteSII(settings.sii_ambiente)) as cliente:
            track_id, _ = enviar_rvd(xml, rut, cliente)
    except Exception as e:  # noqa: BLE001 — el día queda 'generado' y se reintenta luego
        detalle = f"{type(e).__name__}: {e}"
        logger.warning("RVD %s %s generado pero NO enviado: %s", rut, dia, detalle)
        registrar_rvd(rut, dia, ESTADO_GENERADO, xml_path=str(ruta), detalle=detalle)
        return {"rut": rut, "dia": dia.isoformat(), "estado": ESTADO_GENERADO,
                "xml_path": str(ruta), "detalle": detalle}

    registrar_rvd(rut, dia, ESTADO_ENVIADO, track_id=str(track_id), xml_path=str(ruta),
                  detalle=f"Enviado por DTEUpload ({settings.sii_ambiente}).")
    logger.info("RVD %s %s enviado → TrackID %s", rut, dia, track_id)
    return {"rut": rut, "dia": dia.isoformat(), "estado": ESTADO_ENVIADO,
            "track_id": str(track_id), "xml_path": str(ruta)}


def procesar_pendientes(cuenta_id: int = 1, dias_atras: int = 7,
                        hoy: Optional[date] = None) -> list[dict]:
    """Recorre las empresas y genera el RVD de los días con boletas que aún no se reportaron.

    Hace *catch-up*: mira hacia atrás `dias_atras` días, así un servidor que estuvo apagado
    recupera los reportes que debe. No incluye el día de hoy: aún puede recibir boletas.
    """
    hoy = hoy or hoy_chile()
    hasta = hoy - timedelta(days=1)
    desde = hoy - timedelta(days=dias_atras)

    resultados: list[dict] = []
    for neg in negocios.listar_negocios(cuenta_id):
        rut = neg.get("rut")
        if not rut:
            continue
        for dia in dias_con_boletas(rut, desde, hasta, ambiente=settings.sii_ambiente):
            resultados.append(procesar_dia(rut, neg.get("cert_id"), dia, cuenta_id))
    return resultados


class ProgramadorRVD:
    """Tarea asyncio que revisa periódicamente si hay RVD pendientes y los genera.

    Se arranca desde el lifespan de FastAPI. No usa cron: el proceso servidor es el reloj,
    lo que lo hace idéntico en Windows, macOS y Linux.
    """

    def __init__(self, cuenta_id: int = 1, intervalo_seg: int = 1800,
                 dias_atras: int = 7,
                 trabajo: Optional[Callable[..., list[dict]]] = None) -> None:
        self.cuenta_id = cuenta_id
        self.intervalo_seg = intervalo_seg
        self.dias_atras = dias_atras
        self._trabajo = trabajo or procesar_pendientes
        self._tarea: Optional[asyncio.Task] = None
        self.ultima_corrida: Optional[datetime] = None
        self.ultimo_resultado: list[dict] = []

    async def _bucle(self) -> None:
        while True:
            try:
                # El trabajo es sincrónico (SQLite + firma): va a un hilo para no
                # bloquear el event loop de la API.
                self.ultimo_resultado = await asyncio.to_thread(
                    self._trabajo, self.cuenta_id, self.dias_atras)
                self.ultima_corrida = datetime.now(TZ_CHILE)
                hechos = [r for r in self.ultimo_resultado if not r.get("omitido")]
                if hechos:
                    logger.info("RVD: %d día(s) procesado(s)", len(hechos))
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001 — el bucle NUNCA debe morir
                logger.exception("RVD: el ciclo falló (%s); se reintenta luego", e)
            await asyncio.sleep(self.intervalo_seg)

    def iniciar(self) -> None:
        if self._tarea is None or self._tarea.done():
            self._tarea = asyncio.create_task(self._bucle(), name="rvd-diario")
            logger.info("Programador de RVD iniciado (cada %ds, catch-up de %d días)",
                        self.intervalo_seg, self.dias_atras)

    async def detener(self) -> None:
        if self._tarea is None:
            return
        self._tarea.cancel()
        try:
            await self._tarea
        except asyncio.CancelledError:
            pass
        self._tarea = None
        logger.info("Programador de RVD detenido")

    def estado(self) -> dict:
        return {
            "activo": self._tarea is not None and not self._tarea.done(),
            "intervalo_seg": self.intervalo_seg,
            "dias_atras": self.dias_atras,
            "zona_horaria": str(TZ_CHILE),
            "hoy_chile": hoy_chile().isoformat(),
            "ultima_corrida": self.ultima_corrida.isoformat() if self.ultima_corrida else None,
            "ultimo_resultado": self.ultimo_resultado,
        }


programador = ProgramadorRVD()
