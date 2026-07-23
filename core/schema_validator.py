"""core/schema_validator.py — Validación de XML DTE contra esquemas XSD del SII."""

from pathlib import Path
from typing import List, Optional

from lxml import etree
from pydantic import BaseModel

from core.xml_seguro import parse_seguro

_XSD_DIR = Path(__file__).parent / "xsd"
_schema_cache: dict = {}

# Cada tipo de raíz se valida contra su esquema oficial.
_XSD_POR_TIPO = {
    "EnvioBOLETA": "EnvioBOLETA_v11.xsd",
    "ConsumoFolios": "ConsumoFolio_v10.xsd",  # RVD / consumo de folios de boletas
    "EnvioDTE": "EnvioDTE_v10.xsd",
    "DTE": "EnvioDTE_v10.xsd",
}


class ValidationResult(BaseModel):
    """Resultado de la validación de un XML contra el esquema XSD del SII."""
    valido: bool
    errores: List[str]
    tipo_xml: str


def _cargar_schema(tipo_xml: str = "EnvioDTE") -> etree.XMLSchema:
    """Carga (y cachea) el esquema XSD que corresponde al tipo de raíz."""
    archivo = _XSD_POR_TIPO.get(tipo_xml, "EnvioDTE_v10.xsd")
    if archivo not in _schema_cache:
        _schema_cache[archivo] = etree.XMLSchema(etree.parse(str(_XSD_DIR / archivo)))
    return _schema_cache[archivo]


def _detectar_tipo_xml(root: etree._Element) -> str:
    """Detecta el tipo de documento según el nombre local del elemento raíz."""
    local = etree.QName(root.tag).localname
    if local in _XSD_POR_TIPO:
        return local
    return "desconocido"


def validar_xml_dte(xml_bytes: bytes) -> ValidationResult:
    """
    Valida un XML (ISO-8859-1 o UTF-8) contra el esquema XSD oficial del SII.

    Args:
        xml_bytes: Contenido del XML en bytes (ISO-8859-1 o UTF-8).

    Returns:
        ValidationResult con el resultado de la validación.
    """
    try:
        root = parse_seguro(xml_bytes)  # XML no confiable → parser endurecido
    except etree.XMLSyntaxError as e:
        return ValidationResult(
            valido=False,
            errores=[f"Error de sintaxis XML: {e}"],
            tipo_xml="desconocido",
        )

    tipo_xml = _detectar_tipo_xml(root)
    schema = _cargar_schema(tipo_xml)

    try:
        schema.assertValid(root)
        return ValidationResult(valido=True, errores=[], tipo_xml=tipo_xml)
    except etree.DocumentInvalid:
        # Extraer todos los errores del log de validación
        errores = [
            f"Línea {e.line}: {e.message}"
            for e in schema.error_log
        ]
        return ValidationResult(valido=False, errores=errores, tipo_xml=tipo_xml)


def validar_xml_dte_strict(xml_bytes: bytes) -> None:
    """
    Valida el XML contra el esquema XSD del SII. Lanza ValueError si es inválido.

    Args:
        xml_bytes: Contenido del XML en bytes.

    Raises:
        ValueError: Si el XML no cumple con el esquema XSD.
    """
    result = validar_xml_dte(xml_bytes)
    if not result.valido:
        raise ValueError(
            f"XML no válido según esquema XSD del SII: {' | '.join(result.errores)}"
        )
