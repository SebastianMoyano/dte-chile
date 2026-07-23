"""
test_mvp.py — Script de prueba local del MVP de DTE Chile.

Ejecutar con:
    python test_mvp.py

No requiere servidor corriendo. Prueba los módulos directamente.
"""

import json
import sys
from datetime import date

# Colores para la terminal
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
RESET = "\033[0m"
BOLD = "\033[1m"


def ok(msg):
    print(f"  {GREEN}✓{RESET} {msg}")


def falla(msg, e=None):
    print(f"  {RED}✗{RESET} {msg}")
    if e:
        print(f"    {RED}Error: {e}{RESET}")


def titulo(msg):
    print(f"\n{BOLD}{BLUE}{'='*50}{RESET}")
    print(f"{BOLD}{BLUE}  {msg}{RESET}")
    print(f"{BOLD}{BLUE}{'='*50}{RESET}")


def subtitulo(msg):
    print(f"\n{YELLOW}  ▶ {msg}{RESET}")


# =============================================
# TEST 1: Importaciones
# =============================================
titulo("TEST 1: Importaciones de Módulos")

try:
    from core.dte import (
        DTEInput, EmisorModel, ReceptorModel, ItemDTE,
        TipoDTE, GeneradorDTE, calcular_totales
    )
    ok("core.dte importado correctamente")
except Exception as e:
    falla("core.dte", e)
    sys.exit(1)

try:
    from core.crypto import CertificadoDigital, firmar_documento_xml, canonicalizar_elemento
    ok("core.crypto importado correctamente")
except Exception as e:
    falla("core.crypto", e)

try:
    from core.caf import ManejadorCAF
    ok("core.caf importado correctamente")
except Exception as e:
    falla("core.caf", e)

try:
    from core.sii import ClienteSII, AmbienteSII
    ok("core.sii importado correctamente")
except Exception as e:
    falla("core.sii", e)

try:
    from core.pdf_gen import generar_pdf_dte
    ok("core.pdf_gen importado correctamente")
except Exception as e:
    falla("core.pdf_gen", e)


# =============================================
# TEST 2: Modelos Pydantic y cálculo de totales
# =============================================
titulo("TEST 2: Modelos DTE y Cálculo de Totales")

subtitulo("Creando un DTEInput de Factura Electrónica de prueba...")

items_prueba = [
    ItemDTE(
        numero_linea=1,
        nombre="Servicio de Consultoría",
        descripcion="Asesoría técnica mensual",
        cantidad=1.0,
        precio_unitario=100000,
        codigo_producto="SRV-001",
    ),
    ItemDTE(
        numero_linea=2,
        nombre="Licencia de Software",
        cantidad=2.0,
        precio_unitario=50000,
        descuento_pct=10.0,
        codigo_producto="LIC-001",
    ),
    ItemDTE(
        numero_linea=3,
        nombre="Servicio Exento",
        cantidad=1.0,
        precio_unitario=20000,
        exento=True,
    ),
]

dte_prueba = DTEInput(
    tipo_dte=TipoDTE.FACTURA_ELECTRONICA,
    folio=100,
    fecha_emision=date.today(),
    emisor=EmisorModel(
        rut="12345678-9",
        razon_social="Empresa Demo SpA",
        giro="Servicios de Tecnología",
        codigo_actividad=726000,
        direccion="Av. Providencia 1234",
        comuna="Providencia",
        ciudad="Santiago",
        email="demo@empresa.cl",
    ),
    receptor=ReceptorModel(
        rut="98765432-1",
        razon_social="Cliente S.A.",
        giro="Comercio al por mayor",
        direccion="San Pablo 456",
        comuna="Santiago",
        ciudad="Santiago",
        email="compras@cliente.cl",
    ),
    items=items_prueba,
    forma_pago=1,
)

