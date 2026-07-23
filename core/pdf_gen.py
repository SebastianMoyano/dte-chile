"""
core/pdf_gen.py

Generador de representación gráfica (PDF) del DTE con timbre PDF417.

Usa ReportLab para construir el PDF y pdf417gen para el código de barras bidimensional
requerido por el SII de Chile.
"""

from __future__ import annotations

import io
from datetime import date
from typing import List, Optional

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm, mm
from reportlab.platypus import (
    HRFlowable,
    Image,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.platypus.flowables import HRFlowable

from core.dte import DTEInput, TipoDTE, calcular_totales


# Nombres de los tipos de DTE para mostrar en el PDF
NOMBRES_DTE = {
    33: "FACTURA ELECTRÓNICA",
    34: "FACTURA NO AFECTA O EXENTA ELECTRÓNICA",
    39: "BOLETA ELECTRÓNICA",
    41: "BOLETA NO AFECTA O EXENTA ELECTRÓNICA",
    52: "GUÍA DE DESPACHO ELECTRÓNICA",
    56: "NOTA DE DÉBITO ELECTRÓNICA",
    61: "NOTA DE CRÉDITO ELECTRÓNICA",
}

# Colores corporativos del documento
COLOR_HEADER = colors.HexColor("#1a3a5c")  # Azul oscuro marino
COLOR_LINEA = colors.HexColor("#2563eb")   # Azul medio
COLOR_GRIS = colors.HexColor("#f1f5f9")    # Gris muy claro para filas alternas


def _generar_barcode_pdf417(datos_ted: str) -> Optional[Image]:
    """
    Genera la imagen del código de barras PDF417 a partir de los datos del TED.

    Args:
        datos_ted: El contenido del TED como string (XML).

    Returns:
        Un objeto Image de ReportLab, o None si no se puede generar.
    """
    try:
        import pdf417gen
        codes = pdf417gen.encode(datos_ted, security_level=2, columns=12)
        image_data = pdf417gen.render_image(codes, scale=2, ratio=3)

        buf = io.BytesIO()
        image_data.save(buf, format="PNG")
        buf.seek(0)

        return Image(buf, width=9 * cm, height=2.5 * cm)
    except Exception:
        # Si pdf417gen no está disponible, retornar None (el PDF se genera sin barcode)
        return None


def formatear_rut(rut: str) -> str:
    """Formatea un RUT para visualización (agrega puntos si no los tiene)."""
    if "-" in rut:
        partes = rut.split("-")
        numero = partes[0].replace(".", "")
        dv = partes[1] if len(partes) > 1 else ""
        # Formatear con puntos
        numero_fmt = f"{int(numero):,}".replace(",", ".")
        return f"{numero_fmt}-{dv}"
    return rut


def formatear_monto(monto: int) -> str:
    """Formatea un monto en pesos chilenos."""
    return f"$ {monto:,.0f}".replace(",", ".")


def generar_pdf_dte(
    dte_input: DTEInput,
    ted_xml: Optional[str] = None,
    nombre_archivo: Optional[str] = None,
) -> bytes:
    """
    Genera el PDF de la representación gráfica del DTE.

    Args:
        dte_input: Los datos del DTE.
        ted_xml: XML del TED para codificar en el PDF417.
        nombre_archivo: Nombre del archivo PDF (solo para metadata).

    Returns:
        Contenido del PDF en bytes.
    """
    totales = calcular_totales(dte_input.items, dte_input.tipo_dte)
    buf = io.BytesIO()

    doc = SimpleDocTemplate(
        buf,
        pagesize=letter,
        rightMargin=1.5 * cm,
        leftMargin=1.5 * cm,
        topMargin=1.5 * cm,
        bottomMargin=1.5 * cm,
        title=f"DTE-{dte_input.tipo_dte.value}-{dte_input.folio}",
    )

    styles = getSampleStyleSheet()
    story = []

    # ---- Estilos personalizados ----
    style_titulo = ParagraphStyle(
        "Titulo",
        parent=styles["Heading1"],
        textColor=COLOR_HEADER,
        fontSize=13,
        fontName="Helvetica-Bold",
        alignment=TA_CENTER,
        spaceAfter=2,
    )
    style_subtitulo = ParagraphStyle(
        "Subtitulo",
        parent=styles["Normal"],
        textColor=COLOR_HEADER,
        fontSize=10,
        fontName="Helvetica-Bold",
        alignment=TA_CENTER,
        spaceAfter=2,
    )
    style_normal = ParagraphStyle(
        "Normal8",
        parent=styles["Normal"],
        fontSize=8,
        fontName="Helvetica",
    )
    style_negrita = ParagraphStyle(
        "Negrita8",
        parent=styles["Normal"],
        fontSize=8,
        fontName="Helvetica-Bold",
    )
    style_label = ParagraphStyle(
        "Label",
        parent=styles["Normal"],
        fontSize=7,
        textColor=colors.grey,
        fontName="Helvetica",
    )

    nombre_dte = NOMBRES_DTE.get(dte_input.tipo_dte.value, f"DTE TIPO {dte_input.tipo_dte.value}")

    # ======== HEADER ========
    # Tabla de 3 columnas: Emisor | Tipo DTE + Folio | (vacío / logo)
    encabezado_data = [
        [
            # Columna izquierda: Datos del emisor
            Paragraph(f"<b>{dte_input.emisor.razon_social.upper()}</b>", style_subtitulo),
            # Columna central: Tipo DTE y Folio (en un recuadro destacado)
            Table(
                [
                    [Paragraph(nombre_dte, style_titulo)],
                    [Paragraph(f"RUT: {formatear_rut(dte_input.emisor.rut)}", style_subtitulo)],
                    [Paragraph(f"N° <b>{dte_input.folio}</b>", style_titulo)],
                ],
                style=TableStyle([
                    ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                    ("BOX", (0, 0), (-1, -1), 1.5, COLOR_LINEA),
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#EBF2FF")),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]),
            ),
            # Columna derecha: SII
            Paragraph("S.I.I.", style_subtitulo),
        ]
    ]

    encabezado_table = Table(
        encabezado_data,
        colWidths=[7 * cm, 8 * cm, 3.5 * cm],
        style=TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ALIGN", (0, 0), (0, 0), "LEFT"),
            ("ALIGN", (2, 0), (2, 0), "RIGHT"),
        ]),
    )
    story.append(encabezado_table)
    story.append(Spacer(1, 3 * mm))

    # Datos adicionales del emisor
    emisor_data = [
        [Paragraph(f"Giro: {dte_input.emisor.giro}", style_normal),
         Paragraph(f"Fecha de Emisión: <b>{dte_input.fecha_emision.isoformat()}</b>", style_normal)],
        [Paragraph(f"Dirección: {dte_input.emisor.direccion}, {dte_input.emisor.comuna}, {dte_input.emisor.ciudad}", style_normal), ""],
    ]
    emisor_table = Table(emisor_data, colWidths=[12 * cm, 6.5 * cm])
    emisor_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(emisor_table)
    story.append(HRFlowable(width="100%", thickness=1, color=COLOR_LINEA, spaceAfter=3, spaceBefore=3))

    # ======== RECEPTOR ========
    story.append(Paragraph("DATOS DEL RECEPTOR", style_label))
    receptor_data = [
        [
            Paragraph(f"Razón Social: <b>{dte_input.receptor.razon_social}</b>", style_normal),
            Paragraph(f"RUT: <b>{formatear_rut(dte_input.receptor.rut)}</b>", style_normal),
        ],
    ]
    if dte_input.receptor.giro:
        receptor_data.append([
            Paragraph(f"Giro: {dte_input.receptor.giro}", style_normal), ""
        ])
    if dte_input.receptor.direccion:
        receptor_data.append([
            Paragraph(f"Dirección: {dte_input.receptor.direccion}, {dte_input.receptor.comuna or ''}, {dte_input.receptor.ciudad or ''}", style_normal), ""
        ])

    receptor_table = Table(receptor_data, colWidths=[12 * cm, 6.5 * cm])
    receptor_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("BACKGROUND", (0, 0), (-1, -1), COLOR_GRIS),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(receptor_table)
    story.append(Spacer(1, 4 * mm))

    # ======== TABLA DE ÍTEMS ========
    items_header = [
        Paragraph("N°", style_negrita),
        Paragraph("Código", style_negrita),
        Paragraph("Descripción", style_negrita),
        Paragraph("Cant.", style_negrita),
        Paragraph("U.M.", style_negrita),
        Paragraph("Precio Unit.", style_negrita),
        Paragraph("Desc.", style_negrita),
        Paragraph("Total", style_negrita),
    ]

    items_data = [items_header]
    for item in dte_input.items:
        row_bg = COLOR_GRIS if item.numero_linea % 2 == 0 else colors.white
        items_data.append([
            Paragraph(str(item.numero_linea), style_normal),
            Paragraph(item.codigo_producto or "", style_normal),
            Paragraph(item.nombre + (f"\n{item.descripcion}" if item.descripcion else ""), style_normal),
            Paragraph(f"{item.cantidad:g}", style_normal),
            Paragraph(item.unidad_medida or "", style_normal),
            Paragraph(formatear_monto(int(item.precio_unitario)), style_normal),
            Paragraph(formatear_monto(int(item.monto_descuento)) if item.monto_descuento else "-", style_normal),
            Paragraph(formatear_monto(int(item.monto_neto)), style_normal),
        ])

    items_table = Table(
        items_data,
        colWidths=[0.7 * cm, 2 * cm, 6.3 * cm, 1.2 * cm, 1 * cm, 2.5 * cm, 1.5 * cm, 2.8 * cm],
        repeatRows=1,
    )
    items_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), COLOR_HEADER),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("ALIGN", (2, 1), (2, -1), "LEFT"),
        ("ALIGN", (5, 1), (-1, -1), "RIGHT"),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#CBD5E1")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, COLOR_GRIS]),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(items_table)
    story.append(Spacer(1, 4 * mm))

    # ======== TOTALES ========
    totales_data = []
    if totales.monto_neto > 0:
        totales_data.append(["Neto:", Paragraph(formatear_monto(totales.monto_neto), style_normal)])
    if totales.monto_exento > 0:
        totales_data.append(["Exento:", Paragraph(formatear_monto(totales.monto_exento), style_normal)])
    if totales.iva_monto > 0:
        totales_data.append([f"IVA ({totales.iva_tasa}%):", Paragraph(formatear_monto(totales.iva_monto), style_normal)])
    totales_data.append(["TOTAL:", Paragraph(f"<b>{formatear_monto(totales.monto_total)}</b>", style_negrita)])

    totales_table = Table(
        totales_data,
        colWidths=[3 * cm, 3 * cm],
        hAlign="RIGHT",
    )
    totales_table.setStyle(TableStyle([
        ("ALIGN", (0, 0), (0, -1), "RIGHT"),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("LINEABOVE", (0, -1), (-1, -1), 1, COLOR_LINEA),
        ("TOPPADDING", (0, -1), (-1, -1), 3),
        ("BACKGROUND", (0, -1), (-1, -1), COLOR_GRIS),
    ]))
    story.append(totales_table)

    # ======== TIMBRE ELECTRÓNICO / BARCODE ========
    story.append(Spacer(1, 6 * mm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.lightgrey))
    story.append(Spacer(1, 2 * mm))

    timbre_header = Paragraph(
        "Timbre Electrónico SII - Resolución N° 80 de 2014",
        ParagraphStyle("Timbre", parent=styles["Normal"], fontSize=7, textColor=colors.grey, alignment=TA_CENTER),
    )
    story.append(timbre_header)

    # Intentar generar el barcode PDF417
    if ted_xml:
        barcode_img = _generar_barcode_pdf417(ted_xml)
        if barcode_img:
            barcode_img.hAlign = "CENTER"
            story.append(Spacer(1, 2 * mm))
            story.append(barcode_img)

    story.append(Spacer(1, 3 * mm))

    # Pie de página
    from core.config import settings
    pie_style = ParagraphStyle("Pie", parent=styles["Normal"], fontSize=7, textColor=colors.grey, alignment=TA_CENTER)
    story.append(Paragraph(
        f"Documento generado el {date.today().isoformat()} — "
        f"{'AMBIENTE DE CERTIFICACIÓN SII' if settings.sii_ambiente == 'certificacion' else 'PRODUCCIÓN SII'}",
        pie_style,
    ))

    doc.build(story)
    return buf.getvalue()


