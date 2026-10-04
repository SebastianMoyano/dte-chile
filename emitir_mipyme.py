"""
emitir_mipyme.py — Emite una factura exenta (T34) o la NC de anulación (T61) por el canal
MIPYME (Sistema de Facturación Gratuito del SII), sin navegador. Ver `docs/MIPYME.md`.

⚠️ PRODUCCIÓN. No hay sandbox. Por defecto es DRY-RUN: abre sesión, lee el form pre-llenado,
arma el payload y muestra el resumen. Solo con `--emitir` gasta el folio y emite, y como ninguna
cadena está verificada desde este repo (`CADENAS_VERIFICADAS` vacía) exige además
`--acepto-riesgo-folio`: si falla después de GenXMLFirma se pierde el folio (ya pasó: NC 57,
2026-10-02). La evidencia de un fallo queda en storage/mipyme_fallidos/.

Las dos claves salen del Llavero de macOS o se piden por consola (nunca por argumento ni .env):
  - clave tributaria      → login              (Llavero: servicio sii-clave-tributaria, cuenta <rut>)
  - clave del certificado → firma central      (Llavero: servicio sii-clave-certificado, cuenta <rut>)
  security add-generic-password -s sii-clave-tributaria -a 12.345.678-9   ← sin -w, la pide oculta

Uso:
  .venv/bin/python emitir_mipyme.py --usuario 12.345.678-9 --empresa 77.777.777-7 \\
      --receptor 76.111.111-6 --razon "CLIENTE SPA" --giro "SALUD" --dir "CAMINO 1" \\
      --ciudad Chillan --comuna CHILLAN --glosa Arriendo --precio 3270323 \\
      --detalle "-Octubre PAGO DE : 3.270.323"                # dry-run
  ... --emitir                                                 # emite de verdad (1 folio)
  ... --emitir --guardar                                       # y lo registra en la BD

  NC de anulación del documento con DHDR=<id>, folio 57 del 2026-09-06 (mismos ítems):
  ... --anular-dhdr <id> --folio-ref 57 --fecha-ref 2026-09-06 --emitir
"""
from __future__ import annotations

import argparse
import getpass
import sys
from datetime import date
from pathlib import Path

