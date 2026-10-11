#!/usr/bin/env python3
"""Prueba del mundo de práctica (core/simulacion.py): sin red, sin empresa real.

Emite una boleta, una factura y una nota de crédito con EMPRESA DEMO SPA, verifica folios,
totales, archivos y marcas en la BD, y reinicia. Correr: .venv/bin/python test_simulacion.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from core import simulacion as sim
from core.database import init_db
from core.models import obtener_dte, listar_dtes

init_db()   # en una máquina limpia (CI) la base todavía no existe

ok = 0
def check(cond, msg):
    global ok
    print(("  ✓ " if cond else "  ✗ ") + msg)
    if not cond:
        sys.exit(1)
    ok += 1

print("[1] Reiniciar el mundo demo")
r = sim.reiniciar(); check(isinstance(r, dict), f"reiniciado {r}")
e = sim.estado(); check(e["documentos"] == 0 and e["folios"]["39"]["siguiente"] == 1, "0 documentos, boleta siguiente = 1")

print("[2] Boleta de un café (1.190 con IVA incluido: en boletas el precio es bruto)")
b = sim.emitir(39, [{"nombre": "Café", "precio_unitario": 1190}])
check(b["folio"] == 1 and b["tipo_dte"] == 39, f"boleta folio {b['folio']}")
check((b["monto_neto"], b["iva"], b["monto_total"]) == (1000, 190, 1190), f"neto/IVA/total = {b['monto_neto']}/{b['iva']}/{b['monto_total']}")
check(b["ambiente"] == "simulacion" and b["estado"] == "simulado", "marcada como simulación")
check(b["pdf_b64"] and Path(b["pdf_path"]).exists() and "storage/simulacion/" in b["pdf_path"], f"PDF en {b['pdf_path']}")
d = obtener_dte(b["dte_id"]); check(d["xml_firmado"] and "<TED" in d["xml_firmado"] and "77777777-7" in d["xml_firmado"], "XML firmado con TED y RUT demo")

b2 = sim.emitir(39, [{"nombre": "Torta", "precio_unitario": 5950}])
check(b2["folio"] == 2 and b2["monto_total"] == 5950, f"segunda boleta folio {b2['folio']}, total {b2['monto_total']}")

print("[3] Factura a CLIENTE DEMO SPA (20.000 neto)")
f = sim.emitir(33, [{"nombre": "Café para reunión", "precio_unitario": 20000}])
check(f["folio"] == 1 and f["tipo_dte"] == 33 and f["receptor"] == "76111111-6", "factura folio 1 a 76111111-6 (serie aparte)")
check(f["monto_total"] == 23800 and f["iva"] == 3800, f"total {f['monto_total']}, IVA {f['iva']}")

print("[4] Factura exenta (taller 30.000)")
x = sim.emitir(34, [{"nombre": "Taller de pastelería", "precio_unitario": 30000}])
check(x["monto_exento"] == 30000 and x["iva"] == 0 and x["monto_total"] == 30000, "exenta: neto=total, IVA 0")

print("[5] Anular la boleta 1 con nota de crédito")
nc = sim.anular(b["dte_id"], "Era un café, no una torta")
check(nc["tipo_dte"] == 61 and nc["folio"] == 1 and nc["monto_total"] == 1190, f"NC folio {nc['folio']} por {nc['monto_total']}")
check(obtener_dte(b["dte_id"])["estado"] == "anulado_simulado", "la boleta queda marcada anulada (no borrada)")
check("<TpoDocRef>39</TpoDocRef>" in obtener_dte(nc["dte_id"])["xml_firmado"], "la NC referencia la boleta 39")
try:
    sim.anular(b["dte_id"]); check(False, "no debería anular dos veces")
except Exception as ex:
    check("ya fue anulado" in str(ex), "segunda anulación rechazada")

print("[6] Estado y aislamiento")
e = sim.estado()
check(e["documentos"] == 5 and e["folios"]["39"]["siguiente"] == 3 and e["folios"]["61"]["siguiente"] == 2, f"5 docs; boleta sigue en 3, NC en 2")
check(all(d["ambiente"] == "simulacion" for d in listar_dtes(rut_emisor="77777777-7")), "todos los docs demo marcados simulacion")
try:
    sim.ver(10**9); check(False, "ver de id ajeno")
except Exception as ex:
    check("no es de la simulación" in str(ex), "ver rechaza documentos ajenos")

print("[7] Reiniciar deja todo limpio")
r = sim.reiniciar()
check(r["documentos_borrados"] == 5 and sim.estado()["documentos"] == 0, f"borrados {r['documentos_borrados']}, quedan 0")
check(not list((Path("storage") / "simulacion" / "pdfs").glob("*.pdf")), "sin PDFs demo en disco")
print(f"\nTodo OK ({ok} checks)")
