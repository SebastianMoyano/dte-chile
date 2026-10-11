#!/usr/bin/env python3
"""Auditoría de lo que NO puede salir al repo público: RUTs reales, datos de personas, secretos.

Revisa el árbol versionado y TODA la historia de git (cada diff de cada commit). Sale con 1 si
encuentra algo. Es el gate `publico` de tools/prueba_final.sh y el hook pre-push
(tools/instalar_hooks.sh). No sabe ningún dato real: busca RUTs con dígito verificador válido
que no estén en la lista de ficticios (L14 de la constitución), claves privadas fuera de los
fixtures, variables de secretos con valor real, API keys y JWT. Los términos que solo tú
conoces (nombres de personas, cuentas) van en `.auditoria-local.txt` (ignorado por git), uno
por línea.

    python tools/auditar_publico.py            # árbol + historia
    python tools/auditar_publico.py --arbol    # solo el árbol (rápido)
"""
from __future__ import annotations

import os
import re
import subprocess
import sys

# RUTs ficticios permitidos (constitución L14 + los que usan el SII y los fixtures del corpus).
FICTICIOS = {
    "77777777-7", "76111111-6", "12345678-5", "11111111-1", "66666666-6", "60803000-K",
    "12345678-9", "12345678-K", "12345678-0", "78111111-2", "76543210-9", "76543210-5",
    "76444444-2", "76222222-1", "19222222-2", "99999999-9", "98765432-1",
}
RUT = re.compile(r"(?<![0-9])([0-9]{1,2}\.?[0-9]{3}\.?[0-9]{3})-([0-9kK])(?![0-9])")
# Números de caso del set de certificación del SII que casualmente tienen dígito verificador válido.
FALSOS = re.compile(r"^4943(173|176)-")
# En nombres de archivo también se busca el RUT pegado, sin guión (ej. SIISetDePruebas<rut><dv>.txt).
RUT_PEGADO = re.compile(r"(?<![0-9])([0-9]{7,8})([0-9kK])(?![0-9])")
SECRETOS = [
    ("clave privada", re.compile(r"BEGIN (RSA |EC |ENCRYPTED )?PRIVATE KEY")),
    ("variable con secreto", re.compile(
        r"(SII_MAIL_TOKEN|JWT_SECRET_KEY|DTE_MASTER_KEY|MCP_AUTH_TOKEN|ADMIN_PASSWORD|CERTIFICADO_PASSWORD|"
        r"NUCLEO_CLAVE_TRIBUTARIA|NUCLEO_CLAVE_CERTIFICADO|APP_SHELL_KEY)\s*=\s*['\"]?([^\s'\"#]{8,})")),
    ("API key del motor", re.compile(r"\bdte_[A-Za-z0-9]{24,}\b")),
    ("JWT", re.compile(r"\beyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{10,}")),
    ("cookie/token SII", re.compile(r"\bTOKEN=[A-Z0-9]{10,}\b")),
    ("clave tributaria literal", re.compile(r"clave_tributaria['\"]?\s*[:=]\s*['\"][^'\"]{6,}['\"]")),
]
JWT_EJEMPLO = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIn0"
# Valores que no son secretos (plantillas, docs, pruebas).
PLACEHOLDER = re.compile(r"(cambiar|cambia-|tu-|un-|ejemplo|placeholder|xxx|<|\$|\+|\.Clave|secreta-|secreto-|ci-|clave-de-prueba|openssl|os\.environ|getenv|settings\.|\{\{)", re.I)
# Dónde sí puede haber una clave privada: los CAF ficticios del corpus y el código que los genera.
RUTAS_CLAVES_OK = re.compile(r"^(tests/dorado/fixtures/(caf_[0-9]+\.xml|cert_demo\..*)|nucleo/firma/.*|core/caf\.py|tools/generar_.*|tests/dorado/.*\.py)$")


def dv(cuerpo: str) -> str:
    s, m = 0, 2
    for c in reversed(cuerpo):
        s += int(c) * m
        m = 2 if m == 7 else m + 1
    r = 11 - (s % 11)
    return {11: "0", 10: "K"}.get(r, str(r))


