#!/usr/bin/env python3
"""Auditoría de lo que NO puede salir al repo público: RUTs reales, datos de personas, secretos.

Revisa el árbol versionado y TODA la historia de git (cada diff de cada commit). Sale con 1 si
encuentra algo. Es el gate `publico` de tools/prueba_final.sh y el hook pre-push
(tools/instalar_hooks.sh). No sabe ningún dato real: busca RUTs con dígito verificador válido
que no estén en la lista de ficticios (L14 de la constitución), claves privadas fuera de los
fixtures, variables de secretos con valor real, API keys, JWT, tokens de GitHub/Apple/Anthropic/
AWS, contraseñas específicas de app de Apple, archivos que por su nombre no pueden versionarse
(.env, bóveda, certificados, bases, bundles de respaldo), correos que no sean de dominios
ficticios, IPs privadas y rutas de carpetas personales. También exige que `.gitignore` siga
tapando cada ruta sensible. Los términos que solo tú conoces (nombres de personas, cuentas) van
en `.auditoria-local.txt` (ignorado por git), uno por línea.

    python tools/auditar_publico.py               # árbol + historia + .gitignore
    python tools/auditar_publico.py --arbol       # solo el árbol (rápido)
    python tools/auditar_publico.py --autoprueba  # el gate del gate: que detecte lo que debe
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
    ("token de GitHub", re.compile(r"\b(gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{20,})\b")),
    ("API key de Anthropic/OpenAI", re.compile(r"\bsk-(ant-)?[A-Za-z0-9_-]{24,}\b")),
    ("clave de AWS", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("token de Slack", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("API key de Google", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("clave SSH", re.compile(r"BEGIN OPENSSH PRIVATE[ ]KEY")),
    # La "contraseña específica de app" de Apple (notarización) tiene exactamente esta forma.
    ("contraseña de app de Apple", re.compile(r"\b[a-z]{4}-[a-z]{4}-[a-z]{4}-[a-z]{4}\b")),
    ("credencial de Apple", re.compile(
        r"(APPLE_PASSWORD|APPLE_APP_PASSWORD|APPLE_API_KEY|APPLE_API_ISSUER|NOTARY_PASSWORD)\s*=\s*['\"]?([^\s'\"#$<]{8,})")),
    ("contraseña literal", re.compile(r"(?i)(password|passwd|contrase[ñn]a)['\"]?\s*[:=]\s*['\"]([^'\"]{8,})['\"]")),
]
# Un valor "parece real" si mezcla letras y números y no tiene espacios (lo que generan openssl, Fernet, un gestor).
PARECE_REAL = re.compile(r"^(?=.*[A-Za-z])(?=.*[0-9])[^\s]{8,}$")
# Archivos que por su NOMBRE no pueden estar en el repo (ni en el árbol ni en ningún commit).
ARCHIVO_PROHIBIDO = re.compile(
    r"(^|/)(\.env(\..+)?|boveda\.json|credentials\.json|token\.json|\.netrc|\.npmrc|\.pypirc|"
    r"id_(rsa|ed25519|ecdsa|dsa)|AuthKey_[^/]*|task\.md|CHECKPOINT\.md|\.auditoria-local\.txt|SIISetDePruebas[^/]*|"
    r"[^/]*\.(p12|pfx|p8|pem|key|mobileprovision|keychain|keychain-db|db|db-wal|db-shm|sqlite|sqlite3|bundle))$")
ARCHIVO_OK = re.compile(r"^(\.env\.example|tests/dorado/fixtures/cert_demo\.[a-z0-9.]+)$")
# Correos: solo dominios ficticios o de servicios; cualquier otro es un dato de una persona.
CORREO = re.compile(r"\b[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[a-z]{2,})\b")
# "128x128@2x.png" no es un correo: nombres de archivo con @ (íconos retina) y extensiones conocidas.
EXTENSION = re.compile(r"\.(png|jpe?g|svg|gif|webp|icns|ico|js|css|json|xml|html|md|txt|go|rs|py|sh|toml|yml|yaml|lock)$")
DOMINIOS_OK = {
    "ejemplo.cl", "example.com", "example.org", "empresademo.cl", "demo.cl", "colegio.cl", "empresa.cl",
    "miempresa.cl", "cliente.cl", "anthropic.com", "users.noreply.github.com", "github.com", "sii.cl",
    "extralatte.cl", "localhost.cl", "correo.cl", "mail.cl", "test.cl",
}
IP_PRIVADA = re.compile(r"\b(192\.168\.[0-9]{1,3}\.[0-9]{1,3}|10\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}|172\.(1[6-9]|2[0-9]|3[01])\.[0-9]{1,3}\.[0-9]{1,3})\b")
RUTA_PERSONAL = re.compile(r"(/Users|/home|C:\\Users)[/\\]([A-Za-z0-9][^/\\\s'\"`<>$]*)")
USUARIOS_OK = {"x", "tu", "usuario", "admin", "user", "runner", "root", "nombre", "yo", "alguien", "tu-usuario"}
# Rutas que .gitignore tiene que seguir tapando (se prueban con `git check-ignore`).
DEBEN_IGNORARSE = [
    ".env", ".env.local", ".env.bak-1", "boveda.json", "dte_database.db", "x.db-wal", "firma.pfx", "x.p12",
    "x.p8", "AuthKey_X.p8", "x.pem", "x.key", "x.mobileprovision", "x.keychain-db", "respaldo.bundle",
    ".auditoria-local.txt", "storage/x", "logs/x", "dist/x", "task.md", "CHECKPOINT.md", "SIISetDePruebas1.txt",
]
JWT_EJEMPLO = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIn0"
# Valores que no son secretos (plantillas, docs, pruebas).
PLACEHOLDER = re.compile(r"(cambiar|cambia-|tu-|un-|ejemplo|placeholder|xxx|<|\$|\+|\.Clave|secreta-|secreto-|ci-|clave-de-prueba|clave-del|del-paso|contrato-|openssl|os\.environ|getenv|settings\.|\{\{|\bla clave\b|\bsu clave\b)", re.I)
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


def nombre_prohibido(ruta: str) -> bool:
    """True si un archivo con ese nombre no puede estar en el repo (ni en un paquete publicado)."""
    return bool(ARCHIVO_PROHIBIDO.search(ruta)) and not ARCHIVO_OK.match(ruta)


def revisar(texto: str, donde: str, ruta: str, hallazgos: list[str], terminos: list[str], archivo: str = "") -> None:
    """archivo = la ruta del archivo (para las excepciones por ruta); ruta = cómo se reporta."""
    if donde.startswith("nombre de archivo") and nombre_prohibido(texto):
        hallazgos.append(f"archivo prohibido por su nombre en {donde}: {ruta}")
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
            if nombre in ("credencial de Apple", "contraseña literal", "contraseña de app de Apple") and PLACEHOLDER.search(frag):
                continue
            if nombre == "contraseña literal" and not PARECE_REAL.match(m.group(2)):
                continue
            hallazgos.append(f"{nombre} ({frag[:18]}…) en {donde}: {ruta}")
    for m in CORREO.finditer(texto):
        dom = m.group(1).lower()
        if dom not in DOMINIOS_OK and not dom.endswith((".ejemplo.cl", ".example.com", ".sii.cl")) and not EXTENSION.search(dom):
            hallazgos.append(f"correo de persona ({m.group(0)[:3]}…@{dom}) en {donde}: {ruta}")
    for m in IP_PRIVADA.finditer(texto):
        hallazgos.append(f"IP privada ({m.group(0)}) en {donde}: {ruta}")
    for m in RUTA_PERSONAL.finditer(texto):
        if m.group(2).lower() not in USUARIOS_OK:
            hallazgos.append(f"ruta personal ({m.group(1)}/{m.group(2)[:2]}…) en {donde}: {ruta}")
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


def ignorados() -> list[str]:
    """Cada ruta sensible tiene que estar tapada por .gitignore, para que ni un `git add .` la suba."""
    p = subprocess.run(["git", "check-ignore", "--no-index", "-v", "--", *DEBEN_IGNORARSE], capture_output=True, text=True)
    tapadas = {l.rsplit("\t", 1)[-1] for l in p.stdout.splitlines() if "\t" in l}
    return [f".gitignore no tapa: {r}" for r in DEBEN_IGNORARSE if r not in tapadas]


def autoprueba() -> int:
    """El gate del gate: cada clase de hallazgo se detecta y los ejemplos legítimos pasan limpios."""
    # Los ejemplos se arman al vuelo (concatenando) para que este archivo no se delate a sí mismo.
    j = "".join
    deben = {
        "RUT real": "emisor 55.555.555-" + dv("55555555"),  # dígito verificador válido, fuera de la lista
        "clave privada": j(["-----BEGIN RSA ", "PRIVATE KEY-----"]),
        "variable con secreto": j(["DTE_MASTER_KEY", "=Zk9s8d7f6g5h4j3k2l1"]),
        "API key del motor": j(["dte_", "abcdefghijklmnopqrstuvwxyz0123"]),
        "JWT": j(["eyJ", "hbGciOiJIUzI1NiJ9abc.eyJzdWIiOiJ4eHh4eHh4eHgifQ.abcdefghijklmnop"]),
        "token de GitHub": "ghp_" + "A1b2C3d4" * 5,
        "API key de Anthropic/OpenAI": "sk-ant-api03-" + "x" * 30,
        "clave de AWS": "AKIA" + "ABCDEFGHIJKLMNOP",
        "contraseña de app de Apple": j(["abcd-efgh-", "ijkl-mnop"]),
        "credencial de Apple": j(["APPLE_PASSWORD", "=abcd-efgh-", "ijkl-mnop"]),
        "contraseña literal": j(["password: \"", "MiClaveReal2026\""]),
        "correo de persona": j(["escríbele a juan.perez", "@gmail.com"]),
        "IP privada": j(["ssh 192.168.", "0.10"]),
        "ruta personal": j(["/Users/", "juanperez/Desktop/dte"]),
    }
    fallas = 0
    for nombre, texto in deben.items():
        h: list[str] = []
        revisar(texto, "árbol", "autoprueba", h, [])
        if not any(x.startswith(nombre) for x in h):
            print(f"✗ no detectó «{nombre}»: {h}"); fallas += 1
    for ruta in [".env", "x/.env.local", "boveda.json", "firma.p12", "AuthKey_AB12.p8", "respaldo.bundle", "dte_database.db"]:
        if not nombre_prohibido(ruta):
            print(f"✗ no prohibió el nombre {ruta}"); fallas += 1
    limpios = [
        "EMPRESA DEMO SPA 77.777.777-7, contacto@ejemplo.cl, /Users/x/dte, Co-Authored-By: a <noreply@anthropic.com>",
        "APPLE_PASSWORD=xxxx-xxxx-xxxx-xxxx  DTE_MASTER_KEY=$(openssl rand -hex 32)  password: \"<tu-password>\"",
        "paso-a-paso con la app; IDENTIDAD=\"Developer ID Application: …\"; 10.13 es la versión mínima de macOS",
        'cfg.admin_password = "admin-de-prueba"; {"password": "incorrecta"}; app-rs/icons/128x128@2x.png; mkdir -p "$TMP/home/.cursor"',
    ]
    for texto in limpios:
        h = []
        revisar(texto, "árbol", "autoprueba", h, [])
        if h:
            print(f"✗ falso positivo en texto limpio: {h}"); fallas += 1
    for ruta in [".env.example", "tests/dorado/fixtures/cert_demo.p12", "docs/APP.md", "app.js"]:
        if nombre_prohibido(ruta):
            print(f"✗ prohibió un nombre legítimo: {ruta}"); fallas += 1
    print("autoprueba: " + ("falló" if fallas else f"ok ({len(deben)} clases detectadas, {len(limpios)} textos limpios pasan)"))
    return 1 if fallas else 0


def main() -> int:
    if "--autoprueba" in sys.argv:
        return autoprueba()
    solo_arbol = "--arbol" in sys.argv
    terminos = locales()
    h = arbol(terminos) + ignorados()
    if not solo_arbol:
        h += historia(terminos)
    vistos = sorted(set(h))
    for x in vistos:
        print("✗", x)
    ambito = "árbol" if solo_arbol else "árbol + historia"
    if vistos:
        print(f"{len(vistos)} hallazgo(s) en {ambito}")
        return 1
    print(f"limpio: {ambito} sin RUTs reales, personas, correos, rutas ni secretos; .gitignore tapa {len(DEBEN_IGNORARSE)} rutas" + (f" ({len(terminos)} términos locales)" if terminos else ""))
    return 0


if __name__ == "__main__":
    os.chdir(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
    sys.exit(main())
