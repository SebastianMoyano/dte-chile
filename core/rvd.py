"""
core/rvd.py — Registro de Ventas Diario (RVD) / Consumo de Folios (RCOF) de boletas.

Quien emite boletas electrónicas debe reportar al SII, **todos los días**, el consumo de
folios del día: cuántos emitió, cuántos anuló y en qué rangos. Es una obligación aparte de
la emisión (Res. Ex. SII N° 74 de 2020 reemplazó el libro de boletas por este reporte diario).

El XML es `ConsumoFolios` (raíz), validado contra `core/xsd/ConsumoFolio_v10.xsd`. El orden
de los elementos sale del XSD y es significativo: el SII rechaza tags fuera de orden.

Estructura de referencia: LibreDTE (`lib/Sii/ConsumoFolio.php`).

## Dónde se envía: por el canal de FACTURAS, no por el REST de boletas

Contra toda intuición (las boletas SÍ tienen infraestructura REST propia), **el RVD viaja por
el `DTEUpload` clásico de facturas, con el token SOAP de factura**, a maullin/palena.

Lo dice el **OpenAPI oficial del SII** (`www4c.sii.cl/bolcoreinternetui/api/openapi.yaml`):

    "Los sitios rahue.sii.cl y api.sii.cl, son plataformas dedicadas a la recepción de
     Boleta Electrónica en Producción. El sitio de palena.sii.cl es la plataforma dedicada
     para la recepción de DTE y RVD en Producción."

Y su superficie completa son **10 rutas, ninguna de RVD**. Lo confirma el Instructivo Técnico:
*"**No hay cambios en el envío de RCOF**, que pasa a denominarse Registro de Ventas Diario"*.

⚠️ Se perdió tiempo buscando una ruta REST inexistente (16 nombres probados en pangal → 404) y
se descartó a LibreDTE por mandarlo al "endpoint viejo". **LibreDTE tenía razón.**
(Y el spec devuelve 503 sin `User-Agent` de navegador — el mismo capricho de siempre.)

Obligación (Res. Ex. SII **N° 74 de 2020**, letra I): dentro de las primeras **12 horas del día
siguiente**, incluidos fines de semana y festivos, **incluso los días sin ventas** (en cero).
"""
from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING, Iterable, Optional, Sequence

from lxml import etree

from core.crypto import CertificadoDigital, firmar_xml_sii
from core.database import get_db
from core.dte import SII_NAMESPACE
from core.errors import ValidacionError
from core.schema_validator import validar_xml_dte_strict

if TYPE_CHECKING:  # solo para el type hint; evita el ciclo rvd <-> sii
    from core.sii import ClienteSII

_XSD_CONSUMO = "http://www.sii.cl/SiiDte ConsumoFolio_v10.xsd"

# El XSD (TipoConsumoType) solo acepta estos tres tipos en el consumo de folios; por eso
# el Resumen tiene maxOccurs="3".
TIPOS_CONSUMO = (39, 41, 61)

_IVA_TASA = 19


def _txt(parent: etree._Element, tag: str, val) -> etree._Element:
    el = etree.SubElement(parent, tag)
    el.text = str(val)
    return el


def agrupar_rangos(folios: Iterable[int]) -> list[tuple[int, int]]:
    """Agrupa folios sueltos en rangos contiguos: [1,2,3,7,8] → [(1,3), (7,8)].

    Se ordena y se deduplica primero. La versión de LibreDTE no hace ninguna de las dos
    cosas: revienta con la lista vacía (`$folios[0]`) y produce rangos corruptos si un
    folio viene repetido. Aquí ambos casos están cubiertos.
    """
    unicos = sorted(set(int(f) for f in folios))
    if not unicos:
        return []

    rangos: list[tuple[int, int]] = []
    inicio = anterior = unicos[0]
    for folio in unicos[1:]:
        if folio == anterior + 1:
            anterior = folio
            continue
        rangos.append((inicio, anterior))
        inicio = anterior = folio
    rangos.append((inicio, anterior))
    return rangos


