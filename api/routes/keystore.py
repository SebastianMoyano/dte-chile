"""
api/routes/keystore.py

Endpoints REST para la gestión de certificados por cuenta (almacén cifrado).
Backend de la "página para subir el certificado y su clave". Una cuenta (usuario
autenticado) puede tener VARIOS certificados. Todo protegido con JWT.

Los .p12 y sus claves se guardan CIFRADOS (core/keystore.py); estos endpoints
nunca devuelven secretos, sólo metadatos.
"""
from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status
from api.util import leer_upload

from core import keystore, negocios
from core.auth import requerir_autenticacion
from core.errors import CertificadoError, RecursoNoEncontrado, SIIError, ValidacionError

router = APIRouter(prefix="/api/v1/keystore", tags=["Certificados (Keystore)"])


@router.post("/certificados", status_code=status.HTTP_201_CREATED)
async def subir_certificado(
    archivo: UploadFile = File(..., description="Certificado .p12 / .pfx"),
    password: str = Form(..., description="Contraseña del certificado"),
    nombre: str = Form(None, description="Nombre descriptivo (opcional)"),
    alias: str = Form(None, description="Alias (opcional)"),
    usuario: dict = Depends(requerir_autenticacion),
) -> dict:
    """Sube y guarda (cifrado) un certificado para la cuenta autenticada.

    Valida el .p12 con la contraseña (rechaza si es incorrecta), extrae RUT y
    vencimiento, y lo almacena cifrado. Devuelve metadatos (sin secretos).
    """
    contenido = await leer_upload(archivo)
    try:
        info = keystore.guardar_certificado(
            usuario["id"], contenido, password, nombre=nombre, alias=alias)
    except Exception as e:
        raise CertificadoError(f"Certificado inválido o contraseña incorrecta: {e}")
    return info


@router.get("/certificados")
async def listar_certificados(usuario: dict = Depends(requerir_autenticacion)) -> list[dict]:
    """Lista los certificados de la cuenta (metadatos, sin secretos)."""
    keystore.init_keystore()
    return keystore.listar_certificados(usuario["id"])


@router.delete("/certificados/{cert_id}")
async def eliminar_certificado(
    cert_id: int, usuario: dict = Depends(requerir_autenticacion),
) -> dict:
    """Elimina un certificado de la cuenta."""
    if not keystore.eliminar_certificado(usuario["id"], cert_id):
        raise RecursoNoEncontrado("Certificado no encontrado")
    return {"eliminado": True, "id": cert_id}


@router.get("/certificados/{cert_id}/empresas")
async def empresas_del_certificado(
    cert_id: int, usuario: dict = Depends(requerir_autenticacion),
) -> list[dict]:
    """DESCUBRE todas las empresas asociadas a un certificado (donde el titular es
    representante / usuario autorizado) — vía el selector de empresas del SII. No hay
    que escribir RUTs: devuelve `[{rut, razon_social}]` listo para agregar."""
    from core.sii_portal import PortalSII
    try:
        with keystore.pem_transitorio(cert_id, usuario["id"]) as (cert_pem, key_pem):
            portal = PortalSII(cert_pem, key_pem)
            portal.autenticar()
            return portal.empresas_asociadas()
    except ValueError as e:
        raise RecursoNoEncontrado(str(e))
    except SIIError:
        raise
    except Exception as e:
        raise SIIError(f"No se pudo consultar el SII: {e}")


# ----------------------------------------------------------------- Negocios
@router.get("/empresa")
async def previsualizar_empresa(
    rut: str = Query(..., description="RUT del negocio, ej: 76111111-6"),
    ambiente: str = Query("certificacion", description="certificacion | produccion"),
    usuario: dict = Depends(requerir_autenticacion),
) -> dict:
    """Auto-relleno: razón social + tipos DTE autorizados de un RUT (consulta pública).
    Para mostrar el negocio ANTES de agregarlo. 404 si el RUT no está autorizado."""
    info = negocios.info_empresa(rut, ambiente)
    if not info:
        raise RecursoNoEncontrado(f"El RUT {rut} no aparece autorizado a emitir DTE.")
    return info


@router.post("/negocios", status_code=status.HTTP_201_CREATED)
async def agregar_negocio(
    rut: str = Form(...),
    cert_id: int = Form(None, description="Certificado que opera el negocio (opcional)"),
    ambiente: str = Form("certificacion"),
    usuario: dict = Depends(requerir_autenticacion),
) -> dict:
    """Agrega un negocio a la cuenta (auto-completa la razón social desde el SII)."""
    try:
        return negocios.agregar_negocio(usuario["id"], rut, cert_id, ambiente)
    except ValueError as e:
        raise ValidacionError(str(e))


@router.get("/negocios")
async def listar_negocios(usuario: dict = Depends(requerir_autenticacion)) -> list[dict]:
    """Lista los negocios de la cuenta."""
    negocios.init_negocios()
    return negocios.listar_negocios(usuario["id"])


