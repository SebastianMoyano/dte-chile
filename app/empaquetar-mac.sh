#!/bin/sh
# Empaqueta "DTE Chile.app": el motor Go va adentro del mismo ejecutable (fase 7), así que
# no hay Python, venv ni PyInstaller. La misma app lanzada con --mcp es el servidor MCP para
# la IA del computador (la pestaña "Tu IA" la conecta sola).
#
#   cd app && ./empaquetar-mac.sh                      # build/bin/DTE Chile.app (universal)
#   IDENTIDAD="Developer ID Application: …" ./empaquetar-mac.sh && ./firmar-mac.sh   # y firmada
#   DTE_MOTOR_PYTHON_BUNDLE=1 ./empaquetar-mac.sh      # además mete el motor Python (PyInstaller) para DTE_MOTOR=python
set -eu
cd "$(dirname "$0")"
REPO="$(cd .. && pwd)"
echo "→ app (wails, universal)"
PATH="$PATH:$HOME/go/bin" wails build -platform darwin/universal -s >/dev/null
APP="build/bin/DTE Chile.app"
if [ "${DTE_MOTOR_PYTHON_BUNDLE:-0}" = 1 ]; then
  PY="$REPO/.venv/bin/python"
  [ -x "$PY" ] || { echo "falta $PY (crea el venv del repo primero)"; exit 1; }
  "$PY" -m PyInstaller --version >/dev/null 2>&1 || "$PY" -m pip install -q pyinstaller
  echo "→ motor Python (PyInstaller, onedir; solo para DTE_MOTOR=python)"
  rm -rf build/motor
  (cd "$REPO" && "$PY" -m PyInstaller motor.spec --noconfirm --distpath app/build --workpath app/build/pyi 2>&1 | grep -E "ERROR|completed successfully" || true)
  [ -x build/motor/motor ] || { echo "no se generó build/motor/motor"; exit 1; }
  rm -rf "$APP/Contents/Resources/motor"
  cp -R build/motor "$APP/Contents/Resources/motor"
fi
du -sh "$APP" | awk '{print "   tamaño: " $1}'
echo "listo: $APP"
