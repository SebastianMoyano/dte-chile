"""
core/sii_portal.py

Cliente del PORTAL web del SII (`cvc_cgi/dte`) para operaciones de timbraje/folios
que NO están expuestas como web service SOAP y requieren scraping autenticado por
**certificado digital (mutual-TLS)**. Complementa `core/sii.py` (web services SOAP:
envío de DTE, consulta de estado, semilla→token).

Diseñado para ser la base de la REST API / MCP server del proyecto: cada método
mapea una acción común del SII a una llamada programática simple.

Operaciones mapeadas y verificadas contra Maullín (certificación):
- `autenticar()`            — login por cert (mutual-TLS a CAutInicio.cgi) → cookies de sesión.
- `consultar_timbrajes()`  — historial de rangos de folios autorizados por tipo.
- `listar_anulables()`     — rangos que el portal ofrece anular (por tipo).
- `anular_folios()`        — anula un rango de folios NO recepcionados (baja el "stock disponible").
- `situacion_folios()`     — resumen de folios ofrecidos/bloqueo por tipo (via of_confirma_folio).
- `solicitar_folios()`     — solicita, genera y descarga el CAF de un tipo (obtiene los folios).

TODO por **httpx puro** (sin navegador). El único paso que parecía exigir JS
(`of_genera_folio`) se resolvió capturando la request real del navegador: bastaba
agregar `CON_CREDITO=0`/`CON_AJUSTE=0` (que el navegador añade y el form del confirma
no expone) y usar el timestamp HORA/MINUTO fresco que entrega `of_confirma_folio`.
Playwright se usó SOLO como herramienta de investigación para descubrir eso.

NOTA sobre autenticación: el SII autentica por mutual-TLS contra
`herculesr.sii.cl/cgi_AUT2000/CAutInicio.cgi` (sirve tanto para producción como
certificación; el `referencia` define a dónde vuelve). Se requiere el certificado
del contribuyente/mandatario en PEM (cert + key). Sólo se puede anular folios
timbrados por el MANDATARIO de la sesión.
"""

import re
from dataclasses import dataclass
from typing import List, Optional

import httpx

from core.reintentos import ClienteReintentos

_UA = {"User-Agent": "Mozilla/5.0 (compatible; DTE-Portal/1.0)"}
_AUTH_URL = "https://herculesr.sii.cl/cgi_AUT2000/CAutInicio.cgi"

# Bases del portal DTE por ambiente.
BASE_CERTIFICACION = "https://maullin.sii.cl/cvc_cgi/dte"
BASE_PRODUCCION = "https://palena.sii.cl/cvc_cgi/dte"


def _texto(html: str) -> str:
    """HTML → texto plano colapsado (para buscar mensajes)."""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


@dataclass
class RangoFolios:
    """Un rango de folios autorizado (timbraje) para un tipo de documento."""
    tipo_dte: int
    folio_desde: int
    folio_hasta: int
    cantidad: int
    dia: str
    mes: str
    ano: str
    mandatario: str = ""

    @property
    def fecha(self) -> str:
        return f"{self.dia}-{self.mes}-{self.ano}"


@dataclass
class ResultadoAnulacion:
    ok: bool
    mensaje: str
    folio_desde: int
    folio_hasta: int


@dataclass
class DocumentoAutorizado:
    """Un tipo de DTE que un contribuyente está autorizado a emitir."""
    codigo: int
    descripcion: str
    autorizado_desde: str          # AAAA-MM-DD o DD-MM-AAAA según entrega el SII
    desautorizado_desde: str = ""  # vacío si sigue autorizado


@dataclass
class EmpresaAutorizadaDTE:
    """Resumen de autorización DTE de un contribuyente (consulta pública SII)."""
    rut: str
    razon_social: str
    nro_resolucion: str
    fecha_resolucion: str
    direccion_regional: str
    documentos: List[DocumentoAutorizado]

    def autoriza(self, tipo_dte: int) -> bool:
        """True si el contribuyente está autorizado (y no desautorizado) para el tipo."""
        for d in self.documentos:
            if d.codigo == tipo_dte:
                return not d.desautorizado_desde
        return False