# Tipos DTE más usados que se muestran en el panel de timbraje.
_TIPOS_PANEL = {33: "Factura", 34: "Factura exenta", 39: "Boleta",
                52: "Guía despacho", 56: "Nota débito", 61: "Nota crédito"}


def _negocio_o_404(cuenta_id: int, negocio_id: int) -> dict:
    negocios.init_negocios()
    neg = next((n for n in negocios.listar_negocios(cuenta_id) if n["id"] == negocio_id), None)
    if not neg:
        raise RecursoNoEncontrado("Negocio no encontrado")
    if not neg.get("cert_id"):
        raise ValidacionError("El negocio no tiene un certificado asociado")
    return neg


@router.get("/negocios/{negocio_id}/timbraje")
async def timbraje_negocio(
    negocio_id: int, usuario: dict = Depends(requerir_autenticacion),
) -> dict:
    """Panel de timbraje del negocio: por cada tipo de DTE, si está autorizado y si el
    timbraje está habilitado o bloqueado (anti-acaparamiento). Opera con el certificado
    asociado al negocio."""
    from core.sii_portal import BASE_CERTIFICACION, BASE_PRODUCCION, PortalSII
    neg = _negocio_o_404(usuario["id"], negocio_id)
    base = BASE_PRODUCCION if neg.get("ambiente") == "produccion" else BASE_CERTIFICACION
    tipos = list(_TIPOS_PANEL)
    try:
        with keystore.pem_transitorio(neg["cert_id"], usuario["id"]) as (cert_pem, key_pem):
            portal = PortalSII(cert_pem, key_pem, base=base)
            portal.autenticar()
            emp = portal.consultar_empresa_autorizada(neg["rut"])
            sit = portal.situacion_folios(neg["rut"], tipos)
    except Exception as e:
        raise SIIError(f"No se pudo consultar el SII: {e}")
    autorizados = {d.codigo for d in emp.documentos} if emp else set()
    docs = [{"tipo": t, "nombre": _TIPOS_PANEL[t], "autorizado": t in autorizados,
             "bloqueado": bool(sit.get(t, {}).get("bloqueado"))} for t in tipos]
    return {"rut": neg["rut"], "razon_social": neg.get("razon_social"), "documentos": docs}


@router.get("/negocios/{negocio_id}/estado")
async def estado_negocio(
    negocio_id: int, usuario: dict = Depends(requerir_autenticacion),
) -> dict:
    """Estado de habilitación del negocio para facturar con software propio:
    autorización en PRODUCCIÓN (por tipo + fecha), software con que emite hoy, y estado
    de la CERTIFICACIÓN del software propio (Maullín → producción)."""
    from core.sii_portal import BASE_CERTIFICACION, BASE_PRODUCCION, PortalSII
    neg = _negocio_o_404(usuario["id"], negocio_id)
    try:
        with keystore.pem_transitorio(neg["cert_id"], usuario["id"]) as (cert_pem, key_pem):
            portal = PortalSII(cert_pem, key_pem)
            portal.autenticar()
            emp = portal.consultar_empresa_autorizada(neg["rut"], base=BASE_PRODUCCION)
            sw_prod = portal.datos_software(neg["rut"], base=BASE_PRODUCCION)
            sw_cert = portal.datos_software(neg["rut"], base=BASE_CERTIFICACION)
            # ¿folios de factura/NC bloqueados en certificación? (freno del set de pruebas)
            sit_cert = portal.situacion_folios(neg["rut"], [33, 61])
    except Exception as e:
        raise SIIError(f"No se pudo consultar el SII: {e}")

    autorizados = [{"tipo": d.codigo, "nombre": d.descripcion, "desde": d.autorizado_desde}
                   for d in (emp.documentos if emp else [])
                   if not d.desautorizado_desde]

    # Estado de migración a software propio.
    if sw_prod["propio"]:
        estado, etiqueta = "emitiendo", "Emitiendo con software propio en producción"
    elif sw_cert["propio"] and sw_cert["certificado"]:
        estado, etiqueta = "certificado", "Software propio certificado — falta activarlo en producción"
    elif sw_cert["propio"]:
        estado, etiqueta = "certificando", "En certificación del software propio"
    else:
        estado, etiqueta = "sin_propio", "Aún sin software propio registrado"

    # Próximos pasos concretos según el punto de la migración.
    sw_a = sw_prod["software"] or "el sistema del SII"
    sw_b = sw_cert["software"] or "tu software propio"
    pasos = []
    if estado == "emitiendo":
        pasos = [{"titulo": "Todo listo", "detalle": f"Ya emites en producción con {sw_b}. No hay pasos pendientes.", "hecho": True}]
    elif estado == "certificando":
        bloq = [t for t in (33, 61) if sit_cert.get(t, {}).get("bloqueado")]
        if bloq:
            nb = ", ".join("Factura (33)" if t == 33 else "Nota de crédito (61)" for t in bloq)
            pasos.append({"titulo": "Destrabar folios de prueba", "urgente": True,
                          "detalle": f"El timbraje de {nb} está bloqueado en certificación. Pídelo a la Mesa de Ayuda del SII (600 330 3000) para poder emitir los documentos del set de pruebas."})
        pasos.append({"titulo": "Completar el set de pruebas",
                      "detalle": "Emitir y validar los documentos del set de certificación en el ambiente de pruebas."})
        pasos.append({"titulo": "Obtener la resolución del SII",
                      "detalle": f"Al terminar el set, el SII emite la resolución que autoriza a {sw_b} como tu software de emisión."})
        pasos.append({"titulo": "Activar en producción",
                      "detalle": f"Cambiar el software registrado en producción de «{sw_a}» a «{sw_b}» (Actualización de datos del contribuyente)."})
    elif estado == "certificado":
        pasos.append({"titulo": "Activar en producción",
                      "detalle": f"Cambiar el software registrado de «{sw_a}» a «{sw_b}» en el SII (Actualización de datos del contribuyente)."})
        pasos.append({"titulo": "Emitir tu primer documento",
                      "detalle": "Probar la emisión real en producción con tu software propio."})
    else:  # sin_propio
        pasos.append({"titulo": "Registrar tu software",
                      "detalle": "Declarar tu software propio en el SII (Actualización de datos del contribuyente)."})
        pasos.append({"titulo": "Certificar el software",
                      "detalle": "Realizar el set de pruebas en el ambiente de certificación."})

    negocios.guardar_estado(usuario["id"], negocio_id, estado, etiqueta, sw_prod["propio"])
    return {
        "rut": neg["rut"], "razon_social": neg.get("razon_social"),
        "estado": estado, "etiqueta": etiqueta, "pasos": pasos,
        "produccion": {
            "software_actual": sw_prod["software"] or "—",
            "usa_software_propio": sw_prod["propio"],
            "autorizado_a_emitir": autorizados,
        },
        "certificacion": {
            "software": sw_cert["software"] or "—",
            "es_propio": sw_cert["propio"],
            "finalizada": sw_cert["certificado"],
            "fecha": sw_cert["fecha_resolucion"],
        },
    }


