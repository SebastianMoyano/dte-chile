#!/usr/bin/env python3
"""Gate de la mini academia (app/frontend/dist/academia.js).

Revisa que cada lección tenga lo que la app espera (módulo existente, id único, concepto con
al menos dos párrafos, ejemplo, pregunta con 4 opciones y respuesta válida, acción a una vista
real, y la secuencia de pasos: adivina opcional al inicio, ideas, una sola pregunta, misión
opcional a una vista real, cierre con 1 a 3 claves; los números vivos data-vivo solo neto/iva/total),
que no haya RUTs reales (L14) y que el texto no use regionalismos vetados. Con --md
escribe docs/aprender/LECCIONES.md a partir de los mismos datos, para leer fuera de la app.

Uso: .venv/bin/python tools/revisar_academia.py [--md]
"""
import json, re, sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
JS = RAIZ / "app/frontend/dist/academia.js"
VIS = RAIZ / "app/frontend/dist/academia-vis.js"
MD = RAIZ / "docs/aprender/LECCIONES.md"
VISTAS = {"inicio", "cobrar", "documentos", "documentos?tab=mes", "aprender", "ajustes", "empresa", "valores", "ia"}
RUTS_PERMITIDOS = {"77777777-7", "76111111-6", "12345678-5", "66666666-6", "11111111-1"}
VETADAS = re.compile(r"\b(apretar|apreta|apriete|plata\s+cobra|cachai|po\b|al\s+tiro)", re.I)
TIPOS_PASO = {"adivina", "idea", "pregunta", "mision", "cierre"}
VIVOS = {"neto", "iva", "total"}
RUT = re.compile(r"\b(\d{1,2}\.?\d{3}\.?\d{3})-([\dkK])\b")


def cargar():
    t = JS.read_text(encoding="utf-8")
    i = t.index("window.ACADEMIA = ") + len("window.ACADEMIA = ")
    return json.loads(t[i:].rstrip().rstrip(";"))


def revisar(d):
    errs = []
    mods = {m["id"] for m in d["modulos"]}
    ids = set()
    for l in d["lecciones"]:
        donde = f"lección {l.get('id')}"
        if l["modulo"] not in mods: errs.append(f"{donde}: módulo desconocido {l['modulo']}")
        if l["id"] in ids: errs.append(f"{donde}: id repetido")
        ids.add(l["id"])
        for k in ("titulo", "resumen", "concepto", "ejemplo", "pregunta"):
            if not l.get(k): errs.append(f"{donde}: falta {k}")
        if l["concepto"].count("<p>") < 2: errs.append(f"{donde}: el concepto debe tener al menos dos párrafos")
        if "<p>" not in l["ejemplo"]: errs.append(f"{donde}: el ejemplo va en un párrafo")
        p = l["pregunta"]
        if len(p.get("o", [])) != 4: errs.append(f"{donde}: la pregunta debe tener 4 opciones")
        if not isinstance(p.get("c"), int) or not 0 <= p["c"] < 4: errs.append(f"{donde}: respuesta correcta fuera de rango")
        if not p.get("x"): errs.append(f"{donde}: falta la explicación de la pregunta")
        if l.get("accion") and l["accion"]["v"] not in VISTAS: errs.append(f"{donde}: acción a vista desconocida {l['accion']['v']}")
        # la secuencia de pasos
        P = l.get("pasos") or []
        if not P: errs.append(f"{donde}: sin pasos")
        tipos = [x.get("tipo") for x in P]
        if any(t not in TIPOS_PASO for t in tipos): errs.append(f"{donde}: tipo de paso desconocido {tipos}")
        if tipos.count("pregunta") != 1: errs.append(f"{donde}: debe haber exactamente una pregunta en los pasos")
        if tipos.count("adivina") > 1 or ("adivina" in tipos and tipos[0] != "adivina"): errs.append(f"{donde}: la adivinanza va primero y es una sola")
        if not tipos or tipos[-1] != "cierre": errs.append(f"{donde}: el último paso debe ser el cierre")
        for x in P:
            t = x.get("tipo")
            if t in ("adivina", "pregunta"):
                if len(x.get("o", [])) != 4 or not isinstance(x.get("c"), int) or not 0 <= x["c"] < 4 or not x.get("x"): errs.append(f"{donde}: {t} mal formada")
                if x.get("xo") is not None and (len(x["xo"]) != 4 or x["xo"][x["c"]] is not None or any(not v for k, v in enumerate(x["xo"]) if k != x["c"])):
                    errs.append(f"{donde}: xo debe tener 4 entradas, con None en la correcta y texto en las otras")
            if t == "idea" and not x.get("h"): errs.append(f"{donde}: idea sin texto")
            if t == "idea":
                for v in re.findall(r'data-vivo="([^"]+)"', x["h"]):
                    if v not in VIVOS: errs.append(f"{donde}: número vivo desconocido {v}")
            if t == "mision":
                if x.get("v") not in VISTAS: errs.append(f"{donde}: misión a vista desconocida {x.get('v')}")
                if x.get("check") and not set(x["check"]) <= {"tipo", "total"}: errs.append(f"{donde}: check de misión desconocido {x['check']}")
            if t == "cierre" and not 1 <= len(x.get("claves") or []) <= 3: errs.append(f"{donde}: el cierre lleva de 1 a 3 claves")
        extra = " ".join(str(v) for x in P for v in x.values() if isinstance(v, str)) + " " + " ".join(str(v) for x in P for v in (x.get("o") or []) + (x.get("claves") or []) + [y for y in (x.get("xo") or []) if y])
        texto = " ".join([l["titulo"], l["resumen"], l["concepto"], l["ejemplo"], p["t"], *p["o"], p["x"], extra])
        for m in RUT.finditer(texto):
            rut = m.group(1).replace(".", "") + "-" + m.group(2).upper()
            if rut not in RUTS_PERMITIDOS: errs.append(f"{donde}: RUT no permitido {rut} (L14)")
        if VETADAS.search(texto): errs.append(f"{donde}: regionalismo vetado ({VETADAS.search(texto).group(0)})")
    for m in d["modulos"]:
        if not any(l["modulo"] == m["id"] for l in d["lecciones"]): errs.append(f"módulo {m['id']} sin lecciones")
    # cada lección tiene su visual interactivo (VIS.id = … o VIS["id"] = …)
    vis = VIS.read_text(encoding="utf-8")
    con_vis = set(re.findall(r'VIS\.([a-z0-9-]+)\s*=', vis)) | set(re.findall(r'VIS\["([a-z0-9-]+)"\]\s*=', vis))
    for l in d["lecciones"]:
        if l["id"] not in con_vis: errs.append(f"lección {l['id']}: sin visual en academia-vis.js")
    return errs


