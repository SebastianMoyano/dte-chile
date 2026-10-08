"""
test_mipyme.py — Blinda el canal MIPYME (`core/sii_mipyme.py`) SIN gastar folios.

**Por qué existe.** El portal MIPYME no tiene sandbox: cada corrida que llega a
`mipeGenXMLFirma` gasta un folio real en PRODUCCIÓN. Las reglas que costaron folios y reparos
(HED-2-220 por montos desalineados, WAF por RUT sin DV, `txtSignText` sin `<Signature>`,
`EFXP_FOLIO` detrás de `PTDC_CODIGO`) se prueban aquí en seco, contra HTML sintético.

Modo `--live`: abre sesión real, selecciona la empresa y LEE el form (paso gratis, no consume
folio), luego cierra la sesión. Pide las claves por consola, nunca por argumentos.

Uso:  .venv/bin/python test_mipyme.py
      .venv/bin/python test_mipyme.py --live --usuario 12.345.678-9 --empresa 77.777.777-7
"""
from __future__ import annotations

import argparse
import logging
import sys

from core.errors import ValidacionError
from core.sii_mipyme import (CAMPOS_HELPER, CAMPOS_MONTO_TOTAL, SCHEMA_CAMPOS, ClienteMipyme,
                             ItemMipyme, ReceptorMipyme, TIPO_FACTURA_EXENTA, TIPO_NOTA_CREDITO, TIPO_NOTA_DEBITO,
                             armar_payload, extraer_xml_dte, parsear_form)

FALLOS = 0
logging.getLogger("core.sii_mipyme").setLevel(logging.ERROR)   # el drift sintético no es ruido útil aquí


def check(cond: bool, msg: str) -> None:
    global FALLOS
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        FALLOS += 1


HTML_FORM = """
<form name="formulario" action="mipeGenXMLFirma.cgi" method="post">
<input type="hidden" name="INDICA_PRIMERA_EJECUCION" value="0">
<input type="hidden" name="PTDC_CODIGO" value="34">
<input name="EFXP_RZN_SOC" value="EMPRESA DEMO SPA">
<input name="EFXP_GIRO_EMIS" value="SERVICIOS">
<input name="EFXP_ACTECO" value="661903"/>
<input name="EFXP_RUT_RECEP" value="11111111"><input name="EFXP_DV_RECEP" value="1">
<input name="EFXP_NMB_01" value="Arriendo viejo"><input name="EFXP_PRC_01" value="999">
<input name="EFXP_SUBT_01" value="999"><input name="EFXP_MNT_TOTAL" value="999">
<select name="EFXP_TIPOVENTA_SELECT"><option value="1">Del giro</option><option value="2" selected>Bienes</option></select>
<select name="EFXP_FMA_PAGO"><option value="1">Contado</option><option value="2">Crédito</option></select>
<textarea name="EFXP_DSC_ITEM_01">Desc vieja</textarea>
<input name="CANT_DET" value="1"><input name="EFXP_DIR_RECEP_DEFUALT" value="x">
<input name="CAMPO_NUEVO_DEL_SII" value="drift">
</form>
"""

RECEPTOR = ReceptorMipyme(rut="76.111.111-6", razon_social="CLIENTE DEMO SPA", giro="SALUD",
                          direccion="CAMINO 1", ciudad="Chillan", comuna="CHILLAN")


def test_schema():
    print("schema")
    check(len(SCHEMA_CAMPOS) == 243, "243 campos (contrato capturado 2026-09-06)")
    check(len(set(SCHEMA_CAMPOS)) == 243, "sin nombres repetidos")
    check(SCHEMA_CAMPOS[0] == "INDICA_PRIMERA_EJECUCION" and SCHEMA_CAMPOS[7] == "PTDC_CODIGO",
          "orden: INDICA_PRIMERA_EJECUCION primero, PTDC_CODIGO octavo")
    check(not (CAMPOS_HELPER & set(SCHEMA_CAMPOS)), "los helpers del HTML no están en el schema")


