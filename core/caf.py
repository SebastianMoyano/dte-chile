"""
core/caf.py

Módulo de manejo del CAF (Código de Autorización de Folios).

El CAF es un archivo XML entregado por el SII que contiene:
- El rango de folios autorizados para un tipo de DTE
- La clave pública del SII para validar el CAF
- Una clave privada RSA del propio CAF que debe usarse para firmar el TED

El TED (Timbre Electrónico DTE) es un fragmento XML que va dentro de cada DTE
y que se imprime como código de barra PDF417.
"""

import base64
import hashlib
from dataclasses import dataclass
from datetime import date
from typing import Optional

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from lxml import etree

from core.xml_seguro import parse_seguro


@dataclass
class DatosCAF:
    """Datos extraídos del archivo CAF del SII."""
    tipo_dte: int
    rut_emisor: str
    rut_envia: str
    folio_desde: int
    folio_hasta: int
    fecha_autorizacion: date
    clave_privada_pem: bytes  # Clave privada RSA del CAF en formato PEM
    clave_publica_sii_b64: str  # Clave pública del SII para verificar
    xml_raw: bytes  # El XML completo del CAF para embeber en el TED


class ManejadorCAF:
    """
    Lee y procesa un archivo CAF (XML del SII).

    El CAF contiene:
    - <DA>: Datos de autorización (tipo, RUT, rango de folios, fecha)
    - <RSAPK>: Clave pública RSA del CAF (para verificar el TED)
    - <FRMA>: Firma del SII sobre los datos del CAF
    - La clave privada del CAF está en el elemento <RSASK> dentro de <IDDOC>

    IMPORTANTE: La clave privada del CAF (<RSASK>) es la que se usa para firmar
    el fragmento TED de cada DTE, NO la clave del certificado del contribuyente.
    """

    def __init__(self, xml_caf: bytes):
        """
        Args:
            xml_caf: Contenido del archivo CAF en bytes.
        """
        self.xml_raw = xml_caf
        # El CAF viene de afuera (upload) → parseo endurecido anti-XXE/billion-laughs.
        self.root = parse_seguro(xml_caf)
        self.datos = self._parsear_caf()

    @classmethod
    def desde_archivo(cls, path: str) -> "ManejadorCAF":
        """Carga el CAF desde un archivo XML en disco."""
        with open(path, "rb") as f:
            return cls(f.read())

    @classmethod
    def desde_bytes(cls, data: bytes) -> "ManejadorCAF":
        """Carga el CAF desde bytes."""
        return cls(data)

    def _parsear_caf(self) -> DatosCAF:
        """Extrae los datos del CAF y retorna un objeto DatosCAF."""
        da = self.root.find(".//DA")
        if da is None:
            raise ValueError("El XML no parece ser un CAF válido: falta el elemento <DA>")

        re_elem = da.find("RE")
        td_elem = da.find("TD")
        rng = da.find("RNG")
        fa_elem = da.find("FA")
        rsask_elem = self.root.find(".//RSASK")
        rsapk_elem = self.root.find(".//RSAPK")

        if any(e is None for e in [re_elem, td_elem, rng, fa_elem]):
            raise ValueError("El CAF está incompleto o tiene una estructura incorrecta.")

        folio_desde = int(rng.find("D").text)
        folio_hasta = int(rng.find("H").text)
        fecha_autorizacion = date.fromisoformat(fa_elem.text)

        # Extraer clave privada RSA del CAF
        if rsask_elem is None or not rsask_elem.text:
            raise ValueError("El CAF no contiene la clave privada RSASK.")

        clave_privada_pem = rsask_elem.text.strip().encode("ascii")

        # Obtener clave pública del SII (para validación, no para firmar)
        clave_publica_b64 = ""
        if rsapk_elem is not None:
            modulo = rsapk_elem.find("M")
            exponente = rsapk_elem.find("E")
            if modulo is not None and exponente is not None:
                clave_publica_b64 = f"M:{modulo.text}|E:{exponente.text}"

        return DatosCAF(
            tipo_dte=int(td_elem.text),
            rut_emisor=re_elem.text,
            rut_envia=re_elem.text,  # Mismo emisor por defecto
            folio_desde=folio_desde,
            folio_hasta=folio_hasta,
            fecha_autorizacion=fecha_autorizacion,
            clave_privada_pem=clave_privada_pem,
            clave_publica_sii_b64=clave_publica_b64,
            xml_raw=self.xml_raw,
        )

    def _cargar_clave_privada_caf(self):
        """Carga la clave privada RSA del CAF para firmar el TED."""
        pem = self.datos.clave_privada_pem
        # El CAF del SII tiene la clave privada en formato PEM sin encriptación
        try:
            return load_pem_private_key(pem, password=None)
        except Exception as e:
            raise ValueError(f"No se pudo cargar la clave privada del CAF: {e}") from e

    def es_folio_valido(self, folio: int) -> bool:
        """Verifica si un número de folio está dentro del rango autorizado por el CAF."""
        return self.datos.folio_desde <= folio <= self.datos.folio_hasta

    def generar_ted(
        self,
        folio: int,
        rut_emisor: str,
        rut_receptor: str,
        tipo_dte: int,
        fecha_emision_dte: date,
        monto_total: int,
        razon_social_receptor: str,
        primer_item: str,
    ) -> str:
        """
        Genera el Timbre Electrónico DTE (TED) en XML como string.

        El TED contiene datos mínimos del documento y la firma del CAF.
        Se imprime como PDF417 en la representación gráfica del DTE.

        Args:
            folio: Número de folio del DTE.
            rut_emisor: RUT del emisor sin puntos (ej. "12345678-9").
            rut_receptor: RUT del receptor sin puntos.
            tipo_dte: Tipo de DTE (ej. 33 para Factura Electrónica).
            fecha_emision_dte: Fecha de emisión del DTE.
            monto_total: Monto total del DTE en pesos (sin decimales).
            razon_social_receptor: Razón social del receptor del DTE.
            primer_item: Descripción/nombre del primer ítem del DTE.

        Returns:
            String XML del TED ya firmado.
        """
        if not self.es_folio_valido(folio):
            raise ValueError(
                f"El folio {folio} no está en el rango del CAF "
                f"[{self.datos.folio_desde}-{self.datos.folio_hasta}]"
            )

        # Parte firmable del TED (DD)
        dd_xml = f"""<DD>
<RE>{rut_emisor}</RE>
<TD>{tipo_dte}</TD>
<F>{folio}</F>
<FE>{fecha_emision_dte.isoformat()}</FE>
<RR>{rut_receptor}</RR>
<RSR>{razon_social_receptor[:40]}</RSR>
<MNT>{monto_total}</MNT>
<IT1>{primer_item[:40]}</IT1>
{etree.tostring(self.root.find('.//CAF'), encoding='unicode')}
<TSTED>{self._timestamp_actual()}</TSTED>
</DD>"""

        dd_elem = etree.fromstring(dd_xml)

        # Canonicalizar el DD para firmar y APLANARLO (quitar el whitespace entre
        # tags). El SII valida el FRMT sobre el DD canonicalizado y APLANADO
        # (`C14NEncodedFlattened` de LibreDTE: C14N + preg_replace('/>\s+</','><')).
        # Verificado contra la TED real de OpenFactura (aceptada por el SII vivo): su
        # FRMT SÓLO valida con el DD bare+flatten; con saltos de línea NO valida. El DD
        # va bare (sin namespace SiiDte): el timbre es un fragmento autónomo (también
        # va así en el PDF417).
        import io, re as _re
        dd_tree = etree.ElementTree(dd_elem)
        c14n_output = io.BytesIO()
        dd_tree.write_c14n(c14n_output, exclusive=False, with_comments=False)
        dd_c14n = _re.sub(rb">\s+<", b"><", c14n_output.getvalue())
        # El FRMT (timbre) se firma sobre el DD en ISO-8859-1 (Latin-1), NO en UTF-8
        # como sale de C14N. Con caracteres acentuados (á, ñ, ó) los bytes difieren
        # (ó = 0xC3 0xB3 en UTF-8 vs 0xF3 en Latin-1); firmar en UTF-8 hace que el SII
        # rechace el timbre con "(TED-2-510) Firma Timbre Electrónico Incorrecta".
        # (Ref: cryptosys.net/pki/xmldsig-ChileSII: "FRMT uses ISO-8859-1... different
        # from the XML-DSIG rules, which require UTF-8".)
        dd_c14n = dd_c14n.decode("utf-8").encode("ISO-8859-1")

        # Firmar con la clave privada del CAF usando SHA-1
        clave_privada = self._cargar_clave_privada_caf()
        firma_bytes = clave_privada.sign(
            dd_c14n,
            padding.PKCS1v15(),
            hashes.SHA1(),
        )
        firma_b64 = base64.b64encode(firma_bytes).decode("ascii")

        # Construir el TED completo. El TED queda en el namespace SiiDte (heredado
        # del Documento) — es lo que EXIGE el esquema EnvioDTE_v10.xsd (con xmlns=""
        # el XSD lo rechaza). El SII valida el FRMT canonicalizando el DD EN CONTEXTO
        # (bare, sin re-declarar namespaces), que es como lo firma el CAF; verificado
        # local: el FRMT valida con el DD in-context.
        ted_xml = f"""<TED version="1.0">
{etree.tostring(dd_elem, encoding="unicode")}
<FRMT algoritmo="SHA1withRSA">{firma_b64}</FRMT>
</TED>"""

        return ted_xml

    def _timestamp_actual(self) -> str:
        """Retorna el timestamp actual en formato ISO 8601."""
        from datetime import datetime
        return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    def folio_info(self) -> dict:
        """Retorna información del CAF como diccionario."""
        return {
            "tipo_dte": self.datos.tipo_dte,
            "rut_emisor": self.datos.rut_emisor,
            "folio_desde": self.datos.folio_desde,
            "folio_hasta": self.datos.folio_hasta,
            "fecha_autorizacion": self.datos.fecha_autorizacion.isoformat(),
        }
