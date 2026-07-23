"""
core/orchestrator.py

Orquestador de procesos DTE.
Centraliza la lógica para generar, timbrar con el CAF, firmar digitalmente,
almacenar en disco y persistir en la base de datos un DTE y su envío.
"""

from __future__ import annotations

import base64
import os
from datetime import date, datetime
from pathlib import Path
from typing import Optional, Tuple

from lxml import etree

from core.caf import ManejadorCAF
from core.config import settings
from core.crypto import CertificadoDigital, firmar_xml_sii
from core.errors import (
    CertificadoError,
    ConflictoError,
    FolioError,
    SinFoliosError,
    ValidacionError,
)
from core.dte import DTEInput, GeneradorDTE, calcular_totales
from core.models import (
    consumir_folio,
    consumir_siguiente_folio,
    crear_dte,
    obtener_caf_activo,
    guardar_pdf_dte,
    actualizar_estado_dte,
)
from core.pdf_gen import generar_pdf_dte
from core.resolucion import resolucion_emisor
from core.sobre import armar_sobre_firmado, firmar_documento_standalone


class OrquestadorDTE:
    """
    Orquesta todo el flujo de emisión de un DTE.
    """

    def __init__(self):
        self.asegurar_directorios()

    def asegurar_directorios(self) -> None:
        """
        Crea las carpetas necesarias en el almacenamiento local si no existen.
        """
        storage_base = Path(settings.storage_path)
        (storage_base / "dtes").mkdir(parents=True, exist_ok=True)
        (storage_base / "pdfs").mkdir(parents=True, exist_ok=True)
        (storage_base / "cafs").mkdir(parents=True, exist_ok=True)

    def _obtener_certificado(self, certificado: Optional[CertificadoDigital] = None) -> CertificadoDigital:
        """
        Obtiene el certificado digital provisto o lo carga desde la configuración global.
        """
        if certificado is not None:
            return certificado

        if settings.certificado_path and settings.certificado_password:
            try:
                return CertificadoDigital.desde_archivo(
                    settings.certificado_path, settings.certificado_password
                )
            except Exception as e:
                raise CertificadoError(
                    f"Error al cargar el certificado digital desde el archivo configurado "
                    f"[{settings.certificado_path}]: {e}"
                )
        
        # Buscar archivo local por defecto si existe uno
        default_pfx = Path(os.environ.get("DTE_CERT_PATH", "firma.pfx"))
        if default_pfx.exists():
            try:
                # Usar password por defecto del setup
                return CertificadoDigital.desde_archivo(
                    str(default_pfx), "12345678"
                )
            except Exception:
                pass

        raise CertificadoError(
            "Certificado digital no provisto en la petición y tampoco configurado en .env "
            "(CERTIFICADO_PATH y CERTIFICADO_PASSWORD son requeridos)."
        )

    def _preparar_emision(
        self,
        dte_input: DTEInput,
        certificado: Optional[CertificadoDigital] = None,
    ) -> Tuple[CertificadoDigital, "object", str]:
        """
        Pasos previos comunes a FACTURA y BOLETA: certificado → folio (atómico) → CAF
        activo → validación de rango → totales → TED.

        Vive aquí (y no duplicado en el orquestador de boletas) porque el consumo de
        folio es atómico vía `BEGIN IMMEDIATE`: duplicar esta lógica reintroduce la
        carrera TOCTOU que ese candado evita.

        Returns:
            Tupla (certificado, totales, ted_xml). Muta `dte_input.folio` si venía en 0.
        """
        # 1. Obtener certificado digital
        cert = self._obtener_certificado(certificado)

        # 2. Asignar folio (auto o explícito)
        rut_emisor = dte_input.emisor.rut
        tipo_dte = dte_input.tipo_dte.value

        auto_folio = False
        if dte_input.folio <= 0:
            folio = consumir_siguiente_folio(rut_emisor, tipo_dte)
            if folio is None:
                raise SinFoliosError(
                    f"No hay folios disponibles para el emisor {rut_emisor} "
                    f"y tipo DTE {tipo_dte}. Verifique que el CAF esté cargado y activo.",
                    detalle={"rut_emisor": rut_emisor, "tipo_dte": tipo_dte},
                )
            dte_input.folio = folio
            auto_folio = True

        # 3. Obtener CAF activo
        caf_db = obtener_caf_activo(rut_emisor, tipo_dte)
        if not caf_db:
            raise FolioError(
                f"No se encontró un CAF activo en la base de datos para el emisor "
                f"{rut_emisor} y tipo DTE {tipo_dte}.",
                detalle={"rut_emisor": rut_emisor, "tipo_dte": tipo_dte},
            )

        caf_xml_bytes = caf_db["caf_xml"].encode("utf-8")
        caf_manejador = ManejadorCAF(caf_xml_bytes)

        # Validar rango del CAF
        if not caf_manejador.es_folio_valido(dte_input.folio):
            raise FolioError(
                f"El folio {dte_input.folio} no está en el rango autorizado por el CAF activo "
                f"[{caf_manejador.datos.folio_desde}-{caf_manejador.datos.folio_hasta}].",
                detalle={"folio": dte_input.folio, "desde": caf_manejador.datos.folio_desde,
                         "hasta": caf_manejador.datos.folio_hasta},
            )

        # 4. Consumir el folio en base de datos (solo para folio explícito)
        if not auto_folio:
            exito_consumo = consumir_folio(rut_emisor, tipo_dte, dte_input.folio)
            if not exito_consumo:
                raise ConflictoError(
                    f"No se pudo consumir el folio {dte_input.folio} en la base de datos "
                    f"(¿ya fue usado?).", detalle={"folio": dte_input.folio})

        # 5. Calcular totales
        totales = calcular_totales(dte_input.items, dte_input.tipo_dte)

        # 6. Generar el Timbre Electrónico DTE (TED) firmado por el CAF
        primer_item = dte_input.items[0].nombre if dte_input.items else "Sin Items"
        ted_xml = caf_manejador.generar_ted(
            folio=dte_input.folio,
            rut_emisor=dte_input.emisor.rut,
            rut_receptor=dte_input.receptor.rut,
            tipo_dte=tipo_dte,
            fecha_emision_dte=dte_input.fecha_emision,
            monto_total=totales.monto_total,
            razon_social_receptor=dte_input.receptor.razon_social,
            primer_item=primer_item,
        )
        return cert, totales, ted_xml

    def emitir_dte(
        self,
        dte_input: DTEInput,
        certificado: Optional[CertificadoDigital] = None,
    ) -> dict:
        """
        Orquesta el ciclo completo de generación de un DTE (FACTURA y afines).

        Para boletas (39/41) usar `core.orchestrator_boleta.OrquestadorBoleta`: su sobre,
        su estructura y su envío son distintos.

        Args:
            dte_input: Datos del DTE (puede venir con folio=0 para auto-asignar).
            certificado: El certificado digital cargado en memoria.

        Returns:
            Dict con los datos del DTE generado, rutas de archivos y XML final.
        """
        if dte_input.tipo_dte.value in (39, 41):
            raise ValidacionError(
                f"El tipo {dte_input.tipo_dte.value} es una boleta: este orquestador "
                "genera un EnvioDTE que el SII rechazaría. Usar "
                "core.orchestrator_boleta.OrquestadorBoleta.",
                detalle={"tipo_dte": dte_input.tipo_dte.value},
            )

        cert, totales, ted_xml = self._preparar_emision(dte_input, certificado)
        rut_emisor = dte_input.emisor.rut
        tipo_dte = dte_input.tipo_dte.value

        # 7. Generar el documento XML del DTE (SIN firmar todavía)
        generador = GeneradorDTE()
        SII_NS = "http://www.sii.cl/SiiDte"
        dte_xml_elem = generador.generar_documento_xml(dte_input, ted_xml=ted_xml)

        # 8. Firmar el DTE STANDALONE y armar el sobre por STRING (ver core/sobre.py).
        #    NO firmar el DTE ya embebido ni re-serializar después: el SII verifica la
        #    firma del DTE extrayéndolo como documento suelto (sin el xmlns:xsi del sobre)
        #    y cualquier reformateo posterior rompe el digest → DTE-3-505.
        #    Verificado contra el SII vivo: TrackID 253113960 → ACEPTADOS: 1.
        #    La resolución debe ser la del EMISOR (el SII la valida por RUT: la de otra
        #    empresa/ambiente da CRT-3-19). Sale por-empresa del registro del SII, con
        #    fallback al default de config. Ver core/resolucion.py.
        fecha_resol, num_resol = resolucion_emisor(dte_input.emisor.rut)
        dte_firmado_str = firmar_documento_standalone(dte_xml_elem, cert, tipo_dte,
                                                      dte_input.folio)
        xml_envio_bytes = armar_sobre_firmado(
            documentos_firmados=[dte_firmado_str],
            subtotales=[(tipo_dte, 1)],
            rut_emisor=dte_input.emisor.rut,
            rut_envia=cert.rut_emisor,
            cert=cert,
            fecha_resolucion=fecha_resol,
            numero_resolucion=num_resol,
            raiz="EnvioDTE",
        )

        # 9. Guardar el DTE firmado tal cual se firmó (esos son los bytes que valen).
        storage_base = Path(settings.storage_path)
        path_dte_xml = storage_base / "dtes" / f"DTE_{tipo_dte}_{dte_input.folio}.xml"
        xml_dte_bytes = dte_firmado_str.encode("ISO-8859-1")
        path_dte_xml.write_bytes(xml_dte_bytes)

        # 10. Generar el PDF y guardarlo en disco
        pdf_bytes = generar_pdf_dte(dte_input, ted_xml=ted_xml)
        path_dte_pdf = storage_base / "pdfs" / f"DTE_{tipo_dte}_{dte_input.folio}.pdf"
        path_dte_pdf.write_bytes(pdf_bytes)

        # 11. Guardar el EnvioDTE firmado a disco (bytes exactos que van al SII)
        path_envio_xml = storage_base / "dtes" / f"EnvioDTE_{tipo_dte}_{dte_input.folio}.xml"
        path_envio_xml.write_bytes(xml_envio_bytes)

        # 12. Persistir el DTE en la base de datos
        xml_dte_str = xml_dte_bytes.decode("ISO-8859-1")
        
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
            xml_firmado=xml_dte_str,
            ambiente=settings.sii_ambiente,
        )
        
        guardar_pdf_dte(dte_id, str(path_dte_pdf.relative_to(storage_base.parent)))

        # Retornar detalles
        xml_envio_b64 = base64.b64encode(xml_envio_bytes).decode("ascii")

        return {
            "dte_id": dte_id,
            "folio": dte_input.folio,
            "tipo_dte": tipo_dte,
            "monto_total": totales.monto_total,
            "xml_dte_path": str(path_dte_xml),
            "pdf_path": str(path_dte_pdf),
            "xml_envio_path": str(path_envio_xml),
            "xml_envio_b64": xml_envio_b64,
            "ambiente": settings.sii_ambiente,
            "mensaje": f"DTE emitido exitosamente. Folio {dte_input.folio}.",
        }


def emitir_documento(
    dte_input: DTEInput,
    certificado: Optional[CertificadoDigital] = None,
) -> dict:
    """
    Punto de entrada único de emisión: rutea al orquestador que corresponde al tipo.

    Boletas (39/41) van por EnvioBOLETA; el resto por EnvioDTE. Los llamadores (API, MCP)
    deben usar esto en vez de instanciar un orquestador a mano: elegir el equivocado
    produce un sobre que el SII rechaza.
    """
    if dte_input.tipo_dte.value in (39, 41):
        # Import local: orchestrator_boleta hereda de este módulo (evita el ciclo).
        from core.orchestrator_boleta import OrquestadorBoleta

        return OrquestadorBoleta().emitir_boleta(dte_input, certificado=certificado)
    return OrquestadorDTE().emitir_dte(dte_input, certificado=certificado)
