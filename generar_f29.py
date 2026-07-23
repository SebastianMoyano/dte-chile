"""
generar_f29.py

Genera una PROPUESTA de Formulario 29 (IVA mensual) desde los datos del RCV ya
persistidos en la base (tabla `rcv_documentos`). Es solo lectura/agregación: no
emite nada al SII ni toca el pipeline de facturación.

Uso:
    # Sobre lo que ya está en la BD:
    .venv/bin/python generar_f29.py --rut 76111111-6 --periodo 202406

    # Ingiriendo primero un JSON del RCV bajado del portal (compras y/o ventas):
    .venv/bin/python generar_f29.py --rut 76111111-6 --periodo 202406 \
        --compras rcv_compras.json --ventas rcv_ventas.json

    # Con PPM y remanente del mes anterior:
    .venv/bin/python generar_f29.py --rut 76111111-6 --periodo 202406 \
        --ppm 45000 --remanente-anterior 12000

    # Exportar la propuesta a JSON:
    .venv/bin/python generar_f29.py --rut 76111111-6 --periodo 202406 --json salida.json

Los códigos marcados con ⚠ son de confianza media: confírmalos contra un F29 real
de la empresa (los montos son correctos; es el número de casillero lo que puede
variar). Ver core/rcv.py::CODIGOS_F29.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from core.rcv import (
    COMPRA,
    VENTA,
    calcular_desglose_f29,
    cargar_desde_json,
    init_rcv_db,
    mapear_a_f29,
)
from core.database import get_db
from core.rut import validar_rut


def _fmt(n: int) -> str:
    """Formatea pesos con separador de miles chileno."""
    signo = "-" if n < 0 else ""
    return f"{signo}${abs(int(n)):,}".replace(",", ".")


def _contar_docs(rut: str, periodo: str) -> tuple[int, int]:
    with get_db() as conn:
        row = conn.execute(
            """SELECT
                 SUM(CASE WHEN tipo_operacion=? THEN 1 ELSE 0 END) AS v,
                 SUM(CASE WHEN tipo_operacion=? THEN 1 ELSE 0 END) AS c
               FROM rcv_documentos WHERE rut_empresa=? AND periodo=?""",
            (VENTA, COMPRA, rut, periodo),
        ).fetchone()
    return (row["v"] or 0, row["c"] or 0)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Propuesta de Formulario 29 desde el RCV.")
    p.add_argument("--rut", required=True, help="RUT del contribuyente (NNNNNNNN-D)")
    p.add_argument("--periodo", required=True, help="Período tributario YYYYMM o YYYY-MM")
    p.add_argument("--compras", help="JSON de detalle de COMPRAS del RCV a ingerir primero")
    p.add_argument("--ventas", help="JSON de detalle de VENTAS del RCV a ingerir primero")
    p.add_argument("--ppm", type=int, default=0, help="PPM del período (default 0)")
    p.add_argument("--remanente-anterior", type=int, default=0,
                   help="Remanente de crédito fiscal del mes anterior (default 0)")
    p.add_argument("--json", help="Ruta para exportar la propuesta como JSON")
    args = p.parse_args(argv)

    if not validar_rut(args.rut):
        print(f"❌ RUT inválido: {args.rut}", file=sys.stderr)
        return 2

    init_rcv_db()

    # Ingesta opcional de JSON del RCV
    if args.compras:
        n = len(cargar_desde_json(args.rut, COMPRA, args.periodo, args.compras))
        print(f"↳ Ingeridas {n} compras desde {args.compras}")
    if args.ventas:
        n = len(cargar_desde_json(args.rut, VENTA, args.periodo, args.ventas))
        print(f"↳ Ingeridas {n} ventas desde {args.ventas}")

    n_ventas, n_compras = _contar_docs(args.rut, args.periodo)
    if n_ventas == 0 and n_compras == 0:
        print(f"\n⚠  No hay documentos en el RCV para {args.rut} período {args.periodo}.")
        print("   Baja el RCV (RegistroCompraVenta.sincronizar_periodo) o ingiere un JSON")
        print("   con --compras/--ventas antes de generar el F29.")
        return 1

    desglose = calcular_desglose_f29(
        args.rut, args.periodo, ppm=args.ppm, remanente_anterior=args.remanente_anterior
    )
    lineas = mapear_a_f29(desglose)

    # --- Reporte ---
    print("\n" + "=" * 60)
    print(f"  PROPUESTA FORMULARIO 29  —  {args.rut}  —  período {args.periodo}")
    print("=" * 60)
    print(f"  Documentos: {n_ventas} ventas · {n_compras} compras")
    print("-" * 60)
    for l in lineas:
        flag = "" if l.confianza == "OK" else "  ⚠"
        print(f"  [{l.codigo:>3}] {l.glosa:<46} {_fmt(l.valor):>14}{flag}")
    print("-" * 60)

    iva = desglose.iva_determinado
    if iva < 0:
        print(f"  Resultado: REMANENTE de {_fmt(-iva)} para el período siguiente (cód. 077)")
        print(f"  A pagar por IVA: $0" + (f"  (+ PPM {_fmt(desglose.ppm)})" if desglose.ppm else ""))
    else:
        print(f"  IVA determinado a pagar: {_fmt(iva)}"
              + (f"  + PPM {_fmt(desglose.ppm)}" if desglose.ppm else ""))
    print(f"  >>> TOTAL A PAGAR (cód. 091): {_fmt(desglose.total_a_pagar)}")
    print("=" * 60)
    if any(l.confianza != "OK" for l in lineas):
        print("  ⚠ = código de casillero por confirmar contra un F29 real (el monto es correcto).")

    if args.json:
        salida = {
            "rut": args.rut,
            "periodo": args.periodo,
            "n_ventas": n_ventas,
            "n_compras": n_compras,
            "total_debitos": desglose.total_debitos,
            "total_creditos": desglose.total_creditos,
            "iva_determinado": desglose.iva_determinado,
            "remanente_siguiente": desglose.remanente_siguiente,
            "ppm": desglose.ppm,
            "total_a_pagar": desglose.total_a_pagar,
            "casilleros": [
                {"codigo": l.codigo, "glosa": l.glosa, "valor": l.valor, "confianza": l.confianza}
                for l in lineas
            ],
        }
        Path(args.json).write_text(json.dumps(salida, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n↳ Propuesta exportada a {args.json}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
