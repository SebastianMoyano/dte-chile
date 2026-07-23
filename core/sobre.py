"""
core/sobre.py — Armado y firma del sobre (EnvioDTE / EnvioBOLETA) que el SII ACEPTA.

Este módulo existe por una razón concreta y cara: **firmar el DTE ya embebido en el sobre
y re-serializar después NO funciona**. El SII responde `(DTE-3-505) Firma DTE Incorrecta`.

Por qué (verificado contra el SII vivo, TrackID 253113960 → ACEPTADOS: 1):

  1. El SII verifica la firma del DTE **extrayéndolo como documento independiente**, sin el
     `xmlns:xsi` que el sobre declara en su raíz. Si el DTE se firma ya embebido, ese
     `xmlns:xsi` entra al C14N del `<Documento>` y el SII recomputa otro digest → 505.
     ⇒ El DTE se firma **STANDALONE**, en su propio árbol.

  2. Después de firmar, **los bytes no se pueden tocar**. Re-parsear o re-serializar el DTE
     firmado cambia su serialización (namespaces, orden) y rompe el digest.
     ⇒ El sobre se arma **concatenando STRINGS**, con el DTE firmado insertado VERBATIM.

Referencia: cryptosys.net/pki/xmldsig-ChileSII — *"no xmlns attributes in the individual DTE
when signed"* + *"do not reformat after signing"*. Es el mismo enfoque de LibreDTE
(`EnvioDte.php` arma el sobre con `str_replace`, no con un append de árbol).
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Sequence

from lxml import etree

from core.crypto import CertificadoDigital, firmar_xml_sii

_DS = "http://www.w3.org/2000/09/xmldsig#"

RUT_SII = "60803000-K"  # receptor del sobre: siempre el SII

_RAIZ = {
    "EnvioDTE": ("EnvioDTE", "EnvioDTE_v10.xsd"),
    "EnvioBOLETA": ("EnvioBOLETA", "EnvioBOLETA_v11.xsd"),
}


def firmar_documento_standalone(doc_elem: etree._Element, cert: CertificadoDigital,
                                tipo_dte: int, folio: int) -> str:
    """Firma un `<DTE>` como documento INDEPENDIENTE y devuelve su XML exacto (string).

    El `uri` apunta al ID real del `<Documento>` (`T{tipo}F{folio}`). El string devuelto es
    lo que debe insertarse VERBATIM en el sobre: no re-parsearlo ni re-serializarlo.
    """
    # Árbol propio: sin el xmlns:xsi del sobre en alcance (ver docstring del módulo).
    std = etree.fromstring(etree.tostring(doc_elem, encoding="ISO-8859-1"))
    firmar_xml_sii(std, cert, uri=f"#T{tipo_dte}F{folio}")
    return etree.tostring(std, encoding="unicode")


def _caratula(rut_emisor: str, rut_envia: str, fecha_resolucion: str,
              numero_resolucion: int, subtotales: Sequence[tuple[int, int]]) -> str:
    sub = "".join(f"<SubTotDTE><TpoDTE>{t}</TpoDTE><NroDTE>{n}</NroDTE></SubTotDTE>"
                  for t, n in subtotales)
    ts = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    return (f'<Caratula version="1.0"><RutEmisor>{rut_emisor}</RutEmisor>'
            f'<RutEnvia>{rut_envia}</RutEnvia><RutReceptor>{RUT_SII}</RutReceptor>'
            f'<FchResol>{fecha_resolucion}</FchResol><NroResol>{numero_resolucion}</NroResol>'
            f'<TmstFirmaEnv>{ts}</TmstFirmaEnv>{sub}</Caratula>')


def armar_sobre_firmado(documentos_firmados: List[str], subtotales: Sequence[tuple[int, int]],
                        rut_emisor: str, rut_envia: str, cert: CertificadoDigital,
                        fecha_resolucion: str, numero_resolucion: int,
                        raiz: str = "EnvioDTE") -> bytes:
    """Arma el sobre por STRING con los DTE ya firmados insertados VERBATIM, y lo firma.

    Args:
        documentos_firmados: XML de cada DTE **ya firmado** (de `firmar_documento_standalone`).
        subtotales: [(tipo_dte, cantidad), ...] para la carátula.
        raiz: "EnvioDTE" (facturas) o "EnvioBOLETA" (boletas 39/41).

    Returns:
        Los bytes finales en ISO-8859-1, listos para enviar al SII.
    """
    tag, xsd = _RAIZ[raiz]
    car = _caratula(rut_emisor, rut_envia, fecha_resolucion, numero_resolucion, subtotales)
    envio_str = (
        f'<{tag} xmlns="http://www.sii.cl/SiiDte" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        f'xsi:schemaLocation="http://www.sii.cl/SiiDte {xsd}" version="1.0">'
        f'<SetDTE ID="SetDoc">{car}{"".join(documentos_firmados)}</SetDTE></{tag}>'
    )

    # La firma del SOBRE se calcula parseando (solo lectura) y se inserta por STRING, para
    # no re-serializar los DTE internos ya firmados.
    # Se parsea el `str` (no bytes): `envio_str` no lleva declaración de encoding, así que
    # al pasarlo como bytes ISO-8859-1 lxml asumiría UTF-8 y reventaría con cualquier
    # acento ("Morandé") — `Invalid bytes in character encoding`.
    parsed = etree.fromstring(envio_str)
    firmar_xml_sii(parsed, cert, uri="#SetDoc")
    sig = etree.tostring(parsed.findall(f"{{{_DS}}}Signature")[-1], encoding="unicode")

    cierre = f"</{tag}>"
    final = envio_str[: -len(cierre)] + sig + cierre
    return b'<?xml version="1.0" encoding="ISO-8859-1"?>\n' + final.encode("ISO-8859-1")
