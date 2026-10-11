#!/usr/bin/env python3
"""
tools/generar_xsd_vectores.py — Vectores de paridad para nucleo/xsd (validación XSD en Go).

Toma los sobres del corpus dorado (datos ficticios, L14), un ConsumoFolios firmado con el
certificado demo y dos DTE sueltos, y les aplica mutaciones deterministas (semilla fija):
estructurales (borrar, duplicar, reordenar, renombrar, mover, texto en elementos complejos),
de atributos (valor fijo distinto, borrado, extra, xsi:*), de valores simples (vacío, blancos,
largo, signo, decimales, fechas inválidas, base64 roto…) y de documento (codificaciones, BOM,
mal formado, entidades, raíces distintas). Para cada uno guarda el veredicto de lxml
(core/schema_validator.py): valido, tipo_xml, cantidad de errores y el elemento del primer error.

El test Go (TestParidadConLxml) exige el mismo veredicto, tipo y elemento. L15: los vectores
no se regeneran para que un test pase; se regeneran solo si cambia el corpus o este generador.

Uso:  .venv/bin/python tools/generar_xsd_vectores.py   → nucleo/xsd/testdata/vectores.json.gz
"""
from __future__ import annotations

import base64
import copy
import gzip
import json
import pathlib
import random
import re
import sys
from datetime import date

RAIZ = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from lxml import etree  # noqa: E402

from core.crypto import CertificadoDigital, firmar_xml_sii  # noqa: E402
from core.rvd import generar_consumo_folios  # noqa: E402
from core.schema_validator import validar_xml_dte  # noqa: E402

SALIDA = RAIZ / "nucleo" / "xsd" / "testdata" / "vectores.json.gz"
CORPUS = RAIZ / "tests" / "dorado" / "esperado"
NS = "http://www.sii.cl/SiiDte"
XSI = "http://www.w3.org/2001/XMLSchema-instance"
DECL = b'<?xml version="1.0" encoding="ISO-8859-1"?>\n'

# Bases con el juego completo de mutaciones (las demás solo aportan su vector "base").
COMPLETAS = {"02_factura_reunion", "04_nc_anula_boleta", "07_guia_despacho", "12_boleta_mixta_ind_servicio",
             "13_sobre_tres_dte", "14_sobre_dos_boletas", "consumo_folios"}

RE_ELEMENTO = re.compile(r"Element '(?:\{[^}]*\})?([^']+)'")


def veredicto(nombre: str, base: str, xml: bytes) -> dict:
    v = {"nombre": nombre, "base": base, "xml_b64": base64.b64encode(xml).decode("ascii")}
    try:
        r = validar_xml_dte(xml)
    except Exception as e:  # p. ej. DOCTYPE con entidades → "Internal error" de libxml2
        v.update(valido=False, tipo_xml="", n_errores=0, primer_elemento="", primer_error=f"{type(e).__name__}: {e}", excepcion=True)
        return v
    primero = r.errores[0] if r.errores else ""
    m = RE_ELEMENTO.search(primero) if not primero.startswith("Error de sintaxis") else None
    v.update(valido=r.valido, tipo_xml=r.tipo_xml, n_errores=len(r.errores), primer_elemento=m.group(1) if m else "",
             primer_error=primero[:300], excepcion=False)
    return v


def serializar(raiz) -> bytes:
    return etree.tostring(raiz, encoding="ISO-8859-1", xml_declaration=True)


def local(el) -> str:
    return etree.QName(el).localname


def ruta(el) -> str:
    partes = []
    while el is not None and el.getparent() is not None:
        p = el.getparent()
        idx = [h for h in p if isinstance(h.tag, str) and h.tag == el.tag].index(el)
        partes.append(f"{local(el)}[{idx}]")
        el = p
    return "/".join(reversed(partes))


# ---- mutaciones estructurales (sobre una copia del árbol) ----

