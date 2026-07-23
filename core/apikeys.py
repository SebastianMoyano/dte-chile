"""
core/apikeys.py — Llaves de API (bearer estáticas) para integraciones y agentes.

Una API key es un secreto largo aleatorio con prefijo `dte_`. Se muestra **una sola vez** al
crearla; en BD se guarda solo su **hash SHA-256** (la clave es de alta entropía, no necesita
bcrypt). Se envía como `Authorization: Bearer dte_...` — `core/auth.py::requerir_autenticacion`
acepta indistintamente un JWT o una API key válida.

Gestión (crear/listar/revocar) en `api/routes/apikeys.py` + UI `static/apikeys.html`; esos
endpoints exigen un **usuario real** (JWT), no una key, para que una key no cree más keys.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timezone
from typing import Optional, Tuple

from core import database

_PREFIJO = "dte_"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS api_keys (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre     TEXT NOT NULL,
    prefijo    TEXT NOT NULL,
    key_hash   TEXT NOT NULL UNIQUE,
    activo     INTEGER NOT NULL DEFAULT 1,
    creado     TEXT NOT NULL,
    ultimo_uso TEXT
);
"""


def _hash(clave: str) -> str:
    return hashlib.sha256(clave.encode("utf-8")).hexdigest()


def _ahora() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_api_keys() -> None:
    with database.get_db() as conn:
        conn.execute(_SCHEMA)


def crear_api_key(nombre: str) -> Tuple[str, dict]:
    """Crea una key y devuelve `(clave_en_claro, registro)`. La clave NO se puede recuperar
    después: se muestra una sola vez."""
    init_api_keys()
    clave = _PREFIJO + secrets.token_urlsafe(32)
    prefijo = clave[:12]  # "dte_" + 8 chars, para identificarla en la UI sin exponerla
    ahora = _ahora()
    with database.get_db() as conn:
        cur = conn.execute(
            "INSERT INTO api_keys (nombre, prefijo, key_hash, activo, creado) VALUES (?,?,?,1,?)",
            (nombre, prefijo, _hash(clave), ahora))
        kid = cur.lastrowid
    return clave, {"id": kid, "nombre": nombre, "prefijo": prefijo, "creado": ahora, "activo": True}


def verificar_api_key(token: str) -> Optional[dict]:
    """Si `token` es una API key válida y activa, devuelve su registro (y marca uso). Si no
    parece una key (no tiene el prefijo), devuelve None sin tocar la BD."""
    if not token or not token.startswith(_PREFIJO):
        return None
    kh = _hash(token)
    with database.get_db() as conn:
        conn.execute(_SCHEMA)
        row = conn.execute(
            "SELECT id, nombre, prefijo FROM api_keys WHERE key_hash=? AND activo=1", (kh,)).fetchone()
        if not row:
            return None
        conn.execute("UPDATE api_keys SET ultimo_uso=? WHERE id=?", (_ahora(), row["id"]))
    return dict(row)


def listar_api_keys() -> list:
    """Todas las keys (sin el hash ni la clave), para la UI."""
    init_api_keys()
    filas = database.obtener_todos(
        "SELECT id, nombre, prefijo, activo, creado, ultimo_uso FROM api_keys ORDER BY id DESC")
    return [dict(f) for f in filas]


def revocar_api_key(key_id: int) -> bool:
    with database.get_db() as conn:
        conn.execute(_SCHEMA)
        cur = conn.execute("UPDATE api_keys SET activo=0 WHERE id=?", (key_id,))
        return cur.rowcount > 0
