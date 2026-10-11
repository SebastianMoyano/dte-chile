#!/usr/bin/env python3
"""Esperado para el port del portal del SII (nucleo/portal): los parsers de las páginas y el
diagnóstico del onboarding, corridos en Python sobre HTML SINTÉTICO (no hay capturas reales
versionadas) y sobre dobles del portal. Go debe producir el mismo JSON. L15: no regenerar
para que un test pase. Correr: .venv/bin/python tests/dorado/portal/generar_esperado.py"""
import json
import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(RAIZ))
os.environ["NOMBRE_SOFTWARE"] = "DTE Chile, Motor Demo"

from core import sii_portal  # noqa: E402
from core.sii_portal import (BASE_CERTIFICACION, BASE_PRODUCCION, DocumentoAutorizado,  # noqa: E402
                             EmpresaAutorizadaDTE, PortalSII)

AQUI = Path(__file__).parent

HTML = {
    "ee_empresa_rut": """<html><body><table><tr><td><b>Nombres</b></td><td>EMPRESA DEMO SPA</td></tr>
<tr><td>N&deg; Resoluci&oacute;n</td><td>80</td></tr><tr><td>Fecha Resoluci&oacute;n</td><td>22-08-2014</td></tr>
<tr><td>Direcci&oacute;n Regional</td><td>SANTIAGO CENTRO</td></tr></table>
<p>El contribuyente se encuentra autorizada la emisi&oacute;n de los siguientes documentos:</p>
<table><tr><th>Código</th><th>Documento</th><th>Autorizado</th><th>Desautorizado</th></tr>
<tr><td>33</td><td>FACTURA ELECTRONICA</td><td>01-02-2026</td><td></td></tr>
<tr><td>34</td><td>FACTURA NO AFECTA O EXENTA ELECTRONICA</td><td>01-02-2026</td><td>15-03-2026</td></tr>
<tr><td>39</td><td>BOLETA ELECTRONICA</td><td>05-02-2026</td><td></td></tr>
<tr><td>61</td><td>NOTA DE CREDITO ELECTRONICA</td><td>01-02-2026</td><td></td></tr></table></body></html>""",
    "ee_empresa_rut_no": "<html><body><p>El RUT ingresado no est&aacute; autorizado</p></body></html>",
    "ad_empresa2": """<table><tr><td><font size=2>Nombre del Software (*)</font></td><td><font size=2>&nbsp;Motor Demo 2</font></td></tr>
<tr><td><font>Resoluci&oacute;n</font></td><td><font> 0 </font></td></tr>
<tr><td><font>Fecha Resoluci&oacute;n</font></td><td><font></font></td></tr>
<tr><td><font>Mail Contacto</font></td><td><font>admin@demo.cl</font></td></tr></table>""",
    "ad_empresa2_sii": """<table><tr><td><font>Nombre del Software (*)</font></td><td><font>SII</font></td></tr>
<tr><td><font>Resolución</font></td><td><font>123</font></td></tr><tr><td><font>Fecha Resolución</font></td><td><font>2026-01-01</font></td></tr></table>""",
    "mipeSelEmpresa": """<select name="RUT_EMP"><option value="">Seleccione</option>
<option value="77777777-7">EMPRESA DEMO SPA, 77.777.777-7</option>
<option value='76111111-6'>CLIENTE DEMO SPA 76111111-6</option>
<option value="12345678-5">ANA DEMO 12.345.678-5</option><option value="abc">nada</option></select>""",
    "of_consulta2_folio": """<table><tr><td>Fecha</td><td>Cant</td><td>Desde</td><td>Hasta</td><td>Mandatario</td></tr>
<tr><td>10-01-2026</td><td>5</td><td>1</td><td>5</td><td>ANA DEMO</td></tr>
<tr><td>15-02-2026</td><td>10</td><td>6</td><td>15</td><td>JUAN PÉREZ</td></tr>
<tr><td>15-02-2026</td><td>10</td><td>6</td><td>15</td><td>JUAN PÉREZ</td></tr>
<tr><td>01-03-2026</td><td>2</td><td>16</td><td>17</td><td>ANA DEMO</td></tr></table> Anterior Siguiente""",
    "af_anular2": """<form action="af_anular3" method=post><input type=hidden name="FOLIO_INI" value="6"><input type="hidden" name="FOLIO_FIN" value="15">
<input name='CANT_DOCTOS' value='10'><input name="DIA" value="15"><input name="MES" value="02"><input name="ANO" value="2026"></form>
<form action="af_anular3"><input name="FOLIO_INI" value="1"><input name="FOLIO_FIN" value="5"><input name="CANT_DOCTOS" value="5"><input name="DIA" value="10"><input name="MES" value="01"><input name="ANO" value="2026"></form>
<form action="otra"><input name="X" value="1"></form>""",
    "af_anular_ok": "<html><body>El SII ha autorizado la anulaci&oacute;n del rango</body></html>",
    "af_anular_recep": "<html>Existe al menos un folio recepcionado</html>",
    "af_anular_antes": "<html>Rango anulado anteriormente</html>",
    "af_anular_raro": "<html>???</html>",
    "bloqueado": "<html><b>NO SE AUTORIZA</b> el timbraje</html>",
    "libre": "<html>Folio inicial 18</html>",
    "of_confirma_folio": """<form name="f" action="https://maullin.sii.cl/cvc_cgi/dte/of_genera_folio" method="post">
<input type="hidden" name="RUT_EMP" value="77777777"><input type="hidden" name="DV_EMP" value="7">
<input type="hidden" name="COD_DOCTO" value="33"><input type="hidden" name="FOLIO_INI" value="18"><input type="hidden" name="FOLIO_FIN" value="18">
<input type=hidden name=HORA value=10><input type=hidden name=MINUTO value='30'><input type="submit" name="ACEPTAR" value="Generar"></form>""",
}