def boletas_del_dia(rut_emisor: str, dia: date, ambiente: Optional[str] = None) -> list[dict]:
    """Lee de la BD las boletas emitidas por `rut_emisor` en `dia` (tipos 39/41/61)."""
    sql = (
        "SELECT tipo_dte, folio, monto_neto, monto_exento, iva, monto_total, estado "
        "FROM dtes WHERE rut_emisor = ? AND fecha_emision = ? "
        f"AND tipo_dte IN ({','.join('?' * len(TIPOS_CONSUMO))})"
    )
    params: list = [rut_emisor, dia.isoformat(), *TIPOS_CONSUMO]
    if ambiente:
        sql += " AND ambiente = ?"
        params.append(ambiente)
    sql += " ORDER BY tipo_dte, folio"

    with get_db() as conn:
        return [dict(r) for r in conn.execute(sql, params)]


def dias_con_boletas(rut_emisor: str, desde: date, hasta: date,
                     ambiente: Optional[str] = None) -> list[date]:
    """Días entre `desde` y `hasta` (inclusive) en que `rut_emisor` emitió boletas."""
    sql = (
        "SELECT DISTINCT fecha_emision FROM dtes "
        "WHERE rut_emisor = ? AND fecha_emision BETWEEN ? AND ? "
        f"AND tipo_dte IN ({','.join('?' * len(TIPOS_CONSUMO))})"
    )
    params: list = [rut_emisor, desde.isoformat(), hasta.isoformat(), *TIPOS_CONSUMO]
    if ambiente:
        sql += " AND ambiente = ?"
        params.append(ambiente)
    sql += " ORDER BY fecha_emision"

    with get_db() as conn:
        return [date.fromisoformat(r[0]) for r in conn.execute(sql, params)]


def rvd_registrado(rut_emisor: str, dia: date) -> Optional[dict]:
    """Devuelve el último registro de RVD de ese día, o None si nunca se generó."""
    with get_db() as conn:
        fila = conn.execute(
            "SELECT * FROM rvd_envios WHERE rut_emisor = ? AND fecha = ? "
            "ORDER BY sec_envio DESC LIMIT 1",
            (rut_emisor, dia.isoformat()),
        ).fetchone()
    return dict(fila) if fila else None


def registrar_rvd(rut_emisor: str, dia: date, estado: str, sec_envio: int = 1,
                  track_id: Optional[str] = None, xml_path: Optional[str] = None,
                  detalle: Optional[str] = None) -> int:
    """Registra (o actualiza) el RVD de un día.

    El UNIQUE(rut_emisor, fecha, sec_envio) es lo que hace idempotente al programador:
    reintentar el mismo día actualiza la fila en vez de duplicar el reporte.
    """
    ahora = datetime.now().isoformat(timespec="seconds")
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO rvd_envios (rut_emisor, fecha, sec_envio, estado, track_id, "
            "xml_path, detalle, creado_en, actualizado_en) VALUES (?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(rut_emisor, fecha, sec_envio) DO UPDATE SET "
            "estado=excluded.estado, track_id=excluded.track_id, "
            "xml_path=excluded.xml_path, detalle=excluded.detalle, "
            "actualizado_en=excluded.actualizado_en",
            (rut_emisor, dia.isoformat(), sec_envio, estado, track_id, xml_path,
             detalle, ahora, ahora),
        )
        return cur.lastrowid or 0


