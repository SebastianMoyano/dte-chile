#!/usr/bin/env python3
"""Auditoría de lo que se PUBLICA en una release: que ningún paquete lleve algo privado.

Abre cada archivo de `dist/<versión>/` (zip, tar.gz, .mcpb; cualquier otro se revisa como un
solo bloque) y, miembro por miembro, exige:
  - que ningún archivo tenga un nombre prohibido (.env, boveda.json, certificados, bases, bundles…;
    la misma lista que tools/auditar_publico.py);
  - que el .app de Faro solo lleve adentro el binario, el ícono, la firma y la carpeta frontend/;
  - que ningún contenido traiga secretos ni claves privadas; en los archivos de texto, además,
    ningún RUT real, correo de persona, IP privada ni ruta de carpeta personal (en los binarios se
    buscan secretos con valor real, IPs y rutas; los correos de ahí son de bibliotecas de terceros).
    El binario Rust se compila con --remap-path-prefix para no llevar rutas de este computador.
Sale con 1 si encuentra algo. Lo corre tools/release.sh antes de calcular las sumas, y
tools/prueba_final.sh lo autoprueba (gate `release_autoprueba`).

    python tools/auditar_release.py dist/1.1.0
    python tools/auditar_release.py --autoprueba
"""
from __future__ import annotations

import io
import os
import re
import sys
import tarfile
import tempfile
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import auditar_publico as ap  # noqa: E402

APP_OK = re.compile(
    r"^Faro\.app/(Contents/(Info\.plist|PkgInfo|CodeResources|_CodeSignature/.*|MacOS/faro|"
    r"Resources/(icon\.icns|frontend/.*|[a-zA-Z_-]+\.lproj/.*))?|Contents/|Contents/MacOS/|Contents/Resources/|Contents/Resources/frontend/.*|)$")
# Lo que puede ir en la carpeta de la interfaz: archivos de una página web, nada más.
FRONTEND_OK = re.compile(r"\.(js|css|html|json|svg|png|ico|icns|woff2?|ttf|webmanifest|txt|md)$|/$")
# En un binario, lo que buscamos son cadenas; los RUT se revisan solo en texto (en bytes al azar
# un número de 8 cifras con dígito verificador válido aparece por casualidad).
EN_BINARIO = {"clave privada", "clave SSH", "variable con secreto", "API key del motor", "JWT", "token de GitHub",
              "API key de Anthropic/OpenAI", "clave de AWS", "token de Slack", "API key de Google",
              "credencial de Apple", "cookie/token SII"}
# Dentro de un binario, "DTE_MASTER_KEY=%s" o "ADMIN_PASSWORD=" seguido de otro nombre de variable son
# las plantillas con las que el motor escribe el .env; un secreto real mezcla minúsculas y números.
VALOR_REAL = re.compile(r"^(?=.*[a-z])(?=.*[0-9])[A-Za-z0-9+/=_-]{16,}$")


def miembros(ruta: str):
    """Rinde (nombre, bytes) por cada archivo de un paquete; un archivo suelto es un solo miembro."""
    base = os.path.basename(ruta)
    if zipfile.is_zipfile(ruta):
        with zipfile.ZipFile(ruta) as z:
            for i in z.infolist():
                yield f"{base}:{i.filename}", (b"" if i.is_dir() else z.read(i))
    elif tarfile.is_tarfile(ruta):
        with tarfile.open(ruta) as t:
            for m in t:
                f = t.extractfile(m) if m.isfile() else None
                yield f"{base}:{m.name.removeprefix('./')}", (f.read() if f else b"")
    else:
        with open(ruta, "rb") as f:
            yield base, f.read()


