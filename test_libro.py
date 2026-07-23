"""
test_libro.py — Blinda la regla del t46 con retención total en el Libro de COMPRAS.

**Por qué existe.** El SII rechazó (`SRH`, set 4943175) el Libro de Compras con dos
reparos de DATOS —"El Monto Total No Cuadra" y "No Informa Adecuadamente IVA Retenido
Total"— con un XML que VALIDABA contra `LibroCV_v10.xsd` (el XSD no discrimina Compras de
Ventas, ver docs/LECCIONES-SII.md → "El XSD NO alcanza"). Por eso este test NO se conforma
con la validación XSD: verifica los VALORES concretos del caso real (folio 9, neto 10866).

Casos cubiertos:
  1. Factura de compra (t46) con retención TOTAL del IVA — el caso que el SII rechazó.
  2. Una compra normal (sin retención) — que el fix no la haya roto.
  3. Una VENTA con `IVARetTotal` — confirma que ESE camino (correcto para Libro de Ventas)
     sigue intacto tras gatear la emisión por `tipo_operacion`.

Necesita la clave del .pfx de pruebas: `TEST_PFX_PASS` o el Llavero
(`security add-generic-password -s dte-cert -a $USER -w '<clave>'`).
NO envía nada al SII — el veredicto SRH real solo se resuelve certificando contra el SII vivo.

Uso:  .venv/bin/python test_libro.py
"""
from __future__ import annotations

import os
import subprocess
import sys
from datetime import date

from lxml import etree

from core.crypto import CertificadoDigital
from core.libro import CaratulaLibro, DetalleLibro, GeneradorLibro

_PFX = os.environ.get("TEST_PFX", "firma.pfx")
_KEYCHAIN = os.environ.get("TEST_KEYCHAIN_SERVICE", "dte-cert")  # ítem del Llavero (macOS)
_XSD = "core/xsd/LibroCV_v10.xsd"
_SII_NS = "{http://www.sii.cl/SiiDte}"


def _pfx_pass() -> str:
    clave = os.environ.get("TEST_PFX_PASS")
    if clave:
        return clave
    r = subprocess.run(["security", "find-generic-password", "-s", _KEYCHAIN, "-w"],
                       capture_output=True, text=True)
    if r.returncode == 0 and r.stdout.strip():
        return r.stdout.strip()
    raise SystemExit(
        "Falta la clave del .pfx de pruebas. Exporta TEST_PFX_PASS=... o guárdala en el "
        "Llavero:  security add-generic-password -s dte-cert -a $USER -w '<clave>'")


def _check(cond: bool, msg: str) -> None:
    print(f"  {'✅' if cond else '❌'} {msg}")
    if not cond:
        _check.fallos += 1
_check.fallos = 0


def _validar_xsd(xml_bytes: bytes) -> tuple[bool, list]:
    """Valida contra LibroCV_v10.xsd. Necesario, NO suficiente (ver docstring del módulo)."""
    schema = etree.XMLSchema(etree.parse(_XSD))
    root = etree.fromstring(xml_bytes)
    if schema.validate(root):
        return True, []
    return False, [str(e) for e in schema.error_log]


def _caratula(tipo_operacion: str) -> CaratulaLibro:
    return CaratulaLibro(
        rut_emisor="76111111-6", periodo="2026-07", fch_resol="2026-07-08",
        tipo_operacion=tipo_operacion, nro_resol="0",
    )


# ---------------------------------------------------------------------------
def test_compra_t46_retencion_total() -> None:
    print("\n[1] ⭐ Factura de compra (t46) con retención TOTAL del IVA — caso real (set 4943175)")
    cert = CertificadoDigital.desde_archivo(_PFX, _pfx_pass())
    det = DetalleLibro.factura_compra_retencion_total(
        folio=9, fecha=date(2026, 7, 1), rut_doc="76543210-9",
        razon_social="Proveedor Sin Factura", monto_neto=10866)

    # --- valores en el objeto, antes de tocar XML ---
    _check(det.monto_iva == 2065, f"MntIVA = IVA completo (2065), no 0 — dio {det.monto_iva}")
    _check(det.total == 10866, f"MntTotal = neto (10866) tras restar la retención — dio {det.total}")
    _check(det.otros_imp == [(15, "19.00", 2065)],
           f"otros_imp = [(15, '19.00', 2065)] — dio {det.otros_imp}")

    xml = GeneradorLibro().generar_xml(_caratula("COMPRA"), [det], cert, id_libro="LIBRO1")
    txt = xml.decode("ISO-8859-1")

    # --- valores en el XML final ---
    _check("<MntIVA>2065</MntIVA>" in txt, "el <Detalle> lleva <MntIVA>2065</MntIVA>")
    _check("<MntTotal>10866</MntTotal>" in txt, "el <Detalle> lleva <MntTotal>10866</MntTotal>")
    _check("<OtrosImp><CodImp>15</CodImp><TasaImp>19.00</TasaImp><MntImp>2065</MntImp></OtrosImp>" in txt,
           "el <Detalle> lleva <OtrosImp CodImp=15 TasaImp=19.00 MntImp=2065>")
    _check("IVARetTotal" not in txt,
           "NO se emite <IVARetTotal> en ningún lado — causó "
           "'No Informa Adecuadamente IVA Retenido Total' en Compras")
    _check("<TotOtrosImp><CodImp>15</CodImp><TotMntImp>2065</TotMntImp></TotOtrosImp>" in txt,
           "el resumen lleva <TotOtrosImp CodImp=15 TotMntImp=2065>")
    _check("<TotMntTotal>10866</TotMntTotal>" in txt,
           "el resumen lleva <TotMntTotal>10866</TotMntTotal> (no 12931)")
    _check("TotOpIVARetTotal" not in txt and "TotIVARetTotal" not in txt,
           "el resumen NO lleva TotOpIVARetTotal/TotIVARetTotal (son del Libro de Ventas)")

    ok, errores = _validar_xsd(xml)
    _check(ok, f"valida contra LibroCV_v10.xsd (necesario, no suficiente) {errores[:2]}")


