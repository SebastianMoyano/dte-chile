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
    rut_usuario: str = Field(description="RUT (con DV) de quien entra al SII; debe estar autorizado para la empresa")
    rut_empresa: str = Field(description="RUT (con DV) de la empresa a operar")
    clave_tributaria: str = Field(description="Clave tributaria del usuario. No se guarda.")


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
async def diagnostico(d: DiagnosticoIn) -> dict:
    """Login + selección de empresa + lectura del form y del menú. **Producción**, sin
    efecto: no gasta folio. Errores de dominio (`AutenticacionError`, `SIIRechazoError`)
    salen por el manejador global con su código."""
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
async def importar(d: ImportarIn) -> dict:
    """Lista `mipeAdminDocsEmi` (paginado), registra cada documento en `dtes` con canal
    MIPYME (idempotente por rut/tipo/folio) y baja su PDF a `storage/pdfs/mipyme/<rut>/`.
    **Producción**, solo lectura: no emite ni gasta folio."""
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
async def sincronizar(d: ImportarIn) -> dict:
    """Lo que usa la página: login + empresa + lectura del form (emisor, drift) + historial +
    importación a `dtes` con PDF. **Producción**, solo lectura: no emite ni gasta folio."""
    return await run_in_threadpool(_sincronizar, d)
