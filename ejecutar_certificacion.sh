#!/bin/bash
# Script para ejecutar certificación SII.
# RUT/razón social/cert configurables: exporta DTE_RUT_EMPRESA, DTE_RAZON_SOCIAL,
# DTE_EMAIL, DTE_CERT_PATH, o pásalos directo a certificacion_sii.py (--rut, etc.).

CERT_PATH="${DTE_CERT_PATH:-firma.pfx}"

echo "============================================================"
echo "CERTIFICACIÓN SII"
echo "============================================================"
echo ""

# Verificar que el certificado existe
if [ ! -f "$CERT_PATH" ]; then
    echo "❌ Certificado no encontrado: $CERT_PATH"
    exit 1
fi

# Pedir contraseña del certificado
read -sp "Contraseña del certificado: " CERT_PASSWORD
echo ""

if [ -z "$CERT_PASSWORD" ]; then
    echo "❌ Contraseña no proporcionada"
    exit 1
fi

# Exportar variable de entorno
export CERTIFICADO_PASSWORD="$CERT_PASSWORD"

# Activar entorno virtual
source .venv/bin/activate

# Ejecutar script de certificación
python certificacion_sii.py --cert "$CERT_PATH"

# Limpiar variable de entorno
unset CERTIFICADO_PASSWORD

echo ""
echo "============================================================"
echo "Certificación completada"
echo "============================================================"
