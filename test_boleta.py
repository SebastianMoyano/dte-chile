"""
test_boleta.py — Verifica el camino de BOLETAS (39/41), que es infraestructura aparte.

Script plano (como el resto de los tests del repo), no pytest. Comprueba:
  1. Estructura de la boleta: IndServicio, RznSocEmisor, y la AUSENCIA de FmaPago/TasaIVA.
  2. El sobre EnvioBOLETA firmado valida contra el XSD oficial (39 y 41).
  3. La aritmética de IVA de boleta cuadra (IVA por resta, no por redondeo).
  4. Los guardarraíles: el camino de FACTURA rechaza boletas en vez de emitir/enviar un
     sobre malformado (era un falso positivo peligroso), y `emitir_documento` rutea bien.
  5. El cliente REST: hosts asimétricos y constantes del protocolo.

El CAF de tipo 39/41 se SINTETIZA reusando la llave RSA de un CAF real de prueba: el SII
no aceptaría un TED así (su FRMA no cubre ese TD), pero sirve para verificar estructura,
firma y XSD sin depender de un timbraje que todavía no existe.

Uso:  .venv/bin/python test_boleta.py
"""
from __future__ import annotations

import base64
import os
import re
import subprocess
import sys
from datetime import date

from core.caf import ManejadorCAF
from core.crypto import CertificadoDigital
from core.dte import DTEInput, EmisorModel, ItemDTE, ReceptorModel, TipoDTE
from core.errors import ValidacionError
from core.preview import previsualizar_dte

_CAF_BASE = "storage/cafs/CAF_T33_folio101.xml"
_PFX = os.environ.get("TEST_PFX", "firma.pfx")


def _pfx_pass() -> str:
    """Clave del .pfx de pruebas: del entorno o del Llavero de macOS.

    Nunca hardcodeada: el repo no tiene `.gitignore` y una clave en un test es una clave
    publicada (ver L6 de docs/CONSTITUCION.md).
    """
    clave = os.environ.get("TEST_PFX_PASS")
    if clave:
        return clave
    r = subprocess.run(["security", "find-generic-password", "-s", "dte-cert-sebastian", "-w"],
                       capture_output=True, text=True)
    if r.returncode == 0 and r.stdout.strip():
        return r.stdout.strip()
    raise SystemExit(
        "Falta la clave del .pfx de pruebas. Exporta TEST_PFX_PASS=... o guárdala en el "
        "Llavero:  security add-generic-password -s dte-cert-sebastian -a $USER -w '<clave>'")


def _check(cond: bool, msg: str) -> None:
    print(f"  {'✅' if cond else '❌'} {msg}")
    if not cond:
        _check.fallos += 1
_check.fallos = 0


def _caf_sintetico(tipo: int) -> ManejadorCAF:
    """CAF de prueba del tipo pedido, reusando la llave RSA de un CAF real."""
    xml = open(_CAF_BASE, "rb").read().decode("ISO-8859-1")
    xml = xml.replace("<TD>33</TD>", f"<TD>{tipo}</TD>")
    xml = xml.replace("<RNG><D>101</D><H>101</H></RNG>", "<RNG><D>1</D><H>50</H></RNG>")
    return ManejadorCAF(xml.encode("ISO-8859-1"))


def _boleta(tipo: TipoDTE, exento: bool = False) -> DTEInput:
    return DTEInput(
        tipo_dte=tipo, folio=1, fecha_emision=date(2026, 7, 16),
        emisor=EmisorModel(rut="76111111-6", razon_social="EMPRESA DEMO SPA",
                           giro="ELABORACION DE ALIMENTOS", codigo_actividad=101000,
                           direccion="AV SIEMPRE VIVA 123", comuna="SANTIAGO",
                           ciudad="SANTIAGO"),
        # 66666666-6 = receptor genérico de boleta no nominativa.
        receptor=ReceptorModel(rut="66666666-6", razon_social="CONSUMIDOR FINAL"),
        items=[ItemDTE(numero_linea=1, nombre="Empanada de pino", cantidad=3,
                       precio_unitario=2500, exento=exento),
               ItemDTE(numero_linea=2, nombre="Bebida 500ml", cantidad=2,
                       precio_unitario=1200, exento=exento)],
    )


