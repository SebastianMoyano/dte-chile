"""
test_rcv.py

Prueba offline (sin red) del módulo RCV: normalización del JSON facade,
persistencia en la tabla nueva y agregación F29 (débito − crédito, con NC
restando). No toca el pipeline de emisión/firma.

Ejecutar:  .venv/bin/python test_rcv.py
"""

from core.rcv import (
    COMPRA,
    VENTA,
    ResumenF29,
    calcular_desglose_f29,
    calcular_resumen_f29,
    cargar_desde_json,
    init_rcv_db,
    mapear_a_f29,
)
from core.database import get_db

RUT = "76111111-6"
PERIODO = "202406"

# --- Muestras con la forma del facade (llaves det*) -------------------------
VENTAS_JSON = {
    "data": [
        # 2 facturas afectas + 1 factura exenta + 1 nota de crédito (61) que resta
        {"detTipoDoc": 33, "detNroDoc": 1001, "detFchDoc": "05/06/2024",
         "detRutDoc": "76111111", "detDvDoc": "1", "detRznSoc": "CLIENTE UNO SPA",
         "detMntExe": 0, "detMntNeto": 100000, "detMntIVA": 19000, "detMntTotal": 119000},
        {"detTipoDoc": 33, "detNroDoc": 1002, "detFchDoc": "12/06/2024",
         "detRutDoc": "76222222", "detDvDoc": "2", "detRznSoc": "CLIENTE DOS LTDA",
         "detMntExe": 0, "detMntNeto": 50000, "detMntIVA": 9500, "detMntTotal": 59500},
        {"detTipoDoc": 34, "detNroDoc": 1003, "detFchDoc": "20/06/2024",
         "detRutDoc": "76333333", "detDvDoc": "3", "detRznSoc": "CLIENTE EXENTO EIRL",
         "detMntExe": 30000, "detMntNeto": 0, "detMntIVA": 0, "detMntTotal": 30000},
        {"detTipoDoc": 61, "detNroDoc": 500, "detFchDoc": "25/06/2024",
         "detRutDoc": "76111111", "detDvDoc": "1", "detRznSoc": "CLIENTE UNO SPA",
         "detMntExe": 0, "detMntNeto": 20000, "detMntIVA": 3800, "detMntTotal": 23800},
    ]
}

COMPRAS_JSON = {
    "data": [
        # 1 compra con crédito pleno + 1 con parte de IVA no recuperable
        {"detTipoDoc": 33, "detNroDoc": 7001, "detFchDoc": "03/06/2024",
         "detRutDoc": "76999999", "detDvDoc": "9", "detRznSoc": "PROVEEDOR SPA",
         "detMntExe": 0, "detMntNeto": 40000, "detMntIVA": 7600, "detMntTotal": 47600},
        {"detTipoDoc": 33, "detNroDoc": 7002, "detFchDoc": "08/06/2024",
         "detRutDoc": "76888888", "detDvDoc": "8", "detRznSoc": "SERVICIOS LTDA",
         "detMntExe": 0, "detMntNeto": 10000, "detMntIVA": 1900,
         "detMntIVANoRec": 1900, "detMntTotal": 11900},
    ]
}


def _limpiar():
    init_rcv_db()
    with get_db() as conn:
        conn.execute("DELETE FROM rcv_documentos WHERE rut_empresa=? AND periodo=?",
                     ("76111111-6", PERIODO))


