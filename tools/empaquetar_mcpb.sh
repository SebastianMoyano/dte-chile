#!/bin/sh
# Empaqueta el servidor MCP como `dte-chile.mcpb`: el formato de instalación con doble click
# de la app de escritorio de Claude (MCP Bundle: un zip con manifest.json y el binario).
# Un solo bundle para macOS (universal), Linux (amd64) y Windows (amd64). Sin Python, sin Node:
# el binario Go lleva el motor adentro y usa la carpeta de datos de la app (o la crea).
#
#   ./tools/empaquetar_mcpb.sh            → nucleo/bin/dte-chile.mcpb
set -eu
cd "$(dirname "$0")/.."
VERSION=$(grep -o 'Version = "[^"]*"' nucleo/mcp/mcp.go | cut -d'"' -f2)
OUT=nucleo/bin/dte-chile.mcpb
T=$(mktemp -d)
mkdir -p "$T/server"
echo "→ binarios (v$VERSION)"
(cd nucleo && CGO_ENABLED=0 GOOS=darwin GOARCH=arm64 go build -trimpath -ldflags=-s -o "$T/arm64" ./cmd/nucleo-mcp)
(cd nucleo && CGO_ENABLED=0 GOOS=darwin GOARCH=amd64 go build -trimpath -ldflags=-s -o "$T/amd64" ./cmd/nucleo-mcp)
if command -v lipo >/dev/null; then lipo -create "$T/arm64" "$T/amd64" -output "$T/server/nucleo-mcp"; else cp "$T/arm64" "$T/server/nucleo-mcp"; fi
rm -f "$T/arm64" "$T/amd64"
(cd nucleo && CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -trimpath -ldflags=-s -o "$T/server/nucleo-mcp-linux" ./cmd/nucleo-mcp)
(cd nucleo && CGO_ENABLED=0 GOOS=windows GOARCH=amd64 go build -trimpath -ldflags=-s -o "$T/server/nucleo-mcp.exe" ./cmd/nucleo-mcp)
chmod +x "$T/server/"*
cat > "$T/manifest.json" <<JSON
{
  "manifest_version": "0.2",
  "name": "dte-chile",
  "display_name": "Faro",
  "version": "$VERSION",
  "description": "Facturación electrónica de Chile (SII): tus documentos, folios y envíos desde Claude. Todo en tu computador.",
  "long_description": "Conecta Claude al motor DTE Chile instalado en este computador. Claude puede listar tus empresas y certificados, consultar folios y timbrajes, revisar el estado de envíos al SII, previsualizar y emitir documentos (boletas, facturas, notas de crédito). Usa la misma carpeta de datos que la app de escritorio; si no tienes la app, la crea. Nada sale a internet salvo lo que tú le pidas enviar al SII.",
  "author": { "name": "Extralatte" },
  "license": "MIT",
  "keywords": ["chile", "sii", "dte", "factura", "boleta", "facturacion"],
  "server": {
    "type": "binary",
    "entry_point": "server/nucleo-mcp",
    "mcp_config": {
      "command": "\${__dirname}/server/nucleo-mcp",
      "args": [],
      "env": {},
      "platform_overrides": {
        "win32": { "command": "\${__dirname}/server/nucleo-mcp.exe" },
        "linux": { "command": "\${__dirname}/server/nucleo-mcp-linux" }
      }
    }
  },
  "tools": [
    { "name": "salud", "description": "Estado del motor" },
    { "name": "listar_certificados", "description": "Certificados del keystore" },
    { "name": "listar_negocios", "description": "Empresas registradas" },
    { "name": "previsualizar_dte", "description": "Arma un documento sin gastar folio" },
    { "name": "emitir_dte", "description": "Emite (gasta folio) y guarda" },
    { "name": "enviar_dte", "description": "Envía al SII" },
    { "name": "estado_envio", "description": "Estado de un envío (track id)" }
  ],
  "compatibility": { "platforms": ["darwin", "win32", "linux"] }
}
JSON
mkdir -p nucleo/bin
rm -f "$OUT"
(cd "$T" && zip -qr "$OLDPWD/$OUT" manifest.json server)
rm -rf "$T"
du -h "$OUT" | awk '{print "listo: '"$OUT"' (" $1 ")"}'
