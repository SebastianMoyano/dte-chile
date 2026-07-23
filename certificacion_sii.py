#!/usr/bin/env python3
"""
Script de certificación SII (16 casos del Set de Pruebas).

Genera y envía los 16 casos del Set de Pruebas al SII usando Web Services SOAP.
RUT, razón social, correo y certificado del emisor se configuran por CLI o
variable de entorno (ver `parse_args`); los defaults son datos ficticios de
ejemplo, no de una empresa real.
"""

import argparse
import json
import sys
import os
from pathlib import Path
from datetime import date, datetime

from lxml import etree

# Agregar el directorio raíz al path
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv()


from core.dte import (
    GeneradorDTE,
    DTEInput,
    EmisorModel,
    ReceptorModel,
    ItemDTE,
    TipoDTE,
    ReferenciaModel,
    calcular_totales,
)
from core.caf import ManejadorCAF
from core.crypto import CertificadoDigital, firmar_documento_xml, firmar_xml_sii
from core.sii import ClienteSII, AmbienteSII

def _xml_escape(text: str) -> str:
    """Escapa caracteres especiales XML en un string."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace(
        '"', "&quot;"
    ).replace("'", "&apos;")


# Configuración por defecto (ficticia). Se puede sobrescribir por CLI (--rut,
# --razon-social, --email, --cert) o por variable de entorno — ver parse_args().
RUT_EMPRESA = os.environ.get("DTE_RUT_EMPRESA", "76111111-6")
RAZON_SOCIAL = os.environ.get("DTE_RAZON_SOCIAL", "EMPRESA DEMO SPA")
GIRO = "Venta de alimentos"
CODIGO_ACTIVIDAD = 463014  # Venta de alimentos al por mayor
DIRECCION = "Av. Providencia 1234"
COMUNA = "Providencia"
CIUDAD = "Santiago"
EMAIL = os.environ.get("DTE_EMAIL", "contacto@ejemplo.cl")
CERT_PATH = os.environ.get("DTE_CERT_PATH", "firma.pfx")
KEYCHAIN_SERVICE = os.environ.get("DTE_KEYCHAIN_SERVICE", "dte-cert-firma")

# RUT del receptor (usar uno de prueba)
RUT_RECEPTOR = "60803000-K"  # SII
RAZON_SOCIAL_RECEPTOR = "SII"
GIRO_RECEPTOR = "Gobierno"
DIRECCION_RECEPTOR = "Morandé 115"
COMUNA_RECEPTOR = "Santiago"
CIUDAD_RECEPTOR = "Santiago"


def parse_args():
    """Argumentos de línea de comandos; cada uno cae al default (ficticio) o al env si no se pasa."""
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--rut", default=RUT_EMPRESA, help="RUT del emisor, con guión y DV")
    p.add_argument("--razon-social", default=RAZON_SOCIAL, help="Razón social del emisor")
    p.add_argument("--email", default=EMAIL, help="Correo de contacto del emisor")
    p.add_argument("--cert", default=CERT_PATH, help="Ruta al .pfx del certificado del mandatario")
    return p.parse_args()


# Cargar certificados y CAFs
def obtener_password_cert() -> str:
    """
    Obtiene la contraseña del certificado de la forma más segura disponible,
    sin exponerla en texto plano ni imprimirla:
      1. Llavero de macOS (recomendado): servicio configurable vía DTE_KEYCHAIN_SERVICE.
      2. Variable de entorno CERTIFICADO_PASSWORD (fallback, menos seguro).
      3. Prompt interactivo oculto (si se ejecuta a mano).
    """
    import subprocess
    import getpass
    try:
        r = subprocess.run(
            ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w"],
            capture_output=True, text=True,
        )
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    except FileNotFoundError:
        pass  # no macOS / sin `security`
    pw = os.environ.get("CERTIFICADO_PASSWORD")
    if pw:
        return pw
    return getpass.getpass("Contraseña del certificado (no se mostrará): ")


def cargar_recursos(cert_path: Path):
    """Carga el certificado (del mandatario/representante legal) y los CAFs necesarios."""
    print("Cargando recursos...")

    if not cert_path.exists():
        print(f"❌ Certificado no encontrado: {cert_path}")
        sys.exit(1)

    password = obtener_password_cert()
    if not password:
        print("❌ No se pudo obtener la contraseña (Llavero/env/prompt).")
        sys.exit(1)

    cert_data = cert_path.read_bytes()
    cert = CertificadoDigital(cert_data, password)
    print(f"✅ Certificado cargado: {cert.rut_emisor}")
    
    # Cargar CAFs
    cafs = {}
    caf_dir = Path("storage/cafs")
    for caf_file in caf_dir.glob("*.xml"):
        print(f"Cargando CAF: {caf_file.name}")
        caf_data = caf_file.read_bytes()
        caf = ManejadorCAF(caf_data)
        tipo_dte = caf.datos.tipo_dte
        cafs[tipo_dte] = caf
        print(f"  ✅ T{tipo_dte}: folios {caf.datos.folio_desde}-{caf.datos.folio_hasta}")
    
    return cert, cafs

# Definir los 16 casos del Set de Pruebas
def definir_casos():
    """Define los 16 casos del Set de Pruebas."""
    casos = []
    
    # CASO 4943173-1: Factura Electrónica simple
    casos.append({
        "nombre": "4943173-1",
        "tipo_dte": TipoDTE.FACTURA_ELECTRONICA,
        "folio": 1,
        "items": [
            {"nombre": "Cajón AFECTO", "cantidad": 118, "precio": 628},
            {"nombre": "Relleno AFECTO", "cantidad": 51, "precio": 975},
        ]
    })
    
    # CASO 4943173-2: Factura con descuento por línea
    casos.append({
        "nombre": "4943173-2",
        "tipo_dte": TipoDTE.FACTURA_ELECTRONICA,
        "folio": 2,
        "items": [
            {"nombre": "Pañuelo AFECTO", "cantidad": 175, "precio": 1472, "descuento_pct": 3},
            {"nombre": "ITEM 2 AFECTO", "cantidad": 99, "precio": 538, "descuento_pct": 3},
        ]
    })
    
    # CASO 4943173-3: Factura con item exento
    casos.append({
        "nombre": "4943173-3",
        "tipo_dte": TipoDTE.FACTURA_ELECTRONICA,
        "folio": 3,
        "items": [
            {"nombre": "Pintura B&W AFECTO", "cantidad": 23, "precio": 1298},
            {"nombre": "ITEM 2 AFECTO", "cantidad": 138, "precio": 2915},
            {"nombre": "ITEM 3 SERVICIO EXENTO", "cantidad": 1, "precio": 34637, "exento": True},
        ]
    })
    
    # CASO 4943173-4: Factura con descuento global
    casos.append({
        "nombre": "4943173-4",
        "tipo_dte": TipoDTE.FACTURA_ELECTRONICA,
        "folio": 4,
        "items": [
            {"nombre": "ITEM 1 AFECTO", "cantidad": 43, "precio": 1184},
            {"nombre": "ITEM 2 AFECTO", "cantidad": 19, "precio": 739},
            {"nombre": "ITEM 3 SERVICIO EXENTO", "cantidad": 2, "precio": 6760, "exento": True},
        ],
        "descuento_global_pct": 5,
        "aplica_descuento_a": "afectos"
    })
    
    # CASO 4943173-5: Nota de Crédito (corrige giro)
    casos.append({
        "nombre": "4943173-5",
        "tipo_dte": TipoDTE.NOTA_CREDITO,
        "folio": 80,  # CAF real T61: rango 80-157 (1-79 anulado)
        "referencia": {
            "tipo_dte_ref": TipoDTE.FACTURA_ELECTRONICA,
            "folio_ref": 1,
            "fecha_ref": date.today(),
            "razon": "CORRIGE GIRO DEL RECEPTOR"
        },
        "items": []  # Nota de crédito sin items, solo referencia
    })
    
    # CASO 4943173-6: Nota de Crédito (devolución mercaderías)
    casos.append({
        "nombre": "4943173-6",
        "tipo_dte": TipoDTE.NOTA_CREDITO,
        "folio": 81,
        "referencia": {
            "tipo_dte_ref": TipoDTE.FACTURA_ELECTRONICA,
            "folio_ref": 2,
            "fecha_ref": date.today(),
            "razon": "DEVOLUCION DE MERCADERIAS"
        },
        "items": [
            {"nombre": "Pañuelo AFECTO", "cantidad": 64, "precio": 1472},
            {"nombre": "ITEM 2 AFECTO", "cantidad": 67, "precio": 538},
        ]
    })
    
    # CASO 4943173-7: Nota de Crédito (anula factura)
    casos.append({
        "nombre": "4943173-7",
        "tipo_dte": TipoDTE.NOTA_CREDITO,
        "folio": 82,
        "referencia": {
            "tipo_dte_ref": TipoDTE.FACTURA_ELECTRONICA,
            "folio_ref": 3,
            "fecha_ref": date.today(),
            "razon": "ANULA FACTURA"
        },
        # Anulación total (CodRef 1): la NC espeja los ítems del documento
        # anulado (factura 4943173-3) para acreditar el monto completo.
        "items": [
            {"nombre": "Pintura B&W AFECTO", "cantidad": 23, "precio": 1298},
            {"nombre": "ITEM 2 AFECTO", "cantidad": 138, "precio": 2915},
            {"nombre": "ITEM 3 SERVICIO EXENTO", "cantidad": 1, "precio": 34637, "exento": True},
        ]
    })
    
    # CASO 4943173-8: Nota de Débito (anula nota de crédito)
    casos.append({
        "nombre": "4943173-8",
        "tipo_dte": TipoDTE.NOTA_DEBITO,
        "folio": 80,
        "referencia": {
            "tipo_dte_ref": TipoDTE.NOTA_CREDITO,
            "folio_ref": 80,  # apunta a la NC del caso 4943173-5 (folio 80)
            "fecha_ref": date.today(),
            "razon": "ANULA NOTA DE CREDITO ELECTRONICA"
        },
        "items": []
    })
    
    # CASO 4943176-1: Factura Exenta
    casos.append({
        "nombre": "4943176-1",
        "tipo_dte": TipoDTE.FACTURA_NO_AFECTA,
        "folio": 1,
        "items": [
            {"nombre": "HORAS PROGRAMADOR", "cantidad": 3, "precio": 2844, "unidad": "Hora"},
        ]
    })
    
    # CASO 4943176-2: Nota de Crédito (modifica monto)
    casos.append({
        "nombre": "4943176-2",
        "tipo_dte": TipoDTE.NOTA_CREDITO,
        "folio": 83,
        "referencia": {
            "tipo_dte_ref": TipoDTE.FACTURA_NO_AFECTA,
            "folio_ref": 1,
            "fecha_ref": date.today(),
            "razon": "MODIFICA MONTO"
        },
        "items": [
            {"nombre": "HORAS PROGRAMADOR", "cantidad": 3, "precio": 355, "exento": True},
        ]
    })
    
    # CASO 4943176-3: Factura Exenta con múltiples items
    casos.append({
        "nombre": "4943176-3",
        "tipo_dte": TipoDTE.FACTURA_NO_AFECTA,
        "folio": 2,
        "items": [
            {"nombre": "SERV CONSULTORIA FACT ELECTRONICA", "cantidad": 1, "precio": 191355},
            {"nombre": "SERV CONSULTORIA GUIA DESPACHO ELECT", "cantidad": 1, "precio": 200358},
        ]
    })
    
    # CASO 4943176-4: Nota de Crédito (corrige giro)
    casos.append({
        "nombre": "4943176-4",
        "tipo_dte": TipoDTE.NOTA_CREDITO,
        "folio": 84,
        "referencia": {
            "tipo_dte_ref": TipoDTE.FACTURA_NO_AFECTA,
            "folio_ref": 2,
            "fecha_ref": date.today(),
            "razon": "CORRIGE GIRO"
        },
        "items": []
    })
    
    # CASO 4943176-5: Nota de Débito (anula nota de crédito)
    casos.append({
        "nombre": "4943176-5",
        "tipo_dte": TipoDTE.NOTA_DEBITO,
        "folio": 81,
        "referencia": {
            "tipo_dte_ref": TipoDTE.NOTA_CREDITO,
            "folio_ref": 84,  # apunta a la NC del caso 4943176-4 (folio 84)
            "fecha_ref": date.today(),
            "razon": "ANULA NOTA DE CREDITO ELECTRONICA"
        },
        "items": []
    })
    
    # CASO 4943176-6: Factura Exenta (capacitación)
    casos.append({
        "nombre": "4943176-6",
        "tipo_dte": TipoDTE.FACTURA_NO_AFECTA,
        "folio": 3,
        "items": [
            {"nombre": "CAPACITACION USO CIGUEÑALES", "cantidad": 1, "precio": 277924},
            {"nombre": "CAPACITACION USO PLC's CNC", "cantidad": 1, "precio": 176009},
        ]
    })
    
    # CASO 4943176-7: Nota de Crédito (modifica monto)
    casos.append({
        "nombre": "4943176-7",
        "tipo_dte": TipoDTE.NOTA_CREDITO,
        "folio": 85,
        "referencia": {
            "tipo_dte_ref": TipoDTE.FACTURA_NO_AFECTA,
            "folio_ref": 3,
            "fecha_ref": date.today(),
            "razon": "MODIFICA MONTO"
        },
        "items": [
            {"nombre": "CAPACITACION USO CIGUEÑALES", "cantidad": 1, "precio": 138962, "exento": True},
        ]
    })
    
    # CASO 4943176-8: Nota de Débito (modifica monto)
    casos.append({
        "nombre": "4943176-8",
        "tipo_dte": TipoDTE.NOTA_DEBITO,
        "folio": 82,
        "referencia": {
            "tipo_dte_ref": TipoDTE.FACTURA_NO_AFECTA,
            "folio_ref": 3,
            "fecha_ref": date.today(),
            "razon": "MODIFICA MONTO"
        },
        "items": [
            {"nombre": "CAPACITACION USO PLC's CNC", "cantidad": 1, "precio": 35202, "exento": True},
        ]
    })
    
    return casos

def generar_dte(caso, emisor, receptor, caf, cert):
    """Genera un DTE para un caso específico."""
    print(f"\nGenerando {caso['nombre']}...")
    
    # Crear items (con el dummy item si está vacío)
    items = []
    for i, item_data in enumerate(caso.get("items", []), 1):
        item = ItemDTE(
            numero_linea=i,
            nombre=item_data["nombre"],
            cantidad=item_data["cantidad"],
            precio_unitario=item_data["precio"],
            unidad_medida=item_data.get("unidad"),
            descuento_pct=item_data.get("descuento_pct", 0),
            exento=item_data.get("exento", False),
        )
        items.append(item)
    if not items:
        # Nota de corrección de texto / anulación sin monto: una línea con la
        # razón, cantidad 1, monto 0 (el generador omite PrcItem=0). XSD-válido.
        razon_i = (caso.get("referencia") or {}).get("razon") or "REFERENCIA"
        items.append(
            ItemDTE(numero_linea=1, nombre=razon_i[:80], cantidad=1, precio_unitario=0)
        )

    # Crear referencias
    referencias = None
    r = caso.get("referencia")
    if r:
        # CodRef según la razón (SII): 1=anula, 2=corrige texto, 3=corrige montos.
        razon_r = (r.get("razon") or "").upper()
        if "ANULA" in razon_r:
            cod_ref = 1
        elif "CORRIGE GIRO" in razon_r or "CORRIGE TEXTO" in razon_r or "MODIFICA GIRO" in razon_r:
            cod_ref = 2
        else:
            cod_ref = 3
        referencias = [
            ReferenciaModel(
                numero_linea=1,
                tipo_doc_ref=r["tipo_dte_ref"],
                folio_ref=r["folio_ref"],
                fecha_doc_ref=r["fecha_ref"],
                codigo_ref=cod_ref,
                razon_ref=r.get("razon", ""),
            )
        ]
        
    totales = calcular_totales(items, caso["tipo_dte"])
    
    # Generar TED XML
    primer_item = _xml_escape(items[0].nombre or "Sin Items")
    ted_xml = caf.generar_ted(
        folio=caso["folio"],
        rut_emisor=emisor.rut,
        rut_receptor=receptor.rut,
        tipo_dte=caso["tipo_dte"].value,
        fecha_emision_dte=date.today(),
        monto_total=totales.monto_total,
        razon_social_receptor=receptor.razon_social,
        primer_item=primer_item,
    )
    
    # Crear DTE input
    dte_input = DTEInput(
        tipo_dte=caso["tipo_dte"],
        folio=caso["folio"],
        fecha_emision=date.today(),
        emisor=emisor,
        receptor=receptor,
        items=items,
        referencias=referencias,
        forma_pago=1,  # Contado
    )
    
    # Generar XML del DTE (sin firmar todavía)
    generador = GeneradorDTE()
    dte_xml = generador.generar_documento_xml(dte_input, ted_xml=ted_xml)
    id_ref = f"#T{caso['tipo_dte'].value}F{caso['folio']}"

    # === Firma modo LibreDTE (COMPROBADO contra el SII vivo: resuelve DTE-3-505) ===
    # 1) Firmar el DTE como documento STANDALONE (árbol propio, SIN el xmlns:xsi del sobre
    #    en alcance). Firmar el DTE ya embebido en el sobre re-parseado metía el xmlns:xsi
    #    del EnvioDTE en el contexto del <Documento>, y el SII (que verifica la firma del
    #    DTE extrayéndolo como documento independiente, sin xsi) recomputaba otro digest ->
    #    rechazo "(DTE-3-505) Firma DTE Incorrecta". cryptosys.net/pki/xmldsig-ChileSII:
    #    "no xmlns attributes in the individual DTE when signed" + "do not reformat after signing".
    dte_std = etree.fromstring(etree.tostring(dte_xml, encoding="ISO-8859-1"))
    firmar_xml_sii(dte_std, cert, uri=id_ref)
    dte_signed = etree.tostring(dte_std, encoding="unicode")

    # 2) Armar el sobre como STRING, insertando el DTE firmado VERBATIM (sin re-parsear el
    #    DTE interno: así se preservan exactos los bytes que se firmaron).
    _ts = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    _caratula = (
        f'<Caratula version="1.0"><RutEmisor>{emisor.rut}</RutEmisor>'
        f'<RutEnvia>{cert.rut_emisor}</RutEnvia><RutReceptor>{RUT_RECEPTOR}</RutReceptor>'
        f'<FchResol>2026-07-08</FchResol><NroResol>0</NroResol><TmstFirmaEnv>{_ts}</TmstFirmaEnv>'
        f'<SubTotDTE><TpoDTE>{caso["tipo_dte"].value}</TpoDTE><NroDTE>1</NroDTE></SubTotDTE></Caratula>'
    )
    envio_str = (
        '<EnvioDTE xmlns="http://www.sii.cl/SiiDte" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        'xsi:schemaLocation="http://www.sii.cl/SiiDte EnvioDTE_v10.xsd" version="1.0">'
        f'<SetDTE ID="SetDoc">{_caratula}{dte_signed}</SetDTE></EnvioDTE>'
    )

    # 3) Firmar el sobre: parsear (read-only) para calcular la firma del SetDTE, extraer la
    #    <Signature> del sobre e insertarla por STRING (sin re-serializar el DTE interno).
    _ds = "http://www.w3.org/2000/09/xmldsig#"
    envio_parsed = etree.fromstring(envio_str)
    firmar_xml_sii(envio_parsed, cert, uri="#SetDoc")
    _sig = etree.tostring(envio_parsed.findall(f"{{{_ds}}}Signature")[-1], encoding="unicode")
    final_str = envio_str[: -len("</EnvioDTE>")] + _sig + "</EnvioDTE>"
    xml_bytes = b'<?xml version="1.0" encoding="ISO-8859-1"?>\n' + final_str.encode("ISO-8859-1")

    print(f"  ✅ EnvioDTE generado: {len(xml_bytes)} bytes")

    return xml_bytes


def main():
    """Ejecuta el proceso de certificación."""
    args = parse_args()
    rut_empresa = args.rut
    razon_social = args.razon_social
    email = args.email
    cert_path = Path(args.cert)

    print("=" * 60)
    print(f"CERTIFICACIÓN SII - {razon_social} ({rut_empresa})")
    print("=" * 60)

    # Cargar recursos
    cert, cafs = cargar_recursos(cert_path)

    # Verificar que tenemos todos los CAFs necesarios
    tipos_necesarios = [
        TipoDTE.FACTURA_ELECTRONICA,
        TipoDTE.FACTURA_NO_AFECTA,
        TipoDTE.NOTA_CREDITO,
        TipoDTE.NOTA_DEBITO,
    ]
    
    for tipo in tipos_necesarios:
        if tipo not in cafs:
            print(f"❌ Falta CAF para T{tipo.value}")
            sys.exit(1)
    
    print(f"\n✅ Todos los CAFs cargados correctamente")
    
    # Crear emisor y receptor
    emisor = EmisorModel(
        rut=rut_empresa,
        razon_social=razon_social,
        giro=GIRO,
        codigo_actividad=CODIGO_ACTIVIDAD,
        direccion=DIRECCION,
        comuna=COMUNA,
        ciudad=CIUDAD,
        email=email,
    )
    
    receptor = ReceptorModel(
        rut=RUT_RECEPTOR,
        razon_social=RAZON_SOCIAL_RECEPTOR,
        giro=GIRO_RECEPTOR,
        direccion=DIRECCION_RECEPTOR,
        comuna=COMUNA_RECEPTOR,
        ciudad=CIUDAD_RECEPTOR,
    )
    
    # Definir casos
    casos = definir_casos()
    print(f"\n📋 {len(casos)} casos definidos para el Set de Pruebas")
    
    # Crear cliente SII
    cliente_sii = ClienteSII(cert, AmbienteSII.CERTIFICACION)
    
    # Generar y enviar cada caso
    resultados = []
    for i, caso in enumerate(casos, 1):
        print(f"\n[{i}/{len(casos)}] Procesando caso {caso['nombre']}")
        
        try:
            # Obtener CAF correspondiente
            caf = cafs[caso["tipo_dte"]]
            
            # Generar DTE
            xml_bytes = generar_dte(caso, emisor, receptor, caf, cert)
            
            # Guardar XML localmente
            xml_path = Path(f"storage/dtes/caso_{caso['nombre']}.xml")
            xml_path.parent.mkdir(parents=True, exist_ok=True)
            xml_path.write_bytes(xml_bytes)
            print(f"  💾 XML guardado: {xml_path}")
            
            # Enviar al SII
            print(f"  📤 Enviando al SII...")
            track_id, _msg_envio = cliente_sii.enviar_dte(
                xml_bytes,
                rut_empresa=rut_empresa.split("-")[0],
                dv_empresa=rut_empresa.split("-")[1],
                tipo_dte=caso["tipo_dte"].value,
            )

            print(f"  ✅ Enviado - TrackID: {track_id}")
            
            resultados.append({
                "caso": caso["nombre"],
                "estado": "enviado",
                "track_id": track_id,
            })
            
        except Exception as e:
            print(f"  ❌ Error: {e}")
            resultados.append({
                "caso": caso["nombre"],
                "estado": "error",
                "error": str(e),
            })
    
    # Resumen final
    print("\n" + "=" * 60)
    print("RESUMEN DE CERTIFICACIÓN")
    print("=" * 60)
    
    exitosos = [r for r in resultados if r["estado"] == "enviado"]
    fallidos = [r for r in resultados if r["estado"] == "error"]
    
    print(f"\n✅ Exitosos: {len(exitosos)}/{len(resultados)}")
    print(f"❌ Fallidos: {len(fallidos)}/{len(resultados)}")
    
    if fallidos:
        print("\nCasos con errores:")
        for r in fallidos:
            print(f"  - {r['caso']}: {r['error']}")
    
    # Guardar resultados
    resultados_path = Path("storage/resultados_certificacion.json")
    resultados_path.write_text(json.dumps(resultados, indent=2))
    print(f"\n💾 Resultados guardados en: {resultados_path}")
    
    print("\n" + "=" * 60)
    print("PRÓXIMOS PASOS:")
    print("=" * 60)
    print("1. Consultar estado de cada envío en el SII")
    print("2. Si hay rechazos, corregir y reenviar")
    print("3. Una vez aceptados, declarar cumplimiento en el SII")
    print("4. Solicitar paso a producción")

if __name__ == "__main__":
    main()
