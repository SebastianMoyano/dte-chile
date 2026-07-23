"""
api/routes/consulta.py — Buscador PÚBLICO de consulta de boletas para el receptor.

El SII exige que la representación impresa de la boleta señale un sitio donde el cliente pueda
consultar su documento (además del obligatorio "Verifique en www.sii.cl"). Esta es esa página:
pública (sin login), self-hosted. La URL final es `https://<tu-dominio>/consulta` (o un proxy
tipo `tu-dominio.cl/misboletas/{idempresa}`) y va impresa en la boleta / declarada al SII.

Paridad con el estándar autohosteado (LibreDTE community, `DteEmitidos`: acciones públicas
`consultar`, `pdf`, `xml`): mismos 5 datos de match, más descarga pública de PDF y XML.

Seguridad: NO expone datos con solo el folio. Como el SII/LibreDTE, exige que el consultante
conozca los datos reales de SU boleta (RUT emisor + tipo + folio + fecha + **monto total**),
evitando enumeración. Solo lectura de la BD local; no toca el SII ni requiere JWT.
"""
from __future__ import annotations

import html
import re
from datetime import date
from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, Form
from fastapi.responses import HTMLResponse, JSONResponse, Response

from core.database import obtenerUno

router = APIRouter(prefix="/consulta", tags=["Consulta pública"])

# Tipos consultables (boletas). El buscador es para el receptor de boletas.
_TIPOS = {39: "Boleta Electrónica", 41: "Boleta Exenta Electrónica"}


def _norm_rut(rut: str) -> str:
    return (rut or "").replace(".", "").strip().upper()


def _buscar(rut: str, tipo: int, folio: int, monto: int, fecha: str | None):
    """Fila de la boleta si coinciden TODOS los datos (anti-enumeración), o None."""
    if tipo not in _TIPOS:
        return None
    sql = "SELECT * FROM dtes WHERE rut_emisor=? AND tipo_dte=? AND folio=? AND monto_total=?"
    params: list = [_norm_rut(rut), tipo, folio, monto]
    if fecha:
        sql += " AND fecha_emision=?"
        params.append(fecha.strip())
    return obtenerUno(sql, tuple(params))


def _qs(rut: str, tipo: int, folio, monto, fecha: str | None) -> str:
    """Query string con los 5 datos, para los links de descarga (mismo candado)."""
    d = {"rut": _norm_rut(rut), "tipo": tipo, "folio": folio, "monto": monto}
    if fecha:
        d["fecha"] = fecha
    return urlencode(d)


def _reconstruir_boleta(xml_firmado: str):
    """`(DTEInput, ted_str)` desde el XML firmado guardado, para regenerar el PDF.

    El TED se extrae **verbatim** (substring), no re-serializado: así el PDF417 conserva los
    bytes exactos que el SII firmó con la clave del CAF (re-serializarlo invalidaría el timbre).
    El resto (emisor/receptor/ítems) se parsea con lxml, que solo alimenta el layout.
    """
    from lxml import etree

    from core.dte import DTEInput, EmisorModel, ItemDTE, ReceptorModel, TipoDTE

    raiz = etree.fromstring(xml_firmado.encode("ISO-8859-1"))

    def hijo(p, tag):
        if p is None:
            return None
        for el in p:
            if etree.QName(el).localname == tag:
                return el
        return None

    def txt(p, tag, default=None):
        el = hijo(p, tag)
        return el.text if (el is not None and el.text is not None) else default

    doc = hijo(raiz, "Documento")
    enc = hijo(doc, "Encabezado")
    iddoc = hijo(enc, "IdDoc")
    em = hijo(enc, "Emisor")
    rc = hijo(enc, "Receptor")

    emisor = EmisorModel(
        rut=txt(em, "RUTEmisor") or "",
        razon_social=txt(em, "RznSocEmisor") or txt(em, "RznSoc") or "",
        giro=txt(em, "GiroEmisor") or txt(em, "GiroEmis") or "",
        codigo_actividad=int(txt(em, "Acteco") or 0),
        direccion=txt(em, "DirOrigen") or "",
        comuna=txt(em, "CmnaOrigen") or "",
        ciudad=txt(em, "CiudadOrigen") or "",
        es_receptor_boleta=True,
    )
    receptor = ReceptorModel(
        rut=txt(rc, "RUTRecep") or "66666666-6",
        razon_social=txt(rc, "RznSocRecep") or "CONSUMIDOR FINAL",
        direccion=txt(rc, "DirRecep"),
        comuna=txt(rc, "CmnaRecep"),
        ciudad=txt(rc, "CiudadRecep"),
    )

    items = []
    for det in doc:
        if etree.QName(det).localname != "Detalle":
            continue
        prc, monto_it = txt(det, "PrcItem"), txt(det, "MontoItem")
        qty = txt(det, "QtyItem")
        items.append(ItemDTE(
            numero_linea=int(txt(det, "NroLinDet") or (len(items) + 1)),
            nombre=txt(det, "NmbItem") or "",
            cantidad=float(qty) if qty else None,
            precio_unitario=float(prc) if prc else float(monto_it or 0),
            unidad_medida=txt(det, "UnmdItem"),
            exento=hijo(det, "IndExe") is not None,
        ))

    fch, ind = txt(iddoc, "FchEmis"), txt(iddoc, "IndServicio")
    dti = DTEInput(
        tipo_dte=TipoDTE(int(txt(iddoc, "TipoDTE"))),
        folio=int(txt(iddoc, "Folio") or 0),
        emisor=emisor, receptor=receptor, items=items,
        fecha_emision=date.fromisoformat(fch) if fch else None,
        indicador_servicio=int(ind) if ind else None,
    )
    m = re.search(r"<TED\b.*?</TED>", xml_firmado, re.S)
    return dti, (m.group(0) if m else None)


