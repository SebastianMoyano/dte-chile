"""
tools/paridad_siiengine.py — Paridad Python ↔ Go del SII engine (portal MIPYME), SIN gastar folio.

Corre en seco uno de los tres flujos con el módulo Python (`core/sii_mipyme.py`) grabando los
cuerpos que manda (validar, GenXMLFirma) y las páginas que recibe, y opcionalmente los compara
con las trazas del binario Go (`nucleo-siiengine … --trazas <dir>`). Es la vara de la fase 6
del port (`docs/PLAN-PORT.md`): mismo HTML de entrada, mismo cuerpo byte a byte.

Uso (los parámetros reales van en un JSON privado, fuera de git — L14):
  .venv/bin/python tools/paridad_siiengine.py factura     --params storage/siiengine_paridad/params.json --salida /tmp/par/py
  .venv/bin/python tools/paridad_siiengine.py nc-anular   --params … --salida … [--comparar /tmp/par/go]
  .venv/bin/python tools/paridad_siiengine.py nc-corregir --params … --salida … [--comparar …]

params.json: {"usuario": "12.345.678-5", "empresa": "77.777.777-7",
              "receptor": {"rut", "razon_social", "giro", "direccion", "ciudad", "comuna"},
              "item": {"nombre", "precio", "cantidad", "descripcion"}, "fecha": "YYYY-MM-DD", "forma_pago": "1",
              "nc-anular": {"dhdr", "tipo_ref", "folio_ref", "fecha_ref"}, "nc-corregir": {…}}
Las claves salen del Llavero (sii-clave-tributaria / sii-clave-certificado), nunca del JSON.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
from urllib.parse import parse_qsl

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from core.sii_mipyme import (  # noqa: E402
    LLAVERO_CLAVE_CERTIFICADO, LLAVERO_CLAVE_TRIBUTARIA, TIPO_FACTURA_EXENTA, ClienteMipyme, ItemMipyme,
    ReceptorMipyme, _body, clave_desde_llavero,
)

GO_VALIDAR = {"factura": "body_validar.txt", "nc-corregir": "body_corr_validar.txt"}


def correr(flujo: str, params: dict, salida: pathlib.Path) -> None:
    salida.mkdir(parents=True, exist_ok=True)
    rec = ReceptorMipyme(**params["receptor"])
    it = ItemMipyme(**params["item"])
    usuario = params["usuario"]
    cli = ClienteMipyme(usuario, clave_desde_llavero(LLAVERO_CLAVE_TRIBUTARIA, usuario) or "",
                        clave_desde_llavero(LLAVERO_CLAVE_CERTIFICADO, usuario) or "")
    n = [0]
    original = cli._req

    def grabando(metodo, url, **kw):
        r = original(metodo, url, **kw)
        n[0] += 1
        nombre = url.rsplit("/", 1)[-1].split("?")[0].replace(".cgi", "")
        if "postFirma" in url or "DownLoad" in url:   # llevan la clave del certificado / adjunto
            return r
        if metodo == "POST" and kw.get("content") is not None:
            (salida / f"{n[0]:02d}_body_{nombre}.txt").write_bytes(kw["content"])
        (salida / f"{n[0]:02d}_{metodo}_{nombre}.html").write_bytes(r.content)
        return r

    cli._req = grabando
    with cli:
        cli.iniciar_sesion()
        cli.seleccionar_empresa(params["empresa"])
        if flujo == "factura":
            p = cli.preparar(TIPO_FACTURA_EXENTA, rec, [it], params.get("fecha"), params.get("forma_pago", "1"))
        else:
            ref = params[flujo]
            fn = cli.preparar_nc_anulacion if flujo == "nc-anular" else cli.preparar_nc_correccion_montos
            p = fn(ref["dhdr"], ref["tipo_ref"], ref["folio_ref"], ref["fecha_ref"], rec, [it], params.get("fecha"))
    (salida / "body_genxml.txt").write_bytes(_body(p.pares))
    validar = sorted(salida.glob("*_body_mipeDisplayPreView.txt"))
    if validar:
        (salida / "body_validar.txt").write_bytes(validar[-1].read_bytes())
    print(f"python {flujo}: {len(p.pares)} pares, total {p.monto_total}, campos nuevos {p.campos_nuevos}")


def pares(ruta: pathlib.Path) -> list:
    return parse_qsl(ruta.read_bytes().decode("latin-1"), keep_blank_values=True, encoding="latin-1")


def comparar(nombre: str, py: pathlib.Path, go: pathlib.Path) -> bool:
    if not py.exists() or not go.exists():
        print(f"{nombre}: falta {'python' if not py.exists() else 'go'}")
        return False
    a, b = pares(py), pares(go)
    iguales = py.read_bytes() == go.read_bytes()
    print(f"{nombre}: python {len(a)} pares, go {len(b)} pares, bytes idénticos: {iguales}")
    for i, (x, y) in enumerate(zip(a, b)):
        if x != y:
            print(f"  campo {i}: python {x} | go {y}")
    if len(a) != len(b):
        print("  largos distintos")
    return iguales


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("flujo", choices=["factura", "nc-anular", "nc-corregir"])
    ap.add_argument("--params", required=True, help="JSON privado con usuario, empresa, receptor, ítem y referencias")
    ap.add_argument("--salida", required=True, help="carpeta para los cuerpos y páginas de Python")
    ap.add_argument("--comparar", help="carpeta de trazas del Go (nucleo-siiengine … --trazas)")
    ap.add_argument("--solo-comparar", action="store_true", help="no correr Python: comparar lo ya grabado")
    a = ap.parse_args()
    params = json.loads(pathlib.Path(a.params).read_text(encoding="utf-8"))
    salida = pathlib.Path(a.salida)
    if not a.solo_comparar:
        correr(a.flujo, params, salida)
    if a.comparar:
        go = pathlib.Path(a.comparar)
        ok = True
        if a.flujo in GO_VALIDAR:
            ok &= comparar("validar", salida / "body_validar.txt", go / GO_VALIDAR[a.flujo])
        ok &= comparar("genxml", salida / "body_genxml.txt", go / "body_genxml.txt")
        return 0 if ok else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
