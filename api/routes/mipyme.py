"""
api/routes/mipyme.py — Canal MIPYME (Sistema de Facturación Gratuito del SII) desde la página.

Tres endpoints, todos de **solo lectura en el SII** (no emiten, no gastan folio), pero dos de
ellos ESCRIBEN en el motor:
  - `/diagnostico`: login + empresa + form + menú. No escribe nada.
  - `/importar`: historial de emitidos → tabla `dtes` (canal MIPYME) + PDF en `storage/pdfs/mipyme/`.
  - `/sincronizar`: lo que usa la página; diagnóstico + importación en una sola sesión.

La clave tributaria viaja en el body, se usa en memoria para esa petición y no se guarda ni se
loguea (L6). Es PRODUCCIÓN: el portal MIPYME no tiene sandbox (L1), por eso el endpoint lo dice
en la respuesta.
"""
from __future__ import annotations

import re

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from core.auth import requerir_autenticacion
from core.sii_mipyme import (ClienteMipyme, TIPO_FACTURA_EXENTA, armar_payload, ItemMipyme,
                             ReceptorMipyme, importar_emitidos)

router = APIRouter(prefix="/api/v1/mipyme", tags=["Canal MIPYME (gratuito del SII)"],
                   dependencies=[Depends(requerir_autenticacion)])


class DiagnosticoIn(BaseModel):
    rut_empresa: str = Field(description="RUT (con DV) de la empresa a operar")
    rut_usuario: str = Field(default="", description="RUT (con DV) de quien entra al SII; debe estar autorizado para la empresa. Vacío = el recordado.")
    clave_tributaria: str = Field(default="", description="Clave tributaria del usuario. Vacía = la recordada en el keystore (si la hay).")
    recordar: bool = Field(default=False, description="Guardar cifradas en el keystore las claves que vienen en esta petición (solo si la persona lo pidió)")


def _resolver_claves(d: "DiagnosticoIn", usuario: dict) -> None:
    """Claves por petición o recordadas: lo que viene en el cuerpo manda; lo que falta se toma
    del keystore (cifrado con la clave maestra). Con `recordar`, lo que vino se guarda. Nada
    de esto se registra en logs ni en evidencias (las evidencias ya tachan claves)."""
    from core import keystore
    from core.errors import ValidacionError
    guardadas = keystore.obtener_claves_sii(usuario["id"], d.rut_empresa)
    if d.recordar and (d.clave_tributaria or getattr(d, "clave_certificado", "") or d.rut_usuario):
        keystore.guardar_claves_sii(usuario["id"], d.rut_empresa, d.rut_usuario or None,
                                    d.clave_tributaria or None, getattr(d, "clave_certificado", "") or None)
    d.rut_usuario = d.rut_usuario or guardadas["rut_usuario"]
    d.clave_tributaria = d.clave_tributaria or guardadas["tributaria"]
    if hasattr(d, "clave_certificado") and not d.clave_certificado:
        d.clave_certificado = guardadas["certificado"]
    if not d.rut_usuario or not d.clave_tributaria:
        raise ValidacionError("Faltan el RUT de la persona autorizada y/o su clave tributaria "
                              "(no vienen en la petición ni están recordadas para esta empresa)",
                              detalle={"rut_empresa": d.rut_empresa, "faltan": [k for k, v in
                                       (("rut_usuario", d.rut_usuario), ("clave_tributaria", d.clave_tributaria)) if not v]})


@router.get("/contexto-siiengine/{rut_empresa}",
            summary="Lo que el SII engine en Go (app/) necesita para operar esta empresa: claves recordadas y rutas")