def generar_boleta_80mm(dte_input: DTEInput, ted_xml: Optional[str] = None) -> bytes:
    """Genera el PDF de una BOLETA en formato **80mm** (rollo térmico), layout de recibo.

    Independiente del XML/emisión: solo necesita los datos de la boleta + el TED (para el
    timbre PDF417). Reusa `_generar_barcode_pdf417`, `formatear_rut/monto` y `calcular_totales`.
    """
    from reportlab.platypus import Image, Paragraph, Spacer, Table, TableStyle

    ancho = 80 * mm
    margen = 3.5 * mm
    ancho_util = ancho - 2 * margen
    # alto aproximado al contenido (rollo térmico): base + por ítem.
    alto = (115 + 11 * max(1, len(dte_input.items))) * mm
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=(ancho, alto), leftMargin=margen,
                            rightMargin=margen, topMargin=margen, bottomMargin=margen)

    base = getSampleStyleSheet()["Normal"]
    ctr = ParagraphStyle("ctr", parent=base, fontSize=8, alignment=TA_CENTER, leading=10)
    bold = ParagraphStyle("bold", parent=ctr, fontSize=9.5, fontName="Helvetica-Bold")
    tiny = ParagraphStyle("tiny", parent=ctr, fontSize=6.5, textColor=colors.grey, leading=8)
    izq = ParagraphStyle("izq", parent=base, fontSize=7.5, alignment=TA_LEFT, leading=9.5)
    der = ParagraphStyle("der", parent=izq, alignment=TA_RIGHT)

    def hr():
        return HRFlowable(width="100%", thickness=0.6, color=colors.HexColor("#94a3b8"),
                          spaceBefore=3, spaceAfter=3, dash=(1, 1))

    tipo = dte_input.tipo_dte.value
    totales = calcular_totales(dte_input.items, dte_input.tipo_dte)
    e = []

    # ---- Emisor ----
    e.append(Paragraph(dte_input.emisor.razon_social.upper(), bold))
    e.append(Paragraph(f"RUT: {formatear_rut(dte_input.emisor.rut)}", ctr))
    if dte_input.emisor.giro:
        e.append(Paragraph(dte_input.emisor.giro, tiny))
    if dte_input.emisor.direccion:
        dir_txt = ", ".join(filter(None, [dte_input.emisor.direccion, dte_input.emisor.comuna]))
        e.append(Paragraph(dir_txt, tiny))
    e.append(Spacer(1, 2.5 * mm))

    # ---- Tipo + folio ----
    e.append(Paragraph(NOMBRES_DTE.get(tipo, f"DTE {tipo}"), bold))
    e.append(Paragraph(f"N° {dte_input.folio}", ctr))
    e.append(Paragraph(f"Fecha: {dte_input.fecha_emision.isoformat()}", tiny))
    e.append(hr())

    # ---- Ítems ----
    filas = []
    for it in dte_input.items:
        cant = it.cantidad or 0
        precio = it.precio_unitario or 0
        monto = int(round(cant * precio - (it.descuento_monto or 0)))
        sub = (f"<font size=6 color='#64748b'>{int(cant)} x "
               f"{formatear_monto(int(precio))}</font>")
        filas.append([Paragraph(f"{it.nombre[:38]}<br/>{sub}", izq),
                      Paragraph(formatear_monto(monto), der)])
    tabla = Table(filas, colWidths=[ancho_util * 0.66, ancho_util * 0.34])
    tabla.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                               ("LEFTPADDING", (0, 0), (-1, -1), 0),
                               ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
    e.append(tabla)
    e.append(hr())

    # ---- Totales ----
    tot = []
    if totales.monto_neto:
        tot.append(("Neto", totales.monto_neto))
    if totales.iva_monto:
        tot.append(("IVA (19%)", totales.iva_monto))
    if totales.monto_exento:
        tot.append(("Exento", totales.monto_exento))
    for etq, val in tot:
        e.append(Table([[Paragraph(etq, izq), Paragraph(formatear_monto(val), der)]],
                       colWidths=[ancho_util * 0.6, ancho_util * 0.4],
                       style=[("LEFTPADDING", (0, 0), (-1, -1), 0),
                              ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    total_bold = ParagraphStyle("tb", parent=izq, fontSize=10, fontName="Helvetica-Bold")
    e.append(Table([[Paragraph("TOTAL", total_bold),
                     Paragraph(formatear_monto(totales.monto_total),
                               ParagraphStyle("tbr", parent=total_bold, alignment=TA_RIGHT))]],
                   colWidths=[ancho_util * 0.5, ancho_util * 0.5],
                   style=[("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                          ("TOPPADDING", (0, 0), (-1, -1), 4)]))
    e.append(hr())

    # ---- Timbre PDF417 ----
    if ted_xml:
        img = _generar_barcode_pdf417(ted_xml)
        if img is not None:
            img.drawWidth = ancho_util
            img.drawHeight = ancho_util / 3.0
            img.hAlign = "CENTER"
            e.append(Paragraph("Timbre Electrónico SII", tiny))
            e.append(Spacer(1, 1 * mm))
            e.append(img)
    e.append(Spacer(1, 1 * mm))
    e.append(Paragraph("Verifique este documento en www.sii.cl", tiny))

    doc.build(e)
    return buf.getvalue()