def _resumen_por_tipo(tipo: int, docs: Sequence[dict]) -> etree._Element:
    """Arma el <Resumen> de un tipo. El orden de los tags lo fija el XSD."""
    emitidos = [d for d in docs if (d.get("estado") or "").lower() != "anulado"]
    anulados = [d for d in docs if (d.get("estado") or "").lower() == "anulado"]

    resumen = etree.Element("Resumen")
    _txt(resumen, "TipoDocumento", tipo)

    # Solo los montos de lo efectivamente emitido (lo anulado no vendió nada).
    neto = sum(int(d["monto_neto"] or 0) for d in emitidos)
    iva = sum(int(d["iva"] or 0) for d in emitidos)
    exento = sum(int(d["monto_exento"] or 0) for d in emitidos)
    total = sum(int(d["monto_total"] or 0) for d in emitidos)

    if neto:
        _txt(resumen, "MntNeto", neto)
    if iva:
        _txt(resumen, "MntIva", iva)
        _txt(resumen, "TasaIVA", _IVA_TASA)
    if exento:
        _txt(resumen, "MntExento", exento)
    _txt(resumen, "MntTotal", total)

    # FoliosUtilizados = emitidos + anulados (los anulados igual consumieron folio).
    _txt(resumen, "FoliosEmitidos", len(emitidos))
    _txt(resumen, "FoliosAnulados", len(anulados))
    _txt(resumen, "FoliosUtilizados", len(emitidos) + len(anulados))

    for inicial, final in agrupar_rangos(d["folio"] for d in emitidos):
        r = etree.SubElement(resumen, "RangoUtilizados")
        _txt(r, "Inicial", inicial)
        _txt(r, "Final", final)
    for inicial, final in agrupar_rangos(d["folio"] for d in anulados):
        r = etree.SubElement(resumen, "RangoAnulados")
        _txt(r, "Inicial", inicial)
        _txt(r, "Final", final)
    return resumen


def generar_consumo_folios(
    rut_emisor: str,
    rut_envia: str,
    documentos: Sequence[dict],
    fecha_resolucion: str,
    numero_resolucion: int = 0,
    dia: Optional[date] = None,
    tipos: Sequence[int] = TIPOS_CONSUMO,
    sec_envio: int = 1,
    correlativo: Optional[int] = None,
) -> etree._Element:
    """Genera el `<ConsumoFolios>` del día (SIN firmar).

    Args:
        documentos: boletas del día (dicts con tipo_dte, folio, montos, estado).
        dia: día reportado. Si se omite, se toma de `documentos` (mín/máx de fecha).
        tipos: tipos a reportar. **Los que no tuvieron movimiento igual van, en cero** —
            por eso la lista es un parámetro y no se deduce de `documentos`.
        sec_envio: 1 la primera vez. Para CORREGIR un envío ya hecho se reenvía el archivo
            completo con `sec_envio` +1 (no se manda un diferencial).

    Raises:
        ValidacionError: si se pide un tipo que el XSD no admite en el consumo de folios.
    """
    invalidos = [t for t in tipos if t not in TIPOS_CONSUMO]
    if invalidos:
        raise ValidacionError(
            f"El consumo de folios solo admite los tipos {TIPOS_CONSUMO}; "
            f"recibido: {invalidos}.",
            detalle={"tipos_invalidos": invalidos},
        )

    if dia is None:
        if not documentos:
            raise ValidacionError(
                "Sin documentos no se puede deducir el día del consumo: pasar `dia`."
            )
        dia = date.fromisoformat(str(documentos[0]["fecha_emision"]))
    fecha = dia.isoformat()

    nsmap = {None: SII_NAMESPACE, "xsi": "http://www.w3.org/2001/XMLSchema-instance"}
    raiz = etree.Element("ConsumoFolios", nsmap=nsmap, attrib={
        "version": "1.0",
        "{http://www.w3.org/2001/XMLSchema-instance}schemaLocation": _XSD_CONSUMO})
    id_doc = f"RVD{dia.strftime('%Y%m%d')}"
    doc = etree.SubElement(raiz, "DocumentoConsumoFolios", attrib={"ID": id_doc})

    # --- Carátula (orden fijado por el XSD) ---
    car = etree.SubElement(doc, "Caratula", attrib={"version": "1.0"})
    _txt(car, "RutEmisor", rut_emisor)
    _txt(car, "RutEnvia", rut_envia)
    _txt(car, "FchResol", fecha_resolucion)
    _txt(car, "NroResol", numero_resolucion)
    _txt(car, "FchInicio", fecha)
    _txt(car, "FchFinal", fecha)
    if correlativo is not None:
        _txt(car, "Correlativo", correlativo)
    _txt(car, "SecEnvio", sec_envio)
    _txt(car, "TmstFirmaEnv", datetime.now().strftime("%Y-%m-%dT%H:%M:%S"))

    # --- Un Resumen por tipo, incluidos los que no tuvieron movimiento ---
    for tipo in tipos:
        docs = [d for d in documentos if int(d["tipo_dte"]) == tipo]
        doc.append(_resumen_por_tipo(tipo, docs))

    return raiz