from core.errors import DTEChileError
from core.sii_mipyme import (LLAVERO_CLAVE_CERTIFICADO, LLAVERO_CLAVE_TRIBUTARIA, ClienteMipyme,
                             ItemMipyme, ReceptorMipyme, TIPO_FACTURA_EXENTA, clave_desde_llavero,
                             registrar_en_bd)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--usuario", required=True, help="RUT (con DV) de quien entra al SII")
    ap.add_argument("--empresa", required=True, help="RUT (con DV) de la empresa emisora")
    ap.add_argument("--receptor", required=True)
    ap.add_argument("--razon", required=True)
    ap.add_argument("--giro", required=True)
    ap.add_argument("--dir", required=True)
    ap.add_argument("--ciudad", required=True)
    ap.add_argument("--comuna", required=True)
    ap.add_argument("--glosa", default="Arriendo", help="nombre del ítem")
    ap.add_argument("--precio", type=int, required=True)
    ap.add_argument("--detalle", default="", help="descripción del ítem")
    ap.add_argument("--fecha", default=date.today().isoformat())
    ap.add_argument("--forma-pago", default="2", help="1 contado, 2 crédito")
    ap.add_argument("--anular-dhdr", help="DHDR_CODIGO del documento a anular (NC 61, código 1)")
    ap.add_argument("--corregir-dhdr", help="DHDR_CODIGO del documento cuyo monto se corrige (NC 61, código 3; por el total lo deja en cero)")
    ap.add_argument("--folio-ref", type=int, help="folio del documento a anular")
    ap.add_argument("--tipo-ref", type=int, default=34, help="tipo del documento a anular (34 exenta, 33 afecta)")
    ap.add_argument("--fecha-ref", help="fecha (YYYY-MM-DD) del documento a anular")
    ap.add_argument("--emitir", action="store_true", help="EMITE de verdad (gasta 1 folio en PRODUCCIÓN)")
    ap.add_argument("--acepto-riesgo-folio", action="store_true",
                    help="necesario para tipos cuya cadena NO está verificada (p.ej. notas): si falla tras GenXMLFirma se pierde el folio")
    ap.add_argument("--guardar", action="store_true", help="registra el documento en la BD del motor")
    ap.add_argument("--salida", default="storage/pdfs", help="carpeta para el PDF")
    a = ap.parse_args()

    if (a.anular_dhdr or a.corregir_dhdr) and not (a.folio_ref and a.fecha_ref):
        ap.error("--anular-dhdr/--corregir-dhdr necesitan --folio-ref y --fecha-ref")

    receptor = ReceptorMipyme(rut=a.receptor, razon_social=a.razon, giro=a.giro,
                              direccion=a.dir, ciudad=a.ciudad, comuna=a.comuna)
    items = [ItemMipyme(nombre=a.glosa, precio=a.precio, descripcion=a.detalle)]

    print(f"Canal MIPYME → PRODUCCIÓN. Usuario {a.usuario}, empresa {a.empresa}.")
    clave_trib = (clave_desde_llavero(LLAVERO_CLAVE_TRIBUTARIA, a.usuario)
                  or getpass.getpass("Clave tributaria (login): "))
    clave_cert = ""
    if a.emitir:
        clave_cert = (clave_desde_llavero(LLAVERO_CLAVE_CERTIFICADO, a.usuario)
                      or getpass.getpass("Clave del certificado (firma central): "))

    try:
        with ClienteMipyme(a.usuario, clave_trib, clave_cert) as cli:
            cli.iniciar_sesion()
            cli.seleccionar_empresa(a.empresa)
            if a.corregir_dhdr:
                payload = cli.preparar_nc_correccion_montos(a.corregir_dhdr, a.tipo_ref, a.folio_ref,
                                                            a.fecha_ref, receptor, items, a.fecha)
            elif a.anular_dhdr:
                payload = cli.preparar_nc_anulacion(a.anular_dhdr, a.tipo_ref, a.folio_ref,
                                                    a.fecha_ref, receptor, items, a.fecha)
            else:
                payload = cli.preparar(TIPO_FACTURA_EXENTA, receptor, items, a.fecha, a.forma_pago)

            print(f"\nTipo {payload.tipo} | emisor según el portal: {payload.valor('EFXP_RZN_SOC')} "
                  f"| receptor {receptor.rut} {receptor.razon_social} | total ${payload.monto_total:,}"
                  .replace(",", "."))
            if payload.campos_nuevos:
                print(f"⚠️ el form del SII trae campos que el schema no conoce: {payload.campos_nuevos}")
            claves = ("PTDC_CODIGO", "EHDR_CODIGO", "PTES_ESTADO", "EFXP_DOC_REF_RAIZ", "ES_BORR", "EFXP_FMA_PAGO",
                      "EFXP_FCH_EMIS", "EFXP_NMB_01", "EFXP_QTY_01", "EFXP_PRC_01", "EFXP_SUBT_01", "EFXP_DSC_ITEM_01",
                      "EFXP_SUBTOTAL", "EFXP_MNT_NETO", "EFXP_MNT_TOTAL", "EFXP_TPO_DOC_REF_001", "EFXP_FOLIO_REF_001",
                      "EFXP_FCH_REF_001", "EFXP_CODIGO_REF_001", "EFXP_RAZON_REF_001")
            print("Campos clave del documento:")
            for k in claves:
                print(f"  {k:24} = {payload.valor(k)!r}")
            if not a.emitir:
                print("\n[DRY-RUN] no se emitió nada. Agrega --emitir para gastar el folio y emitir.")
                return 0

            res = cli.emitir(payload, confirmar=True, aceptar_riesgo_folio=a.acepto_riesgo_folio)
            print(f"\n✅ EMITIDO: tipo {res.tipo} folio {res.folio} DHDR={res.dhdr}")
            if res.pdf:
                out = Path(a.salida)
                out.mkdir(parents=True, exist_ok=True)
                ruta = out / f"mipyme_T{res.tipo}_F{res.folio}_{a.fecha}.pdf"
                ruta.write_bytes(res.pdf)
                print(f"   PDF: {ruta}")
            if a.guardar:
                dte_id = registrar_en_bd(res, a.empresa, receptor, a.fecha)
                print(f"   registrado en la BD (id {dte_id}, estado emitido_mipyme)")
            return 0
    except DTEChileError as e:
        print(f"\n❌ {e.codigo}: {e.mensaje}")
        for k, v in e.detalle.items():
            print(f"   {k}: {v}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
