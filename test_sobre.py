"""
test_sobre.py — Blinda la Ley L2 (`docs/CONSTITUCION.md`): la firma que el SII acepta.

**Por qué existe este archivo.** `core/sobre.py` es el módulo más caro del proyecto: costó 11
variantes de firma probadas contra el SII vivo, y su forma correcta quedó verificada con el
TrackID 253113966 → `ACEPTADOS: 1`. Aun así, el mismo día en que se arregló, `core/preview.py`
quedó firmando a la vieja usanza y **solo lo pilló una auditoría por casualidad**. Sin tests,
la Ley L2 está protegida por convención — y la convención ya falló una vez.

**Qué comprueba, y por qué así.** El SII no valida el árbol en memoria: valida **los bytes
que llegan por el cable**. Por eso el test central (`test_firma_sobrevive_al_sobre`) parsea el
XML **final serializado** y recomputa los digests desde ahí, igual que el SII. Ese es el test
que un `preview.py` re-serializando habría reprobado.

Necesita un CAF real (para un TED válido) y la clave del .pfx: `TEST_PFX_PASS` o el Llavero
(`security add-generic-password -s dte-cert -a $USER -w '<clave>'`).
NO envía nada al SII.

Uso:  .venv/bin/python test_sobre.py
"""
from __future__ import annotations

import base64
import os
import re
import subprocess
import sys
from datetime import date

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from lxml import etree

from core.caf import ManejadorCAF
from core.crypto import CertificadoDigital, _c14n_reparse
from core.dte import (DTEInput, EmisorModel, GeneradorDTE, ItemDTE, ReceptorModel,
                      TipoDTE, calcular_totales)
from core.schema_validator import validar_xml_dte
from core.sobre import armar_sobre_firmado, firmar_documento_standalone

_CAF = "storage/cafs/CAF_T34_cert_110.xml"   # CAF REAL de certificación (folios 110-112)
_FOLIO = 112                                  # 110 y 111 ya se enviaron; 112 está libre
_PFX = os.environ.get("TEST_PFX", "firma.pfx")
_KEYCHAIN = os.environ.get("TEST_KEYCHAIN_SERVICE", "dte-cert")  # ítem del Llavero (macOS)
_SII = "http://www.sii.cl/SiiDte"
_DS = "http://www.w3.org/2000/09/xmldsig#"


def _pfx_pass() -> str:
    clave = os.environ.get("TEST_PFX_PASS")
    if clave:
        return clave
    r = subprocess.run(["security", "find-generic-password", "-s", _KEYCHAIN, "-w"],
                       capture_output=True, text=True)
    if r.returncode == 0 and r.stdout.strip():
        return r.stdout.strip()
    raise SystemExit(
        "Falta la clave del .pfx. Exporta TEST_PFX_PASS=... o guárdala en el Llavero:\n"
        "  security add-generic-password -s dte-cert -a $USER -w '<clave>'")


def _check(cond: bool, msg: str) -> None:
    print(f"  {'✅' if cond else '❌'} {msg}")
    if not cond:
        _check.fallos += 1
_check.fallos = 0


def _dte_input(folio: int = _FOLIO) -> DTEInput:
    # Datos de una empresa real de certificación: un acteco inventado da HED-3-861
    # (ver LECCIONES-SII.md). "Morandé" lleva acento a propósito: cubre el bug de
    # encoding del armado del sobre.
    return DTEInput(
        tipo_dte=TipoDTE.FACTURA_NO_AFECTA, folio=folio, fecha_emision=date.today(),
        emisor=EmisorModel(rut="76111111-6", razon_social="EMPRESA DEMO SPA",
                           giro="Venta de alimentos", codigo_actividad=463014,
                           direccion="Av. Providencia 1234", comuna="Providencia",
                           ciudad="Santiago"),
        receptor=ReceptorModel(rut="60803000-K", razon_social="SII", giro="Gobierno",
                               direccion="Morandé 115", comuna="Santiago", ciudad="Santiago"),
        items=[ItemDTE(numero_linea=1, nombre="Servicio exento", cantidad=1,
                       precio_unitario=10000)])