class PortalSII:
    """Cliente scraping del portal de timbraje del SII, autenticado por certificado."""

    def __init__(self, cert_pem: Optional[str] = None, key_pem: Optional[str] = None,
                 base: str = BASE_CERTIFICACION, max_folios_por_tipo: int = 3):
        """
        Args:
            cert_pem: ruta al certificado del contribuyente/mandatario en PEM (para
                `autenticar()` por certificado). Opcional si sólo se usa clave.
            key_pem: ruta a la clave privada en PEM.
            base: base del portal (BASE_CERTIFICACION o BASE_PRODUCCION).
            max_folios_por_tipo: tope BLANDO de solicitudes de folios por (rut, tipo) en
                esta sesión, para no gatillar el anti-acaparamiento del SII. El SII
                bloquea el timbraje si acumulas folios sin usar; este guardrail evita
                pedir de más. Súbelo sólo si sabes lo que haces.
        """
        self._cert_pem = cert_pem
        self._key_pem = key_pem
        self._ssl = (httpx.create_ssl_context(cert=(cert_pem, key_pem), verify=True)
                     if cert_pem and key_pem else None)
        self.base = base
        self.max_folios_por_tipo = max_folios_por_tipo
        self.cookies: Optional[dict] = None
        self.rut_sesion: Optional[str] = None
        self._solicitudes: dict = {}  # (rut, tipo) -> nº de folios solicitados en la sesión

    # ------------------------------------------------------------------ auth
    def autenticar(self, referencia: Optional[str] = None) -> dict:
        """Login por **certificado digital** (mutual-TLS a CAutInicio.cgi). Cachea y
        retorna las cookies de sesión. Da acceso al portal DTE (folios, etc.)."""
        if self._ssl is None:
            raise ValueError("Se requiere certificado (cert_pem/key_pem) para autenticar por firma. "
                             "Usa autenticar_con_clave() si sólo tienes RUT+clave.")
        ref = referencia or f"{self.base}/of_solicita_folios"
        with ClienteReintentos(verify=self._ssl, timeout=40, follow_redirects=True, headers=_UA) as c:
            c.post(_AUTH_URL, data={"referencia": ref})
            self.cookies = {k: v for k, v in c.cookies.items()}
        self.rut_sesion = self.cookies.get("RUT_NS")
        return self.cookies

    def autenticar_con_clave(self, rut: str, clave: str, referencia: Optional[str] = None) -> dict:
        """Login por **RUT + clave tributaria** (Mi SII). Cachea y retorna las cookies.

        El mismo backend (`CAutInicio.cgi`) autentica por cert o por clave; el form de
        clave (`IngresoRutClave.html`) postea `rutcntr`(RUT completo)+`clave` con
        `rut/dv/referencia/411` de apoyo. Da acceso a Mi SII (situación tributaria, RCV,
        formularios), que la sesión por certificado NO cubre. NO requiere el .pem.

        Args:
            rut: RUT completo del usuario (p.ej. "12345678-9").
            clave: clave tributaria del SII.
        """
        rut = rut.replace(".", "")
        n, dv = rut.split("-")
        ref = referencia or "https://misiir.sii.cl/cgi_misii/siihome.cgi"
        with ClienteReintentos(verify=True, timeout=40, follow_redirects=True, headers=_UA) as c:
            c.post("https://zeusr.sii.cl/cgi_AUT2000/CAutInicio.cgi",
                   data={"rut": n, "dv": dv, "rutcntr": rut, "clave": clave,
                         "referencia": ref, "411": ""})
            self.cookies = {k: v for k, v in c.cookies.items()}
        self.rut_sesion = self.cookies.get("RUT_NS") or n
        return self.cookies

    def _cli(self) -> httpx.Client:
        if not self.cookies:
            self.autenticar()
        return ClienteReintentos(verify=True, timeout=30, follow_redirects=True,
                            cookies=self.cookies, headers=_UA)

    @staticmethod
    def _split_rut(rut: str):
        rut = rut.replace(".", "")
        n, dv = rut.split("-")
        return n, dv

    # ------------------------------------------------------- consulta timbrajes
    def consultar_timbrajes(self, rut_emisor: str, tipo_dte: int) -> List[RangoFolios]:
        """Historial de rangos de folios autorizados para un tipo (of_consulta2_folio)."""
        n, dv = self._split_rut(rut_emisor)
        with self._cli() as c:
            t = c.post(f"{self.base}/of_consulta2_folio",
                       data={"RUT_EMP": n, "DV_EMP": dv, "PAGINA": "1",
                             "COD_DOCTO": str(tipo_dte), "ACEPTAR": "Consultar"}).text
        p = _texto(t)
        rangos = []
        for m in re.finditer(r"(\d{2})-(\d{2})-(\d{4})\s+(\d+)\s+(\d+)\s+(\d+)\s+([A-ZÑÁÉÍÓÚ ]+?)(?=\d{2}-\d{2}-\d{4}|Anterior|Siguiente|$)", p):
            dia, mes, ano, cant, desde, hasta, mand = m.groups()
            rangos.append(RangoFolios(tipo_dte, int(desde), int(hasta), int(cant),
                                      dia, mes, ano, mand.strip()))
        # dedup por (desde,hasta)
        vistos, out = set(), []
        for r in rangos:
            k = (r.folio_desde, r.folio_hasta)
            if k not in vistos:
                vistos.add(k); out.append(r)
        return sorted(out, key=lambda r: r.folio_desde)

    # ------------------------------------------- autorización DTE de un contribuyente
    def consultar_empresa_autorizada(self, rut_emisor: str,
                                     base: Optional[str] = None) -> Optional[EmpresaAutorizadaDTE]:
        """Consulta qué DTE está autorizado a emitir un contribuyente (`ee_empresa_rut`).

        **Pública**: no requiere certificado ni sesión. Útil para validar emisores/
        receptores. `base` = maullin (certificación) o palena (producción); por defecto
        `self.base`. Devuelve `EmpresaAutorizadaDTE` o None si el RUT no está autorizado.
        """
        import html as _html
        base = base or self.base
        n, dv = self._split_rut(rut_emisor)
        with ClienteReintentos(verify=True, timeout=25, follow_redirects=True, headers=_UA) as c:
            t = c.post(f"{base}/ee_empresa_rut",
                       data={"CNSLT": "R", "RUT_EMP": n, "DV_EMP": dv, "ACEPTAR": "Consultar"}).text
        p = _html.unescape(_texto(t))
        if "autorizada la emisi" not in p.lower():
            return None

        def _campo(rotulo, sig):
            m = re.search(rotulo + r"\s+(.+?)\s+" + sig, p)
            return m.group(1).strip() if m else ""

        razon = _campo("Nombres", r"N°|Nro|Resoluci")
        nrores = _campo(r"N°?\s*Resoluci[oó]n", r"Fecha")
        fchres = _campo(r"Fecha\s+Resoluci[oó]n", r"Direcci")
        dirreg = _campo(r"Direcci[oó]n\s+Regional", r"El contribuyente|autorizada")

        docs = []
        seg = p[p.lower().find("siguientes documentos"):]
        for m in re.finditer(r"\b(\d{2,3})\s+([A-ZÑ][A-ZÑ0-9 ./'\"]+?)\s+(\d{2}-\d{2}-\d{4})\s*(\d{2}-\d{2}-\d{4})?", seg):
            cod, desc, aut, desaut = m.groups()
            docs.append(DocumentoAutorizado(int(cod), desc.strip(), aut, desaut or ""))
        return EmpresaAutorizadaDTE(f"{n}-{dv}", razon, nrores, fchres, dirreg, docs)

    # ------------------------------------------------- software / modalidad emisión
    def datos_software(self, rut_emisor: str, base: Optional[str] = None) -> dict:
        """Lee el software de emisión registrado y el estado de resolución del
        contribuyente (`ad_empresa2`). Requiere sesión autenticada.

        Devuelve `{software, resolucion, fecha_resolucion, mail_admin, propio,
        certificado}`. `resolucion=="0"` ⇒ certificación del software SIN finalizar.
        `software=="SII"` ⇒ usa el sistema gratuito del SII (centralizado).

        `base` permite consultar otro ambiente con la misma sesión (cookies .sii.cl
        sirven en maullin y palena).
        """
        import html as _html
        base = base or self.base
        n, dv = self._split_rut(rut_emisor)
        with self._cli() as c:
            t = c.post(f"{base}/ad_empresa2", data={"RUT_EMP": n, "DV_EMP": dv}).text

        def val(label):
            m = re.search(r"<font[^>]*>\s*" + label +
                          r"[^<]*</font>\s*</td>\s*<td[^>]*>\s*<font[^>]*>\s*(?:&nbsp;)?\s*([^<]*?)\s*</font>",
                          t, re.I)
            return _html.unescape(m.group(1).strip()) if m else ""

        _res = r"Resoluci(?:&oacute;|[oó])n"  # el HTML trae la ó como entidad
        software = val(r"Nombre del Software \(\*\)")
        resol = val(_res)
        return {
            "software": software,
            "resolucion": resol,
            "fecha_resolucion": val(r"Fecha " + _res),
            "mail_admin": val(r"Mail Contacto"),
            "propio": bool(software) and software.upper() != "SII",   # SII = sistema gratuito
            "certificado": resol not in ("", "0"),                      # 0 = certificación sin finalizar
        }

    # ------------------------------------------- empresas asociadas al certificado
    def empresas_asociadas(self) -> List[dict]:
        """Lista TODAS las empresas que el titular de la sesión (dueño del certificado)
        puede operar — enumeración REAL de asociaciones vía el portal MIPYME
        (`mipeSelEmpresa.cgi`). Devuelve `[{rut, razon_social}]`.

        Requiere sesión autenticada (`autenticar()` por cert). Es exactamente el
        selector "Seleccione Empresa" del SII: incluye al propio titular y todas las
        empresas donde está asociado como representante / usuario autorizado.
        """
        with self._cli() as c:
            t = c.get("https://www1.sii.cl/cgi-bin/Portal001/mipeSelEmpresa.cgi").text
        empresas = []
        for val, txt in re.findall(r'<option[^>]*value="?([\dkK.\-]+)"?[^>]*>([^<]+)', t, re.I):
            rut = val.strip()
            if not re.match(r"\d{7,8}-[\dkK]$", rut):
                continue
            razon = re.sub(r"[\s,]*\d[\d.\-kK]*\s*$", "", txt).strip().rstrip(",").strip()
            empresas.append({"rut": rut, "razon_social": razon})
        return empresas

    # ------------------------------------------------------- rangos anulables
    def listar_anulables(self, rut_emisor: str, tipo_dte: int) -> List[RangoFolios]:
        """Rangos que el portal ofrece anular (af_anular2). OJO: es optimista — el
        rango puede contener folios recepcionados; la anulación real (af_anular)
        rechaza si ≥1 folio fue recepcionado."""
        n, dv = self._split_rut(rut_emisor)
        with self._cli() as c:
            t = c.post(f"{self.base}/af_anular2",
                       data={"RUT_EMP": n, "DV_EMP": dv, "PAGINA": "1",
                             "COD_DOCTO": str(tipo_dte), "ACEPTAR": "Consultar"}).text
        rangos = []
        for f in re.findall(r"<form\b.*?</form>", t, re.I | re.S):
            d = {mm.group(1): mm.group(2) for mm in
                 re.finditer(r'<input[^>]*name=["\']?(\w+)["\']?[^>]*?value=["\']?([^"\'>]*)', f, re.I)}
            if "FOLIO_INI" in d and "FOLIO_FIN" in d:
                rangos.append(RangoFolios(tipo_dte, int(d["FOLIO_INI"]), int(d["FOLIO_FIN"]),
                                          int(d.get("CANT_DOCTOS", 0)), d.get("DIA", ""),
                                          d.get("MES", ""), d.get("ANO", "")))
        return sorted(rangos, key=lambda r: r.folio_desde)

    # --------------------------------------------------------------- anular
    def anular_folios(self, rut_emisor: str, tipo_dte: int, folio_desde: int,
                      folio_hasta: int, motivo: str = "Folios no utilizados") -> ResultadoAnulacion:
        """Anula el sub-rango [folio_desde, folio_hasta]. Requiere que TODOS estén
        NO recepcionados (si alguno fue recepcionado, el SII rechaza la transacción).
        La sesión debe ser del MANDATARIO que timbró el rango."""
        n, dv = self._split_rut(rut_emisor)
        # localizar el rango padre (para DIA/MES/ANO) que contiene el sub-rango
        padre = None
        for r in self.listar_anulables(rut_emisor, tipo_dte):
            if r.folio_desde <= folio_desde and folio_hasta <= r.folio_hasta:
                padre = r; break
        if padre is None:
            return ResultadoAnulacion(False, "No hay rango anulable que contenga esos folios",
                                      folio_desde, folio_hasta)
        with self._cli() as c:
            # paso confirmación (registra el rango en la sesión)
            c.post(f"{self.base}/af_anular3",
                   data={"RUT_EMP": n, "DV_EMP": dv, "DIA": padre.dia, "MES": padre.mes,
                         "ANO": padre.ano, "COD_DOCTO": str(tipo_dte),
                         "FOLIO_INI": str(padre.folio_desde), "FOLIO_FIN": str(padre.folio_hasta),
                         "CANT_DOCTOS": str(padre.cantidad)})
            # paso final (ejecuta la anulación del sub-rango)
            r = c.post(f"{self.base}/af_anular",
                       data={"FOLIO_INI_A": str(folio_desde), "FOLIO_FIN_A": str(folio_hasta),
                             "MOTIVO": motivo, "RUT_EMP": n, "DV_EMP": dv,
                             "COD_DOCTO": str(tipo_dte), "FOLIO_INI": str(padre.folio_desde),
                             "FOLIO_FIN": str(padre.folio_hasta)})
        p = _texto(r.text).lower()
        if "ha autorizado la anulaci" in p:
            return ResultadoAnulacion(True, "Anulación autorizada por el SII", folio_desde, folio_hasta)
        if "recepcionado" in p:
            return ResultadoAnulacion(False, "Al menos un folio fue recepcionado (no anulable)", folio_desde, folio_hasta)
        if "anulado anteriormente" in p:
            return ResultadoAnulacion(False, "El rango ya fue anulado anteriormente", folio_desde, folio_hasta)
        return ResultadoAnulacion(False, "Respuesta no reconocida del SII", folio_desde, folio_hasta)

    # ----------------------------------------------------- situación de folios
    def situacion_folios(self, rut_emisor: str, tipos: Optional[List[int]] = None) -> dict:
        """Para cada tipo, indica si el timbraje está bloqueado y qué folio se ofrece.
        Usa el paso de PROCESAMIENTO real (of_solicita_folios_dcto con COD_DOCTO), que
        es donde el SII aplica el control de stock (of_confirma_folio es preview y
        engaña)."""
        tipos = tipos or [33, 34, 39, 41, 43, 46, 52, 56, 61]
        n, dv = self._split_rut(rut_emisor)
        out = {}
        with self._cli() as c:
            for tp in tipos:
                t = c.post(f"{self.base}/of_solicita_folios_dcto",
                           data={"RUT_EMP": n, "DV_EMP": dv, "COD_DOCTO": str(tp),
                                 "FOLIO_INICIAL": "", "CANT_DOCTOS": ""}).text
                bloqueado = "NO SE AUTORIZA" in _texto(t).upper()
                out[tp] = {"bloqueado": bloqueado, "puede_timbrar": not bloqueado}
        return out

    # ------------------------------------------------------- solicitar/generar CAF
    def solicitar_folios(self, rut_emisor: str, tipo_dte: int, cantidad: int = 1,
                         verificar_bloqueo: bool = True, forzar: bool = False):
        """Solicita, genera y descarga folios (CAF) para un tipo — **100% httpx, sin
        navegador**.

        Devuelve `(caf_bytes, info)`. `caf_bytes` es None (con la razón en `info`) si:
        `info["rate_limited"]` (tope de la sesión, guardrail cliente), `info["bloqueado"]`
        (el SII ya bloquea el timbraje por anti-acaparamiento), o `info["error"]`.

        GUARDRAILS anti-abuso (para no gatillar el bloqueo del SII):
          - Tope BLANDO `max_folios_por_tipo` de folios por (rut, tipo) por sesión.
            `forzar=True` lo salta.
          - `verificar_bloqueo=True` chequea `situacion_folios` ANTES de generar; si ya
            está bloqueado, no toca `of_genera_folio` (que escala la advertencia del SII).

        Flujo del portal (todo por httpx):
          1. `of_confirma_folio` → entrega el form `of_genera_folio` con el folio
             asignado y el timestamp del servidor (HORA/MINUTO frescos).
          2. `of_genera_folio` → valida el stock (aquí se aplica el anti-acaparamiento)
             y crea el folio. **Requiere agregar `CON_CREDITO=0` y `CON_AJUSTE=0`**, que
             el navegador añade y el form del confirma NO expone (descubierto capturando
             la request real del navegador; sin esos campos el SII devuelve página vacía).
          3. `of_genera_archivo` → descarga el CAF XML.
        """
        clave = (rut_emisor, tipo_dte)
        ya = self._solicitudes.get(clave, 0)
        if not forzar and ya + cantidad > self.max_folios_por_tipo:
            return None, {"rate_limited": True, "solicitados_en_sesion": ya,
                          "max": self.max_folios_por_tipo,
                          "mensaje": f"Tope de {self.max_folios_por_tipo} folios T{tipo_dte}/sesión alcanzado. "
                          "El SII bloquea el timbraje si acumulas folios sin usar: emítelos o anúlalos antes "
                          "de pedir más (o usa forzar=True bajo tu responsabilidad)."}
        if verificar_bloqueo:
            sit = self.situacion_folios(rut_emisor, [tipo_dte])
            if sit.get(tipo_dte, {}).get("bloqueado"):
                return None, {"bloqueado": True,
                              "mensaje": f"El SII ya bloquea el timbraje T{tipo_dte} (anti-acaparamiento). "
                              "Emite o anula folios sin usar de ese tipo antes de reintentar."}
        n, dv = self._split_rut(rut_emisor)
        with self._cli() as c:
            conf = c.post(f"{self.base}/of_confirma_folio", data={
                "RUT_EMP": n, "DV_EMP": dv, "COD_DOCTO": str(tipo_dte), "CANT_DOCTOS": str(cantidad),
                "FOLIO_INICIAL": "", "AFECTO_IVA": "", "ANOTACION": "", "CON_CREDITO": "",
                "CON_AJUSTE": "", "FACTOR": ""}).text
            campos = self._campos_form(conf, "of_genera_folio")
            # BOLETAS (y a veces facturas) tienen un paso intermedio: `of_confirma_folio`
            # devuelve una página "Confirmar Folio Inicial" (con FOLIO_INICIAL asignado) que
            # postea de nuevo a `of_confirma_folio`. Recién ESE responde el form de generación.
            if not campos or "FOLIO_INI" not in campos:
                inter = self._campos_form(conf, "of_confirma_folio")
                if inter and inter.get("FOLIO_INICIAL") and "Confirmar" in inter.get("ACEPTAR", ""):
                    inter.setdefault("CON_CREDITO", "0")
                    inter.setdefault("CON_AJUSTE", "0")
                    conf = c.post(f"{self.base}/of_confirma_folio", data=inter).text
                    campos = self._campos_form(conf, "of_genera_folio")
            if not campos or "FOLIO_INI" not in campos:
                return None, {"bloqueado": "NO SE AUTORIZA" in _texto(conf).upper(),
                              "error": "of_confirma_folio no ofreció folio"}
            # el navegador agrega estos dos; el form del confirma no los expone.
            campos.setdefault("CON_CREDITO", "0")
            campos.setdefault("CON_AJUSTE", "0")
            gen = c.post(f"{self.base}/of_genera_folio", data=campos).text
            if "NO SE AUTORIZA" in _texto(gen).upper():
                return None, {"bloqueado": True, "folio": campos.get("FOLIO_INI")}
            arch = self._campos_form(gen, "of_genera_archivo")
            if not arch:
                return None, {"error": "of_genera_folio no devolvió el form de descarga",
                              "folio": campos.get("FOLIO_INI")}
            caf = c.post(f"{self.base}/of_genera_archivo", data=arch).content
        self._solicitudes[clave] = ya + cantidad  # registrar para el guardrail
        info = {"bloqueado": False, "folio_desde": int(arch.get("FOLIO_INI", 0)),
                "folio_hasta": int(arch.get("FOLIO_FIN", 0)), "caf_bytes": len(caf)}
        return (caf if b"<CAF" in caf else None), info

    @staticmethod
    def _campos_form(html: str, action_contiene: str) -> Optional[dict]:
        """Extrae `{name: value}` de los <input> del <form> cuyo action contiene el string."""
        m = re.search(rf"<form\b[^>]*{action_contiene}[^>]*>(.*?)</form>", html, re.S | re.I)
        if not m:
            return None
        campos = {}
        for im in re.finditer(r"<input\b([^>]*)>", m.group(1), re.I):
            a = im.group(1)
            nm = re.search(r'name=["\']?(\w+)', a)
            vl = re.search(r'value=["\']?([^"\'>]*)', a)
            if nm:
                campos[nm.group(1)] = vl.group(1) if vl else ""
        return campos