def mut_elementos(arbol, el):
    """Genera (sufijo, árbol mutado) para un elemento (dado por su ruta)."""
    r = ruta(el)

    def copia():
        t = copy.deepcopy(arbol)
        e = t
        for paso in (r.split("/") if r else []):
            nombre, idx = paso[:-1].split("[")
            e = [h for h in e if isinstance(h.tag, str) and local(h) == nombre][int(idx)]
        return t, e

    t, e = copia(); e.getparent().remove(e); yield "borrar", t
    t, e = copia(); p = e.getparent(); p.insert(p.index(e) + 1, copy.deepcopy(e)); yield "duplicar", t
    t, e = copia(); e.tag = e.tag + "X"; yield "renombrar", t
    t, e = copia(); p = e.getparent(); p.remove(e); p.append(e); yield "mover_al_final", t
    t, e = copia(); p = e.getparent(); i = p.index(e)
    if i + 1 < len(p):
        p.remove(e); p.insert(i + 1, e); yield "intercambiar_siguiente", t
    elif i > 0:
        p.remove(e); p.insert(i - 1, e); yield "intercambiar_anterior", t
    t, e = copia(); p = e.getparent(); x = etree.Element(f"{{{NS}}}Extra"); x.text = "1"; p.insert(p.index(e), x); yield "desconocido_antes", t
    t, e = copia(); p = e.getparent(); p.text = (p.text or "") + "texto"; yield "texto_en_padre", t
    t, e = copia()
    otros = [o for o in t.iter() if isinstance(o.tag, str) and len(o) and o is not e and e not in list(o.iterancestors())]
    if otros:
        d = random.Random(r).choice(otros); e.getparent().remove(e); d.append(e); yield "mover_a_" + local(d), t


def mut_atributos(arbol, el):
    r = ruta(el)

    def copia():
        t = copy.deepcopy(arbol)
        e = t
        for paso in (r.split("/") if r else []):
            nombre, idx = paso[:-1].split("[")
            e = [h for h in e if isinstance(h.tag, str) and local(h) == nombre][int(idx)]
        return t, e

    for k in list(el.attrib):
        if k.startswith("{"):
            continue
        for sufijo, nuevo in (("1.00", "1.00"), ("x", "x"), ("blanco", " " + el.attrib[k]), ("vacio", "")):
            t, e = copia(); e.set(k, nuevo); yield f"attr_{k}_{sufijo}", t
        t, e = copia(); del e.attrib[k]; yield f"attr_{k}_borrado", t
    t, e = copia(); e.set("extra", "1"); yield "attr_extra", t
    t, e = copia(); e.set(f"{{{XSI}}}nil", "true"); yield "attr_xsi_nil", t
    t, e = copia(); e.set(f"{{{NS}}}version", "1.0"); yield "attr_con_ns", t


VALORES = [
    ("vacio", lambda v: ""), ("blancos", lambda v: f"  {v}  "), ("sufijo_X", lambda v: v + "X"), ("negativo", lambda v: "-" + v),
    ("decimal_5", lambda v: v + ".5"), ("x5", lambda v: v * 5), ("enie_41", lambda v: "ñ" * 41), ("enie_101", lambda v: "ñ" * 101),
    ("K", lambda v: "K"), ("fecha_30feb", lambda v: "2026-02-30"), ("fecha_bisiesta", lambda v: "2024-02-29"), ("1e2", lambda v: "1e2"),
    ("mas", lambda v: "+" + v), ("cero_delante", lambda v: "0" + v), ("salto", lambda v: v + "\n"), ("rut_K", lambda v: "12345678-K"),
    ("cero", lambda v: "0"), ("abc", lambda v: "abc"), ("fechahora", lambda v: "2026-01-01T10:00:00"), ("b64_malo", lambda v: "ab=="),
    ("19_001", lambda v: "19.001"), ("20_digitos", lambda v: "99999999999999999999"), ("fecha_1999", lambda v: "1999-12-31"),
    ("fecha_Z", lambda v: "2026-01-01Z"), ("hora_24", lambda v: "2026-01-01T24:00:00"), ("interno", lambda v: v[:1] + " " + v[1:] if len(v) > 1 else v + " 1"),
]


