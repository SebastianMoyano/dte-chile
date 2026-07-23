"""
core/sii.py

Cliente HTTP para los Web Services del SII de Chile.

Implementa:
 - Autenticación (Semilla → Token)
 - Envío de EnvioDTE al SII
 - Consulta de estado de documentos por TrackID y por folio
 - Soporte para ambientes de Pruebas (Maullin) y Producción

Esto es SOLO el camino de FACTURAS (SOAP, maullin/palena). Las boletas (39/41) usan otra
infraestructura por completo — REST, otros servidores y token propio: ver `core/sii_boleta.py`.
"""

import base64
from datetime import datetime
from enum import Enum
from typing import Optional, Tuple

import httpx

from core.reintentos import ClienteReintentos
from lxml import etree

from core.crypto import CertificadoDigital, canonicalizar_elemento
from core.errors import ValidacionError


class AmbienteSII(str, Enum):
    """Ambientes del Servicio de Impuestos Internos de Chile."""
    PRODUCCION = "produccion"
    CERTIFICACION = "certificacion"  # También llamado "maullin"


# URLs de los web services del SII
URLS_SII = {
    AmbienteSII.CERTIFICACION: {
        "semilla": "https://maullin.sii.cl/DTEWS/CrSeed.jws",
        "token": "https://maullin.sii.cl/DTEWS/GetTokenFromSeed.jws",
        "envio_dte": "https://maullin.sii.cl/cgi_dte/UPL/DTEUpload",
        "estado_dte": "https://maullin.sii.cl/DTEWS/services/wsDTECorreo",
        "estado_track": "https://maullin.sii.cl/DTEWS/QueryEstUp.jws",
    },
    AmbienteSII.PRODUCCION: {
        "semilla": "https://palena.sii.cl/DTEWS/CrSeed.jws",
        "token": "https://palena.sii.cl/DTEWS/GetTokenFromSeed.jws",
        "envio_dte": "https://palena.sii.cl/cgi_dte/UPL/DTEUpload",
        "estado_dte": "https://palena.sii.cl/DTEWS/services/wsDTECorreo",
        "estado_track": "https://palena.sii.cl/DTEWS/QueryEstUp.jws",
    },
}

# SOAP envelope para consultar la semilla
SOAP_SEMILLA = """<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/">
  <soapenv:Body>
    <getSeed/>
  </soapenv:Body>
</soapenv:Envelope>"""

# SOAP envelope para obtener el token con la semilla firmada
SOAP_TOKEN_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/">
  <soapenv:Body>
    <getToken>
      <pszXml>{semilla_firmada}</pszXml>
    </getToken>
  </soapenv:Body>
</soapenv:Envelope>"""


class ClienteSII:
    """
    Cliente para los Web Services del SII de Chile.

    Maneja la autenticación y el envío de documentos DTE.
    """

    def __init__(
        self,
        certificado: CertificadoDigital,
        ambiente: AmbienteSII = AmbienteSII.CERTIFICACION,
        timeout: float = 30.0,
    ):
        """
        Args:
            certificado: Certificado digital del contribuyente.
            ambiente: Ambiente del SII (pruebas o producción).
            timeout: Timeout en segundos para las peticiones HTTP.
        """
        self.certificado = certificado
        self.ambiente = ambiente
        self.urls = URLS_SII[ambiente]
        self.timeout = timeout
        self._token: Optional[str] = None
        self._token_expira: Optional[datetime] = None
        # Cliente HTTP persistente (keep-alive) — se crea al primer uso y se reutiliza.
        self._client: Optional[ClienteReintentos] = None

    def _cli(self) -> ClienteReintentos:
        """Cliente HTTP persistente: reutiliza la conexión TLS (keep-alive) entre
        llamadas. Todas van al mismo host (maullin/palena), así que semilla→token→
        envío→consultas comparten una sola conexión en vez de un handshake por request."""
        if self._client is None or self._client.is_closed:
            self._client = ClienteReintentos(timeout=self.timeout, verify=True)
        return self._client

    def close(self) -> None:
        """Cierra la conexión persistente. Llamar al terminar (o usar como context manager)."""
        if self._client is not None and not self._client.is_closed:
            self._client.close()
        self._client = None

    def __enter__(self) -> "ClienteSII":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

    def _soap_post(self, url: str, soap_body: str, accion: str = "") -> str:
        """
        Envía una petición SOAP al SII.

        Args:
            url: URL del web service.
            soap_body: Cuerpo del mensaje SOAP.
            accion: Acción SOAP (SOAPAction header).

        Returns:
            Respuesta XML como string.

        Raises:
            httpx.HTTPError: Si la petición falla.
        """
        headers = {
            "Content-Type": "text/xml; charset=UTF-8",
            "SOAPAction": accion,
        }
        response = self._cli().post(url, content=soap_body.encode("utf-8"), headers=headers)
        response.raise_for_status()
        return response.text

    def obtener_semilla(self) -> str:
        """
        Solicita una semilla temporal al SII.
        La semilla es un string único que debe firmarse para obtener el token.

        Returns:
            La semilla como string.

        Raises:
            ValueError: Si el SII responde con error.
        """
        respuesta = self._soap_post(self.urls["semilla"], SOAP_SEMILLA)
        root = etree.fromstring(respuesta.encode("utf-8"))

        # Buscar la semilla en la respuesta SOAP
        semilla_elem = root.find(".//{http://www.sii.cl/XMLSchema}SEMILLA")
        if semilla_elem is None:
            semilla_elem = root.find(".//SEMILLA")

        if semilla_elem is None:
            # Intentar buscar dentro de getSeedReturn que suele contener XML escapado
            return_elem = root.find(".//getSeedReturn")
            if return_elem is None:
                return_elem = root.xpath("//*[local-name()='getSeedReturn']")
                if return_elem:
                    return_elem = return_elem[0]
            if return_elem is not None and return_elem.text:
                try:
                    inner_root = etree.fromstring(return_elem.text.encode("utf-8"))
                    semilla_elem = inner_root.find(".//SEMILLA")
                except Exception:
                    pass

        if semilla_elem is None or not semilla_elem.text:
            raise ValueError(f"No se pudo obtener la semilla del SII. Respuesta: {respuesta}")

        return semilla_elem.text.strip()

    def _firmar_semilla(self, semilla: str) -> str:
        """
        Firma la semilla obtenida del SII con el certificado del contribuyente.

        El formato esperado es un XML firmado con XMLDSig que contiene la semilla.
        """
        from core.crypto import firmar_documento_xml
        
        semilla_xml_str = f"""<getToken>