def _pagina(cuerpo: str, rut="", folio="", monto="", tipo=39, fecha="") -> str:
    """Envuelve el contenido en una página autocontenida, tema claro/oscuro, sin dependencias."""
    opciones = "".join(
        f'<option value="{c}"{" selected" if c == tipo else ""}>{n}</option>'
        for c, n in _TIPOS.items())
    return f"""<!doctype html><html lang="es"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Consulta de Boleta Electrónica</title>
<style>
  :root {{ --bg:#f4f5f7; --card:#fff; --fg:#1a1c1f; --mut:#5c636e; --acc:#1f6feb; --bd:#dfe3e8; }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --bg:#0f1216; --card:#181c22; --fg:#e8eaed; --mut:#9aa3ad; --acc:#4c8dff; --bd:#2a2f37; }} }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--fg); font:15px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif; }}
  .wrap {{ max-width:560px; margin:0 auto; padding:32px 20px; }}
  h1 {{ font-size:1.35rem; margin:0 0 4px; }}
  .sub {{ color:var(--mut); margin:0 0 24px; font-size:.92rem; }}
  .card {{ background:var(--card); border:1px solid var(--bd); border-radius:12px; padding:22px; }}
  label {{ display:block; font-weight:600; font-size:.82rem; margin:14px 0 5px; }}
  input,select {{ width:100%; padding:10px 12px; border:1px solid var(--bd); border-radius:8px;
    background:transparent; color:var(--fg); font-size:1rem; }}
  button {{ margin-top:20px; width:100%; padding:12px; border:0; border-radius:8px;
    background:var(--acc); color:#fff; font-size:1rem; font-weight:600; cursor:pointer; }}
  table {{ width:100%; border-collapse:collapse; margin-top:6px; }}
  td {{ padding:8px 4px; border-bottom:1px solid var(--bd); }}
  td:first-child {{ color:var(--mut); width:44%; }}
  td:last-child {{ text-align:right; font-variant-numeric:tabular-nums; }}
  .ok {{ color:#1a7f37; font-weight:600; }} .no {{ color:#b3261e; font-weight:600; }}
  .dl {{ display:flex; gap:10px; margin-top:18px; }}
  .dl a {{ flex:1; text-align:center; padding:11px; border:1px solid var(--acc); border-radius:8px;
    color:var(--acc); text-decoration:none; font-weight:600; font-size:.92rem; }}
  .foot {{ color:var(--mut); font-size:.82rem; margin-top:18px; text-align:center; }}
  .foot a {{ color:var(--acc); }}
</style></head><body><div class="wrap">
<h1>Consulta de Boleta Electrónica</h1>
<p class="sub">Ingrese los datos de su boleta para verificarla.</p>
<div class="card">
<form method="post" action="/consulta">
  <label>RUT del emisor</label>
  <input name="rut_emisor" placeholder="76111111-6" value="{html.escape(rut)}" required>
  <label>Tipo de documento</label>
  <select name="tipo_dte">{opciones}</select>
  <label>Folio</label>
  <input name="folio" inputmode="numeric" placeholder="1" value="{html.escape(str(folio))}" required>
  <label>Fecha de emisión</label>
  <input name="fecha_emision" type="date" value="{html.escape(str(fecha))}" required>
  <label>Monto total ($)</label>
  <input name="monto_total" inputmode="numeric" placeholder="29800" value="{html.escape(str(monto))}" required>
  <button type="submit">Consultar boleta</button>
</form>
{cuerpo}
</div>
<p class="foot">Verifique también la autenticidad en <a href="https://www.sii.cl" rel="noopener">www.sii.cl</a></p>
</div></body></html>"""


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def formulario() -> HTMLResponse:
    """Formulario público de consulta (GET)."""
    return HTMLResponse(_pagina(""))