def main():
    print("=== Test RCV (offline) ===")
    _limpiar()

    ventas = cargar_desde_json(RUT, VENTA, PERIODO, VENTAS_JSON)
    compras = cargar_desde_json(RUT, COMPRA, PERIODO, COMPRAS_JSON)
    print(f"Normalizados: {len(ventas)} ventas, {len(compras)} compras")

    # Idempotencia: re-ingerir no debe duplicar
    cargar_desde_json(RUT, VENTA, PERIODO, VENTAS_JSON)
    with get_db() as conn:
        total = conn.execute(
            "SELECT COUNT(*) c FROM rcv_documentos WHERE rut_empresa=? AND periodo=?",
            ("76111111-6", PERIODO)).fetchone()["c"]
    assert total == 6, f"Se esperaban 6 filas (sin duplicar), hay {total}"
    print(f"Idempotencia OK: {total} filas tras re-ingesta")

    r: ResumenF29 = calcular_resumen_f29(RUT, PERIODO, ppm=5000, remanente_anterior=0)

    # --- Verificación de la aritmética ---
    # Débito: 19000 + 9500 + 0 - 3800 (NC) = 24700
    assert r.debito_fiscal == 24700, r.debito_fiscal
    # Ventas netas afectas: 100000 + 50000 - 20000 (NC) = 130000
    assert r.ventas_netas == 130000, r.ventas_netas
    assert r.ventas_exentas == 30000, r.ventas_exentas
    # Crédito recuperable: 7600 + (1900 - 1900 no rec) = 7600
    assert r.credito_fiscal == 7600, r.credito_fiscal
    assert r.iva_no_recuperable == 1900, r.iva_no_recuperable
    # IVA determinado = 24700 - 7600 = 17100 (a pagar)
    assert r.iva_determinado == 17100, r.iva_determinado
    assert r.remanente_siguiente == 0
    # Total a pagar = 17100 + 5000 PPM = 22100
    assert r.total_a_pagar == 22100, r.total_a_pagar

    print(f"Débito fiscal:      {r.debito_fiscal:>10,}")
    print(f"Crédito fiscal:     {r.credito_fiscal:>10,}")
    print(f"IVA determinado:    {r.iva_determinado:>10,}")
    print(f"PPM:                {r.ppm:>10,}")
    print(f"TOTAL a pagar F29:  {r.total_a_pagar:>10,}")

    # --- Caso remanente: crédito > débito ---
    r2 = calcular_resumen_f29(RUT, PERIODO, ppm=0, remanente_anterior=30000)
    # 24700 - 7600 - 30000 = -12900 -> remanente siguiente 12900, nada a pagar
    assert r2.iva_determinado == -12900, r2.iva_determinado
    assert r2.remanente_siguiente == 12900, r2.remanente_siguiente
    assert r2.total_a_pagar == 0, r2.total_a_pagar
    print(f"Remanente mes sig.: {r2.remanente_siguiente:>10,}  (caso crédito>débito) OK")

    # --- Mapeo a casilleros del F29 ---
    d = calcular_desglose_f29(RUT, PERIODO, ppm=5000, remanente_anterior=0)
    # El desglose debe reconciliar con el resumen colapsado
    assert d.total_debitos == r.debito_fiscal, (d.total_debitos, r.debito_fiscal)
    assert d.total_creditos == r.credito_fiscal, (d.total_creditos, r.credito_fiscal)
    assert d.iva_determinado == r.iva_determinado
    # Facturas emitidas: 3 docs (2 afectas 33 + 1 exenta 34), débito 19000+9500 = 28500
    # (la exenta cuenta como factura emitida; su monto va aparte a exentas/142)
    assert d.fact_emitidas_cant == 3 and d.fact_emitidas_debito == 28500, d
    # NC emitida: 1 doc, rebaja 3800
    assert d.nc_emitidas_cant == 1 and d.nc_emitidas_debito == 3800, d
    # Exenta: 1 doc, 30000
    assert d.exentas_cant == 1 and d.ventas_exentas == 30000, d
    # Base PPM = ventas netas + exentas del giro: (100000+50000+0+30000) - NC 20000...
    # OJO: base PPM suma neto+exento por doc SIN signo de NC (ingresos brutos).
    assert d.base_ppm == 100000 + 50000 + 30000 + 20000, d.base_ppm

    lineas = mapear_a_f29(d)
    por_codigo = {l.codigo: l.valor for l in lineas}
    assert por_codigo["502"] == 28500      # débito facturas emitidas
    assert por_codigo["510"] == 3800       # rebaja NC emitidas (cód. oficial 510)
    assert por_codigo["142"] == 30000      # ventas exentas
    assert por_codigo["538"] == 24700      # TOTAL DÉBITOS
    assert por_codigo["520"] == 7600       # crédito facturas recibidas
    assert por_codigo["537"] == 7600       # TOTAL CRÉDITOS
    assert por_codigo["89"] == 17100       # IVA determinado a pagar
    assert por_codigo["62"] == 5000        # PPM
    assert por_codigo["91"] == 22100       # total a pagar
    # Todos los códigos deben estar confirmados contra el formulario oficial
    assert all(l.confianza == "OK" for l in lineas), \
        [l.codigo for l in lineas if l.confianza != "OK"]

    print("\n--- Propuesta F29 (casilleros) ---")
    for l in lineas:
        flag = "" if l.confianza == "OK" else "  ⚠ confirmar código"
        print(f"  [{l.codigo}] {l.glosa:<48} {l.valor:>10,}{flag}")

    _limpiar()
    print("\n✅ TODOS LOS ASSERTS PASARON")


if __name__ == "__main__":
    main()