async def contexto_siiengine(rut_empresa: str, usuario: dict = Depends(requerir_autenticacion)) -> dict:
    """Entrega al cascarón de escritorio las claves del SII **recordadas** (descifradas del
    keystore) y las rutas absolutas de la base y del storage, para que `nucleo/siiengine` corra
    en el proceso de la app sin pasar por este motor. Mismo modelo de confianza que
    `keystore/negocios/{id}/contexto-emision` (que entrega la clave privada del certificado):
    solo localhost, solo con la clave efímera de la app, y nada se persiste del lado Go. Las
    claves que la persona NO marcó como recordadas no están aquí: la app las tiene en memoria."""
    from pathlib import Path
    from core import keystore
    from core.config import settings
    from core.database import DATABASE_PATH
    guardadas = keystore.obtener_claves_sii(usuario["id"], rut_empresa)
    return {"rut_empresa": rut_empresa, "rut_usuario": guardadas["rut_usuario"],
            "clave_tributaria": guardadas["tributaria"], "clave_certificado": guardadas["certificado"],
            "database_path": str(Path(DATABASE_PATH).resolve()),
            "storage_path": str(Path(settings.storage_path).resolve())}


_RECEPTOR_PRUEBA = ReceptorMipyme(rut="11111111-1", razon_social="PRUEBA", giro="PRUEBA",
                                  direccion="-", ciudad="-", comuna="-")


def _diagnosticar(d: DiagnosticoIn) -> dict:
    with ClienteMipyme(d.rut_usuario, d.clave_tributaria, clave_certificado="") as cli:
        cli.iniciar_sesion()
        cli.seleccionar_empresa(d.rut_empresa)
        enlaces = [{"texto": t, "href": h} for t, h in cli.enlaces_menu()]
        menu = cli.resumen_menu()
        campos = cli.leer_form(TIPO_FACTURA_EXENTA)
    # El drift se calcula con un receptor ficticio: armar_payload no toca la red.
    payload = armar_payload(campos, TIPO_FACTURA_EXENTA, _RECEPTOR_PRUEBA, [ItemMipyme("x", 1)])
    boleta = [e for e in enlaces if re.search(r"bolet", e["texto"] + " " + e["href"], re.I)]
    historial = [e for e in enlaces if re.search(r"histor|emitid|consult", e["texto"] + " " + e["href"], re.I)]
    return {
        "ambiente": "produccion",
        "empresa": d.rut_empresa,
        "emisor_segun_portal": {"razon_social": campos.get("EFXP_RZN_SOC", ""),
                                "giro": campos.get("EFXP_GIRO_EMIS", ""),
                                "acteco": campos.get("EFXP_ACTECO", ""),
                                "direccion": campos.get("EFXP_DIR_ORIGEN", ""),
                                "comuna": campos.get("EFXP_CMNA_ORIGEN", "")},
        "ultimo_receptor": {"rut": f'{campos.get("EFXP_RUT_RECEP", "")}-{campos.get("EFXP_DV_RECEP", "")}',
                            "razon_social": campos.get("EFXP_RZN_SOC_RECEP", "")},
        "form": {"campos_en_html": len(campos), "campos_del_schema": len(payload.pares),
                 "campos_nuevos": payload.campos_nuevos},
        "boleta_en_gratuito": bool(boleta),
        "enlaces_boleta": boleta,
        "enlaces_historial": historial,
        "enlaces": enlaces,
        "menu": menu,
        "nota": "Solo lectura: no se emitió nada ni se gastó folio. La sesión se cerró.",
    }


@router.post("/diagnostico", summary="Entrar al portal MIPYME y leer (sin emitir)")
async def diagnostico(d: DiagnosticoIn, usuario: dict = Depends(requerir_autenticacion)) -> dict:
    """Login + selección de empresa + lectura del form y del menú. **Producción**, sin
    efecto: no gasta folio. Errores de dominio (`AutenticacionError`, `SIIRechazoError`)
    salen por el manejador global con su código."""
    _resolver_claves(d, usuario)
    return await run_in_threadpool(_diagnosticar, d)