def mut_valores(arbol, el, rnd):
    r = ruta(el)
    ops = rnd.sample(VALORES, 3)
    for nombre, fn in ops:
        t = copy.deepcopy(arbol)
        e = t
        for paso in (r.split("/") if r else []):
            n, idx = paso[:-1].split("[")
            e = [h for h in e if isinstance(h.tag, str) and local(h) == n][int(idx)]
        e.text = fn(e.text or "")
        yield f"valor_{local(el)}_{nombre}", t


def mut_documento(xml: bytes):
    yield "sin_declaracion", xml.replace(DECL.strip(), b"", 1)
    yield "declaracion_utf8_bytes_latin1", xml.replace(b'encoding="ISO-8859-1"', b'encoding="UTF-8"', 1)
    yield "utf8_real", xml.replace(b'encoding="ISO-8859-1"', b'encoding="UTF-8"', 1).decode("latin-1").encode("utf-8")
    yield "bom_utf8", b"\xef\xbb\xbf" + xml.replace(b'encoding="ISO-8859-1"', b'encoding="UTF-8"', 1).decode("latin-1").encode("utf-8")
    yield "utf16", xml.replace(b'encoding="ISO-8859-1"', b'encoding="UTF-16"', 1).decode("latin-1").encode("utf-16")
    yield "windows1252", xml.replace(b'encoding="ISO-8859-1"', b'encoding="windows-1252"', 1)
    yield "truncado", xml[: len(xml) * 2 // 3]
    yield "entidad_indefinida", re.sub(rb"<NroResol>(\d+)", rb"<NroResol>&x;\1", xml, count=1)
    yield "entidad_numerica", re.sub(rb"<NroResol>(\d)", rb"<NroResol>&#4\1;", xml, count=1)
    yield "texto_fuera_raiz", xml + b"x"
    yield "dos_raices", xml + b"<a/>"
    yield "blanco_tras_raiz", xml + b"\n\n  \n"
    yield "comentario_y_pi", xml.replace(b"<NroResol>", b"<!-- c --><?pi x?><NroResol>", 1)
    yield "cdata_en_numero", re.sub(rb"<NroResol>(\d+)<", rb"<NroResol><![CDATA[\1]]><", xml, count=1)
    yield "doctype_simple", xml.replace(b"?>", b"?><!DOCTYPE raiz>", 1)
    yield "doctype_entidad", xml.replace(b"?>", b'?><!DOCTYPE raiz [<!ENTITY x "0">]>', 1).replace(b"<NroResol>", b"<NroResol>&x;", 1)
    yield "vacio", b""
    yield "solo_blanco", b"  \n "
    raiz = re.search(rb"<(\w+) xmlns=", xml).group(1)
    yield "raiz_renombrada", xml.replace(b"<" + raiz + b" ", b"<Envio ", 1).replace(b"</" + raiz + b">", b"</Envio>")
    yield "raiz_sin_ns", xml.replace(b"<" + raiz + b' xmlns="http://www.sii.cl/SiiDte"', b"<" + raiz, 1)
    yield "raiz_prefijada", (xml.replace(b"<" + raiz + b' xmlns="http://www.sii.cl/SiiDte"', b"<s:" + raiz + b' xmlns:s="http://www.sii.cl/SiiDte"', 1)
                             .replace(b"</" + raiz + b">", b"</s:" + raiz + b">"))
    otra = {b"EnvioDTE": b"EnvioBOLETA", b"EnvioBOLETA": b"EnvioDTE", b"ConsumoFolios": b"EnvioDTE"}[raiz]
    yield "raiz_" + otra.decode(), xml.replace(b"<" + raiz + b" ", b"<" + otra + b" ", 1).replace(b"</" + raiz + b">", b"</" + otra + b">")
    m = re.search(rb"<Signature xmlns=.*?</Signature>", xml, re.S)
    if m:
        yield "raiz_Signature", DECL + m.group(0)
    m = re.search(rb"<DTE xmlns=.*?</DTE>", xml, re.S)
    if m:
        yield "raiz_DTE", DECL + m.group(0)
        yield "raiz_DTE_sin_declaracion", m.group(0)


def consumo_folios_firmado() -> bytes:
    cert = CertificadoDigital((RAIZ / "tests" / "dorado" / "fixtures" / "cert_demo.p12").read_bytes(), "demo")
    docs = [
        {"tipo_dte": 39, "folio": 1, "monto_neto": 1000, "iva": 190, "monto_exento": 0, "monto_total": 1190, "estado": "aceptado", "fecha_emision": "2026-01-23"},
        {"tipo_dte": 39, "folio": 2, "monto_neto": 2000, "iva": 380, "monto_exento": 0, "monto_total": 2380, "estado": "aceptado", "fecha_emision": "2026-01-23"},
        {"tipo_dte": 39, "folio": 3, "monto_neto": 0, "iva": 0, "monto_exento": 0, "monto_total": 0, "estado": "anulado", "fecha_emision": "2026-01-23"},
        {"tipo_dte": 41, "folio": 1, "monto_neto": 0, "iva": 0, "monto_exento": 5000, "monto_total": 5000, "estado": "aceptado", "fecha_emision": "2026-01-23"},
    ]
    raiz = generar_consumo_folios(rut_emisor="77777777-7", rut_envia="12345678-5", documentos=docs, fecha_resolucion="2026-01-01",
                                  numero_resolucion=0, dia=date(2026, 1, 23), tipos=(39, 41, 61), sec_envio=1)
    raiz = etree.fromstring(etree.tostring(raiz, encoding="ISO-8859-1"))
    id_doc = raiz.find(f".//{{{NS}}}DocumentoConsumoFolios").get("ID")
    firmado = firmar_xml_sii(raiz, cert, uri=f"#{id_doc}")
    return DECL + etree.tostring(firmado, encoding="ISO-8859-1", xml_declaration=False)


def main():
    bases: dict[str, bytes] = {}
    for carpeta in sorted(CORPUS.iterdir()):
        if (carpeta / "envio.xml").exists():
            bases[carpeta.name] = (carpeta / "envio.xml").read_bytes()
    bases["consumo_folios"] = consumo_folios_firmado()

    vectores = []
    for nombre, xml in bases.items():
        vectores.append(veredicto("base", nombre, xml))
        if nombre not in COMPLETAS:
            continue
        rnd = random.Random(nombre)
        arbol = etree.fromstring(xml)
        elementos = [e for e in arbol.iter() if isinstance(e.tag, str) and e.getparent() is not None]
        hojas = [e for e in elementos if len(e) == 0 and (e.text or "").strip()]
        con_attrs = [e for e in elementos if any(not k.startswith("{") for k in e.attrib)] + [arbol]
        for e in rnd.sample(elementos, min(5, len(elementos))):
            for sufijo, t in mut_elementos(arbol, e):
                vectores.append(veredicto(f"{local(e)}_{sufijo}", nombre, serializar(t)))
        for e in rnd.sample(con_attrs, min(4, len(con_attrs))):
            for sufijo, t in mut_atributos(arbol, e):
                vectores.append(veredicto(f"{local(e)}_{sufijo}", nombre, serializar(t)))
        for e in rnd.sample(hojas, min(18, len(hojas))):
            for sufijo, t in mut_valores(arbol, e, rnd):
                vectores.append(veredicto(sufijo, nombre, serializar(t)))
        for sufijo, x in mut_documento(xml):
            vectores.append(veredicto("doc_" + sufijo, nombre, x))

    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    datos = json.dumps(vectores, ensure_ascii=False, indent=0).encode("utf-8")
    with gzip.open(SALIDA, "wb", compresslevel=9) as f:
        f.write(datos)
    validos = sum(1 for v in vectores if v["valido"])
    print(f"{len(vectores)} vectores ({validos} válidos, {sum(1 for v in vectores if v['excepcion'])} excepciones) → {SALIDA} "
          f"({SALIDA.stat().st_size // 1024} KB gz, {len(datos) // 1024} KB json)")


if __name__ == "__main__":
    main()
