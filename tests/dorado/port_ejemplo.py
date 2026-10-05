#!/usr/bin/env python3
"""Port de ejemplo: muestra el contrato que debe cumplir un port del núcleo en otro lenguaje.

    <este programa> <entrada.json> <carpeta fixtures> <carpeta salida>

Entorno: RELOJ_FIJO (hora ISO a usar en todos los timestamps), DORADO_RESOLUCION_FECHA,
DORADO_RESOLUCION_NUMERO. Debe escribir en <salida>: ted.xml, dte.xml, envio.xml.

Este ejemplo reusa el motor Python, así que pasa por construcción: sirve para validar el
runner (`test_dorado.py --port`) y como referencia de qué lee y qué escribe un port real.
Un port en Go o Rust hace exactamente esto con su propio código.
"""
import json
import os
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def main() -> int:
    entrada, fixtures, salida = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    from core import reloj
    reloj.fijar(os.environ["RELOJ_FIJO"])
    from core.boleta import generar_documento_boleta
    from core.caf import ManejadorCAF
    from core.crypto import CertificadoDigital
    from core.dte import DTEInput, GeneradorDTE, calcular_totales
    from core.simulacion import EMISOR_DEMO
    from core.sobre import armar_sobre_firmado, firmar_documento_standalone

    caso = json.loads(entrada.read_text(encoding="utf-8"))
    cert = CertificadoDigital((fixtures / "cert_demo.p12").read_bytes(), "demo")
    caf = ManejadorCAF((fixtures / f"caf_{caso['tipo_dte']}.xml").read_bytes())
    dte = DTEInput(tipo_dte=caso["tipo_dte"], folio=caso["folio"], fecha_emision=date.fromisoformat(caso["fecha_emision"]),
                   emisor=EMISOR_DEMO, receptor=caso["receptor"], items=caso["items"],
                   referencias=caso.get("referencias"), forma_pago=1)
    totales = calcular_totales(dte.items, dte.tipo_dte)
    ted = caf.generar_ted(folio=dte.folio, rut_emisor=dte.emisor.rut, rut_receptor=dte.receptor.rut,
                          tipo_dte=dte.tipo_dte.value, fecha_emision_dte=dte.fecha_emision,
                          monto_total=totales.monto_total, razon_social_receptor=dte.receptor.razon_social,
                          primer_item=dte.items[0].nombre)
    es_boleta = dte.tipo_dte.value in (39, 41)
    doc = generar_documento_boleta(dte, ted_xml=ted) if es_boleta else GeneradorDTE().generar_documento_xml(dte, ted_xml=ted)
    firmado = firmar_documento_standalone(doc, cert, dte.tipo_dte.value, dte.folio)
    envio = armar_sobre_firmado(documentos_firmados=[firmado], subtotales=[(dte.tipo_dte.value, 1)],
                                rut_emisor=dte.emisor.rut, rut_envia=cert.rut_emisor, cert=cert,
                                fecha_resolucion=os.environ["DORADO_RESOLUCION_FECHA"],
                                numero_resolucion=int(os.environ["DORADO_RESOLUCION_NUMERO"]),
                                raiz="EnvioBOLETA" if es_boleta else "EnvioDTE")
    salida.mkdir(parents=True, exist_ok=True)
    (salida / "ted.xml").write_bytes(ted.encode("ISO-8859-1"))
    (salida / "dte.xml").write_bytes(firmado.encode("ISO-8859-1"))
    (salida / "envio.xml").write_bytes(envio)
    return 0


if __name__ == "__main__":
    sys.exit(main())