def test_iva_redondeo_frontera() -> None:
    print("\n[1b] El IVA se redondea half-up, no con banker's rounding (neto en .5)")
    # neto=1350 → 1350*0.19 = 256.5: round() nativo da 256, el SII espera 257 (half-up).
    # Es el mismo bug de $1 que core/dte.py ya documentó; sin este caso, el test del neto
    # 10866 (que no cae en .5) daba verde con el bug presente.
    det = DetalleLibro.factura_compra_retencion_total(
        folio=10, fecha=date(2026, 7, 1), rut_doc="76543210-9", monto_neto=1350)
    _check(det.monto_iva == 257,
           f"IVA de 1350 = 257 (half-up), no 256 (banker's) — dio {det.monto_iva}")
    _check(det.total == 1350, f"MntTotal = neto tras restar la retención (1350) — dio {det.total}")
    _check(det.otros_imp == [(15, "19.00", 257)],
           f"la retención en OtrosImp usa el mismo IVA (257) — dio {det.otros_imp}")


def test_compra_normal_sin_retencion() -> None:
    print("\n[2] Compra normal (sin retención) — no se rompió lo que ya funcionaba")
    cert = CertificadoDigital.desde_archivo(_PFX, _pfx_pass())
    det = DetalleLibro(
        tipo_doc=33, folio=501, fecha=date(2026, 7, 2), rut_doc="76543210-9",
        razon_social="Proveedor Normal", monto_neto=10000, monto_iva=1900)

    _check(det.total == 11900, f"MntTotal = neto+IVA sin retención (11900) — dio {det.total}")

    xml = GeneradorLibro().generar_xml(_caratula("COMPRA"), [det], cert, id_libro="LIBRO2")
    txt = xml.decode("ISO-8859-1")

    _check("<MntTotal>11900</MntTotal>" in txt, "el <Detalle> lleva <MntTotal>11900</MntTotal>")
    _check("<TotMntTotal>11900</TotMntTotal>" in txt, "el resumen lleva <TotMntTotal>11900</TotMntTotal>")
    _check("OtrosImp" not in txt, "sin retención no se emite <OtrosImp>/<TotOtrosImp>")
    _check("IVARetTotal" not in txt, "sin retención no se emite <IVARetTotal>")

    ok, errores = _validar_xsd(xml)
    _check(ok, f"valida contra LibroCV_v10.xsd {errores[:2]}")


def test_venta_con_iva_ret_total_sigue_intacta() -> None:
    print("\n[3] VENTA con IVARetTotal — el camino de Ventas sigue intacto (LV)")
    cert = CertificadoDigital.desde_archivo(_PFX, _pfx_pass())
    det = DetalleLibro(
        tipo_doc=33, folio=77, fecha=date(2026, 7, 3), rut_doc="60803000-K",
        razon_social="Cliente Gran Contribuyente", monto_neto=50000, monto_iva=9500,
        iva_ret_total=9500)

    # El total de VENTAS no se ve afectado por iva_ret_total (comportamiento preexistente:
    # `iva_ret_total` nunca entró al cálculo de `.total`, sólo la retención vía `otros_imp`
    # con CodImp=15 lo hace — y ese mecanismo es exclusivo de Compras).
    _check(det.total == 59500, f"MntTotal de venta = neto+IVA (59500), sin restar — dio {det.total}")

    xml = GeneradorLibro().generar_xml(_caratula("VENTA"), [det], cert, id_libro="LIBRO3")
    txt = xml.decode("ISO-8859-1")

    _check("<IVARetTotal>9500</IVARetTotal>" in txt,
           "el <Detalle> SÍ lleva <IVARetTotal>9500</IVARetTotal> — es Libro de Ventas")
    _check("<TotOpIVARetTotal>1</TotOpIVARetTotal>" in txt, "el resumen lleva TotOpIVARetTotal=1")
    _check("<TotIVARetTotal>9500</TotIVARetTotal>" in txt, "el resumen lleva TotIVARetTotal=9500")
    _check("OtrosImp" not in txt, "en Ventas la retención NO usa <OtrosImp> (eso es de Compras)")

    ok, errores = _validar_xsd(xml)
    _check(ok, f"valida contra LibroCV_v10.xsd {errores[:2]}")


def main_() -> int:
    print("=" * 66)
    print("  core/libro.py — t46 con retención total en Libro de Compras")
    print("  Referencia: SII SRH, set 4943175 (docs/LECCIONES-SII.md)")
    print("=" * 66)
    test_compra_t46_retencion_total()
    test_iva_redondeo_frontera()
    test_compra_normal_sin_retencion()
    test_venta_con_iva_ret_total_sigue_intacta()
    print("\n" + "=" * 66)
    if _check.fallos:
        print(f"❌ {_check.fallos} comprobación(es) fallaron")
        return 1
    print("✅ Todo OK (XSD válido y valores concretos correctos — el veredicto SII real "
          "sigue sin verificar contra el SII vivo)")
    return 0


if __name__ == "__main__":
    sys.exit(main_())
