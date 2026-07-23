#!/usr/bin/env python3
"""Diagnóstico completo del certificado.

Uso: CERTIFICADO_PASSWORD=... .venv/bin/python diagnostico_cert2.py [ruta.pfx]
Ruta por defecto: variable de entorno DTE_CERT_PATH o "firma.pfx".
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from cryptography.x509.oid import NameOID
from core.crypto import CertificadoDigital

password = os.environ.get("CERTIFICADO_PASSWORD")
if not password:
    print("❌ Define CERTIFICADO_PASSWORD")
    sys.exit(1)

cert_path = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("DTE_CERT_PATH", "firma.pfx")
cert_data = Path(cert_path).read_bytes()
cert = CertificadoDigital(cert_data, password)

print("=== Todos los atributos del Subject ===")
for attr in cert.certificado.subject:
    print(f"  {attr.oid}: {attr.value}")

print()
print("=== Extensiones ===")
for ext in cert.certificado.extensions:
    print(f"  {ext.oid}: {ext.value}")