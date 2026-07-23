#!/usr/bin/env python3
"""Genera un CAF T61 (Nota de Crédito) FICTICIO para pruebas locales sin red.

La firma del CAF (`FRMA`) es un placeholder, no una firma real del SII: sirve
solo para ejercitar el pipeline local (parseo, TED), no para timbrar ante el SII.

Uso: .venv/bin/python crear_caf_mock_61.py [--rut RUT] [--razon-social RS]
"""
import argparse
import os
import sys
import base64
from datetime import date
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization

sys.path.insert(0, str(Path(__file__).parent))
from core.config import settings

def generar_clave_y_datos_rsa() -> tuple[str, str, str]:
    """Genera una clave RSA privada de 1024 bits y retorna la clave PEM, el módulo y el exponente en base64."""
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=1024
    )
    # Clave privada en formato PEM tradicional (PKCS#1) sin cifrar
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption()
    )
    
    pn = private_key.public_key().public_numbers()
    
    # Modulus (M)
    m_bytes = pn.n.to_bytes((pn.n.bit_length() + 7) // 8, byteorder='big')
    m_b64 = base64.b64encode(m_bytes).decode('ascii')
    
    # Exponent (E)
    e_bytes = pn.e.to_bytes((pn.e.bit_length() + 7) // 8, byteorder='big')
    e_b64 = base64.b64encode(e_bytes).decode('ascii')
    
    return pem.decode("ascii"), m_b64, e_b64

def crear_xml_caf_ficticio(
    rut_emisor: str, razon_social: str, tipo_dte: int, folio_desde: int, folio_hasta: int
) -> str:
    priv_key_pem, m_b64, e_b64 = generar_clave_y_datos_rsa()

    xml = f"""<?xml version="1.0" encoding="ISO-8859-1"?>
<AUTORIZACION>
  <CAF version="1.0">
    <DA>
      <RE>{rut_emisor}</RE>
      <RS>{razon_social}</RS>
      <TD>{tipo_dte}</TD>
      <RNG>
        <D>{folio_desde}</D>
        <H>{folio_hasta}</H>
      </RNG>
      <FA>{date.today().isoformat()}</FA>
      <RSAPK>
        <M>{m_b64}</M>
        <E>{e_b64}</E>
      </RSAPK>
    </DA>
    <FRMA algoritmo="SHA1withRSA">FIRMA_SII_PLACEHOLDER</FRMA>
  </CAF>
  <RSASK>
{priv_key_pem}  </RSASK>
</AUTORIZACION>
"""
    return xml

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--rut", default="76111111-6", help="RUT del emisor, con guión y DV")
    p.add_argument("--razon-social", default="EMPRESA DEMO SPA", help="Razón social del emisor")
    args = p.parse_args()

    rut_emisor = args.rut
    tipo_dte = 61  # Nota de Crédito
    folio_desde = 1
    folio_hasta = 100

    xml_content = crear_xml_caf_ficticio(
        rut_emisor, args.razon_social, tipo_dte, folio_desde, folio_hasta
    )

    out_dir = settings.storage_dir / "cafs"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"FoliosSII{rut_emisor.replace('-', '')}{tipo_dte}12026.xml"

    out_path.write_text(xml_content, encoding="iso-8859-1")

    print(f"✓ Mock CAF para DTE {tipo_dte} generado en: {out_path}")

if __name__ == "__main__":
    main()