@router.get("/api", response_class=JSONResponse)
async def consultar_api(rut: str, tipo: int, folio: int, monto: int,
                        fecha: str | None = None) -> JSONResponse:
    """Consulta en **JSON** — punto de integración para hospedar el buscador en otra app
    (p. ej. `tu-dominio.cl/misboletas/{idempresa}`, que llama a esto y renderiza su propia UI).

    Misma regla anti-enumeración que el HTML: exige `rut`, `tipo`, `folio`, `monto` (y `fecha`
    si se envía) y solo confirma si TODOS coinciden. `fecha` (ISO `YYYY-MM-DD`) es opcional
    pero recomendado — lo usan facturacion.cl, LibreDTE y la propia consulta del SII. Público,
    solo lectura, sin JWT.

    Respuesta: `{"encontrada": false}` o `{"encontrada": true, "documento": {...},
    "links": {"pdf": "...", "xml": "..."}}`.
    """
    if tipo not in _TIPOS:
        return JSONResponse({"encontrada": False, "error": "tipo_no_valido"}, status_code=400)
    fila = _buscar(rut, tipo, folio, monto, fecha)
    if fila is None:
        return JSONResponse({"encontrada": False})
    d = dict(fila)
    qs = _qs(rut, tipo, folio, monto, fecha)
    return JSONResponse({"encontrada": True, "documento": {
        "tipo": tipo, "tipo_nombre": _TIPOS[tipo], "folio": d["folio"],
        "rut_emisor": d["rut_emisor"], "rut_receptor": d.get("rut_receptor"),
        "fecha_emision": d["fecha_emision"], "monto_neto": d.get("monto_neto"),
        "monto_exento": d.get("monto_exento"), "iva": d.get("iva"),
        "monto_total": d["monto_total"], "track_id": d.get("track_id")},
        "links": {"pdf": f"/consulta/pdf?{qs}", "xml": f"/consulta/xml?{qs}"}})


@router.get("/xml")
async def descargar_xml(rut: str, tipo: int, folio: int, monto: int,
                        fecha: str | None = None) -> Response:
    """Descarga pública del XML firmado (mismo candado de 5 datos). Equivalente a LibreDTE `xml`."""
    fila = _buscar(rut, tipo, folio, monto, fecha)
    if fila is None or not dict(fila).get("xml_firmado"):
        return JSONResponse({"error": "no_encontrada"}, status_code=404)
    xml = dict(fila)["xml_firmado"]
    data = xml.encode("ISO-8859-1", "replace") if isinstance(xml, str) else xml
    return Response(data, media_type="application/xml", headers={
        "Content-Disposition": f'attachment; filename="boleta_{tipo}_{folio}.xml"'})


