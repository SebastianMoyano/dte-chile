"""
mcp_server.py — Servidor MCP del motor DTE Chile.

Expone el toolkit del SII como **herramientas MCP** para que una IA (Claude u otro
cliente MCP) pueda realizar acciones sobre el SII: consultar autorización de una
empresa, ver la situación de folios, timbrar/anular folios, y consultar el estado de
un envío. Reusa exactamente el mismo `core/` que la API REST, así que la lógica y las
validaciones son una sola.

Manejo de credenciales:
  - Los certificados NO viajan por el protocolo. Cada herramienta que necesita firma
    o mutual-TLS recibe un ``cert_id`` que referencia el **keystore cifrado**
    (`core/keystore`); el servidor descifra el .p12 en memoria / a un PEM transitorio
    (permisos 600, borrado al terminar) y nunca lo expone.
  - La cuenta por defecto es ``MCP_CUENTA_ID`` (env, default 1).

Ejecutar (stdio, para clientes MCP locales — sin red, seguridad = frontera del proceso):
    .venv/bin/python mcp_server.py
o vía el CLI del SDK:
    .venv/bin/mcp run mcp_server.py

Ejecutar sobre HTTP (expone red → EXIGE auth por bearer token):
    MCP_AUTH_TOKEN=un-secreto .venv/bin/python mcp_server.py --http 0.0.0.0 8090
    # cada request necesita: Authorization: Bearer <MCP_AUTH_TOKEN o un JWT del proyecto>

Config de un cliente MCP (ej. Claude Desktop):
    {"mcpServers": {"dte-chile": {"command": ".venv/bin/python",
                                  "args": ["mcp_server.py"], "cwd": "/ruta/al/proyecto"}}}
"""
from __future__ import annotations

import dataclasses
import functools
import logging
import os
import sys
from typing import Any, Callable, Optional

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from core import keystore, negocios
from core.config import settings
from core.crypto import CertificadoDigital
from core.dte import DTEInput
from core.errors import DTEChileError, SIIError, SIIRechazoError, ValidacionError
from core.orchestrator import emitir_documento
from core.sii import AmbienteSII, ClienteSII
from core.sii_portal import BASE_CERTIFICACION, BASE_PRODUCCION, PortalSII

logger = logging.getLogger("dte.mcp")

CUENTA_ID = int(os.environ.get("MCP_CUENTA_ID", "1"))
AMBIENTE_DEFECTO = settings.sii_ambiente  # "certificacion" | "produccion"