def revisar_bytes(nombre: str, datos: bytes, h: list[str]) -> None:
    try:
        texto, es_texto = datos.decode("utf-8"), True
    except UnicodeDecodeError:
        texto, es_texto = datos.decode("latin-1"), False
    if es_texto:
        ap.revisar(texto, "paquete", nombre, h, [], nombre)
        return
    for sec, rx in ap.SECRETOS:
        if sec not in EN_BINARIO:
            continue
        for m in rx.finditer(texto):
            frag = m.group(0)
            if sec in ("variable con secreto", "credencial de Apple") and (ap.PLACEHOLDER.search(frag) or not VALOR_REAL.match(m.group(2))):
                continue
            if sec == "JWT" and frag.startswith(ap.JWT_EJEMPLO):
                continue
            h.append(f"{sec} ({frag[:18]}…) en binario: {nombre}")
    for m in ap.RUTA_PERSONAL.finditer(texto):
        if m.group(2).lower() not in ap.USUARIOS_OK:
            h.append(f"ruta personal ({m.group(1)}/{m.group(2)[:2]}…) en binario: {nombre}")
    for m in ap.IP_PRIVADA.finditer(texto):
        h.append(f"IP privada ({m.group(0)}) en binario: {nombre}")
    # Correos no se buscan en binarios: los que hay son de las bibliotecas de terceros (openssl, debian…).


def auditar(rutas: list[str]) -> list[str]:
    h: list[str] = []
    for ruta in rutas:
        for nombre, datos in miembros(ruta):
            interno = nombre.split(":", 1)[-1]
            if ap.nombre_prohibido(interno):
                h.append(f"archivo prohibido por su nombre en el paquete: {nombre}")
            if interno.startswith("Faro.app/"):
                if not APP_OK.match(interno):
                    h.append(f"archivo fuera de lo esperado dentro de Faro.app: {nombre}")
                if "/Resources/frontend/" in interno and not FRONTEND_OK.search(interno):
                    h.append(f"archivo que no es de la interfaz dentro de frontend/: {nombre}")
            revisar_bytes(nombre, datos, h)
    return sorted(set(h))


def autoprueba() -> int:
    with tempfile.TemporaryDirectory() as d:
        sucio = os.path.join(d, "sucio.zip")
        with zipfile.ZipFile(sucio, "w") as z:
            z.writestr("Faro.app/Contents/Resources/.env", "DTE_MASTER_KEY" + "=zk9s8d7f6g5h4j3k2l1m0\n")
            z.writestr("Faro.app/Contents/Resources/firma.p12", b"\x30\x82binario")
            z.writestr("Faro.app/Contents/MacOS/faro", b"\x00\x01/Users/" + b"juanperez/Desktop/dte\x00ghp_" + b"A1b2C3d4" * 5)
            z.writestr("Faro.app/Contents/Resources/frontend/notas.txt", "cliente 55.555.555-" + ap.dv("55555555") + " juan.perez" + "@gmail.com")
            z.writestr("Faro.app/Contents/Resources/frontend/motor.bin", b"\x00\x01\x02")
        limpio = os.path.join(d, "limpio.tar.gz")
        with tarfile.open(limpio, "w:gz") as t:
            info = tarfile.TarInfo("./nucleo-servidor"); datos = b"\x7fELF/Users/x/dte EMPRESA DEMO 77777777-7 \x00" * 3
            info.size = len(datos); t.addfile(info, io.BytesIO(datos))
        hs = auditar([sucio])
        esperados = ["archivo prohibido", "archivo fuera de lo esperado", "variable con secreto", "ruta personal",
                     "token de GitHub", "RUT real", "correo de persona", "archivo que no es de la interfaz"]
        fallas = [e for e in esperados if not any(x.startswith(e) for x in hs)]
        for f in fallas:
            print(f"✗ no detectó «{f}»")
        hl = auditar([limpio])
        if hl:
            print(f"✗ falso positivo en paquete limpio: {hl}"); fallas.append("limpio")
        print("autoprueba: " + ("falló" if fallas else f"ok ({len(esperados)} clases detectadas, paquete limpio pasa)"))
        return 1 if fallas else 0


def main() -> int:
    if "--autoprueba" in sys.argv:
        return autoprueba()
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__); return 2
    rutas: list[str] = []
    for a in args:
        if os.path.isdir(a):
            rutas += [os.path.join(a, f) for f in sorted(os.listdir(a)) if not f.startswith(".") and f != "SHA256SUMS.txt"]
        else:
            rutas.append(a)
    h = auditar(rutas)
    for x in h:
        print("✗", x)
    if h:
        print(f"{len(h)} hallazgo(s) en {len(rutas)} paquete(s)")
        return 1
    print(f"limpio: {len(rutas)} paquete(s) sin archivos prohibidos, secretos, rutas personales ni correos")
    return 0


if __name__ == "__main__":
    os.chdir(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
    sys.exit(main())
