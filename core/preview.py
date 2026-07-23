"""
core/preview.py — Previsualización de un DTE.

Genera un DTE **firmado + timbrado (TED) + validado contra el XSD del SII + PDF**, pero
SIN enviarlo al SII y SIN consumir folios de la BD. Es el "ver tu factura antes de emitir"
del onboarding: demuestra, con los datos reales de la empresa, que el motor produce un
documento válido.
"""
from __future__ import annotations

import base64

from lxml import etree

from core.boleta import generar_documento_boleta
from core.caf import ManejadorCAF
from core.config import settings
from core.crypto import CertificadoDigital
from core.dte import DTEInput, GeneradorDTE, calcular_totales
from core.errors import FolioError
from core.pdf_gen import generar_boleta_80mm, generar_pdf_dte
from core.resolucion import resolucion_emisor
from core.schema_validator import validar_xml_dte
from core.sobre import armar_sobre_firmado, firmar_documento_standalone

_SII_NS = "http://www.sii.cl/SiiDte"


def previsualizar_dte(dte_input: DTEInput, cert: CertificadoDigital,
                      caf: ManejadorCAF) -> dict:
    """Genera la previsualización (firma + TED + XSD + PDF) sin enviar ni consumir folios.

    Si `dte_input.folio <= 0`, usa el primer folio del CAF (solo para previsualizar; no se
    marca como usado). Devuelve totales, resultado de validación XSD, y el XML y el PDF en
    base64.
    """
    tipo = dte_input.tipo_dte.value
    if dte_input.folio <= 0:
        dte_input.folio = caf.datos.folio_desde
    if not caf.es_folio_valido(dte_input.folio):
        raise FolioError(
            f"El folio {dte_input.folio} no está en el rango del CAF "
            f"[{caf.datos.folio_desde}-{caf.datos.folio_hasta}].")

    totales = calcular_totales(dte_input.items, dte_input.tipo_dte)
    ted = caf.generar_ted(
        folio=dte_input.folio, rut_emisor=dte_input.emisor.rut,
        rut_receptor=dte_input.receptor.rut, tipo_dte=tipo,
        fecha_emision_dte=dte_input.fecha_emision, monto_total=totales.monto_total,
        razon_social_receptor=dte_input.receptor.razon_social,
        primer_item=dte_input.items[0].nombre if dte_input.items else "Sin Items")

    # Se firma por EXACTAMENTE el mismo camino que la emisión real (`core/sobre.py`): firma
    # standalone + sobre armado por string con el DTE verbatim. Si el preview firmara de otra
    # forma dejaría de ser un pre-vuelo: mostraría "válido" un XML que el SII rechazaría con
    # DTE-3-505. Las boletas además usan su propio documento y sobre.
    es_boleta = tipo in (39, 41)
    generador = GeneradorDTE()
    # Resolución POR-EMPRESA (el SII la valida por RUT; la de otra empresa da CRT-3-19).
    # Ver core/resolucion.py. El pre-vuelo debe usar la MISMA que la emisión real.
    fecha_resol, num_resol = resolucion_emisor(dte_input.emisor.rut)
    doc_elem = (generar_documento_boleta(dte_input, ted_xml=ted) if es_boleta
                else generador.generar_documento_xml(dte_input, ted_xml=ted))
    xml_doc = firmar_documento_standalone(doc_elem, cert, tipo, dte_input.folio)
    xml_envio = armar_sobre_firmado(
        documentos_firmados=[xml_doc], subtotales=[(tipo, 1)],
        rut_emisor=dte_input.emisor.rut, rut_envia=cert.rut_emisor, cert=cert,
        fecha_resolucion=fecha_resol, numero_resolucion=num_resol,
        raiz="EnvioBOLETA" if es_boleta else "EnvioDTE")
    xml_bytes = xml_doc.encode("ISO-8859-1")

    # Se valida el SOBRE completo, que es lo que realmente viaja al SII (y es lo único que
    # tiene XSD propio: un <DTE> de boleta suelto se validaría contra el esquema de factura).
    val = validar_xml_dte(xml_envio)
    pdf_bytes = (generar_boleta_80mm(dte_input, ted_xml=ted) if es_boleta
                 else generar_pdf_dte(dte_input, ted_xml=ted))

    return {
        "es_preview": True,
        "aviso": "Previsualización — NO enviada al SII, no consume folios.",
        "folio": dte_input.folio,
        "tipo_dte": tipo,
        "monto_neto": totales.monto_neto,
        "monto_exento": totales.monto_exento,
        "iva": totales.iva_monto,
        "monto_total": totales.monto_total,
        "valido_xsd": val.valido,
        "errores_xsd": val.errores,
        "xml_b64": base64.b64encode(xml_bytes).decode("ascii"),
        "pdf_b64": base64.b64encode(pdf_bytes).decode("ascii"),
    }