class ImportarIn(DiagnosticoIn):
    clave_certificado: str = Field(default="", description="Clave del certificado (firma central). Solo si se quiere el XML. No se guarda.")
    con_xml: bool = Field(default=False, description="Bajar también el XML de cada documento (Obtener Envío; exige clave_certificado)")
    desde: str = Field(default="", description="YYYY-MM-DD (opcional)")
    hasta: str = Field(default="", description="YYYY-MM-DD (opcional)")
    con_pdf: bool = Field(default=True, description="Bajar también el PDF de cada documento")


def _importar(d: ImportarIn) -> dict:
    with ClienteMipyme(d.rut_usuario, d.clave_tributaria, clave_certificado=d.clave_certificado) as cli:
        cli.iniciar_sesion()
        cli.seleccionar_empresa(d.rut_empresa)
        docs = cli.listar_emitidos(desde=d.desde, hasta=d.hasta)
        resumen = importar_emitidos(cli, d.rut_empresa, docs, con_pdf=d.con_pdf, con_xml=d.con_xml and bool(d.clave_certificado))
    resumen["ambiente"] = "produccion"
    resumen["nota"] = "Solo lectura en el SII: se listó el historial y se bajaron PDF. Nada se emitió."
    return resumen


@router.post("/importar", summary="Importar el historial de emitidos del gratuito (con PDF)")
async def importar(d: ImportarIn, usuario: dict = Depends(requerir_autenticacion)) -> dict:
    """Lista `mipeAdminDocsEmi` (paginado), registra cada documento en `dtes` con canal
    MIPYME (idempotente por rut/tipo/folio) y baja su PDF a `storage/pdfs/mipyme/<rut>/`.
    **Producción**, solo lectura: no emite ni gasta folio."""
    _resolver_claves(d, usuario)
    return await run_in_threadpool(_importar, d)


def _sincronizar(d: ImportarIn) -> dict:
    with ClienteMipyme(d.rut_usuario, d.clave_tributaria, clave_certificado=d.clave_certificado) as cli:
        cli.iniciar_sesion()
        cli.seleccionar_empresa(d.rut_empresa)
        enlaces = [{"texto": t, "href": h} for t, h in cli.enlaces_menu()]
        menu = cli.resumen_menu()
        campos = cli.leer_form(TIPO_FACTURA_EXENTA)
        docs = cli.listar_emitidos(desde=d.desde, hasta=d.hasta)
        resumen = importar_emitidos(cli, d.rut_empresa, docs, con_pdf=d.con_pdf, con_xml=d.con_xml and bool(d.clave_certificado))
    payload = armar_payload(campos, TIPO_FACTURA_EXENTA, _RECEPTOR_PRUEBA, [ItemMipyme("x", 1)])
    resumen.update({
        "ambiente": "produccion",
        "emisor_segun_portal": {"razon_social": campos.get("EFXP_RZN_SOC", ""),
                                "giro": campos.get("EFXP_GIRO_EMIS", ""),
                                "acteco": campos.get("EFXP_ACTECO", ""),
                                "comuna": campos.get("EFXP_CMNA_ORIGEN", "")},
        "form": {"campos_en_html": len(campos), "campos_del_schema": len(payload.pares),
                 "campos_nuevos": payload.campos_nuevos},
        "enlaces": enlaces, "menu": menu,
        "nota": "Solo lectura en el SII: sesión comprobada, historial listado y PDF descargados. Nada se emitió.",
    })
    return resumen


@router.post("/sincronizar", summary="Entrar al gratuito del SII e importar lo emitido (una sola sesión)")
async def sincronizar(d: ImportarIn, usuario: dict = Depends(requerir_autenticacion)) -> dict:
    """Lo que usa la página: login + empresa + lectura del form (emisor, drift) + historial +
    importación a `dtes` con PDF. **Producción**, solo lectura: no emite ni gasta folio."""
    _resolver_claves(d, usuario)
    return await run_in_threadpool(_sincronizar, d)
