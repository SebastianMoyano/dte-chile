"""
core/orchestrator_boleta.py — Orquestador de emisión de BOLETAS (39/41).

Hermano de `core/orchestrator.py`, que es el camino de FACTURAS. Existe aparte porque la
boleta difiere en todo lo que viene después del TED:

  - Sobre **EnvioBOLETA** (no EnvioDTE) y estructura propia (`core/boleta.py`).
  - **NroResol = 0** en certificación (la factura usa el 80 de la resolución).
  - PDF de **80mm** (rollo térmico) en vez de la carta.
  - Envío por **REST a otros servidores y con token propio** (`core/sii_boleta.py`).

Lo que SÍ comparte —certificado, folio atómico, CAF, TED— se hereda de `OrquestadorDTE`
vía `_preparar_emision`, para no duplicar el consumo de folio (que es atómico por diseño).
"""
from __future__ import annotations

import base64
from pathlib import Path
from typing import Optional

from lxml import etree

from core.boleta import generar_documento_boleta
from core.config import settings
from core.crypto import CertificadoDigital
from core.dte import DTEInput
from core.errors import ValidacionError
from core.models import crear_dte, guardar_pdf_dte
from core.orchestrator import OrquestadorDTE
from core.pdf_gen import generar_boleta_80mm
from core.schema_validator import validar_xml_dte_strict
from core.resolucion import resolucion_emisor
from core.sobre import armar_sobre_firmado, firmar_documento_standalone

TIPOS_BOLETA = (39, 41)


class OrquestadorBoleta(OrquestadorDTE):
    """Orquesta la emisión completa de una boleta electrónica (39/41)."""

    def emitir_boleta(
        self,
        dte_input: DTEInput,
        certificado: Optional[CertificadoDigital] = None,
        ind_servicio: Optional[int] = None,
        razon_referencia: Optional[str] = None,
        cod_referencia: Optional[str] = None,
    ) -> dict:
        """
        Genera una boleta: folio → TED → EnvioBOLETA → firma → XSD → PDF 80mm → BD.

        NO la envía al SII (eso es `core.sii_boleta.ClienteBoletaSII.enviar_boletas`, que
        además permite agrupar hasta 500 boletas en un solo sobre).

        Args:
            dte_input: Datos de la boleta (folio=0 para auto-asignar).
            certificado: Certificado digital en memoria.
            ind_servicio: IndServicio (1-4). Por defecto 3 (ventas y servicios).

        Returns:
            Dict con el folio, rutas de los archivos y el sobre en base64.
        """
        tipo_dte = dte_input.tipo_dte.value
        if tipo_dte not in TIPOS_BOLETA:
            raise ValidacionError(
                f"El tipo {tipo_dte} no es una boleta. Usar OrquestadorDTE.emitir_dte.",
                detalle={"tipo_dte": tipo_dte},
            )

        # 1-6. Certificado, folio (atómico), CAF, rango, totales y TED — compartido.
        cert, totales, ted_xml = self._preparar_emision(dte_input, certificado)
        rut_emisor = dte_input.emisor.rut

        # 7. Documento de boleta SIN firmar (IdDoc con IndServicio y sin FmaPago; Emisor
        #    con RznSocEmisor/GiroEmisor — el SII rechaza los nombres de factura aquí).
        doc_elem = generar_documento_boleta(dte_input, ted_xml=ted_xml, ind_servicio=ind_servicio,
                                            razon_referencia=razon_referencia,
                                            cod_referencia=cod_referencia)

        # 8-9. Firmar el DTE STANDALONE y armar el sobre por STRING — mismo método que
        #      facturas, verificado contra el SII vivo (TrackID 253113960 → ACEPTADOS: 1).
        #      NO firmar embebido ni re-serializar después: rompe el digest → DTE-3-505.
        #      Ver core/sobre.py. La resolución sale POR-EMPRESA del registro del SII (el
        #      SII la valida por RUT: usar la de otra empresa da CRT-3-19, verificado en vivo).
        #      Ver core/resolucion.py.
        fecha_resol, num_resol = resolucion_emisor(rut_emisor)
        doc_firmado_str = firmar_documento_standalone(doc_elem, cert, tipo_dte, dte_input.folio)
        xml_envio_bytes = armar_sobre_firmado(
            documentos_firmados=[doc_firmado_str],
            subtotales=[(tipo_dte, 1)],
            rut_emisor=rut_emisor,
            rut_envia=cert.rut_emisor,
            cert=cert,
            fecha_resolucion=fecha_resol,
            numero_resolucion=num_resol,
            raiz="EnvioBOLETA",
        )

        # 10. Validar contra el XSD oficial ANTES de tocar disco: un tag fuera de orden lo
        #     rechaza el SII, y es mucho más barato detectarlo aquí.
        validar_xml_dte_strict(xml_envio_bytes)

        # 11. Guardar el documento (bytes exactos que se firmaron) y el sobre.
        storage_base = Path(settings.storage_path)
        xml_doc_bytes = doc_firmado_str.encode("ISO-8859-1")
        path_xml = storage_base / "dtes" / f"BOLETA_{tipo_dte}_{dte_input.folio}.xml"
        path_xml.write_bytes(xml_doc_bytes)
        path_envio = storage_base / "dtes" / f"EnvioBOLETA_{tipo_dte}_{dte_input.folio}.xml"
        path_envio.write_bytes(xml_envio_bytes)

        # 12. PDF 80mm (rollo térmico).
        path_pdf = storage_base / "pdfs" / f"BOLETA_{tipo_dte}_{dte_input.folio}.pdf"
        path_pdf.write_bytes(generar_boleta_80mm(dte_input, ted_xml=ted_xml))

        # 13. Persistir.
        dte_id = crear_dte(
            tipo_dte=tipo_dte,
            folio=dte_input.folio,
            rut_emisor=rut_emisor,
            rut_receptor=dte_input.receptor.rut,
            razon_social_receptor=dte_input.receptor.razon_social,
            fecha_emision=dte_input.fecha_emision.isoformat(),
            monto_neto=totales.monto_neto,
            monto_exento=totales.monto_exento,
            iva=totales.iva_monto,
            monto_total=totales.monto_total,
            xml_firmado=xml_doc_bytes.decode("ISO-8859-1"),
            ambiente=settings.sii_ambiente,
        )
        guardar_pdf_dte(dte_id, str(path_pdf.relative_to(storage_base.parent)))

        return {
            "dte_id": dte_id,
            "folio": dte_input.folio,
            "tipo_dte": tipo_dte,
            "monto_total": totales.monto_total,
            "xml_dte_path": str(path_xml),
            "pdf_path": str(path_pdf),
            "xml_envio_path": str(path_envio),
            "xml_envio_b64": base64.b64encode(xml_envio_bytes).decode("ascii"),
            "ambiente": settings.sii_ambiente,
            "mensaje": f"Boleta emitida. Folio {dte_input.folio}.",
        }