def test_boleta_afecta() -> None:
    print("\n[1] Boleta afecta (39): estructura + XSD")
    cert = CertificadoDigital.desde_archivo(_PFX, _pfx_pass())
    r = previsualizar_dte(_boleta(TipoDTE.BOLETA_ELECTRONICA), cert, _caf_sintetico(39))

    _check(r["valido_xsd"], f"EnvioBOLETA firmado valida contra el XSD oficial "
                            f"{'' if r['valido_xsd'] else r['errores_xsd'][:2]}")
    xml = base64.b64decode(r["xml_b64"]).decode("ISO-8859-1")
    m = re.search(r"<IndServicio>(\d+)</IndServicio>", xml)
    _check(m is not None and m.group(1) == "3", "IndServicio presente (3 = ventas y servicios)")
    _check("RznSocEmisor" in xml and "GiroEmisor" in xml,
           "Emisor usa RznSocEmisor/GiroEmisor (no los nombres de factura)")
    _check("FmaPago" not in xml, "sin FmaPago (la boleta no lo lleva)")
    _check("TasaIVA" not in xml, "sin TasaIVA (la boleta no lo lleva)")
    _check("<TED" in xml and "FRMT" in xml, "lleva el timbre TED")


def test_iva_por_resta() -> None:
    print("\n[2] Aritmética de IVA (el precio incluye IVA)")
    cert = CertificadoDigital.desde_archivo(_PFX, _pfx_pass())
    r = previsualizar_dte(_boleta(TipoDTE.BOLETA_ELECTRONICA), cert, _caf_sintetico(39))

    # 3*2500 + 2*1200 = 9900 bruto.
    _check(r["monto_total"] == 9900, f"total = bruto de los ítems ({r['monto_total']})")
    _check(r["monto_neto"] + r["iva"] == r["monto_total"],
           f"neto + IVA == total ({r['monto_neto']} + {r['iva']} = {r['monto_total']}) "
           "— el IVA va por RESTA; redondearlo aparte descuadra el total")
    _check(r["monto_neto"] == 8319 and r["iva"] == 1581, "neto/IVA derivados del bruto")


def test_boleta_exenta() -> None:
    print("\n[3] Boleta exenta (41)")
    cert = CertificadoDigital.desde_archivo(_PFX, _pfx_pass())
    r = previsualizar_dte(_boleta(TipoDTE.BOLETA_NO_AFECTA), cert, _caf_sintetico(41))
    _check(r["valido_xsd"], f"EnvioBOLETA 41 valida contra el XSD "
                            f"{'' if r['valido_xsd'] else r['errores_xsd'][:2]}")
    _check(r["iva"] == 0 and r["monto_exento"] == 9900, "sin IVA, todo exento")


def test_guardarrailes() -> None:
    print("\n[4] Guardarraíles: el camino de factura NO debe tragarse una boleta")
    from core.orchestrator import OrquestadorDTE

    # Antes esto armaba un EnvioDTE malformado y lo mandaba: un falso positivo peligroso.
    try:
        OrquestadorDTE().emitir_dte(_boleta(TipoDTE.BOLETA_ELECTRONICA))
        _check(False, "emitir_dte(39) debía rechazar la boleta")
    except ValidacionError as e:
        _check("boleta" in str(e).lower(), "OrquestadorDTE.emitir_dte(39) → ValidacionError")

    from core.sii import ClienteSII
    cli = ClienteSII.__new__(ClienteSII)
    try:
        cli.enviar_dte(b"<x/>", "76111111", "6", tipo_dte=39)
        _check(False, "enviar_dte(39) debía rechazar la boleta")
    except ValidacionError as e:
        _check("sii_boleta" in str(e), "ClienteSII.enviar_dte(39) → ValidacionError que "
                                       "apunta al cliente correcto")

    # El endpoint legado ya no existe: mandar ahí fallaba en silencio.
    from core.sii import URLS_SII, AmbienteSII
    _check("envio_boleta" not in URLS_SII[AmbienteSII.CERTIFICACION],
           "el endpoint legado BOLUpload fue retirado")


def test_ruteo() -> None:
    print("\n[5] Ruteo por tipo")
    import core.orchestrator as orch

    llamados = {}

    class FakeBoleta:
        def emitir_boleta(self, dte, certificado=None):
            llamados["boleta"] = dte.tipo_dte.value
            return {"ok": True}

    import core.orchestrator_boleta as ob
    original = ob.OrquestadorBoleta
    ob.OrquestadorBoleta = FakeBoleta
    try:
        orch.emitir_documento(_boleta(TipoDTE.BOLETA_ELECTRONICA))
        _check(llamados.get("boleta") == 39, "emitir_documento(39) → OrquestadorBoleta")
        orch.emitir_documento(_boleta(TipoDTE.BOLETA_NO_AFECTA))
        _check(llamados.get("boleta") == 41, "emitir_documento(41) → OrquestadorBoleta")
    finally:
        ob.OrquestadorBoleta = original


