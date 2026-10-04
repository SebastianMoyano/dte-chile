"""
core/onboarding.py — Diagnóstico automático de una empresa para el onboarding.

Dado un `PortalSII` ya autenticado (con el certificado del contribuyente) y un RUT,
lee TODO lo que el SII expone en modo **solo lectura** y arma un diagnóstico claro:
en qué punto está la empresa y qué pasos faltan para emitir con SU software, cada uno
marcado como automático, con-consentimiento, o que necesita a un humano/al SII.

NO escribe nada en el SII. Es la "investigación automática" del asistente de onboarding.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import List, Optional

from core.sii_portal import BASE_CERTIFICACION, BASE_PRODUCCION, PortalSII

# Modo de ejecución de cada acción del plan.
AUTO = "auto"                   # el sistema lo hace solo
CONSENTIMIENTO = "consentimiento"  # escribe en el SII → pide autorización explícita primero
HUMANO = "humano"              # requiere una gestión con el SII (llamada, espera)


@dataclass
class Chequeo:
    """Un requisito verificado en modo solo-lectura."""
    id: str
    titulo: str
    estado: str      # "ok" | "falta" | "atencion" | "desconocido"
    detalle: str


@dataclass
class Accion:
    """Un paso del plan para llegar a emitir."""
    titulo: str
    detalle: str
    modo: str        # AUTO | CONSENTIMIENTO | HUMANO
    hecho: bool = False
    urgente: bool = False


@dataclass
class Diagnostico:
    rut: str
    razon_social: str
    estado: str          # emitiendo | certificado | certificando | sin_propio
    etiqueta: str
    resumen: str
    listo_para_emitir: bool
    chequeos: List[Chequeo] = field(default_factory=list)
    acciones: List[Accion] = field(default_factory=list)
    notas: List[str] = field(default_factory=list)  # aclaraciones para el usuario

    def to_dict(self) -> dict:
        return asdict(self)


def es_nuestro_software(nombre: str, registrado: Optional[str] = None) -> Optional[bool]:
    """¿El software que el SII muestra es este motor?

    Compara primero con `registrado`: el nombre que el motor mismo usó al postular/inscribir
    a esa empresa (lo guarda `core/postulacion.py` en `negocios.software_registrado`). Si no
    hay, cae a `NOMBRE_SOFTWARE` de la config. `None` = no hay con qué comparar."""
    from core.config import settings
    nuestros = [registrado.strip().lower()] if registrado and registrado.strip() else []
    nuestros += [n.strip().lower() for n in (settings.nombre_software or "").split(",") if n.strip()]
    if not nuestros or not nombre:
        return None
    n = nombre.lower()
    return any(x in n or n in x for x in nuestros)


def clasificar_software(sw_prod: dict, sw_cert: dict, registrado: Optional[str] = None) -> tuple:
    """`(estado, etiqueta)` de cómo emite una empresa hoy, según el registro del SII.

    Estados: `emitiendo` (software propio en producción: este motor, o cualquiera si no hay
    `NOMBRE_SOFTWARE`), `externo` (otro proveedor de facturación en producción), `certificado`,
    `certificando`, `sin_propio` (emite por el gratuito del SII). Un facturador externo se
    detecta por el "Nombre del Software" que el SII muestra en producción.
    """
    sw = (sw_prod.get("software") or "").strip()
    if sw_prod.get("propio"):
        if es_nuestro_software(sw, registrado) is False:
            return "externo", f"Emite con «{sw}» (otro proveedor)"
        return "emitiendo", f"Emite en producción con «{sw}»" if sw else "Emitiendo en producción con software propio"
    if sw_cert.get("propio") and sw_cert.get("certificado"):
        return "certificado", "Software propio certificado — falta activarlo en producción"
    if sw_cert.get("propio"):
        return "certificando", "En certificación del software propio"
    return "sin_propio", "Emite por el gratuito del SII"


def diagnosticar(portal: PortalSII, rut: str, nombre_sistema: str = "tu software propio") -> Diagnostico:
    """Corre la batería de lecturas del SII y arma el diagnóstico + plan.

    Args:
        portal: `PortalSII` YA autenticado (por certificado).
        rut: RUT de la empresa a diagnosticar (con guión).
        nombre_sistema: cómo llamar al software propio en los textos del plan.
    """
    emp = portal.consultar_empresa_autorizada(rut, base=BASE_PRODUCCION)
    sw_prod = portal.datos_software(rut, base=BASE_PRODUCCION)
    sw_cert = portal.datos_software(rut, base=BASE_CERTIFICACION)
    sit_cert = portal.situacion_folios(rut, [33, 61])  # freno típico del set de pruebas

    razon = (emp.razon_social if emp else "") or rut
    autorizados = [d for d in (emp.documentos if emp else []) if not d.desautorizado_desde]
    codigos = {str(d.codigo) for d in autorizados}
    sw_actual = sw_prod.get("software") or "el sistema gratuito del SII"
    folios_bloqueados = [t for t in (33, 61) if sit_cert.get(t, {}).get("bloqueado")]

    # Caso frecuente que confunde: autorizada a Factura Exenta (34) pero NO a Afecta (33),
    # emitiendo por el sistema gratuito. Para software propio/mercado la certificación
    # agrega el 33 (SET BÁSICO). Lo explicamos para que no sorprenda.
    notas: List[str] = []
    exenta_sin_afecta = ("34" in codigos and "33" not in codigos)
    if exenta_sin_afecta and not sw_prod.get("propio"):
        notas.append(
            "Hoy estás autorizada a Factura Exenta (34) pero NO a Factura Afecta (33), "
            "y emites por el sistema gratuito del SII. Eso es válido, pero para pasar a "
            "software propio (o de mercado) la certificación del SET BÁSICO agrega la "
            "Factura Afecta (33). No te obliga a emitir afectas — solo queda habilitada. "
            "Por eso proveedores como Haulmer piden 'factura' aunque solo emitas exenta.")

    # ---- Estado global (misma lógica que el panel de negocios) ----
    try:
        from core import negocios as _neg
        registrado = _neg.software_registrado(rut)
    except Exception:  # noqa: BLE001 — sin tabla de negocios seguimos con la config
        registrado = None
    estado, etiqueta = clasificar_software(sw_prod, sw_cert, registrado)
    if estado == "externo":
        notas.append(
            f"Esta empresa emite hoy con «{sw_actual}», otro proveedor de facturación. Mientras "
            f"siga así, NO emitas facturas con {nombre_sistema}: los folios del CAF los administra "
            "ese proveedor y se chocarían. Para migrar hay que cambiar el software registrado en el "
            "SII y traspasar (o anular) los folios que le queden.")

    # ---- Chequeos (solo lectura) ----
    chequeos = [
        Chequeo("empresa", "Empresa reconocida en el SII",
                "ok" if emp else "desconocido",
                razon if emp else f"El RUT {rut} no aparece en el SII."),
        Chequeo("facturador", "Inscrita como facturadora electrónica",
                "ok" if autorizados else "falta",
                (f"Autorizada a emitir: {', '.join(str(d.codigo) for d in autorizados)}"
                 if autorizados else "No aparece autorizada a emitir DTE todavía.")),
        Chequeo("software", "Software de facturación actual",
                "ok" if sw_prod.get("propio") else "atencion",
                (f"Emite con «{sw_actual}»" +
                 ("" if sw_prod.get("propio") else f" — hay que cambiarlo a {nombre_sistema}."))),
        Chequeo("certificacion", "Certificación del software propio",
                "ok" if sw_cert.get("certificado") else ("atencion" if sw_cert.get("propio") else "falta"),
                ("Certificado" if sw_cert.get("certificado")
                 else "En curso" if sw_cert.get("propio") else "No iniciada")),
        Chequeo("folios", "Folios / timbraje para el set de pruebas",
                "atencion" if folios_bloqueados else "ok",
                ("Bloqueado en: " + ", ".join("Factura(33)" if t == 33 else "NotaCrédito(61)"
                                              for t in folios_bloqueados)
                 if folios_bloqueados else "Sin bloqueos detectados")),
    ]

    # ---- Plan de acciones (con modo de ejecución) ----
    acciones: List[Accion] = []
    if estado == "emitiendo":
        acciones.append(Accion("Todo listo", f"Ya emites en producción con {nombre_sistema}.",
                               AUTO, hecho=True))
    else:
        if not autorizados:
            acciones.append(Accion(
                "Inscribir como facturador electrónico",
                "Declarar ante el SII que la empresa emitirá DTE. Requiere tu autorización "
                "(se hace con tu certificado).", CONSENTIMIENTO))
        if estado == "sin_propio":
            acciones.append(Accion(
                "Registrar tu software en el SII",
                f"Declarar «{nombre_sistema}» como tu software de facturación (Actualización "
                "de datos del contribuyente).", CONSENTIMIENTO))
        if folios_bloqueados:
            acciones.append(Accion(
                "Destrabar folios de prueba", "El timbraje está bloqueado por anti-acaparamiento. "
                "Se gestiona con la Mesa de Ayuda del SII (600 330 3000).", HUMANO, urgente=True))
        acciones.append(Accion(
            "Completar el set de pruebas",
            "Emitir y validar los documentos del set de certificación (el sistema lo hace).",
            AUTO, hecho=(estado in ("certificado",))))
        acciones.append(Accion(
            "Obtener la resolución del SII",
            "Al terminar el set, el SII emite la resolución que autoriza tu software.",
            AUTO, hecho=(estado in ("certificado",))))
        acciones.append(Accion(
            "Activar en producción",
            f"Cambiar el software de facturación de «{sw_actual}» a {nombre_sistema} "
            "(Actualización de datos). Requiere tu autorización.", CONSENTIMIENTO))

    # ---- Modelo de emisión de boletas (aplica también si YA emite) ----
    # No se puede verificar en modo lectura (la app del SII exige RUT+Clave de la
    # EMPRESA, no el certificado) → siempre va como paso HUMANO con instrucción precisa.
    # Sin declarar, el SII asume el Modelo 2 (voucher = boleta): exactamente lo contrario
    # de cómo opera un software emisor propio → ventas contadas doble.
    if "39" in codigos or "41" in codigos:
        acciones.append(Accion(
            "Declarar el modelo de emisión de boletas (si cobras con tarjeta)",
            "Hazlo UNA vez por empresa, con RUT y Clave de la EMPRESA (no la persona) en "
            "www4.sii.cl/actatributointernetui: marca «Siempre emito Boleta… aún cuando "
            "reciba un pago electrónico» (Modelo 1). Ojo: sin declarar, el SII asume que "
            "el voucher de la tarjeta ES tu boleta (Modelo 2) y tus ventas quedarían "
            "contadas doble. Guía paso a paso: docs/MODELO-EMISION.md.", HUMANO))

    resumen = f"{razon}: {etiqueta.lower()}."
    if folios_bloqueados:
        resumen += " Hay folios bloqueados que destrabar."

    return Diagnostico(rut=rut, razon_social=razon, estado=estado, etiqueta=etiqueta,
                       resumen=resumen, listo_para_emitir=(estado == "emitiendo"),
                       chequeos=chequeos, acciones=acciones, notas=notas)


def diagnosticar_con_cert(cert_pem: str, key_pem: str, rut: str,
                          nombre_sistema: str = "tu software propio") -> Diagnostico:
    """Autentica un `PortalSII` con los PEM dados y diagnostica. Para uso directo."""
    portal = PortalSII(cert_pem, key_pem, base=BASE_CERTIFICACION)
    portal.autenticar()
    return diagnosticar(portal, rut, nombre_sistema)


def diagnosticar_cartera(portal: PortalSII, ruts: Optional[List[str]] = None,
                         nombre_sistema: str = "tu software propio") -> List[Diagnostico]:
    """Diagnostica TODAS las empresas de un certificado de una vez (vista de cartera).

    Si `ruts` es None, descubre las empresas asociadas al certificado
    (`empresas_asociadas`). Una empresa que falle no rompe el resto (se omite).
    Reusa la sesión autenticada del `portal` (una sola auth para toda la cartera).
    """
    if ruts is None:
        ruts = [e["rut"] for e in portal.empresas_asociadas()]
    resultados: List[Diagnostico] = []
    for r in ruts:
        try:
            resultados.append(diagnosticar(portal, r, nombre_sistema))
        except Exception:
            continue  # una empresa problemática no debe tumbar la cartera
    return resultados