<item>
<Semilla>{semilla}</Semilla>
</item>
</getToken>"""
        
        semilla_elem = etree.fromstring(semilla_xml_str)
        semilla_firmada_elem = firmar_documento_xml(semilla_elem, self.certificado)
        
        # El SII espera la cabecera XML
        xml_str = etree.tostring(semilla_firmada_elem, encoding="unicode")
        return f'<?xml version="1.0" encoding="UTF-8"?>\n{xml_str}'


    def obtener_token(self) -> str:
        """
        Realiza el flujo completo de autenticación con el SII:
        1. Obtiene una semilla
        2. Firma la semilla con el certificado del contribuyente
        3. Envía la semilla firmada al SII
        4. Retorna el token de sesión

        Returns:
            Token de sesión del SII.

        Raises:
            ValueError: Si la autenticación falla.
        """
        # Reusar el token en caché si sigue vigente (se guarda con TTL de 50 min).
        if self._token and self._token_expira and datetime.now() < self._token_expira:
            return self._token

        # Paso 1: Obtener semilla
        semilla = self.obtener_semilla()

        # Paso 2: Firmar la semilla
        semilla_firmada = self._firmar_semilla(semilla)

        # Escapar para el SOAP body
        semilla_firmada_escaped = semilla_firmada.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        # Paso 3: Enviar semilla firmada al SII para obtener token
        soap_body = SOAP_TOKEN_TEMPLATE.format(semilla_firmada=semilla_firmada_escaped)
        respuesta = self._soap_post(self.urls["token"], soap_body)

        # Extraer el token de la respuesta
        root = etree.fromstring(respuesta.encode("utf-8"))
        token_elem = root.find(".//{http://www.sii.cl/XMLSchema}TOKEN")
        if token_elem is None:
            token_elem = root.find(".//TOKEN")

        if token_elem is None:
            # Intentar buscar dentro de getTokenReturn que suele contener XML escapado
            return_elem = root.find(".//getTokenReturn")
            if return_elem is None:
                return_elem = root.xpath("//*[local-name()='getTokenReturn']")
                if return_elem:
                    return_elem = return_elem[0]
            if return_elem is not None and return_elem.text:
                try:
                    inner_root = etree.fromstring(return_elem.text.encode("utf-8"))
                    token_elem = inner_root.find(".//TOKEN")
                except Exception:
                    pass

        if token_elem is None or not token_elem.text:
            raise ValueError(f"No se pudo obtener el token del SII. Respuesta: {respuesta}")

        self._token = token_elem.text.strip()
        # Tokens del SII duran aprox. 1 hora, guardamos con margen de seguridad
        from datetime import timedelta
        self._token_expira = datetime.now() + timedelta(minutes=50)

        return self._token

    def enviar_dte(
        self,
        xml_envio_bytes: bytes,
        rut_empresa: str,
        dv_empresa: str,
        tipo_dte: int = 33,
    ) -> Tuple[int, str]:
        """
        Envía el XML de EnvioDTE al SII y retorna el TrackID.

        Args:
            xml_envio_bytes: XML del EnvioDTE firmado en bytes (ISO-8859-1).
            rut_empresa: RUT de la empresa (sin DV, sin guión).
            dv_empresa: Dígito verificador del RUT.
            tipo_dte: Tipo principal de DTE del envío.

        Returns:
            Tupla (track_id, mensaje) con el número de seguimiento y mensaje del SII.

        Raises:
            ValueError: Si el envío falla o el SII rechaza el documento.
        """
        # Las boletas NO se envían por aquí: viven en otra infraestructura (REST, otros
        # servidores, token propio). El antiguo ruteo a `cgi_bol/UPL/BOLUpload` era un
        # endpoint legado que ya no existe → fallaba en silencio o devolvía HTML.
        if tipo_dte in (39, 41):
            raise ValidacionError(
                f"El tipo {tipo_dte} es una boleta y no se envía por este cliente. "
                "Usar core.sii_boleta.ClienteBoletaSII (REST, token propio).",
                detalle={"tipo_dte": tipo_dte},
            )

        token = self.obtener_token()
        url = self.urls["envio_dte"]

        # Obtener el RUT de quien envía (dueño del certificado)
        rut_envia = self.certificado.rut_emisor
        if rut_envia == "SIN-RUT":
            rut_sender, dv_sender = rut_empresa, dv_empresa
        else:
            rut_sender, dv_sender = rut_envia.split("-")

        # El servlet DTEUpload EXIGE un User-Agent tipo navegador; sin él responde
        # con la página HTML genérica "HA OCURRIDO UN ERROR EN EL UPLOAD" (no da
        # TrackID). Se replica el header de LibreDTE. Ref: LibreDTE
        # SendXmlDocumentJob::uploadXml.
        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; DTE-Chile/1.0)",
            "Cookie": f"TOKEN={token}",
        }

        data = {
            "rutSender": rut_sender,
            "dvSender": dv_sender,
            "rutCompany": rut_empresa,
            "dvCompany": dv_empresa,
        }
        # Nombre de archivo con prefijo del RUT de la empresa, como hace LibreDTE
        # (`<rut_empresa>_<nombre>.xml`), y mimetype application/xml.
        filename = f"{rut_empresa}-{dv_empresa}_envio.xml"
        files = {
            "archivo": (filename, xml_envio_bytes, "application/xml"),
        }

        response = self._cli().post(url, headers=headers, data=data, files=files)
        response.raise_for_status()

        # Parsear la respuesta del SII
        respuesta_xml = response.text
        try:
            root = etree.fromstring(respuesta_xml.encode("utf-8"))
        except Exception as e:
            raise ValueError(f"La respuesta del SII no es un XML válido (puede ser una página de error HTML). Detalles: {e}. Respuesta cruda: {respuesta_xml}")


        track_elem = root.find(".//TRACKID")
        estado_elem = root.find(".//STATUS")

        track_id = int(track_elem.text) if track_elem is not None and track_elem.text else 0
        estado = estado_elem.text if estado_elem is not None else "DESCONOCIDO"

        if estado != "0":
            raise ValueError(f"El SII rechazó el envío. Estado: {estado}. Respuesta: {respuesta_xml}")

        return track_id, f"Envío exitoso. TrackID: {track_id}"

    def consultar_estado_track(self, track_id: int, rut_empresa: str, dv_empresa: str) -> dict:
        """
        Consulta el estado de procesamiento de un envío por TrackID.

        Args:
            track_id: El número de seguimiento obtenido al enviar el DTE.
            rut_empresa: RUT de la empresa (sin DV, sin guión).
            dv_empresa: Dígito verificador del RUT.

        Returns:
            Diccionario con el estado del envío.
        """
        token = self.obtener_token()

        # getEstUp en QueryEstUp.jws espera los parámetros Rut / Dv / TrackId /
        # Token (NO RutEmpresa/DvEmpresa). Ref: LibreDTE CheckXmlDocumentSentStatusJob.
        soap_body = f"""<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/">
  <soapenv:Body>
    <getEstUp>
      <Rut>{rut_empresa}</Rut>
      <Dv>{dv_empresa}</Dv>
      <TrackId>{track_id}</TrackId>
      <Token>{token}</Token>
    </getEstUp>
  </soapenv:Body>
