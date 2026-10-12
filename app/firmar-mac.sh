#!/bin/sh
# Firma y notariza "Faro.app" para distribuirla fuera de la App Store.
#
#   IDENTIDAD="Developer ID Application: Tu Nombre (TEAMID)" \
#   APPLE_ID=tu@correo APPLE_TEAM_ID=TEAMID APPLE_APP_PASSWORD=xxxx-xxxx-xxxx-xxxx \
#   ./firmar-mac.sh
#
# La contraseña específica de app se crea en appleid.apple.com. Nada de esto se guarda en el
# repo. Ver docs/APP.md.
set -eu
APP="build/bin/Faro.app"
: "${IDENTIDAD:?Define IDENTIDAD (security find-identity -v -p codesigning)}"
wails build -platform darwin/universal -s
codesign --force --deep --options runtime --timestamp --sign "$IDENTIDAD" "$APP"
codesign --verify --deep --strict "$APP" && echo "firmada"
if [ -n "${APPLE_ID:-}" ]; then
  ditto -c -k --keepParent "$APP" build/bin/dte-chile.zip
  xcrun notarytool submit build/bin/dte-chile.zip --apple-id "$APPLE_ID" --team-id "$APPLE_TEAM_ID" \
    --password "$APPLE_APP_PASSWORD" --wait
  xcrun stapler staple "$APP" && echo "notarizada y grapada"
fi