def test_parser():
    print("parsear_form")
    c = parsear_form(HTML_FORM)
    check(c["EFXP_RZN_SOC"] == "EMPRESA DEMO SPA", "input con value")
    check(c["EFXP_ACTECO"] == "661903", "input auto-cerrado")
    check(c["EFXP_TIPOVENTA_SELECT"] == "2", "select: gana la opción `selected`")
    check(c["EFXP_FMA_PAGO"] == "1", "select sin selected: la primera opción (como el navegador)")
    check(c["EFXP_DSC_ITEM_01"] == "Desc vieja", "textarea con contenido")


def test_payload():
    print("armar_payload")
    campos = parsear_form(HTML_FORM)
    item = ItemMipyme(nombre="Arriendo", precio=3_270_323, descripcion="-Octubre PAGO DE : 3.270.323")
    p = armar_payload(campos, TIPO_FACTURA_EXENTA, RECEPTOR, [item], fecha="2026-10-01")
    nombres = [n for n, _ in p.pares]
    check(nombres == list(SCHEMA_CAMPOS), "el POST lleva los 243 campos en el orden del schema")
    montos = {p.valor("EFXP_PRC_01"), p.valor("EFXP_SUBT_01")} | {p.valor(c) for c in CAMPOS_MONTO_TOTAL}
    check(montos == {"3270323"}, "los 5 montos coinciden (HED-2-220 si no)")
    check(p.valor("EFXP_RZN_SOC") == "EMPRESA DEMO SPA", "los datos del emisor vienen del HTML fresco")
    check(p.valor("EFXP_RUT_RECEP") == "76111111" and p.valor("EFXP_DV_RECEP") == "6",
          "receptor sustituido, RUT partido en número y DV")
    check(p.valor("INDICA_PRIMERA_EJECUCION") == "1" and p.valor("ES_BORR") == "FALSE",
          "flags de primera ejecución")
    check(p.valor("EFXP_NMB_02") == "" and p.valor("EFXP_PRC_02") == "", "ítems sobrantes del último doc limpiados")
    check(p.campos_nuevos == ["CAMPO_NUEVO_DEL_SII"], "drift detectado, helpers ignorados")
    check("CANT_DET" not in nombres, "los helpers no viajan en el POST")

    dos = armar_payload(campos, TIPO_FACTURA_EXENTA, RECEPTOR,
                        [ItemMipyme("A", 100, 2), ItemMipyme("B", 50)])
    check(dos.valor("EFXP_SUBT_01") == "200" and dos.valor("EFXP_MNT_TOTAL") == "250",
          "varios ítems: subtotal por ítem y total sumado")
    try:
        armar_payload(campos, TIPO_FACTURA_EXENTA, RECEPTOR, [])
        check(False, "sin ítems debe fallar")
    except ValidacionError:
        check(True, "sin ítems → ValidacionError")

    nc = armar_payload(campos, TIPO_NOTA_CREDITO, RECEPTOR, [item], fecha="2026-10-01",
                       referencias=[{"tipo": 34, "folio": 57, "fecha": "2026-09-06"}])
    import re as _re
    html_nota = _re.sub(r'<select name="EFXP_FMA_PAGO">.*?</select>', '<input type="hidden" name="EFXP_FMA_PAGO" value="">', HTML_FORM, flags=_re.S) \
        .replace('name="INDICA_PRIMERA_EJECUCION" value="0"', 'name="INDICA_PRIMERA_EJECUCION" value="1"') \
        + '<input type="hidden" name="ES_BORR" value="">'
    nota = armar_payload(parsear_form(html_nota), TIPO_NOTA_CREDITO, RECEPTOR, [item], forma_pago="",
                         referencias=[{"tipo": 34, "folio": 57, "fecha": "2026-09-06"}],
                         respetar_html=("ES_BORR", "EFXP_FMA_PAGO", "INDICA_PRIMERA_EJECUCION"))
    check(nota.valor("ES_BORR") == "" and nota.valor("EFXP_FMA_PAGO") == "" and nota.valor("INDICA_PRIMERA_EJECUCION") == "1",
          "en una nota se respetan ES_BORR, FMA_PAGO e INDICA tal como vienen del portal")
    check(nc.valor("PTDC_CODIGO") == "61" and nc.valor("EFXP_TPO_DOC_REF_001") == "34"
          and nc.valor("EFXP_FOLIO_REF_001") == "57" and nc.valor("EFXP_CODIGO_REF_001") == "1"
          and nc.valor("EFXP_RAZON_REF_001") == "ANULA DOCUMENTO DE LA REFERENCIA",
          "NC de anulación: PTDC_CODIGO=61 + referencia CODIGO_REF=1")