def test_cliente_rest() -> None:
    print("\n[6] Cliente REST de boleta")
    from core.sii import AmbienteSII
    from core.sii_boleta import (ESTADO_OK, MAX_BOLETAS_POR_ENVIO, URLS_BOLETA,
                                 _USER_AGENT)

    cert = URLS_BOLETA[AmbienteSII.CERTIFICACION]
    prod = URLS_BOLETA[AmbienteSII.PRODUCCION]

    # La asimetría es el error más caro: el envío NO va al mismo host que el token.
    _check("apicert.sii.cl" in cert["token"], "cert: token → apicert")
    _check("pangal.sii.cl" in cert["envio"], "cert: ENVÍO → pangal (no apicert)")
    _check("api.sii.cl" in prod["token"], "prod: token → api")
    _check("rahue.sii.cl" in prod["envio"], "prod: ENVÍO → rahue (no api)")
    _check(all("cgi_bol" not in u and "BOLUpload" not in u
               for u in list(cert.values()) + list(prod.values())),
           "sin rastros del endpoint legado")
    _check(ESTADO_OK == "00", 'ESTADO OK es "00" (dos dígitos), no "0"')
    # OJO: el 500 NO está en el XSD (ahí DTE es maxOccurs="unbounded"); es un tope
    # conservador nuestro, del Instructivo del SII. Lo que SÍ verifica el XSD:
    from lxml import etree as _et
    _x = _et.parse("core/xsd/EnvioBOLETA_v11.xsd")
    _sub = [e for e in _x.iter("{http://www.w3.org/2001/XMLSchema}element")
            if e.get("name") == "SubTotDTE"]
    _check(bool(_sub) and _sub[0].get("maxOccurs") == "2",
           "el XSD limita SubTotDTE a 2 tipos por sobre (vs 20 en EnvioDTE)")
    _check(0 < MAX_BOLETAS_POR_ENVIO <= 1000,
           f"hay un tope conservador de boletas por sobre ({MAX_BOLETAS_POR_ENVIO}, "
           "del Instructivo del SII — el XSD no lo impone)")
    _check("Mozilla" in _USER_AGENT,
           "hay User-Agent de navegador (sin él el SII responde 401 engañoso)")


def test_epr_no_es_aceptado() -> None:
    print("\n[11] EPR = 'Envío Procesado', NO 'aceptado'")
    from core.sii_boleta import ClienteBoletaSII

    # Respuesta REAL del SII (trackid 30417072): sobre procesado, boleta RECHAZADA.
    real = {
        "estado": "EPR",
        "estadistica": [{"tipo": 39, "informados": 1, "aceptados": 0, "rechazados": 1,
                         "reparos": 0}],
        "detalle_rep_rech": [{"tipo": 39, "folio": 1, "estado": "RCH", "error": [
            {"seccion": "DTE", "codigo": 505, "descripcion": "Firma DTE Incorrecta"}]}],
    }

    class _Resp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return real

    c = ClienteBoletaSII.__new__(ClienteBoletaSII)
    c.urls = {"estado": "https://x/y"}
    c.obtener_token = lambda: "tok"
    c._cli = lambda: type("F", (), {"get": lambda *a, **k: _Resp()})()

    r = c.consultar_estado("30417072", "76111111", "6")
    _check(r["estado"] == "EPR" and r["procesado"], "EPR se reporta como PROCESADO")
    _check(r["todo_aceptado"] is False,
           "EPR con 1 rechazado NO es 'todo aceptado' (el bug que ocultó el fallo real)")
    _check(r["rechazados"] == 1 and r["aceptados"] == 0,
           "el veredicto sale de `estadistica`, no de `estado`")
    _check(r["detalle"][0]["error"][0]["codigo"] == 505,
           "el detalle trae el código exacto por documento (505 = firma DTE incorrecta)")


def _docs_dia() -> list[dict]:
    return [
        {"tipo_dte": 39, "folio": 1, "monto_neto": 8319, "monto_exento": 0, "iva": 1581,
         "monto_total": 9900, "estado": "emitido", "fecha_emision": "2026-07-16"},
        {"tipo_dte": 39, "folio": 2, "monto_neto": 1681, "monto_exento": 0, "iva": 319,
         "monto_total": 2000, "estado": "emitido", "fecha_emision": "2026-07-16"},
        {"tipo_dte": 39, "folio": 3, "monto_neto": 0, "monto_exento": 0, "iva": 0,
         "monto_total": 0, "estado": "anulado", "fecha_emision": "2026-07-16"},
        {"tipo_dte": 41, "folio": 1, "monto_neto": 0, "monto_exento": 5000, "iva": 0,
         "monto_total": 5000, "estado": "emitido", "fecha_emision": "2026-07-16"},
    ]


