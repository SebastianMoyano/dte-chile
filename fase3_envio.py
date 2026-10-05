#!/usr/bin/env python3
"""
fase3_envio.py — Fase 3B del port: el núcleo en Go EMITE, Python ENVÍA al SII de certificación.

Un solo documento por corrida, con la empresa configurada en el .env (EMPRESA_*), el
certificado (cert=… o CERTIFICADO_PATH/DTE_CERT_PATH, clave desde el Llavero
`sii-clave-certificado`) y el CAF activo de la base. Antes de enviar se comprueba que lo que
Go emitió lo reproduce Python puro byte a byte y que valida XSD.

Solo ambiente de CERTIFICACIÓN (Maullín). Consume un folio de certificación.
    .venv/bin/python fase3_envio.py [rut=XXXXXXXX-X] [cert=firma.pfx] [tipo=34]

Primera corrida (2026-10-05): T34, ACEPTADOS=1, TrackID 261542052 — el primer documento
emitido por el núcleo en Go que el SII acepta.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).parent
sys.path.insert(0, str(RAIZ))
from core.crypto import CertificadoDigital  # noqa: E402
from core.models import marcar_enviados_por_xml, obtener_caf_activo  # noqa: E402
from core.resolucion import resolucion_emisor  # noqa: E402
from core.schema_validator import validar_xml_dte_strict  # noqa: E402
from core.sii import AmbienteSII, ClienteSII  # noqa: E402
from tests.dorado import privado  # noqa: E402

ARGS = {a.split("=")[0]: a.split("=", 1)[1] for a in sys.argv[1:] if "=" in a}
from core.config import settings  # noqa: E402

RUT_EMISOR = ARGS.get("rut") or settings.empresa_rut
if not RUT_EMISOR or "-" not in RUT_EMISOR:
    sys.exit("Falta el RUT del emisor: rut=XXXXXXXX-X o EMPRESA_RUT en .env")
RUT, DV = RUT_EMISOR.split("-")
PFX = Path(ARGS.get("cert") or settings.certificado_path or os.environ.get("DTE_CERT_PATH", "firma.pfx"))
GO = RAIZ / "nucleo" / "bin" / "nucleo-emitir"
TIPO = int(ARGS.get("tipo", 34))

clave = privado.clave_llavero()
cert = CertificadoDigital(PFX.read_bytes(), clave)
caf = obtener_caf_activo(RUT_EMISOR, TIPO)
if not caf or caf["folio_siguiente"] > caf["folio_hasta"]:
    sys.exit(f"Sin folios T{TIPO} de certificación para {RUT_EMISOR}: {caf}")
resol = resolucion_emisor(RUT_EMISOR, "certificacion")
print(f"[1] Emitir con Go: {RUT_EMISOR} T{TIPO}, folio siguiente {caf['folio_siguiente']} (CAF {caf['folio_desde']}-{caf['folio_hasta']}), resolución {resol}")

# Emisor desde la configuración del motor (EMPRESA_* del .env); receptor: el SII (como en el
# set de pruebas); un ítem exento de prueba. Sin giro/actividad/dirección el SII rechaza.
faltan = [k for k in ("empresa_razon_social", "empresa_giro", "empresa_codigo_actividad",
                      "empresa_direccion", "empresa_comuna", "empresa_ciudad") if not getattr(settings, k)]
if faltan:
    sys.exit("Faltan en .env: " + ", ".join(k.upper() for k in faltan))
documento = {
    "tipo_dte": TIPO, "folio": 0, "fecha_emision": time.strftime("%Y-%m-%d"), "forma_pago": 1,
    "emisor": {"rut": RUT_EMISOR, "razon_social": settings.empresa_razon_social, "giro": settings.empresa_giro,
               "codigo_actividad": settings.empresa_codigo_actividad, "direccion": settings.empresa_direccion,
               "comuna": settings.empresa_comuna, "ciudad": settings.empresa_ciudad},
    "receptor": {"rut": "60803000-K", "razon_social": "SII", "giro": "Gobierno", "direccion": "Morande 115",
                 "comuna": "Santiago", "ciudad": "Santiago"},
    "items": [{"numero_linea": 1, "nombre": "Servicio exento de prueba (port Go)", "cantidad": 1, "precio_unitario": 10000}],
}
if TIPO in (33, 39):
    documento["items"][0]["nombre"] = "Servicio afecto de prueba (port Go)"
r = subprocess.run([str(GO), "--db", "dte_database.db", "--storage", "storage", "--cert", str(PFX),
                    "--ambiente", "certificacion", "--resolucion-fecha", resol[0], "--resolucion-numero", str(resol[1])],
                   input=json.dumps(documento), capture_output=True, text=True, env=dict(os.environ, NUCLEO_CERT_CLAVE=clave))
if r.returncode != 0:
    sys.exit("Go falló: " + r.stderr)
res = json.loads(r.stdout)
folio = res["folio"]
print(f"    ✓ Go emitió T{TIPO} folio {folio}: {res['xml_envio_path']} (dte_id {res['dte_id']})")

print("[2] Comprobar en local antes de enviar")
env_path, doc_path = Path(res["xml_envio_path"]), Path(res["xml_dte_path"])
ok = privado.correr(f"{TIPO}_{folio}", env_path, doc_path, clave)
if not ok:
    sys.exit("    ✗ El sobre de Go NO lo reproduce Python puro: no se envía.")
xml = env_path.read_bytes()
validar_xml_dte_strict(xml)
print("    ✓ Python puro reproduce el sobre de Go byte a byte y valida XSD")

print("[3] Enviar a Maullín (certificación)")
cli = ClienteSII(cert, AmbienteSII.CERTIFICACION)
track, msg = cli.enviar_dte(xml, rut_empresa=RUT, dv_empresa=DV, tipo_dte=TIPO)
print(f"    ✓ TrackID {track} — {msg}")
marcar_enviados_por_xml(xml, track, "certificacion")

print("[4] Esperar el veredicto (EPR no es 'aceptado': mirar ACEPTADOS/RECHAZADOS)")
import re
resultado = {"track_id": track, "tipo_dte": TIPO, "folio": folio, "emitido_por": "nucleo-emitir (Go)", "enviado_por": "core/sii.py"}
for intento in range(14):
    time.sleep(30 if intento else 20)
    est = cli.consultar_estado_track(track, RUT, DV)
    raw = est.get("respuesta_raw", "")
    import html
    des = html.unescape(raw)
    cuentas = {k: (re.search(rf"<{k}>(\d+)</{k}>", des) or [None, None])[1] for k in ("INFORMADOS", "ACEPTADOS", "RECHAZADOS", "REPAROS")}
    print(f"    [{intento + 1}] estado {est['estado']} · {est['glosa']} · {cuentas}")
    resultado.update(estado=est["estado"], glosa=est["glosa"], cuentas=cuentas)
    if est["estado"] not in ("-11", "", "DESCONOCIDO") and (cuentas["ACEPTADOS"] is not None or est["estado"] in ("RCT", "RFR", "RSC", "RCH", "FAU", "FAN")):
        break
(RAIZ / "storage" / "fase3_resultado.json").write_text(json.dumps(resultado, ensure_ascii=False, indent=1), encoding="utf-8")
veredicto = "ACEPTADO" if cuentas.get("ACEPTADOS") == "1" else ("RECHAZADO" if cuentas.get("RECHAZADOS") == "1" else "SIN VEREDICTO TODAVÍA")
print(f"\n{veredicto} — T{TIPO} folio {folio}, TrackID {track}, estado {resultado.get('estado')} ({resultado.get('glosa')})")
if veredicto != "ACEPTADO":
    print("Respuesta cruda (recortada):", des[:1200])