def test_extraer_xml():
    print("extraer_xml_dte")
    crudo = '<?xml version="1.0"?><DTE><Documento><Folio>59</Folio></Documento></DTE>'
    check(extraer_xml_dte(f"<html><script>var xmlDte = '{crudo}';</script></html>") == crudo,
          "XML dentro de una variable JS: sin el `var ... ;`")
    check(extraer_xml_dte(f"<html><pre>{crudo}</pre></html>") == crudo, "XML suelto en la página")
    check(extraer_xml_dte("<html>nada</html>") is None, "sin XML → None")


def test_cliente_sin_red():
    print("ClienteMipyme (sin red)")
    try:
        ClienteMipyme("12345678-0", "x", "y")
        check(False, "RUT inválido debe fallar")
    except ValidacionError:
        check(True, "RUT de usuario inválido → ValidacionError")
    cli = ClienteMipyme("12.345.678-5", "trib", "cert")
    check(cli.rut_usuario == "12345678-5", "RUT normalizado sin puntos, con DV")
    try:
        cli.emitir(armar_payload({}, 34, RECEPTOR, [ItemMipyme("A", 1)]))
        check(False, "emitir sin confirmar debe fallar")
    except ValidacionError:
        check(True, "emitir() sin confirmar=True no toca el SII")
    cli.empresa = "77777777-7"
    try:
        # La nota de débito (56) sigue sin corrida real desde el repo (34 y 61 ya están verificadas).
        cli.emitir(armar_payload({}, TIPO_NOTA_DEBITO, RECEPTOR, [ItemMipyme("A", 1)]), confirmar=True)
        check(False, "emitir una cadena no verificada sin aceptar el riesgo debe fallar")
    except ValidacionError as e:
        check("NO está verificada" in e.mensaje, "tipo fuera de CADENAS_VERIFICADAS → exige aceptar_riesgo_folio")
    cli.empresa = None
    try:
        cli.leer_form()
        check(False, "leer_form sin empresa debe fallar")
    except ValidacionError:
        check(True, "leer_form() sin sesión/empresa → ValidacionError")
    cli.cerrar()
    check(True, "cerrar() sin sesión no revienta")


def test_encoding_body():
    print("encoding (L8)")
    from core.sii_mipyme import _body
    b = _body([("EFXP_CIUDAD_RECEP", "Concepción"), ("x", "Ñuñoa")])
    check(b"%F1" in b and b"%D1" in b and b"%C3" not in b, "el body va en ISO-8859-1, no UTF-8")
    # _req codifica también los POST con `data=` (login, selEmpresa, postFirmaDigital)
    cli = ClienteMipyme("12.345.678-5", "trib", "cert")
    capturado = {}

    def fake_request(metodo, url, content=None, params=None, headers=None):
        capturado["content"] = content
        capturado["headers"] = headers
        raise RuntimeError("stop")  # no salimos a la red

    cli._s.request = fake_request  # type: ignore[assignment]
    try:
        cli._req("POST", "https://x", data={"a": "ñ"}, navegacion=False)
    except RuntimeError:
        pass
    check(capturado.get("content") == b"a=%F1", "_req codifica `data=` en latin-1 (httpx usaría UTF-8)")
    check(capturado["headers"]["Sec-Fetch-Mode"] == "cors", "POST de fondo lleva Sec-Fetch-Mode: cors")
    cli.cerrar()


def test_registrar_en_bd():
    print("registrar_en_bd (BD temporal)")
    import tempfile
    from pathlib import Path
    import core.database as db
    from core.models import listar_dtes, obtener_dte
    from core.sii_mipyme import ResultadoMipyme, registrar_en_bd

    original = db.DATABASE_PATH
    with tempfile.TemporaryDirectory() as d:
        db.DATABASE_PATH = Path(d) / "t.db"
        try:
            db.init_db()
            res = ResultadoMipyme(tipo=34, folio=59, dhdr="2850540417", xml_firmado="<DTE/>", monto_total=3_270_323)
            dte_id = registrar_en_bd(res, "77.777.777-7", RECEPTOR, "2026-09-06")
            fila = obtener_dte(dte_id)
            check(fila["rut_emisor"] == "77777777-7" and fila["rut_receptor"] == "76111111-6",
                  "RUTs guardados en el formato canónico del motor (sin puntos)")
            check(fila["estado"] == "emitido_mipyme" and fila["ambiente"] == "produccion", "estado emitido_mipyme, ambiente produccion")
            check(fila["track_id"] == 2850540417 and fila["monto_exento"] == 3_270_323 and fila["iva"] == 0,
                  "DHDR en track_id; monto como exento")
            check(len(listar_dtes(rut_emisor="77777777-7")) == 1, "listar_dtes lo encuentra por el RUT canónico")
        finally:
            db.DATABASE_PATH = original


