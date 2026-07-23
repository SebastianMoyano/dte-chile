"""
core/models.py

Modelos de datos para operaciones CRUD con la base de datos.
Funciones de acceso a datos para DTEs, CAFs, logs y usuarios.
"""

from __future__ import annotations

import json
import sqlite3
import time
from datetime import datetime
from typing import Optional

from core.database import DATABASE_PATH, ejecutar, obtener_todos, obtenerUno, get_db


# =============================================
# DTEs - Documentos Tributarios Electrónicos
# =============================================

def crear_dte(
    tipo_dte: int,
    folio: int,
    rut_emisor: str,
    rut_receptor: str,
    razon_social_receptor: str,
    fecha_emision: str,
    monto_neto: int,
    monto_exento: int,
    iva: int,
    monto_total: int,
    xml_firmado: Optional[str] = None,
    ambiente: str = "certificacion",
) -> int:
    """
    Registra un nuevo DTE en la base de datos.

    Returns:
        ID del DTE creado.
    """
    ahora = datetime.now().isoformat()
    with get_db() as conn:
        cursor = conn.execute(
            """INSERT INTO dtes
            (tipo_dte, folio, rut_emisor, rut_receptor, razon_social_receptor,
             fecha_emision, monto_neto, monto_exento, iva, monto_total,
             estado, xml_firmado, ambiente, creado_en, actualizado_en)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'generado', ?, ?, ?, ?)""",
            (tipo_dte, folio, rut_emisor, rut_receptor, razon_social_receptor,
             fecha_emision, monto_neto, monto_exento, iva, monto_total,
             xml_firmado, ambiente, ahora, ahora),
        )
        return cursor.lastrowid


def actualizar_estado_dte(dte_id: int, estado: str, track_id: Optional[int] = None) -> bool:
    """Actualiza el estado de un DTE."""
    ahora = datetime.now().isoformat()
    if track_id:
        ejecutar(
            "UPDATE dtes SET estado=?, track_id=?, actualizado_en=? WHERE id=?",
            (estado, track_id, ahora, dte_id),
        )
    else:
        ejecutar(
            "UPDATE dtes SET estado=?, actualizado_en=? WHERE id=?",
            (estado, ahora, dte_id),
        )
    return True


def obtener_dte(dte_id: int) -> Optional[dict]:
    """Obtiene un DTE por su ID."""
    row = obtenerUno("SELECT * FROM dtes WHERE id=?", (dte_id,))
    return dict(row) if row else None


def obtener_dte_por_folio(rut_emisor: str, tipo_dte: int, folio: int) -> Optional[dict]:
    """Obtiene un DTE por RUT emisor, tipo y folio."""
    row = obtenerUno(
        "SELECT * FROM dtes WHERE rut_emisor=? AND tipo_dte=? AND folio=?",
        (rut_emisor, tipo_dte, folio),
    )
    return dict(row) if row else None


def listar_dtes(
    rut_emisor: Optional[str] = None,
    tipo_dte: Optional[int] = None,
    estado: Optional[str] = None,
    fecha_desde: Optional[str] = None,
    fecha_hasta: Optional[str] = None,
    limite: int = 100,
    offset: int = 0,
) -> list[dict]:
    """Lista DTEs con filtros opcionales."""
    condiciones = []
    params = []

    if rut_emisor:
        condiciones.append("rut_emisor=?")
        params.append(rut_emisor)
    if tipo_dte:
        condiciones.append("tipo_dte=?")
        params.append(tipo_dte)
    if estado:
        condiciones.append("estado=?")
        params.append(estado)
    if fecha_desde:
        condiciones.append("fecha_emision>=?")
        params.append(fecha_desde)
    if fecha_hasta:
        condiciones.append("fecha_emision<=?")
        params.append(fecha_hasta)

    where = " AND ".join(condiciones) if condiciones else "1=1"
    params.extend([limite, offset])

    rows = obtener_todos(
        f"SELECT * FROM dtes WHERE {where} ORDER BY creado_en DESC LIMIT ? OFFSET ?",
        tuple(params),
    )
    return [dict(r) for r in rows]


def contar_dtes(
    rut_emisor: Optional[str] = None,
    tipo_dte: Optional[int] = None,
    estado: Optional[str] = None,
) -> int:
    """Cuenta DTEs con filtros opcionales."""
    condiciones = []
    params = []

    if rut_emisor:
        condiciones.append("rut_emisor=?")
        params.append(rut_emisor)
    if tipo_dte:
        condiciones.append("tipo_dte=?")
        params.append(tipo_dte)
    if estado:
        condiciones.append("estado=?")
        params.append(estado)

    where = " AND ".join(condiciones) if condiciones else "1=1"
    row = obtenerUno(f"SELECT COUNT(*) as total FROM dtes WHERE {where}", tuple(params))
    return row["total"] if row else 0


