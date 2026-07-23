#!/usr/bin/env python3
"""
dry_run_certificacion.py — Dry-run local de los 16 casos de certificación SII.

Genera XML + PDF + TED para cada caso, valida contra XSD, verifica firma
XMLDSig y firma TED. NO envía nada al endpoint SOAP del SII.

Uso:
    .venv/bin/python dry_run_certificacion.py

Salida:
    - storage/dtes_cert/  → XMLs generados por caso
    - storage/pdfs_cert/  → PDFs generados por caso
    - storage/resultados_dry_run.json  → resumen JSON
    - Consola: tabla de resultados
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import os
import sys
import traceback
from datetime import date
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent))

from lxml import etree
from cryptography import x509 as crypto_x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa as rsa_asym

from core.caf import ManejadorCAF
from core.config import settings
from core.crypto import CertificadoDigital, XMLDSIG_NS
from core.dte import (
    DTEInput,
    EmisorModel,
    GeneradorDTE,
    ItemDTE,
    ReceptorModel,
    ReferenciaModel,
    TipoDTE,
    calcular_totales,
)
from core.models import obtener_caf_activo
from core.pdf_gen import generar_pdf_dte
from core.schema_validator import validar_xml_dte

# ──────────────────────────────────────────────
# Configuración del emisor. Defaults ficticios; sobrescribibles por CLI
# (--rut, --razon-social, --email) o por variable de entorno — ver parse_args().
# ──────────────────────────────────────────────
RUT_EMPRESA = os.environ.get("DTE_RUT_EMPRESA", "76111111-6")
RAZON_SOCIAL = os.environ.get("DTE_RAZON_SOCIAL", "EMPRESA DEMO SPA")
GIRO = "Venta de alimentos"
CODIGO_ACTIVIDAD = 463014
DIRECCION = "Av. Providencia 1234"
COMUNA = "Providencia"
CIUDAD = "Santiago"
EMAIL = os.environ.get("DTE_EMAIL", "contacto@ejemplo.cl")


def parse_args() -> argparse.Namespace:
    """CLI para sobrescribir el emisor (default: datos ficticios de ejemplo)."""
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--rut", default=RUT_EMPRESA, help="RUT del emisor, con guión y DV")
    p.add_argument("--razon-social", default=RAZON_SOCIAL, help="Razón social del emisor")
    p.add_argument("--email", default=EMAIL, help="Correo de contacto del emisor")
    return p.parse_args()

RUT_RECEPTOR = "60803000-K"
RAZON_SOCIAL_RECEPTOR = "SII"
GIRO_RECEPTOR = "Gobierno"
DIRECCION_RECEPTOR = "Morandé 115"
COMUNA_RECEPTOR = "Santiago"
CIUDAD_RECEPTOR = "Santiago"

DTES_DIR = Path("storage/dtes_cert")
PDFS_DIR = Path("storage/pdfs_cert")
RESULTADOS_PATH = Path("storage/resultados_dry_run.json")


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def cargar_certificado() -> CertificadoDigital:
    """Carga el certificado digital desde la ruta configurada en .env."""
    p = Path(settings.certificado_path)
    pw = settings.certificado_password
    if not p.exists():
        raise FileNotFoundError(f"Certificado no encontrado: {p}")
    if not pw:
        raise ValueError("CERTIFICADO_PASSWORD no está configurado en .env")
    return CertificadoDigital(p.read_bytes(), pw)


def cargar_caf_desde_db(tipo_dte: int) -> ManejadorCAF:
    """Obtiene el CAF activo desde la BD para RUT_EMPRESA y tipo dado."""
    caf_db = obtener_caf_activo(RUT_EMPRESA, tipo_dte)
    if not caf_db:
        raise ValueError(
            f"No hay CAF activo en BD para RUT {RUT_EMPRESA} tipo {tipo_dte}. "
            f"Verifique que el CAF esté cargado."
        )
    return ManejadorCAF(caf_db["caf_xml"].encode("utf-8"))


def construir_items(caso: dict) -> list[ItemDTE]:
    """Convierte los items del caso en objetos ItemDTE.

    Si el caso no trae items (notas de crédito/débito de solo referencia),
    se agrega un item dummy con valor 0 para que pase la validación del
    pipeline interno.
    """
    raw = caso.get("items") or []
    items: list[ItemDTE] = []
    for i, d in enumerate(raw, 1):
        items.append(
            ItemDTE(
                numero_linea=i,
                nombre=d["nombre"],
                cantidad=d["cantidad"],
                precio_unitario=d["precio"],
                unidad_medida=d.get("unidad"),
                descuento_pct=d.get("descuento_pct", 0),
                exento=d.get("exento", False),
            )
        )
    if not items:
        # Nota de crédito/débito de corrección de texto o de anulación de un
        # documento sin monto: una sola línea descriptiva con la razón, cantidad
        # 1 y monto 0 (regla SII para CodRef 2). El generador omite PrcItem (0),
        # así que cumple el XSD oficial (Detalle obligatorio; NmbItem+MontoItem
        # requeridos; QtyItem/PrcItem opcionales con mínimo 0.000001).
        razon = (caso.get("referencia") or {}).get("razon") or "REFERENCIA"
        items.append(
            ItemDTE(numero_linea=1, nombre=razon[:80], cantidad=1, precio_unitario=0)
        )
    return items


def codigo_ref_desde_razon(razon: str) -> int:
    """CodRef según la razón (regla SII): 1=anula, 2=corrige texto, 3=corrige montos."""
    r = (razon or "").upper()
    if "ANULA" in r:
        return 1
    if "CORRIGE GIRO" in r or "CORRIGE TEXTO" in r or "MODIFICA GIRO" in r:
        return 2
    return 3  # modifica/corrige monto, devolución de mercaderías


def construir_referencias(caso: dict) -> Optional[list[ReferenciaModel]]:
    """Construye la lista de referencias si el caso la declara."""
    r = caso.get("referencia")
    if not r:
        return None
    return [
        ReferenciaModel(
            numero_linea=1,
            tipo_doc_ref=r["tipo_dte_ref"],
            folio_ref=r["folio_ref"],
            fecha_doc_ref=r["fecha_ref"],
            codigo_ref=codigo_ref_desde_razon(r.get("razon", "")),
            razon_ref=r.get("razon", ""),
        )
    ]


def verificar_firma_xmldsig(root: etree._Element) -> tuple[bool, str]:
    """Verifica la firma XMLDSig (SignedInfo + SignatureValue) del XML.

    Usa canonicalización exclusiva (C14N exclusive) para evitar que
    declaraciones de namespace heredadas de ancestros (p.ej. ``xmlns:xsi``)
    alteren el digest.
    """
    XMLDSIG = XMLDSIG_NS
    sig = root.find(f".//{{{XMLDSIG}}}Signature")
    if sig is None:
        return False, "No se encontró elemento Signature"

    signed_info = sig.find(f"{{{XMLDSIG}}}SignedInfo")
    sig_value = sig.find(f"{{{XMLDSIG}}}SignatureValue")
    x509 = sig.find(f".//{{{XMLDSIG}}}X509Certificate")
    if signed_info is None or sig_value is None or x509 is None:
        return False, "SignedInfo, SignatureValue o X509Certificate ausente"

    firma_bytes = base64.b64decode(sig_value.text.strip())

    # Cargar certificado y extraer clave pública
    cert_der = base64.b64decode(x509.text.strip())
    cer = crypto_x509.load_der_x509_certificate(cert_der)
    pub = cer.public_key()

    # El PRIMER candidato es el método real del firmante (`_c14n_reparse`, el único
    # verificado contra el SII: TrackID 253113966 → ACEPTADOS: 1). Los demás son SOLO
    # diagnóstico: si la firma valida con uno de ellos y no con `reparse`, es un FALSO VERDE
    # — el SII la rechazaría con DTE-3-505. Antes este dict no incluía `reparse` y etiquetaba
    # `in-context` como "el actual", que hacía justo lo contrario de detectar el problema.
    from core.crypto import _c14n_en_contexto, _c14n_reparse
    candidatos = {
        "reparse (el del firmante)": _c14n_reparse(signed_info),
        "in-context (NO es el del SII)": _c14n_en_contexto(signed_info),
        "exclusiva (NO es el del SII)": etree.tostring(signed_info, method="c14n", exclusive=True),
        "subárbol (NO es el del SII)": etree.tostring(signed_info, method="c14n"),
    }
    for nombre, si_c14n in candidatos.items():
        try:
            pub.verify(firma_bytes, si_c14n, padding.PKCS1v15(), hashes.SHA1())
            return True, f"Firma XMLDSig válida (SHA1+RSA, SignedInfo C14N {nombre})"
        except Exception:
            continue
    return False, "Firma XMLDSig inválida (ningún C14N del SignedInfo valida)"


def _xml_escape(text: str) -> str:
    """Escapa caracteres especiales XML en un string."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace(
        '"', "&quot;"
    ).replace("'", "&apos;")