mcp = FastMCP(
    "dte-chile",
    instructions=(
        "Motor de facturación electrónica DTE para el SII de Chile. Usa estas "
        "herramientas para consultar autorización de empresas, gestionar folios "
        "(timbrar/anular), y consultar el estado de envíos. Los tipos de DTE son: 33 "
        "Factura, 34 Factura Exenta, 39/41 Boletas, 52 Guía, 56 Nota Débito, 61 Nota "
        "Crédito. Los RUT van con guión y dígito verificador (ej. 76111111-6). El "
        "'ambiente' es 'certificacion' (pruebas, Maullín) o 'produccion' (Palena)."
    ),
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _base(ambiente: str) -> str:
    return BASE_PRODUCCION if ambiente == "produccion" else BASE_CERTIFICACION


def _amb(ambiente: str) -> AmbienteSII:
    return AmbienteSII.PRODUCCION if ambiente == "produccion" else AmbienteSII.CERTIFICACION


def _serializar(obj: Any) -> Any:
    """Convierte dataclasses/listas a estructuras JSON-serializables."""
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {k: _serializar(v) for k, v in dataclasses.asdict(obj).items()}
    if isinstance(obj, list):
        return [_serializar(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _serializar(v) for k, v in obj.items()}
    return obj


def herramienta(fn: Callable) -> Callable:
    """Decorador: registra la función como tool MCP y unifica el manejo de errores.

    - `DTEChileError`  → `ToolError` legible con el código de dominio.
    - Cualquier otra   → se loguea con traza y se devuelve un mensaje genérico.
    """

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return _serializar(fn(*args, **kwargs))
        except DTEChileError as e:
            raise ToolError(f"[{e.codigo}] {e.mensaje}") from None
        except ToolError:
            raise
        except Exception as e:  # noqa: BLE001 - frontera del servidor
            logger.exception("error en tool %s", fn.__name__)
            raise ToolError(f"Error ejecutando '{fn.__name__}': {e}") from None

    return mcp.tool()(wrapper)


def _portal_con_cert(cert_id: int, ambiente: str) -> "PortalSIICtx":
    """Devuelve un context manager que entrega un PortalSII autenticado."""
    return PortalSIICtx(cert_id, ambiente)


class PortalSIICtx:
    """Context manager: abre un PortalSII autenticado con un cert del keystore."""

    def __init__(self, cert_id: int, ambiente: str):
        self.cert_id, self.ambiente = cert_id, ambiente
        self._pem = None

    def __enter__(self) -> PortalSII:
        self._pem = keystore.pem_transitorio(self.cert_id, CUENTA_ID)
        cert_path, key_path = self._pem.__enter__()
        self.portal = PortalSII(cert_path, key_path, base=_base(self.ambiente))
        self.portal.autenticar()
        return self.portal

    def __exit__(self, *exc):
        if self._pem is not None:
            self._pem.__exit__(*exc)


# ---------------------------------------------------------------------------
# Herramientas — gestión local (keystore / negocios)
# ---------------------------------------------------------------------------
@herramienta
def salud() -> dict:
    """Estado del servidor MCP: ambiente por defecto, cuenta y nº de certificados."""
    certs = keystore.listar_certificados(CUENTA_ID)
    return {"servicio": "dte-chile-mcp", "ambiente_defecto": AMBIENTE_DEFECTO,
            "cuenta_id": CUENTA_ID, "certificados": len(certs)}


@herramienta
def listar_certificados() -> list:
    """Lista los certificados cargados en el keystore (id, RUT, nombre, vencimiento).

    Usa el ``id`` que devuelve como ``cert_id`` en las demás herramientas. NUNCA
    expone la clave privada.
    """
    return keystore.listar_certificados(CUENTA_ID)


@herramienta
def listar_negocios() -> list:
    """Lista los negocios (empresas) registrados en la cuenta con su cert asociado."""
    return negocios.listar_negocios(CUENTA_ID)


# ---------------------------------------------------------------------------
# Herramientas — consultas SII (algunas públicas, otras con certificado)
# ---------------------------------------------------------------------------
@herramienta
def empresa_autorizada(rut: str, ambiente: str = AMBIENTE_DEFECTO) -> Optional[dict]:
    """¿Qué DTE está autorizada a emitir una empresa? (consulta PÚBLICA, sin cert).

    Devuelve razón social, nº/fecha de resolución y los tipos de DTE autorizados; o
    ``null`` si el RUT no aparece autorizado.
    """
    return negocios.info_empresa(rut, ambiente)


@herramienta
def diagnostico(rut: str, cert_id: int, nombre_sistema: str = "tu software propio") -> dict:
    """Investigación automática (SOLO LECTURA) del estado de una empresa en el SII + plan.

    Devuelve estado, chequeos y un plan de acciones donde cada una trae `modo`: 'auto'
    (el sistema lo hace), 'consentimiento' (escribe en el SII → pide autorización) o
    'humano' (gestión con el SII). Ideal como primer paso del onboarding: dice qué falta
    para que la empresa emita con su software.
    """
    from core.onboarding import diagnosticar
    with _portal_con_cert(cert_id, "certificacion") as portal:
        return diagnosticar(portal, rut, nombre_sistema).to_dict()


@herramienta
def diagnostico_cartera(cert_id: int, nombre_sistema: str = "tu software propio") -> list:
    """Diagnostica TODAS las empresas asociadas a un certificado (vista de cartera).

    Descubre las empresas del cert y devuelve un RESUMEN por empresa (estado + si está
    lista para emitir + nº de acciones pendientes). Para el detalle de una empresa
    puntual usa `diagnostico`. Solo lectura.
    """
    from core.onboarding import diagnosticar_cartera
    with _portal_con_cert(cert_id, "certificacion") as portal:
        cartera = diagnosticar_cartera(portal, nombre_sistema=nombre_sistema)
        return [{"rut": d.rut, "razon_social": d.razon_social, "estado": d.estado,
                 "etiqueta": d.etiqueta, "listo_para_emitir": d.listo_para_emitir,
                 "acciones_pendientes": sum(1 for a in d.acciones if not a.hecho)}
                for d in cartera]


@herramienta
def salud_folios(rut: str) -> dict:
    """Salud de folios/CAF de una empresa — LOCAL, sin tocar el SII.

    Lee los CAF cargados y detecta **vencidos** (regla SII de 6 meses, CAF-3-517) y folios
    **agotándose**. Devuelve un veredicto (ok/atencion/critico) + detalle por CAF con la
    acción sugerida. Útil para no quedarse sin folios ni usar un CAF vencido.
    """
    from core.monitoreo import resumen_salud
    return resumen_salud(rut)


@herramienta
def salud_folios_cartera() -> dict:
    """Salud de folios/CAF de TODAS las empresas cargadas — LOCAL, sin SII. Ordena por
    urgencia y lista cuáles requieren atención (CAF vencido o folios agotándose)."""
    from core.monitoreo import salud_cartera
    return salud_cartera()


@herramienta
def situacion_folios(rut: str, cert_id: int, tipos: Optional[list[int]] = None,
                     ambiente: str = AMBIENTE_DEFECTO) -> dict:
    """Situación de folios por tipo: si puede timbrar y si está bloqueado.

    ``tipos`` es una lista de tipos de DTE (ej. [33, 61]); si se omite, usa los
    habituales. Requiere ``cert_id`` (el mandatario que timbra).
    """
    with _portal_con_cert(cert_id, ambiente) as portal:
        return portal.situacion_folios(rut, tipos)


@herramienta
def timbrajes(rut: str, tipo_dte: int, cert_id: int,
              ambiente: str = AMBIENTE_DEFECTO) -> list:
    """Rangos de folios ya autorizados (timbrados) para un RUT y tipo de DTE."""
    with _portal_con_cert(cert_id, ambiente) as portal:
        return portal.consultar_timbrajes(rut, tipo_dte)


@herramienta
def datos_software(rut: str, cert_id: int, ambiente: str = AMBIENTE_DEFECTO) -> dict:
    """Software de emisión registrado y resolución del contribuyente en el SII."""
    with _portal_con_cert(cert_id, ambiente) as portal:
        return portal.datos_software(rut)


@herramienta
def empresas_del_certificado(cert_id: int, ambiente: str = AMBIENTE_DEFECTO) -> list:
    """Empresas a las que está asociado el titular de un certificado (mandatario)."""
    with _portal_con_cert(cert_id, ambiente) as portal:
        return portal.empresas_asociadas()


@herramienta
def folios_anulables(rut: str, tipo_dte: int, cert_id: int,
                     ambiente: str = AMBIENTE_DEFECTO) -> list:
    """Rangos de folios que se pueden ANULAR (no recepcionados) para un tipo de DTE."""
    with _portal_con_cert(cert_id, ambiente) as portal:
        return portal.listar_anulables(rut, tipo_dte)


@herramienta
def estado_envio(track_id: int, rut: str, cert_id: int,
                 ambiente: str = AMBIENTE_DEFECTO) -> dict:
    """Estado de un envío al SII por su TrackID (EPR/aceptado/rechazado + glosa)."""
    num, dv = rut.split("-") if "-" in rut else (rut, "")
    cert: CertificadoDigital = keystore.cargar_certificado(cert_id, CUENTA_ID)
    cliente = ClienteSII(cert, _amb(ambiente))
    return cliente.consultar_estado_track(int(track_id), num, dv)


# ---------------------------------------------------------------------------
# Herramientas — acciones de ESCRITURA (modifican estado en el SII)
# ---------------------------------------------------------------------------
@herramienta
def estado_envios(track_ids: list[int], rut: str, cert_id: int,
                  ambiente: str = AMBIENTE_DEFECTO) -> dict:
    """Estado de VARIOS envíos al SII de una vez (por TrackID) + resumen accionable
    (aceptados/rechazados/pendientes/todos_resueltos). Cierra el ciclo emitir→enviar→
    confirmar: útil para saber si un lote ya terminó de procesarse.
    """
    from core.seguimiento import estados_lote
    num, dv = rut.split("-") if "-" in rut else (rut, "")
    cliente = ClienteSII(keystore.cargar_certificado(cert_id, CUENTA_ID), _amb(ambiente))
    try:
        return estados_lote(cliente, [int(t) for t in track_ids], num, dv)
    finally:
        cliente.close()


@herramienta
def solicitar_folios(rut: str, tipo_dte: int, cert_id: int, cantidad: int = 1,
                     ambiente: str = AMBIENTE_DEFECTO, forzar: bool = False) -> dict:
    """TIMBRA (solicita) folios nuevos al SII. ACCIÓN REAL: consume cupo de timbraje.

    Verifica bloqueo por anti-acaparamiento antes de pedir; usa ``forzar=True`` solo
    si sabes lo que haces. Devuelve ``{obtenido, info, caf_xml}`` — ``caf_xml`` trae el
    CAF (XML) si se obtuvo, y ``info`` la razón si no (bloqueado / rate_limited / error).
    """
    with _portal_con_cert(cert_id, ambiente) as portal:
        caf_bytes, info = portal.solicitar_folios(rut, tipo_dte, cantidad, forzar=forzar)
    return {
        "obtenido": caf_bytes is not None,
        "info": info,
        "caf_xml": caf_bytes.decode("ISO-8859-1") if caf_bytes else None,
    }


@herramienta
def anular_folios(rut: str, tipo_dte: int, folio_desde: int, folio_hasta: int,
                  cert_id: int, motivo: str = "", ambiente: str = AMBIENTE_DEFECTO) -> dict:
    """ANULA un rango de folios NO recepcionados. ACCIÓN REAL E IRREVERSIBLE.

    Solo funciona con folios que el SII no haya recibido aún, y con el mandatario que
    los timbró. Útil para drenar stock y destrabar el anti-acaparamiento.
    """
    with _portal_con_cert(cert_id, ambiente) as portal:
        return portal.anular_folios(rut, tipo_dte, folio_desde, folio_hasta, motivo)


@herramienta
def enviar_dte(xml_envio_b64: str, rut_empresa: str, cert_id: int, tipo_dte: int = 33,
               ambiente: str = AMBIENTE_DEFECTO) -> dict:
    """ENVÍA un EnvioDTE firmado al SII. ACCIÓN REAL. Devuelve el TrackID.

    `xml_envio_b64` es el sobre EnvioDTE en base64 — típicamente el `xml_envio_b64` que
    devuelve `emitir_dte`. Luego consulta el resultado con `estado_envio` usando el
    TrackID. `rut_empresa` va con guión y DV (ej. 76111111-6).
    """
    import base64
    num, dv = rut_empresa.split("-") if "-" in rut_empresa else (rut_empresa, "")
    try:
        xml_bytes = base64.b64decode(xml_envio_b64)
    except Exception as e:
        raise ValidacionError(f"xml_envio_b64 no es base64 válido: {e}")
    cert = keystore.cargar_certificado(cert_id, CUENTA_ID)
    cliente = ClienteSII(cert, _amb(ambiente))
    try:
        track_id, mensaje = cliente.enviar_dte(
            xml_bytes, rut_empresa=num, dv_empresa=dv, tipo_dte=tipo_dte)
    except ValueError as e:
        raise SIIRechazoError(f"El SII rechazó el envío: {e}")
    except SIIError:
        raise
    except Exception as e:
        raise SIIError(f"Error de comunicación con el SII: {e}")
    return {"track_id": track_id, "mensaje": mensaje, "ambiente": ambiente}


@herramienta
def previsualizar_dte(dte: DTEInput, cert_id: int) -> dict:
    """Previsualiza un DTE: lo genera FIRMADO + timbrado + valida XSD + PDF, SIN enviarlo al
    SII ni consumir folios. Para 'ver la factura' antes de emitir de verdad. Resuelve el CAF
    activo de la BD (por emisor+tipo) y el certificado del keystore. Devuelve totales,
    resultado XSD y el XML + PDF en base64.
    """
    from core.caf import ManejadorCAF
    from core.errors import FolioError
    from core.models import obtener_caf_activo
    from core.preview import previsualizar_dte as _prev
    cert = keystore.cargar_certificado(cert_id, CUENTA_ID)
    caf_db = obtener_caf_activo(dte.emisor.rut, dte.tipo_dte.value)
    if not caf_db:
        raise FolioError(f"No hay CAF activo para {dte.emisor.rut} tipo {dte.tipo_dte.value}.")
    return _prev(dte, cert, ManejadorCAF(caf_db["caf_xml"].encode("utf-8")))


@herramienta
def emitir_dte(dte: DTEInput, cert_id: Optional[int] = None) -> dict:
    """EMITE un DTE o BOLETA completo. ACCIÓN REAL: consume un folio, firma, genera PDF y persiste.

    Ejecuta el pipeline del orquestador: asigna folio (auto si `folio=0`) desde el CAF
    activo → arma y firma el TED → firma el documento y su sobre → genera el PDF → guarda
    en BD. Devuelve ids, rutas y el sobre en base64 (listo para enviar al SII).

    Rutea solo según el tipo: 39/41 salen como EnvioBOLETA con PDF de 80mm; el resto como
    EnvioDTE. `cert_id` referencia el certificado firmante en el keystore; si se omite, usa
    el configurado en `.env`. NO envía al SII por sí solo (usa el resultado para enviarlo).
    """
    cert = keystore.cargar_certificado(cert_id, CUENTA_ID) if cert_id else None
    return emitir_documento(dte, certificado=cert)


# ---------------------------------------------------------------------------
# Autenticación (solo para el transporte HTTP)
# ---------------------------------------------------------------------------
# En stdio el servidor lo lanza el cliente MCP local: la seguridad es la frontera del
# proceso (no expone red), así que no aplica auth. Sobre HTTP sí exponemos red, y ahí
# exigimos `Authorization: Bearer <token>` donde el token es:
#   - el secreto compartido `MCP_AUTH_TOKEN` (env), o
#   - un JWT válido del proyecto (el mismo de la API REST, `core/auth`).
MCP_AUTH_TOKEN = os.environ.get("MCP_AUTH_TOKEN")


def _token_valido(token: str) -> bool:
    import hmac
    if not token:
        return False
    # compare_digest evita filtrar el secreto por tiempo (timing attack).
    if MCP_AUTH_TOKEN and hmac.compare_digest(token, MCP_AUTH_TOKEN):
        return True
    from core.auth import decodificar_token
    return bool(decodificar_token(token))


class _AuthASGI:
    """Middleware ASGI puro: gate de bearer token sin bufferizar el streaming del MCP."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers") or [])
        auth = headers.get(b"authorization", b"").decode("latin-1")
        token = auth[7:].strip() if auth[:7].lower() == "bearer " else ""
        if not _token_valido(token):
            body = (b'{"error":{"codigo":"autenticacion",'
                    b'"mensaje":"Token MCP invalido o ausente (Authorization: Bearer)."}}')
            await send({"type": "http.response.start", "status": 401,
                        "headers": [(b"content-type", b"application/json"),
                                    (b"content-length", str(len(body)).encode())]})
            await send({"type": "http.response.body", "body": body})
            return
        await self.app(scope, receive, send)


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s")
    args = sys.argv[1:]
    if args and args[0].lstrip("-") == "http":
        host = args[1] if len(args) > 1 else "127.0.0.1"
        port = int(args[2]) if len(args) > 2 else 8090
        metodos = (["MCP_AUTH_TOKEN"] if MCP_AUTH_TOKEN else []) + ["JWT del proyecto"]
        logger.info("MCP HTTP en http://%s:%s — auth por: %s", host, port, ", ".join(metodos))
        import uvicorn
        uvicorn.run(_AuthASGI(mcp.streamable_http_app()), host=host, port=port)
    else:
        mcp.run()  # stdio (local, sin red)


if __name__ == "__main__":
    main()
