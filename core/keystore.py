"""
core/keystore.py

Almacén SEGURO de credenciales del SII (certificados digitales + su clave).

Una **cuenta** (usuario de la plataforma) puede tener VARIOS certificados (p.ej. un
contador que opera para varias empresas / mandantes). Cada certificado `.p12/.pfx`
y su contraseña se guardan **cifrados en reposo** (Fernet/AES) y sólo se descifran
de forma **transitoria en memoria** cuando se usan.

Reemplaza la regla previa de "certs sólo en memoria, nunca persistir": para una
plataforma multi-empresa hay que almacenarlos, pero SIEMPRE cifrados. El .p12 en
claro y la contraseña NUNCA tocan disco sin cifrar ni se escriben en logs.

Clave maestra: `settings`/env `DTE_MASTER_KEY` (una clave Fernet urlsafe-base64 de
32 bytes). Si no está, se deriva de `jwt_secret_key` (menos ideal; se avisa). En
producción define `DTE_MASTER_KEY` en un secreto/KMS, fuera de la base de datos.

Integra con:
- `core/crypto.CertificadoDigital` (carga en memoria para firmar).
- `core/sii_portal.PortalSII` (necesita PEM en disco para mutual-TLS → se entregan
  como archivos TRANSITORIOS con permisos 600, borrados al salir del contexto).
"""

import base64
import hashlib
import os
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import List, Optional

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.serialization import (
    Encoding, NoEncryption, PrivateFormat, pkcs12,
)

from core import database
from core.config import settings
from core.errors import RecursoNoEncontrado
from core.crypto import CertificadoDigital

# Tabla de certificados cifrados por cuenta.
SCHEMA_CERTIFICADOS = """
CREATE TABLE IF NOT EXISTS certificados (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    cuenta_id     INTEGER NOT NULL,
    rut           TEXT NOT NULL,
    nombre        TEXT,
    alias         TEXT,
    vencimiento   TEXT,
    p12_cifrado   BLOB NOT NULL,
    clave_cifrada BLOB NOT NULL,
    creado        TEXT NOT NULL,
    UNIQUE(cuenta_id, rut)
);
"""


def _fernet() -> Fernet:
    """Construye el cifrador simétrico desde la clave maestra."""
    key = os.environ.get("DTE_MASTER_KEY") or getattr(settings, "master_key", None)
    if key:
        key = key.encode() if isinstance(key, str) else key
    else:
        # Derivación de respaldo desde el secreto JWT (definir DTE_MASTER_KEY en prod).
        import warnings
        warnings.warn("DTE_MASTER_KEY no definida; derivando de jwt_secret_key. "
                      "Define DTE_MASTER_KEY (clave Fernet) en producción.")
        digest = hashlib.sha256(settings.jwt_secret_key.encode()).digest()
        key = base64.urlsafe_b64encode(digest)
    return Fernet(key)


def _p12_a_pem(p12_bytes: bytes, password: str):
    """Extrae (cert_pem, key_pem) en bytes desde un .p12/.pfx (en memoria)."""
    pwd = password.encode() if password else None
    key, cert, _ = pkcs12.load_key_and_certificates(p12_bytes, pwd)
    cert_pem = cert.public_bytes(Encoding.PEM)
    key_pem = key.private_bytes(Encoding.PEM, PrivateFormat.TraditionalOpenSSL, NoEncryption())
    return cert_pem, key_pem


def init_keystore() -> None:
    """Crea la tabla de certificados si no existe."""
    with database.get_db() as conn:
        conn.execute(SCHEMA_CERTIFICADOS)


