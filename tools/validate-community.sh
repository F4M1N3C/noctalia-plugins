#!/usr/bin/env bash
# Valida un plugin con el validador compartido de noctalia-dev/official-plugins.
#
# Uso: tools/validate-community.sh [carpeta-del-plugin]
#
# El validador se descarga de la rama main del repositorio oficial y se ejecuta
# contra una copia temporal que contiene solo el plugin indicado.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLUGIN="${1:-terminal-widgets}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

VALIDATOR_BASE="https://raw.githubusercontent.com/noctalia-dev/official-plugins/main/.github/actions/validate-plugins"
mkdir -p "$TMP/.validator"
curl -fsSL "$VALIDATOR_BASE/validate-plugins.py" -o "$TMP/.validator/validate-plugins.py"
curl -fsSL "$VALIDATOR_BASE/requirements.txt" -o "$TMP/.validator/requirements.txt"

if python3 -m pip --version >/dev/null 2>&1; then
  python3 -m pip install --quiet --disable-pip-version-check -r "$TMP/.validator/requirements.txt"
elif command -v pip3 >/dev/null 2>&1; then
  pip3 install --quiet --disable-pip-version-check -r "$TMP/.validator/requirements.txt"
else
  echo "warning: pip not available, assuming validator dependencies are installed" >&2
fi

cp -r "$REPO_ROOT/$PLUGIN" "$TMP/$(basename "$PLUGIN")"
find "$TMP/$(basename "$PLUGIN")" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true

python3 "$TMP/.validator/validate-plugins.py" --profile community --root "$TMP"