def a_md(d):
    sin = lambda h: re.sub(r"<[^>]+>", "", h).replace("&nbsp;", " ")
    parrafos = lambda h: "\n\n".join(sin(p) for p in re.findall(r"<p>(.*?)</p>", h, re.S))
    out = ["# Mini academia: las lecciones", "",
           "> Generado desde `app/frontend/dist/academia.js` con `tools/revisar_academia.py --md`. No se edita a mano:",
           "> se edita `tools/academia_datos.py` y se vuelve a generar. Mismo texto que ve el alumno en la app.", ""]
    for i, m in enumerate(d["modulos"], 1):
        out += [f"## {i}. {m['titulo']}", "", m["resumen"], ""]
        for l in [x for x in d["lecciones"] if x["modulo"] == m["id"]]:
            out += [f"### {l['titulo']}", "", f"*{l['resumen']}*", ""]
            ad = next((x for x in l.get("pasos", []) if x["tipo"] == "adivina"), None)
            if ad: out += [f"**Antes de leer, adivina.** {ad['t']}", ""] + [f"- {'**' if k == ad['c'] else ''}{o}{'**' if k == ad['c'] else ''}" for k, o in enumerate(ad["o"])] + ["", f"*{ad['x']}*", ""]
            out += [parrafos(l["concepto"]), "", "**Un ejemplo.** " + parrafos(l["ejemplo"]), ""]
            if l.get("accion"): out += [f"**Hazlo en la app:** {l['accion']['t']} (`#{l['accion']['v']}`).", ""]
            p = l["pregunta"]
            out += [f"**Pregunta.** {p['t']}", ""] + [f"- {'**' if k == p['c'] else ''}{o}{'**' if k == p['c'] else ''}" for k, o in enumerate(p["o"])] + ["", f"*{p['x']}*", ""]
            ci = next((x for x in l.get("pasos", []) if x["tipo"] == "cierre"), None)
            if ci: out += ["**Lo que te llevas.**", ""] + [f"- {c}" for c in ci["claves"]] + [""]
    return "\n".join(out)


if __name__ == "__main__":
    d = cargar()
    errs = revisar(d)
    n = len(d["lecciones"])
    if errs:
        print("\n".join("✗ " + e for e in errs)); print(f"{len(errs)} problema(s) en {n} lecciones"); sys.exit(1)
    if "--md" in sys.argv:
        MD.write_text(a_md(d), encoding="utf-8"); print(f"escrito {MD.relative_to(RAIZ)}")
    ad = sum(1 for l in d["lecciones"] if any(x["tipo"] == "adivina" for x in l["pasos"]))
    print(f"academia ok: {n} lecciones en {len(d['modulos'])} módulos, {ad} con pregunta de apertura, {sum(1 for l in d['lecciones'] if l.get('accion'))} con misión en la app, todas con visual y pasos")