HTML_LISTADO = """
<table>
<tr><th>RUT</th><th>Razón Social</th><th>Tipo</th><th>Folio</th><th>Fecha</th><th>Monto</th><th>Estado</th><th></th></tr>
<tr><td>76.111.111-6</td><td>CLIENTE DEMO SPA</td><td>FACTURA NO AFECTA O EXENTA ELECTRONICA</td><td>59</td>
    <td>06/09/2026</td><td>3.270.323</td><td>Aceptado</td><td><a href="mipeGesDocEmi.cgi?ALL_PAGE_ANT=2&CODIGO=2850540417">ver</a></td></tr>
<tr><td>76.111.111-6</td><td>CLIENTE DEMO SPA</td><td>NOTA DE CREDITO ELECTRONICA</td><td>56</td>
    <td>2026-09-06</td><td>$3.068.005</td><td>Aceptado con Reparos</td><td><a href="mipeGesDocEmi.cgi?CODIGO=2850540999">ver</a></td></tr>
<tr><td colspan="8">Página 1 de 3</td></tr>
</table>
"""


def test_listado():
    print("parsear_listado / importar_emitidos")
    from core.sii_mipyme import parsear_listado, tipo_desde_texto
    docs, ultima = parsear_listado(HTML_LISTADO)
    check(len(docs) == 2 and ultima == 3, "2 filas con DHDR y 'Página 1 de 3'")
    f, nc = docs
    check(f.dhdr == "2850540417" and f.folio == 59 and f.fecha == "2026-09-06" and f.monto == 3_270_323,
          "DHDR del enlace, folio, fecha DD/MM/YYYY→ISO, monto con puntos")
    check(f.tipo == 34 and nc.tipo == 61, "tipo desde el texto: exenta→34, NC→61")
    check(nc.fecha == "2026-09-06" and nc.monto == 3_068_005, "fecha ISO se respeta, monto con $")
    check(tipo_desde_texto("FACTURA ELECTRONICA") == 33 and tipo_desde_texto("GUIA DE DESPACHO ELECTRONICA") == 52
          and tipo_desde_texto("RARO") is None, "mapa de tipos por texto")

    import tempfile
    from pathlib import Path
    import core.database as db
    from core.models import listar_dtes, obtener_dte_por_folio
    from core.sii_mipyme import importar_emitidos
    class _Cli:  # no toca la red: el PDF viene de aquí
        def descargar_pdf(self, dhdr): return b"%PDF-1.4 fake " + dhdr.encode()
    original = db.DATABASE_PATH
    with tempfile.TemporaryDirectory() as d:
        db.DATABASE_PATH = Path(d) / "t.db"
        try:
            db.init_db()
            r1 = importar_emitidos(_Cli(), "77.777.777-7", docs, carpeta=str(Path(d) / "pdfs"), pausa=0)
            check(r1["importados"] == 2 and r1["pdf_ok"] == 2, "importa 2 y baja 2 PDF")
            fila = obtener_dte_por_folio("77777777-7", 34, 59)
            check(fila and fila["estado"] == "emitido_mipyme" and fila["track_id"] == 2850540417
                  and fila["rut_receptor"] == "76111111-6" and Path(fila["pdf_path"]).exists(),
                  "fila en dtes con DHDR, receptor canónico y PDF en disco")
            r2 = importar_emitidos(_Cli(), "77777777-7", docs, carpeta=str(Path(d) / "pdfs"), pausa=0)
            check(r2["importados"] == 0 and r2["ya_existian"] == 2 and r2["pdf_ok"] == 0,
                  "segunda corrida: idempotente, no rebaja PDF")
            check(len(listar_dtes(rut_emisor="77777777-7")) == 2, "listar_dtes los ve")
        finally:
            db.DATABASE_PATH = original