class _Resp:
    def __init__(self, text):
        self.text = text
        self.content = text.encode("latin-1", "replace")


class _Fake:
    """Doble de ClienteReintentos: responde por el sufijo de la URL."""
    paginas = {}
    cookies = {}

    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass

    def post(self, url, data=None, **k):
        return _Resp(self.paginas[url.rsplit("/", 1)[-1]])

    def get(self, url, **k):
        return _Resp(self.paginas[url.rsplit("/", 1)[-1]])


def pagina_real(rut="77777777-7"):
    """La página pública ee_empresa_rut del RUT DE PRUEBA del SII (ficticio por diseño del SII),
    decodificada como la ve Python (resp.text). Red solo al generar; si falla, se omite."""
    from core.reintentos import ClienteReintentos
    n, dv = rut.split("-")
    try:
        with ClienteReintentos(verify=True, timeout=25, follow_redirects=True, headers=sii_portal._UA) as c:
            return c.post(f"{BASE_CERTIFICACION}/ee_empresa_rut", data={"CNSLT": "R", "RUT_EMP": n, "DV_EMP": dv, "ACEPTAR": "Consultar"}).text
    except Exception as e:  # noqa: BLE001
        print("sin página real:", e)
        return None


def main():
    real = pagina_real()
    if real:
        HTML["ee_empresa_rut_real"] = real
    sii_portal.ClienteReintentos = _Fake
    portal = PortalSII(base=BASE_CERTIFICACION)
    portal.cookies = {"TOKEN": "x"}
    out = {}
    _Fake.paginas = {"ee_empresa_rut": HTML["ee_empresa_rut"]}
    emp = portal.consultar_empresa_autorizada("77.777.777-7")
    out["empresa_autorizada"] = {"rut": emp.rut, "razon_social": emp.razon_social, "nro_resolucion": emp.nro_resolucion,
                                 "fecha_resolucion": emp.fecha_resolucion, "direccion_regional": emp.direccion_regional,
                                 "documentos": [vars(d) for d in emp.documentos]}
    _Fake.paginas = {"ee_empresa_rut": HTML["ee_empresa_rut_no"]}
    out["empresa_no_autorizada"] = portal.consultar_empresa_autorizada("77777777-7")
    if real:
        _Fake.paginas = {"ee_empresa_rut": real}
        e = portal.consultar_empresa_autorizada("77777777-7")
        out["empresa_autorizada_real"] = {"rut": e.rut, "razon_social": e.razon_social, "nro_resolucion": e.nro_resolucion,
                                          "fecha_resolucion": e.fecha_resolucion, "direccion_regional": e.direccion_regional,
                                          "documentos": [vars(d) for d in e.documentos]}
    _Fake.paginas = {"ad_empresa2": HTML["ad_empresa2"]}
    out["software"] = portal.datos_software("77777777-7")
    _Fake.paginas = {"ad_empresa2": HTML["ad_empresa2_sii"]}
    out["software_sii"] = portal.datos_software("77777777-7")
    _Fake.paginas = {"mipeSelEmpresa.cgi": HTML["mipeSelEmpresa"]}
    out["empresas_asociadas"] = portal.empresas_asociadas()
    _Fake.paginas = {"of_consulta2_folio": HTML["of_consulta2_folio"]}
    out["timbrajes"] = [vars(r) for r in portal.consultar_timbrajes("77777777-7", 33)]
    _Fake.paginas = {"af_anular2": HTML["af_anular2"]}
    out["anulables"] = [vars(r) for r in portal.listar_anulables("77777777-7", 33)]
    out["anulacion"] = {}
    for k in ("af_anular_ok", "af_anular_recep", "af_anular_antes", "af_anular_raro"):
        _Fake.paginas = {"af_anular2": HTML["af_anular2"], "af_anular3": "", "af_anular": HTML[k]}
        out["anulacion"][k] = vars(portal.anular_folios("77777777-7", 33, 7, 9))
    _Fake.paginas = {"af_anular2": HTML["af_anular2"], "af_anular3": "", "af_anular": HTML["af_anular_ok"]}
    out["anulacion"]["sin_padre"] = vars(portal.anular_folios("77777777-7", 33, 100, 101))
    _Fake.paginas = {"of_solicita_folios_dcto": HTML["bloqueado"]}
    out["situacion_bloqueada"] = {str(k): v for k, v in portal.situacion_folios("77777777-7", [33, 61]).items()}
    _Fake.paginas = {"of_solicita_folios_dcto": HTML["libre"]}
    out["situacion_libre"] = {str(k): v for k, v in portal.situacion_folios("77777777-7", [39]).items()}
    out["campos_form"] = PortalSII._campos_form(HTML["of_confirma_folio"], "of_genera_folio")
    out["campos_form_none"] = PortalSII._campos_form(HTML["of_confirma_folio"], "no_existe")

    # ---- onboarding con un doble del portal ----
    from core import onboarding, negocios
    negocios.software_registrado = lambda rut: None

    class _Portal:
        def __init__(self, emp, prod, cert, sit, asociadas=()):
            self.emp, self.prod, self.cert, self.sit, self.asociadas = emp, prod, cert, sit, list(asociadas)

        def consultar_empresa_autorizada(self, rut, base=None):
            return self.emp

        def datos_software(self, rut, base=None):
            return self.prod if base == BASE_PRODUCCION else self.cert

        def situacion_folios(self, rut, tipos=None):
            return {t: self.sit.get(t, {"bloqueado": False, "puede_timbrar": True}) for t in (tipos or [])}

        def empresas_asociadas(self):
            return self.asociadas

    def sw(nombre, res="0"):
        return {"software": nombre, "resolucion": res, "fecha_resolucion": "", "mail_admin": "",
                "propio": bool(nombre) and nombre.upper() != "SII", "certificado": res not in ("", "0")}

    emp_full = EmpresaAutorizadaDTE("77777777-7", "EMPRESA DEMO SPA", "80", "22-08-2014", "SANTIAGO", [
        DocumentoAutorizado(33, "FACTURA ELECTRONICA", "01-02-2026"), DocumentoAutorizado(39, "BOLETA ELECTRONICA", "05-02-2026"),
        DocumentoAutorizado(61, "NOTA DE CREDITO ELECTRONICA", "01-02-2026", "15-03-2026")])
    emp_exenta = EmpresaAutorizadaDTE("77777777-7", "EMPRESA DEMO SPA", "80", "22-08-2014", "SANTIAGO", [
        DocumentoAutorizado(34, "FACTURA NO AFECTA O EXENTA ELECTRONICA", "01-02-2026"), DocumentoAutorizado(41, "BOLETA EXENTA ELECTRONICA", "05-02-2026")])
    casos = {
        "sin_propio_exenta": _Portal(emp_exenta, sw("SII"), sw(""), {}),
        "externo": _Portal(emp_full, sw("Haulmer Facturación", "500"), sw(""), {}),
        "emitiendo_nuestro": _Portal(emp_full, sw("DTE Chile v2", "500"), sw("DTE Chile v2", "500"), {}),
        "certificando_bloqueada": _Portal(emp_full, sw("SII"), sw("Motor Demo"), {33: {"bloqueado": True, "puede_timbrar": False}}),
        "certificado": _Portal(emp_full, sw("SII"), sw("Motor Demo", "77"), {}),
        "desconocida": _Portal(None, sw(""), sw(""), {61: {"bloqueado": True, "puede_timbrar": False}}),
    }
    out["diagnosticos"] = {k: onboarding.diagnosticar(p, "77777777-7", "Motor Demo").to_dict() for k, p in casos.items()}
    cartera = _Portal(emp_full, sw("SII"), sw(""), {}, asociadas=[{"rut": "77777777-7", "razon_social": "EMPRESA DEMO SPA"}, {"rut": "76111111-6", "razon_social": "CLIENTE"}])
    out["cartera"] = [d.to_dict() for d in onboarding.diagnosticar_cartera(cartera, nombre_sistema="Motor Demo")]
    out["clasificar"] = {
        "externo_registrado": list(onboarding.clasificar_software(sw("Otro Soft", "9"), sw(""), "Mi Registro")),
        "nuestro_registrado": list(onboarding.clasificar_software(sw("mi registro pro", "9"), sw(""), "Mi Registro")),
        "propio_sin_config": list(onboarding.clasificar_software(sw("X", "9"), sw(""), None)),
    }
    (AQUI / "html.json").write_text(json.dumps(HTML, ensure_ascii=False, indent=1), encoding="utf-8")
    (AQUI / "esperado.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print("escrito esperado.json con", len(out), "bloques")


if __name__ == "__main__":
    main()