@router.get("/pdf")
async def descargar_pdf(rut: str, tipo: int, folio: int, monto: int,
                        fecha: str | None = None) -> Response:
    """Descarga pública del PDF (mismo candado). Sirve el PDF guardado o, si falta, lo
    regenera desde el XML (con el TED verbatim). Equivalente a LibreDTE `pdf`."""
    fila = _buscar(rut, tipo, folio, monto, fecha)
    if fila is None:
        return JSONResponse({"error": "no_encontrada"}, status_code=404)
    d = dict(fila)
    # 1) PDF ya guardado en disco (emisión por el orquestador).
    pp = d.get("pdf_path")
    if pp and Path(pp).exists():
        return Response(Path(pp).read_bytes(), media_type="application/pdf", headers={
            "Content-Disposition": f'inline; filename="boleta_{tipo}_{folio}.pdf"'})
    # 2) Regenerar desde el XML firmado.
    if not d.get("xml_firmado"):
        return JSONResponse({"error": "sin_xml"}, status_code=404)
    try:
        from core.pdf_gen import generar_boleta_80mm
        dti, ted = _reconstruir_boleta(d["xml_firmado"])
        pdf = generar_boleta_80mm(dti, ted_xml=ted)
    except Exception as e:  # noqa: BLE001 — degradar a XML si el PDF no se puede armar
        return JSONResponse({"error": "pdf_no_disponible", "detalle": str(e)}, status_code=500)
    return Response(pdf, media_type="application/pdf", headers={
        "Content-Disposition": f'inline; filename="boleta_{tipo}_{folio}.pdf"'})


@router.post("", response_class=HTMLResponse)
@router.post("/", response_class=HTMLResponse)
async def consultar(
    rut_emisor: str = Form(...),
    tipo_dte: int = Form(...),
    folio: str = Form(...),
    monto_total: str = Form(...),
    fecha_emision: str = Form(""),
) -> HTMLResponse:
    """Verifica una boleta contra la BD local. Exige que los datos coincidan (evita enumeración)."""
    fch = (fecha_emision or "").strip()
    try:
        folio_i = int(str(folio).strip())
        monto_i = int(str(monto_total).replace(".", "").replace("$", "").strip())
    except ValueError:
        return HTMLResponse(_pagina(
            '<p class="no" style="margin-top:16px">Folio y monto deben ser números.</p>',
            rut=rut_emisor, folio=folio, monto=monto_total, tipo=tipo_dte, fecha=fch))

    if tipo_dte not in _TIPOS:
        return HTMLResponse(_pagina(
            '<p class="no" style="margin-top:16px">Tipo de documento no válido.</p>',
            rut=rut_emisor, folio=folio, monto=monto_total, fecha=fch))

    fila = _buscar(rut_emisor, tipo_dte, folio_i, monto_i, fch)
    if fila is None:
        cuerpo = ('<p class="no" style="margin-top:16px">No se encontró una boleta con esos '
                  'datos. Verifique el RUT, tipo, folio, fecha y monto.</p>')
        return HTMLResponse(_pagina(cuerpo, rut=rut_emisor, folio=folio,
                                    monto=monto_total, tipo=tipo_dte, fecha=fch))

    d = dict(fila)
    def _money(v): return "$" + f"{int(v or 0):,}".replace(",", ".")
    filas = [
        ("Documento", f"{_TIPOS[tipo_dte]} N° {d['folio']}"),
        ("RUT emisor", d["rut_emisor"]),
        ("RUT receptor", d.get("rut_receptor") or "—"),
        ("Fecha de emisión", d["fecha_emision"]),
        ("Monto neto", _money(d.get("monto_neto"))),
        ("Monto exento", _money(d.get("monto_exento"))),
        ("IVA", _money(d.get("iva"))),
        ("Monto total", _money(d["monto_total"])),
    ]
    tabla = "".join(f"<tr><td>{html.escape(k)}</td><td>{html.escape(str(v))}</td></tr>"
                    for k, v in filas)
    qs = _qs(rut_emisor, tipo_dte, folio_i, monto_i, fch)
    descargas = (f'<div class="dl"><a href="/consulta/pdf?{qs}">Descargar PDF</a>'
                 f'<a href="/consulta/xml?{qs}">Descargar XML</a></div>')
    cuerpo = (f'<p class="ok" style="margin-top:18px">✓ Boleta encontrada y válida.</p>'
              f'<table>{tabla}</table>{descargas}')
    return HTMLResponse(_pagina(cuerpo, rut=rut_emisor, folio=folio,
                                monto=monto_total, tipo=tipo_dte, fecha=fch))
