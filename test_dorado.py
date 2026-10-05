#!/usr/bin/env python3
"""
test_dorado.py — Corpus dorado: la salida del motor, byte a byte.

Con hora fija (core/reloj.py), certificado fijo y CAF fijos (tests/dorado/fixtures), el
pipeline de firma es determinista: misma entrada → mismos bytes de TED, DTE firmado y sobre.
Este script fija todo eso, corre la capa PURA del motor (sin BD, sin red) sobre los casos de
tests/dorado/casos/*.json y compara contra tests/dorado/esperado/<caso>/.

    .venv/bin/python test_dorado.py            # compara (falla al primer byte distinto)
    .venv/bin/python test_dorado.py --generar  # (re)escribe lo esperado — SOLO a propósito

Para qué sirve:
  1. Un cambio en el motor que altere un byte de la salida se nota al instante.
  2. Cualquier port (Go, Rust, lo que sea) se prueba contra los mismos archivos: debe producir
     exactamente estos bytes a partir de estas entradas, ANTES de hablar con el SII.
Ver docs/DORADO.md.
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from core import reloj  # noqa: E402

HORA_FIJA = "2026-01-15T10:30:00"
RESOLUCION = ("2026-01-01", 0)
RAIZ = Path(__file__).parent / "tests" / "dorado"
FIX, CASOS, ESPERADO = RAIZ / "fixtures", RAIZ / "casos", RAIZ / "esperado"


def correr_caso(caso: dict) -> dict[str, bytes]:
    """Capa pura del motor, en el mismo orden que core/orchestrator.py pero sin BD ni red."""
    from core.boleta import generar_documento_boleta
    from core.caf import ManejadorCAF
    from core.crypto import CertificadoDigital
    from core.dte import DTEInput, GeneradorDTE, calcular_totales
    from core.simulacion import EMISOR_DEMO
    from core.sobre import armar_sobre_firmado, firmar_documento_standalone

    cert = CertificadoDigital((FIX / "cert_demo.p12").read_bytes(), "demo")
    caf = ManejadorCAF((FIX / f"caf_{caso['tipo_dte']}.xml").read_bytes())
    dte = DTEInput(tipo_dte=caso["tipo_dte"], folio=caso["folio"], fecha_emision=date.fromisoformat(caso["fecha_emision"]),
                   emisor=EMISOR_DEMO, receptor=caso["receptor"], items=caso["items"],
                   referencias=caso.get("referencias"), forma_pago=1)
    totales = calcular_totales(dte.items, dte.tipo_dte)
    ted = caf.generar_ted(folio=dte.folio, rut_emisor=dte.emisor.rut, rut_receptor=dte.receptor.rut,
                          tipo_dte=dte.tipo_dte.value, fecha_emision_dte=dte.fecha_emision,
                          monto_total=totales.monto_total, razon_social_receptor=dte.receptor.razon_social,
                          primer_item=dte.items[0].nombre)
    es_boleta = dte.tipo_dte.value in (39, 41)
    doc = generar_documento_boleta(dte, ted_xml=ted) if es_boleta else GeneradorDTE().generar_documento_xml(dte, ted_xml=ted)
    firmado = firmar_documento_standalone(doc, cert, dte.tipo_dte.value, dte.folio)
    envio = armar_sobre_firmado(documentos_firmados=[firmado], subtotales=[(dte.tipo_dte.value, 1)],
                                rut_emisor=dte.emisor.rut, rut_envia=cert.rut_emisor, cert=cert,
                                fecha_resolucion=RESOLUCION[0], numero_resolucion=RESOLUCION[1],
                                raiz="EnvioBOLETA" if es_boleta else "EnvioDTE")
    return {"ted.xml": ted.encode("ISO-8859-1"), "dte.xml": firmado.encode("ISO-8859-1"), "envio.xml": envio,
            "totales.json": json.dumps(totales.model_dump(), ensure_ascii=False, indent=1).encode("utf-8")}


def primer_byte_distinto(a: bytes, b: bytes) -> str:
    n = next((i for i, (x, y) in enumerate(zip(a, b)) if x != y), min(len(a), len(b)))
    ctx = lambda s: s[max(0, n - 40):n + 40].decode("ISO-8859-1", "replace")
    return f"byte {n} (largo {len(a)} vs {len(b)})\n      esperado: …{ctx(a)}…\n      obtenido: …{ctx(b)}…"


def main() -> int:
    generar = "--generar" in sys.argv
    if not (FIX / "cert_demo.p12").exists():
        print("Faltan los fixtures: .venv/bin/python tests/dorado/generar_fixtures.py"); return 2
    reloj.fijar(HORA_FIJA)
    casos = sorted(CASOS.glob("*.json"))
    fallos = 0
    for ruta in casos:
        caso = json.loads(ruta.read_text(encoding="utf-8"))
        nombre = ruta.stem
        salida = correr_caso(caso)
        # Determinismo dentro del proceso: dos corridas, mismos bytes.
        if correr_caso(caso) != salida:
            print(f"✗ {nombre}: la salida NO es determinista entre dos corridas"); fallos += 1; continue
        if HORA_FIJA.encode() not in salida["dte.xml"] or HORA_FIJA.encode() not in salida["envio.xml"]:
            print(f"✗ {nombre}: la hora fija no aparece en la salida (¿un datetime.now() fuera del reloj?)"); fallos += 1; continue
        carpeta = ESPERADO / nombre
        if generar:
            carpeta.mkdir(parents=True, exist_ok=True)
            (carpeta / "entrada.json").write_text(json.dumps(caso, ensure_ascii=False, indent=1), encoding="utf-8")
            for k, v in salida.items():
                (carpeta / k).write_bytes(v)
            print(f"✓ {nombre}: esperado escrito ({', '.join(salida)})")
            continue
        if not carpeta.exists():
            print(f"✗ {nombre}: no hay esperado (corre con --generar)"); fallos += 1; continue
        malos = [k for k, v in salida.items() if (carpeta / k).read_bytes() != v]
        if malos:
            fallos += 1
            print(f"✗ {nombre}: difiere en {', '.join(malos)}")
            for k in malos:
                print(f"    {k}: " + primer_byte_distinto((carpeta / k).read_bytes(), salida[k]))
        else:
            print(f"✓ {nombre}: idéntico byte a byte ({len(salida['envio.xml'])} bytes de sobre)")
    print(f"\n{len(casos) - fallos}/{len(casos)} casos {'escritos' if generar else 'idénticos'}")
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
