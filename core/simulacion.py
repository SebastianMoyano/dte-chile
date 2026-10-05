"""
core/simulacion.py — El mundo de práctica: EMPRESA DEMO SPA.

Primer tramo del curso (docs/aprender/00-plan.md): emitir boletas, facturas y notas de
crédito que se **forman, se firman, se timbran y se ven igual que las reales**, pero que
nunca salen del computador. Usa el mismo pipeline que producción (`core/orchestrator.py`),
con tres diferencias que lo hacen inofensivo:

1. **Emisor ficticio** (RUT 77.777.777-7, ley L14) con un **CAF de mentira** por tipo de
   documento: la firma del SII en el CAF es un placeholder, así que ningún documento
   podría ser aceptado aunque alguien lo enviara. El TED sí se firma con la clave del CAF,
   por eso el timbre PDF417 se ve real.
2. **Certificado autofirmado** generado en memoria en cada proceso (nunca se guarda).
3. **Nada se envía.** El orquestador solo genera, firma, hace el PDF y persiste. Los
   documentos quedan con `ambiente='simulacion'` y `estado='simulado'`, y sus archivos en
   `storage/simulacion/` para no pisar los de una empresa real con el mismo folio.

La resolución del emisor se fija en memoria (`fijar_resolucion_local`) para que el pipeline
no consulte al SII. Todo este módulo funciona sin red.
"""
from __future__ import annotations

import base64
import shutil
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID

from core import database
from core.config import settings
from core.crypto import CertificadoDigital
from core.dte import DTEInput, EmisorModel, ItemDTE, ReceptorModel, ReferenciaModel, TipoDTE
from core.errors import RecursoNoEncontrado, ValidacionError
from core.models import obtener_caf_activo, obtener_dte, registrar_caf
from core.orchestrator import emitir_documento
from core.resolucion import fijar_resolucion_local

RUT_DEMO = "77777777-7"
RUT_PERSONA_DEMO = "12345678-5"      # "Ana", la dueña y firmante
RUT_CLIENTE_DEMO = "76111111-6"
RUT_CONSUMIDOR_FINAL = "66666666-6"  # convención SII para boletas sin identificar
AMBIENTE = "simulacion"
ESTADO = "simulado"
TIPOS_DEMO = (33, 34, 39, 41, 56, 61)
FOLIOS_POR_TIPO = 100

EMISOR_DEMO = EmisorModel(
    rut=RUT_DEMO, razon_social="EMPRESA DEMO SPA", giro="Cafetería",
    codigo_actividad=561000, direccion="Calle Ficticia 123", comuna="Santiago",
    ciudad="Santiago", email="hola@empresademo.cl", es_receptor_boleta=True,
)
CLIENTE_DEMO = ReceptorModel(
    rut=RUT_CLIENTE_DEMO, razon_social="CLIENTE DEMO SPA", giro="Oficina",
    direccion="Avenida Imaginaria 456", comuna="Providencia", ciudad="Santiago",
)
CONSUMIDOR_FINAL = ReceptorModel(rut=RUT_CONSUMIDOR_FINAL, razon_social="CONSUMIDOR FINAL",
                                 es_contribuyente=False)


def carpeta() -> Path:
    return Path(settings.storage_path) / "simulacion"


# ---------------------------------------------------------------------------
# Certificado y CAF ficticios
# ---------------------------------------------------------------------------
_CERT: Optional[CertificadoDigital] = None


def certificado_demo() -> CertificadoDigital:
    """Certificado autofirmado de 'Ana' con el RUT en el SAN (OID chileno), en memoria."""
    global _CERT
    if _CERT is not None:
        return _CERT
    # Si existe el certificado fijo del corpus dorado, usarlo: así la demo es estable y la
    # misma que comparan los ports (tests/dorado/fixtures, clave "demo", ficticio).
    fijo = Path("tests/dorado/fixtures/cert_demo.p12")
    if fijo.exists():
        _CERT = CertificadoDigital(fijo.read_bytes(), "demo")
        return _CERT
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    nombre = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "CL"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "SIMULACION DTE CHILE"),
        x509.NameAttribute(NameOID.COMMON_NAME, f"ANA DEMO {RUT_PERSONA_DEMO}"),
    ])
    # El RUT como IA5String DER dentro del otherName 1.3.6.1.4.1.8321.1 (lo que lee crypto.py).
    rut_der = b"\x16" + bytes([len(RUT_PERSONA_DEMO)]) + RUT_PERSONA_DEMO.encode("ascii")
    ahora = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder()
            .subject_name(nombre).issuer_name(nombre).public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(ahora - timedelta(days=1)).not_valid_after(ahora + timedelta(days=3650))
            .add_extension(x509.SubjectAlternativeName(
                [x509.OtherName(x509.ObjectIdentifier("1.3.6.1.4.1.8321.1"), rut_der)]), critical=False)
            .sign(key, hashes.SHA256()))
    p12 = pkcs12.serialize_key_and_certificates(
        b"demo", key, cert, None, serialization.BestAvailableEncryption(b"demo"))
    _CERT = CertificadoDigital(p12, "demo")
    return _CERT


