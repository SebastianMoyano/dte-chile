#!/bin/sh
# Empaqueta "DTE Chile.app" con el motor Python ADENTRO (sin repo ni .venv en la máquina del
# usuario). Pasos: PyInstaller del motor → wails build → copiar el motor al bundle.
#
#   cd app && ./empaquetar-mac.sh            # build/bin/DTE Chile.app, lista para abrir
#   IDENTIDAD="Developer ID Application: …" ./empaquetar-mac.sh && ./firmar-mac.sh   # y firmada
#
# La app resultante es para la arquitectura de esta máquina (el motor congelado no es universal).
set -eu
cd "$(dirname "$0")"
REPO="$(cd .. && pwd)"
PY="$REPO/.venv/bin/python"
[ -x "$PY" ] || { echo "falta $PY (crea el venv del repo primero)"; exit 1; }
"$PY" -m PyInstaller --version >/dev/null 2>&1 || "$PY" -m pip install -q pyinstaller

echo "→ motor (PyInstaller, onedir)"
rm -rf build/motor
(cd "$REPO" && "$PY" -m PyInstaller motor.spec --noconfirm --distpath app/build --workpath app/build/pyi 2>&1 | grep -E "ERROR|completed successfully" || true)
[ -x build/motor/motor ] || { echo "no se generó build/motor/motor"; exit 1; }

echo "→ app (wails)"
wails build -platform darwin/arm64 -s >/dev/null
APP="build/bin/DTE Chile.app"
echo "→ motor dentro del bundle"
rm -rf "$APP/Contents/Resources/motor"
cp -R build/motor "$APP/Contents/Resources/motor"
du -sh "$APP" | awk '{print "   tamaño: " $1}'
echo "listo: $APP"
