"""
core/sii_boleta.py — Cliente REST para BOLETAS electrónicas (39/41) del SII.

Las boletas NO comparten infraestructura con las facturas (Res. Ex. SII N° 74 de 2020):
  - Son **servicios REST**, no SOAP (`core/sii.py` es el camino de facturas).
  - Corren en **servidores propios**: NO maullin/palena.
  - Usan un **token propio**: el token de factura electrónica NO sirve aquí.

⚠️ LOS HOSTS SON ASIMÉTRICOS — es el error que más tiempo cuesta:

    paso                        certificación      producción
    semilla · token · consulta  apicert.sii.cl     api.sii.cl
    ENVÍO                       pangal.sii.cl      rahue.sii.cl

Mandar el ENVÍO a apicert/api NO da un error de auth: devuelve un SOAP Fault
"Acceso Denegado (from client)" con HTTP 500, que parece un problema de permisos y
manda a depurar el certificado. `pangal`/`rahue` responden HTTP 400 "No trae TOKEN"
→ ésa es la ruta correcta.

Procedencia de las rutas: verificadas en vivo contra el SII (2026-07-16) y contrastadas
con `benjamcadev/apiAgroDTE` (C#), la única implementación open source del envío REST.
**LibreDTE NO sirve como referencia aquí**: nunca implementó el envío de boletas
(`EnvioDte::enviar()` retorna `false` si es boleta; en su master sigue siendo un TODO).
`BOLUpload` / `cgi_bol` / `rest/int/boleta` son pistas falsas: no existen en ningún
código público ni respondieron en las pruebas.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Optional, Tuple

import httpx
from lxml import etree

from core.crypto import CertificadoDigital, firmar_documento_xml
from core.errors import SIIError, SIIRechazoError
from core.reintentos import ClienteReintentos
from core.sii import AmbienteSII

logger = logging.getLogger("dte.sii_boleta")

# Rutas REST de boleta. Ojo con la asimetría de hosts (ver docstring del módulo).
URLS_BOLETA = {
    AmbienteSII.CERTIFICACION: {
        "semilla": "https://apicert.sii.cl/recursos/v1/boleta.electronica.semilla",
        "token": "https://apicert.sii.cl/recursos/v1/boleta.electronica.token",
        "envio": "https://pangal.sii.cl/recursos/v1/boleta.electronica.envio",
        "estado": "https://apicert.sii.cl/recursos/v1/boleta.electronica.envio",
    },
    AmbienteSII.PRODUCCION: {
        "semilla": "https://api.sii.cl/recursos/v1/boleta.electronica.semilla",
        "token": "https://api.sii.cl/recursos/v1/boleta.electronica.token",
        "envio": "https://rahue.sii.cl/recursos/v1/boleta.electronica.envio",
        "estado": "https://api.sii.cl/recursos/v1/boleta.electronica.envio",
    },
}

# El SII responde el ESTADO como string de DOS dígitos ("00"), no "0". Comparar con "0"
# hace que todo parezca fallar.
ESTADO_OK = "00"

# Estados del ENVÍO (el sobre), que devuelve la consulta REST.
# ⚠️ EPR = "Envío Procesado", NO "aceptado". Dice que el SII procesó el SOBRE; cada
# documento adentro puede haber sido rechazado igual. El estado real por documento está en
# `estadistica` (aceptados/rechazados) y `detalle_rep_rech`. Confundir EPR con aceptación
# tuvo al proyecto creyendo que la certificación pasaba mientras el SII rechazaba TODO.
ESTADO_PROCESADO = "EPR"
ESTADO_RECHAZADO = "RCT"
ESTADOS_REPARO = ("RLV", "RPR")

# El servlet de envío del SII EXIGE un User-Agent de navegador. Sin él responde
# **401 "NO ESTA AUTENTICADO"** aunque el token sea válido — un mensaje que miente y manda
# a depurar el certificado. Es el mismo capricho ya documentado para DTEUpload en core/sii.py.
_USER_AGENT = "Mozilla/5.0 (compatible; DTE-Chile/1.0)"

# Tope de boletas por sobre. ⚠️ NO está en el XSD: `EnvioBOLETA_v11.xsd:89` declara
# `maxOccurs="unbounded"` para DTE (el `maxOccurs="1000"` del esquema es de `Detalle`, las
# líneas DENTRO de una boleta). El 500 viene del Instructivo Técnico del SII (Res. Ex. SII N° 74 de 2020)
# y **no está verificado contra el SII vivo**: es un tope conservador nuestro.
MAX_BOLETAS_POR_ENVIO = 500


def _texto(root: etree._Element, tag: str) -> Optional[str]:
    """Busca un tag por nombre local (el SII mezcla elementos con y sin namespace)."""
    encontrados = root.xpath(f"//*[local-name()='{tag}']")
    if not encontrados or not encontrados[0].text:
        return None
    return encontrados[0].text.strip()


class ClienteBoletaSII:
    """Cliente REST del SII para boletas electrónicas (39/41).

    Flujo: `obtener_token()` (semilla → firma → token) → `enviar_boletas()` → `consultar_estado()`.
    El token se cachea 50 min (dura ~1h) y es **propio de boleta**.
    """

    def __init__(
        self,
        certificado: CertificadoDigital,
        ambiente: AmbienteSII = AmbienteSII.CERTIFICACION,
        timeout: float = 30.0,
    ):
        self.certificado = certificado
        self.ambiente = ambiente
        self.urls = URLS_BOLETA[ambiente]
        self.timeout = timeout
        self._token: Optional[str] = None
        self._token_expira: Optional[datetime] = None
        self._client: Optional[ClienteReintentos] = None

    def _cli(self) -> ClienteReintentos:
        """Cliente HTTP persistente con reintentos (429/5xx). A diferencia del cliente de
        facturas aquí hay DOS hosts (apicert y pangal); httpx mantiene un pool por host,
        así que igual se reutilizan las conexiones TLS."""
        if self._client is None or self._client.is_closed:
            self._client = ClienteReintentos(timeout=self.timeout, verify=True)
        return self._client

    def close(self) -> None:
        if self._client is not None and not self._client.is_closed:
            self._client.close()
        self._client = None

    def __enter__(self) -> "ClienteBoletaSII":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Autenticación (token PROPIO de boleta)
    # ------------------------------------------------------------------
    def obtener_semilla(self) -> str:
        """Pide una semilla al SII (endpoint REST, sin autenticación)."""
        try:
            resp = self._cli().get(self.urls["semilla"], headers={"accept": "application/xml"})
            resp.raise_for_status()
        except httpx.HTTPError as e:
            raise SIIError(f"No se pudo pedir la semilla de boleta al SII: {e}") from e

        try:
            root = etree.fromstring(resp.content)
        except etree.XMLSyntaxError as e:
            raise SIIError(
                f"La respuesta de semilla del SII no es XML válido: {e}",
                detalle={"respuesta": resp.text[:500]},
            ) from e

        estado = _texto(root, "ESTADO")
        semilla = _texto(root, "SEMILLA")
        if estado != ESTADO_OK or not semilla:
            raise SIIError(
                f"El SII no entregó semilla de boleta (ESTADO={estado}).",
                detalle={"estado": estado, "glosa": _texto(root, "GLOSA")},
            )
        return semilla

    def _firmar_semilla(self, semilla: str) -> bytes:
        """Firma la semilla. El cuerpo es el mismo `<getToken>` del flujo SOAP, pero aquí
        el XML firmado se manda **directo** como body (sin escapar dentro de un sobre)."""
        elem = etree.fromstring(
            f"<getToken><item><Semilla>{semilla}</Semilla></item></getToken>".encode("utf-8")
        )
        firmado = firmar_documento_xml(elem, self.certificado)
        return b'<?xml version="1.0" encoding="UTF-8"?>\n' + etree.tostring(firmado)

    def obtener_token(self) -> str:
        """Semilla → firma → token de boleta. Cachea el token 50 min."""
        if self._token and self._token_expira and datetime.now() < self._token_expira:
            return self._token

        cuerpo = self._firmar_semilla(self.obtener_semilla())
        try:
            resp = self._cli().post(
                self.urls["token"],
                content=cuerpo,
                headers={"Content-Type": "application/xml", "accept": "application/xml"},
            )
            resp.raise_for_status()
        except httpx.HTTPError as e:
            raise SIIError(f"No se pudo obtener el token de boleta: {e}") from e

        try:
            root = etree.fromstring(resp.content)
        except etree.XMLSyntaxError as e:
            raise SIIError(
                f"La respuesta de token del SII no es XML válido: {e}",
                detalle={"respuesta": resp.text[:500]},
            ) from e

        token = _texto(root, "TOKEN")
        if not token:
            # El SII responde HTTP 200 aunque falle: el error viene en ESTADO/GLOSA.
            raise SIIError(
                "El SII no entregó token de boleta.",
                detalle={"estado": _texto(root, "ESTADO"), "glosa": _texto(root, "GLOSA")},
            )

        self._token = token
        self._token_expira = datetime.now() + timedelta(minutes=50)
        return token

    # ------------------------------------------------------------------
    # Envío y consulta
    # ------------------------------------------------------------------
    def enviar_boletas(
        self,
        xml_envio_bytes: bytes,
        rut_empresa: str,
        dv_empresa: str,
    ) -> Tuple[str, str]:
        """Envía un `EnvioBOLETA` firmado y devuelve `(track_id, mensaje)`.

        Args:
            xml_envio_bytes: XML EnvioBOLETA firmado, en ISO-8859-1.
            rut_empresa: RUT del emisor SIN DV ni guion (ej. "76111111").
            dv_empresa: Dígito verificador (ej. "6").

        El TrackID de boleta tiene **15 dígitos** (el de factura, 10) → se devuelve como
        `str` para no depender del ancho del entero.
        """
        token = self.obtener_token()

        rut_cert = self.certificado.rut_emisor
        if rut_cert == "SIN-RUT":
            rut_sender, dv_sender = rut_empresa, dv_empresa
        else:
            rut_sender, dv_sender = rut_cert.split("-")

        # El RUT va PARTIDO y sin guion, en cuatro campos: quien envía (dueño del
        # certificado) y la empresa emisora.
        data = {
            "rutSender": rut_sender,
            "dvSender": dv_sender,
            "rutCompany": rut_empresa,
            "dvCompany": dv_empresa,
        }
        # El mimetype exacto que espera el SII para esta parte NO está confirmado (el
        # cliente C# de referencia lo infiere de la extensión). text/xml + ISO-8859-1 es
        # lo coherente con el resto del motor; si el SII lo rechaza, probar aquí primero.
        files = {
            "archivo": (
                f"{rut_empresa}-{dv_empresa}_boletas.xml",
                xml_envio_bytes,
                "text/xml",
            ),
        }

        try:
            resp = self._cli().post(
                self.urls["envio"],
                headers={"Cookie": f"TOKEN={token}", "Accept": "application/json",
                         "User-Agent": _USER_AGENT},  # sin esto: 401 engañoso
                data=data,
                files=files,
            )
            resp.raise_for_status()
        except httpx.HTTPError as e:
            raise SIIError(f"Falló el envío de boletas al SII: {e}") from e

        # A diferencia de DTEUpload (que responde XML), el envío de boleta responde JSON.
        try:
            cuerpo = resp.json()
        except json.JSONDecodeError as e:
            raise SIIError(
                "La respuesta del envío de boletas no es JSON (¿endpoint equivocado? "
                "el envío va a pangal/rahue, no a apicert/api).",
                detalle={"respuesta": resp.text[:500]},
            ) from e

        estado = str(cuerpo.get("estado", "")).upper()
        if estado != "REC":
            raise SIIRechazoError(
                f"El SII no recibió el envío de boletas (estado={estado or 'desconocido'}).",
                codigo_sii=estado or None,
                detalle={k: v for k, v in cuerpo.items() if k != "archivo"},
            )

        track_id = str(cuerpo.get("trackid", "")).strip()
        if not track_id:
            raise SIIError(
                "El SII aceptó el envío pero no devolvió TrackID.",
                detalle={"respuesta": cuerpo},
            )
        return track_id, f"Envío de boletas recibido. TrackID: {track_id}"

    def consultar_estado(self, track_id: str, rut_empresa: str, dv_empresa: str) -> dict:
        """Consulta el estado de un envío de boletas por TrackID.

        El TrackID va **en el path**, pegado al RUT con guiones: `{RUT}-{DV}-{TRACKID}`.
        No hay query params.

        Returns:
            dict con el estado del SOBRE y, lo que de verdad importa, el recuento por
            documento: `aceptados`, `rechazados`, `reparos` y `detalle` con el error exacto
            de cada boleta rechazada (sección, código y descripción).

        ⚠️ `estado == "EPR"` NO quiere decir que las boletas se aceptaran: quiere decir que
        el SII terminó de procesar el sobre. Usar `aceptados`/`rechazados`.
        """
        token = self.obtener_token()
        url = f"{self.urls['estado']}/{rut_empresa}-{dv_empresa}-{track_id}"

        try:
            resp = self._cli().get(
                url, headers={"Cookie": f"TOKEN={token}", "Accept": "application/json",
                              "User-Agent": _USER_AGENT}
            )
            resp.raise_for_status()
        except httpx.HTTPError as e:
            raise SIIError(f"No se pudo consultar el estado del envío {track_id}: {e}") from e

        try:
            cuerpo = resp.json()
        except json.JSONDecodeError as e:
            raise SIIError(
                f"La respuesta de estado del envío {track_id} no es JSON: {e}",
                detalle={"respuesta": resp.text[:500]},
            ) from e

        estado = str(cuerpo.get("estado", "")).upper()

        # El veredicto por documento vive en `estadistica`, NO en `estado`.
        aceptados = rechazados = reparos = informados = 0
        for e in cuerpo.get("estadistica") or []:
            informados += int(e.get("informados") or 0)
            aceptados += int(e.get("aceptados") or 0)
            rechazados += int(e.get("rechazados") or 0)
            reparos += int(e.get("reparos") or 0)

        return {
            "track_id": track_id,
            "estado": estado,
            "glosa": cuerpo.get("glosa") or cuerpo.get("descripcion") or "",
            "procesado": estado == ESTADO_PROCESADO,
            "informados": informados,
            "aceptados": aceptados,
            "rechazados": rechazados,
            "reparos": reparos,
            # Solo es "todo aceptado" si el SII procesó Y no rechazó ni reparó nada.
            "todo_aceptado": (estado == ESTADO_PROCESADO and informados > 0
                              and rechazados == 0 and reparos == 0),
            # `resuelto` = el SII ya terminó (no sigue en tránsito).
            "resuelto": estado in (ESTADO_PROCESADO, ESTADO_RECHAZADO, *ESTADOS_REPARO),
            # Error exacto por documento: [{tipo, folio, estado, error:[{codigo,...}]}]
            "detalle": cuerpo.get("detalle_rep_rech"),
            "respuesta_raw": cuerpo,
        }