def guardar_pdf_dte(dte_id: int, pdf_path: str) -> bool:
    """Guarda la ruta del PDF generado para un DTE."""
    ahora = datetime.now().isoformat()
    ejecutar(
        "UPDATE dtes SET pdf_path=?, actualizado_en=? WHERE id=?",
        (pdf_path, ahora, dte_id),
    )
    return True


# =============================================
# CAFs - Códigos de Autorización de Folios
# =============================================

def registrar_caf(
    tipo_dte: int,
    rut_emisor: str,
    folio_desde: int,
    folio_hasta: int,
    fecha_autorizacion: str,
    caf_xml: str,
) -> int:
    """
    Registra un nuevo CAF en la base de datos.

    Returns:
        ID del CAF registrado.
    """
    ahora = datetime.now().isoformat()
    with get_db() as conn:
        cursor = conn.execute(
            """INSERT INTO cafs
            (tipo_dte, rut_emisor, folio_desde, folio_hasta, folio_siguiente,
             fecha_autorizacion, caf_xml, creado_en)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (tipo_dte, rut_emisor, folio_desde, folio_hasta, folio_desde,
             fecha_autorizacion, caf_xml, ahora),
        )
        return cursor.lastrowid


def obtener_caf_activo(rut_emisor: str, tipo_dte: int) -> Optional[dict]:
    """Obtiene el CAF activo para un emisor y tipo de DTE."""
    row = obtenerUno(
        "SELECT * FROM cafs WHERE rut_emisor=? AND tipo_dte=? AND activo=1 ORDER BY folio_desde DESC LIMIT 1",
        (rut_emisor, tipo_dte),
    )
    return dict(row) if row else None


def listar_cafs(rut_emisor: Optional[str] = None, tipo_dte: Optional[int] = None) -> list[dict]:
    """Lista todos los CAFs registrados."""
    condiciones = []
    params = []

    if rut_emisor:
        condiciones.append("rut_emisor=?")
        params.append(rut_emisor)
    if tipo_dte:
        condiciones.append("tipo_dte=?")
        params.append(tipo_dte)

    where = " AND ".join(condiciones) if condiciones else "1=1"
    rows = obtener_todos(f"SELECT * FROM cafs WHERE {where} ORDER BY creado_en DESC", tuple(params))
    return [dict(r) for r in rows]


def actualizar_folio_siguiente(caf_id: int, folio_siguiente: int) -> bool:
    """Actualiza el siguiente folio disponible en un CAF."""
    ejecutar("UPDATE cafs SET folio_siguiente=? WHERE id=?", (folio_siguiente, caf_id))
    return True


def desactivar_caf(caf_id: int) -> bool:
    """Desactiva un CAF."""
    ejecutar("UPDATE cafs SET activo=0 WHERE id=?", (caf_id,))
    return True


def obtener_siguiente_folio(rut_emisor: str, tipo_dte: int) -> Optional[int]:
    """Obtiene el siguiente folio disponible para un emisor y tipo de DTE."""
    caf = obtener_caf_activo(rut_emisor, tipo_dte)
    if not caf:
        return None
    if caf["folio_siguiente"] > caf["folio_hasta"]:
        return None
    return caf["folio_siguiente"]


def consumir_folio(rut_emisor: str, tipo_dte: int, folio: int) -> bool:
    """Marca un folio como consumido (avanza folio_siguiente)."""
    caf = obtener_caf_activo(rut_emisor, tipo_dte)
    if not caf:
        return False
    if folio < caf["folio_desde"] or folio > caf["folio_hasta"]:
        return False
    nuevo_siguiente = folio + 1
    actualizar_folio_siguiente(caf["id"], nuevo_siguiente)
    return True


def consumir_siguiente_folio(rut_emisor: str, tipo_dte: int) -> Optional[int]:
    """
    Obtiene y consume atómicamente el siguiente folio disponible para un emisor y tipo de DTE.

    Usa BEGIN IMMEDIATE en una sola transacción para evitar el race condition TOCTOU
    que ocurre cuando obtener_siguiente_folio() y consumir_folio() se ejecutan en
    transacciones separadas.

    Returns:
        El folio asignado, o None si no hay folios disponibles.
    """
    db_path = str(DATABASE_PATH)
    max_retries = 3
    retry_delay = 0.05  # 50ms

    for attempt in range(max_retries):
        try:
            conn = sqlite3.connect(db_path, isolation_level=None)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")

            try:
                conn.execute("BEGIN IMMEDIATE")

                cursor = conn.execute(
                    "SELECT id, folio_siguiente, folio_desde, folio_hasta FROM cafs "
                    "WHERE rut_emisor=? AND tipo_dte=? AND activo=1 "
                    "ORDER BY folio_desde DESC LIMIT 1",
                    (rut_emisor, tipo_dte),
                )
                row = cursor.fetchone()

                if not row:
                    conn.commit()
                    return None

                folio = row["folio_siguiente"]

                if folio > row["folio_hasta"]:
                    conn.commit()
                    return None

                conn.execute(
                    "UPDATE cafs SET folio_siguiente=? WHERE id=?",
                    (folio + 1, row["id"]),
                )

                conn.commit()
                return folio
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()
        except sqlite3.OperationalError as e:
            if "database is locked" in str(e) and attempt < max_retries - 1:
                time.sleep(retry_delay)
                continue
            raise


# =============================================
# Audit Log - Registro de auditoría
# =============================================

def registrar_log(
    accion: str,
    tipo_dte: Optional[int] = None,
    folio: Optional[int] = None,
    rut_emisor: Optional[str] = None,
    detalle: Optional[str] = None,
    ip_origen: Optional[str] = None,
) -> int:
    """Registra una acción en el log de auditoría."""
    ahora = datetime.now().isoformat()
    with get_db() as conn:
        cursor = conn.execute(
            """INSERT INTO audit_log
            (accion, tipo_dte, folio, rut_emisor, detalle, ip_origen, creado_en)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (accion, tipo_dte, folio, rut_emisor, detalle, ip_origen, ahora),
        )
        return cursor.lastrowid