def test_guardarrail_nc():
    print("guardarraíl NC de anulación (total desde el PDF del SII)")
    import glob
    from core.sii_mipyme import total_desde_pdf
    pdfs = {f.split("_F")[1].split("_")[0]: f for f in glob.glob("storage/pdfs/mipyme/*/T34_F5[79]_*.pdf")}
    if "57" not in pdfs or "59" not in pdfs:
        print("  (sin los PDF reales de la 57/59 en storage: se omite)")
        return
    t57 = total_desde_pdf(open(pdfs["57"], "rb").read()); t59 = total_desde_pdf(open(pdfs["59"], "rb").read())
    check(t57 == 3_068_005, f"factura 57: el TOTAL firmado es 3.068.005 aunque la línea diga 3.270.323 (leído {t57})")
    check(t59 == 3_270_323, f"factura 59: TOTAL 3.270.323 (leído {t59})")

    cli = ClienteMipyme("12.345.678-5", "trib", "cert"); cli.empresa = "77777777-7"
    cli.descargar_pdf = lambda dhdr: open(pdfs["57"], "rb").read()   # sin red
    try:
        cli.preparar_nc_anulacion("x", 34, 57, "2026-09-06", RECEPTOR, [ItemMipyme("Arriendo", 3_270_323)])
        check(False, "NC por 3.270.323 contra la 57 debería rechazarse")
    except ValidacionError as e:
        check(e.detalle.get("total_registrado") == 3_068_005, "NC con monto ≠ total registrado → ValidacionError antes de gastar folio")
    cli.cerrar()


def test_form_firma():
    print("frmSign de mipeGenXMLFirma")
    from core.sii_mipyme import armar_send_xml_desde_form, extraer_form_firma
    html = ('<html><form name="PreViewDTE" action="x"><input name="a" value="1"></form>'
            '<form name="frmSign" method="post" action="/cgi-bin/Portal001/mipeSendXML.cgi">'
            '<input type="hidden" name="txtPlainText" value="&lt;DTE/&gt;"><input type="hidden" name="PTDC_CODIGO" value="61">'
            '<input type="hidden" name="EFXP_FOLIO" value="58"><input type="button" name="btnSign" value="Firmar"></form></html>')
    f = extraer_form_firma(html)
    check(f is not None and f["action"].endswith("mipeSendXML.cgi") and f["campos"]["EFXP_FOLIO"] == "58", "encuentra frmSign, su action y sus campos")
    lista = armar_send_xml_desde_form(f, "<DTE><Signature/></DTE>", "clave", "2026-10-02T10:00:00")
    pares = dict(lista); nombres = [k for k, _ in lista]
    check(pares["txtSignText"] == "<DTE><Signature/></DTE>" and pares["TMST_SIGN"] == "2026-10-02T10:00:00"
          and pares["clave"] == "clave" and pares["nodo"] == "dte:DTE" and "btnSign" not in pares and pares["PTDC_CODIGO"] == "61",
          "body = campos del form + firma, sin los botones")
    check(nombres == sorted(nombres), "los campos van ordenados por nombre (ASCII), como el navegador (captura 2026-10-08)")
    f2 = extraer_form_firma(html.replace('name="txtPlainText"', 'name="TMST_SIGN" value="2026-04-07T21:28:49"><input type="hidden" name="txtPlainText"'))
    check(dict(armar_send_xml_desde_form(f2, "x", "c", "2026-10-02T10:00:00"))["TMST_SIGN"] == "2026-04-07T21:28:49",
          "TMST_SIGN conserva el valor de la página de firma")
    check(extraer_form_firma("<html>sin form</html>") is None, "sin frmSign → None (cae a la reconstrucción)")


