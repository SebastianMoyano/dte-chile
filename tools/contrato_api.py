"""
tools/contrato_api.py — Contrato dorado de la API: el motor Go debe responder lo mismo que el
motor Python (fase 7 del port). Pide cada ruta a los dos y compara status, `codigo` de error y
el JSON completo (ignorando campos volátiles como request_id y actualizado).

Uso (los dos motores corriendo, con el MISMO APP_SHELL_KEY en el entorno de ambos, o un JWT):
  APP_SHELL_KEY=… .venv/bin/python tools/contrato_api.py --python http://127.0.0.1:8771 --go http://127.0.0.1:8010
  … --token <jwt o api key>        (si no, usa APP_SHELL_KEY del entorno)
  … --rutas rutas.txt              (una ruta por línea; si no, el juego de rutas de abajo)

Sale 0 si todo coincide; 1 si hay diferencias (se listan).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

IGNORAR = {"request_id", "actualizado"}

RUTAS_DEFAULT = [
    "/",
    "/api/v1/valores",
    "/api/v1/valores?fecha=2026-10-01",
    "/api/v1/valores?fecha=2026-09-14",
    "/api/v1/valores?fecha=no-es-fecha",
    "/api/v1/valores/uf",
    "/api/v1/valores/utm?fecha=2026-09-15",
    "/api/v1/valores/dolar?fecha=2026-10-05",
    "/api/v1/valores/xx",
    "/api/v1/valores/uf?fecha=1990-01-01",
    "/api/v1/valores/historico?anio=2026",
    "/api/v1/valores/historico?anio=2015",
    "/api/v1/valores/historico?anio=1999",
    "/api/v1/valores/historico",
    "/api/v1/valores/uf/serie?desde=2026-09-01&hasta=2026-09-10",
    "/api/v1/valores/utm/serie?desde=2026-01-01&hasta=2026-12-31",
    "/api/v1/valores/uf/serie",
    # reenviadas (Python detrás de Go): deben ser idénticas
    "/api/v1/keystore/negocios",
    "/api/v1/dte/documentos?limite=3",
]


def pedir(base: str, ruta: str, token: str | None):
    req = urllib.request.Request(base + ruta, headers={"Accept": "application/json", **({"Authorization": "Bearer " + token} if token else {})})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except Exception as e:  # noqa: BLE001
        return -1, str(e).encode()


def limpiar(x):
    if isinstance(x, dict):
        return {k: limpiar(v) for k, v in x.items() if k not in IGNORAR}
    if isinstance(x, list):
        return [limpiar(v) for v in x]
    return x


def diferencias(a, b, ruta=""):
    out = []
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a:
                out.append(f"{ruta}.{k}: solo en go = {b[k]!r}")
            elif k not in b:
                out.append(f"{ruta}.{k}: solo en python = {a[k]!r}")
            else:
                out += diferencias(a[k], b[k], f"{ruta}.{k}")
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            out.append(f"{ruta}: largos {len(a)} vs {len(b)}")
        for i, (x, y) in enumerate(zip(a, b)):
            out += diferencias(x, y, f"{ruta}[{i}]")
    elif a != b and not (isinstance(a, (int, float)) and isinstance(b, (int, float)) and a == b):
        out.append(f"{ruta}: python={a!r} go={b!r}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--python", required=True)
    ap.add_argument("--go", required=True)
    ap.add_argument("--token", default=os.environ.get("APP_SHELL_KEY"))
    ap.add_argument("--rutas")
    ap.add_argument("--sin-auth", action="store_true", help="además, pedir cada ruta sin token y comparar el 401")
    a = ap.parse_args()
    rutas = [l.strip() for l in open(a.rutas, encoding="utf-8") if l.strip() and not l.startswith("#")] if a.rutas else RUTAS_DEFAULT
    fallas = 0
    for ruta in rutas:
        variantes = [(ruta, a.token)] + ([(ruta, None)] if a.sin_auth and ruta != "/" else [])
        for r, tok in variantes:
            sp, bp = pedir(a.python, r, tok)
            sg, bg = pedir(a.go, r, tok)
            etiqueta = r + ("" if tok else "  [sin token]")
            try:
                jp, jg = json.loads(bp or b"null"), json.loads(bg or b"null")
            except ValueError:
                print(f"✗ {etiqueta}: respuesta no JSON (python {sp}, go {sg})"); fallas += 1; continue
            if sp != sg:
                print(f"✗ {etiqueta}: status python {sp} ≠ go {sg}"); fallas += 1; continue
            if sp >= 400:
                cp, cg = (jp or {}).get("error", {}).get("codigo"), (jg or {}).get("error", {}).get("codigo")
                if cp != cg:
                    print(f"✗ {etiqueta}: {sp} codigo python {cp!r} ≠ go {cg!r}"); fallas += 1
                else:
                    print(f"✓ {etiqueta}: {sp} {cp}")
                continue
            difs = diferencias(limpiar(jp), limpiar(jg))
            if difs:
                fallas += 1
                print(f"✗ {etiqueta}: {len(difs)} diferencia(s)")
                for d in difs[:8]:
                    print("    " + d)
            else:
                print(f"✓ {etiqueta}: {sp} idéntico")
    print(f"\n{'TODO IDÉNTICO' if not fallas else str(fallas) + ' ruta(s) con diferencias'}")
    return 0 if not fallas else 1


if __name__ == "__main__":
    sys.exit(main())
