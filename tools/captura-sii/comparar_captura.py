"""
comparar_captura.py — Lee un JSON de la extensión "Captura SII" y lo cruza con lo que manda
`core/sii_mipyme.py`. Imprime el flujo en orden, los campos de cada POST clave y, si se pasa
`--evidencia <carpeta de storage/mipyme_fallidos/...>`, el diff campo a campo del envío.

Uso:  .venv/bin/python tools/captura-sii/comparar_captura.py captura.json [--evidencia carpeta]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

CLAVES = ("mipeGenFacEx", "mipeDisplayPreView", "mipePreView", "mipeGenXMLFirma", "postFirmaDigital",
          "mipeSendXML", "mipeGenDLNewEnvio", "mipeDisplayPDF", "CAutInicio", "mipeSelEmpresa")


def _pares_evidencia(body: str):
    """Pares del body guardado en la evidencia: desde 2026-10-08 es una sola línea
    x-www-form-urlencoded (como viaja); antes era "k=v" por línea, que partía los valores
    multilínea (el base64 de la firma aparecía como nombres falsos)."""
    if "\n" not in body.strip():
        return parse_qsl(body, keep_blank_values=True, encoding="latin-1", errors="replace")
    pares, actual = [], None
    for ln in body.split("\n"):
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", ln)
        if m:
            actual = [m.group(1), m.group(2)]; pares.append(actual)
        elif actual is not None:
            actual[1] += "\n" + ln
    return [tuple(p) for p in pares]


def campos_de(cuerpo: str | None, tipo_contenido: str = "") -> list[tuple[str, str]]:
    if not cuerpo:
        return []
    if "json" in (tipo_contenido or "") or cuerpo.lstrip().startswith("{"):
        try:
            return [(k, str(v)) for k, v in json.loads(cuerpo).items()]
        except ValueError:
            pass
    return parse_qsl(cuerpo, keep_blank_values=True, encoding="latin-1", errors="replace")


def normalizar(d: dict) -> list[dict]:
    """Deja las entradas v1 (debugger) y v2 (webRequest + página + xhr) con la misma forma:
    metodo, url, cabeceras, cuerpo (texto), respuesta{estado, cuerpo}, evento?."""
    if "peticiones" in d:
        return d["peticiones"]
    out = []
    paginas = [e for e in d["entradas"] if e.get("tipo") == "pagina"]
    for e in d["entradas"]:
        t = e.get("tipo")
        if t == "red":
            cuerpo = (e.get("cuerpo") or {}).get("texto") if isinstance(e.get("cuerpo"), dict) else e.get("cuerpo")
            # la "respuesta" de una navegación/form POST es el HTML de la página que llegó después
            html = next((pg.get("html") for pg in paginas if pg.get("t", 0) >= e.get("t", 0) and pg.get("momento") in ("load", "domcontentloaded")
                         and pg.get("marco") == "top" and e.get("recurso") in ("main_frame",)), None)
            out.append({"n": e["n"], "metodo": e.get("metodo", ""), "url": e.get("url", ""), "cabeceras": e.get("cabeceras") or {},
                        "cuerpo": cuerpo, "respuesta": {"estado": e.get("estado") or e.get("error"), "cuerpo": html,
                                                       "cabeceras": e.get("cabeceras_respuesta") or {}}, "redirige_a": e.get("redirige_a")})
        elif t == "xhr":
            out.append({"n": e["n"], "metodo": e.get("metodo", ""), "url": e.get("url", ""), "cabeceras": {"Content-Type": "ajax"},
                        "cuerpo": e.get("cuerpo"), "respuesta": {"estado": e.get("estado"), "cuerpo": e.get("respuesta")}})
        elif t == "pagina":
            out.append({"n": e["n"], "metodo": "PAG", "url": e.get("url", ""), "cabeceras": {}, "cuerpo": None,
                        "respuesta": {"estado": e.get("momento"), "cuerpo": e.get("html")}, "pagina": True})
    return out


def resumen_peticion(p: dict) -> str:
    r = p.get("respuesta") or {}
    cuerpo = (r.get("cuerpo") or "")
    pista = ""
    if "Request Rejected" in cuerpo:
        pista = "  ← WAF Request Rejected"
    elif re.search(r"Error al contribuyente|no ha sido bien recepcionado|Firma no reconocida", cuerpo):
        pista = "  ← ERROR del SII: " + re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", cuerpo))[:160]
    elif re.search(r"ENVIADO EXITOSAMENTE|Firmado y Enviado", cuerpo, re.I):
        pista = "  ← ÉXITO"
    return f"{p['n']:3} {p['metodo']:4} {str(r.get('estado', '---')):4} {urlsplit(p['url']).path.split('/')[-1] or p['url'][:50]}{pista}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("captura")
    ap.add_argument("--evidencia", help="carpeta storage/mipyme_fallidos/<rut>/T.._F.._<ts> del módulo")
    ap.add_argument("--todo", action="store_true", help="mostrar también las peticiones que no son clave")
    a = ap.parse_args()
    d = json.loads(Path(a.captura).read_text(encoding="utf-8"))
    pets = normalizar(d)
    print(f"Captura {d['inicio']} → {d['fin']} · {len(pets)} peticiones a sii.cl\n")
    print("Flujo:")
    for p in pets:
        if p.get("evento"):
            print(f"  {p['n']:3} [{p['evento']}: {p.get('razon')}] (se reconectó)"); continue
        if p.get("pagina") and not a.todo:
            continue
        if a.todo or any(k in p["url"] for k in CLAVES):
            print("  " + resumen_peticion(p))

    print("\nPOST clave, campo a campo (valor recortado):")
    por_cgi: dict[str, list[tuple[str, str]]] = {}
    for p in pets:
        if p.get("evento") or p["metodo"] != "POST":
            continue
        cgi = next((k for k in CLAVES if k in p["url"]), None)
        if not cgi:
            continue
        ct = (p.get("cabeceras") or {}).get("Content-Type") or (p.get("cabeceras") or {}).get("content-type") or ""
        pares = campos_de(p.get("cuerpo"), ct)
        por_cgi[cgi] = pares
        print(f"\n  [{p['n']}] {cgi}  ({len(pares)} campos, Content-Type: {ct or '?'}, Referer: {(p.get('cabeceras') or {}).get('Referer') or (p.get('cabeceras') or {}).get('referer') or '?'})")
        for k, v in pares:
            v1 = v.replace("\n", "\\n")
            print(f"      {k:28} = {v1[:70]!r}{'…' if len(v1) > 70 else ''}")
        r = p.get("respuesta") or {}
        if cgi in ("postFirmaDigital",):
            cuerpo = (r.get("cuerpo") or "").lstrip()
            forma = "JSON" if cuerpo.startswith("{") or cuerpo.startswith("while") else ("XML" if cuerpo.startswith("<") else "otro")
            print(f"      → respuesta {r.get('estado')} ({len(cuerpo)} B), forma: {forma}, empieza: {cuerpo[:90]!r}")

    if a.evidencia:
        ev = Path(a.evidencia)
        body = (ev / "body_envio.txt").read_text(encoding="latin-1") if (ev / "body_envio.txt").exists() else ""
        mios = re.findall(r"^([A-Za-z_][A-Za-z0-9_]*)=", body, re.M)
        nav = [k for k, _ in por_cgi.get("mipeSendXML", [])]
        if not nav or not mios:
            print("\n(no hay mipeSendXML en la captura o no hay body_envio.txt en la evidencia: sin diff)")
            return 0
        print("\nDiff del envío (mipeSendXML) navegador vs módulo:")
        print("  solo en el navegador:", [k for k in nav if k not in mios] or "—")
        print("  solo en el módulo:   ", [k for k in mios if k not in nav] or "—")
        comunes_nav = [k for k in nav if k in mios]
        comunes_mio = [k for k in mios if k in nav]
        print("  mismo orden:", comunes_nav == comunes_mio)
        if comunes_nav != comunes_mio:
            for i, (x, y) in enumerate(zip(comunes_nav, comunes_mio)):
                if x != y:
                    print(f"    primera diferencia de orden en la posición {i}: navegador={x} módulo={y}")
                    break
        # valores que difieren (sin los secretos ni los XML)
        vn = dict(por_cgi["mipeSendXML"])
        vm = dict(_pares_evidencia(body))
        difs = [k for k in comunes_nav if k not in ("txtPlainText", "txtSignText", "clave") and vn.get(k, "") != vm.get(k, "")]
        print("  valores distintos (sin XML ni clave):", difs or "—")
        for k in difs[:25]:
            print(f"    {k:26} navegador={vn.get(k, '')[:60]!r}  módulo={vm.get(k, '')[:60]!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
