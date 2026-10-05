"""
core/dte_xml.py — Leer un DTE ya emitido (XML firmado) y volver a su entrada.

Sirve para dos cosas: regenerar el PDF de un documento del que solo se tiene el XML (los que
emite el núcleo en Go, los importados), y reconstruir casos del corpus dorado privado. Lee lo
que el motor escribe (`GeneradorDTE`, `generar_documento_boleta`); no pretende cubrir todo
el XSD del SII.
"""
from __future__ import annotations

from datetime import date
from typing import Optional, Tuple

from lxml import etree

from core.dte import DTEInput, EmisorModel, ItemDTE, ReceptorModel, ReferenciaModel, TipoDTE

NS = "{http://www.sii.cl/SiiDte}"


def _t(el, tag: str) -> Optional[str]:
    x = el.find(NS + tag) if el is not None else None
    return x.text if x is not None else None


def documento_desde_xml(xml: bytes | str) -> Tuple[DTEInput, str]:
    """`(DTEInput, ted_xml)` a partir del `<DTE>` firmado (o del sobre que lo contiene; toma
    el primero). El TED se devuelve tal cual está en el XML (string), listo para el PDF417."""
    # Los DTE del motor no llevan declaración XML y son ISO-8859-1: si se parsean como bytes,
    # lxml asume UTF-8 y revienta con la primera tilde. Se parsea el texto decodificado.
    if isinstance(xml, bytes):
        xml = xml if xml.startswith(b"<?xml") else xml.decode("ISO-8859-1")
    root = etree.fromstring(xml)
    doc = root.find(f".//{NS}Documento") if root.tag != NS + "Documento" else root
    if doc is None:
        raise ValueError("El XML no contiene un <Documento> del SII")
    enc = doc.find(NS + "Encabezado")
    idd, em, rc = enc.find(NS + "IdDoc"), enc.find(NS + "Emisor"), enc.find(NS + "Receptor")
    tipo = int(_t(idd, "TipoDTE"))
    es_boleta = tipo in (39, 41)
    emisor = EmisorModel(
        rut=_t(em, "RUTEmisor"), razon_social=_t(em, "RznSoc") or _t(em, "RznSocEmisor") or "",
        giro=_t(em, "GiroEmis") or _t(em, "GiroEmisor") or "", codigo_actividad=int(_t(em, "Acteco") or 0),
        direccion=_t(em, "DirOrigen") or "", comuna=_t(em, "CmnaOrigen") or "", ciudad=_t(em, "CiudadOrigen") or "",
        telefono=_t(em, "Telefono"), email=_t(em, "CorreoEmisor"), es_receptor_boleta=es_boleta)
    receptor = ReceptorModel(
        rut=_t(rc, "RUTRecep"), razon_social=_t(rc, "RznSocRecep") or "CONSUMIDOR FINAL",
        giro=_t(rc, "GiroRecep"), direccion=_t(rc, "DirRecep"), comuna=_t(rc, "CmnaRecep"),
        ciudad=_t(rc, "CiudadRecep"), email=_t(rc, "CorreoRecep"),
        es_contribuyente=(_t(rc, "RUTRecep") or "") != "66666666-6")
    items = []
    for det in doc.findall(NS + "Detalle"):
        qty = _t(det, "QtyItem")
        cod = det.find(NS + "CdgItem")
        items.append(ItemDTE(
            numero_linea=int(_t(det, "NroLinDet") or len(items) + 1), nombre=_t(det, "NmbItem") or "",
            descripcion=_t(det, "DscItem"), cantidad=float(qty) if qty else (0.0 if es_boleta else 1.0),
            unidad_medida=_t(det, "UnmdItem"), precio_unitario=float(_t(det, "PrcItem") or 0),
            descuento_pct=float(_t(det, "DescuentoPct") or 0), descuento_monto=float(_t(det, "DescuentoMonto") or 0),
            exento=_t(det, "IndExe") == "1", codigo_producto=_t(cod, "VlrCodigo") if cod is not None else None))
    refs = []
    for r in doc.findall(NS + "Referencia"):
        if _t(r, "TpoDocRef") and _t(r, "FchRef") and _t(r, "TpoDocRef").isdigit():
            refs.append(ReferenciaModel(
                numero_linea=int(_t(r, "NroLinRef") or 1), tipo_doc_ref=TipoDTE(int(_t(r, "TpoDocRef"))),
                folio_ref=int(_t(r, "FolioRef")), fecha_doc_ref=date.fromisoformat(_t(r, "FchRef")),
                codigo_ref=int(_t(r, "CodRef") or 1), razon_ref=_t(r, "RazonRef")))
    ted_el = doc.find(NS + "TED")
    ted_xml = etree.tostring(ted_el, encoding="unicode") if ted_el is not None else ""
    # el TED sale con xmlns heredado si se serializa suelto; el PDF417 lleva el TED a secas
    ted_xml = ted_xml.replace(' xmlns="http://www.sii.cl/SiiDte"', "", 1)
    dte = DTEInput(
        tipo_dte=TipoDTE(tipo), folio=int(_t(idd, "Folio")), fecha_emision=date.fromisoformat(_t(idd, "FchEmis")),
        emisor=emisor, receptor=receptor, items=items, referencias=refs or None,
        forma_pago=int(_t(idd, "FmaPago") or 1),
        fecha_vencimiento=date.fromisoformat(_t(idd, "FchVenc")) if _t(idd, "FchVenc") else None,
        indicador_servicio=int(_t(idd, "IndServicio")) if _t(idd, "IndServicio") else None)
    return dte, ted_xml
