"""
core/negocios.py

Gestión de los NEGOCIOS (empresas) que una cuenta opera con sus certificados.

El SII no expone un listado inverso "empresas que representa este certificado"
(es dato sensible), así que el alta es por RUT — pero con **auto-relleno**: dado
un RUT, se consulta públicamente su razón social y los tipos de DTE que está
autorizado a emitir (`PortalSII.consultar_empresa_autorizada`), para que el usuario
confirme el negocio sin escribir nada más.

Modelo: una cuenta tiene certificados (core/keystore) y negocios; cada negocio se
opera con un certificado (mandatario).
"""
from typing import List, Optional

from core import database
from core.sii_portal import BASE_CERTIFICACION, BASE_PRODUCCION, PortalSII

SCHEMA_NEGOCIOS = """
CREATE TABLE IF NOT EXISTS negocios (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    cuenta_id    INTEGER NOT NULL,
    rut          TEXT NOT NULL,
    razon_social TEXT,
    cert_id      INTEGER,
    ambiente     TEXT DEFAULT 'certificacion',
    creado       TEXT NOT NULL,
    UNIQUE(cuenta_id, rut)
);
"""


# Columnas de caché del estado de habilitación (se computan consultando el SII y se
# guardan para que la lista de negocios cargue rápido, sin re-consultar cada vez).
_COLS_ESTADO = [("estado", "TEXT"), ("estado_etiqueta", "TEXT"),
                ("usa_sw_propio", "INTEGER"), ("estado_ts", "TEXT")]


def init_negocios() -> None:
    with database.get_db() as conn:
        conn.execute(SCHEMA_NEGOCIOS)
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(negocios)")}
        for col, ddl in _COLS_ESTADO:
            if col not in cols:
                conn.execute(f"ALTER TABLE negocios ADD COLUMN {col} {ddl}")


def guardar_estado(cuenta_id: int, negocio_id: int, estado: str, etiqueta: str,
                   usa_propio: bool) -> None:
    """Cachea el estado de habilitación de un negocio (tras consultarlo al SII)."""
    from datetime import datetime, timezone
    with database.get_db() as conn:
        conn.execute(
            "UPDATE negocios SET estado=?, estado_etiqueta=?, usa_sw_propio=?, estado_ts=? "
            "WHERE id=? AND cuenta_id=?",
            (estado, etiqueta, 1 if usa_propio else 0,
             datetime.now(timezone.utc).isoformat(), negocio_id, cuenta_id))


def _base(ambiente: str) -> str:
    return BASE_PRODUCCION if ambiente == "produccion" else BASE_CERTIFICACION


def info_empresa(rut: str, ambiente: str = "certificacion") -> Optional[dict]:
    """Auto-relleno: razón social + autorización DTE de un RUT (consulta pública).

    Devuelve `{rut, razon_social, autorizado, tipos:[{codigo,descripcion}]}` o None si
    el RUT no está autorizado / no existe.
    """
    portal = PortalSII(base=_base(ambiente))  # consulta pública, no requiere certificado
    emp = portal.consultar_empresa_autorizada(rut)
    if not emp:
        return None
    return {
        "rut": emp.rut,
        "razon_social": emp.razon_social,
        "resolucion": {"numero": emp.nro_resolucion, "fecha": emp.fecha_resolucion},
        "autorizado": len(emp.documentos) > 0,
        "tipos": [{"codigo": d.codigo, "descripcion": d.descripcion} for d in emp.documentos],
    }


def agregar_negocio(cuenta_id: int, rut: str, cert_id: Optional[int] = None,
                    ambiente: str = "certificacion") -> dict:
    """Agrega un negocio a la cuenta, auto-completando la razón social desde el SII.

    Raises:
        ValueError: si el RUT no está autorizado a emitir DTE (no parece un negocio válido).
    """
    from datetime import datetime, timezone
    info = info_empresa(rut, ambiente)
    if not info:
        raise ValueError(f"El RUT {rut} no aparece autorizado a emitir DTE en el SII.")
    ahora = datetime.now(timezone.utc).isoformat()
    with database.get_db() as conn:
        conn.execute(SCHEMA_NEGOCIOS)
        # SELECT-luego-UPDATE/INSERT para no dejar huecos en los ids (ver keystore).
        existente = conn.execute("SELECT id FROM negocios WHERE cuenta_id=? AND rut=?",
                                 (cuenta_id, info["rut"])).fetchone()
        if existente:
            conn.execute("UPDATE negocios SET razon_social=?, cert_id=?, ambiente=? WHERE id=?",
                         (info["razon_social"], cert_id, ambiente, existente["id"]))
            neg_id = existente["id"]
        else:
            cur = conn.execute(
                "INSERT INTO negocios (cuenta_id, rut, razon_social, cert_id, ambiente, creado) "
                "VALUES (?,?,?,?,?,?)",
                (cuenta_id, info["rut"], info["razon_social"], cert_id, ambiente, ahora))
            neg_id = cur.lastrowid
    return {"id": neg_id, "rut": info["rut"], "razon_social": info["razon_social"],
            "cert_id": cert_id, "ambiente": ambiente}


def listar_negocios(cuenta_id: int) -> List[dict]:
    init_negocios()
    filas = database.obtener_todos(
        "SELECT id, rut, razon_social, cert_id, ambiente, creado, "
        "estado, estado_etiqueta, usa_sw_propio, estado_ts FROM negocios "
        "WHERE cuenta_id=? ORDER BY id", (cuenta_id,))
    return [dict(f) for f in filas]


def eliminar_negocio(cuenta_id: int, negocio_id: int) -> bool:
    with database.get_db() as conn:
        cur = conn.execute("DELETE FROM negocios WHERE id=? AND cuenta_id=?",
                           (negocio_id, cuenta_id))
        return cur.rowcount > 0
