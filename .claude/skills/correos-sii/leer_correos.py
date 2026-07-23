#!/usr/bin/env python3
"""
Lee los correos del SII desde el endpoint propio del usuario y extrae el CÓDIGO de error.

Existe porque el detalle de un rechazo de factura llega SOLO por correo: el SOAP
(`QueryEstUp`) da nada más que conteos, sin código, y sin código no se diagnostica.

El token vive en `.env` como `SII_MAIL_TOKEN` (el usuario lo rota ahí). `.env` está en
`.gitignore` — verificado. También se acepta por variable de entorno, que tiene prioridad.
⚠️ NUNCA usar las herramientas de Gmail: solo este endpoint (ver SKILL.md).

Uso:
    leer_correos.py                 # tabla resumen de los últimos 20
    leer_correos.py 253113966       # correo completo de un envío
    leer_correos.py --set 4943175   # resultado de un set de certificación
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.request

# La URL no es un secreto: sin el token responde "No autorizado" (verificado 2026-07-17).
URL = ("https://script.google.com/macros/s/"
       "AKfycbxeLxYJHumrQaGIwJGhKux7Ttr_BOPo4Eo-tCvFPCPcsxAT1GDlR87V2CHr2JjtGvAjLQ/exec")


def _token() -> str:
    """El token, del entorno o de `.env` (vía settings). El entorno manda."""
    t = os.environ.get("SII_MAIL_TOKEN", "").strip()
    if t:
        return t
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
        from core.config import settings
        return (settings.sii_mail_token or "").strip()
    except Exception:
        return ""


def bajar() -> dict:
    token = _token()
    if not token:
        sys.exit("Falta el token del endpoint de correos.\n"
                 "  Ponlo en .env como  SII_MAIL_TOKEN=...  (el usuario lo rota ahí),\n"
                 "  o expórtalo:        export SII_MAIL_TOKEN='<token>'\n"
                 "Si no lo tienes, pídeselo al usuario. No lo busques por otra vía.")
    req = urllib.request.Request(f"{URL}?token={token}",
                                 headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        datos = json.loads(r.read().decode("utf-8"))
    if not datos.get("exito"):
        sys.exit(f"El endpoint respondió: {datos.get('error', datos)}")
    return datos


def _adjuntos(correo: dict):
    for a in (correo.get("adjuntosTxt") or []):
        yield a.get("contenido", "")


def resumir(txt: str) -> dict:
    """Extrae los campos útiles de un correo del SII (envío o set)."""
    d: dict = {}
    for clave, patron in [
        ("envio", r"Identificador de Envio\s*:\s*(\d+)"),
        ("set", r"Identificador del Set\s*:\s*(\d+)"),
        ("tipo_set", r"Tipo de Set\s*:\s*([^\r\n]+)"),
        ("estado", r"Estado del (?:Envio|Set)\s*:\s*([^\r\n]+)"),
    ]:
        m = re.search(patron, txt)
        if m:
            d[clave] = m.group(1).strip()

    # Estadísticas: "Tipo DTE  Informados  Rechazos  Reparos  Aceptados"
    # OJO con el orden de las columnas: aceptados va AL FINAL, no al principio.
    m = re.search(r"^\s*(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s*$", txt, re.M)
    if m:
        d["tipo"], d["informados"], d["rechazos"], d["reparos"], d["aceptados"] = m.groups()

    # Códigos de error: "(DTE-3-505) Firma DTE Incorrecta"
    d["codigos"] = [(c, g.strip()) for c, g in
                    re.findall(r"\((\w+-\d+-\d+)\)\s*([^\r\n]*)", txt)]
    # Reparos de set, que no traen código entre paréntesis
    if not d["codigos"] and d.get("set"):
        d["reparos_set"] = [l.strip() for l in txt.splitlines()
                            if l.startswith("     ") and l.strip()]
    return d


def tabla(datos: dict) -> None:
    print(f"{'envío/set':<12}{'fecha':<7}{'tipo':<6}{'acep':<6}{'rech':<6}detalle")
    print("-" * 92)
    for c in reversed(datos["correos"]):
        if "sii.cl" not in (c.get("remitente") or ""):
            continue
        for txt in _adjuntos(c):
            d = resumir(txt)
            ident = d.get("envio") or d.get("set") or "?"
            det = ""
            if d.get("codigos"):
                det = f"{d['codigos'][0][0]} {d['codigos'][0][1][:40]}"
            elif d.get("reparos_set"):
                det = f"{d.get('estado','')} · {d['reparos_set'][0][:44]}"
            elif d.get("estado"):
                det = d["estado"]
            print(f"{ident:<12}{c['fecha'][5:10]:<7}"
                  f"{d.get('tipo','-'):<6}{d.get('aceptados','-'):<6}"
                  f"{d.get('rechazos','-'):<6}{det}")
    print()
    print("⚠️  EPR = 'envío procesado', NO aceptado. Mira la columna `acep`.")
    print("    Los códigos están explicados en docs/LECCIONES-SII.md")


def detalle(datos: dict, buscado: str, por_set: bool = False) -> None:
    clave = "Identificador del Set" if por_set else "Identificador de Envio"
    for c in datos["correos"]:
        for txt in _adjuntos(c):
            m = re.search(rf"{clave}\s*:\s*{buscado}\b", txt)
            if m:
                print(f"--- {c['asunto']}  ({c['fecha'][:16]})")
                print(txt)
                return
    sys.exit(f"No encontré {'el set' if por_set else 'el envío'} {buscado} "
             "en los últimos 20 correos.")


def main() -> None:
    args = [a for a in sys.argv[1:]]
    por_set = "--set" in args
    if por_set:
        args.remove("--set")
    datos = bajar()
    if args:
        detalle(datos, args[0], por_set)
    else:
        tabla(datos)


if __name__ == "__main__":
    main()
