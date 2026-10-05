#!/usr/bin/env python3
"""
limpiar_captura.py — Vuelve a tachar una captura ya descargada y dice qué quedaba.

Para archivos grabados con versiones anteriores de la extensión (cuyo tachado era solo por
nombre exacto de campo) o para pasar una segunda vez antes de compartir. Mismas reglas que
`tachar.js`: por NOMBRE (cualquier campo/parámetro/clave que contenga clave, token, secret,
api_key, auth, csrf, session…) y por VALOR (JWT, Bearer, hex ≥ 32, uuid junto a nombres
sensibles, inputs type=password).

    python3 limpiar_captura.py captura.json            # escribe captura.limpio.json
    python3 limpiar_captura.py captura.json --en-sitio # sobrescribe
    python3 limpiar_captura.py captura.json --sin-pii  # no reemplazar RUT/correos/celulares (p. ej. para comparar con el módulo)
"""
import json
import re
import sys
from pathlib import Path

PALABRAS = r"clave|contrase[nñ]a|password|passwd|pwd|pass|token|secret|api_?key|apikey|auth|csrf|xsrf|otp|pin|session|sess|sid|jwt|bearer|credential|myPass|SII_PASSWORD|SII_CERT_PASS"
NOMBRE = rf"[A-Za-z0-9_.\-]*(?:{PALABRAS})[A-Za-z0-9_.\-]*"
Q = r"\\?[\"']"   # comilla, opcionalmente escapada (dentro de un JSON serializado van como \")
NOQ = r"[^\"'\\]"
RE = [
    (re.compile(r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"), "***JWT***"),
    (re.compile(r"(Bearer\s+)[A-Za-z0-9._~+/=-]{8,}", re.I), r"\1***"),
    (re.compile(rf"((?:^|[?&;]){NOMBRE}=)[^&;\s\"'<>\\]*", re.I | re.M), r"\1***"),
    (re.compile(rf"({Q}{NOMBRE}{Q}\s*:\s*{Q}){NOQ}*({Q})", re.I), r"\1***\2"),
    (re.compile(rf"(name={Q}{NOMBRE}{Q}[^>]*value={Q}){NOQ}*({Q})", re.I), r"\1***\2"),
    (re.compile(rf"(value={Q}){NOQ}*({Q}[^>]*name={Q}{NOMBRE}{Q})", re.I), r"\1***\2"),
    (re.compile(rf"(<input[^>]*type={Q}password{Q}[^>]*value={Q}){NOQ}*({Q})", re.I), r"\1***\2"),
    (re.compile(rf"({NOMBRE}(?:{Q})?\s*[:=]\s*(?:{Q})?)[0-9a-f]{{8}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{12}}", re.I), r"\1***"),
    (re.compile(rf"(\b{NOMBRE}\s*[:=]\s*{Q}){NOQ}{{6,}}({Q})", re.I), r"\1***\2"),
    (re.compile(r"\b[a-f0-9]{32,}\b", re.I), "***HEX***"),
    (re.compile(r"(NETSCAPE_LIVEWIRE\.mac=|(?:TOKEN|CSESSIONID|JSESSIONID|PHPSESSID)=)[^;\s\"]*"), r"\1***"),
]
JWT = re.compile(r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}")
UUID_TRAS = re.compile(rf"{NOMBRE}(?:{Q})?\s*[:=]\s*(?:{Q})?[0-9a-f]{{8}}-[0-9a-f]{{4}}-", re.I)
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)


def tachar(texto: str) -> str:
    for rx, rep in RE:
        texto = rx.sub(rep, texto)
    return texto


def auditar(texto: str) -> dict:
    uuids = {}
    for u in UUID.findall(texto):
        uuids[u.lower()] = uuids.get(u.lower(), 0) + 1
    repetidos = {u: n for u, n in uuids.items() if n >= 3}
    return {"jwt_sin_tachar": len(JWT.findall(texto)), "uuid_tras_nombre_sensible": len(UUID_TRAS.findall(texto)),
            "uuids_repetidos_3_o_mas": repetidos}


# ---- datos personales: reemplazo consistente (mismo algoritmo que pii.js) ----
def _fnv(s: str) -> int:
    h = 0x811C9DC5
    for b in s.encode("utf-8"):
        h ^= b
        h = (h * 0x01000193) & 0xFFFFFFFF
    return h


def _digitos(semilla: str, valor: str, n: int) -> str:
    out, i = "", 0
    while len(out) < n:
        out += str(_fnv(f"{semilla}|{valor}|{i}")).zfill(10)
        i += 1
    return out[:n]


def dv_rut(num: int) -> str:
    s, m = 0, 2
    for c in reversed(str(num)):
        s += int(c) * m
        m = 2 if m == 7 else m + 1
    r = 11 - (s % 11)
    return "0" if r == 11 else "K" if r == 10 else str(r)


def _rut_ficticio(semilla: str, num_real: str):
    n = int(num_real)
    d = int(_digitos(semilla, f"rut:{n}", 7))
    base = 76_000_000 + d % 2_000_000 if n >= 50_000_000 else 10_000_000 + d % 15_000_000
    return str(base), dv_rut(base)


def _con_formato(original: str, nuevos: str) -> str:
    it = iter(nuevos)
    return re.sub(r"\d", lambda m: next(it, "0"), original)


RE_RUT = re.compile(r"\b(\d{1,2}\.?\d{3}\.?\d{3})-([\dkK])\b")
RE_RUT_PARAM = re.compile(r"((?:^|[?&;\"'\s])[A-Za-z_]*rut[A-Za-z_]*(?:\\?[\"']?\s*[:=]\s*\\?[\"']?))(\d{7,8})(?![\d-])", re.I | re.M)
RE_MAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
RE_CEL = re.compile(r"(?<!\d)(\+?56[\s.-]?)?(9[\s.-]?\d{4}[\s.-]?\d{4})(?!\d)")


def reemplazar_pii(texto: str, semilla: str) -> str:
    def rut(m):
        num, dv = _rut_ficticio(semilla, m.group(1).replace(".", ""))
        return _con_formato(m.group(1), num) + "-" + dv
    texto = RE_RUT.sub(rut, texto)
    texto = RE_RUT_PARAM.sub(lambda m: m.group(1) + _rut_ficticio(semilla, m.group(2))[0], texto)
    texto = RE_MAIL.sub(lambda m: f"persona{_digitos(semilla, 'mail:' + m.group(0).lower(), 4)}@ejemplo.cl", texto)
    texto = RE_CEL.sub(lambda m: (m.group(1) or "") + _con_formato(m.group(2), "9" + _digitos(semilla, "cel:" + re.sub(r"\D", "", m.group(2)), 8)), texto)
    return texto


def auditar_pii(texto: str) -> dict:
    return {"ruts": len(RE_RUT.findall(texto)), "correos": len(RE_MAIL.findall(texto)), "celulares": len(RE_CEL.findall(texto))}


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__); return 2
    ruta = Path(sys.argv[1])
    crudo = ruta.read_text(encoding="utf-8")
    antes = auditar(crudo)
    limpio = tachar(crudo)
    pii = "--sin-pii" not in sys.argv
    pii_antes = auditar_pii(limpio)
    if pii:
        import secrets
        limpio = reemplazar_pii(limpio, secrets.token_hex(12))
    despues = auditar(limpio)
    try:
        d = json.loads(limpio)
        d["auditoria"] = {**despues, "limpiado_por": "limpiar_captura.py", "nota": "Conteo tras el segundo tachado. Si no es todo 0, revisa antes de compartir."}
        d["datos_personales"] = ({"reemplazados": True, "antes": pii_antes, "nota": "RUT, correos y celulares sustituidos por ficticios consistentes."}
                                 if pii else {"reemplazados": False, "presentes": pii_antes})
        limpio = json.dumps(d, ensure_ascii=False, indent=1)
    except json.JSONDecodeError:
        pass  # se escribe el texto tachado tal cual
    destino = ruta if "--en-sitio" in sys.argv else ruta.with_suffix(".limpio.json")
    destino.write_text(limpio, encoding="utf-8")
    print(f"antes : JWT {antes['jwt_sin_tachar']}, uuid tras nombre sensible {antes['uuid_tras_nombre_sensible']}, uuids repetidos {len(antes['uuids_repetidos_3_o_mas'])}")
    print(f"después: JWT {despues['jwt_sin_tachar']}, uuid tras nombre sensible {despues['uuid_tras_nombre_sensible']}, uuids repetidos {len(despues['uuids_repetidos_3_o_mas'])}")
    print(f"datos personales: {pii_antes} → {'reemplazados por ficticios' if pii else 'SIN reemplazar (--sin-pii)'}")
    if despues["uuids_repetidos_3_o_mas"]:
        print("  uuids que se repiten (pueden ser ids inocentes o un token con nombre no previsto):")
        for u, n in sorted(despues["uuids_repetidos_3_o_mas"].items(), key=lambda x: -x[1])[:5]:
            print(f"    {u[:8]}… ×{n}")
    print("escrito:", destino)
    return 0 if not (despues["jwt_sin_tachar"] or despues["uuid_tras_nombre_sensible"]) else 1


if __name__ == "__main__":
    sys.exit(main())
