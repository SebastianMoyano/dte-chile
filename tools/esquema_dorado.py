"""
tools/esquema_dorado.py — El esquema que crea Go (nucleo/almacen/migraciones) debe ser el mismo
que creaba Python (core/database.py + keystore + apikeys + negocios + rcv + resolución + folios).

Crea dos bases vacías, una con cada motor, y compara `sqlite_master` tabla por tabla e índice
por índice (SQL normalizado: espacios y comentarios fuera). Ignora `migraciones` y
`sqlite_sequence`. Sale 0 si son iguales.

Uso:  .venv/bin/python tools/esquema_dorado.py [--go nucleo/bin/nucleo-servidor]
"""
from __future__ import annotations

import argparse
import os
import pathlib
import re
import sqlite3
import subprocess
import sys
import tempfile

RAIZ = pathlib.Path(__file__).resolve().parent.parent


def esquema(ruta: str) -> dict:
    con = sqlite3.connect(ruta)
    out = {}
    for tipo, nombre, tabla, sql in con.execute("SELECT type, name, tbl_name, sql FROM sqlite_master WHERE sql IS NOT NULL"):
        if nombre in ("migraciones", "sqlite_sequence") or nombre.startswith("sqlite_"):
            continue
        s = re.sub(r"--[^\n]*", "", sql)
        s = re.sub(r"\s+", " ", s).strip().rstrip(";")
        s = s.replace("( ", "(").replace(" )", ")").replace(" ,", ",")
        out[(tipo, nombre)] = (tabla, s.upper())
    con.close()
    return out


def crear_python(ruta: str) -> None:
    env = {**os.environ, "DATABASE_URL": "sqlite:///" + ruta}
    codigo = (
        "import core.database as d; d.init_db()\n"
        "from core import keystore, apikeys, negocios, rcv; keystore.init_keystore(); apikeys.init_api_keys(); negocios.init_negocios(); rcv.init_rcv_db()\n"
        "import core.resolucion, core.folios_auto\n"
        "from core import database\n"
        "for mod in (core.resolucion, core.folios_auto):\n"
        "    import re; src=open(mod.__file__,encoding='utf-8').read()\n"
        "    for ddl in re.findall(r'CREATE (?:TABLE|INDEX) IF NOT EXISTS[\\s\\S]*?;', src): database.ejecutar(ddl)\n"
    )
    subprocess.run([sys.executable, "-c", codigo], cwd=RAIZ, env=env, check=True)


def crear_go(ruta: str, binario: str) -> None:
    subprocess.run([binario, "migrar", "--db", ruta, "--env", "/dev/null"], cwd=RAIZ, check=True, capture_output=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--go", default=str(RAIZ / "nucleo" / "bin" / "nucleo-servidor"))
    a = ap.parse_args()
    with tempfile.TemporaryDirectory() as d:
        py, go = os.path.join(d, "py.db"), os.path.join(d, "go.db")
        crear_python(py)
        crear_go(go, a.go)
        ep, eg = esquema(py), esquema(go)
    fallas = 0
    for k in sorted(set(ep) | set(eg)):
        if k not in eg:
            print(f"✗ {k[0]} {k[1]}: solo Python"); fallas += 1
        elif k not in ep:
            print(f"✗ {k[0]} {k[1]}: solo Go"); fallas += 1
        elif ep[k] != eg[k]:
            print(f"✗ {k[0]} {k[1]}: distinto\n    py: {ep[k][1]}\n    go: {eg[k][1]}"); fallas += 1
        else:
            print(f"✓ {k[0]} {k[1]}")
    print(f"\n{len(ep)} objetos en Python, {len(eg)} en Go: {'IDÉNTICOS' if not fallas else str(fallas) + ' diferencia(s)'}")
    return 0 if not fallas else 1


if __name__ == "__main__":
    sys.exit(main())
