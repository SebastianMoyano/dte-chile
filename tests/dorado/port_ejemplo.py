#!/usr/bin/env python3
"""Port de ejemplo: muestra el contrato que debe cumplir un port del núcleo en otro lenguaje.

    <este programa> <entrada.json> <carpeta fixtures> <carpeta salida>

Entorno: RELOJ_FIJO (hora ISO a usar en todos los timestamps), DORADO_RESOLUCION_FECHA,
DORADO_RESOLUCION_NUMERO. Debe escribir en <salida>: ted.xml, dte.xml, envio.xml.

Este ejemplo reusa el motor Python (vía test_dorado.correr_caso), así que pasa por construcción: sirve para validar el
runner (`test_dorado.py --port`) y como referencia de qué lee y qué escribe un port real.
Un port en Go o Rust hace exactamente esto con su propio código.
"""
import json
import os
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def main() -> int:
    entrada, fixtures, salida = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    from core import reloj
    reloj.fijar(os.environ["RELOJ_FIJO"])
    import test_dorado as td
    td.FIX = fixtures
    td.RESOLUCION = (os.environ["DORADO_RESOLUCION_FECHA"], int(os.environ["DORADO_RESOLUCION_NUMERO"]))
    caso = json.loads(entrada.read_text(encoding="utf-8"))
    salida.mkdir(parents=True, exist_ok=True)
    for nombre, datos in td.correr_caso(caso).items():
        if nombre.endswith(".xml"):
            (salida / nombre).write_bytes(datos)
    return 0


if __name__ == "__main__":
    sys.exit(main())