def test_hallazgos_revision():
    print("hallazgos de la revisión (firma JSON, SUBTOTAL, latin-1 estricto, form de nota, tachado)")
    from core.sii_mipyme import parsear_respuesta_firma, total_desde_pdf, _body, _guardar_evidencia
    xml = '<?xml version="1.0"?><DTE><Signature/></DTE>'
    check(parsear_respuesta_firma(xml) == (0, xml), "respuesta XML cruda → (0, xml)")
    check(parsear_respuesta_firma('while(1);{"status":0,"text":"<DTE><Signature/></DTE>"}') == (0, "<DTE><Signature/></DTE>"),
          "respuesta JSON con prefijo anti-JSON → se usa solo `text`")
    check(parsear_respuesta_firma('{statusCode:2,text:"clave no corresponde"}')[0] == 2, "objeto estilo JS con status 2")
    check(parsear_respuesta_firma("<html>error</html>") == (-1, ""), "basura → (-1, '')")
    try:
        _body([("a", "€")]); check(False, "€ no es latin-1: debe fallar")
    except ValidacionError:
        check(True, "carácter fuera de ISO-8859-1 → ValidacionError, nada se reemplaza en silencio")
    campos = parsear_form(HTML_FORM)
    nota = armar_payload(campos, TIPO_NOTA_CREDITO, RECEPTOR, [ItemMipyme("A", 10)],
                         referencias=[{"tipo": 34, "folio": 1, "fecha": "2026-01-01"}])
    nombres = [n for n, _ in nota.pares]
    check(nombres[:3] == list(campos)[:3] and "CAMPO_NUEVO_DEL_SII" in nombres,
          "nota: el payload sigue el orden del HTML y conserva los campos que el schema no conoce")
    check(len(set(nombres)) == len(nombres) and set(SCHEMA_CAMPOS) <= set(nombres), "nota: sin duplicados y con todo el schema")
    fac = armar_payload(campos, TIPO_FACTURA_EXENTA, RECEPTOR, [ItemMipyme("A", 10)])
    check(fac.valor("EFXP_PCTD_01") == "" and fac.valor("EFXP_FOLIO_REF_001") == "", "factura: no hereda descuentos ni referencias del último documento")
    import tempfile, pathlib, shutil
    c = _guardar_evidencia("11111111-1", 61, 0, "x", "a=p%40ss+w%26x b=p@ss w&amp;x c=p@ss w&x d=p%40ss%20w%26x",
                           None, [("clave", "p@ss w&x")], ("p@ss w&x",))
    txt = pathlib.Path(c, "respuesta_x.html").read_text(encoding="iso-8859-1")
    check("p@ss" not in txt and "p%40ss" not in txt and txt.count("***") == 4,
          "el tachado cubre la clave literal, url-encoded (quote y quote_plus) y html-escapada")
    shutil.rmtree(pathlib.Path(c).parent)


def test_total_pdf_subtotal():
    print("TOTAL vs SUBTOTAL en el PDF")
    try:
        from reportlab.pdfgen import canvas
    except ImportError:
        print("  (sin reportlab: se omite)"); return
    import io
    from core.sii_mipyme import total_desde_pdf
    buf = io.BytesIO(); cv = canvas.Canvas(buf)
    for i, ln in enumerate(["SUBTOTAL $ 1.000.000", "DESCUENTO $ 100.000", "TOTAL $ 900.000"]):
        cv.drawString(50, 700 - 20 * i, ln)
    cv.save()
    check(total_desde_pdf(buf.getvalue()) == 900_000, "con SUBTOTAL antes del TOTAL se toma el TOTAL (900.000)")


def test_firma_navegador():
    print("firma central como el navegador (captura 2026-10-04)")
    from core.sii_mipyme import COMENTARIO_FIRMA, preparar_dato_firma
    xml = '<?xml version="1.0"?>\n<DTE xmlns="x" version="1.0">\n<Documento ID="F1">A &amp; B</Documento></DTE>'
    d = preparar_dato_firma(xml)
    check(d.startswith('<?xml version="1.0"?>\n<DTE xmlns="x" version="1.0">\n' + COMENTARIO_FIRMA + "\n<Documento "),
          "antepone el comentario <!-- O … central … --> al <Documento")
    check("A &amp;amp; B" in d, "escapa & como el JS del portal (sí, doble)")
    check(preparar_dato_firma(d).count("<!-- O") == 1, "no duplica el comentario")
    env = '<?xml version="1.0"?><EnvioDTE><SetDTE ID="S"><DTE><Documento ID="F"></Documento></DTE></SetDTE></EnvioDTE>'
    check(COMENTARIO_FIRMA + "\n<Documento " in preparar_dato_firma(env), "en un EnvioDTE el comentario va antes del <Documento interno")
    check("v20170209" in COMENTARIO_FIRMA and "central" in COMENTARIO_FIRMA, "comentario con la versión capturada del navegador real")


