#!/bin/sh
# Instala el hook pre-push: antes de subir, tools/auditar_publico.py revisa árbol e historia.
# Si encuentra un RUT real, una persona o un secreto, el push no sale.
#   ./tools/instalar_hooks.sh
set -eu
cd "$(dirname "$0")/.."
H=.git/hooks/pre-push
cat > "$H" <<'HOOK'
#!/bin/sh
# gate público (tools/instalar_hooks.sh)
cd "$(git rev-parse --show-toplevel)"
PY=.venv/bin/python; [ -x "$PY" ] || PY=python3
exec "$PY" tools/auditar_publico.py
HOOK
chmod +x "$H"
echo "hook pre-push instalado: $H"
