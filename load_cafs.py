#!/usr/bin/env python3
"""
load_cafs.py — Carga los CAF XML de storage/cafs/ a la BD.

Uso:
    .venv/bin/python load_cafs.py

Globpea storage/cafs/*.xml, parsea cada uno con ManejadorCAF,
verifica duplicados por (rut_emisor, tipo_dte, folio_desde),
e inserta con registrar_caf().  Muestra antes/después.
"""

import glob
import os
import sys
from pathlib import Path

# Garantiza que el directorio raíz del proyecto está en sys.path
_PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(_PROJECT_ROOT))

from core.caf import ManejadorCAF
from core.models import registrar_caf
from core.database import get_db


def listar_cafs():
    """Retorna list[dict] con todos los CAFs de la BD ordenados por id."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, rut_emisor, tipo_dte, folio_desde, folio_hasta, "
            "folio_siguiente FROM cafs ORDER BY id"
        ).fetchall()
    return [dict(r) for r in rows]


def caf_existe(rut_emisor: str, tipo_dte: int, folio_desde: int) -> bool:
    """True si ya hay un CAF con esa (rut_emisor, tipo_dte, folio_desde)."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT id FROM cafs WHERE rut_emisor=? AND tipo_dte=? AND folio_desde=?",
            (rut_emisor, tipo_dte, folio_desde),
        ).fetchone()
    return row is not None


def mostrar_tabla(rows: list[dict], titulo: str):
    """Imprime la tabla de CAFs."""
    print()
    print("=" * 60)
    print(titulo)
    print("=" * 60)
    if not rows:
        print("  (vacío)")
        print("=" * 60)
        return
    print(f"{'ID':>4}  {'RUT':<12} {'TIPO':>5}  {'DESDE':>6}  {'HASTA':>6}  {'SIG':>6}")
    print("-" * 60)
    for r in rows:
        print(
            f"{r['id']:>4}  {r['rut_emisor']:<12} {r['tipo_dte']:>5}  "
            f"{r['folio_desde']:>6}  {r['folio_hasta']:>6}  {r['folio_siguiente']:>6}"
        )
    print("=" * 60)


def main():
    cafs_dir = _PROJECT_ROOT / "storage" / "cafs"
    xml_files = sorted(glob.glob(os.path.join(str(cafs_dir), "*.xml")))

    if not xml_files:
        print("❌ No se encontraron archivos *.xml en storage/cafs/")
        sys.exit(1)

    # ---- Antes ----
    antes = listar_cafs()
    mostrar_tabla(antes, "ESTADO ANTES DE LA CARGA")

    insertados = 0
    saltados = 0

    # ---- Procesar cada CAF ----
    for xml_path in xml_files:
        filename = Path(xml_path).name
        print(f"\n📄 Procesando: {filename}")

        try:
            manejador = ManejadorCAF.desde_archivo(xml_path)
            datos = manejador.datos

            print(f"   RUT Emisor    : {datos.rut_emisor}")
            print(f"   Tipo DTE      : {datos.tipo_dte}")
            print(f"   Folios        : {datos.folio_desde} - {datos.folio_hasta}")
            print(f"   Fecha Aut     : {datos.fecha_autorizacion}")

            # Evitar duplicados
            if caf_existe(datos.rut_emisor, datos.tipo_dte, datos.folio_desde):
                print(f"   ⏭️  Ya existe en BD — saltando.")
                saltados += 1
                continue

            caf_id = registrar_caf(
                tipo_dte=datos.tipo_dte,
                rut_emisor=datos.rut_emisor,
                folio_desde=datos.folio_desde,
                folio_hasta=datos.folio_hasta,
                fecha_autorizacion=datos.fecha_autorizacion.isoformat(),
                # El XML del SII viene en ISO-8859-1; decodeamos seguro
                caf_xml=datos.xml_raw.decode("iso-8859-1"),
            )
            print(f"   ✅ Insertado con ID = {caf_id}")
            insertados += 1

        except Exception as e:
            print(f"   ❌ Error al procesar: {e}")

    # ---- Después ----
    despues = listar_cafs()
    mostrar_tabla(despues, "ESTADO DESPUÉS DE LA CARGA")

    print()
    print(f"📊 Resumen: {insertados} insertados, {saltados} saltados, "
          f"{len(despues)} total en BD.")


if __name__ == "__main__":
    main()
