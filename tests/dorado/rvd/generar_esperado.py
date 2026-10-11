#!/usr/bin/env python3
"""Esperado para el port del RVD (Registro de Ventas Diario / ConsumoFolios) a Go: con el
certificado ficticio del corpus, boletas ficticias y hora fija, el ConsumoFolios sin firmar y
firmado deben salir byte a byte iguales desde Go (`nucleo/rvd`). Correr una vez:
.venv/bin/python tests/dorado/rvd/generar_esperado.py  (L15: no regenerar para que un test pase)."""
import json
import sys
from datetime import date
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(RAIZ))
from lxml import etree  # noqa: E402

from core import reloj  # noqa: E402
from core.crypto import CertificadoDigital, firmar_xml_sii  # noqa: E402
from core.rvd import generar_consumo_folios  # noqa: E402
from core.schema_validator import validar_xml_dte_strict  # noqa: E402

AQUI = Path(__file__).parent
NS = "http://www.sii.cl/SiiDte"
ENTRADA = {
    "rut_emisor": "77777777-7", "rut_envia": "12345678-5", "fecha_resolucion": "2026-01-01",
    "numero_resolucion": 0, "dia": "2026-01-23", "tipos": [39, 41, 61], "sec_envio": 1,
    "marca": "2026-01-24T08:00:00",
    "documentos": [
        {"tipo_dte": 39, "folio": 1, "monto_neto": 1000, "iva": 190, "monto_exento": 0, "monto_total": 1190, "estado": "aceptado"},
        {"tipo_dte": 39, "folio": 2, "monto_neto": 2000, "iva": 380, "monto_exento": 0, "monto_total": 2380, "estado": "enviado"},
        {"tipo_dte": 39, "folio": 3, "monto_neto": 0, "iva": 0, "monto_exento": 0, "monto_total": 0, "estado": "anulado"},
        {"tipo_dte": 39, "folio": 5, "monto_neto": 500, "iva": 95, "monto_exento": 0, "monto_total": 595, "estado": "generado"},
        {"tipo_dte": 41, "folio": 1, "monto_neto": 0, "iva": 0, "monto_exento": 5000, "monto_total": 5000, "estado": "aceptado"},
        {"tipo_dte": 41, "folio": 2, "monto_neto": 0, "iva": 0, "monto_exento": 0, "monto_total": 0, "estado": "anulado"},
        {"tipo_dte": 41, "folio": 3, "monto_neto": 0, "iva": 0, "monto_exento": 0, "monto_total": 0, "estado": "anulado"},
        {"tipo_dte": 41, "folio": 7, "monto_neto": 0, "iva": 0, "monto_exento": 1200, "monto_total": 1200, "estado": "aceptado"},
    ],
}


def main():
    reloj.fijar(ENTRADA["marca"])
    cert = CertificadoDigital((RAIZ / "tests/dorado/fixtures/cert_demo.p12").read_bytes(), "demo")
    raiz = generar_consumo_folios(
        rut_emisor=ENTRADA["rut_emisor"], rut_envia=ENTRADA["rut_envia"], documentos=ENTRADA["documentos"],
        fecha_resolucion=ENTRADA["fecha_resolucion"], numero_resolucion=ENTRADA["numero_resolucion"],
        dia=date.fromisoformat(ENTRADA["dia"]), tipos=tuple(ENTRADA["tipos"]), sec_envio=ENTRADA["sec_envio"])
    sin_firma = etree.tostring(raiz, encoding="ISO-8859-1")
    # Mismos pasos que core/rvd.py::generar_rvd_firmado (normalizar, firmar #ID, declaración con comillas dobles).
    raiz = etree.fromstring(sin_firma)
    id_doc = raiz.find(f".//{{{NS}}}DocumentoConsumoFolios").get("ID")
    firmado = firmar_xml_sii(raiz, cert, uri=f"#{id_doc}")
    xml = b'<?xml version="1.0" encoding="ISO-8859-1"?>\n' + etree.tostring(firmado, encoding="ISO-8859-1", xml_declaration=False)
    validar_xml_dte_strict(xml)
    (AQUI / "entrada.json").write_text(json.dumps(ENTRADA, ensure_ascii=False, indent=1), encoding="utf-8")
    (AQUI / "consumo_sin_firma.xml").write_bytes(sin_firma)
    (AQUI / "consumo_firmado.xml").write_bytes(xml)
    print("escrito", len(sin_firma), "y", len(xml), "bytes")


if __name__ == "__main__":
    main()
