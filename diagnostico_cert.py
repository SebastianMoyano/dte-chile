#!/usr/bin/env python3
"""Diagnóstico del certificado digital.

Uso: CERTIFICADO_PASSWORD=... .venv/bin/python diagnostico_cert.py [ruta.pfx]
Ruta por defecto: variable de entorno DTE_CERT_PATH o "firma.pfx".
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from core.crypto import CertificadoDigital

password = os.environ.get("CERTIFICADO_PASSWORD")
if not password:
    print("❌ Define CERTIFICADO_PASSWORD")
    sys.exit(1)

cert_path = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("DTE_CERT_PATH", "firma.pfx")
cert_data = Path(cert_path).read_bytes()
cert = CertificadoDigital(cert_data, password)

print("=== Subject completo ===")
print(cert.certificado.subject)
print()
print("=== RUT extraído ===")
print(cert.rut_emisor)
print()
print("=== Issuer ===")
print(cert.certificado.issuer)