def _armar(cert, folio: int = _FOLIO):
    """Reproduce el camino real: documento → firma standalone → sobre. Devuelve (str, bytes)."""
    caf = ManejadorCAF(open(_CAF, "rb").read())
    dte = _dte_input(folio)
    tot = calcular_totales(dte.items, dte.tipo_dte)
    ted = caf.generar_ted(
        folio=folio, rut_emisor=dte.emisor.rut, rut_receptor=dte.receptor.rut, tipo_dte=34,
        fecha_emision_dte=dte.fecha_emision, monto_total=tot.monto_total,
        razon_social_receptor=dte.receptor.razon_social, primer_item="Servicio exento")
    doc = GeneradorDTE().generar_documento_xml(dte, ted_xml=ted)
    xml_doc = firmar_documento_standalone(doc, cert, 34, folio)
    xml_envio = armar_sobre_firmado(
        documentos_firmados=[xml_doc], subtotales=[(34, 1)], rut_emisor=dte.emisor.rut,
        rut_envia=cert.rut_emisor, cert=cert, fecha_resolucion="2026-07-08",
        numero_resolucion=0, raiz="EnvioDTE")
    return xml_doc, xml_envio


# ---------------------------------------------------------------------------
def test_firma_standalone() -> None:
    print("\n[1] El DTE se firma STANDALONE (L2.1)")
    cert = CertificadoDigital.desde_archivo(_PFX, _pfx_pass())
    xml_doc, _ = _armar(cert)

    _check("xmlns:xsi" not in xml_doc,
           "el DTE firmado NO lleva xmlns:xsi — se firmó en árbol propio, no dentro del sobre")
    ids = re.findall(r'ID="([^"]+)"', xml_doc)
    uris = re.findall(r'Reference URI="([^"]*)"', xml_doc)
    _check(f"T34F{_FOLIO}" in ids, f"el <Documento> lleva ID=T34F{_FOLIO}")
    _check(uris == [f"#T34F{_FOLIO}"],
           f"la Reference apunta a #T34F{_FOLIO} — el ID que EXISTE "
           f"(el viejo #DTE-34-{_FOLIO} colgaba y el SII no podía dereferenciarlo)")


def test_dte_va_verbatim() -> None:
    print("\n[2] El DTE firmado entra al sobre VERBATIM (L2.2 y L2.3)")
    cert = CertificadoDigital.desde_archivo(_PFX, _pfx_pass())
    xml_doc, xml_envio = _armar(cert)

    # ESTE es el corazón de la ley: si alguien re-parsea o re-serializa el sobre, los bytes
    # del DTE cambian y este test cae.
    _check(xml_doc.encode("ISO-8859-1") in xml_envio,
           "los bytes EXACTOS del DTE firmado aparecen literales dentro del sobre "
           "(nadie lo re-serializó después de firmar)")
    _check(xml_envio.count(b"<DTE ") == 1, "el DTE aparece una sola vez")
    _check(xml_envio.startswith(b'<?xml version="1.0" encoding="ISO-8859-1"?>'),
           "declaración XML con comillas dobles e ISO-8859-1 (el SII rechaza otra cosa)")


