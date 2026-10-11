#!/usr/bin/env python3
"""Esperado para el port del cliente SII: la semilla firmada (getToken) con el certificado
ficticio del corpus. La firma RSA-SHA1 es determinista, así que el port en Go debe producir
exactamente estos bytes. Correr una vez: .venv/bin/python tests/dorado/sii/generar_esperado.py"""
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(RAIZ))
from core.crypto import CertificadoDigital  # noqa: E402
from core.sii import AmbienteSII, ClienteSII  # noqa: E402

SEMILLA = "012345678901"
cert = CertificadoDigital((RAIZ / "tests/dorado/fixtures/cert_demo.p12").read_bytes(), "demo")
cli = ClienteSII(cert, AmbienteSII.CERTIFICACION)
xml = cli._firmar_semilla(SEMILLA)
(Path(__file__).parent / "semilla.txt").write_text(SEMILLA)
(Path(__file__).parent / "semilla_firmada.xml").write_text(xml, encoding="utf-8")
print("escrito semilla_firmada.xml", len(xml), "bytes")

# Variante REST de boletas (core/sii_boleta.py::_firmar_semilla): mismo <getToken> firmado pero
# compacto (sin saltos de línea) y mandado directo como body, no escapado dentro de un SOAP.
from core.sii_boleta import ClienteBoletaSII  # noqa: E402

xml_boleta = ClienteBoletaSII(cert, AmbienteSII.CERTIFICACION)._firmar_semilla(SEMILLA)
(Path(__file__).parent / "semilla_firmada_boleta.xml").write_bytes(xml_boleta)
print("escrito semilla_firmada_boleta.xml", len(xml_boleta), "bytes")