</soapenv:Envelope>"""

        respuesta = self._soap_post(self.urls["estado_track"], soap_body)

        # La respuesta trae el XML del SII ESCAPADO dentro de <getEstUpReturn>.
        # Se des-escapa y se parsea para extraer ESTADO/GLOSA (SII:RESP_HDR).
        import html as _html
        import re as _re
        des = _html.unescape(respuesta)
        m_est = _re.search(r"<ESTADO>([^<]*)</ESTADO>", des)
        m_glosa = _re.search(r"<GLOSA>([^<]*)</GLOSA>", des)

        return {
            "track_id": track_id,
            "estado": m_est.group(1).strip() if m_est else "DESCONOCIDO",
            "glosa": m_glosa.group(1).strip() if m_glosa else "",
            "respuesta_raw": respuesta,
        }

    def solicitar_correo_estado(self, track_id: int, rut_empresa: str, dv_empresa: str) -> dict:
        """
        Pide al SII que ENVÍE POR CORREO el estado detallado de un envío (incluye
        la sección "Detalle de Rechazos y Reparos" que explica un RFR: qué firma
        —sobre/DTE/TED— falla y por qué). El correo llega a la dirección registrada
        de la empresa en el SII. Útil para diagnosticar rechazos sin el portal.

        Ref: LibreDTE RequestXmlDocumentSentStatusByEmailJob (WS wsDTECorreo,
        función reenvioCorreo).

        Args:
            track_id: TrackID del envío.
            rut_empresa: RUT de la empresa (sin DV, sin guión).
            dv_empresa: Dígito verificador.

        Returns:
            Dict con 'estado' ('0' = solicitud aceptada) y 'respuesta_raw'.
        """
        token = self.obtener_token()
        soap_body = f"""<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/">
  <soapenv:Body>
    <reenvioCorreo>
      <Token>{token}</Token>
      <RutEmpresa>{rut_empresa}</RutEmpresa>
      <DvEmpresa>{dv_empresa}</DvEmpresa>
      <TrackId>{track_id}</TrackId>
    </reenvioCorreo>
  </soapenv:Body>
