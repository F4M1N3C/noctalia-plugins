#!/usr/bin/env bash
# Deploy script for the Terminal Widgets plugin.
#
# Usage: tools/deploy-terminal-widgets.sh [--restart-noctalia]
#
# The source is resolved relative to this script, so the monorepo can live
# anywhere. The destination defaults to Noctalia's plugin directory and can be
# overridden with DEST.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_SRC="$SCRIPT_DIR/../terminal-widgets"
PLUGIN_DST="${DEST:-$HOME/.local/share/noctalia/plugins/terminal-widgets}"
RESTART=false

if [[ "${1:-}" == "--restart-noctalia" ]]; then
    RESTART=true
fi

echo "=== Deploying Terminal Widgets ==="
echo "Source:  $PLUGIN_SRC"
echo "Target:  $PLUGIN_DST"
echo ""

# Copy all plugin files (tests, docs and assets stay in the repo).
rsync -av --delete \
    --exclude='.git' \
    --exclude='test-*' \
    --exclude='*.md' \
    --exclude='screenshots' \
    --exclude='.playwright-mcp' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    "$PLUGIN_SRC/" "$PLUGIN_DST/"

echo ""
echo "=== Files deployed ==="
find "$PLUGIN_DST" -type f | sort

if [[ "$RESTART" == true ]]; then
    echo ""
    echo "=== Restarting Noctalia ==="
    # Si Noctalia lo lleva systemd, se reinicia el servicio: matar el proceso
    # a mano deja al servicio en un bucle de reinicio ("noctalia is already
    # running") porque el nuevo proceso no hereda el socket único.
    if systemctl --user is-enabled --quiet noctalia.service 2>/dev/null; then
        systemctl --user restart noctalia.service
        sleep 3
        echo "Noctalia reiniciado (systemd --user)"
    else
        pkill -x noctalia 2>/dev/null || true
        sleep 2
        nohup noctalia >/dev/null 2>&1 &
        sleep 3
        echo "Noctalia reiniciado (proceso manual)"
    fi
fi

echo ""
echo "=== Deploy complete ==="
echo "To test: noctalia msg panel-toggle faminec/terminal-widgets:panel"