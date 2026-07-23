"""
rotar_claves.py — Endurece/rota los secretos SIN orfanar los certificados del keystore.

El keystore cifra los .p12 con `DTE_MASTER_KEY` (o, si falta, una clave derivada del
`JWT_SECRET_KEY`). Cambiar cualquiera de esas claves dejaría los certs guardados
imposibles de descifrar. Este script hace la migración segura:

  1. Descifra TODOS los certs con la clave ACTUAL (en memoria).
  2. Genera `JWT_SECRET_KEY` y `DTE_MASTER_KEY` nuevos y fuertes.
  3. Re-cifra los certs con la clave nueva y actualiza la BD.
  4. Escribe los secretos nuevos en el `.env` y restringe `CORS_ORIGINS` a localhost.
  5. Resetea la contraseña de `admin` a una aleatoria (o la de `ADMIN_PASSWORD`).
  6. Verifica que los certs se descifren con la clave nueva.

Si algo falla ANTES del paso 3, no toca nada. Haz backup de `dte_database.db` y `.env`
antes (el flujo del proyecto ya lo hace).

Uso:  .venv/bin/python rotar_claves.py
"""
from __future__ import annotations

import os
import re
import secrets
import sys
from pathlib import Path

from cryptography.fernet import Fernet

from core import database
from core.auth import hash_password
from core.crypto import CertificadoDigital


def _to_bytes(v) -> bytes:
    return v if isinstance(v, (bytes, bytearray)) else str(v).encode()


def main() -> int:
    from core.keystore import _fernet  # cifrador ACTUAL (derivado o DTE_MASTER_KEY vigente)

    # 1) Descifrar todos los certs con la clave actual (aborta si alguno falla).
    old = _fernet()
    filas = database.obtener_todos(
        "SELECT id, rut, p12_cifrado, clave_cifrada FROM certificados")
    plano: list[tuple[int, str, bytes, bytes]] = []
    for r in filas:
        d = dict(r)
        try:
            p12 = old.decrypt(_to_bytes(d["p12_cifrado"]))
            clave = old.decrypt(_to_bytes(d["clave_cifrada"]))
        except Exception as e:
            print(f"❌ No se pudo descifrar el cert id={d['id']} ({d['rut']}): {e}")
            print("   Abortado — NO se cambió nada.")
            return 1
        plano.append((d["id"], d["rut"], p12, clave))
    print(f"✓ Descifrados {len(plano)} certificado(s) con la clave actual.")

    # 2) Secretos nuevos.
    nuevo_jwt = secrets.token_urlsafe(48)
    nuevo_master = Fernet.generate_key().decode()
    nuevo = Fernet(nuevo_master.encode())

    # 3) Re-cifrar y actualizar la BD.
    for cid, _rut, p12, clave in plano:
        database.ejecutar(
            "UPDATE certificados SET p12_cifrado=?, clave_cifrada=? WHERE id=?",
            (nuevo.encrypt(p12), nuevo.encrypt(clave), cid))
    print(f"✓ Re-cifrados {len(plano)} certificado(s) con la clave nueva.")

    # 4) Escribir .env (JWT, MASTER, CORS).
    env = Path(".env")
    t = env.read_text(encoding="utf-8")
    reemplazos = {
        "JWT_SECRET_KEY": nuevo_jwt,
        "DTE_MASTER_KEY": nuevo_master,
        "CORS_ORIGINS": "http://localhost:8000,http://127.0.0.1:8000",
    }
    for clave_env, valor in reemplazos.items():
        if re.search(rf"(?m)^{clave_env}=", t):
            t = re.sub(rf"(?m)^{clave_env}=.*$", f"{clave_env}={valor}", t)
        else:
            t += f"\n{clave_env}={valor}\n"
    env.write_text(t, encoding="utf-8")
    print("✓ .env actualizado (JWT_SECRET_KEY, DTE_MASTER_KEY, CORS_ORIGINS).")

    # 5) Resetear la contraseña de admin.
    admin_pwd = os.environ.get("ADMIN_PASSWORD") or secrets.token_urlsafe(12)
    database.ejecutar("UPDATE usuarios SET hashed_password=? WHERE username='admin'",
                      (hash_password(admin_pwd),))
    print("✓ Contraseña de admin reseteada.")

    # 6) Verificar que los certs se descifren con la clave nueva.
    os.environ["DTE_MASTER_KEY"] = nuevo_master  # que _fernet use la nueva ya
    from core import keystore as ks
    for cid, rut, _p12, _clave in plano:
        try:
            cert: CertificadoDigital = ks.cargar_certificado(cid)
            assert cert.rut_emisor, "sin RUT"
        except Exception as e:
            print(f"❌ VERIFICACIÓN falló para cert id={cid} ({rut}): {e}")
            return 2
    print(f"✓ Verificado: los {len(plano)} certificado(s) se descifran con la clave nueva.")

    print("\n" + "=" * 60)
    print("ENDURECIMIENTO COMPLETO")
    print("=" * 60)
    print(f"  Contraseña de admin (guárdala, se muestra 1 vez): {admin_pwd}")
    print("  JWT y master key nuevos escritos en .env (los tokens viejos ya no valen).")
    print("  Reinicia el servidor para tomar el nuevo .env.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