def _verificar_firma(cert, raiz, etiqueta: str) -> None:
    """Recomputa digest y SignatureValue de `raiz` como lo haría el SII."""
    pub = cert.certificado.public_key()
    sig = raiz.findall(f"{{{_DS}}}Signature")[-1]
    ref = sig.find(f".//{{{_DS}}}Reference")
    uri = (ref.get("URI") or "")[1:]
    destino = next((e for e in raiz.iter() if e.get("ID") == uri), None)
    _check(destino is not None,
           f"{etiqueta}: la Reference URI='#{uri}' apunta a un ID que EXISTE")
    if destino is None:
        return
    dv = ref.find(f"{{{_DS}}}DigestValue").text
    _check(cert.hash_sha1_b64(_c14n_reparse(destino)) == dv,
           f"{etiqueta}: el DigestValue calza recomputado desde los bytes finales")
    si = sig.find(f"{{{_DS}}}SignedInfo")
    sv = base64.b64decode(sig.find(f"{{{_DS}}}SignatureValue").text)
    try:
        pub.verify(sv, _c14n_reparse(si), padding.PKCS1v15(), hashes.SHA1())
        ok = True
    except Exception:
        ok = False
    _check(ok, f"{etiqueta}: la SignatureValue verifica criptográficamente")


def test_firma_sobrevive_al_sobre() -> None:
    print("\n[3] ⭐ Las firmas verifican sobre los BYTES FINALES (lo que hace el SII)")
    cert = CertificadoDigital.desde_archivo(_PFX, _pfx_pass())
    _, xml_envio = _armar(cert)

    # Se parte del XML SERIALIZADO, como lo recibe el SII — no del árbol en memoria.
    # ⚠️ Cada firma se verifica como la verifica el SII, y NO es igual para las dos:
    #
    #  - SOBRE: en contexto, sobre el documento completo.
    #  - DTE:   el SII lo **EXTRAE como documento independiente**. Por eso aquí se recorta el
    #           `<DTE>…</DTE>` de los bytes crudos y se parsea SOLO. Verificarlo en contexto
    #           FALLA (y es correcto que falle): dentro del sobre, el <Documento> hereda el
    #           `xmlns:xsi` de la raíz y el digest da distinto. Ese es exactamente el
    #           mecanismo del DTE-3-505 — y la razón de que el DTE se firme standalone.
    _verificar_firma(cert, etree.fromstring(xml_envio), "sobre (#SetDoc)")

    txt = xml_envio.decode("ISO-8859-1")
    ini, fin = txt.index("<DTE "), txt.index("</DTE>") + len("</DTE>")
    # Se parsea el `str`, no bytes: el recorte no lleva declaración de encoding, así que como
    # bytes ISO-8859-1 lxml asumiría UTF-8 y reventaría con "Morandé". Misma trampa que
    # documenta `core/sobre.py` — reaparece cada vez que se manipula el sobre a mano.
    dte_suelto = etree.fromstring(txt[ini:fin])
    _check("xsi" not in txt[ini:fin],
           "el <DTE> recortado del sobre NO arrastra xmlns:xsi — se verifica igual que se firmó")
    _verificar_firma(cert, dte_suelto, "DTE extraído del sobre")


def test_xsd_y_perfil() -> None:
    print("\n[4] El sobre valida contra el XSD oficial y respeta el perfil del SII (L8)")
    cert = CertificadoDigital.desde_archivo(_PFX, _pfx_pass())
    _, xml_envio = _armar(cert)

    val = validar_xml_dte(xml_envio)
    _check(val.valido, f"EnvioDTE valida contra EnvioDTE_v10.xsd {val.errores[:2]}")

    root = etree.fromstring(xml_envio)
    for sig in root.iter(f"{{{_DS}}}Signature"):
        # El perfil del SII es RESTRINGIDO: 1 solo Transform, y KeyValue ANTES de X509Data.
        _check(len(sig.findall(f".//{{{_DS}}}Transform")) == 1,
               "un solo Transform (el XSD del SII exige maxOccurs=1; signxml emite 2)")
        hijos = [etree.QName(e).localname for e in sig.find(f"{{{_DS}}}KeyInfo")]
        _check(hijos == ["KeyValue", "X509Data"],
               "KeyInfo = KeyValue y luego X509Data, en ese orden")
        break