def test_rangos() -> None:
    print("\n[7] Agrupación de folios en rangos (RVD)")
    from core.rvd import agrupar_rangos

    _check(agrupar_rangos([1, 2, 3, 7, 8, 10]) == [(1, 3), (7, 8), (10, 10)],
           "agrupa contiguos y deja los sueltos como rango de 1")
    # Los dos casos donde la implementación de LibreDTE se rompe.
    _check(agrupar_rangos([]) == [], "lista vacía → [] (LibreDTE revienta aquí)")
    _check(agrupar_rangos([1, 1, 2, 3]) == [(1, 3)],
           "folios duplicados → rango correcto (LibreDTE lo corrompe)")
    _check(agrupar_rangos([5, 1, 2]) == [(1, 2), (5, 5)], "ordena antes de agrupar")


def test_rvd() -> None:
    print("\n[8] RVD / Consumo de folios diario")
    from lxml import etree

    from core.crypto import firmar_xml_sii
    from core.dte import SII_NAMESPACE
    from core.rvd import generar_consumo_folios
    from core.schema_validator import validar_xml_dte

    raiz = generar_consumo_folios("76111111-6", "19222222-2", _docs_dia(),
                                  "2014-08-22", 0, dia=date(2026, 7, 16))
    xml_txt = etree.tostring(raiz, encoding="unicode")
    _check(re.findall(r"<TipoDocumento>(\d+)</TipoDocumento>", xml_txt) == ["39", "41", "61"],
           "reporta 39/41/61 — los tipos SIN movimiento igual van, en cero")
    _check("<FoliosEmitidos>2</FoliosEmitidos>" in xml_txt
           and "<FoliosAnulados>1</FoliosAnulados>" in xml_txt
           and "<FoliosUtilizados>3</FoliosUtilizados>" in xml_txt,
           "FoliosUtilizados = emitidos + anulados")
    _check("<RangoAnulados><Inicial>3</Inicial><Final>3</Final></RangoAnulados>"
           in xml_txt.replace("\n", "").replace("  ", ""),
           "el folio anulado va en RangoAnulados, no en RangoUtilizados")

    # Firmado y validado contra el XSD oficial.
    cert = CertificadoDigital.desde_archivo(_PFX, _pfx_pass())
    raiz = etree.fromstring(etree.tostring(raiz, encoding="ISO-8859-1"))
    idd = raiz.find(f".//{{{SII_NAMESPACE}}}DocumentoConsumoFolios").get("ID")
    firmado = firmar_xml_sii(raiz, cert, uri=f"#{idd}")
    xml = etree.tostring(firmado, encoding="ISO-8859-1", xml_declaration=True)
    val = validar_xml_dte(xml)
    _check(val.valido, f"ConsumoFolios firmado valida contra ConsumoFolio_v10.xsd "
                       f"{'' if val.valido else val.errores[:2]}")
    _check(val.tipo_xml == "ConsumoFolios", "el validador reconoce la raíz ConsumoFolios")

    # Un tipo que el XSD no admite en el consumo de folios debe rechazarse temprano.
    try:
        generar_consumo_folios("76111111-6", "19222222-2", _docs_dia(), "2014-08-22", 0,
                               dia=date(2026, 7, 16), tipos=(33,))
        _check(False, "tipo 33 en el RVD debía rechazarse")
    except ValidacionError:
        _check(True, "tipo no admitido (33) → ValidacionError antes de generar")


