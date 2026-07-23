"""
test_rcv_live.py — smoke-test EN VIVO de la bajada del RCV (lo que faltaba validar).

Requiere un RUT + período que SÍ tengan movimientos en el Registro de Compras y
Ventas del SII (producción). Resuelve las dos preguntas abiertas:

  1) ¿La bajada trae datos reales? (validar el parseo del facade en vivo)
  2) Los endpoints "*Export" ¿devuelven las filas INLINE o un archivo (nombreArchivo)?
     ¿Hay que usar los endpoints sin "Export" iterando por tipo de documento?

Uso:
    .venv/bin/python test_rcv_live.py --rut 76111111-6 --periodo 202506
    # con otro certificado (PEM):
    .venv/bin/python test_rcv_live.py --rut ... --periodo ... \
        --cert /ruta/cert.pem --key /ruta/key.pem

RUT por defecto configurable vía DTE_RUT_EMPRESA (default ficticio si no se define).

OJO: el SII rate-limitea (HTTP 429) si se consulta mucho. Si sale 429, esperar y
reintentar más tarde. No correr en bucle.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import httpx

import core.rcv as rcv
from core.sii_portal import BASE_PRODUCCION, PortalSII

# Tipos de documento típicos para iterar los endpoints sin "Export".
TIPOS = [33, 34, 39, 46, 56, 61]


def _headers(token: str, num: str, dv: str) -> dict:
    return {
        "Accept": "*/*",  # `application/json` da HTTP 500 en el facade RESTEasy
        "Content-Type": "application/json;charset=UTF-8",
        "User-Agent": rcv.RCV_USER_AGENT,
        "Cookie": f"TOKEN={token};RUT_NS={num};DV_NS={dv}",
    }


def _post(c, token, num, dv, metodo, data):
    payload = {
        "metaData": {"namespace": rcv._rcv_namespace(metodo),
                     "conversationId": f"{num}-{dv}", "transactionId": "0", "page": None},
        "data": data,
    }
    r = c.post(rcv.RCV_BASE + metodo, headers=_headers(token, num, dv), json=payload)
    return r


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rut", default=os.environ.get("DTE_RUT_EMPRESA", "76111111-6"))
    ap.add_argument("--periodo", required=True)
    ap.add_argument("--cert", default="/tmp/of_ref/cert.pem")
    ap.add_argument("--key", default="/tmp/of_ref/key.pem")
    a = ap.parse_args(argv)

    portal = PortalSII(a.cert, a.key, base=BASE_PRODUCCION)
    portal.autenticar()
    token = portal.cookies.get("TOKEN")
    num, dv = a.rut.replace(".", "").split("-")
    c = httpx.Client(timeout=60, verify=True)
    print(f"== RCV {a.rut} período {a.periodo} ==")

    # 1) Resumen del período.
    r = _post(c, token, num, dv, "getResumen",
              {"rutEmisor": num, "dvEmisor": dv, "ptributario": a.periodo, "estadoContab": "REGISTRO"})
    if r.status_code == 429:
        print("HTTP 429: rate-limit del SII. Espera y reintenta más tarde."); return 2
    j = r.json()
    print("\n[getResumen]", json.dumps(j.get("respEstado"), ensure_ascii=False),
          "| data:", "SÍ" if j.get("data") else "null")
    if j.get("data"):
        print("  totales:", json.dumps(j["data"], ensure_ascii=False)[:400])

    # 2) Export (codTipoDoc:0) — ¿inline o archivo?
    for oper in ("VENTA", "COMPRA"):
        r = _post(c, token, num, dv, rcv.RCV_METODOS[oper],
                  {"rutEmisor": num, "dvEmisor": dv, "ptributario": a.periodo,
                   "estadoContab": "REGISTRO", "codTipoDoc": 0, "operacion": oper})
        j = r.json()
        print(f"\n[{rcv.RCV_METODOS[oper]}] data:", "SÍ" if isinstance(j.get('data'), list) else j.get('data'),
              "| nombreArchivo:", j.get("nombreArchivo"), "| respEstado:", j.get("respEstado"))
        if isinstance(j.get("data"), list) and j["data"]:
            print("  → EXPORT DEVUELVE INLINE. 1er doc llaves:", list(j["data"][0].keys())[:14])

    # 3) Sin "Export", iterando por tipo (exigen codTipoDoc != 0).
    print("\n[getDetalleVenta / getDetalleCompra por tipo]")
    total_docs = 0
    for oper in ("VENTA", "COMPRA"):
        metodo = "getDetalleVenta" if oper == "VENTA" else "getDetalleCompra"
        for td in TIPOS:
            r = _post(c, token, num, dv, metodo,
                      {"rutEmisor": num, "dvEmisor": dv, "ptributario": a.periodo,
                       "estadoContab": "REGISTRO", "codTipoDoc": td, "operacion": oper})
            j = r.json()
            d = j.get("data")
            if isinstance(d, list) and d:
                total_docs += len(d)
                print(f"  {oper} tipo {td}: {len(d)} docs")
                # normalizar + persistir para la propuesta F29
                docs = rcv.normalizar_detalle(a.rut, oper, a.periodo, {"data": d}, origen="rcv")
                rcv.guardar_documentos(docs)

    # 4) Propuesta F29 con lo bajado.
    if total_docs:
        desg = rcv.calcular_desglose_f29(a.rut, a.periodo)
        print(f"\n== F29 propuesto ({total_docs} docs) ==")
        for l in rcv.mapear_a_f29(desg):
            print(f"  [{l.codigo:>3}] {l.glosa:<44} {l.valor:>12,}".replace(",", "."))
        print(f"  IVA determinado: {desg.iva_determinado:,}".replace(",", "."))
    else:
        print("\n(sin documentos en el RCV para ese RUT/período)")
    c.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
