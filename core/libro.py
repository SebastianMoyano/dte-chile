"""
core/libro.py

Generación del Libro de Compras y Ventas Electrónico (IECV) del SII.

El "Libro" es un documento XML (esquema ``LibroCV_v10.xsd``) que resume los
documentos tributarios de un período. Se usa tanto para el Libro de Ventas
(``TipoOperacion=VENTA``) como el de Compras (``TipoOperacion=COMPRA``); ambos
comparten estructura y sólo cambian ese campo y los totales aplicables.

Estructura:
    LibroCompraVenta > EnvioLibro(ID) > Caratula + ResumenPeriodo + Detalle* + TmstFirma
    y <Signature> HERMANA de EnvioLibro (firmada sobre el ID de EnvioLibro).

Dos requisitos NO evidentes del SII (aprendidos contra el SII vivo, durante una
certificación real), ambos resueltos aquí:

1. **Largo de línea**: el SII rechaza (``CHR-00002: Line too long``) cualquier
   línea > 4090 bytes. Como el libro va sin pretty-print, se insertan saltos de
   línea entre elementos ANTES de firmar. C14N preserva ese whitespace verbatim,
   así que el digest de la firma sigue cuadrando (la firma va sobre EnvioLibro,
   los saltos quedan dentro de su C14N de forma consistente).

2. **Montos obligatorios**: cada ``<Detalle>`` DEBE incluir ``MntExe``,
   ``MntNeto`` y ``MntIVA`` aunque sean 0 (si no, ``LBR-3 Falta [MntNeto MntExe
   MntIVA]`` y el libro sale ``LRH - Descuadrado``).

3. **Retención total del IVA en un t46 (factura de compra), Libro de COMPRAS**:
   ``MntIVA`` lleva el IVA completo, ``MntTotal`` lo resta (``DetalleLibro.total``),
   y la retención va en ``<OtrosImp CodImp=15>`` — NUNCA en ``<IVARetTotal>``, que es
   exclusivo del Libro de VENTAS. Ver ``DetalleLibro.factura_compra_retencion_total``
   y ``docs/LECCIONES-SII.md`` → "La regla del t46 con retención total" (verificado
   contra el SII: set 4943175, reparos ``SRH`` resueltos).

El XML va en ISO-8859-1, sin pretty-print. Los montos van POSITIVOS por
documento; el SII aplica el signo según el tipo (61=NC resta).
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import List, Optional, Tuple

from lxml import etree

from core.crypto import CertificadoDigital, firmar_xml_sii
from core.dte import redondear

SII_NS = "http://www.sii.cl/SiiDte"
DS_NS = "http://www.w3.org/2000/09/xmldsig#"
TASA_IVA_DEFAULT = "19.00"

# Código de "Otros Impuestos" (SiiDte:ImptoType) para retención total del IVA.
# Verificado contra core/xsd/LceSiiTypes_v10.xsd: 15 = "IVA Retenido Total".
COD_IMP_RETENCION_TOTAL = 15

# Orden EXACTO de los hijos de <Detalle> según LibroCV_v10.xsd (los tags fuera de
# secuencia hacen que el SII rechace por schema). Sólo se emiten los presentes.
# ``OtrosImp`` es anidado y repetible (CodImp/TasaImp/MntImp cada uno) — se maneja
# aparte, igual que ``IVANoRec``.
_ORDEN_DETALLE = [
    "TpoDoc", "IndFactCompra", "NroDoc", "Anulado", "TpoImp", "TasaImp",
    "FchDoc", "RUTDoc", "RznSoc", "TpoDocRef", "FolioDocRef",
    "MntExe", "MntNeto", "MntIVA", "IVANoRec", "IVAUsoComun", "OtrosImp",
    "IVARetTotal", "MntTotal",
]

# Orden EXACTO de los hijos de <TotalesPeriodo>. ``TotOtrosImp`` también es
# anidado y repetible (CodImp/TotMntImp) — se maneja aparte, igual que ``TotIVANoRec``.
_ORDEN_TOTALES = [
    "TpoDoc", "TotDoc", "TotMntExe", "TotMntNeto", "TotOpIVARec", "TotMntIVA",
    "TotIVANoRec", "TotOpIVAUsoComun", "TotIVAUsoComun", "FctProp",
    "TotCredIVAUsoComun", "TotOtrosImp", "TotOpIVARetTotal", "TotIVARetTotal",
    "TotMntTotal",
]


@dataclass
class DetalleLibro:
    """Un documento del libro (una fila del Detalle)."""
    tipo_doc: int
    folio: int
    fecha: date
    rut_doc: str
    razon_social: str = ""
    monto_exento: int = 0
    monto_neto: int = 0
    monto_iva: int = 0
    monto_total: Optional[int] = None  # si None se calcula exe+neto+iva
    tasa_imp: str = TASA_IVA_DEFAULT
    tipo_doc_ref: Optional[int] = None
    folio_doc_ref: Optional[int] = None
    # --- específicos de COMPRAS ---
    # IndFactCompra: SOLO para una NC/ND que afecta a una factura de compra (LC) —
    # valor "1" = "Emitido por el Emisor del Libro de Compra" (LibroCV_v10.xsd:899-913).
    # NO aplica al t46 mismo; no confundir con la retención de IVA (eso es `otros_imp`).
    ind_fact_compra: Optional[int] = None
    iva_uso_comun: Optional[int] = None          # monto IVA de uso común
    # IVA Retenido Total — el XSD lo anota "(LV)": es EXCLUSIVO del Libro de VENTAS
    # (LibroCV_v10.xsd:1239). Para retención total en COMPRAS (t46) usar `otros_imp`
    # con CodImp=15 — ver `factura_compra_retencion_total` más abajo y
    # docs/LECCIONES-SII.md → "La regla del t46 con retención total".
    iva_ret_total: Optional[int] = None
    iva_no_rec_cod: Optional[int] = None         # código IVA no recuperable
    iva_no_rec_monto: Optional[int] = None
    # Otros Impuestos o Recargos (<OtrosImp> del XSD): lista de (CodImp, TasaImp, MntImp).
    # Cod 15 = retención total del IVA (Libro de Compras); 30-41 = retención parcial, etc.
    otros_imp: List[Tuple[int, str, int]] = field(default_factory=list)
    anulado: bool = False

    @property
    def total(self) -> int:
        if self.monto_total is not None:
            return self.monto_total
        t = self.monto_exento + self.monto_neto + self.monto_iva
        if self.iva_uso_comun:
            t += self.iva_uso_comun
        if self.iva_no_rec_monto:
            t += self.iva_no_rec_monto
        # Retención total (CodImp=15, Libro de Compras): el comprador retiene el IVA
        # completo y lo entera directo al SII, así que no forma parte del MntTotal del
        # documento aunque siga presente en MntIVA. Verificado: set 4943175, factura de
        # compra folio 9, neto 10866 → MntIVA=2065, MntTotal=10866 (docs/LECCIONES-SII.md).
        for cod, _tasa, monto in self.otros_imp:
            if cod == COD_IMP_RETENCION_TOTAL:
                t -= monto
        return t

    @classmethod
    def factura_compra_retencion_total(
        cls, folio: int, fecha: date, rut_doc: str, monto_neto: int,
        razon_social: str = "", tasa: str = TASA_IVA_DEFAULT, **kwargs,
    ) -> "DetalleLibro":
        """Factura de compra (t46) con retención total del IVA, para el Libro de COMPRAS.

        El comprador retiene el 100% del IVA y lo entera directo al SII: `MntIVA` lleva
        el IVA completo, pero se resta de `MntTotal`, y la retención se declara vía
        `<OtrosImp CodImp=15>` — NUNCA `<IVARetTotal>` (ese tag es del Libro de Ventas;
        emitirlo aquí causó el reparo SII "No Informa Adecuadamente IVA Retenido Total").
        """
        # redondear() (half-up), NO round() nativo: el banker's rounding de Python da
        # diferencias de $1 en los netos que caen en .5 (ej. 1350 → 256 vs 257 correcto) y
        # el SII rechaza el total. Mismo bug que core/dte.py ya documentó y evitó.
        iva = redondear(monto_neto * float(tasa) / 100)
        return cls(
            tipo_doc=46, folio=folio, fecha=fecha, rut_doc=rut_doc,
            razon_social=razon_social, monto_neto=monto_neto, monto_iva=iva,
            tasa_imp=tasa, otros_imp=[(COD_IMP_RETENCION_TOTAL, tasa, iva)], **kwargs,
        )


@dataclass
class CaratulaLibro:
    """Carátula del libro."""
    rut_emisor: str
    periodo: str                       # AAAA-MM
    fch_resol: str                     # AAAA-MM-DD
    tipo_operacion: str = "VENTA"      # VENTA | COMPRA
    nro_resol: str = "0"               # 0 en certificación (Maullín)
    tipo_libro: str = "ESPECIAL"       # MENSUAL | ESPECIAL | RECTIFICA
    tipo_envio: str = "TOTAL"          # TOTAL | PARCIAL | FINAL | AJUSTE
    folio_notificacion: str = "1"      # obligatorio si TipoLibro=ESPECIAL
    factor_proporcionalidad: float = 0.0  # FctProp para IVA uso común (ej. 0.60)


class GeneradorLibro:
    """Construye y firma el Libro de Compras/Ventas Electrónico."""

    def generar_xml(
        self,
        caratula: CaratulaLibro,
        detalles: List[DetalleLibro],
        certificado: CertificadoDigital,
        id_libro: str = "LIBRO",
        rut_envia: Optional[str] = None,
    ) -> bytes:
        """
        Genera el XML del libro firmado, en ISO-8859-1, listo para enviar.

        Args:
            caratula: datos de la carátula.
            detalles: lista de documentos del período.
            certificado: certificado para firmar (y RUT que envía por defecto).
            id_libro: atributo ID del <EnvioLibro> (xs:ID válido).
            rut_envia: RUT declarado en <RutEnvia>; por defecto el del certificado.
        """
        rut_envia = rut_envia or certificado.rut_emisor
        ts = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

        caratula_xml = self._construir_caratula(caratula, rut_envia)
        resumen_xml = self._construir_resumen(
            detalles, caratula.factor_proporcionalidad, caratula.tipo_operacion)
        detalles_xml = "\n".join(
            self._construir_detalle(d, caratula.tipo_operacion) for d in detalles)

        # Saltos de línea entre elementos (fix largo de línea > 4090). Van ANTES de
        # firmar: C14N los preserva y el digest de EnvioLibro sigue cuadrando.
        envio_libro = (
            f'<EnvioLibro ID="{id_libro}">\n{caratula_xml}\n'
            f'<ResumenPeriodo>\n{resumen_xml}\n</ResumenPeriodo>\n'
            f'{detalles_xml}\n<TmstFirma>{ts}</TmstFirma></EnvioLibro>'
        )
        libro_str = (
            f'<LibroCompraVenta xmlns="{SII_NS}" '
            'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
            f'xsi:schemaLocation="{SII_NS} LibroCV_v10.xsd" version="1.0">'
            f'{envio_libro}</LibroCompraVenta>'
        )

        # Firmar EnvioLibro (firma hermana, URI=#id_libro). firmar_xml_sii anexa la
        # <Signature> al root; la extraemos y la insertamos como string para no
        # re-serializar (y alterar) el contenido ya firmado.
        root = etree.fromstring(libro_str)
        firmar_xml_sii(root, certificado, uri=f"#{id_libro}")
        sig = etree.tostring(root.findall(f"{{{DS_NS}}}Signature")[-1], encoding="unicode")
        final = libro_str[: -len("</LibroCompraVenta>")] + "\n" + sig + "</LibroCompraVenta>"
        return b'<?xml version="1.0" encoding="ISO-8859-1"?>\n' + final.encode("ISO-8859-1")

    # ------------------------------------------------------------------ carátula
    def _construir_caratula(self, c: CaratulaLibro, rut_envia: str) -> str:
        xml = (
            f"<Caratula><RutEmisorLibro>{c.rut_emisor}</RutEmisorLibro>"
            f"<RutEnvia>{rut_envia}</RutEnvia>"
            f"<PeriodoTributario>{c.periodo}</PeriodoTributario>"
            f"<FchResol>{c.fch_resol}</FchResol><NroResol>{c.nro_resol}</NroResol>"
            f"<TipoOperacion>{c.tipo_operacion}</TipoOperacion>"
            f"<TipoLibro>{c.tipo_libro}</TipoLibro>"
            f"<TipoEnvio>{c.tipo_envio}</TipoEnvio>"
        )
        if c.tipo_libro == "ESPECIAL":
            xml += f"<FolioNotificacion>{c.folio_notificacion}</FolioNotificacion>"
        return xml + "</Caratula>"

    # -------------------------------------------------------------- ResumenPeriodo
    def _construir_resumen(
        self, detalles: List[DetalleLibro], fct_prop: float, tipo_operacion: str,
    ) -> str:
        # Agrupar por TpoDoc.
        grupos: dict = {}
        for d in detalles:
            g = grupos.setdefault(d.tipo_doc, [])
            g.append(d)

        bloques = []
        for tipo in sorted(grupos):
            docs = grupos[tipo]
            campos = {
                "TpoDoc": tipo,
                "TotDoc": len(docs),
                "TotMntExe": sum(d.monto_exento for d in docs),
                "TotMntNeto": sum(d.monto_neto for d in docs),
                "TotMntIVA": sum(d.monto_iva for d in docs),
                "TotMntTotal": sum(d.total for d in docs),
            }
            # IVA de uso común (compras): totales + factor + crédito proporcional.
            uso_comun = [d for d in docs if d.iva_uso_comun]
            if uso_comun:
                tot_uc = sum(d.iva_uso_comun for d in uso_comun)
                campos["TotOpIVAUsoComun"] = len(uso_comun)
                campos["TotIVAUsoComun"] = tot_uc
                campos["FctProp"] = f"{fct_prop:.2f}"
                campos["TotCredIVAUsoComun"] = redondear(tot_uc * fct_prop)
            # IVARetTotal es EXCLUSIVO del Libro de Ventas (XSD: "(LV)"). En Compras la
            # retención total va por TotOtrosImp/CodImp=15 (ver más abajo) — NUNCA aquí.
            if tipo_operacion == "VENTA":
                ret = [d for d in docs if d.iva_ret_total]
                if ret:
                    campos["TotOpIVARetTotal"] = len(ret)
                    campos["TotIVARetTotal"] = sum(d.iva_ret_total for d in ret)
            # Otros Impuestos o Recargos, agrupados por código (incluye la retención
            # total de Compras, CodImp=15 — docs/LECCIONES-SII.md).
            otros_por_cod: dict = {}
            for d in docs:
                for cod, _tasa, monto in d.otros_imp:
                    otros_por_cod[cod] = otros_por_cod.get(cod, 0) + monto
            tot_otros_xml = "".join(
                f"<TotOtrosImp><CodImp>{cod}</CodImp><TotMntImp>{monto}</TotMntImp></TotOtrosImp>"
                for cod, monto in sorted(otros_por_cod.items())
            )
            # IVA no recuperable (agrupado por código).
            norec = [d for d in docs if d.iva_no_rec_monto]
            tot_norec_xml = ""
            if norec:
                por_cod: dict = {}
                for d in norec:
                    e = por_cod.setdefault(d.iva_no_rec_cod, {"n": 0, "m": 0})
                    e["n"] += 1
                    e["m"] += d.iva_no_rec_monto
                for cod, e in sorted(por_cod.items()):
                    tot_norec_xml += (
                        f"<TotIVANoRec><CodIVANoRec>{cod}</CodIVANoRec>"
                        f"<TotOpIVANoRec>{e['n']}</TotOpIVANoRec>"
                        f"<TotMntIVANoRec>{e['m']}</TotMntIVANoRec></TotIVANoRec>"
                    )

            # Emitir en el orden EXACTO del XSD, sólo los presentes.
            partes = []
            for tag in _ORDEN_TOTALES:
                if tag == "TotIVANoRec":
                    if tot_norec_xml:
                        partes.append(tot_norec_xml)
                elif tag == "TotOtrosImp":
                    if tot_otros_xml:
                        partes.append(tot_otros_xml)
                elif tag in campos:
                    partes.append(f"<{tag}>{campos[tag]}</{tag}>")
            bloques.append(f"<TotalesPeriodo>{''.join(partes)}</TotalesPeriodo>")
        return "\n".join(bloques)

    # --------------------------------------------------------------------- Detalle
    def _construir_detalle(self, d: DetalleLibro, tipo_operacion: str) -> str:
        # Documento anulado: sólo TpoDoc, NroDoc, Anulado.
        if d.anulado:
            return f"<Detalle><TpoDoc>{d.tipo_doc}</TpoDoc><NroDoc>{d.folio}</NroDoc><Anulado>A</Anulado></Detalle>"

        campos: dict = {
            "TpoDoc": d.tipo_doc,
            "NroDoc": d.folio,
            "FchDoc": d.fecha.isoformat() if isinstance(d.fecha, date) else d.fecha,
            "RUTDoc": d.rut_doc,
            "RznSoc": (d.razon_social or "")[:50],
            # MntExe/MntNeto/MntIVA SIEMPRE presentes (aunque 0) — requisito del SII.
            "MntExe": d.monto_exento,
            "MntNeto": d.monto_neto,
            "MntIVA": d.monto_iva,
            "MntTotal": d.total,
        }
        if d.ind_fact_compra is not None:
            campos["IndFactCompra"] = d.ind_fact_compra
        # TasaImp presente si hay cualquier impuesto (IVA normal, uso común, no
        # recuperable, retenido u otros impuestos). En ventas sólo hay monto_iva →
        # salida sin cambios.
        if d.monto_iva or d.iva_uso_comun or d.iva_no_rec_monto or d.iva_ret_total or d.otros_imp:
            campos["TasaImp"] = d.tasa_imp
        if d.tipo_doc_ref is not None:
            campos["TpoDocRef"] = d.tipo_doc_ref
            campos["FolioDocRef"] = d.folio_doc_ref
        if d.iva_uso_comun:
            campos["IVAUsoComun"] = d.iva_uso_comun
        # IVARetTotal es EXCLUSIVO del Libro de Ventas (XSD: "(LV)", LibroCV_v10.xsd:1239).
        # En Compras la retención total va por <OtrosImp CodImp=15> (más abajo) —
        # emitirlo aquí en Compras dio el reparo SII "No Informa Adecuadamente IVA
        # Retenido Total" (set 4943175, docs/LECCIONES-SII.md).
        if d.iva_ret_total and tipo_operacion == "VENTA":
            campos["IVARetTotal"] = d.iva_ret_total

        iva_no_rec_xml = ""
        if d.iva_no_rec_monto:
            iva_no_rec_xml = (
                f"<IVANoRec><CodIVANoRec>{d.iva_no_rec_cod}</CodIVANoRec>"
                f"<MntIVANoRec>{d.iva_no_rec_monto}</MntIVANoRec></IVANoRec>"
            )
        otros_imp_xml = "".join(
            f"<OtrosImp><CodImp>{cod}</CodImp><TasaImp>{tasa}</TasaImp>"
            f"<MntImp>{monto}</MntImp></OtrosImp>"
            for cod, tasa, monto in d.otros_imp
        )

        partes = []
        for tag in _ORDEN_DETALLE:
            if tag == "IVANoRec":
                if iva_no_rec_xml:
                    partes.append(iva_no_rec_xml)
            elif tag == "OtrosImp":
                if otros_imp_xml:
                    partes.append(otros_imp_xml)
            elif tag in campos:
                partes.append(f"<{tag}>{campos[tag]}</{tag}>")
        return f"<Detalle>{''.join(partes)}</Detalle>"