def test_correccion_montos():
    print("NC de corrección de montos (contrato capturado 2026-10-04)")
    from core.sii_mipyme import CAMPOS_VALIDAR_CORR_MNT, CODIGO_REF_CORRIGE_MONTO, RAZON_REF_CORRIGE_MONTO
    check(len(CAMPOS_VALIDAR_CORR_MNT) == 60 and len(set(CAMPOS_VALIDAR_CORR_MNT)) == 60, "60 campos exactos de 'Validar y visualizar'")
    check({"TIPO_PLANTILLA", "REF_SI_NO", "CANT_DET", "MNT_TOTAL_ORI", "EFXP_CODIGO_REF_001"} <= set(CAMPOS_VALIDAR_CORR_MNT), "incluye plantilla, referencia y helpers")
    check(CODIGO_REF_CORRIGE_MONTO == "3" and RAZON_REF_CORRIGE_MONTO == "CORRIGE MONTO", "código 3 + razón como el portal")
    cli = ClienteMipyme("12.345.678-5", "trib", "cert"); cli.empresa = "77777777-7"
    # sin red: el form y la vista previa se simulan
    form_html = HTML_FORM.replace('name="EFXP_MNT_TOTAL" value="999"', 'name="EFXP_MNT_TOTAL" value="3068005"') + "x" * 5000
    vista_html = HTML_FORM.replace('name="INDICA_PRIMERA_EJECUCION" value="0"', 'name="INDICA_PRIMERA_EJECUCION" value="1"').replace("formulario", "PreViewDTE")
    llamadas = []
    class R:  # respuesta falsa
        def __init__(self, t): self.status_code = 200; self.content = t.encode("latin-1", "replace"); self.text = t; self.headers = {}
    def fake_req(metodo, url, **kw):
        llamadas.append((metodo, url, kw.get("content")))
        return R(form_html if metodo == "GET" else vista_html)
    cli._req = fake_req
    p = cli.preparar_nc_correccion_montos("2850551452", 34, 57, "2026-09-06", RECEPTOR, [ItemMipyme("Arriendo", 3_068_005, descripcion="Corrige Factura Exenta N 57")])
    check([m for m, _, _ in llamadas] == ["GET", "POST"] and "mipeDisplayPreView" in llamadas[1][1], "GET del form y POST a mipeDisplayPreView")
    cuerpo = llamadas[1][2].decode("ascii"); nombres = [par.split("=")[0] for par in cuerpo.split("&")]
    check(nombres == list(CAMPOS_VALIDAR_CORR_MNT), "el POST lleva los 60 campos en el orden capturado")
    check("TIPO_PLANTILLA=CORR_MNT_V_NC" in cuerpo and "EFXP_CODIGO_REF_001=3" in cuerpo and "EFXP_RAZON_REF_001=CORRIGE+MONTO" in cuerpo
          and "MNT_TOTAL_ORI=3068005" in cuerpo and "EFXP_PRC_01=3068005" in cuerpo and "EFXP_MNT_TOTAL=3068005" in cuerpo,
          "plantilla, referencia código 3, total original y los 5 montos")
    check(p.tipo == 61 and p.valor("EFXP_CODIGO_REF_001") == "3" and p.valor("EFXP_MNT_TOTAL") == "3068005", "payload de GenXMLFirma: NC 61 con referencia 3")
    try:
        cli.preparar_nc_correccion_montos("x", 34, 57, "2026-09-06", RECEPTOR, [ItemMipyme("A", 9_999_999)])
        check(False, "una NC mayor que el total debe fallar")
    except ValidacionError:
        check(True, "NC mayor que el total registrado → ValidacionError antes de gastar folio")
    cli.cerrar()