def test_scheduler() -> None:
    print("\n[9] Programador del RVD (portable: sin cron/launchd)")
    import asyncio
    import logging
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    from core.scheduler import TZ_CHILE, ProgramadorRVD, hoy_chile, procesar_pendientes

    # El día del RVD lo fija el SII: debe ser el de Chile aunque el server esté en otra zona.
    ahora_chile = datetime.now(TZ_CHILE)
    ahora_berlin = datetime.now(ZoneInfo("Europe/Berlin"))
    _check(str(TZ_CHILE) == "America/Santiago", "el programador usa la zona horaria de Chile")
    _check(ahora_chile.utcoffset() != ahora_berlin.utcoffset(),
           "la hora de Chile difiere de la del servidor → por eso no se usa la local")
    _check(hoy_chile() == ahora_chile.date(), "hoy_chile() = fecha en Chile")

    # Windows no trae base de zonas horarias: sin `tzdata` esto reventaría allí.
    import importlib.util
    _check(importlib.util.find_spec("tzdata") is not None,
           "tzdata instalado (requisito para que el server corra en Windows)")

    # El bucle NUNCA debe morir: si el trabajo explota, se registra y se reintenta.
    llamadas = []

    def trabajo_que_explota(cuenta_id, dias_atras):
        llamadas.append(1)
        raise RuntimeError("el SII se cayó")

    async def _prueba_bucle():
        p = ProgramadorRVD(intervalo_seg=0.05, trabajo=trabajo_que_explota)
        p.iniciar()
        await asyncio.sleep(0.25)
        activo = p.estado()["activo"]
        await p.detener()
        return activo, len(llamadas)

    logging.getLogger("dte.scheduler").setLevel(logging.CRITICAL)  # el fallo es esperado
    activo, veces = asyncio.run(_prueba_bucle())
    logging.getLogger("dte.scheduler").setLevel(logging.NOTSET)
    _check(veces > 1 and activo,
           f"el bucle sobrevive a los fallos y reintenta ({veces} intentos, sigue vivo)")

    # Catch-up: si el servidor estuvo apagado, los días previos se recuperan.
    vistos = []

    def trabajo_espia(cuenta_id, dias_atras):
        vistos.append(dias_atras)
        return []

    async def _prueba_catchup():
        p = ProgramadorRVD(intervalo_seg=0.05, dias_atras=7, trabajo=trabajo_espia)
        p.iniciar()
        await asyncio.sleep(0.08)
        await p.detener()

    asyncio.run(_prueba_catchup())
    _check(vistos and vistos[0] == 7,
           "hace catch-up de 7 días (un server apagado no pierde el reporte)")

    _check(callable(procesar_pendientes), "el trabajo es sincrónico y testeable aparte")


def test_idempotencia_rvd() -> None:
    print("\n[10] Idempotencia del RVD (no reportar dos veces el mismo día)")
    from core.database import init_db
    from core.rvd import registrar_rvd, rvd_registrado
    from core.scheduler import ESTADO_PENDIENTE_RUTA, procesar_dia

    init_db()
    rut, dia = "99999999-9", date(2026, 1, 2)
    with __import__("core.database", fromlist=["get_db"]).get_db() as c:
        c.execute("DELETE FROM rvd_envios WHERE rut_emisor = ?", (rut,))

    registrar_rvd(rut, dia, ESTADO_PENDIENTE_RUTA, xml_path="/tmp/x.xml")
    _check(rvd_registrado(rut, dia)["estado"] == ESTADO_PENDIENTE_RUTA, "queda registrado")

    # Volver a procesar el mismo día NO debe regenerar ni duplicar.
    r = procesar_dia(rut, cert_id=None, dia=dia)
    _check(r.get("omitido") is True and r["estado"] == "ya_estaba",
           "reprocesar el mismo día → se omite (idempotente)")

    with __import__("core.database", fromlist=["get_db"]).get_db() as c:
        n = c.execute("SELECT COUNT(*) FROM rvd_envios WHERE rut_emisor = ? AND fecha = ?",
                      (rut, dia.isoformat())).fetchone()[0]
    _check(n == 1, "una sola fila por (emisor, día): el UNIQUE evita el doble reporte")

    # Un día nuevo sin certificado se registra como error, sin voltear el proceso.
    r2 = procesar_dia(rut, cert_id=None, dia=date(2026, 1, 3))
    _check(r2["estado"] == "error" and "certificado" in r2["detalle"],
           "sin certificado → error registrado, no una excepción que mate el bucle")

    with __import__("core.database", fromlist=["get_db"]).get_db() as c:
        c.execute("DELETE FROM rvd_envios WHERE rut_emisor = ?", (rut,))


def main_() -> int:
    print("=" * 60)
    print("  BOLETAS (39/41) — camino propio")
    print("=" * 60)
    test_boleta_afecta()
    test_iva_por_resta()
    test_boleta_exenta()
    test_guardarrailes()
    test_ruteo()
    test_cliente_rest()
    test_rangos()
    test_rvd()
    test_scheduler()
    test_idempotencia_rvd()
    test_epr_no_es_aceptado()
    print("\n" + "=" * 60)
    if _check.fallos:
        print(f"❌ {_check.fallos} comprobación(es) fallaron")
        return 1
    print("✅ Todo OK")
    return 0


if __name__ == "__main__":
    sys.exit(main_())
