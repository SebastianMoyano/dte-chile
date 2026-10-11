"""
tools/contrato_api.py — Contrato dorado de la API: el motor Go debe responder lo mismo que el
motor Python (fase 7 del port). Pide cada paso a los dos motores y compara status, `codigo` de
error y el JSON completo (ignorando campos volátiles).

Uso (los dos motores corriendo, con el MISMO APP_SHELL_KEY en el entorno de ambos):
  APP_SHELL_KEY=… .venv/bin/python tools/contrato_api.py --python http://127.0.0.1:8771 --go http://127.0.0.1:8010
  … --escenario valores|auth|apikeys|simulacion|xsd|keystore|todos   (default: todos)
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
SOBRE_BOLETAS = RAIZ / "tests" / "dorado" / "esperado" / "14_sobre_dos_boletas" / "envio.xml"


def b64(datos: bytes) -> str:
    import base64
    return base64.b64encode(datos).decode("ascii")


def sobre(ruta, reemplazo=None) -> str:
    datos = ruta.read_bytes()
    if reemplazo:
        datos = datos.replace(reemplazo[0], reemplazo[1], 1)
    return b64(datos)


def paso(metodo, ruta, cuerpo=None, ignorar=(), guarda=None, archivo=None, solo=None, espera=None):
    """guarda: campo de la respuesta → variable del mismo nombre; "access_token" se usa como Bearer en los pasos
    siguientes del escenario. solo="py"|"go": el paso corre en un solo motor (preparación), sin comparar;
    espera: status exigido en ese caso."""
    return {"metodo": metodo, "ruta": ruta, "cuerpo": cuerpo, "ignorar": set(ignorar), "guarda": guarda, "archivo": archivo, "solo": solo, "espera": espera}


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
    if p["archivo"]:
        limite = uuid.uuid4().hex
        partes = []
        for k, v in (cuerpo or {}).items():
            partes.append(f"--{limite}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode())
        contenido = open(p["archivo"], "rb").read()
        nombre = os.path.basename(p["archivo"])
        tipo = mimetypes.guess_type(nombre)[0] or "application/octet-stream"
        partes.append(f"--{limite}\r\nContent-Disposition: form-data; name=\"archivo\"; filename=\"{nombre}\"\r\nContent-Type: {tipo}\r\n\r\n".encode() + contenido + b"\r\n")
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
                    cp, cg = (jp or {}).get("error", {}).get("codigo"), (jg or {}).get("error", {}).get("codigo")
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
