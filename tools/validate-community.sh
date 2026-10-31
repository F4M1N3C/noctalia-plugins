#!/usr/bin/env bash
# Valida un plugin con el validador oficial de community-plugins.
#
# Uso: tools/validate-community.sh [carpeta-del-plugin]
#
# El validador se descarga de la rama main del repositorio oficial y se ejecuta
# contra una copia temporal del plugin: el validador exige que el nombre de la
# carpeta coincida con la parte del id tras la "/" y que no haya enlaces
# simbólicos, así que se valida una copia y no el directorio de trabajo.
set -euo pipefail

PLUGIN="${1:-terminal-widgets}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VALIDATOR_URL="https://raw.githubusercontent.com/noctalia-dev/community-plugins/main/.github/workflows/scripts/validate-plugins.py"

if [[ ! -d "$REPO_ROOT/$PLUGIN" ]]; then
  echo "no existe el directorio del plugin: $REPO_ROOT/$PLUGIN" >&2
  exit 2
fi

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# El validador calcula DEFAULT_ROOT con parents[3]: necesita esa profundidad.
mkdir -p "$TMP/.github/workflows/scripts"
curl -sSfL "$VALIDATOR_URL" -o "$TMP/.github/workflows/scripts/validate-plugins.py"

cp -r "$REPO_ROOT/$PLUGIN" "$TMP/$(basename "$PLUGIN")"
find "$TMP/$(basename "$PLUGIN")" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true

python3 "$TMP/.github/workflows/scripts/validate-plugins.py" --root "$TMP"