def test_rcv_csv():
    print("RCV: CSV real de ventas y compras (capturado 2026-10-04)")
    from core.rcv import normalizar_detalle, VENTA, COMPRA
    v = normalizar_detalle("77777777-7", VENTA, "202610", {"data": [
        "Nro;Tipo Doc;Tipo Venta;Rut cliente;Razon Social;Folio;Fecha Docto;Fecha Recepcion;Fecha Acuse Recibo;Fecha Reclamo;Monto Exento;Monto Neto;Monto IVA;Monto total;IVA Retenido Total",
        "1;56;Del Giro;76111111-6;CLIENTE DEMO SPA;1;02/10/2026;02/10/2026 19:31:23;;;3270323;0;0;3270323;0"]})
    check(len(v) == 1 and v[0].tipo_dte == 56 and v[0].folio == 1 and v[0].fecha_doc == "2026-10-02" and v[0].monto_exento == 3270323 and v[0].rut_contraparte == "76111111-6",
          "ventas: tipo, folio, fecha ISO, exento y RUT del cliente")
    c = normalizar_detalle("77777777-7", COMPRA, "202609", {"data": [
        "Nro;Tipo Doc;Tipo Compra;RUT Proveedor;Razon Social;Folio;Fecha Docto;Fecha Recepcion;Fecha Acuse;Monto Exento;Monto Neto;Monto IVA Recuperable;Monto Iva No Recuperable;Codigo IVA No Rec.;Monto Total;Monto Neto Activo Fijo;IVA Activo Fijo",
        "1;33;Del Giro;76222222-1;PROVEEDOR DEMO LTDA;65035;18/09/2026;18/09/2026 20:30:05;;0;55929;10627;;;76720;;"]})
    check(len(c) == 1 and c[0].monto_neto == 55929 and c[0].monto_iva == 10627 and c[0].monto_total == 76720 and c[0].rut_contraparte == "76222222-1",
          "compras: neto no lo pisa 'Monto Neto Activo Fijo' vacío; IVA recuperable → monto_iva")


def live(usuario: str, empresa: str) -> None:
    import getpass
    print(f"\n--live: sesión REAL en PRODUCCIÓN con {usuario}, empresa {empresa}. Solo lee el form (no gasta folio).")
    from core.sii_mipyme import LLAVERO_CLAVE_TRIBUTARIA, clave_desde_llavero
    clave = clave_desde_llavero(LLAVERO_CLAVE_TRIBUTARIA, usuario)
    if clave:
        print("  clave tributaria tomada del Llavero (sii-clave-tributaria)")
    else:
        clave = getpass.getpass("Clave tributaria (login): ")
    with ClienteMipyme(usuario, clave, clave_certificado="") as cli:
        cli.iniciar_sesion()
        check(True, "login: cookies NETSCAPE_LIVEWIRE presentes")
        cli.seleccionar_empresa(empresa)
        check(True, "mipeSelEmpresa aceptó el RUT con DV (el WAF no rechazó)")
        campos = cli.leer_form()
        check(len(campos) >= 30, f"form pre-llenado leído: {len(campos)} campos")
        p = armar_payload(campos, TIPO_FACTURA_EXENTA, RECEPTOR, [ItemMipyme("prueba", 1)])
        check(not p.campos_nuevos, f"sin drift del form (campos nuevos: {p.campos_nuevos})")
        print(f"  emisor según el portal: {campos.get('EFXP_RZN_SOC', '?')} / {campos.get('EFXP_GIRO_EMIS', '?')}")
        print("  enlaces del menú de la empresa (para ubicar historial/XML sin adivinar):")
        for texto, href in cli.enlaces_menu():
            print(f"    - {texto[:50]:50} {href}")
    check(True, "sesión cerrada (autTermino)")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true", help="sesión real, solo lectura del form")
    ap.add_argument("--usuario", help="RUT del usuario que entra (con DV)")
    ap.add_argument("--empresa", help="RUT de la empresa a operar (con DV)")
    a = ap.parse_args()
    for t in (test_schema, test_parser, test_payload, test_extraer_xml, test_cliente_sin_red,
              test_encoding_body, test_registrar_en_bd, test_listado, test_guardarrail_nc, test_form_firma, test_hallazgos_revision, test_total_pdf_subtotal, test_firma_navegador, test_correccion_montos, test_rcv_csv):
        t()
    if a.live:
        if not (a.usuario and a.empresa):
            print("--live necesita --usuario y --empresa")
            return 2
        live(a.usuario, a.empresa)
    print(f"\n{'TODO OK' if not FALLOS else f'{FALLOS} fallo(s)'}")
    return 1 if FALLOS else 0


if __name__ == "__main__":
    sys.exit(main())
