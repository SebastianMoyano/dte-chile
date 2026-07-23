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
    if sw_prod.get("propio"):
        estado, etiqueta = "emitiendo", "Emitiendo en producción con software propio"
    elif sw_cert.get("propio") and sw_cert.get("certificado"):
        estado, etiqueta = "certificado", "Software propio certificado — falta activarlo en producción"
    elif sw_cert.get("propio"):
        estado, etiqueta = "certificando", "En certificación del software propio"
    else:
        estado, etiqueta = "sin_propio", "Aún sin software propio registrado"

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
