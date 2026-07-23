"""
core/xml_seguro.py — Parseo de XML NO confiable de forma segura.

`lxml` con el parser por defecto **resuelve entidades** y **puede acceder a red/archivos**,
lo que expone dos ataques al parsear XML que viene de afuera (un CAF subido, el XML del
endpoint de validación, o una respuesta manipulada):

  - **XXE** (XML External Entity): `<!ENTITY x SYSTEM "file:///etc/passwd">` → leer
    archivos locales o hacer SSRF.
  - **Billion laughs**: entidades anidadas que se expanden exponencialmente → agota la RAM.

`parse_seguro()` usa un parser endurecido: sin resolución de entidades, sin red, sin DTD,
sin árboles "huge". Úsalo para TODO XML que no hayamos generado nosotros.
"""
from __future__ import annotations

from typing import Union

from lxml import etree


def _parser() -> etree.XMLParser:
    # Un parser nuevo por llamada: los parsers de lxml no son seguros de compartir entre
    # hilos, y el costo de crearlo es despreciable frente al parseo.
    return etree.XMLParser(resolve_entities=False, no_network=True,
                           load_dtd=False, huge_tree=False)


def parse_seguro(data: Union[str, bytes]) -> etree._Element:
    """Parsea XML no confiable y devuelve el elemento raíz. Anti-XXE / billion-laughs.

    Raises:
        etree.XMLSyntaxError: si el XML está mal formado (incluye entidades no resueltas).
    """
    if isinstance(data, str):
        data = data.encode("utf-8")
    return etree.fromstring(data, parser=_parser())
