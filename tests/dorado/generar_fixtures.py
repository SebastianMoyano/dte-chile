#!/usr/bin/env python3
"""Genera UNA VEZ las entradas fijas del corpus dorado: certificado ficticio y CAF ficticios
de EMPRESA DEMO SPA. Son claves inventadas (ley L14): se versionan para que la salida del
motor sea reproducible en cualquier máquina. NO volver a correr salvo que se quiera
regenerar TODO el corpus (cambian las claves → cambian todas las firmas esperadas)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from core import simulacion as sim  # noqa: E402

AQUI = Path(__file__).parent / "fixtures"


def main():
    AQUI.mkdir(parents=True, exist_ok=True)
    cert = AQUI / "cert_demo.p12"
    if cert.exists():
        print("ya existe", cert, "— no se regenera"); return
    sim._CERT = None
    # Forzar generación en memoria (no leer el fixture que aún no existe) y volcar el p12.
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives.serialization import pkcs12
    from cryptography.x509.oid import NameOID
    from datetime import datetime, timedelta, timezone
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    nombre = x509.Name([x509.NameAttribute(NameOID.COUNTRY_NAME, "CL"),
                        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "CORPUS DORADO DTE CHILE"),
                        x509.NameAttribute(NameOID.COMMON_NAME, f"ANA DEMO {sim.RUT_PERSONA_DEMO}")])
    rut_der = b"\x16" + bytes([len(sim.RUT_PERSONA_DEMO)]) + sim.RUT_PERSONA_DEMO.encode("ascii")
    ahora = datetime(2026, 1, 1, tzinfo=timezone.utc)
    c = (x509.CertificateBuilder().subject_name(nombre).issuer_name(nombre).public_key(key.public_key())
         .serial_number(1).not_valid_before(ahora).not_valid_after(ahora + timedelta(days=365 * 30))
         .add_extension(x509.SubjectAlternativeName([x509.OtherName(x509.ObjectIdentifier("1.3.6.1.4.1.8321.1"), rut_der)]), critical=False)
         .sign(key, hashes.SHA256()))
    p12 = pkcs12.serialize_key_and_certificates(b"demo", key, c, None, serialization.BestAvailableEncryption(b"demo"))
    cert.write_bytes(p12)
    print("escrito", cert)
    for t in sim.TIPOS_DEMO:
        (AQUI / f"caf_{t}.xml").write_text(sim._caf_ficticio(t, 1, 100), encoding="iso-8859-1")
        print("escrito", AQUI / f"caf_{t}.xml")


if __name__ == "__main__":
    main()