try:
    totales = calcular_totales(dte_prueba.items, dte_prueba.tipo_dte)
    ok(f"Totales calculados correctamente:")
    print(f"     Neto:    ${totales.monto_neto:>10,}")
    print(f"     Exento:  ${totales.monto_exento:>10,}")
    print(f"     IVA 19%: ${totales.iva_monto:>10,}")
    print(f"     TOTAL:   ${totales.monto_total:>10,}")

    # Validar cálculo esperado
    # Servicio: 100.000
    # Licencia: 2 x 50.000 = 100.000 - 10% = 90.000
    # Neto esperado: 190.000
    # Exento esperado: 20.000
    # IVA esperado: round(190.000 * 0.19) = 36.100
    # Total esperado: 246.100
    assert totales.monto_neto == 190000, f"Neto incorrecto: {totales.monto_neto}"
    assert totales.monto_exento == 20000, f"Exento incorrecto: {totales.monto_exento}"
    assert totales.iva_monto == 36100, f"IVA incorrecto: {totales.iva_monto}"
    assert totales.monto_total == 246100, f"Total incorrecto: {totales.monto_total}"
    ok("Validación de montos: OK")
except Exception as e:
    falla("Cálculo de totales", e)


# =============================================
# TEST 3: Generación de XML
# =============================================
titulo("TEST 3: Generación de XML DTE")

subtitulo("Generando XML sin firma (solo estructura)...")

try:
    generador = GeneradorDTE()
    dte_elem = generador.generar_documento_xml(dte_prueba, ted_xml=None)
    xml_str = generador.to_xml_string(dte_elem)

    assert "<DTE" in xml_str, "Falta el elemento raíz <DTE>"
    assert "<Encabezado>" in xml_str, "Falta <Encabezado>"
    assert "<Emisor>" in xml_str, "Falta <Emisor>"
    assert "<Receptor>" in xml_str, "Falta <Receptor>"
    assert "<Totales>" in xml_str, "Falta <Totales>"
    assert "<Detalle>" in xml_str, "Falta <Detalle>"
    assert "12345678-9" in xml_str, "RUT emisor no encontrado en el XML"
    assert "Empresa Demo SpA" in xml_str, "Razón social no encontrada en el XML"

    ok(f"XML generado correctamente ({len(xml_str)} caracteres)")
    ok("Estructura básica del XML validada")

    # Mostrar primeras líneas del XML
    print(f"\n  {BLUE}Primeras 10 líneas del XML generado:{RESET}")
    for i, linea in enumerate(xml_str.split("\n")[:12], 1):
        print(f"  {i:2}: {linea}")

except Exception as e:
    falla("Generación de XML", e)


# =============================================
# TEST 4: Dependencias opcionales
# =============================================
titulo("TEST 4: Verificación de Dependencias")

deps = {
    "lxml": "Manipulación de XML",
    "cryptography": "Criptografía RSA y certificados",
    "signxml": "Firma XMLDSig",
    "reportlab": "Generación de PDF",
    "pdf417gen": "Código de barras PDF417",
    "httpx": "Cliente HTTP para SII",
    "fastapi": "Framework API REST",
    "uvicorn": "Servidor ASGI",
}

for lib, desc in deps.items():
    try:
        __import__(lib.replace("-", "_"))
        ok(f"{lib:<15} — {desc}")
    except ImportError:
        falla(f"{lib:<15} — {desc} (NO INSTALADA)")


# =============================================
# TEST 5: Generación de PDF
# =============================================
titulo("TEST 5: Generación de PDF")

subtitulo("Generando PDF de la factura de prueba...")
try:
    pdf_bytes = generar_pdf_dte(dte_prueba, ted_xml=None)
    assert len(pdf_bytes) > 1000, "El PDF parece estar vacío"
    ok(f"PDF generado correctamente ({len(pdf_bytes):,} bytes)")

    # Guardar el PDF para inspección visual
    pdf_path = "/tmp/dte_prueba.pdf"
    with open(pdf_path, "wb") as f:
        f.write(pdf_bytes)
    ok(f"PDF guardado en {pdf_path}")
    print(f"  {YELLOW}→ Abre el archivo para verificar el diseño del PDF.{RESET}")
except Exception as e:
    falla("Generación de PDF", e)


# =============================================
# RESUMEN
# =============================================
titulo("RESUMEN")
print(f"""
  {GREEN}El MVP está listo para levantarse:{RESET}

  {BOLD}pip install -r requirements.txt{RESET}
  {BOLD}uvicorn main:app --reload --port 8000{RESET}

  Luego accede a:
  {BLUE}http://localhost:8000/docs{RESET}  → Swagger UI interactivo
  {BLUE}http://localhost:8000/redoc{RESET} → Documentación ReDoc
""")
