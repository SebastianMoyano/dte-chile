"""
tools/contrato_api.py — Contrato dorado de la API: el motor Go debe responder lo mismo que el
motor Python (fase 7 del port). Pide cada paso a los dos motores y compara status, `codigo` de
error y el JSON completo (ignorando campos volátiles).

Uso (los dos motores corriendo, con el MISMO APP_SHELL_KEY en el entorno de ambos):
  APP_SHELL_KEY=… .venv/bin/python tools/contrato_api.py --python http://127.0.0.1:8771 --go http://127.0.0.1:8010
  … --escenario valores|auth|apikeys|simulacion|xsd|emitir|rutas|portal|consulta|keystore|todos   (default: todos)
  … --token <jwt o api key>                            (si no, APP_SHELL_KEY del entorno)
  … --sin-auth                                         (además, cada GET sin token → 401)

Un paso es (método, ruta, cuerpo, ignorar, guarda). `{motor}` en ruta/cuerpo se reemplaza por
"py"/"go" (cada motor crea sus propios recursos en la MISMA base); `guarda="id"` captura ese
campo de la respuesta para usarlo como `{id}` en pasos siguientes (por motor). `archivo=`
manda multipart. Sale 0 si todo coincide; 1 si hay diferencias (se listan).
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import pathlib
import sys
import urllib.error
import urllib.request
import uuid

IGNORAR_SIEMPRE = {"request_id", "actualizado", "creado", "creado_en", "ultimo_acceso", "ultimo_uso", "actualizado_en"}
RAIZ = pathlib.Path(__file__).resolve().parent.parent
CERT_DEMO = RAIZ / "tests" / "dorado" / "fixtures" / "cert_demo.p12"
SOBRE_FACTURA = RAIZ / "tests" / "dorado" / "esperado" / "02_factura_reunion" / "envio.xml"
CAF_DEMO_33 = RAIZ / "tests" / "dorado" / "fixtures" / "caf_33.xml"
SOBRE_BOLETAS = RAIZ / "tests" / "dorado" / "esperado" / "14_sobre_dos_boletas" / "envio.xml"


def b64(datos: bytes) -> str:
    import base64
    return base64.b64encode(datos).decode("ascii")


CERT_DEMO_B64 = b64(CERT_DEMO.read_bytes()) if CERT_DEMO.exists() else ""
EMISOR_DEMO = {"rut": "77777777-7", "razon_social": "EMPRESA DEMO SPA", "giro": "Cafetería", "codigo_actividad": 561000,
               "direccion": "Calle Ficticia 123", "comuna": "Santiago", "ciudad": "Santiago", "email": "hola@empresademo.cl"}
CLIENTE_DEMO = {"rut": "76111111-6", "razon_social": "CLIENTE DEMO SPA", "giro": "Oficina", "direccion": "Avenida Imaginaria 456",
                "comuna": "Providencia", "ciudad": "Santiago"}


def dte_demo(tipo, items, receptor=None, folio=0, emisor=None, **extra):
    """Un DTEInput de EMPRESA DEMO SPA (el emisor de la práctica, con CAF demo en la base)."""
    if receptor is None:
        receptor = {"rut": "66666666-6", "razon_social": "CONSUMIDOR FINAL"} if tipo in (39, 41) else CLIENTE_DEMO
    items = [dict(it, numero_linea=i + 1) for i, it in enumerate(items)]
    d = {"tipo_dte": tipo, "folio": folio, "fecha_emision": "2026-01-15", "emisor": emisor or EMISOR_DEMO, "receptor": receptor, "items": items}
    d.update(extra)
    return d


IGNORAR_EMISION = {"dte_id", "folio", "xml_dte_path", "pdf_path", "xml_envio_path", "xml_envio_b64", "mensaje"}


def sobre(ruta, reemplazo=None) -> str:
    datos = ruta.read_bytes()
    if reemplazo:
        datos = datos.replace(reemplazo[0], reemplazo[1], 1)
    return b64(datos)


def paso(metodo, ruta, cuerpo=None, ignorar=(), guarda=None, archivo=None, solo=None, espera=None, archivo_campo="archivo", archivos_extra=None, multipart=False):
    """guarda: campo de la respuesta → variable del mismo nombre; "access_token" se usa como Bearer en los pasos
    siguientes del escenario. solo="py"|"go": el paso corre en un solo motor (preparación), sin comparar;
    espera: status exigido en ese caso."""
    return {"metodo": metodo, "ruta": ruta, "cuerpo": cuerpo, "ignorar": set(ignorar), "guarda": guarda, "archivo": archivo, "solo": solo, "espera": espera,
            "archivo_campo": archivo_campo, "archivos_extra": archivos_extra or {}, "multipart": multipart}


ESCENARIOS = {
    "valores": [paso("GET", r) for r in [
        "/", "/api/v1/valores", "/api/v1/valores?fecha=2026-10-01", "/api/v1/valores?fecha=2026-09-14", "/api/v1/valores?fecha=no-es-fecha",
        "/api/v1/valores/uf", "/api/v1/valores/utm?fecha=2026-09-15", "/api/v1/valores/dolar?fecha=2026-10-05", "/api/v1/valores/xx",
        "/api/v1/valores/uf?fecha=1990-01-01", "/api/v1/valores/historico?anio=2026", "/api/v1/valores/historico?anio=2015",
        "/api/v1/valores/historico?anio=1999", "/api/v1/valores/historico", "/api/v1/valores/uf/serie?desde=2026-09-01&hasta=2026-09-10",
        "/api/v1/valores/utm/serie?desde=2026-01-01&hasta=2026-12-31", "/api/v1/valores/uf/serie",
        "/api/v1/keystore/negocios", "/api/v1/dte/documentos?limite=3"]],
    "auth": [
        paso("POST", "/api/v1/auth/registro", {"username": "contrato_{motor}", "password": "clave-contrato-1", "nombre_completo": "Contrato {motor}"}, ignorar={"id", "username", "mensaje"}, guarda="id"),
        paso("POST", "/api/v1/auth/registro", {"username": "contrato_{motor}", "password": "clave-contrato-1"}),
        paso("POST", "/api/v1/auth/registro", {"username": "ab", "password": "123"}),
        paso("POST", "/api/v1/auth/registro", {"username": "sin_clave"}),
        paso("POST", "/api/v1/auth/login", {"username": "contrato_{motor}", "password": "clave-contrato-1"}, ignorar={"access_token", "username", "nombre_completo"}),
        paso("POST", "/api/v1/auth/login", {"username": "contrato_{motor}", "password": "incorrecta"}),
        paso("POST", "/api/v1/auth/login", {"username": "nadie_{motor}", "password": "x"}),
        paso("POST", "/api/v1/auth/login", {"username": "solo"}),
        # cruzados: cada motor verifica el hash que generó el OTRO (passlib ↔ Go)
        paso("POST", "/api/v1/auth/login", {"username": "contrato_py", "password": "clave-contrato-1"}, ignorar={"access_token"}),
        paso("POST", "/api/v1/auth/login", {"username": "contrato_go", "password": "clave-contrato-1"}, ignorar={"access_token"}),
        paso("GET", "/api/v1/auth/me"),
        paso("GET", "/api/v1/auth/usuarios", ignorar={"id", "username", "nombre_completo", "email"}),
        paso("DELETE", "/api/v1/auth/usuarios/{id}", ignorar={"mensaje"}),
        paso("DELETE", "/api/v1/auth/usuarios/abc"),
    ],
    "apikeys": [
        # las keys se gestionan SOLO con un JWT de usuario (no con la clave de la app ni con otra key)
        paso("POST", "/api/v1/apikeys", {"nombre": "con-clave-de-app"}),
        paso("POST", "/api/v1/auth/registro", {"username": "apikeys_{motor}", "password": "clave-contrato-1"}, ignorar={"id", "username", "mensaje"}, guarda="id:usuario_id"),
        paso("POST", "/api/v1/auth/login", {"username": "apikeys_{motor}", "password": "clave-contrato-1"}, ignorar={"access_token", "username"}, guarda="access_token"),
        paso("POST", "/api/v1/apikeys", {"nombre": "contrato-{motor}"}, ignorar={"api_key", "id", "prefijo", "nombre"}, guarda="id"),
        paso("POST", "/api/v1/apikeys", {"nombre": ""}),
        paso("POST", "/api/v1/apikeys", {}),
        paso("GET", "/api/v1/apikeys", ignorar={"id", "nombre", "prefijo", "activo"}),
        paso("DELETE", "/api/v1/apikeys/{id}", ignorar={"revocada"}),
        paso("DELETE", "/api/v1/apikeys/{id}", ignorar={"revocada"}),
        paso("DELETE", "/api/v1/apikeys/999999"),
        paso("DELETE", "/api/v1/auth/usuarios/{usuario_id}", ignorar={"mensaje"}),
    ],
    # solo lectura sobre la base real: el PEM del certificado y la resolución deben ser byte a byte iguales
    "contexto": [paso("GET", f"/api/v1/keystore/negocios/{i}/contexto-emision") for i in (1, 2, 3, 999999)],
    # práctica: cada motor emite con el mismo CAF demo (folios distintos) → se ignora lo que depende del folio/id
    "simulacion": [
        paso("POST", "/api/v1/simulacion/reiniciar", {}, ignorar={"documentos_borrados", "cafs_borrados"}),
        paso("GET", "/api/v1/simulacion/estado", ignorar={"documentos", "folios"}),
        paso("POST", "/api/v1/simulacion/emitir", {"tipo_dte": 39, "items": [{"nombre": "Café", "precio_unitario": 1190}]}, ignorar={"dte_id", "folio", "pdf_path", "pdf_b64"}, guarda="dte_id"),
        paso("POST", "/api/v1/simulacion/emitir", {"tipo_dte": 33, "items": [{"nombre": "Servicio", "precio_unitario": 20000, "cantidad": 2}], "receptor": {"rut": "76111111-6", "razon_social": "CLIENTE DEMO SPA"}}, ignorar={"dte_id", "folio", "pdf_path", "pdf_b64"}, guarda="dte_id:factura_id"),
        paso("POST", "/api/v1/simulacion/emitir", {"tipo_dte": 34, "items": [{"nombre": "Arriendo", "precio_unitario": 100000}]}, ignorar={"dte_id", "folio", "pdf_path", "pdf_b64"}),
        paso("POST", "/api/v1/simulacion/emitir", {"tipo_dte": 52, "items": [{"nombre": "x", "precio_unitario": 1}]}),
        paso("POST", "/api/v1/simulacion/emitir", {"tipo_dte": 39, "items": []}),
        paso("POST", "/api/v1/simulacion/emitir", {"tipo_dte": 39}),
        paso("GET", "/api/v1/simulacion/documentos/{dte_id}", ignorar={"dte_id", "folio", "pdf_path", "pdf_b64"}),
        paso("POST", "/api/v1/dte/documentos/{dte_id}/pdf", {}, ignorar={"dte_id", "pdf_path"}),
        paso("POST", "/api/v1/dte/documentos/999999/pdf", {}),
        paso("GET", "/api/v1/dte/documentos/{dte_id}/pdf", ignorar={"*"}),
        paso("GET", "/api/v1/simulacion/documentos/999999"),
        paso("POST", "/api/v1/simulacion/anular/{factura_id}", {"motivo": "Prueba del contrato"}, ignorar={"dte_id", "folio", "pdf_path", "pdf_b64"}),
        paso("POST", "/api/v1/simulacion/anular/{factura_id}"),
        paso("POST", "/api/v1/simulacion/anular/999999"),
        paso("GET", "/api/v1/simulacion/estado", ignorar={"documentos", "folios"}),
        paso("GET", "/api/v1/dte/documentos?rut_emisor=77777777-7&limite=3", ignorar={"id", "folio", "pdf_path", "total", "documentos"}),
        paso("GET", "/api/v1/dte/documentos/{dte_id}/xml", ignorar={"*"}),
        paso("GET", "/api/v1/dte/documentos/999999/pdf"),
        paso("GET", "/api/v1/dte/documentos/emisores", ignorar={"documentos", "ultimo"}),
        paso("GET", "/api/v1/dte/emisor"),
        paso("GET", "/api/v1/dte/documentos?limite=abc"),
    ],
    # XSD: mismo veredicto y tipo; los textos de los errores son de cada validador (lxml / nucleo/xsd)
    "xsd": [
        paso("POST", "/api/v1/dte/validar-xml", {"xml_b64": sobre(SOBRE_FACTURA)}),
        paso("POST", "/api/v1/dte/validar-xml", {"xml_b64": sobre(SOBRE_BOLETAS)}),
        paso("POST", "/api/v1/dte/validar-xml", {"xml_b64": sobre(SOBRE_FACTURA, (b"<RutEmisor>77777777-7", b"<RutEmisor>77777777-X"))}, ignorar={"errores", "mensaje"}),
        paso("POST", "/api/v1/dte/validar-xml", {"xml_b64": sobre(SOBRE_BOLETAS, (b"<TpoDTE>39", b"<TpoDTE>33"))}, ignorar={"errores", "mensaje"}),
        paso("POST", "/api/v1/dte/validar-xml", {"xml_b64": sobre(SOBRE_FACTURA, (b"</EnvioDTE>", b""))}, ignorar={"errores", "mensaje"}),
        paso("POST", "/api/v1/dte/validar-xml", {"xml_b64": b64(b"<Otro/>")}, ignorar={"errores", "mensaje"}),
        paso("POST", "/api/v1/dte/validar-xml", {"xml_b64": "no-es-base64!!"}, ignorar={"mensaje"}),
        paso("POST", "/api/v1/dte/validar-xml", {}),
    ],
    # motor propio: emitir (folio → TED → firma → sobre → XSD → disco → BD → PDF), previsualizar, enviar, estado.
    # Cada motor consume su propio folio del CAF demo → se ignora lo que depende del folio. Enviar/estado con
    # el certificado ficticio: el SII no lo conoce → 502 en los dos (el texto del error es de cada cliente).
    "emitir": [
        paso("POST", "/api/v1/simulacion/reiniciar", {}, ignorar={"documentos_borrados", "cafs_borrados"}),
        paso("POST", "/api/v1/dte/emitir", {"dte": dte_demo(33, [{"nombre": "Café para reunión", "cantidad": 1, "precio_unitario": 20000}]),
                                            "certificado_p12_b64": CERT_DEMO_B64, "password_certificado": "demo"}, ignorar=IGNORAR_EMISION),
        paso("POST", "/api/v1/dte/emitir", {"dte": dte_demo(34, [{"nombre": "Taller", "cantidad": 2, "precio_unitario": 15000, "exento": True}]),
                                            "certificado_p12_b64": CERT_DEMO_B64, "password_certificado": "demo"}, ignorar=IGNORAR_EMISION),
        paso("POST", "/api/v1/dte/emitir", {"dte": dte_demo(39, [{"nombre": "Café", "cantidad": 1, "precio_unitario": 1190}]),
                                            "certificado_p12_b64": CERT_DEMO_B64, "password_certificado": "demo"}, ignorar=IGNORAR_EMISION),
        paso("POST", "/api/v1/dte/emitir", {"dte": dte_demo(33, [{"nombre": "x", "precio_unitario": 1000}], emisor=dict(EMISOR_DEMO, rut="76111111-6")),
                                            "certificado_p12_b64": CERT_DEMO_B64, "password_certificado": "demo"}),
        paso("POST", "/api/v1/dte/emitir", {"dte": dte_demo(33, [{"nombre": "x", "precio_unitario": 1000}])}),
        paso("POST", "/api/v1/dte/emitir", {"dte": dte_demo(33, [{"nombre": "x", "precio_unitario": 1000}]), "certificado_p12_b64": "no-es-b64!!", "password_certificado": "demo"}, ignorar={"mensaje"}),
        paso("POST", "/api/v1/dte/emitir", {"dte": dte_demo(33, [{"nombre": "x", "precio_unitario": 1000}]), "certificado_p12_b64": CERT_DEMO_B64, "password_certificado": "mala"}, ignorar={"mensaje"}),
        paso("POST", "/api/v1/dte/emitir", {"dte": dte_demo(99, [{"nombre": "x", "precio_unitario": 1000}]), "certificado_p12_b64": CERT_DEMO_B64, "password_certificado": "demo"}, ignorar={"detalle"}),
        paso("POST", "/api/v1/dte/emitir", {}),
        # previsualizar usa el certificado del keystore (fila única por cuenta+RUT): cada motor por turnos
        paso("POST", "/api/v1/keystore/certificados", {"password": "demo", "nombre": "demo py"}, archivo=str(CERT_DEMO), solo="py", espera=201, guarda="id"),
        paso("POST", "/api/v1/dte/previsualizar", {"dte": dte_demo(33, [{"nombre": "Café", "cantidad": 1, "precio_unitario": 20000}]), "cert_id": "{id}"}, solo="py", espera=200),
        paso("DELETE", "/api/v1/keystore/certificados/{id}", solo="py", espera=200),
        paso("POST", "/api/v1/keystore/certificados", {"password": "demo", "nombre": "demo go"}, archivo=str(CERT_DEMO), solo="go", espera=201, guarda="id"),
        paso("POST", "/api/v1/dte/previsualizar", {"dte": dte_demo(33, [{"nombre": "Café", "cantidad": 1, "precio_unitario": 20000}]), "cert_id": "{id}"}, solo="go", espera=200),
        paso("DELETE", "/api/v1/keystore/certificados/{id}", solo="go", espera=200),
        paso("POST", "/api/v1/dte/previsualizar", {"dte": dte_demo(33, [{"nombre": "x", "precio_unitario": 1}]), "cert_id": 999999}),
        paso("POST", "/api/v1/dte/previsualizar", {"dte": dte_demo(33, [{"nombre": "x", "precio_unitario": 1}])}),
        paso("POST", "/api/v1/dte/enviar", {"xml_envio_b64": sobre(SOBRE_FACTURA), "certificado_p12_b64": CERT_DEMO_B64, "password_certificado": "demo",
                                            "rut_empresa": "77777777", "dv_empresa": "7", "tipo_dte": 39}),
        paso("POST", "/api/v1/dte/enviar", {"xml_envio_b64": sobre(SOBRE_FACTURA, (b"<RutEmisor>77777777-7", b"<RutEmisor>77777777-X")), "certificado_p12_b64": CERT_DEMO_B64,
                                            "password_certificado": "demo", "rut_empresa": "77777777", "dv_empresa": "7"}, ignorar={"mensaje"}),
        paso("POST", "/api/v1/dte/enviar", {"xml_envio_b64": sobre(SOBRE_FACTURA), "certificado_p12_b64": CERT_DEMO_B64, "password_certificado": "demo",
                                            "rut_empresa": "77777777", "dv_empresa": "7"}, ignorar={"mensaje"}),
        paso("POST", "/api/v1/dte/enviar", {"xml_envio_b64": sobre(SOBRE_FACTURA)}),
        paso("POST", "/api/v1/estado/track", {"track_id": 1, "rut_empresa": "77777777", "dv_empresa": "7", "certificado_p12_b64": CERT_DEMO_B64, "password_certificado": "demo"}, ignorar={"mensaje"}),
        paso("POST", "/api/v1/estado/track", {"track_id": 1}),
        paso("POST", "/api/v1/estado/dte", {"rut_emisor": "77777777", "dv_emisor": "7", "tipo_dte": 33, "folio": 1, "fecha_emision": "20260115", "monto_total": 23800,
                                            "rut_receptor": "76111111", "dv_receptor": "6", "certificado_p12_b64": CERT_DEMO_B64, "password_certificado": "demo"}, ignorar={"mensaje"}),
    ],
    # utilidades sin estado y consultas a tablas: CAF, certificado, generar/pdf, db/*, monitoreo, lote, mipyme (solo la validación local)
    "rutas": [
        paso("POST", "/api/v1/caf/info", {}, archivo=str(CAF_DEMO_33)),
        paso("POST", "/api/v1/caf/info", {}, archivo=str(CERT_DEMO)),
        paso("POST", "/api/v1/caf/info", {}),
        paso("POST", "/api/v1/caf/validar-folio", {"caf_xml_b64": b64(CAF_DEMO_33.read_bytes()), "folio": 5}),
        paso("POST", "/api/v1/caf/validar-folio", {"caf_xml_b64": b64(CAF_DEMO_33.read_bytes()), "folio": 999999}),
        paso("POST", "/api/v1/caf/validar-folio", {"caf_xml_b64": "no-es-b64!!", "folio": 1}, ignorar={"mensaje"}),
        paso("POST", "/api/v1/caf/validar-folio", {"folio": 1}),
        paso("POST", "/api/v1/certificado/validar", {"password": "demo"}, archivo=str(CERT_DEMO)),
        paso("POST", "/api/v1/certificado/validar", {"password": "mala"}, archivo=str(CERT_DEMO), ignorar={"mensaje"}),
        paso("POST", "/api/v1/certificado/validar", {"password": "demo"}, archivo=str(CAF_DEMO_33)),
        paso("POST", "/api/v1/certificado/firmar-datos", {"datos_b64": b64(b"hola"), "password": "demo", "certificado_p12_b64": CERT_DEMO_B64}),
        paso("POST", "/api/v1/certificado/firmar-datos", {"datos_b64": "x!!", "password": "demo", "certificado_p12_b64": CERT_DEMO_B64}, ignorar={"mensaje"}),
        paso("POST", "/api/v1/certificado/firmar-datos", {"datos_b64": b64(b"hola")}),
        paso("POST", "/api/v1/dte/generar-simple", dte_demo(33, [{"nombre": "Café", "cantidad": 1, "precio_unitario": 20000}], folio=7)),
        paso("POST", "/api/v1/dte/generar-simple", dte_demo(39, [{"nombre": "Café", "cantidad": 2, "precio_unitario": 1190}], folio=3)),
        paso("POST", "/api/v1/dte/generar-simple", {"tipo_dte": 33}),
        paso("POST", "/api/v1/dte/generar", {"dte_json": json.dumps(dte_demo(33, [{"nombre": "Café", "cantidad": 1, "precio_unitario": 20000}], folio=7)), "password_certificado": "demo"}, archivo=str(CERT_DEMO), archivo_campo="certificado_p12", archivos_extra={"caf_xml": str(CAF_DEMO_33)}),
        paso("POST", "/api/v1/dte/generar", {"dte_json": json.dumps(dte_demo(33, [{"nombre": "Café", "cantidad": 1, "precio_unitario": 20000}], folio=7)), "password_certificado": "demo"}, archivo=str(CERT_DEMO), archivo_campo="certificado_p12"),
        paso("POST", "/api/v1/dte/generar", {"dte_json": json.dumps(dte_demo(33, [{"nombre": "Café", "cantidad": 1, "precio_unitario": 20000}], folio=999999)), "password_certificado": "demo"}, archivo=str(CERT_DEMO), archivo_campo="certificado_p12", archivos_extra={"caf_xml": str(CAF_DEMO_33)}),
        paso("POST", "/api/v1/dte/generar", {"dte_json": json.dumps(dte_demo(34, [{"nombre": "x", "precio_unitario": 1}], folio=1)), "password_certificado": "demo"}, archivo=str(CERT_DEMO), archivo_campo="certificado_p12", archivos_extra={"caf_xml": str(CAF_DEMO_33)}),
        paso("POST", "/api/v1/dte/generar", {"dte_json": "{no es json", "password_certificado": "demo"}, archivo=str(CERT_DEMO), archivo_campo="certificado_p12", ignorar={"mensaje"}),
        paso("POST", "/api/v1/dte/generar", {"dte_json": json.dumps(dte_demo(33, [{"nombre": "x", "precio_unitario": 1}])), "password_certificado": "mala"}, archivo=str(CERT_DEMO), archivo_campo="certificado_p12", ignorar={"mensaje"}),
        paso("POST", "/api/v1/dte/pdf-simple", dte_demo(33, [{"nombre": "Café", "cantidad": 1, "precio_unitario": 20000}], folio=7), ignorar={"*"}),
        paso("POST", "/api/v1/dte/pdf", {"dte_json": json.dumps(dte_demo(39, [{"nombre": "Café", "precio_unitario": 1190}], folio=3))}, multipart=True, ignorar={"*"}),
        paso("POST", "/api/v1/dte/pdf", {"dte_json": "{"}, multipart=True, ignorar={"mensaje"}),
        paso("GET", "/api/v1/db/dtes?limite=3", ignorar={"dtes", "total"}),
        paso("GET", "/api/v1/db/dtes?rut_emisor=77777777-7&tipo_dte=33&limite=2", ignorar={"id", "folio", "pdf_path", "creado_en", "total", "track_id"}),
        paso("GET", "/api/v1/db/dtes?limite=0"),
        paso("GET", "/api/v1/db/dtes?limite=abc"),
        paso("GET", "/api/v1/db/dtes?limite=5000"),
        paso("GET", "/api/v1/db/dtes/999999"),
        paso("GET", "/api/v1/db/dtes/abc"),
        paso("GET", "/api/v1/db/dtes/buscar/77777777-7/33/999999"),
        paso("GET", "/api/v1/db/cafs?rut_emisor=77777777-7", ignorar={"id", "folio_siguiente", "creado_en", "fecha_autorizacion", "activo"}),
        paso("GET", "/api/v1/db/cafs?tipo_dte=abc"),
        paso("GET", "/api/v1/db/cafs/activo/77777777-7/33", ignorar={"id", "folio_siguiente", "creado_en", "fecha_autorizacion"}),
        paso("GET", "/api/v1/db/cafs/activo/77777777-7/99"),
        paso("GET", "/api/v1/db/folios/siguiente/77777777-7/33", ignorar={"folio_disponible", "mensaje"}),
        paso("GET", "/api/v1/db/folios/siguiente/77777777-7/99"),
        paso("GET", "/api/v1/db/logs?limite=2", ignorar={"*"}),
        paso("GET", "/api/v1/db/logs?limite=abc"),
        paso("GET", "/api/v1/monitoreo/folios?rut=77777777-7", ignorar={"folio_siguiente", "restantes", "detalle", "estado", "por_estado", "verdict", "meses", "fecha_autorizacion"}),
        paso("GET", "/api/v1/monitoreo/folios"),
        paso("GET", "/api/v1/monitoreo/folios/cartera", ignorar={"*"}),
        paso("POST", "/api/v1/estado/lote", {"track_ids": [1], "rut_empresa": "77777777-7", "cert_id": 999999}),
        paso("POST", "/api/v1/estado/lote", {"track_ids": [1]}),
        paso("POST", "/api/v1/mipyme/diagnostico", {"rut_empresa": "77777777-7"}),
        paso("POST", "/api/v1/mipyme/importar", {"rut_empresa": "77777777-7", "rut_usuario": "12345678-5"}),
        paso("POST", "/api/v1/mipyme/sincronizar", {}),
    ],
    # portal del SII con certificado: validación local + consultas públicas (RUT ficticio → no autorizado)
    "portal": [
        paso("GET", "/api/v1/keystore/empresa?rut=77777777-7"),
        paso("GET", "/api/v1/keystore/empresa?rut=77777777-7&ambiente=produccion"),
        paso("GET", "/api/v1/keystore/empresa"),
        paso("GET", "/api/v1/keystore/certificados/999999/empresas"),
        paso("GET", "/api/v1/keystore/certificados/abc/empresas"),
        paso("POST", "/api/v1/keystore/negocios", {"rut": "77777777-7"}, multipart=True),
        paso("POST", "/api/v1/keystore/negocios", {"ambiente": "certificacion"}, multipart=True),
        paso("POST", "/api/v1/keystore/negocios", {"rut": "77777777-7", "cert_id": "abc"}, multipart=True),
        paso("GET", "/api/v1/keystore/negocios/999999/estado"),
        paso("GET", "/api/v1/keystore/negocios/999999/timbraje"),
        paso("GET", "/api/v1/keystore/negocios/abc/estado"),
        paso("GET", "/api/v1/keystore/negocios/999999/f29?periodo=202601"),
        paso("GET", "/api/v1/keystore/negocios/999999/f29"),
        paso("GET", "/api/v1/keystore/negocios/999999/f29?periodo=202601&ppm=abc"),
        paso("GET", "/api/v1/onboarding/diagnostico"),
        paso("GET", "/api/v1/onboarding/diagnostico?cert_id=abc&rut=77777777-7"),
        paso("GET", "/api/v1/onboarding/diagnostico?cert_id=999999&rut=77777777-7"),
        paso("GET", "/api/v1/onboarding/cartera?cert_id=999999"),
        paso("GET", "/api/v1/onboarding/cartera"),
    ],
    # buscador público de boletas (sin JWT) + páginas del panel: tras la práctica hay boletas de 77777777-7 en la base
    "consulta": [
        paso("POST", "/api/v1/simulacion/reiniciar", {}, ignorar={"documentos_borrados", "cafs_borrados"}),
        paso("POST", "/api/v1/simulacion/emitir", {"tipo_dte": 39, "items": [{"nombre": "Café", "precio_unitario": 1190}]}, ignorar={"dte_id", "folio", "pdf_path", "pdf_b64"}, guarda="folio"),
        paso("GET", "/consulta/api?rut=77777777-7&tipo=39&folio={folio}&monto=1190", ignorar={"folio", "links", "track_id"}),
        paso("GET", "/consulta/api?rut=77.777.777-7&tipo=39&folio={folio}&monto=1190&fecha=2026-01-15", ignorar={"folio", "links", "track_id"}),
        paso("GET", "/consulta/api?rut=77777777-7&tipo=39&folio={folio}&monto=1"),
        paso("GET", "/consulta/api?rut=77777777-7&tipo=33&folio=1&monto=1190"),
        paso("GET", "/consulta/api?rut=77777777-7&tipo=39&folio=abc&monto=1190"),
        paso("GET", "/consulta/api?rut=77777777-7"),
        paso("GET", "/consulta/xml?rut=77777777-7&tipo=39&folio={folio}&monto=1190", ignorar={"*"}),
        paso("GET", "/consulta/xml?rut=77777777-7&tipo=39&folio=999999&monto=1190"),
        paso("GET", "/consulta/pdf?rut=77777777-7&tipo=39&folio={folio}&monto=1190", ignorar={"*"}),
        paso("GET", "/consulta/pdf?rut=77777777-7&tipo=39&folio=999999&monto=1190"),
        paso("GET", "/consulta", ignorar={"*"}),
        paso("GET", "/consulta/", ignorar={"*"}),
        paso("GET", "/certificados", ignorar={"*"}),
        paso("GET", "/onboarding", ignorar={"*"}),
        paso("GET", "/apikeys", ignorar={"*"}),
        paso("GET", "/documentos", ignorar={"*"}),
        paso("GET", "/favicon.ico", ignorar={"*"}),
    ],
    "keystore": [
        paso("POST", "/api/v1/keystore/certificados", {"password": "demo", "nombre": "demo {motor}"}, archivo=str(CERT_DEMO), ignorar={"id", "nombre"}, guarda="id"),
        paso("POST", "/api/v1/keystore/certificados", {"password": "mala"}, archivo=str(CERT_DEMO)),
        paso("POST", "/api/v1/keystore/certificados", {"nombre": "sin clave"}, archivo=str(CERT_DEMO)),
        paso("GET", "/api/v1/keystore/certificados", ignorar={"id", "nombre", "alias"}),
        # el demo tiene un solo RUT y la fila es por (cuenta, rut): cada motor borra la suya por turnos
        paso("DELETE", "/api/v1/keystore/certificados/{id}", solo="py", espera=200),
        paso("POST", "/api/v1/keystore/certificados", {"password": "demo", "nombre": "demo go"}, archivo=str(CERT_DEMO), solo="go", espera=201, guarda="id"),
        paso("DELETE", "/api/v1/keystore/certificados/{id}", solo="go", espera=200),
        paso("DELETE", "/api/v1/keystore/certificados/{id}"),
        paso("GET", "/api/v1/keystore/negocios"),
        paso("DELETE", "/api/v1/keystore/negocios/999999"),
        paso("PUT", "/api/v1/keystore/claves-sii", {"rut_empresa": "77777777-{motor}", "rut_usuario": "12345678-5", "clave_tributaria": "secreta-{motor}"}, ignorar={"rut_empresa"}),
        paso("PUT", "/api/v1/keystore/claves-sii", {"rut_empresa": "77777777-{motor}", "clave_certificado": "cert-{motor}"}, ignorar={"rut_empresa"}),
        paso("PUT", "/api/v1/keystore/claves-sii", {}),
        paso("GET", "/api/v1/keystore/claves-sii/77777777-{motor}", ignorar={"rut_empresa"}),
        paso("GET", "/api/v1/mipyme/contexto-siiengine/77777777-{motor}", ignorar={"rut_empresa", "clave_tributaria", "clave_certificado"}),
        # cruzados: cada motor descifra lo que cifró el OTRO (Fernet)
        paso("GET", "/api/v1/mipyme/contexto-siiengine/77777777-py"),
        paso("GET", "/api/v1/mipyme/contexto-siiengine/77777777-go"),
        paso("DELETE", "/api/v1/keystore/claves-sii/77777777-{motor}"),
        paso("DELETE", "/api/v1/keystore/claves-sii/77777777-{motor}"),
        paso("GET", "/api/v1/keystore/claves-sii/77777777-{motor}", ignorar={"rut_empresa"}),
        paso("GET", "/api/v1/keystore/negocios/999999/contexto-emision"),
    ],
}


def pedir(base: str, p: dict, token: str | None, motor: str, vars_: dict):
    def sub(x):
        if isinstance(x, str):
            x = x.replace("{motor}", motor)
            for k, v in vars_.items():
                x = x.replace("{" + k + "}", str(v))
            return x
        if isinstance(x, dict):
            return {k: sub(v) for k, v in x.items()}
        return x
    ruta, cuerpo = sub(p["ruta"]), sub(p["cuerpo"])
    if token and vars_.get("access_token") and ruta.startswith("/api/v1/apikeys"):
        token = vars_["access_token"]   # las rutas de API keys exigen el JWT del usuario
    headers = {"Accept": "application/json", **({"Authorization": "Bearer " + token} if token else {})}
    datos = None
    if p["archivo"] or p.get("multipart"):
        limite = uuid.uuid4().hex
        partes = []
        for k, v in (cuerpo or {}).items():
            partes.append(f"--{limite}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode())
        archivos = ([(p.get("archivo_campo") or "archivo", p["archivo"])] if p["archivo"] else []) + list((p.get("archivos_extra") or {}).items())
        for campo, ruta_archivo in archivos:
            contenido = open(ruta_archivo, "rb").read()
            nombre = os.path.basename(ruta_archivo)
            tipo = mimetypes.guess_type(nombre)[0] or "application/octet-stream"
            partes.append(f"--{limite}\r\nContent-Disposition: form-data; name=\"{campo}\"; filename=\"{nombre}\"\r\nContent-Type: {tipo}\r\n\r\n".encode() + contenido + b"\r\n")
        partes.append(f"--{limite}--\r\n".encode())
        datos = b"".join(partes)
        headers["Content-Type"] = f"multipart/form-data; boundary={limite}"
    elif cuerpo is not None:
        datos = json.dumps(cuerpo).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(base + ruta, data=datos, method=p["metodo"], headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, r.read(), ruta
    except urllib.error.HTTPError as e:
        return e.code, e.read(), ruta
    except Exception as e:  # noqa: BLE001
        return -1, str(e).encode(), ruta


def limpiar(x, ignorar):
    if isinstance(x, dict):
        return {k: limpiar(v, ignorar) for k, v in x.items() if k not in ignorar}
    if isinstance(x, list):
        return [limpiar(v, ignorar) for v in x]
    return x


def diferencias(a, b, ruta=""):
    out = []
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a:
                out.append(f"{ruta}.{k}: solo en go = {b[k]!r}")
            elif k not in b:
                out.append(f"{ruta}.{k}: solo en python = {a[k]!r}")
            else:
                out += diferencias(a[k], b[k], f"{ruta}.{k}")
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            out.append(f"{ruta}: largos {len(a)} vs {len(b)}")
        for i, (x, y) in enumerate(zip(a, b)):
            out += diferencias(x, y, f"{ruta}[{i}]")
    elif a != b and not (isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool) and not isinstance(b, bool) and a == b):
        out.append(f"{ruta}: python={a!r} go={b!r}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--python", required=True)
    ap.add_argument("--go", required=True)
    ap.add_argument("--token", default=os.environ.get("APP_SHELL_KEY"))
    ap.add_argument("--escenario", default="todos")
    ap.add_argument("--sin-auth", action="store_true")
    a = ap.parse_args()
    nombres = list(ESCENARIOS) if a.escenario == "todos" else [a.escenario]
    fallas = 0
    for nombre in nombres:
        print(f"\n== {nombre} ==")
        vars_py, vars_go = {}, {}
        for p in ESCENARIOS[nombre]:
            if p["solo"]:
                base, motor, vars_ = (a.python, "py", vars_py) if p["solo"] == "py" else (a.go, "go", vars_go)
                st, cuerpo, ruta = pedir(base, p, a.token, motor, vars_)
                try:
                    j = json.loads(cuerpo or b"null")
                except ValueError:
                    j = None
                if p["guarda"] and isinstance(j, dict):
                    campo, _, var = p["guarda"].partition(":")
                    if campo in j:
                        vars_[var or campo] = j[campo]
                ok = p["espera"] is None or st == p["espera"]
                print(f"{'·' if ok else '✗'} {p['metodo']} {ruta}  [solo {motor}] → {st}")
                if not ok:
                    fallas += 1
                continue
            variantes = [(a.token, True)] + ([(None, False)] if a.sin_auth and p["metodo"] == "GET" and p["ruta"] != "/" else [])
            for tok, con in variantes:
                sp, bp, rp = pedir(a.python, p, tok, "py", vars_py)
                sg, bg, rg = pedir(a.go, p, tok, "go", vars_go)
                etiqueta = f"{p['metodo']} {p['ruta']}" + ("" if con else "  [sin token]")
                try:
                    jp, jg = json.loads(bp or b"null"), json.loads(bg or b"null")
                except ValueError:
                    if sp == sg and sp < 400 and "*" in p["ignorar"]:
                        print(f"✓ {etiqueta}: {sp} (binario, {len(bp)} B vs {len(bg)} B)"); continue
                    print(f"✗ {etiqueta}: respuesta no JSON (python {sp}: {bp[:80]!r}, go {sg}: {bg[:80]!r})"); fallas += 1; continue
                if con and p["guarda"]:
                    campo, _, var = p["guarda"].partition(":")
                    var = var or campo
                    if isinstance(jp, dict) and campo in jp:
                        vars_py[var] = jp[campo]
                    if isinstance(jg, dict) and campo in jg:
                        vars_go[var] = jg[campo]
                if sp != sg:
                    print(f"✗ {etiqueta}: status python {sp} ≠ go {sg}  (py: {bp[:120]!r} | go: {bg[:120]!r})"); fallas += 1; continue
                if sp >= 400:
                    def _cod(j):  # el envoltorio {"error": {"codigo"}} o, en el buscador público, "error": "texto"
                        e = (j or {}).get("error") if isinstance(j, dict) else None
                        return e.get("codigo") if isinstance(e, dict) else e
                    cp, cg = _cod(jp), _cod(jg)
                    if cp != cg:
                        print(f"✗ {etiqueta}: {sp} codigo python {cp!r} ≠ go {cg!r}"); fallas += 1
                    else:
                        print(f"✓ {etiqueta}: {sp} {cp}")
                    continue
                ign = IGNORAR_SIEMPRE | p["ignorar"]
                difs = diferencias(limpiar(jp, ign), limpiar(jg, ign))
                if difs:
                    fallas += 1
                    print(f"✗ {etiqueta}: {len(difs)} diferencia(s)")
                    for d in difs[:8]:
                        print("    " + d)
                else:
                    print(f"✓ {etiqueta}: {sp} idéntico")
    print(f"\n{'TODO IDÉNTICO' if not fallas else str(fallas) + ' paso(s) con diferencias'}")
    return 0 if not fallas else 1


if __name__ == "__main__":
    sys.exit(main())
