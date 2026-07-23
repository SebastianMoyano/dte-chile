import base64
import os
import sqlite3
from datetime import date, datetime
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization

# Asegurar importación del proyecto
import sys
sys.path.append(os.path.abspath("."))

from core.models import registrar_caf, obtener_caf_activo
from core.dte import DTEInput, EmisorModel, ReceptorModel, ItemDTE, TipoDTE
from core.orchestrator import OrquestadorDTE
from core.crypto import CertificadoDigital

def generar_clave_rsa_pem() -> str:
    """Genera una clave RSA privada de 1024 bits en formato PEM."""
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=1024
    )
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption()
    )
    return pem.decode("ascii")

def crear_xml_caf_ficticio(rut_emisor: str, tipo_dte: int, folio_desde: int, folio_hasta: int) -> str:
    """Genera un XML CAF ficticio con una clave privada RSA válida."""
    priv_key_pem = generar_clave_rsa_pem()
    
    # Estructura mínima que core/caf.py espera parsear
    xml = f"""<?xml version="1.0" encoding="ISO-8859-1"?>
<AUTORIZACION>
  <CAF version="1.0">
    <DA>
      <RE>{rut_emisor}</RE>
      <RS>RAZON SOCIAL S.A.</RS>
      <TD>{tipo_dte}</TD>
      <RNG>
        <D>{folio_desde}</D>
        <H>{folio_hasta}</H>
      </RNG>
      <FA>{date.today().isoformat()}</FA>
      <RSAPK>
        <M>MODULO_PLACEHOLDER</M>
        <E>Exponent</E>
      </RSAPK>
    </DA>
    <FRMA algoritmo="SHA1withRSA">FIRMA_SII_PLACEHOLDER</FRMA>
  </CAF>
  <IDDOC>
    <RSASK>
{priv_key_pem}
    </RSASK>
  </IDDOC>
</AUTORIZACION>
"""
    return xml

def test_flujo_emision_completo():
    print("=== INICIANDO TEST DE FLUJO DE EMISIÓN ORQUESTADO ===")
    
    # 1. Parámetros de prueba
    rut_emisor = "78111111-2"
    tipo_dte = TipoDTE.FACTURA_NO_AFECTA  # Tipo 34 (Exenta)
    
    # Limpiar BD anterior de CAFs activos para este emisor
    conn = sqlite3.connect("dte_database.db")
    conn.execute("DELETE FROM cafs WHERE rut_emisor=? AND tipo_dte=?", (rut_emisor, tipo_dte.value))
    conn.commit()
    conn.close()
    
    # 2. Generar y registrar el CAF en la BD
    print("\n[1] Generando CAF de prueba...")
    caf_xml = crear_xml_caf_ficticio(rut_emisor, tipo_dte.value, 1, 100)
    
    print("[2] Registrando CAF en la base de datos...")
    caf_id = registrar_caf(
        tipo_dte=tipo_dte.value,
        rut_emisor=rut_emisor,
        folio_desde=1,
        folio_hasta=100,
        fecha_autorizacion=date.today().isoformat(),
        caf_xml=caf_xml
    )
    print(f"  ✓ CAF registrado exitosamente (ID: {caf_id})")
    
    # Verificar CAF activo
    caf_activo = obtener_caf_activo(rut_emisor, tipo_dte.value)
    assert caf_activo is not None, "El CAF debería estar activo en la BD"
    print(f"  ✓ CAF activo verificado en BD. Folio siguiente: {caf_activo['folio_siguiente']}")
    
    # 3. Crear DTEInput de prueba (Folio 0 para auto-asignación)
    dte_in = DTEInput(
        tipo_dte=tipo_dte,
        folio=0,
        fecha_emision=date.today(),
        emisor=EmisorModel(
            rut=rut_emisor,
            razon_social="MI EMPRESA SPA",
            giro="Servicios Informáticos",
            codigo_actividad=620100,
            direccion="Calle Falsa 123",
            comuna="Cobquecura",
            ciudad="Buchupureo",
            email="contacto@miempresa.cl"
        ),
        receptor=ReceptorModel(
            rut="76543210-5",
            razon_social="CLIENTE RECEPTOR S.A.",
            giro="Venta de tecnología",
            direccion="Av. Apoquindo 4500",
            comuna="Las Condes",
            ciudad="Santiago"
        ),
        items=[
            ItemDTE(
                numero_linea=1,
                nombre="Consultoría Desarrollo Software",
                cantidad=1,
                precio_unitario=150000,
                exento=True
            ),
            ItemDTE(
                numero_linea=2,
                nombre="Soporte Mensual Infraestructura",
                cantidad=1,
                precio_unitario=50000,
                exento=True
            )
        ]
    )
    
    # 4. Obtener certificado digital si existe el firma.pfx (ruta configurable vía DTE_CERT_PATH)
    print("\n[3] Buscando certificado digital para firmar...")
    pfx_path = os.environ.get("DTE_CERT_PATH", "firma.pfx")
    cert = None
    if os.path.exists(pfx_path):
        try:
            from core.config import settings
            password = settings.certificado_password or "12345678"
            cert = CertificadoDigital.desde_archivo(pfx_path, password)
            print("  ✓ Certificado digital cargado correctamente.")
        except Exception as e:
            print(f"  ⚠ No se pudo cargar el certificado digital: {e}")
    else:
        print(f"  ⚠ No se encontró el archivo {pfx_path}. El test fallará al firmar.")
        return

    # 5. Ejecutar orquestador
    print("\n[4] Ejecutando OrquestadorDTE...")
    orquestador = OrquestadorDTE()
    
    try:
        resultado = orquestador.emitir_dte(dte_in, certificado=cert)
        
        print("\n=== RESULTADO DE EMISIÓN ORQUESTADA ===")
        for k, v in resultado.items():
            if k == "xml_envio_b64":
                print(f"  - {k}: {v[:60]}... (Truncado)")
            else:
                print(f"  - {k}: {v}")
                
        # 6. Validaciones de archivos guardados
        print("\n[5] Validando existencia de archivos guardados...")
        assert os.path.exists(resultado["xml_dte_path"]), "XML del DTE no existe"
        assert os.path.exists(resultado["pdf_path"]), "PDF no existe"
        assert os.path.exists(resultado["xml_envio_path"]), "XML de EnvioDTE no existe"
        print("  ✓ Todos los archivos persistieron en disco.")
        
        # Validar en base de datos
        conn = sqlite3.connect("dte_database.db")
        conn.row_factory = sqlite3.Row
        dte_row = conn.execute("SELECT * FROM dtes WHERE id=?", (resultado["dte_id"],)).fetchone()
        conn.close()
        
        assert dte_row is not None, "El DTE no se registró en la BD"
        print(f"  ✓ Registro en BD verificado. Folio guardado: {dte_row['folio']} - Estado: {dte_row['estado']}")
        
        # Comprobar que avanzó el folio_siguiente del CAF
        caf_post = obtener_caf_activo(rut_emisor, tipo_dte.value)
        print(f"  ✓ Siguiente folio del CAF post-emisión: {caf_post['folio_siguiente']}")
        assert caf_post["folio_siguiente"] == caf_activo["folio_siguiente"] + 1, "El folio no avanzó en la BD"
        
        print("\n🎉 ¡TEST COMPLETADO CON ÉXITO! 🎉")
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"\n✗ Error durante la emisión: {e}")

if __name__ == "__main__":
    test_flujo_emision_completo()
