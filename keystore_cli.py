#!/usr/bin/env python
"""
keystore_cli.py — gestión de certificados del SII por cuenta (almacén cifrado).

Una cuenta puede tener VARIOS certificados. El .p12 y su clave se guardan cifrados
(ver core/keystore.py). La clave NUNCA se pasa en texto plano si usas el prompt.

Ejemplos:
    python keystore_cli.py add firma.pfx --cuenta 1 --nombre "rep-legal"  # pide clave por prompt
    python keystore_cli.py list --cuenta 1
    python keystore_cli.py test 3 --cuenta 1        # carga y muestra info del cert
    python keystore_cli.py portal 3 --cuenta 1      # autentica en el SII y muestra situación de folios
    python keystore_cli.py remove 3 --cuenta 1
"""
import argparse
import getpass
import sys

from core import keystore


def _clave(args) -> str:
    return args.password or getpass.getpass("Clave del certificado (.p12): ")


def cmd_add(args):
    with open(args.p12, "rb") as f:
        p12 = f.read()
    try:
        info = keystore.guardar_certificado(args.cuenta, p12, _clave(args),
                                            nombre=args.nombre, alias=args.alias)
    except Exception as e:
        print(f"✗ No se pudo guardar: {e}"); sys.exit(1)
    print(f"✓ Certificado guardado (id={info['id']}): RUT {info['rut']} · vence {info['vencimiento'][:10]}")


def cmd_list(args):
    certs = keystore.listar_certificados(args.cuenta)
    if not certs:
        print(f"(cuenta {args.cuenta} sin certificados)"); return
    print(f"Certificados de la cuenta {args.cuenta}:")
    for c in certs:
        print(f"  [{c['id']}] RUT {c['rut']:12} {c['nombre'] or '':20} vence {c['vencimiento'][:10]}")


def cmd_test(args):
    cert = keystore.cargar_certificado(args.id, args.cuenta)
    print(f"✓ Certificado {args.id} cargado en memoria: RUT {cert.rut_emisor}")
    print(f"  vence: {cert.certificado.not_valid_after}")


def cmd_portal(args):
    from core.sii_portal import PortalSII
    with keystore.pem_transitorio(args.id, args.cuenta) as (cert_pem, key_pem):
        portal = PortalSII(cert_pem, key_pem)
        portal.autenticar()
        print(f"✓ Autenticado en el SII (sesión RUT {portal.rut_sesion})")
        if args.rut:
            sit = portal.situacion_folios(args.rut, tipos=[33, 34, 52, 56, 61])
            print(f"  Situación de timbraje de {args.rut}:")
            for tp, st in sit.items():
                print(f"    T{tp}: {'BLOQUEADO' if st['bloqueado'] else 'ok'}")


def cmd_remove(args):
    ok = keystore.eliminar_certificado(args.cuenta, args.id)
    print("✓ Eliminado" if ok else "✗ No encontrado")


def main():
    p = argparse.ArgumentParser(description="Gestión de certificados SII (almacén cifrado por cuenta)")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("add", help="agregar/actualizar un certificado")
    a.add_argument("p12"); a.add_argument("--cuenta", type=int, required=True)
    a.add_argument("--password"); a.add_argument("--nombre"); a.add_argument("--alias")
    a.set_defaults(func=cmd_add)

    l = sub.add_parser("list", help="listar certificados de una cuenta")
    l.add_argument("--cuenta", type=int, required=True); l.set_defaults(func=cmd_list)

    t = sub.add_parser("test", help="cargar un certificado y mostrar su info")
    t.add_argument("id", type=int); t.add_argument("--cuenta", type=int, required=True)
    t.set_defaults(func=cmd_test)

    pt = sub.add_parser("portal", help="autenticar en el SII con el certificado")
    pt.add_argument("id", type=int); pt.add_argument("--cuenta", type=int, required=True)
    pt.add_argument("--rut", help="RUT de empresa para consultar situación de folios")
    pt.set_defaults(func=cmd_portal)

    r = sub.add_parser("remove", help="eliminar un certificado")
    r.add_argument("id", type=int); r.add_argument("--cuenta", type=int, required=True)
    r.set_defaults(func=cmd_remove)

    args = p.parse_args()
    keystore.init_keystore()
    args.func(args)


if __name__ == "__main__":
    main()