def listar_logs(
    accion: Optional[str] = None,
    rut_emisor: Optional[str] = None,
    fecha_desde: Optional[str] = None,
    limite: int = 100,
) -> list[dict]:
    """Lista logs de auditoría con filtros."""
    condiciones = []
    params = []

    if accion:
        condiciones.append("accion=?")
        params.append(accion)
    if rut_emisor:
        condiciones.append("rut_emisor=?")
        params.append(rut_emisor)
    if fecha_desde:
        condiciones.append("creado_en>=?")
        params.append(fecha_desde)

    where = " AND ".join(condiciones) if condiciones else "1=1"
    params.append(limite)

    rows = obtener_todos(
        f"SELECT * FROM audit_log WHERE {where} ORDER BY creado_en DESC LIMIT ?",
        tuple(params),
    )
    return [dict(r) for r in rows]


# =============================================
# Usuarios - Autenticación
# =============================================

def crear_usuario(
    username: str,
    hashed_password: str,
    nombre_completo: Optional[str] = None,
    email: Optional[str] = None,
) -> int:
    """Crea un nuevo usuario."""
    ahora = datetime.now().isoformat()
    with get_db() as conn:
        cursor = conn.execute(
            """INSERT INTO usuarios
            (username, hashed_password, nombre_completo, email, creado_en)
            VALUES (?, ?, ?, ?, ?)""",
            (username, hashed_password, nombre_completo, email, ahora),
        )
        return cursor.lastrowid


def obtener_usuario_por_username(username: str) -> Optional[dict]:
    """Obtiene un usuario por su nombre de usuario."""
    row = obtenerUno("SELECT * FROM usuarios WHERE username=? AND activo=1", (username,))
    return dict(row) if row else None


def actualizar_ultimo_acceso(user_id: int) -> bool:
    """Actualiza la fecha del último acceso del usuario."""
    ahora = datetime.now().isoformat()
    ejecutar("UPDATE usuarios SET ultimo_acceso=? WHERE id=?", (ahora, user_id))
    return True


def listar_usuarios() -> list[dict]:
    """Lista todos los usuarios activos."""
    rows = obtener_todos("SELECT id, username, nombre_completo, email, activo, creado_en, ultimo_acceso FROM usuarios WHERE activo=1")
    return [dict(r) for r in rows]


def desactivar_usuario(user_id: int) -> bool:
    """Desactiva un usuario."""
    ejecutar("UPDATE usuarios SET activo=0 WHERE id=?", (user_id,))
    return True