def generar_rvd_firmado(
    rut_emisor: str,
    cert: CertificadoDigital,
    dia: date,
    fecha_resolucion: str,
    numero_resolucion: int = 0,
    tipos: Sequence[int] = TIPOS_CONSUMO,
    sec_envio: int = 1,
    ambiente: Optional[str] = None,
) -> bytes:
    """Genera el RVD del día desde la BD, lo firma y lo valida contra el XSD.

    Returns:
        El XML firmado en ISO-8859-1, listo para enviar (cuando se confirme la ruta REST).
    """
    documentos = boletas_del_dia(rut_emisor, dia, ambiente=ambiente)
    raiz = generar_consumo_folios(
        rut_emisor=rut_emisor,
        rut_envia=cert.rut_emisor,
        documentos=documentos,
        fecha_resolucion=fecha_resolucion,
        numero_resolucion=numero_resolucion,
        dia=dia,
        tipos=tipos,
        sec_envio=sec_envio,
    )

    # Mismo método de firma que el resto del motor: normalizar (serializar+reparsear) para
    # que los namespaces sean los finales y recién ahí firmar. Ver core/crypto.py.
    raiz = etree.fromstring(etree.tostring(raiz, encoding="ISO-8859-1"))
    id_doc = raiz.find(f".//{{{SII_NAMESPACE}}}DocumentoConsumoFolios").get("ID")
    firmado = firmar_xml_sii(raiz, cert, uri=f"#{id_doc}")

    # Declaración con comillas DOBLES (como core/sobre.py). El `xml_declaration=True` de lxml
    # la emite con comillas SIMPLES (<?xml version='1.0'...), y el DTEUpload del SII la rechaza
    # con `CHR-00001: Invalid Character Set` (verificado en vivo, 2026-07-20). No re-serializar.
    cuerpo = etree.tostring(firmado, encoding="ISO-8859-1", xml_declaration=False)
    xml = b'<?xml version="1.0" encoding="ISO-8859-1"?>\n' + cuerpo
    validar_xml_dte_strict(xml)
    return xml


def enviar_rvd(xml_rvd: bytes, rut_emisor: str, cliente: "ClienteSII") -> tuple[int, str]:
    """Envía el RVD al SII y devuelve `(track_id, mensaje)`.

    ⚠️ Va por el **canal de FACTURAS** (`DTEUpload` en maullin/palena, token SOAP de
    factura), NO por el REST de boletas — ver el docstring del módulo. Por eso recibe un
    `ClienteSII`, no un `ClienteBoletaSII`.

    Args:
        xml_rvd: el ConsumoFolios firmado (de `generar_rvd_firmado`).
        rut_emisor: RUT del emisor con DV (ej. "76111111-6").
        cliente: `core.sii.ClienteSII` ya construido con el certificado y el ambiente.
    """
    n, dv = rut_emisor.split("-")
    # `tipo_dte=33` solo enruta a DTEUpload (el guardarraíl de `enviar_dte` rechaza 39/41
    # porque las BOLETAS van por REST; el RVD, en cambio, sí va por aquí).
    return cliente.enviar_dte(xml_rvd, n, dv, tipo_dte=33)
