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
                ("usa_sw_propio", "INTEGER"), ("estado_ts", "TEXT"),
                # Nombre con que ESTE motor registró/postuló el software de la empresa en el SII.
                # Lo escribe la postulación automática; sirve para reconocer "emite con nosotros"
                # frente a "emite con otro proveedor" sin que nadie lo configure a mano.
                ("software_registrado", "TEXT")]

# Datos fijos del emisor que van en la carátula de cada DTE (antes vivían en EMPRESA_* del .env,
# uno solo para todo el motor). Ahora cada negocio tiene los suyos y la app los pide en
# "Mi empresa"; `settings.empresa_*` queda como valor por defecto para instalaciones viejas.
CAMPOS_DATOS = ["razon_social", "giro", "codigo_actividad", "direccion", "comuna", "ciudad", "email", "telefono"]
_COLS_DATOS = [("giro", "TEXT"), ("codigo_actividad", "INTEGER"), ("direccion", "TEXT"),
               ("comuna", "TEXT"), ("ciudad", "TEXT"), ("email", "TEXT"), ("telefono", "TEXT")]


def init_negocios() -> None:
    with database.get_db() as conn:
        conn.execute(SCHEMA_NEGOCIOS)
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(negocios)")}
        for col, ddl in _COLS_ESTADO + _COLS_DATOS:
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
        "estado, estado_etiqueta, usa_sw_propio, estado_ts, "
        "giro, codigo_actividad, direccion, comuna, ciudad, email, telefono FROM negocios "
        "WHERE cuenta_id=? ORDER BY id", (cuenta_id,))
    return [dict(f) for f in filas]


def actualizar_datos(cuenta_id: int, negocio_id: int, datos: dict) -> Optional[dict]:
    """Guarda los datos del emisor de un negocio. Solo toca las claves presentes en `datos`
    (las de `CAMPOS_DATOS`); un texto vacío deja la columna en NULL. Devuelve la fila
    actualizada o None si el negocio no es de la cuenta."""
    init_negocios()
    sets, args = [], []
    for k in CAMPOS_DATOS:
        if k not in datos or datos[k] is None:
            continue
        v = datos[k]
        if isinstance(v, str):
            v = v.strip() or None
        sets.append(f"{k}=?")
        args.append(v)
    with database.get_db() as conn:
        if sets:
            cur = conn.execute(f"UPDATE negocios SET {', '.join(sets)} WHERE id=? AND cuenta_id=?",
                               (*args, negocio_id, cuenta_id))
            if cur.rowcount == 0:
                return None
    return next((n for n in listar_negocios(cuenta_id) if n["id"] == negocio_id), None)


def eliminar_negocio(cuenta_id: int, negocio_id: int) -> bool:
    with database.get_db() as conn:
        cur = conn.execute("DELETE FROM negocios WHERE id=? AND cuenta_id=?",
                           (negocio_id, cuenta_id))
        return cur.rowcount > 0


def registrar_software(rut: str, nombre: str) -> None:
    """Recuerda el nombre de software que el motor registró en el SII para `rut` (todas las
    cuentas que tengan ese negocio). Lo llama la postulación automática; best-effort."""
    if not (rut and nombre and nombre.strip()):
        return
    with database.get_db() as conn:
        conn.execute("UPDATE negocios SET software_registrado=? WHERE rut=?", (nombre.strip(), rut))


def software_registrado(rut: str) -> Optional[str]:
    """Nombre de software que el motor registró en el SII para `rut`, o None."""
    with database.get_db() as conn:
        row = conn.execute("SELECT software_registrado FROM negocios WHERE rut=? "
                           "AND software_registrado IS NOT NULL LIMIT 1", (rut,)).fetchone()
    return row[0] if row else None
