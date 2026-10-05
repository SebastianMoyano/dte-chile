#!/usr/bin/env python3
"""
test_dorado.py — Corpus dorado: la salida del motor, byte a byte.

Con hora fija (core/reloj.py), certificado fijo y CAF fijos (tests/dorado/fixtures), el
pipeline de firma es determinista: misma entrada → mismos bytes de TED, DTE firmado y sobre.
Este script fija todo eso, corre la capa PURA del motor (sin BD, sin red) sobre los casos de
tests/dorado/casos/*.json y compara contra tests/dorado/esperado/<caso>/.

    .venv/bin/python test_dorado.py            # compara (falla al primer byte distinto)
    .venv/bin/python test_dorado.py --generar  # (re)escribe lo esperado — SOLO a propósito
    .venv/bin/python test_dorado.py --port "<comando>"   # prueba un PORT externo (ver abajo)
    .venv/bin/python test_dorado.py --port "<comando>" --parcial   # idem, pero solo lo que el port ya produce

Modo --port: por cada caso se ejecuta `<comando> <entrada.json> <fixtures/> <salida/>` con
RELOJ_FIJO en el entorno; el port debe dejar en <salida/> los archivos ted.xml, dte.xml y
envio.xml, y se comparan byte a byte contra lo esperado. Sirve para Go, Rust o lo que sea:
el contrato es solo archivos. Ejemplo que pasa: --port ".venv/bin/python tests/dorado/port_ejemplo.py"

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
from core.sobre import armar_sobre_firmado, firmar_documento_standalone  # noqa: E402

HORA_FIJA = "2026-01-15T10:30:00"
RESOLUCION = ("2026-01-01", 0)
RAIZ = Path(__file__).parent / "tests" / "dorado"
FIX, CASOS, ESPERADO = RAIZ / "fixtures", RAIZ / "casos", RAIZ / "esperado"


def _documento(d: dict, cert, es_boleta: bool):
    """Un DTE de principio a fin: totales → TED → XML → firma. Devuelve (ted, firmado, totales)."""
    from core.boleta import generar_documento_boleta
    from core.caf import ManejadorCAF
    from core.dte import DTEInput, GeneradorDTE, calcular_totales
    from core.simulacion import EMISOR_DEMO

    caf = ManejadorCAF((FIX / f"caf_{d['tipo_dte']}.xml").read_bytes())
    dte = DTEInput(tipo_dte=d["tipo_dte"], folio=d["folio"], fecha_emision=date.fromisoformat(d["fecha_emision"]),
                   emisor=EMISOR_DEMO, receptor=d["receptor"], items=d["items"],
                   referencias=d.get("referencias"), forma_pago=d.get("forma_pago", 1),
                   fecha_vencimiento=d.get("fecha_vencimiento"), indicador_servicio=d.get("indicador_servicio"),
                   observaciones=d.get("observaciones"))
    totales = calcular_totales(dte.items, dte.tipo_dte)
    ted = caf.generar_ted(folio=dte.folio, rut_emisor=dte.emisor.rut, rut_receptor=dte.receptor.rut,
                          tipo_dte=dte.tipo_dte.value, fecha_emision_dte=dte.fecha_emision,
                          monto_total=totales.monto_total, razon_social_receptor=dte.receptor.razon_social,
                          primer_item=dte.items[0].nombre)
    if es_boleta:
        doc = generar_documento_boleta(dte, ted_xml=ted, ind_servicio=d.get("ind_servicio"))
    else:
        doc = GeneradorDTE().generar_documento_xml(dte, ted_xml=ted)
    firmado = firmar_documento_standalone(doc, cert, dte.tipo_dte.value, dte.folio)
    return ted, firmado, totales


def correr_caso(caso: dict) -> dict[str, bytes]:
    """Capa pura del motor, en el mismo orden que core/orchestrator.py pero sin BD ni red.

    Un caso es un documento (campos al nivel raíz) o un sobre con varios (`documentos: [...]`).
    Salida: `ted.xml`, `dte.xml`, `totales.json` por documento (con sufijo `_N` si hay varios)
    y un único `envio.xml`."""
    from core.crypto import CertificadoDigital

    cert = CertificadoDigital((FIX / "cert_demo.p12").read_bytes(), "demo")
    docs = caso.get("documentos") or [caso]
    tipos = {d["tipo_dte"] for d in docs}
    es_boleta = tipos <= {39, 41}
    if not es_boleta and tipos & {39, 41}:
        raise ValueError("un sobre no mezcla boletas con otros DTE (EnvioBOLETA vs EnvioDTE)")
    salida: dict[str, bytes] = {}
    firmados = []
    subtotales: dict[int, int] = {}
    for i, d in enumerate(docs, 1):
        ted, firmado, totales = _documento(d, cert, es_boleta)
        suf = f"_{i}" if len(docs) > 1 else ""
        salida[f"ted{suf}.xml"] = ted.encode("ISO-8859-1")
        salida[f"dte{suf}.xml"] = firmado.encode("ISO-8859-1")
        salida[f"totales{suf}.json"] = json.dumps(totales.model_dump(), ensure_ascii=False, indent=1).encode("utf-8")
        firmados.append(firmado)
        subtotales[d["tipo_dte"]] = subtotales.get(d["tipo_dte"], 0) + 1
    salida["envio.xml"] = armar_sobre_firmado(
        documentos_firmados=firmados, subtotales=sorted(subtotales.items()),
        rut_emisor=docs[0]["emisor_rut"] if "emisor_rut" in docs[0] else "77777777-7",
        rut_envia=cert.rut_emisor, cert=cert,
        fecha_resolucion=RESOLUCION[0], numero_resolucion=RESOLUCION[1],
        raiz="EnvioBOLETA" if es_boleta else "EnvioDTE")
    return salida


def primer_byte_distinto(a: bytes, b: bytes) -> str:
    n = next((i for i, (x, y) in enumerate(zip(a, b)) if x != y), min(len(a), len(b)))
    ctx = lambda s: s[max(0, n - 40):n + 40].decode("ISO-8859-1", "replace")
    return f"byte {n} (largo {len(a)} vs {len(b)})\n      esperado: …{ctx(a)}…\n      obtenido: …{ctx(b)}…"


def correr_port(comando: str, caso_dir: Path) -> dict[str, bytes]:
    """Ejecuta un port externo sobre un caso y devuelve lo que dejó en su carpeta de salida."""
    import os
    import shlex
    import subprocess
    import tempfile
    with tempfile.TemporaryDirectory(prefix="dorado_port_") as tmp:
        env = dict(os.environ, RELOJ_FIJO=HORA_FIJA, DORADO_RESOLUCION_FECHA=RESOLUCION[0],
                   DORADO_RESOLUCION_NUMERO=str(RESOLUCION[1]))
        cmd = shlex.split(comando) + [str(caso_dir / "entrada.json"), str(FIX), tmp]
        r = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            raise RuntimeError(f"el port terminó con código {r.returncode}:\n{r.stderr[-2000:]}")
        return {q.name: q.read_bytes() for q in Path(tmp).iterdir() if q.suffix == ".xml"}


def main() -> int:
    generar = "--generar" in sys.argv
    port = sys.argv[sys.argv.index("--port") + 1] if "--port" in sys.argv else None
    parcial = "--parcial" in sys.argv   # con --port: compara solo lo que el port produjo (port a medio camino)
    if not (FIX / "cert_demo.p12").exists():
        print("Faltan los fixtures: .venv/bin/python tests/dorado/generar_fixtures.py"); return 2
    reloj.fijar(HORA_FIJA)
    casos = sorted(CASOS.glob("*.json"))
    fallos = 0
    for ruta in casos:
        caso = json.loads(ruta.read_text(encoding="utf-8"))
        nombre = ruta.stem
        if port:
            carpeta = ESPERADO / nombre
            try:
                salida = correr_port(port, carpeta)
            except Exception as e:  # noqa: BLE001 — se reporta por caso y se sigue
                print(f"✗ {nombre}: {e}"); fallos += 1; continue
            pedidos = [q.name for q in carpeta.iterdir() if q.suffix == ".xml"]
            faltan = [] if parcial else [k for k in pedidos if k not in salida]
            if parcial and not salida:
                print(f"✗ {nombre}: el port no produjo ningún .xml"); fallos += 1; continue
            malos = [k for k, v in salida.items() if k in pedidos and (carpeta / k).read_bytes() != v]
            if faltan or malos:
                fallos += 1
                print(f"✗ {nombre}: " + (f"no produjo {', '.join(faltan)}. " if faltan else "") + (f"difiere en {', '.join(malos)}" if malos else ""))
                for k in malos:
                    print(f"    {k}: " + primer_byte_distinto((carpeta / k).read_bytes(), salida[k]))
            else:
                hechos = ", ".join(k for k in pedidos if k in salida)
                print(f"✓ {nombre}: el port produce bytes idénticos" + (f" ({hechos})" if parcial else ""))
            continue
        salida = correr_caso(caso)
        # Determinismo dentro del proceso: dos corridas, mismos bytes.
        if correr_caso(caso) != salida:
            print(f"✗ {nombre}: la salida NO es determinista entre dos corridas"); fallos += 1; continue
        if any(HORA_FIJA.encode() not in v for k, v in salida.items() if k.endswith(".xml")):
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
        esperados = {q.name for q in carpeta.iterdir() if q.name != "entrada.json"}
        malos = [k for k, v in salida.items() if not (carpeta / k).exists() or (carpeta / k).read_bytes() != v]
        malos += sorted(esperados - set(salida))
        if malos:
            fallos += 1
            print(f"✗ {nombre}: difiere en {', '.join(malos)}")
            for k in malos:
                if k in salida and (carpeta / k).exists():
                    print(f"    {k}: " + primer_byte_distinto((carpeta / k).read_bytes(), salida[k]))
        else:
            print(f"✓ {nombre}: idéntico byte a byte ({len(salida['envio.xml'])} bytes de sobre)")
    print(f"\n{len(casos) - fallos}/{len(casos)} casos {'escritos' if generar else 'idénticos'}" + (" (port externo)" if port else ""))
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