def test_encoding_con_acentos() -> None:
    print("\n[5] El armado del sobre soporta acentos (regresión del bug de encoding)")
    cert = CertificadoDigital.desde_archivo(_PFX, _pfx_pass())
    # `armar_sobre_firmado` parsea el str, NO bytes ISO-8859-1: si alguien lo cambia a bytes,
    # lxml asume UTF-8 y revienta con "Morandé" → Invalid bytes in character encoding.
    try:
        _, xml_envio = _armar(cert)
        _check(b"Morand" in xml_envio, "el receptor con acento sobrevive al armado del sobre")
        _check("Morandé" in xml_envio.decode("ISO-8859-1"),
               "y decodifica correcto como ISO-8859-1")
    except Exception as e:
        _check(False, f"el armado reventó con acentos: {type(e).__name__}: {e}")


def test_nadie_firma_a_la_antigua() -> None:
    print("\n[6] Nadie vuelve al camino viejo (regresión de preview.py y api/routes/dte.py)")
    import inspect

    import core.orchestrator as orch
    import core.orchestrator_boleta as ob
    import core.preview as prev

    for mod, nombre in [(orch, "orchestrator"), (ob, "orchestrator_boleta"), (prev, "preview")]:
        src = inspect.getsource(mod)
        _check("armar_sobre_firmado" in src and "firmar_documento_standalone" in src,
               f"{nombre} usa core/sobre.py")
        _check("firmar_documento_xml" not in src,
               f"{nombre} NO usa firmar_documento_xml (esa es SOLO para la semilla del token)")

    # En api/routes/dte.py se mira el CÓDIGO, no los comentarios: ahí `firmar_documento_xml`
    # se menciona a propósito para advertir que no se debe usar.
    codigo_api = "\n".join(l for l in open("api/routes/dte.py").read().splitlines()
                           if not l.lstrip().startswith("#"))
    _check("firmar_documento_standalone" in codigo_api,
           "api/routes/dte.py firma con core/sobre.py")
    _check("firmar_documento_xml" not in codigo_api,
           "api/routes/dte.py ya no usa el método de la semilla para firmar DTEs")


def test_preview_es_prevuelo_fiel() -> None:
    print("\n[7] ⭐ La previsualización produce una firma que el SII aceptaría")
    # ESTA es la regresión que ocurrió de verdad: `preview.py` siguió firmando el DTE
    # EMBEBIDO cuando `core/sobre.py` ya existía. El XSD daba verde y el preview decía
    # "válido" — pero el SII lo habría rechazado con DTE-3-505. Un pre-vuelo que miente es
    # peor que no tenerlo. Se verifica su salida igual que la del sobre: extrayendo el DTE.
    from core.preview import previsualizar_dte

    cert = CertificadoDigital.desde_archivo(_PFX, _pfx_pass())
    caf = ManejadorCAF(open(_CAF, "rb").read())
    r = previsualizar_dte(_dte_input(_FOLIO), cert, caf)

    _check(r["valido_xsd"], f"el preview valida contra el XSD {r['errores_xsd'][:2]}")
    xml_doc = base64.b64decode(r["xml_b64"]).decode("ISO-8859-1")
    _check("xmlns:xsi" not in xml_doc,
           "el DTE del preview NO lleva xmlns:xsi → se firmó standalone, como la emisión real")
    _verificar_firma(cert, etree.fromstring(xml_doc), "DTE del preview")


def main_() -> int:
    print("=" * 66)
    print("  core/sobre.py — la firma que el SII ACEPTA (Ley L2)")
    print("  Referencia: TrackID 253113966 → ACEPTADOS: 1")
    print("=" * 66)
    test_firma_standalone()
    test_dte_va_verbatim()
    test_firma_sobrevive_al_sobre()
    test_xsd_y_perfil()
    test_encoding_con_acentos()
    test_nadie_firma_a_la_antigua()
    test_preview_es_prevuelo_fiel()
    print("\n" + "=" * 66)
    if _check.fallos:
        print(f"❌ {_check.fallos} comprobación(es) fallaron — NO enviar al SII")
        return 1
    print("✅ Todo OK")
    return 0


if __name__ == "__main__":
    sys.exit(main_())
