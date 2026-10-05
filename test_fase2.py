#!/usr/bin/env python3
"""
test_fase2.py — Fase 2 del port: Python y Go emiten sobre la MISMA base y el MISMO storage.

Comprueba, en una base temporal (nunca la real):
  1. Alternando Go → Python → Go → Python, los folios salen 1, 2, 3, 4 (sin repetir ni saltar)
     y cada fila de `dtes` tiene lo mismo venga de donde venga.
  2. Lo que Go dejó en disco (DTE firmado y sobre) es byte a byte lo que Python produce con
     ese mismo folio y esa misma hora (el pipeline puro del corpus dorado).
  3. Bajo concurrencia (procesos Go y hilos Python a la vez) no hay folios duplicados ni huecos.
  4. Los sobres de Go validan contra el XSD oficial.

Correr: .venv/bin/python test_fase2.py   (necesita nucleo/bin/nucleo-emitir compilado)
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

RAIZ = Path(__file__).parent
TMP = Path(tempfile.mkdtemp(prefix="fase2_"))
DB = TMP / "fase2.db"
STORAGE = TMP / "storage"
os.environ["DATABASE_URL"] = f"sqlite:///{DB}"   # ANTES de importar core: la base real no se toca
os.environ["RELOJ_FIJO"] = "2026-01-15T10:30:00"
sys.path.insert(0, str(RAIZ))

from core import database, reloj  # noqa: E402
from core.crypto import CertificadoDigital  # noqa: E402
from core.dte import DTEInput  # noqa: E402
from core.models import listar_dtes, registrar_caf  # noqa: E402
from core.orchestrator import emitir_documento  # noqa: E402
from core.resolucion import fijar_resolucion_local  # noqa: E402
from core.schema_validator import validar_xml_dte_strict  # noqa: E402
from core.simulacion import EMISOR_DEMO, RUT_DEMO  # noqa: E402
import test_dorado as td  # noqa: E402

assert str(database.DATABASE_PATH) == str(DB), f"la base no es la temporal: {database.DATABASE_PATH}"
GO = RAIZ / "nucleo" / "bin" / "nucleo-emitir"
FIX = RAIZ / "tests" / "dorado" / "fixtures"
CERT = CertificadoDigital((FIX / "cert_demo.p12").read_bytes(), "demo")
RES = ("2026-01-01", 0)
ok = 0


def check(cond, msg):
    global ok
    print(("  ✓ " if cond else "  ✗ ") + msg)
    if not cond:
        sys.exit(1)
    ok += 1


def caso(tipo, folio=0):
    es_boleta = tipo in (39, 41)
    return {"tipo_dte": tipo, "folio": folio, "fecha_emision": "2026-01-15",
            "receptor": {"rut": "66666666-6", "razon_social": "CONSUMIDOR FINAL", "es_contribuyente": False} if es_boleta
            else {"rut": "76111111-6", "razon_social": "CLIENTE DEMO SPA", "giro": "Oficina", "direccion": "Avenida Imaginaria 456", "comuna": "Providencia", "ciudad": "Santiago"},
            "items": [{"numero_linea": 1, "nombre": "Café", "cantidad": 1, "precio_unitario": 1190 if es_boleta else 20000}]}


def emitir_go(tipo, folio=0):
    c = dict(caso(tipo, folio), emisor=EMISOR_DEMO.model_dump())
    r = subprocess.run([str(GO), "--db", str(DB), "--storage", str(STORAGE), "--cert", str(FIX / "cert_demo.p12"),
                        "--ambiente", "certificacion", "--resolucion-fecha", RES[0], "--resolucion-numero", str(RES[1])],
                       input=json.dumps(c), capture_output=True, text=True,
                       env=dict(os.environ, NUCLEO_CERT_CLAVE="demo"))
    if r.returncode != 0:
        raise RuntimeError("Go falló: " + r.stderr)
    return json.loads(r.stdout)


def emitir_py(tipo, folio=0):
    c = caso(tipo, folio)
    dte = DTEInput(tipo_dte=tipo, folio=folio, fecha_emision=c["fecha_emision"], emisor=EMISOR_DEMO,
                   receptor=c["receptor"], items=c["items"], forma_pago=1)
    return emitir_documento(dte, certificado=CERT, storage_base=STORAGE, ambiente="certificacion")


def bytes_puros(tipo, folio):
    """Lo que el pipeline puro (corpus dorado) produce para ese folio: (dte, envio)."""
    reloj.fijar(os.environ["RELOJ_FIJO"])
    td.FIX, td.RESOLUCION = FIX, RES
    s = td.correr_caso(caso(tipo, folio))
    return s["dte.xml"], s["envio.xml"]


print(f"[0] Base temporal {DB}")
database.init_db()
fijar_resolucion_local(RUT_DEMO, *RES)
reloj.fijar(os.environ["RELOJ_FIJO"])
for t in (33, 39):
    registrar_caf(tipo_dte=t, rut_emisor=RUT_DEMO, folio_desde=1, folio_hasta=1000, fecha_autorizacion="2026-01-01",
                  caf_xml=(FIX / f"caf_{t}.xml").read_text(encoding="iso-8859-1"))
check(GO.exists(), "nucleo-emitir compilado")

print("[1] Alternar Go → Python → Go → Python (boleta 39) y Go → Python (factura 33)")
secuencia = [("go", emitir_go(39)), ("py", emitir_py(39)), ("go", emitir_go(39)), ("py", emitir_py(39))]
folios = [r["folio"] for _, r in secuencia]
check(folios == [1, 2, 3, 4], f"folios de boleta en orden: {folios}")
f33 = [emitir_go(33)["folio"], emitir_py(33)["folio"]]
check(f33 == [1, 2], f"folios de factura en orden (serie aparte): {f33}")
filas = {(d["tipo_dte"], d["folio"]): d for d in listar_dtes(rut_emisor=RUT_DEMO)}
check(len(filas) == 6, f"6 filas en dtes")
check(all(d["estado"] == "generado" and d["ambiente"] == "certificacion" and d["xml_firmado"] and d["monto_total"] for d in filas.values()),
      "todas con estado generado, ambiente, xml_firmado y total")
check(filas[(39, 1)]["monto_total"] == 1190 == filas[(39, 2)]["monto_total"] and filas[(33, 1)]["monto_total"] == 23800 == filas[(33, 2)]["monto_total"],
      "mismos totales vengan de Go o de Python")

print("[2] Lo que Go dejó en disco == pipeline puro de Python con el mismo folio y hora")
for tipo, folio, pdoc, penv in ((39, 1, "BOLETA", "EnvioBOLETA"), (39, 3, "BOLETA", "EnvioBOLETA"), (33, 1, "DTE", "EnvioDTE")):
    dte_go = (STORAGE / "dtes" / f"{pdoc}_{tipo}_{folio}.xml").read_bytes()
    env_go = (STORAGE / "dtes" / f"{penv}_{tipo}_{folio}.xml").read_bytes()
    dte_py, env_py = bytes_puros(tipo, folio)
    check(dte_go == dte_py, f"{pdoc} {tipo}/{folio} de Go idéntico al puro ({len(dte_go)} bytes)")
    check(env_go == env_py, f"{penv} {tipo}/{folio} de Go idéntico al puro ({len(env_go)} bytes)")
    check(filas[(tipo, folio)]["xml_firmado"].encode("ISO-8859-1") == dte_go, f"xml_firmado en BD (fila de Go) == archivo")
# y el orquestador Python real también coincide con el puro (el harness refleja al motor)
dte_py2, _ = bytes_puros(39, 2)
check((STORAGE / "dtes" / "BOLETA_39_2.xml").read_bytes() == dte_py2, "el orquestador Python (folio 2) == pipeline puro")
check(filas[(39, 1)]["xml_firmado"] != filas[(39, 2)]["xml_firmado"], "folios distintos → XML distintos (no se pisó nada)")

print("[3] Concurrencia: 3 procesos Go × 15 + 3 hilos Python × 15 emisiones a la vez (boleta)")
antes = max(d["folio"] for d in listar_dtes(rut_emisor=RUT_DEMO, tipo_dte=39))
errores = []


def lote_go():
    for _ in range(15):
        try:
            emitir_go(39)
        except Exception as e:  # noqa: BLE001
            errores.append(f"go: {e}")


def lote_py():
    for _ in range(15):
        try:
            emitir_py(39)
        except Exception as e:  # noqa: BLE001
            errores.append(f"py: {e}")


hilos = [threading.Thread(target=lote_go) for _ in range(3)] + [threading.Thread(target=lote_py) for _ in range(3)]
for h in hilos:
    h.start()
for h in hilos:
    h.join()
check(not errores, f"sin errores de emisión ({len(errores)}: {errores[:2]})")
fol = sorted(d["folio"] for d in listar_dtes(rut_emisor=RUT_DEMO, tipo_dte=39, limite=1000))
check(len(fol) == len(set(fol)), f"sin folios duplicados ({len(fol)} boletas)")
check(fol == list(range(1, antes + 90 + 1)), f"sin huecos: 1..{fol[-1]}")

print("[4] XSD de los sobres de Go")
for tipo, folio, penv in ((39, 1, "EnvioBOLETA"), (39, 3, "EnvioBOLETA"), (33, 1, "EnvioDTE")):
    validar_xml_dte_strict((STORAGE / "dtes" / f"{penv}_{tipo}_{folio}.xml").read_bytes())
check(True, "los 3 sobres de Go validan contra el XSD oficial")

print("[5] El camino de la app: nucleo-emitir --contexto (certificado en PEM, como lo entrega el keystore)")
ctx = {"rut": RUT_DEMO, "ambiente": "certificacion", "resolucion": {"fecha": RES[0], "numero": RES[1]},
       "cert_pem": (FIX / "cert_demo.cert.pem").read_text(), "key_pem": (FIX / "cert_demo.key.pem").read_text(),
       "database_path": str(DB), "storage_path": str(STORAGE)}
(TMP / "contexto.json").write_text(json.dumps(ctx))
c = dict(caso(33), emisor=EMISOR_DEMO.model_dump())
r = subprocess.run([str(GO), "--contexto", str(TMP / "contexto.json")], input=json.dumps(c), capture_output=True, text=True, env=dict(os.environ))
check(r.returncode == 0, f"emite con contexto PEM: {r.stderr.strip()[-200:] or 'ok'}")
res = json.loads(r.stdout)
dte_go = (STORAGE / "dtes" / f"DTE_33_{res['folio']}.xml").read_bytes()
dte_py, _ = bytes_puros(33, res["folio"])
check(dte_go == dte_py, f"factura {res['folio']} por el camino de la app == pipeline puro")

shutil.rmtree(TMP, ignore_errors=True)
print(f"\nTodo OK ({ok} checks)")
