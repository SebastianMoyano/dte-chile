#!/usr/bin/env python3
"""Esperado para el port del RCV (nucleo/rcv): normalización del facade (CSV del Export y
dicts), el payload del cliente (sin el uuid), la persistencia + agregación F29 y el mapeo a
casilleros, con datos FICTICIOS. Go debe producir el mismo JSON. L15."""
import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(RAIZ))
AQUI = Path(__file__).parent
# base temporal para que guardar_documentos/calcular_desglose_f29 trabajen sobre algo limpio
tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{tmp}/rcv.db"

from core import rcv  # noqa: E402

CSV_VENTAS = {"data": [
    "Nro;Tipo Doc;Tipo Compra;RUT cliente;Razon Social;Folio;Fecha Docto;Fecha Recepcion;Monto Exento;Monto Neto;Monto IVA;Monto Total;IVA Retenido Total;Monto Neto Activo Fijo",
    "1;33;;76111111-6;CLIENTE DEMO SPA;12;15/01/2026;15/01/2026 10:00;0;100000;19000;119000;0;",
    "2;34;;76111111-6;CLIENTE DEMO SPA;3;20/01/2026;20/01/2026;50000;0;0;50000;0;",
    "3;61;;76111111-6;CLIENTE DEMO SPA;7;25/01/2026;25/01/2026;0;20000;3800;23800;0;",
    "4;39;;66666666-6;;100;26/01/2026;;0;10000;1900;11900;0;",
    "5;56;;76111111-6;CLIENTE DEMO SPA;2;27-01-2026;;0;5000;950;5950;0;",
    "6;33;;76111111-6;SIN FOLIO;;28/01/2026;;0;1;0;1;0;",
    "",
]}
DICT_COMPRAS = {"data": [
    {"detTipoDoc": 33, "detNroDoc": 501, "detFchDoc": "2026-01-10", "detRutDoc": 12345678, "detDvDoc": "5", "detRznSoc": "PROVEEDOR UNO",
     "detMntExe": 0, "detMntNeto": 40000, "detMntIVA": 7600, "detMntIVANoRec": 1000, "detMntIVAUsoComun": None, "detMntTotal": 47600, "detEventoReceptor": "REGISTRO"},
    {"tipoDoc": "61", "nroDoc": "9", "fchDoc": "12/01/2026", "rutDoc": "12345678", "dvDoc": "5", "rznSoc": "PROVEEDOR UNO",
     "mntExe": "0", "mntNeto": "10.000", "mntIVA": "1.900", "mntTotal": "11.900"},
    {"tipoDoc": 34, "folio": 77, "fecha": "2026-01-30T00:00:00", "rut": "", "dv": "", "razonSocial": "EXENTO",
     "montoExento": 8000.4, "montoNeto": "", "montoIva": None, "montoTotal": 8000},
    "no es dict",
], "respEstado": {"codRespuesta": 0}}


def main():
    out = {}
    ventas = rcv.normalizar_detalle("77.777.777-7", rcv.VENTA, "2026-01", CSV_VENTAS)
    compras = rcv.normalizar_detalle("77777777-7", rcv.COMPRA, "202601", DICT_COMPRAS, origen="csv")
    out["ventas"] = [vars(d) for d in ventas]
    out["compras"] = [vars(d) for d in compras]
    out["lista_directa"] = [vars(d) for d in rcv.normalizar_detalle("77777777-7", rcv.VENTA, "202601", [{"tipoDoc": 33, "folio": 1}])]
    out["vacios"] = [rcv.normalizar_detalle("77777777-7", rcv.VENTA, "202601", {"data": None}), rcv.normalizar_detalle("77777777-7", rcv.VENTA, "202601", {"data": []})]
    out["num"] = [rcv._num(v) for v in [None, "", 12, 12.6, "1.234", "1,234", "x", -3.5]]
    out["fecha"] = [rcv._fecha_iso(v) for v in [None, "", "15/01/2026", "2026-01-15", "2026-01-15T10:00:00", "15-01-2026", "garbage!!!", "2026"]]
    out["periodo"] = [rcv._normalizar_periodo(v) for v in ["2026-01", "202601", "2026/01", " 202601 "]]
    cli = rcv.RegistroCompraVenta(token="TOK")
    pv = cli._payload("77777777-7", "2026-01", rcv.VENTA)
    pc = cli._payload("77777777-7", "202601", rcv.COMPRA)
    pr = cli._payload("77777777-7", "202601", rcv.VENTA, metodo="getResumen")
    for p in (pv, pc, pr):
        p["metaData"]["transactionId"] = "<uuid>"
    out["payload"] = {"venta": pv, "compra": pc, "resumen": pr}
    cli2 = rcv.RegistroCompraVenta(cookies={"CSESSIONID": "CS", "TOKEN": "T2"})
    p2 = cli2._payload("77777777-7", "202601", rcv.VENTA)
    p2["metaData"]["transactionId"] = "<uuid>"
    out["payload_cookies"] = p2
    out["headers"] = cli._headers("TOK", "77777777", "7")
    out["endpoints"] = rcv.RCV_ENDPOINTS
    out["guardados"] = rcv.guardar_documentos(ventas + compras)
    out["guardados_otra_vez"] = rcv.guardar_documentos(ventas + compras)
    con = sqlite3.connect(f"{tmp}/rcv.db")
    out["filas_en_bd"] = con.execute("SELECT COUNT(*) FROM rcv_documentos").fetchone()[0]
    con.close()
    d = rcv.calcular_desglose_f29("77777777-7", "202601", ppm=1234, remanente_anterior=500)
    out["desglose"] = {k: v for k, v in vars(d).items() if not k.startswith("_")}
    out["desglose"].update({"iva_determinado": d.iva_determinado, "remanente_siguiente": d.remanente_siguiente, "base_ppm": d.base_ppm, "total_a_pagar": d.total_a_pagar})
    out["casilleros"] = [vars(l) for l in rcv.mapear_a_f29(d)]
    d2 = rcv.calcular_desglose_f29("77777777-7", "202601", ppm=0, remanente_anterior=900000)
    out["casilleros_remanente"] = [vars(l) for l in rcv.mapear_a_f29(d2)]
    r = rcv.calcular_resumen_f29("77777777-7", "202601", ppm=10, remanente_anterior=0)
    out["resumen"] = dict(vars(r), iva_determinado=r.iva_determinado, remanente_siguiente=r.remanente_siguiente, total_a_pagar=r.total_a_pagar)
    out["codigos_f29"] = {k: list(v) for k, v in rcv.CODIGOS_F29.items()}
    (AQUI / "entrada.json").write_text(json.dumps({"csv_ventas": CSV_VENTAS, "dict_compras": DICT_COMPRAS}, ensure_ascii=False, indent=1), encoding="utf-8")
    (AQUI / "esperado.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("escrito esperado.json con", len(out), "bloques")


if __name__ == "__main__":
    main()
