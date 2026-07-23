"""
core/dte.py

Modelos de datos (Pydantic) y generador de XML para DTEs chilenos.

Tipos soportados en esta versión MVP:
 - Tipo 33: Factura Electrónica
 - Tipo 34: Factura No Afecta o Exenta Electrónica
 - Tipo 39: Boleta Electrónica
 - Tipo 41: Boleta No Afecta o Exenta Electrónica
 - Tipo 56: Nota de Débito Electrónica
 - Tipo 61: Nota de Crédito Electrónica

Referencia: Formato de Documentos Tributarios Electrónicos del SII de Chile.
"""

from __future__ import annotations

import base64
import io
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from enum import IntEnum
from typing import List, Optional

from lxml import etree
from pydantic import BaseModel, Field, field_validator

# Namespaces del SII
SII_NAMESPACE = "http://www.sii.cl/SiiDte"
XSD_LOCATION = "http://www.sii.cl/SiiDte EnvioDTE_v10.xsd"


def redondear(valor) -> int:
    """
    Redondeo aritmético estándar (half-up: los .5 van hacia afuera del cero),
    como exige el SII y como usa LibreDTE (round() de PHP).

    Necesario porque round() de Python usa banker's rounding (half-to-even),
    que difiere en los montos que caen exactamente en .5 y produce diferencias
    de $1 que el SII rechaza al revalidar los totales.
    """
    return int(Decimal(str(valor)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def formatear_numero(valor) -> str:
    """
    Formatea un número para el XML del SII: entero si no tiene decimales, o
    hasta 6 decimales (sin ceros sobrantes) si los tiene. PrcItem y QtyItem son
    Dec12_6Type en el XSD, por lo que NO deben truncarse a entero.
    """
    f = float(valor)
    if f == int(f):
        return str(int(f))
    return f"{f:.6f}".rstrip("0").rstrip(".")


class TipoDTE(IntEnum):
    """Tipos de Documentos Tributarios Electrónicos soportados."""
    FACTURA_ELECTRONICA = 33
    FACTURA_NO_AFECTA = 34
    LIQUIDACION_FACTURA = 40
    BOLETA_ELECTRONICA = 39
    BOLETA_NO_AFECTA = 41
    NOTA_DEBITO = 56
    NOTA_CREDITO = 61
    GUIA_DESPACHO = 52


class TipoDocumentoRef(IntEnum):
    """Tipos de documentos para referencias (notas de crédito/débito)."""
    ANULA_DTE = 1
    CORRIGE_TEXTO = 2
    CORRIGE_MONTOS = 3


# ------- MODELOS PYDANTIC -------

class DireccionModel(BaseModel):
    """Dirección de emisor o receptor."""
    direccion: str = Field(..., max_length=80, description="Dirección")
    comuna: str = Field(..., max_length=20, description="Comuna")
    ciudad: str = Field(..., max_length=20, description="Ciudad")

    @field_validator("direccion", "comuna", "ciudad", mode="before")
    @classmethod
    def strip_str(cls, v: str) -> str:
        return v.strip() if v else v


class EmisorModel(BaseModel):
    """Datos del emisor del DTE."""
    rut: str = Field(..., description="RUT del emisor sin puntos con guión (ej: 12345678-9)")
    razon_social: str = Field(..., max_length=100, description="Razón social o nombre del emisor")
    giro: str = Field(..., max_length=80, description="Giro o actividad económica")
    codigo_actividad: int = Field(..., description="Código de actividad económica (SII)")
    direccion: str = Field(..., max_length=80)
    comuna: str = Field(..., max_length=20)
    ciudad: str = Field(..., max_length=20)
    telefono: Optional[str] = Field(None, max_length=20)
    email: Optional[str] = Field(None, max_length=80)
    es_receptor_boleta: bool = Field(False, description="True si emite boletas electrónicas")


class ReceptorModel(BaseModel):
    """Datos del receptor del DTE."""
    rut: str = Field(..., description="RUT del receptor sin puntos con guión")
    razon_social: str = Field(..., max_length=100, description="Razón social o nombre del receptor")
    giro: Optional[str] = Field(None, max_length=80, description="Giro del receptor")
    direccion: Optional[str] = Field(None, max_length=80)
    comuna: Optional[str] = Field(None, max_length=20)
    ciudad: Optional[str] = Field(None, max_length=20)
    email: Optional[str] = Field(None, max_length=80)
    es_contribuyente: bool = Field(True, description="True si el receptor es contribuyente de IVA")


class ItemDTE(BaseModel):
    """Un ítem (línea de detalle) en el DTE."""
    numero_linea: int = Field(..., ge=1, description="Número de línea (1 en adelante)")
    nombre: str = Field(..., max_length=80, description="Nombre o descripción del producto/servicio")
    descripcion: Optional[str] = Field(None, max_length=1000, description="Descripción adicional")
    cantidad: float = Field(1.0, ge=0, description="Cantidad")
    unidad_medida: Optional[str] = Field(None, max_length=4, description="Unidad de medida (ej: UN, KG)")
    precio_unitario: float = Field(..., ge=0, description="Precio unitario sin impuestos")
    descuento_pct: float = Field(0.0, ge=0, le=100, description="Descuento en porcentaje")
    descuento_monto: float = Field(0.0, ge=0, description="Descuento como monto fijo")
    exento: bool = Field(False, description="True si el ítem está exento de IVA")
    codigo_producto: Optional[str] = Field(None, max_length=35, description="Código interno del producto")

    @property
    def monto_item(self) -> float:
        """Calcula el monto del ítem sin descuento (redondeo half-up para CLP)."""
        return redondear(self.cantidad * self.precio_unitario)

    @property
    def monto_descuento(self) -> float:
        """Calcula el monto de descuento (prioriza monto fijo sobre porcentaje)."""
        if self.descuento_monto > 0:
            return self.descuento_monto
        if self.descuento_pct > 0:
            return redondear(self.monto_item * self.descuento_pct / 100)
        return 0.0

    @property
    def monto_neto(self) -> float:
        """Monto del ítem después de descuento."""
        return self.monto_item - self.monto_descuento


class ReferenciaModel(BaseModel):
    """Referencia a otro documento (ej: nota de crédito referenciando una factura)."""
    numero_linea: int = Field(1, ge=1)
    tipo_doc_ref: TipoDTE = Field(..., description="Tipo del documento referenciado")
    folio_ref: int = Field(..., description="Folio del documento referenciado")
    fecha_doc_ref: date = Field(..., description="Fecha del documento referenciado")
    codigo_ref: int = Field(1, ge=1, le=3, description="Código del motivo (1=Anula, 2=Corrige texto, 3=Corrige montos)")
    razon_ref: Optional[str] = Field(None, max_length=90, description="Descripción del motivo de la referencia")


class DTEInput(BaseModel):
    """Modelo de entrada completo para generar un DTE."""
    tipo_dte: TipoDTE = Field(..., description="Tipo de DTE (33=Factura, 39=Boleta, 61=Nota Crédito, etc.)")
    folio: int = Field(default=0, ge=0, description="Número de folio del DTE. Si es 0, se auto-asignará usando el correlativo del CAF.")
    fecha_emision: date = Field(default_factory=date.today, description="Fecha de emisión del DTE")
    emisor: EmisorModel
    receptor: ReceptorModel
    items: List[ItemDTE] = Field(..., min_length=1, description="Lista de ítems del DTE")
    referencias: Optional[List[ReferenciaModel]] = Field(None, description="Referencias a otros documentos")
    forma_pago: int = Field(1, ge=1, le=3, description="1=Contado, 2=Crédito, 3=Sin Costo")
    fecha_vencimiento: Optional[date] = Field(None, description="Fecha de vencimiento (para facturas a crédito)")
    indicador_servicio: Optional[int] = Field(None, description="1-3 para boletas de servicios periódicos")
    observaciones: Optional[str] = Field(None, max_length=1000, description="Observaciones del DTE")


class TotalesDTE(BaseModel):
    """Totales calculados del DTE."""
    monto_neto: int = 0
    monto_exento: int = 0
    iva_tasa: int = 19  # IVA 19% en Chile
    iva_monto: int = 0
    monto_total: int = 0


def calcular_totales(items: List[ItemDTE], tipo_dte: TipoDTE) -> TotalesDTE:
    """
    Calcula los totales del DTE a partir de los ítems.

    Args:
        items: Lista de ítems del DTE.
        tipo_dte: Tipo de DTE (determina si aplica IVA o no).

    Returns:
        TotalesDTE con los montos calculados.
    """
    iva_tasa = 19  # IVA vigente en Chile
    tipos_afectos = {TipoDTE.FACTURA_ELECTRONICA, TipoDTE.BOLETA_ELECTRONICA, TipoDTE.NOTA_DEBITO, TipoDTE.NOTA_CREDITO, TipoDTE.GUIA_DESPACHO}
    tipos_exentos_doc = {TipoDTE.FACTURA_NO_AFECTA, TipoDTE.BOLETA_NO_AFECTA}
    boletas = {TipoDTE.BOLETA_ELECTRONICA, TipoDTE.BOLETA_NO_AFECTA}
    es_boleta = tipo_dte in boletas
    aplica_iva = tipo_dte in tipos_afectos

    monto_neto = 0
    monto_exento = 0
    bruto_afecto = 0  # en boletas el precio incluye IVA (monto bruto)

    for item in items:
        es_exento_item = item.exento or tipo_dte in tipos_exentos_doc
        if es_exento_item:
            monto_exento += int(item.monto_neto)
        elif es_boleta:
            bruto_afecto += int(item.monto_neto)
        else:
            monto_neto += int(item.monto_neto)

    iva_monto = 0
    if es_boleta and bruto_afecto > 0:
        # Boleta afecta: el precio incluye IVA. Se deriva el neto desde el bruto
        # y el IVA por diferencia (iva = total - neto), como LibreDTE, para
        # evitar el drift de redondeo de calcular neto*tasa.
        monto_neto = redondear(bruto_afecto / (1 + iva_tasa / 100))
        iva_monto = bruto_afecto - monto_neto
        monto_total = bruto_afecto + monto_exento
    else:
        if aplica_iva and monto_neto > 0:
            iva_monto = redondear(monto_neto * iva_tasa / 100)
        monto_total = monto_neto + monto_exento + iva_monto

    return TotalesDTE(
        monto_neto=monto_neto,
        monto_exento=monto_exento,
        iva_tasa=iva_tasa,
        iva_monto=iva_monto,
        monto_total=monto_total,
    )


# ------- GENERADOR DE XML -------

class GeneradorDTE:
    """
    Genera el XML de un DTE de acuerdo con los esquemas XSD oficiales del SII.
    """

    def generar_documento_xml(
        self,
        dte_input: DTEInput,
        ted_xml: Optional[str] = None,
    ) -> etree._Element:
        """
        Genera el elemento XML <DTE> completo.

        Args:
            dte_input: Datos del DTE a generar.
            ted_xml: XML del TED (timbre electrónico). Si es None, se genera un TED de placeholder.

        Returns:
            Elemento lxml <DTE> completo sin firmar.
        """
        totales = calcular_totales(dte_input.items, dte_input.tipo_dte)

        nsmap = {None: SII_NAMESPACE}
        dte = etree.Element("DTE", nsmap=nsmap, attrib={"version": "1.0"})
        documento = etree.SubElement(dte, "Documento", attrib={"ID": f"T{int(dte_input.tipo_dte)}F{dte_input.folio}"})

        # --- Encabezado ---
        encabezado = etree.SubElement(documento, "Encabezado")
        self._agregar_id_doc(encabezado, dte_input, totales)
        self._agregar_emisor(encabezado, dte_input.emisor)
        self._agregar_receptor(encabezado, dte_input.receptor)
        self._agregar_totales(encabezado, totales)

        # --- Detalle (ítems) ---
        for item in dte_input.items:
            self._agregar_detalle(documento, item)

        # --- Referencias ---
        if dte_input.referencias:
            for ref in dte_input.referencias:
                self._agregar_referencia(documento, ref)

        # --- TED (Timbre Electrónico) ---
        ted_placeholder = ted_xml or self._generar_ted_placeholder(dte_input, totales)
        try:
            ted_elem = etree.fromstring(ted_placeholder.encode("utf-8") if isinstance(ted_placeholder, str) else ted_placeholder)
            documento.append(ted_elem)
        except etree.XMLSyntaxError:
            # Si el TED no es XML válido, lo embebemos como texto
            ted_node = etree.SubElement(documento, "TED")
            ted_node.text = ted_placeholder

        # --- Timestamp de timbre ---
        tmstamp = etree.SubElement(documento, "TmstFirma")
        tmstamp.text = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

        return dte

    def generar_envio_dte(
        self,
        documentos: List[etree._Element],
        rut_emisor: str,
        rut_envia: str,
        rut_receptor: str = "60803000-K",  # SII RUT
        fecha_resolucion: str = "2014-08-22",
        numero_resolucion: int = 80,
    ) -> etree._Element:
        """
        Genera el contenedor <EnvioDTE> con uno o más documentos DTE.

        Args:
            documentos: Lista de elementos XML DTE a empaquetar.
            rut_emisor: RUT del emisor de los documentos.
            rut_envia: RUT de quien realiza el envío al SII.
            rut_receptor: RUT del receptor del envío (por defecto el SII).
            fecha_resolucion: Fecha de la resolución del SII.
            numero_resolucion: Número de la resolución del SII.

        Returns:
            Elemento <EnvioDTE> listo para firmar.
        """
        # El xsi:schemaLocation es OBLIGATORIO para el SII (sin él rechaza con
        # "SCH-00001: Invalid Schema Name"). El namespace xsi se "fuga" al C14N,
        # pero como ahora se firma con firmar_xml_sii sobre el árbol YA normalizado
        # (mismo contexto de namespaces que verá el SII), la firma sigue válida.
        nsmap = {
            None: SII_NAMESPACE,
            "xsi": "http://www.w3.org/2001/XMLSchema-instance",
        }
        envio = etree.Element(
            "EnvioDTE",
            nsmap=nsmap,
            attrib={
                "version": "1.0",
                "{http://www.w3.org/2001/XMLSchema-instance}schemaLocation": XSD_LOCATION,
            },
        )

        set_dte = etree.SubElement(envio, "SetDTE", attrib={"ID": "SetDoc"})

        # Caratula del set
        caratula = etree.SubElement(set_dte, "Caratula", attrib={"version": "1.0"})
        self._texto(caratula, "RutEmisor", rut_emisor)
        self._texto(caratula, "RutEnvia", rut_envia)
        self._texto(caratula, "RutReceptor", rut_receptor)
        self._texto(caratula, "FchResol", fecha_resolucion)
        self._texto(caratula, "NroResol", str(numero_resolucion))
        self._texto(caratula, "TmstFirmaEnv", datetime.now().strftime("%Y-%m-%dT%H:%M:%S"))

        # Subsets de DTEs por tipo
        subsets: dict[int, list] = {}
        for doc in documentos:
            # El tag emitido en IdDoc es <TipoDTE> (ver _agregar_id_doc). Buscar
            # "TpoDTE" (nombre del XSD) devolvía siempre None -> tipo=0, lo que
            # generaba un <SubTotDTE><TpoDTE>0</TpoDTE> inválido y el SII rechazaba
            # el EnvioDTE completo. Se usa is-not-None explícito porque un elemento
            # hoja de lxml sin hijos evalúa como falsy en un `or`.
            tipo_el = doc.find(f".//{{{SII_NAMESPACE}}}TipoDTE")
            if tipo_el is None:
                tipo_el = doc.find(".//TipoDTE")
            tipo = int(tipo_el.text) if tipo_el is not None else 0
            subsets.setdefault(tipo, []).append(doc)

        # El SubTotDTE va DENTRO de la Caratula (último hijo), no como hermano de
        # ella dentro del SetDTE. Ponerlo en set_dte hacía que el EnvioDTE fuera
        # inválido contra EnvioDTE_v10.xsd y el SII lo rechazara con "error en el
        # upload" (genérico).
        for tipo, docs in subsets.items():
            tipo_elem = etree.SubElement(caratula, "SubTotDTE")
            self._texto(tipo_elem, "TpoDTE", str(tipo))
            self._texto(tipo_elem, "NroDTE", str(len(docs)))

        for doc in documentos:
            set_dte.append(doc)

        return envio

    # ------- Métodos internos de construcción de nodos XML -------

    def _agregar_id_doc(self, encabezado: etree._Element, d: DTEInput, t: TotalesDTE):
        id_doc = etree.SubElement(encabezado, "IdDoc")
        self._texto(id_doc, "TipoDTE", str(d.tipo_dte.value))
        self._texto(id_doc, "Folio", str(d.folio))
        self._texto(id_doc, "FchEmis", d.fecha_emision.isoformat())
        if d.indicador_servicio:
            self._texto(id_doc, "IndServicio", str(d.indicador_servicio))
        self._texto(id_doc, "FmaPago", str(d.forma_pago))
        if d.fecha_vencimiento:
            self._texto(id_doc, "FchVenc", d.fecha_vencimiento.isoformat())

    def _agregar_emisor(self, encabezado: etree._Element, e: EmisorModel):
        emisor = etree.SubElement(encabezado, "Emisor")
        self._texto(emisor, "RUTEmisor", e.rut)
        self._texto(emisor, "RznSoc", e.razon_social)
        self._texto(emisor, "GiroEmis", e.giro)
        if e.telefono:
            self._texto(emisor, "Telefono", e.telefono)
        if e.email:
            self._texto(emisor, "CorreoEmisor", e.email)
        self._texto(emisor, "Acteco", str(e.codigo_actividad))
        self._texto(emisor, "DirOrigen", e.direccion)
        self._texto(emisor, "CmnaOrigen", e.comuna)
        self._texto(emisor, "CiudadOrigen", e.ciudad)

    def _agregar_receptor(self, encabezado: etree._Element, r: ReceptorModel):
        receptor = etree.SubElement(encabezado, "Receptor")
        self._texto(receptor, "RUTRecep", r.rut)
        self._texto(receptor, "RznSocRecep", r.razon_social)
        if r.giro:
            self._texto(receptor, "GiroRecep", r.giro)
        if r.email:
            self._texto(receptor, "CorreoRecep", r.email)
        if r.direccion:
            self._texto(receptor, "DirRecep", r.direccion)
        if r.comuna:
            self._texto(receptor, "CmnaRecep", r.comuna)
        if r.ciudad:
            self._texto(receptor, "CiudadRecep", r.ciudad)

    def _agregar_totales(self, encabezado: etree._Element, t: TotalesDTE):
        totales = etree.SubElement(encabezado, "Totales")
        if t.monto_neto > 0:
            self._texto(totales, "MntNeto", str(t.monto_neto))
        if t.monto_exento > 0:
            self._texto(totales, "MntExe", str(t.monto_exento))
        if t.iva_monto > 0:
            self._texto(totales, "TasaIVA", str(t.iva_tasa))
            self._texto(totales, "IVA", str(t.iva_monto))
        self._texto(totales, "MntTotal", str(t.monto_total))

    def _agregar_detalle(self, documento: etree._Element, item: ItemDTE):
        detalle = etree.SubElement(documento, "Detalle")
        self._texto(detalle, "NroLinDet", str(item.numero_linea))
        if item.codigo_producto:
            cod_item = etree.SubElement(detalle, "CdgItem")
            self._texto(cod_item, "TpoCodigo", "INT1")
            self._texto(cod_item, "VlrCodigo", item.codigo_producto)
        if item.exento:
            self._texto(detalle, "IndExe", "1")
        self._texto(detalle, "NmbItem", item.nombre)
        if item.descripcion:
            self._texto(detalle, "DscItem", item.descripcion)
        # Orden XSD-significativo (complexType Detalle): QtyItem debe ir ANTES que
        # UnmdItem, y ambos antes de PrcItem. El orden previo (UnmdItem->QtyItem)
        # provocaba rechazo del SII por tag fuera de secuencia.
        # QtyItem y PrcItem son opcionales (Dec12_6Type, min 0.000001): en notas de
        # crédito/débito de anulación o corrección de texto (sin cantidad/precio) se
        # OMITEN — emitirlos en 0 viola el XSD oficial. Solo NmbItem y MontoItem son
        # obligatorios en el Detalle.
        if item.cantidad and item.cantidad > 0:
            self._texto(detalle, "QtyItem", formatear_numero(item.cantidad))
        if item.unidad_medida:
            self._texto(detalle, "UnmdItem", item.unidad_medida)
        # PrcItem es Dec12_6Type: no truncar a entero (rompería MntNeto=Σ Qty·Prc).
        if item.precio_unitario and item.precio_unitario > 0:
            self._texto(detalle, "PrcItem", formatear_numero(item.precio_unitario))
        if item.descuento_pct > 0:
            self._texto(detalle, "DescuentoPct", str(item.descuento_pct))
        if item.monto_descuento > 0:
            self._texto(detalle, "DescuentoMonto", str(int(item.monto_descuento)))
        self._texto(detalle, "MontoItem", str(int(item.monto_neto)))

    def _agregar_referencia(self, documento: etree._Element, ref: ReferenciaModel):
        referencia = etree.SubElement(documento, "Referencia")
        self._texto(referencia, "NroLinRef", str(ref.numero_linea))
        self._texto(referencia, "TpoDocRef", str(ref.tipo_doc_ref.value))
        self._texto(referencia, "FolioRef", str(ref.folio_ref))
        self._texto(referencia, "FchRef", ref.fecha_doc_ref.isoformat())
        self._texto(referencia, "CodRef", str(ref.codigo_ref))
        if ref.razon_ref:
            self._texto(referencia, "RazonRef", ref.razon_ref)

    def _generar_ted_placeholder(self, d: DTEInput, t: TotalesDTE) -> str:
        """Genera un TED de marcador de posición (sin firma real del CAF)."""
        return (
            f'<TED version="1.0">'
            f"<DD><RE>{d.emisor.rut}</RE><TD>{d.tipo_dte.value}</TD>"
            f"<F>{d.folio}</F><FE>{d.fecha_emision.isoformat()}</FE>"
            f"<RR>{d.receptor.rut}</RR><RSR>{d.emisor.razon_social[:40]}</RSR>"
            f"<MNT>{t.monto_total}</MNT><IT1>{d.items[0].nombre[:40]}</IT1>"
            f"<CAF></CAF><TSTED>{datetime.now().strftime('%Y-%m-%dT%H:%M:%S')}</TSTED>"
            f"</DD><FRMT algoritmo=\"SHA1withRSA\">FIRMA_PLACEHOLDER</FRMT></TED>"
        )

    @staticmethod
    def _texto(parent: etree._Element, tag: str, text: str):
        """Agrega un subelemento con texto a un elemento padre."""
        elem = etree.SubElement(parent, tag)
        elem.text = text
        return elem

    def to_xml_string(self, elemento: etree._Element, pretty: bool = True) -> str:
        """Serializa un elemento XML a string."""
        return etree.tostring(
            elemento,
            pretty_print=pretty,
            xml_declaration=True,
            encoding="ISO-8859-1",
        ).decode("ISO-8859-1")

    def to_xml_bytes(self, elemento: etree._Element, pretty: bool = False) -> bytes:
        """Serializa un elemento XML a bytes en ISO-8859-1.

        La declaración XML se antepone a mano con COMILLAS DOBLES: lxml usa
        comillas simples (<?xml version='1.0'...?>) y el SII rechaza el upload si
        no vienen dobles (<?xml version="1.0" encoding="ISO-8859-1"?>).
        """
        cuerpo = etree.tostring(
            elemento,
            pretty_print=pretty,
            xml_declaration=False,
            encoding="ISO-8859-1",
        )
        return b'<?xml version="1.0" encoding="ISO-8859-1"?>\n' + cuerpo