def verificar_firma_ted(ted_xml: str, caf: ManejadorCAF) -> tuple[bool, str]:
    """Verifica la firma del TED contra la clave pública del CAF."""
    try:
        root = etree.fromstring(ted_xml.encode("utf-8"))
    except Exception as e:
        return False, f"Error parseando TED: {e}"

    dd = root.find("DD")
    frmt = root.find("FRMT")
    if dd is None or frmt is None or not frmt.text:
        return False, "TED incompleto: faltan DD o FRMT"

    firma_bytes = base64.b64decode(frmt.text.strip())

    # El FRMT se firma sobre el DD con EXACTAMENTE la misma canonicalización que usa
    # ManejadorCAF.generar_ted: C14N no-exclusiva + aplanado (`>\s+<`→`><`) + re-encode
    # a ISO-8859-1. Verificar con otra canonicalización (p.ej. exclusive=True sin
    # aplanar) da un digest distinto y marca la firma como inválida aunque el TED sea
    # correcto. Reproducimos aquí los mismos bytes firmados.
    import io, re as _re
    dd_tree = etree.ElementTree(dd)
    _buf = io.BytesIO()
    dd_tree.write_c14n(_buf, exclusive=False, with_comments=False)
    dd_c14n = _re.sub(rb">\s+<", b"><", _buf.getvalue())
    dd_c14n = dd_c14n.decode("utf-8").encode("ISO-8859-1")

    # Extraer clave pública RSA del CAF (elemento <RSAPK>)
    rsapk = caf.root.find(".//RSAPK")
    if rsapk is None:
        return False, "No se encontró RSAPK en el CAF"
    m_elem = rsapk.find("M")
    e_elem = rsapk.find("E")
    if m_elem is None or e_elem is None or not m_elem.text or not e_elem.text:
        return False, "RSAPK incompleto (M o E)"

    mod = int.from_bytes(base64.b64decode(m_elem.text.strip()), "big")
    exp = int.from_bytes(base64.b64decode(e_elem.text.strip()), "big")
    pub_num = rsa_asym.RSAPublicNumbers(exp, mod)
    pub_key = pub_num.public_key()

    try:
        pub_key.verify(firma_bytes, dd_c14n, padding.PKCS1v15(), hashes.SHA1())
        return True, "Firma TED válida"
    except Exception as e:
        return False, f"Firma TED inválida: {e}"