@router.delete("/negocios/{negocio_id}")
async def eliminar_negocio(
    negocio_id: int, usuario: dict = Depends(requerir_autenticacion),
) -> dict:
    """Elimina un negocio de la cuenta."""
    if not negocios.eliminar_negocio(usuario["id"], negocio_id):
        raise RecursoNoEncontrado("Negocio no encontrado")
    return {"eliminado": True, "id": negocio_id}


@router.get("/negocios/{negocio_id}/f29")
async def f29_negocio(
    negocio_id: int, periodo: str = Query(..., description="Período tributario YYYYMM"),
    ppm: int = Query(0, description="PPM del período (opcional)"),
    remanente_anterior: int = Query(0, description="Remanente de crédito fiscal del mes anterior (opcional)"),
    usuario: dict = Depends(requerir_autenticacion),
) -> dict:
    """Propuesta de Formulario 29 (IVA mensual) del negocio para un período.

    Baja el RCV (Registro de Compras y Ventas) desde PRODUCCIÓN con la sesión del
    certificado del negocio, agrega los totales y los mapea a los casilleros del F29.
    Es sólo lectura: NO declara nada al SII.
    """
    from core.sii_portal import BASE_PRODUCCION, PortalSII
    from core import rcv as rcv_mod
    neg = _negocio_o_404(usuario["id"], negocio_id)
    rcv_mod.init_rcv_db()
    try:
        with keystore.pem_transitorio(neg["cert_id"], usuario["id"]) as (cert_pem, key_pem):
            portal = PortalSII(cert_pem, key_pem, base=BASE_PRODUCCION)
            portal.autenticar()
            cli = rcv_mod.RegistroCompraVenta(token=portal.cookies.get("TOKEN"))
            sync = cli.sincronizar_periodo(neg["rut"], periodo)
    except Exception as e:
        raise SIIError(f"No se pudo bajar el RCV del SII: {e}")
    desglose = rcv_mod.calcular_desglose_f29(
        neg["rut"], periodo, ppm=ppm, remanente_anterior=remanente_anterior)
    lineas = rcv_mod.mapear_a_f29(desglose)
    return {
        "rut": neg["rut"], "razon_social": neg.get("razon_social"), "periodo": periodo,
        "documentos": sync,
        "sin_datos": (sync.get("compras", 0) + sync.get("ventas", 0)) == 0,
        "ppm": ppm,
        "remanente_anterior": remanente_anterior,
        "total_debitos": desglose.total_debitos,
        "total_creditos": desglose.total_creditos,
        "iva_determinado": desglose.iva_determinado,
        "remanente_siguiente": desglose.remanente_siguiente,
        "total_a_pagar": desglose.total_a_pagar,
        "casilleros": [{"codigo": l.codigo, "glosa": l.glosa, "valor": l.valor} for l in lineas],
    }