def guardar_certificado(cuenta_id: int, p12_bytes: bytes, password: str,
                        nombre: Optional[str] = None, alias: Optional[str] = None) -> dict:
    """Valida, cifra y almacena un certificado para una cuenta.

    Valida cargándolo (detecta contraseña incorrecta), extrae RUT y vencimiento, y
    guarda el .p12 y la contraseña CIFRADOS. Devuelve metadatos (sin secretos).

    Raises:
        ValueError: si el .p12 no carga (contraseña incorrecta o archivo inválido).
    """
    # Validación: carga en memoria (lanza si la clave es incorrecta).
    cert = CertificadoDigital(p12_bytes, password)
    rut = cert.rut_emisor
    vence = cert.certificado.not_valid_after_utc.isoformat() if hasattr(
        cert.certificado, "not_valid_after_utc") else cert.certificado.not_valid_after.isoformat()

    f = _fernet()
    p12_cif = f.encrypt(p12_bytes)
    clave_cif = f.encrypt(password.encode())
    ahora = datetime.now(timezone.utc).isoformat()

    with database.get_db() as conn:
        conn.execute(SCHEMA_CERTIFICADOS)
        # SELECT-luego-UPDATE/INSERT (no `ON CONFLICT`): el upsert con AUTOINCREMENT
        # consume un id en cada intento de INSERT aunque termine en UPDATE, dejando
        # huecos (1,3,...). Con el chequeo explícito los ids quedan consecutivos.
        existente = conn.execute("SELECT id FROM certificados WHERE cuenta_id=? AND rut=?",
                                 (cuenta_id, rut)).fetchone()
        if existente:
            conn.execute(
                "UPDATE certificados SET nombre=?, alias=?, vencimiento=?, p12_cifrado=?, "
                "clave_cifrada=?, creado=? WHERE id=?",
                (nombre, alias, vence, p12_cif, clave_cif, ahora, existente["id"]))
            cert_id = existente["id"]
        else:
            cur = conn.execute(
                "INSERT INTO certificados (cuenta_id, rut, nombre, alias, vencimiento, "
                "p12_cifrado, clave_cifrada, creado) VALUES (?,?,?,?,?,?,?,?)",
                (cuenta_id, rut, nombre, alias, vence, p12_cif, clave_cif, ahora))
            cert_id = cur.lastrowid
    return {"id": cert_id, "cuenta_id": cuenta_id, "rut": rut, "nombre": nombre,
            "alias": alias, "vencimiento": vence}


def listar_certificados(cuenta_id: int) -> List[dict]:
    """Metadatos de los certificados de una cuenta (SIN secretos)."""
    filas = database.obtener_todos(
        "SELECT id, rut, nombre, alias, vencimiento, creado FROM certificados "
        "WHERE cuenta_id=? ORDER BY id", (cuenta_id,))
    return [dict(f) for f in filas]


def eliminar_certificado(cuenta_id: int, cert_id: int) -> bool:
    """Borra un certificado de la cuenta. True si borró algo."""
    with database.get_db() as conn:
        cur = conn.execute("DELETE FROM certificados WHERE id=? AND cuenta_id=?",
                           (cert_id, cuenta_id))
        return cur.rowcount > 0


def _descifrar(cert_id: int, cuenta_id: Optional[int] = None):
    """Devuelve (p12_bytes, password) descifrados. Uso interno / transitorio."""
    sql = "SELECT p12_cifrado, clave_cifrada FROM certificados WHERE id=?"
    params = (cert_id,)
    if cuenta_id is not None:
        sql += " AND cuenta_id=?"; params = (cert_id, cuenta_id)
    fila = database.obtenerUno(sql, params)
    if not fila:
        raise RecursoNoEncontrado(f"Certificado {cert_id} no encontrado")
    f = _fernet()
    return f.decrypt(fila["p12_cifrado"]), f.decrypt(fila["clave_cifrada"]).decode()


def cargar_certificado(cert_id: int, cuenta_id: Optional[int] = None) -> CertificadoDigital:
    """Descifra y carga el certificado EN MEMORIA (para firmar DTE)."""
    p12, pwd = _descifrar(cert_id, cuenta_id)
    return CertificadoDigital(p12, pwd)


@contextmanager
def pem_transitorio(cert_id: int, cuenta_id: Optional[int] = None):
    """Context manager que entrega (cert_pem_path, key_pem_path) para mutual-TLS
    (p.ej. `PortalSII`). Los archivos se crean con permisos 600 y se BORRAN al salir.

    Uso:
        with pem_transitorio(cid) as (cert, key):
            portal = PortalSII(cert, key); portal.autenticar()
    """
    p12, pwd = _descifrar(cert_id, cuenta_id)
    cert_pem, key_pem = _p12_a_pem(p12, pwd)
    tmp = tempfile.mkdtemp(prefix="dte_pem_")
    cert_path = os.path.join(tmp, "cert.pem")
    key_path = os.path.join(tmp, "key.pem")
    try:
        for path, data in ((cert_path, cert_pem), (key_path, key_pem)):
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
        yield cert_path, key_path
    finally:
        for path in (cert_path, key_path):
            try:
                os.remove(path)
            except OSError:
                pass
        try:
            os.rmdir(tmp)
        except OSError:
            pass
