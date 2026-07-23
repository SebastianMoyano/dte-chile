"""
reenviar_certificacion.py — Reenvía el Set de Pruebas con CAF FRESCOS, por OLAS.

Diagnóstico final (ver memoria certificacion-caf-vencido):
  - El bloqueo real era `CAF-3-517` (CAF vencido: Firma_DTE − FA_CAF > 6 meses).
    Los CAF viejos (FA 2025-02-10) están vencidos.
  - El pipeline es CORRECTO: 3 T34 (F90-92) ya fueron ACEPTADOS por el SII vivo.

Este script usa un CAF fresco (FA 2026-07) por folio, sacados de a uno vía httpx
(en /tmp/of_ref). Envía por OLAS para respetar las referencias del set y no quemar
folios escasos con `REF-3-750` (DTE referenciado no recibido):
  ola 1 = T33 (facturas base, sin referencias)
  ola 2 = T61 (notas de crédito → referencian T33 de la ola 1 y T34 ya aceptados)
  ola 3 = T56 (notas de débito → referencian T61 de la ola 2 y T34 ya aceptados)

Uso:  .venv/bin/python reenviar_certificacion.py <ola:1|2|3>
"""
from __future__ import annotations

import sys
from pathlib import Path

import certificacion_sii as C
from core.dte import EmisorModel, ReceptorModel
from core.caf import ManejadorCAF
from core.crypto import CertificadoDigital
from core.sii import AmbienteSII, ClienteSII

OF = "/tmp/of_ref"

# (tipo, folio_viejo) -> folio_nuevo (fresco). El caso T61 4943176-7 (F85) queda
# FUERA: nos falta 1 folio T61 fresco (timbraje bloqueado). Nadie lo referencia.
REMAP = {
    (33, 1): 100, (33, 2): 101, (33, 3): 102, (33, 4): 103,
    (34, 1): 90,  (34, 2): 91,  (34, 3): 92,   # T34 YA aceptados (no se reenvían)
    (61, 80): 158, (61, 81): 159, (61, 82): 160, (61, 83): 161, (61, 84): 162,
    (56, 80): 158, (56, 81): 159, (56, 82): 160,
}

# CAF fresco (FA 2026-07) por (tipo, folio_nuevo).
CAF_POR_FOLIO = {
    (33, 100): f"{OF}/CAF_T33_folio100.xml", (33, 101): f"{OF}/CAF_T33_folio101.xml",
    (33, 102): f"{OF}/CAF_T33_f102.xml",     (33, 103): f"{OF}/CAF_T33_f103.xml",
    (61, 158): f"{OF}/CAF_T61_f158.xml", (61, 159): f"{OF}/CAF_T61_f159.xml",
    (61, 160): f"{OF}/CAF_T61_f160.xml", (61, 161): f"{OF}/CAF_T61_f161.xml",
    (61, 162): f"{OF}/CAF_T61_f162.xml",
    (56, 158): f"{OF}/CAF_T56_158_158.xml", (56, 159): f"{OF}/CAF_T56_f159.xml",
    (56, 160): f"{OF}/CAF_T56_f160.xml",
}

# Casos por ola (4943176-7 T61 y los 3 T34 ya aceptados quedan fuera).
OLAS = {
    1: ["4943173-1", "4943173-2", "4943173-3", "4943173-4"],            # T33
    2: ["4943173-5", "4943173-6", "4943173-7", "4943176-2", "4943176-4"],  # T61
    3: ["4943173-8", "4943176-5", "4943176-8"],                         # T56
}


def renumerar(caso: dict) -> dict:
    c = dict(caso)
    t = c["tipo_dte"].value
    c["folio"] = REMAP[(t, c["folio"])]
    ref = c.get("referencia")
    if ref:
        ref = dict(ref)
        clave = (ref["tipo_dte_ref"], ref["folio_ref"])
        if clave in REMAP:
            ref["folio_ref"] = REMAP[clave]
        c["referencia"] = ref
    return c


def main(argv=None) -> int:
    argv = argv or sys.argv[1:]
    if not argv or argv[0] not in ("1", "2", "3"):
        print("Uso: reenviar_certificacion.py <ola:1|2|3>"); return 1
    ola = int(argv[0])
    nombres = set(OLAS[ola])
    print(f"{'='*60}\nREENVÍO CERTIFICACIÓN — OLA {ola}  (CAF frescos)\n{'='*60}")

    password = C.obtener_password_cert()
    cert = CertificadoDigital(Path(C.CERT_PATH).read_bytes(), password)
    print(f"✅ Certificado: {cert.rut_emisor}")

    emisor = EmisorModel(
        rut=C.RUT_EMPRESA, razon_social=C.RAZON_SOCIAL, giro=C.GIRO,
        codigo_actividad=C.CODIGO_ACTIVIDAD, direccion=C.DIRECCION,
        comuna=C.COMUNA, ciudad=C.CIUDAD, email=C.EMAIL)
    receptor = ReceptorModel(
        rut=C.RUT_RECEPTOR, razon_social=C.RAZON_SOCIAL_RECEPTOR,
        giro=C.GIRO_RECEPTOR, direccion=C.DIRECCION_RECEPTOR,
        comuna=C.COMUNA_RECEPTOR, ciudad=C.CIUDAD_RECEPTOR)

    cliente = ClienteSII(cert, AmbienteSII.CERTIFICACION)
    casos = [renumerar(c) for c in C.definir_casos() if c["nombre"] in nombres]

    resultados = []
    for caso in casos:
        t = caso["tipo_dte"].value
        caf = ManejadorCAF(Path(CAF_POR_FOLIO[(t, caso["folio"])]).read_bytes())
        print(f"\n{caso['nombre']}  T{t} F{caso['folio']}  (CAF FA={caf.datos.fecha_autorizacion})")
        try:
            xml_bytes = C.generar_dte(caso, emisor, receptor, caf, cert)
            Path(f"storage/dtes/ola{ola}_{caso['nombre']}_T{t}_F{caso['folio']}.xml").write_bytes(xml_bytes)
            track_id, _ = cliente.enviar_dte(
                xml_bytes, rut_empresa=C.RUT_EMPRESA.split("-")[0],
                dv_empresa=C.RUT_EMPRESA.split("-")[1], tipo_dte=t)
            print(f"   ✅ TrackID: {track_id}")
            resultados.append({"caso": caso["nombre"], "tipo": t,
                               "folio": caso["folio"], "track_id": track_id})
        except Exception as e:
            print(f"   ❌ {e}")
            resultados.append({"caso": caso["nombre"], "error": str(e)})

    ok = [r for r in resultados if "track_id" in r]
    print(f"\n{'='*60}\nOLA {ola}: enviados {len(ok)}/{len(casos)}")
    print("TrackIDs:", {r['caso']: r['track_id'] for r in ok})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