def _caf_ficticio(tipo_dte: int, desde: int, hasta: int) -> str:
    """CAF con clave RSA real (para firmar el TED) y firma del SII de mentira."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=1024)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
                            serialization.NoEncryption()).decode("ascii")
    pn = key.public_key().public_numbers()
    m = base64.b64encode(pn.n.to_bytes((pn.n.bit_length() + 7) // 8, "big")).decode()
    e = base64.b64encode(pn.e.to_bytes((pn.e.bit_length() + 7) // 8, "big")).decode()
    return f"""<?xml version="1.0" encoding="ISO-8859-1"?>
<AUTORIZACION>
  <CAF version="1.0">
    <DA>
      <RE>{RUT_DEMO}</RE>
      <RS>{EMISOR_DEMO.razon_social}</RS>
      <TD>{tipo_dte}</TD>
      <RNG><D>{desde}</D><H>{hasta}</H></RNG>
      <FA>{date.today().isoformat()}</FA>
      <RSAPK><M>{m}</M><E>{e}</E></RSAPK>
      <IDK>100</IDK>
    </DA>
    <FRMA algoritmo="SHA1withRSA">U0lNVUxBQ0lPTi1OTy1FUy1VTkEtRklSTUEtREVMLVNJSQ==</FRMA>
  </CAF>
  <RSASK>
{pem}  </RSASK>
</AUTORIZACION>
"""


def asegurar_mundo() -> None:
    """Deja listo el mundo demo: CAF por tipo (si falta) y resolución fija en memoria."""
    carpeta().mkdir(parents=True, exist_ok=True)
    fijar_resolucion_local(RUT_DEMO, "2026-01-01", 0)
    for t in TIPOS_DEMO:
        if not obtener_caf_activo(RUT_DEMO, t):
            registrar_caf(tipo_dte=t, rut_emisor=RUT_DEMO, folio_desde=1, folio_hasta=FOLIOS_POR_TIPO,
                          fecha_autorizacion=date.today().isoformat(),
                          caf_xml=_caf_ficticio(t, 1, FOLIOS_POR_TIPO))


# ---------------------------------------------------------------------------
# Emitir, anular, ver, reiniciar
# ---------------------------------------------------------------------------
def _marcar_simulado(dte_id: int) -> None:
    with database.get_db() as conn:
        conn.execute("UPDATE dtes SET ambiente=?, estado=? WHERE id=?", (AMBIENTE, ESTADO, dte_id))


def _resultado(dte_id: int) -> dict:
    d = obtener_dte(dte_id)
    pdf = Path(d["pdf_path"]) if d.get("pdf_path") else None
    return {
        "dte_id": d["id"], "tipo_dte": d["tipo_dte"], "folio": d["folio"],
        "fecha_emision": d["fecha_emision"], "receptor": d["rut_receptor"],
        "razon_social_receptor": d["razon_social_receptor"],
        "monto_neto": d["monto_neto"], "monto_exento": d["monto_exento"], "iva": d["iva"],
        "monto_total": d["monto_total"], "ambiente": d["ambiente"], "estado": d["estado"],
        "pdf_path": d.get("pdf_path"),
        "pdf_b64": base64.b64encode(pdf.read_bytes()).decode() if pdf and pdf.exists() else None,
    }


def emitir(tipo_dte: int, items: List[dict], receptor: Optional[dict] = None,
           referencias: Optional[List[dict]] = None, fecha: Optional[date] = None) -> dict:
    """Emite un documento ficticio de EMPRESA DEMO SPA. `items` son dicts de `ItemDTE`
    (nombre, precio_unitario, cantidad, exento); `receptor` un dict de `ReceptorModel` o
    None (consumidor final para boletas, CLIENTE DEMO SPA para el resto).

    OJO con el precio: en **boletas (39/41) el precio va CON IVA incluido** (así las exige
    el SII y así las calcula `calcular_totales`: un café de 1.190 → neto 1.000, IVA 190).
    En facturas y notas el precio es **neto** (20.000 → IVA 3.800, total 23.800)."""
    if tipo_dte not in TIPOS_DEMO:
        raise ValidacionError(f"La simulación solo emite tipos {TIPOS_DEMO}", detalle={"tipo_dte": tipo_dte})
    if not items:
        raise ValidacionError("Hace falta al menos un ítem")
    asegurar_mundo()
    es_boleta = tipo_dte in (39, 41)
    exento_forzado = tipo_dte in (34, 41)
    its = [ItemDTE(numero_linea=i + 1, nombre=str(it.get("nombre") or "Venta")[:80],
                   cantidad=float(it.get("cantidad") or 1), precio_unitario=float(it.get("precio_unitario") or 0),
                   exento=bool(it.get("exento")) or exento_forzado)
           for i, it in enumerate(items)]
    if receptor:
        rec = ReceptorModel(**receptor)
    else:
        rec = CONSUMIDOR_FINAL if es_boleta else CLIENTE_DEMO
    refs = [ReferenciaModel(**r) for r in (referencias or [])] or None
    dte = DTEInput(tipo_dte=TipoDTE(tipo_dte), folio=0, fecha_emision=fecha or date.today(),
                   emisor=EMISOR_DEMO, receptor=rec, items=its, referencias=refs, forma_pago=1)
    res = emitir_documento(dte, certificado=certificado_demo(), storage_base=carpeta(), ambiente=AMBIENTE)
    _marcar_simulado(res["dte_id"])
    return _resultado(res["dte_id"])


def anular(dte_id: int, motivo: str = "Anula documento") -> dict:
    """Nota de crédito (61) que anula por el TOTAL registrado un documento demo (lección 1.4:
    nada se borra, se corrige con otro documento). Devuelve la NC emitida."""
    d = obtener_dte(dte_id)
    if not d or d["rut_emisor"] != RUT_DEMO or d.get("ambiente") != AMBIENTE:
        raise RecursoNoEncontrado("Ese documento no es de la simulación")
    if d["tipo_dte"] in (56, 61):
        raise ValidacionError("Una nota de crédito o débito no se anula con otra nota de crédito en este curso")
    if d["estado"] == "anulado_simulado":
        raise ValidacionError("Ese documento ya fue anulado")
    items = []
    if d["monto_neto"]:
        items.append({"nombre": f"Anula {_nombre(d['tipo_dte'])} folio {d['folio']}", "precio_unitario": d["monto_neto"], "exento": False})
    if d["monto_exento"]:
        items.append({"nombre": f"Anula {_nombre(d['tipo_dte'])} folio {d['folio']} (exento)", "precio_unitario": d["monto_exento"], "exento": True})
    receptor = {"rut": d["rut_receptor"], "razon_social": d["razon_social_receptor"] or "CONSUMIDOR FINAL",
                "es_contribuyente": d["rut_receptor"] != RUT_CONSUMIDOR_FINAL}
    ref = {"numero_linea": 1, "tipo_doc_ref": d["tipo_dte"], "folio_ref": d["folio"],
           "fecha_doc_ref": d["fecha_emision"][:10], "codigo_ref": 1, "razon_ref": motivo[:90]}
    nc = emitir(61, items, receptor=receptor, referencias=[ref])
    with database.get_db() as conn:
        conn.execute("UPDATE dtes SET estado='anulado_simulado' WHERE id=?", (dte_id,))
    return nc


def ver(dte_id: int) -> dict:
    d = obtener_dte(dte_id)
    if not d or d["rut_emisor"] != RUT_DEMO:
        raise RecursoNoEncontrado("Ese documento no es de la simulación")
    return _resultado(dte_id)


def estado() -> dict:
    """Cuántos documentos hay y qué folio sigue por tipo (lección 1.2)."""
    asegurar_mundo()
    folios = {}
    for t in TIPOS_DEMO:
        c = obtener_caf_activo(RUT_DEMO, t)
        folios[str(t)] = {"siguiente": c["folio_siguiente"], "hasta": c["folio_hasta"]} if c else None
    n = database.obtenerUno("SELECT COUNT(*) AS n FROM dtes WHERE rut_emisor=?", (RUT_DEMO,))["n"]
    return {"empresa": EMISOR_DEMO.model_dump(), "documentos": n, "folios": folios, "ambiente": AMBIENTE}


def reiniciar() -> dict:
    """Borra TODO lo de la empresa demo (documentos, CAF, archivos) y la deja en folio 1.
    Solo aquí se puede 'borrar': es práctica. En el mundo real no existe este botón."""
    with database.get_db() as conn:
        a = conn.execute("DELETE FROM dtes WHERE rut_emisor=?", (RUT_DEMO,)).rowcount
        b = conn.execute("DELETE FROM cafs WHERE rut_emisor=?", (RUT_DEMO,)).rowcount
    shutil.rmtree(carpeta(), ignore_errors=True)
    asegurar_mundo()
    return {"documentos_borrados": a, "cafs_borrados": b}


def _nombre(tipo: int) -> str:
    return {33: "factura", 34: "factura exenta", 39: "boleta", 41: "boleta exenta",
            52: "guía", 56: "nota de débito", 61: "nota de crédito"}.get(tipo, f"tipo {tipo}")
