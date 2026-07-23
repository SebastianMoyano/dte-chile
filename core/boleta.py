"""
core/boleta.py — Generación de BOLETAS electrónicas (39 / 41) y su sobre EnvioBOLETA.

La boleta NO es una factura: su estructura (definida en `EnvioBOLETA_v11.xsd`, no en
DTE_v10) difiere en puntos que el SII rechaza si se copian de la factura:
  - `IdDoc` lleva **IndServicio** (obligatorio) y **NO** lleva `FmaPago`.
  - `Emisor` usa **RznSocEmisor / GiroEmisor** (la factura usa RznSoc / GiroEmis).
  - El sobre es **EnvioBOLETA** (no EnvioDTE) y se envía a `BOLUpload`.

El orden de los elementos sale del XSD oficial (`core/xsd/EnvioBOLETA_v11.xsd`); se valida
contra él. Referencia de estructura: LibreDTE.
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from lxml import etree

from core.dte import SII_NAMESPACE, DTEInput, calcular_totales

_XSD_BOLETA = "http://www.sii.cl/SiiDte EnvioBOLETA_v11.xsd"

# IndServicio (valores del XSD oficial, EnvioBOLETA_v11.xsd:141-169): 1 servicios periódicos ·
# 2 servicios periódicos domiciliarios · 3 ventas y servicios (el común) · 4 espectáculo por
# cuenta de terceros. No hay más: cualquier otro valor lo rechaza el esquema.
IND_SERVICIO_DEFECTO = 3


def _txt(parent: etree._Element, tag: str, val) -> etree._Element:
    el = etree.SubElement(parent, tag)
    el.text = str(val)
    return el


def _num(v) -> str:
    """Formatea cantidad/precio: entero si es redondo, si no con decimales."""
    f = float(v)
    return str(int(f)) if f.is_integer() else repr(f)


def generar_documento_boleta(dte_input: DTEInput, ted_xml: str,
                             ind_servicio: Optional[int] = None,
                             razon_referencia: Optional[str] = None,
                             cod_referencia: Optional[str] = None,
                             tpo_doc_ref: Optional[str] = None,
                             folio_ref: Optional[int] = None) -> etree._Element:
    """Genera el `<DTE>` de una boleta (39/41) (sin firmar).

    Referencia al CASO del set (certificación) — **formato MÍNIMO, verificado con set SOK**
    (2026-07-21): solo `<NroLinRef>1</NroLinRef><CodRef>SET</CodRef><RazonRef>CASO-N</RazonRef>`.
    → pasar `cod_referencia="SET"` + `razon_referencia="CASO-N"`.

    ⚠️ **NO usar `TpoDocRef`/`FolioRef`** (siguen soportados por retrocompat, pero son campos de
    FACTURA): por el canal DTEUpload dan `HED-3-211`. El rechazo "El Documento no está en el
    envío" que se persiguió durante días **NO era la referencia — era el CANAL**: el set de
    boletas se envía por **DTEUpload/maullin**, no por el REST de pangal (ver
    `docs/LECCIONES-SII.md`). Con la referencia mínima + DTEUpload + la resolución por-empresa
    correcta, el set quedó SOK.
    Orden del XSD (v4.2) si se usan los opcionales: NroLinRef → TpoDocRef → FolioRef → CodRef → RazonRef.
    """
    totales = calcular_totales(dte_input.items, dte_input.tipo_dte)
    tipo = dte_input.tipo_dte.value

    # Mismo ID/patrón de firma que el orquestador de facturas (probado y aceptado por
    # el SII): Documento ID="T{tipo}F{folio}", se firma con uri="#DTE-{tipo}-{folio}".
    dte = etree.Element("DTE", nsmap={None: SII_NAMESPACE}, attrib={"version": "1.0"})
    doc = etree.SubElement(dte, "Documento", attrib={"ID": f"T{tipo}F{dte_input.folio}"})
    enc = etree.SubElement(doc, "Encabezado")

    # ---- IdDoc (IndServicio obligatorio, SIN FmaPago) ----
    idd = etree.SubElement(enc, "IdDoc")
    _txt(idd, "TipoDTE", tipo)
    _txt(idd, "Folio", dte_input.folio)
    _txt(idd, "FchEmis", dte_input.fecha_emision.isoformat())
    _txt(idd, "IndServicio", dte_input.indicador_servicio or ind_servicio or IND_SERVICIO_DEFECTO)

    # ---- Emisor (RznSocEmisor / GiroEmisor — nombres propios de boleta) ----
    em = dte_input.emisor
    e = etree.SubElement(enc, "Emisor")
    _txt(e, "RUTEmisor", em.rut)
    _txt(e, "RznSocEmisor", em.razon_social)
    _txt(e, "GiroEmisor", em.giro)
    if em.direccion:
        _txt(e, "DirOrigen", em.direccion)
    if em.comuna:
        _txt(e, "CmnaOrigen", em.comuna)
    if em.ciudad:
        _txt(e, "CiudadOrigen", em.ciudad)

    # ---- Receptor (mínimo RUTRecep; consumidor final = 66666666-6) ----
    r = dte_input.receptor
    rc = etree.SubElement(enc, "Receptor")
    _txt(rc, "RUTRecep", r.rut)
    if r.razon_social and r.razon_social.upper() != "CONSUMIDOR FINAL":
        _txt(rc, "RznSocRecep", r.razon_social)
    if r.direccion:
        _txt(rc, "DirRecep", r.direccion)
    if r.comuna:
        _txt(rc, "CmnaRecep", r.comuna)
    if r.ciudad:
        _txt(rc, "CiudadRecep", r.ciudad)

    # ---- Totales ----
    tot = etree.SubElement(enc, "Totales")
    if totales.monto_neto:
        _txt(tot, "MntNeto", totales.monto_neto)
    if totales.monto_exento:
        _txt(tot, "MntExe", totales.monto_exento)
    if totales.iva_monto:
        _txt(tot, "IVA", totales.iva_monto)
    _txt(tot, "MntTotal", totales.monto_total)

    # ---- Detalle ----
    for i, it in enumerate(dte_input.items, 1):
        d = etree.SubElement(doc, "Detalle")
        _txt(d, "NroLinDet", it.numero_linea or i)
        if it.exento:
            _txt(d, "IndExe", 1)
        _txt(d, "NmbItem", it.nombre)
        if it.cantidad is not None:
            _txt(d, "QtyItem", _num(it.cantidad))
        if it.unidad_medida:
            _txt(d, "UnmdItem", it.unidad_medida)
        if it.precio_unitario is not None:
            _txt(d, "PrcItem", _num(it.precio_unitario))
        if it.descuento_monto:
            _txt(d, "DescuentoMonto", int(it.descuento_monto))
        monto = int(round((it.cantidad or 0) * (it.precio_unitario or 0) - (it.descuento_monto or 0)))
        _txt(d, "MontoItem", monto)

    # ---- Referencia (va DESPUÉS de Detalle y ANTES del TED; orden del XSD v4.2:
    #      NroLinRef → TpoDocRef → FolioRef → CodRef → RazonRef) ----
    if razon_referencia or cod_referencia or tpo_doc_ref:
        ref = etree.SubElement(doc, "Referencia")
        _txt(ref, "NroLinRef", 1)
        if tpo_doc_ref:
            _txt(ref, "TpoDocRef", tpo_doc_ref)
        if folio_ref is not None:
            _txt(ref, "FolioRef", folio_ref)
        if cod_referencia:
            _txt(ref, "CodRef", cod_referencia[:18])
        if razon_referencia:
            _txt(ref, "RazonRef", razon_referencia[:90])

    # ---- TED + timestamp ----
    doc.append(etree.fromstring(
        ted_xml.encode("utf-8") if isinstance(ted_xml, str) else ted_xml))
    _txt(doc, "TmstFirma", datetime.now().strftime("%Y-%m-%dT%H:%M:%S"))
    return dte


def generar_envio_boleta(documentos: List[etree._Element], rut_emisor: str, rut_envia: str,
                         rut_receptor: str = "60803000-K", fecha_resolucion: str = "2014-08-22",
                         numero_resolucion: int = 0) -> etree._Element:
    """Genera el sobre `<EnvioBOLETA>` (SetDTE + Caratula + SubTotDTE + DTE+), sin firmar.

    `numero_resolucion=0` es lo correcto para el ambiente de CERTIFICACIÓN.
    """
    nsmap = {None: SII_NAMESPACE, "xsi": "http://www.w3.org/2001/XMLSchema-instance"}
    envio = etree.Element("EnvioBOLETA", nsmap=nsmap, attrib={
        "version": "1.0",
        "{http://www.w3.org/2001/XMLSchema-instance}schemaLocation": _XSD_BOLETA})
    set_dte = etree.SubElement(envio, "SetDTE", attrib={"ID": "SetDoc"})

    car = etree.SubElement(set_dte, "Caratula", attrib={"version": "1.0"})
    _txt(car, "RutEmisor", rut_emisor)
    _txt(car, "RutEnvia", rut_envia)
    _txt(car, "RutReceptor", rut_receptor)
    _txt(car, "FchResol", fecha_resolucion)
    _txt(car, "NroResol", str(numero_resolucion))
    _txt(car, "TmstFirmaEnv", datetime.now().strftime("%Y-%m-%dT%H:%M:%S"))

    subsets: dict = {}
    for doc in documentos:
        te = doc.find(f".//{{{SII_NAMESPACE}}}TipoDTE")
        if te is None:  # el DTE crudo (pre-reparse) tiene los tags sin namespace
            te = doc.find(".//TipoDTE")
        tipo = int(te.text) if te is not None else 0
        subsets.setdefault(tipo, []).append(doc)
    for tipo, docs in subsets.items():
        st = etree.SubElement(car, "SubTotDTE")
        _txt(st, "TpoDTE", tipo)
        _txt(st, "NroDTE", len(docs))

    for doc in documentos:
        set_dte.append(doc)
    return envio