def locales() -> list[str]:
    try:
        with open(".auditoria-local.txt", encoding="utf-8") as f:
            return [l.strip() for l in f if l.strip() and not l.startswith("#")]
    except FileNotFoundError:
        return []


def revisar(texto: str, donde: str, ruta: str, hallazgos: list[str], terminos: list[str], archivo: str = "") -> None:
    """archivo = la ruta del archivo (para las excepciones por ruta); ruta = cómo se reporta."""
    candidatos = [(m.group(1), m.group(2)) for m in RUT.finditer(texto)]
    if donde.startswith("nombre de archivo"):
        candidatos += [(m.group(1), m.group(2)) for m in RUT_PEGADO.finditer(texto)]
    for cuerpo, d in candidatos:
        cuerpo = cuerpo.replace(".", "")
        if len(cuerpo) < 7 or dv(cuerpo) != d.upper():
            continue  # no es un RUT (número de caso, folio, etc.)
        r = f"{int(cuerpo)}-{d.upper()}"
        if r not in FICTICIOS and not FALSOS.match(r):
            hallazgos.append(f"RUT real {r[:3]}…-{r[-1]} en {donde}: {ruta}")
    for nombre, rx in SECRETOS:
        for m in rx.finditer(texto):
            frag = m.group(0)
            if nombre == "clave privada" and RUTAS_CLAVES_OK.match(archivo or ruta):
                continue
            if nombre == "variable con secreto" and PLACEHOLDER.search(frag):
                continue
            if nombre == "clave tributaria literal" and PLACEHOLDER.search(frag):
                continue
            if nombre == "JWT" and frag.startswith(JWT_EJEMPLO):
                continue  # el ejemplo público de jwt.io ("John Doe"), usado en las pruebas de tachado
            hallazgos.append(f"{nombre} ({frag[:18]}…) en {donde}: {ruta}")
    for t in terminos:
        if t.lower() in texto.lower():
            hallazgos.append(f"término local «{t[0]}…» en {donde}: {ruta}")


def arbol(terminos: list[str]) -> list[str]:
    h: list[str] = []
    archivos = subprocess.run(["git", "ls-files", "-z"], capture_output=True, check=True).stdout.decode().split("\0")
    for ruta in archivos:
        if not ruta:
            continue
        revisar(ruta, "nombre de archivo", ruta, h, terminos)
        try:
            with open(ruta, "rb") as f:
                texto = f.read().decode("utf-8", "replace")
        except (IsADirectoryError, FileNotFoundError):
            continue
        revisar(texto, "árbol", ruta, h, terminos, ruta)
    return h


def historia(terminos: list[str]) -> list[str]:
    h: list[str] = []
    # ramas y tags locales: lo que se va a subir (las referencias remotas son el pasado ya publicado)
    p = subprocess.run(["git", "log", "--branches", "--tags", "-p", "--format=COMMIT %h %s%n%b"], capture_output=True, check=True)
    ruta, commit = "", ""
    for linea in p.stdout.decode("utf-8", "replace").split("\n"):
        if linea.startswith("COMMIT "):
            commit = linea[7:14]
            revisar(linea[7:], "mensaje de commit", commit, h, terminos)
            continue
        if linea.startswith("diff --git "):
            ruta = linea.split(" b/", 1)[-1]
            revisar(ruta, "nombre de archivo (historia)", f"{commit} {ruta}", h, terminos, ruta)
            continue
        if linea.startswith("+") and not linea.startswith("+++"):
            revisar(linea[1:], "historia", f"{commit} {ruta}", h, terminos, ruta)
    return h


def main() -> int:
    solo_arbol = "--arbol" in sys.argv
    terminos = locales()
    h = arbol(terminos)
    if not solo_arbol:
        h += historia(terminos)
    vistos = sorted(set(h))
    for x in vistos:
        print("✗", x)
    ambito = "árbol" if solo_arbol else "árbol + historia"
    if vistos:
        print(f"{len(vistos)} hallazgo(s) en {ambito}")
        return 1
    print(f"limpio: {ambito} sin RUTs reales, personas ni secretos" + (f" ({len(terminos)} términos locales)" if terminos else ""))
    return 0


if __name__ == "__main__":
    os.chdir(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
    sys.exit(main())
