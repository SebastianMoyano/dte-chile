#!/usr/bin/env python3
"""Esperado para el port del set de certificación (nucleo/certificacion): los 16 casos de
`certificacion_sii.definir_casos()` generados por `certificacion_sii.generar_dte` con el
certificado y los CAF FICTICIOS del corpus (EMPRESA DEMO SPA, 77.777.777-7) y hora fija. Go
debe producir los mismos bytes. También exporta los casos a casos.json (única fuente: el
script Python). L15: no regenerar para que un test pase."""
import json
import sys
from datetime import date, datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(RAIZ))
AQUI = Path(__file__).parent
FECHA = date(2026, 1, 15)
MARCA = "2026-01-15T10:30:00"

import certificacion_sii as cs  # noqa: E402
from core import reloj  # noqa: E402
from core.caf import ManejadorCAF  # noqa: E402
from core.crypto import CertificadoDigital  # noqa: E402
from core.dte import EmisorModel, ReceptorModel  # noqa: E402


class _Date(date):
    @classmethod
    def today(cls):
        return FECHA


class _Datetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return datetime.fromisoformat(MARCA)


def main():
    cs.date, cs.datetime = _Date, _Datetime   # date.today() y datetime.now() del script
    reloj.fijar(MARCA)                         # TmstFirma del generador
    casos = cs.definir_casos()
    exportados = []
    for c in casos:
        e = {"nombre": c["nombre"], "tipo_dte": c["tipo_dte"].value, "folio": c["folio"],
             "items": [{"nombre": i["nombre"], "cantidad": i["cantidad"], "precio": i["precio"], "descuento_pct": i.get("descuento_pct", 0),
                        "exento": i.get("exento", False), "unidad": i.get("unidad", "")} for i in c.get("items", [])]}
        if c.get("referencia"):
            r = c["referencia"]
            e["referencia"] = {"tipo_dte_ref": r["tipo_dte_ref"].value, "folio_ref": r["folio_ref"], "razon": r["razon"]}
        exportados.append(e)
    (AQUI / "casos.json").write_text(json.dumps(exportados, ensure_ascii=False, indent=1), encoding="utf-8")
    cert = CertificadoDigital((RAIZ / "tests/dorado/fixtures/cert_demo.p12").read_bytes(), "demo")
    cafs = {t: ManejadorCAF((RAIZ / f"tests/dorado/fixtures/caf_{t}.xml").read_bytes()) for t in (33, 34, 56, 61)}
    emisor = EmisorModel(rut="77777777-7", razon_social="EMPRESA DEMO SPA", giro=cs.GIRO, codigo_actividad=cs.CODIGO_ACTIVIDAD,
                         direccion=cs.DIRECCION, comuna=cs.COMUNA, ciudad=cs.CIUDAD, email="contacto@ejemplo.cl")
    receptor = ReceptorModel(rut=cs.RUT_RECEPTOR, razon_social=cs.RAZON_SOCIAL_RECEPTOR, giro=cs.GIRO_RECEPTOR,
                             direccion=cs.DIRECCION_RECEPTOR, comuna=cs.COMUNA_RECEPTOR, ciudad=cs.CIUDAD_RECEPTOR)
    salida = AQUI / "esperado"
    salida.mkdir(exist_ok=True)
    for c in casos:
        xml = cs.generar_dte(c, emisor, receptor, cafs[c["tipo_dte"].value], cert)
        (salida / f"{c['nombre']}_T{c['tipo_dte'].value}_F{c['folio']}.xml").write_bytes(xml)
    (AQUI / "parametros.json").write_text(json.dumps({"fecha": FECHA.isoformat(), "marca": MARCA, "rut": "77777777-7",
                                                      "razon_social": "EMPRESA DEMO SPA", "email": "contacto@ejemplo.cl"}, indent=1))
    print("escritos", len(casos), "sobres en", salida)


if __name__ == "__main__":
    main()