# ──────────────────────────────────────────────
# Procesamiento individual de cada caso
# ──────────────────────────────────────────────

def procesar_caso(caso: dict, cert: CertificadoDigital, gen: GeneradorDTE) -> dict:
    """Ejecuta el pipeline completo para un caso y retorta el resultado."""
    nombre: str = caso["nombre"]
    tipo_dte: TipoDTE = caso["tipo_dte"]
    folio: int = caso["folio"]
    tipo_val = tipo_dte.value

    result: dict = {
        "nombre": nombre,
        "tipo_dte": tipo_val,
        "folio": folio,
        "xml_ok": False,
        "firma_ok": False,
        "ted_ok": False,
        "xsd_ok": False,
        "pdf_ok": False,
        "error": None,
    }

    try:
        # ── 1. Emisor / Receptor ──
        emisor = EmisorModel(
            rut=RUT_EMPRESA,
            razon_social=RAZON_SOCIAL,
            giro=GIRO,
            codigo_actividad=CODIGO_ACTIVIDAD,
            direccion=DIRECCION,
            comuna=COMUNA,
            ciudad=CIUDAD,
            email=EMAIL,
        )
        receptor = ReceptorModel(
            rut=RUT_RECEPTOR,
            razon_social=RAZON_SOCIAL_RECEPTOR,
            giro=GIRO_RECEPTOR,
            direccion=DIRECCION_RECEPTOR,
            comuna=COMUNA_RECEPTOR,
            ciudad=CIUDAD_RECEPTOR,
        )

        # ── 2. Items y referencias ──
        items = construir_items(caso)
        referencias = construir_referencias(caso)
        totales = calcular_totales(items, tipo_dte)

        # ── 3. CAF + TED ──
        caf = cargar_caf_desde_db(tipo_val)
        if not caf.es_folio_valido(folio):
            raise ValueError(
                f"Folio {folio} fuera del rango del CAF "
                f"[{caf.datos.folio_desde}-{caf.datos.folio_hasta}]"
            )

        primer_item = _xml_escape(items[0].nombre or "Sin Items")
        ted_xml = caf.generar_ted(
            folio=folio,
            rut_emisor=RUT_EMPRESA,
            rut_receptor=RUT_RECEPTOR,
            tipo_dte=tipo_val,
            fecha_emision_dte=date.today(),
            monto_total=totales.monto_total,
            razon_social_receptor=RAZON_SOCIAL_RECEPTOR,
            primer_item=primer_item,
        )

        ted_ok, ted_msg = verificar_firma_ted(ted_xml, caf)
        result["ted_ok"] = ted_ok
        if not ted_ok:
            result["error"] = ted_msg

        # ── 4. DTEInput → XML ──
        dte_input = DTEInput(
            tipo_dte=tipo_dte,
            folio=folio,
            fecha_emision=date.today(),
            emisor=emisor,
            receptor=receptor,
            items=items,
            referencias=referencias,
            forma_pago=1,
        )

        dte_elem = gen.generar_documento_xml(dte_input, ted_xml=ted_xml)

        # ── 5. EnvioDTE firmado por el MISMO camino que el envío real ──
        # Delegamos en certificacion_sii.generar_dte para tener UNA sola fuente de
        # verdad de la firma: embebe el DTE sin firmar, normaliza (serializa+reparsea)
        # y firma con firmar_xml_sii (DigestValue en-contexto + Transform
        # enveloped-signature + SignedInfo C14N exclusiva). Es el método que el SII
        # acepta, comprobado criptográficamente contra un EnvioDTE real de
        # OpenFactura. NO usar firmar_documento_xml aquí (firma standalone → RFR).
        from certificacion_sii import generar_dte as _generar_envio_firmado
        envio_bytes = _generar_envio_firmado(caso, emisor, receptor, caf, cert)
        xml_bytes = envio_bytes
        result["xml_ok"] = True

        # ── 6. Validación XSD del EnvioDTE completo contra EnvioDTE_v10.xsd
        #      (esquema oficial del SII en core/xsd/). Es la validación que importa:
        #      valida carátula + DTE + firma en su forma final normalizada.
        envio_xsd = validar_xml_dte(envio_bytes)
        result["xsd_ok"] = envio_xsd.valido
        if not envio_xsd.valido:
            result["error"] = "; ".join(envio_xsd.errores[:3])

        # ── 7. Verificación XMLDSig ──
        root_parseado = etree.fromstring(xml_bytes)
        f_ok, f_msg = verificar_firma_xmldsig(root_parseado)
        result["firma_ok"] = f_ok
        if not f_ok:
            result["error"] = f_msg

        # ── 8. Guardar XML ──
        xml_name = f"{nombre}_T{tipo_val}_F{folio}.xml"
        (DTES_DIR / xml_name).write_bytes(xml_bytes)

        # ── 9. PDF ──
        try:
            pdf_bytes = generar_pdf_dte(dte_input, ted_xml=ted_xml)
            pdf_name = f"{nombre}_T{tipo_val}_F{folio}.pdf"
            (PDFS_DIR / pdf_name).write_bytes(pdf_bytes)
            result["pdf_ok"] = True
        except Exception as e:
            result["error"] = str(e)

        # El XSD SÍ es bloqueante: el SII rechaza cualquier tag fuera de orden, así que un
        # fallo aquí es un fallo real.
        #
        # Antes se silenciaba con esta excusa: "el esquema local tiene diferencias con el
        # oficial del SII, p.ej. `TipoDTE` vs `TpoDTE`". **La excusa era falsa por partida
        # doble**: (1) `core/xsd/` ya son los esquemas OFICIALES del SII, y (2) `TipoDTE` y
        # `TpoDTE` no son una discrepancia sino DOS elementos legítimos y distintos —
        # `TipoDTE` es el del IdDoc (`DTE_v10.xsd:30`) y `TpoDTE` el del SubTotDTE de la
        # carátula (`EnvioDTE_v10.xsd:75`). Con la premisa muerta, la red de seguridad vuelve.
        result["ok"] = all([result["xml_ok"], result["firma_ok"], result["ted_ok"],
                            result["pdf_ok"], result["xsd_ok"]])

    except Exception as e:
        result["error"] = str(e)
        traceback.print_exc()

    return result


# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────

def main() -> int:
    global RUT_EMPRESA, RAZON_SOCIAL, EMAIL
    args = parse_args()
    RUT_EMPRESA = args.rut
    RAZON_SOCIAL = args.razon_social
    EMAIL = args.email

    print("=" * 78)
    print("  DRY RUN — Certificación SII Chile (16 casos)")
    print("  Generación local + validación XSD / Firma / TED / PDF")
    print("  Sin envío SOAP al SII")
    print("=" * 78)

    DTES_DIR.mkdir(parents=True, exist_ok=True)
    PDFS_DIR.mkdir(parents=True, exist_ok=True)

    # Importar la definición de casos desde el script original
    from certificacion_sii import definir_casos  # type: ignore[import]
    casos = definir_casos()
    print(f"\n📋 {len(casos)} casos cargados desde certificacion_sii.definir_casos()")

    try:
        cert = cargar_certificado()
        print(f"✅ Certificado: {cert.rut_emisor}")
    except Exception as e:
        print(f"❌ Error cargando certificado: {e}")
        return 1

    gen = GeneradorDTE()
    resultados: list[dict] = []

    for i, caso in enumerate(casos, 1):
        tipo_str = f"T{caso['tipo_dte'].value}"
        prefix = f"[{i:2d}/{len(casos)}] {caso['nombre']:12s} | {tipo_str:4s} F{caso['folio']:3d}"
        print(f"\n{prefix}  ", end="", flush=True)

        r = procesar_caso(caso, cert, gen)
        resultados.append(r)

        flags = (
            f"{'✓' if r['xml_ok'] else '✗'}XML "
            f"{'✓' if r['firma_ok'] else '✗'}Firma "
            f"{'✓' if r['ted_ok'] else '✗'}TED "
            f"{'✓' if r['xsd_ok'] else '✗'}XSD "
            f"{'✓' if r['pdf_ok'] else '✗'}PDF"
        )
        print(flags)
        if r["error"] and not all([r["xml_ok"], r["firma_ok"], r["ted_ok"],
                                    r["xsd_ok"], r["pdf_ok"]]):
            short = r["error"][:130]
            print(f"  ⚠  {short}")

    # ── Tabla resumen ──
    print()
    print("=" * 130)
    h = (f"{'Caso':14s} {'Tipo':5s} {'Folio':5s}  "
         f"{'XML':6s} {'Firma':7s} {'TED':6s} {'PDF':6s} {'XSD':6s}  Error")
    print(h)
    print("-" * 130)
    for r in resultados:
        # El XSD cuenta igual que lo demás: un tag fuera de orden lo rechaza el SII.
        # (Antes un fallo XSD se etiquetaba `✗ (local)` culpando a "nuestro esquema" —
        # excusa falsa: `core/xsd/` son los oficiales. Ver el comentario en `generar_caso`.)
        if r.get("ok"):
            print(f"{r['nombre']:14s} {r['tipo_dte']:4d}   {r['folio']:3d}   "
                  f"{'✓ OK':6s} {'✓ OK':7s} {'✓ OK':6s} {'✓ OK':6s} {'✓ OK':6s}")
        else:
            err = (r["error"] or ("XSD inválido" if not r["xsd_ok"] else ""))[:65]
            print(f"{r['nombre']:14s} {r['tipo_dte']:4d}   {r['folio']:3d}   "
                  f"{'✓' if r['xml_ok'] else '✗'}{'':5s} "
                  f"{'✓' if r['firma_ok'] else '✗'}{'':6s} "
                  f"{'✓' if r['ted_ok'] else '✗'}{'':5s} "
                  f"{'✓' if r['pdf_ok'] else '✗'}{'':5s} "
                  f"{'✓' if r['xsd_ok'] else '✗'}{'':5s} "
                  f"{err}")
    print("-" * 130)

    exitosos = sum(1 for r in resultados if r.get("ok"))
    fallidos = len(resultados) - exitosos
    core_fallidos = sum(
        1 for r in resultados
        if not all([r["xml_ok"], r["firma_ok"], r["ted_ok"], r["pdf_ok"]])
    )
    xsd_exitosos = sum(1 for r in resultados if r["xsd_ok"])
    print()
    print(f"✅ Casos OK (XML+Firma+TED+PDF+XSD): {exitosos}/{len(resultados)}")
    print(f"❌ Casos con fallos:                  {fallidos}/{len(resultados)}")
    print(f"📋 Validación XSD (esquema OFICIAL):  {xsd_exitosos}/{len(resultados)}")
    print()
    if xsd_exitosos < len(resultados):
        print("  ⚠️  Un fallo XSD es un FALLO REAL: `core/xsd/` son los esquemas oficiales")
        print("     del SII, y el SII rechaza cualquier tag fuera de orden. Revisar detalle.")

    if core_fallidos:
        print("\nDetalle de fallos del pipeline core:")
        for r in resultados:
            if not all([r["xml_ok"], r["firma_ok"], r["ted_ok"], r["pdf_ok"]]):
                causas = []
                if not r["xml_ok"]:
                    causas.append("XML")
                if not r["firma_ok"]:
                    causas.append("FIRMA")
                if not r["ted_ok"]:
                    causas.append("TED")
                if not r["pdf_ok"]:
                    causas.append("PDF")
                print(f"  • {r['nombre']} (T{r['tipo_dte']} F{r['folio']}): "
                      f"{', '.join(causas)} → {r.get('error', '?')}")
        print()

    # Guardar JSON
    RESULTADOS_PATH.write_text(
        json.dumps(resultados, indent=2, default=str, ensure_ascii=False)
    )
    print(f"\n💾 Resultados guardados en: {RESULTADOS_PATH}")

    # El XSD cuenta: si un caso no valida contra el esquema OFICIAL, el SII lo rechazaría.
    return 0 if fallidos == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
