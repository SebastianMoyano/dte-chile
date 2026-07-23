"""
core/postulacion.py — Postulación a certificación ante el SII (boletas y facturas).

Automatiza el paso 1 de la certificación: **postular la empresa y ver / bajar el set de
pruebas**. Ver `docs/CERTIFICACION.md` para el modelo completo.

Dos portales, DOS mecanismos (por eso hay dos backends):

  - **BOLETA** → `www4.sii.cl/certBolElectDteInternet` — es una **app GWT**, NO scriptable con
    httpx. Se maneja con **playwright** (librería). Entra con el CERTIFICADO (sin clave
    tributaria). Al confirmar la empresa, ofrece los sets de boleta disponibles.
  - **FACTURA** → `maullin.sii.cl/cvc_cgi/dte/pe_generar` — es el **cgi viejo**, scriptable con
    httpx (via `PortalSII`). Requiere que la empresa esté "inscrita en Postulación".

## Seguridad (dos frenos, como el resto del proyecto)
  1. **Read-only por defecto**: `consultar_*` solo MIRA (confirma la empresa y enumera los
     documentos que se pueden postular). No inicia nada.
  2. **`postular_*` exige `confirmar=True`**: sin él, es dry-run (reporta qué haría). El clic
     real que inicia la certificación formal ("Bajar Nuevo Set") solo ocurre con confirmación
     explícita. Es un trámite formal ante el SII, no algo que se dispare solo.

playwright es un **import perezoso**: el resto del motor no depende de él. Si no está
instalado, se devuelven las **instrucciones manuales precisas** en vez de fallar.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List

import httpx

from core import keystore
from core.errors import DTEChileError, SIIError, SIIRechazoError
from core.sii_portal import BASE_CERTIFICACION, PortalSII, _UA, _texto

# Logout del SII. **Obligatorio cerrar cada sesión autenticada**: el SII tiene un tope de
# sesiones concurrentes por RUT y, si no se cierran, responde "Usted ha superado el máximo de
# sesiones autenticadas" y NIEGA nuevas auth (cookies vacías) hasta que expiren solas. Cada
# función que autentica debe llamar `_cerrar_sesion` en su `finally`.
_LOGOUT_URL = "https://herculesr.sii.cl/cgi_AUT2000/autTermino.cgi"

URL_BOLETA = "https://www4.sii.cl/certBolElectDteInternet/?SET=1"

INSTRUCCIONES_MANUALES_BOLETA = (
    "Postulación de boletas — pasos manuales (si playwright no está o el portal cambió):\n"
    "  1. Entra a https://www4.sii.cl/certBolElectDteInternet/?SET=1 (con el certificado).\n"
    "  2. Ingresa el RUT de la empresa y 'Confirmar Empresa'.\n"
    "  3. Marca el/los 'SET DE BOLETA ELECTRÓNICA' que quieras certificar.\n"
    "  4. Ingresa el correo del proveedor de software.\n"
    "  5. 'Bajar Nuevo Set' — esto INICIA la certificación y descarga el set de pruebas."
)


@dataclass
class DocPostulable:
    """Un set/documento que el portal ofrece postular ahora mismo."""
    nombre: str                 # ej. "SET DE BOLETA ELECTRÓNICA AFECTA"
    marcable: bool = True       # el checkbox está disponible


@dataclass
class EstadoPostulacion:
    """Resultado de consultar la postulación de una empresa (read-only)."""
    rut: str
    tipo: str                   # "boleta" | "factura"
    razon_social: str = ""
    elegible: bool = False      # ¿puede postular / bajar el set ahora?
    docs: List[DocPostulable] = field(default_factory=list)
    mensaje: str = ""           # lo que dijo el portal
    requiere_correo_proveedor: bool = False

    def resumen(self) -> str:
        docs = ", ".join(d.nombre for d in self.docs) or "(ninguno ofrecido)"
        estado = "ELEGIBLE" if self.elegible else "NO elegible"
        return (f"[{self.tipo}] {self.razon_social or self.rut} → {estado}\n"
                f"  documentos postulables ahora: {docs}\n"
                f"  {self.mensaje}")


# ---------------------------------------------------------------------------
# Sesión: cookies del certificado → storage state de playwright
# ---------------------------------------------------------------------------
def _cookies_sesion(cert_id: int, cuenta_id: int, referencia: str) -> dict:
    """Autentica en el SII con el certificado y devuelve las cookies de sesión.

    Usa `keystore.pem_transitorio` (PEM con permisos 600 + borrado garantizado en `finally`,
    incluso ante error), en vez de escribir los PEM a mano — la clave privada nunca queda
    huérfana en disco (L6). Los PEM ya no se necesitan tras autenticar: playwright/httpx
    operan solo con las cookies.
    """
    with keystore.pem_transitorio(cert_id, cuenta_id) as (cp, kp):
        portal = PortalSII(cert_pem=cp, key_pem=kp, base=BASE_CERTIFICACION)
        cookies = portal.autenticar(referencia=referencia)
        # Sesión vacía = auth no prendió (típicamente rate-limiting del SII tras muchos ciclos
        # seguidos, o token caído). Fallar claro AQUÍ: si no, el portal rebota a la página de
        # login y el flujo timeouterá 30s buscando un campo que nunca aparece (falso síntoma).
        if not cookies:
            raise SIIError(
                "El SII devolvió una sesión vacía (cookies=∅). Suele ser rate-limiting tras "
                "autenticar muchas veces seguidas; reintenta en unos minutos.")
        return cookies


def _storage_state(cookies: dict) -> dict:
    """Cookies de la sesión del SII en el formato storage_state de playwright."""
    return {"cookies": [
        {"name": k, "value": v, "domain": ".sii.cl", "path": "/",
         "secure": True, "httpOnly": False, "sameSite": "Lax"}
        for k, v in cookies.items()], "origins": []}


def _cerrar_sesion(cookies: dict) -> None:
    """Cierra la sesión autenticada del SII (best-effort). Ver `_LOGOUT_URL`: sin esto, las
    sesiones se acumulan y el SII bloquea nuevas auth. Se llama en el `finally` de cada flujo.
    Nunca lanza: cerrar sesión es limpieza, no debe tumbar el resultado del trámite."""
    if not cookies:
        return
    try:
        with httpx.Client(verify=True, timeout=15, follow_redirects=True,
                          cookies=cookies, headers=_UA) as c:
            c.get(_LOGOUT_URL)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# BOLETA — portal GWT, via playwright (librería)
# ---------------------------------------------------------------------------
def _pw():
    """Import perezoso de playwright. Lanza SIIError legible si no está."""
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
        return sync_playwright
    except ImportError as e:
        raise SIIError(
            "playwright no está instalado; no puedo manejar el portal de boletas (GWT).\n"
            "Instala con:  .venv/bin/pip install playwright && .venv/bin/python -m playwright "
            "install chromium\n" + INSTRUCCIONES_MANUALES_BOLETA) from e


def _abrir_portal_boleta(page, rut: str) -> None:
    """Navega, confirma la empresa. Deja la página en el estado con los sets ofrecidos."""
    n, dv = rut.split("-") if "-" in rut else (rut[:-1], rut[-1])
    page.goto(URL_BOLETA, wait_until="networkidle", timeout=45000)
    # El GWT tarda en montar el form; localizar por texto/rol (los refs no persisten).
    page.get_by_role("button", name="Confirmar Empresa").wait_for(timeout=30000)
    inputs = page.get_by_role("textbox")
    inputs.nth(0).fill(n)
    inputs.nth(1).fill(dv)
    page.get_by_role("button", name="Confirmar Empresa").click()
    page.wait_for_timeout(3500)  # el GWT recarga la vista tras confirmar


def consultar_boleta(rut: str, cert_id: int, cuenta_id: int = 1) -> EstadoPostulacion:
    """READ-ONLY: confirma la empresa en el portal de boletas y enumera los sets que ofrece.

    No inicia ninguna certificación. Confirmar la empresa es solo el lookup del portal.
    """
    est = EstadoPostulacion(rut=rut, tipo="boleta")
    cookies = _cookies_sesion(cert_id, cuenta_id, URL_BOLETA)

    sync_playwright = _pw()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(storage_state=_storage_state(cookies))
        page = ctx.new_page()
        try:
            _abrir_portal_boleta(page, rut)
            cuerpo = _texto(page.content())
            est.razon_social = _entre(cuerpo, "La Empresa", "Rut").strip() or ""
            est.mensaje = _entre(cuerpo, "La Empresa", ".").strip()[:200]
            # Enumerar TODOS los sets ofrecidos (checkboxes con su etiqueta).
            for cb in page.get_by_role("checkbox").all():
                etiqueta = _etiqueta_checkbox(page, cb)
                if etiqueta:
                    est.docs.append(DocPostulable(nombre=etiqueta,
                                                  marcable=cb.is_enabled()))
            est.elegible = bool(est.docs) and page.get_by_role(
                "button", name="Bajar Nuevo Set").count() > 0
            est.requiere_correo_proveedor = "Correo electrónico Proveedor" in page.content()
        finally:
            browser.close()
            _cerrar_sesion(cookies)
    return est


def postular_boleta(rut: str, cert_id: int, sets: List[str], email_proveedor: str,
                    cuenta_id: int = 1, confirmar: bool = False) -> dict:
    """Postula boletas: marca los sets, ingresa el correo y baja el set (INICIA la certificación).

    Args:
        sets: nombres de los sets a marcar (deben existir en `consultar_boleta`).
        email_proveedor: correo del proveedor de software (requerido por el portal).
        confirmar: **si es False (default), NO hace clic en "Bajar Nuevo Set"** — devuelve el
            plan (dry-run). Con True ejecuta la postulación real.

    ⚠️ `confirmar=True` inicia un trámite FORMAL ante el SII. No es reversible como un simple
    lookup: descarga el set y registra a la empresa en el proceso de certificación.
    """
    if not sets:
        raise DTEChileError("Debes indicar al menos un set a postular (sets vacío).")

    est = consultar_boleta(rut, cert_id, cuenta_id)
    if not est.elegible:
        raise DTEChileError(f"La empresa {rut} no puede postular boletas ahora: {est.mensaje}")

    disponibles = {d.nombre for d in est.docs}
    faltan = [s for s in sets if s not in disponibles]
    if faltan:
        raise DTEChileError(f"Estos sets no los ofrece el portal: {faltan}. "
                            f"Disponibles: {sorted(disponibles)}")

    if not confirmar:
        return {"dry_run": True, "rut": rut, "razon_social": est.razon_social,
                "sets_a_postular": sets, "email_proveedor": email_proveedor,
                "aviso": "confirmar=True para hacer clic en 'Bajar Nuevo Set' (inicia la "
                         "certificación formal ante el SII).",
                "disponibles": sorted(disponibles)}

    # --- ejecución real (confirmar=True) ---
    cookies = _cookies_sesion(cert_id, cuenta_id, URL_BOLETA)

    sync_playwright = _pw()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(storage_state=_storage_state(cookies),
                                  accept_downloads=True)
        page = ctx.new_page()
        try:
            _abrir_portal_boleta(page, rut)
            for nombre in sets:
                _marcar_set(page, nombre)
            if est.requiere_correo_proveedor:
                _llenar_correo(page, email_proveedor)
            tmp = Path("storage") / "sets_boleta" / f"set_{rut}.download"
            tmp.parent.mkdir(parents=True, exist_ok=True)
            with page.expect_download(timeout=45000) as dl:
                page.get_by_role("button", name="Bajar Nuevo Set").click()
            dl.value.save_as(str(tmp))
            datos = tmp.read_bytes()
            tmp.unlink(missing_ok=True)
            # ⚠️ El portal responde con una DESCARGA aunque falle: capturar una descarga ≠ éxito.
            # El set de BOLETA se entrega como PÁGINA DE INSTRUCCIONES (HTML/texto:
            # "SET DE PRUEBA DE BOLETA ELECTRONICA…"), NO como ZIP (a diferencia de facturas).
            # Aceptar ZIP/XML o esa página; rechazar solo si es un texto de error
            # ("Debe estar habilitado…", etc.).
            texto = datos.decode("ISO-8859-1", "replace")
            es_zip = datos[:2] == b"PK"
            es_xml = datos.lstrip()[:5].lower() == b"<?xml"
            es_set_boleta = "SET DE PRUEBA DE BOLETA" in texto.upper()
            if not (es_zip or es_xml or es_set_boleta):
                raise SIIRechazoError(
                    f"El SII NO entregó el set: {texto.strip()[:300]}",
                    codigo_sii="postulacion_rechazada")
            ext = "zip" if es_zip else ("xml" if es_xml else "html")
            destino = Path("storage") / "sets_boleta" / f"set_{rut}.{ext}"
            destino.write_bytes(datos)
            return {"dry_run": False, "postulado": True, "rut": rut,
                    "sets": sets, "set_descargado": str(destino), "bytes": len(datos),
                    "formato": ext,
                    "mensaje": "Set de pruebas descargado; la empresa quedó en el proceso "
                               "de certificación de boletas."}
        finally:
            browser.close()
            _cerrar_sesion(cookies)


# ---------------------------------------------------------------------------
# INSCRIPCIÓN al ambiente de certificación (habilitación) — SOLO BOLETAS
# ---------------------------------------------------------------------------
# El portal de boletas (certBolElectDteInternet) exige estar "habilitado en ambiente de
# certificación y pruebas" antes de bajar el set. Esa habilitación es la postulación general
# `pe_condiciones` → `pe_ingrut` → `pe_datos_empresa` (cgi viejo, pero el form final necesita
# JS/estado, por eso se maneja con playwright, no httpx).
URL_POSTULACION = "https://maullin.sii.cl/cvc/dte/pe_condiciones.html"

# ⚠️ EL grupo FACTURA del form pe_datos_empresa. Marcar CUALQUIERA de estos convierte a la
# empresa en "facturador electrónico con software de mercado" y, al autorizarse en producción,
# le quita el Portal MiPyme gratuito para facturas (FAQ SII 6568 + blog SuperFactura, ver
# docs/CERTIFICACION.md). Para "solo boletas" NUNCA se marcan — y se VERIFICA que sigan en 0.
_CHK_FACTURA = ["ESFAC", "FACT", "NC", "ND", "SET03", "SET06", "SET11", "SET84", "SET72"]
# Solo los TIPOS de factura, SIN el toggle de grupo `ESFAC`. En el resumen (pe_confirma) el
# `value` del checkbox indica selección ("S"=sí, "N"=no) para los TIPOS, pero el toggle `ESFAC`
# lleva `value="S"` ESTÁTICO aunque el grupo NO esté seleccionado (falso positivo). La
# verificación de "solo boletas" en el resumen mira estos tipos, no el toggle.
_CHK_FACTURA_TIPOS = ["FACT", "NC", "ND", "SET03", "SET06", "SET11", "SET84", "SET72"]
_CHK_BOLETA_AFECTA = ["ESBOL", "BOLELEC"]   # "Para Boleta Electrónica" + "Boleta Afecta"
_CHK_BOLETA_EXENTA = "BOLEXEN"


def inscribir_boletas(rut: str, cert_id: int, usuario_rut: str, razon_social: str,
                      nombre_software: str, correo: str, cuenta_id: int = 1,
                      incluir_exenta: bool = False, url_software: str = "",
                      confirmar: bool = False) -> dict:
    """Inscribe (habilita) la empresa en el ambiente de certificación para **SOLO BOLETAS**.

    Camina `pe_condiciones → pe_ingrut → pe_datos_empresa` y, en la pantalla de tipos de
    documento, marca **únicamente** el grupo boleta (afecta; exenta solo si `incluir_exenta`),
    dejando el grupo FACTURA intacto. Esa es la garantía de "solo boletas" que conserva el
    Portal MiPyme gratuito de facturas.

    `confirmar=False` (default): **dry-run**. Llena el formulario, marca solo boleta, y
    **verifica por DOM que ningún checkbox de factura quedó marcado**, pero NO hace clic en
    "Confirmar Datos" — devuelve el plan. `confirmar=True`: graba la postulación (trámite formal).

    Verifica el resultado (no asume éxito): si tras grabar el SII devuelve un error/validación o
    reaparece el mismo formulario, lo reporta como fallo en vez de cantar victoria.
    """
    n, dv = (rut.split("-") if "-" in rut else (rut[:-1], rut[-1]))
    nu, dvu = (usuario_rut.split("-") if "-" in usuario_rut else (usuario_rut[:-1], usuario_rut[-1]))
    if not nombre_software.strip():
        raise DTEChileError("nombre_software vacío: el SII exige el nombre del software.")
    if not correo.strip():
        raise DTEChileError("correo vacío: el SII exige al menos un correo de contacto.")

    sync_playwright = _pw()
    cookies = _cookies_sesion(cert_id, cuenta_id, URL_POSTULACION)
    alertas: List[str] = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(storage_state=_storage_state(cookies))
        page = ctx.new_page()
        page.on("dialog", lambda d: (alertas.append(d.message), d.accept()))

        def _submit(valor: str) -> None:
            page.locator(f'input[value="{valor}"]').first.click()
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(900)

        try:
            page.goto(URL_POSTULACION, wait_until="networkidle", timeout=45000)
            _submit("Aceptar Condiciones")
            page.locator('input[name="RUT_EMP"]').first.fill(n)
            page.locator('input[name="DV_EMP"]').first.fill(dv)
            _submit("Ingresar")
            _submit("Continuar")   # pe_datos_empresa (confirmación) → pantalla de tipos

            # --- pantalla de tipos de documento: llenar datos + marcar SOLO boleta ---
            if page.locator('input[name="ESBOL"]').count() == 0:
                cuerpo = " ".join(_texto(page.content()).split())
                raise SIIRechazoError(
                    f"No se llegó a la pantalla de tipos de documento. El SII dijo: "
                    f"{cuerpo[:250]}", codigo_sii="postulacion_sin_pantalla_tipos")

            def _fill(name: str, val: str) -> None:
                loc = page.locator(f'input[name="{name}"]')
                if loc.count() and val:
                    loc.first.fill(val)

            _fill("RUT_USU", nu); _fill("DV_USU", dvu)
            _fill("NOM_SW", nombre_software); _fill("URL", url_software)
            _fill("MAIL_SUP", correo); _fill("MAIL_SII", correo); _fill("MAIL_DTE", correo)

            # marcar SOLO boleta (afecta; exenta si se pidió). check() dispara el JS del portal.
            marcar = list(_CHK_BOLETA_AFECTA) + ([_CHK_BOLETA_EXENTA] if incluir_exenta else [])
            for name in marcar:
                loc = page.locator(f'input[name="{name}"]')
                if loc.count():
                    loc.first.check()
            # asegurar exenta DESmarcada si no se pidió
            if not incluir_exenta:
                loc = page.locator(f'input[name="{_CHK_BOLETA_EXENTA}"]')
                if loc.count():
                    loc.first.uncheck()

            # --- VERIFICACIÓN dura: ningún checkbox de factura marcado ---
            estado = page.evaluate("""() => {
                const r = {};
                for (const el of document.querySelectorAll('input[type=checkbox]')) r[el.name] = el.checked;
                return r;
            }""")
            factura_marcadas = [k for k in _CHK_FACTURA if estado.get(k)]
            if factura_marcadas:
                raise SIIRechazoError(
                    f"ABORTADO: quedaron marcados checkboxes de FACTURA {factura_marcadas} — "
                    f"eso costaría el gratuito. No se grabó nada.",
                    codigo_sii="factura_marcada_abortado")
            boleta_ok = estado.get("BOLELEC", False)

            plan = {"rut": rut, "razon_social": razon_social, "software": nombre_software,
                    "usuario": usuario_rut, "correo": correo,
                    "boleta_afecta_marcada": boleta_ok,
                    "boleta_exenta_marcada": estado.get("BOLEXEN", False),
                    "factura_marcadas": factura_marcadas,   # debe ser []
                    "alertas_sii": alertas}

            if not boleta_ok:
                raise SIIRechazoError("No se pudo marcar la Boleta Afecta (BOLELEC); no se graba.",
                                      codigo_sii="boleta_no_marcada")

            # "Confirmar Datos" es NAVEGACIÓN al resumen (pe_confirma), NO el commit. El commit
            # real es el botón "Confirmar Postulación" del resumen — ahí está el gate.
            _submit("Confirmar Datos")
            if page.locator('input[value="Confirmar Postulación"]').count() == 0:
                cuerpo = " ".join(_texto(page.content()).split())
                raise SIIRechazoError(f"No se llegó al resumen de confirmación. SII: {cuerpo[:250]}",
                                      codigo_sii="sin_resumen_confirma")
            # Segundo chequeo de "solo boletas" EN EL RESUMEN: los checkboxes (disabled) llevan
            # value="S" si el tipo quedó seleccionado, "N" si no. Factura debe ser todo "N".
            resumen = page.evaluate("""() => {
                const r = {};
                for (const el of document.querySelectorAll('input[type=checkbox]')) r[el.name] = el.value;
                return r;
            }""")
            factura_resumen = [k for k in _CHK_FACTURA_TIPOS if resumen.get(k) == "S"]
            if factura_resumen:
                raise SIIRechazoError(
                    f"ABORTADO en el resumen: factura seleccionada {factura_resumen}. No se confirma.",
                    codigo_sii="factura_en_resumen")
            plan["resumen_boleta_afecta"] = resumen.get("BOLELEC") == "S"
            plan["resumen_factura"] = factura_resumen   # debe ser []

            if not confirmar:
                plan.update(dry_run=True, aviso="confirmar=True para hacer clic en 'Confirmar "
                            "Postulación' y grabar la postulación (trámite formal ante el SII).")
                return plan

            # --- COMMIT real (confirmar=True): Confirmar Postulación ---
            _submit("Confirmar Postulación")
            cuerpo = " ".join(_texto(page.content()).split())
            # verificar: no reaparece el resumen y no hay error/validación (no asumir éxito)
            reapareció = page.locator('input[value="Confirmar Postulación"]').count() > 0
            hay_error = any(k in cuerpo.lower() for k in
                            ("error", "obligatorio", "debe ingresar", "no válido", "invalido",
                             "no fue posible", "rechaz"))
            if reapareció or hay_error:
                raise SIIRechazoError(
                    f"El SII NO confirmó la postulación (validación/errores). "
                    f"Alertas: {alertas}. Página: {cuerpo[:280]}",
                    codigo_sii="postulacion_no_confirmada")
            plan.update(dry_run=False, grabado=True, url_resultado=page.url,
                        resultado=cuerpo[:400])
            return plan
        finally:
            browser.close()
            _cerrar_sesion(cookies)


# ---------------------------------------------------------------------------
# FACTURA — cgi viejo, via httpx (PortalSII)
# ---------------------------------------------------------------------------
def consultar_factura(rut: str, cert_id: int, cuenta_id: int = 1) -> EstadoPostulacion:
    """READ-ONLY: consulta la postulación de FACTURA (portal cgi, httpx).

    ⚠️ Muchas empresas ya autorizadas a facturas en PRODUCCIÓN **no necesitan** certificar
    facturas (cambiar de software no obliga a re-certificar tipos ya autorizados). Este
    método solo reporta el estado de la postulación en CERTIFICACIÓN.
    """
    est = EstadoPostulacion(rut=rut, tipo="factura")
    n, dv = rut.split("-") if "-" in rut else (rut[:-1], rut[-1])
    with keystore.pem_transitorio(cert_id, cuenta_id) as (cp, kp):
        portal = PortalSII(cert_pem=cp, key_pem=kp, base=BASE_CERTIFICACION)
        portal.autenticar()
        with portal._cli() as cli:
            cli.get(f"{portal.base}/pe_generar")
            r = cli.post(f"{portal.base}/pe_generar1",
                         data={"RUT_EMP": n, "DV_EMP": dv, "CODIGO": "2",
                               "ACEPTAR": "Confirmar Empresa"})
    import html as _html
    t = " ".join(_html.unescape(_texto(r.text)).split())
    # El cgi antepone CSS del bloque mostrar(); quedarse con la frase útil.
    frase = _entre(t, "Set de Pruebas.", "") or _entre(t, "SET DE PRUEBAS", "")
    est.mensaje = frase.strip()[:200] or t[-200:]
    est.elegible = "no ha sido posible" not in t.lower()
    # El cgi de factura ofrece el set completo (los tipos del set básico) al inscrito.
    if est.elegible:
        est.docs.append(DocPostulable(nombre="SET DE FACTURA ELECTRÓNICA (set básico)"))
    return est


# ---------------------------------------------------------------------------
# Interfaz común
# ---------------------------------------------------------------------------
def consultar_docs(rut: str, cert_id: int, tipo: str = "boleta",
                   cuenta_id: int = 1) -> EstadoPostulacion:
    """Muestra TODOS los documentos que la empresa puede postular ahora (read-only).

    `tipo`: "boleta" (portal GWT) o "factura" (portal cgi).
    """
    if tipo == "boleta":
        return consultar_boleta(rut, cert_id, cuenta_id)
    if tipo == "factura":
        return consultar_factura(rut, cert_id, cuenta_id)
    raise DTEChileError(f"tipo desconocido: {tipo!r} (usar 'boleta' o 'factura')")


# ---------------------------------------------------------------------------
# helpers de parseo del portal GWT
# ---------------------------------------------------------------------------
def _entre(texto: str, ini: str, fin: str) -> str:
    a = texto.find(ini)
    if a < 0:
        return ""
    a += len(ini)
    b = texto.find(fin, a)
    return texto[a:b] if b > a else texto[a:a + 120]


def _etiqueta_checkbox(page, cb) -> str:
    """Texto asociado a un checkbox (la fila que lo contiene, en el GWT del SII)."""
    try:
        fila = cb.locator("xpath=ancestor::tr[1]")
        txt = " ".join(fila.inner_text().split())
        return txt.strip()
    except Exception:
        return ""


def _marcar_set(page, nombre: str) -> None:
    fila = page.get_by_role("row").filter(has_text=nombre)
    fila.get_by_role("checkbox").check()


def _llenar_correo(page, email: str) -> None:
    """Llena el campo de correo del proveedor, ubicándolo por su FILA (no por posición).

    Antes usaba `textbox.last`, que llenaría el campo equivocado en silencio si el GWT
    renderizara otro textbox. Se localiza el textbox dentro de la fila que contiene la
    etiqueta "Correo electrónico"; si no aparece, se falla en vez de adivinar.
    """
    fila = page.get_by_role("row").filter(has_text="Correo electrónico")
    caja = fila.get_by_role("textbox")
    if caja.count() == 0:
        raise SIIError("No encontré el campo 'Correo electrónico Proveedor' en el portal "
                       "(¿cambió la UI?). " + INSTRUCCIONES_MANUALES_BOLETA)
    caja.first.fill(email)