</soapenv:Envelope>"""

        respuesta = self._soap_post(self.urls["estado_dte"], soap_body)
        import html as _html
        import re as _re
        des = _html.unescape(respuesta)
        m_est = _re.search(r"<(?:SII:)?ESTADO>([^<]*)</(?:SII:)?ESTADO>", des)
        return {
            "track_id": track_id,
            "estado": m_est.group(1).strip() if m_est else "DESCONOCIDO",
            "respuesta_raw": respuesta,
        }

    def consultar_estado_dte(
        self,
        rut_emisor: str,
        dv_emisor: str,
        tipo_dte: int,
        folio: int,
        fecha_emision: str,
        monto_total: int,
        rut_receptor: str,
        dv_receptor: str,
    ) -> dict:
        """
        Consulta el estado de un DTE específico por sus datos identificadores.

        Args:
            rut_emisor: RUT del emisor (sin DV, sin guión).
            dv_emisor: DV del emisor.
            tipo_dte: Tipo del DTE.
            folio: Número de folio del DTE.
            fecha_emision: Fecha de emisión en formato YYYYMMDD.
            monto_total: Monto total del DTE.
            rut_receptor: RUT del receptor (sin DV, sin guión).
            dv_receptor: DV del receptor.

        Returns:
            Diccionario con el estado del DTE.
        """
        token = self.obtener_token()

        soap_body = f"""<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/">
  <soapenv:Body>
    <getEstDte>
      <RutEmisor>{rut_emisor}</RutEmisor>
      <DvEmisor>{dv_emisor}</DvEmisor>
      <TipoDte>{tipo_dte}</TipoDte>
      <FolioDte>{folio}</FolioDte>
      <FechaEmisionDte>{fecha_emision}</FechaEmisionDte>
      <MontoDte>{monto_total}</MontoDte>
      <RutReceptor>{rut_receptor}</RutReceptor>
      <DvReceptor>{dv_receptor}</DvReceptor>
      <Token>{token}</Token>
    </getEstDte>
  </soapenv:Body>
</soapenv:Envelope>"""

        respuesta = self._soap_post(self.urls["estado_dte"], soap_body)
        root = etree.fromstring(respuesta.encode("utf-8"))

        return {
            "folio": folio,
            "tipo_dte": tipo_dte,
            "estado": (root.find(".//ESTADO") or root.find(".//estado") or etree.Element("_")).text,
            "glosa": (root.find(".//GLOSA") or root.find(".//glosa") or etree.Element("_")).text,
            "respuesta_raw": respuesta,
        }
