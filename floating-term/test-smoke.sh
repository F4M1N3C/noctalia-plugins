#!/usr/bin/env bash
# Prueba de humo del plugin `faminec/floating-term` sobre el escritorio.
#
# Necesita Hyprland con Noctalia y el plugin activados. Abre el panel, lanza
# todos los widgets, los rota y los cierra, y comprueba que el log de Noctalia
# no ha recibido ningún aviso ni error del plugin.
#
#   ./test-smoke.sh            # usa el plugin instalado
#   ./test-smoke.sh /ruta/otra # usa otra copia
#
# Sale con código distinto de 0 si algo falla.

set -u

PLUGIN_ID="faminec/floating-term"
LOG="${NOCTALIA_LOG:-$HOME/.cache/noctalia/noctalia.log}"
PANEL="$PLUGIN_ID:panel"

fail() {
  echo "FALLA: $*" >&2
  exit 1
}

if ! command -v noctalia >/dev/null 2>&1; then
  echo "noctalia no está en el PATH; esta prueba necesita el escritorio" >&2
  exit 2
fi

if ! command -v hyprctl >/dev/null 2>&1; then
  echo "hyprctl no está en el PATH; esta prueba necesita Hyprland" >&2
  exit 2
fi

open_panel() {
  noctalia msg panel-toggle "$PANEL" >/dev/null 2>&1
  sleep 3
}

plugin_windows() {
  hyprctl clients -j 2>/dev/null | python3 -c "
import json, sys
try:
    clients = json.load(sys.stdin)
except Exception:
    clients = []
print(len([c for c in clients if c.get('class', '').startswith('noctalia-term-')]))
"
}

echo "1) abrir todos los widgets"
open_panel
noctalia msg plugin "$PANEL" all open-all >/dev/null 2>&1 || fail "el IPC open-all no respondió"
sleep 8
count=$(plugin_windows)
echo "   ventanas abiertas: $count"
[ "$count" -ge 1 ] || fail "no se abrió ninguna ventana"

echo "2) rotar"
open_panel
noctalia msg plugin "$PANEL" all rotate >/dev/null 2>&1 || fail "el IPC rotate no respondió"
sleep 4

echo "3) cerrar todas"
open_panel
noctalia msg plugin "$PANEL" all close-all >/dev/null 2>&1 || fail "el IPC close-all no respondió"
sleep 3
count=$(plugin_windows)
echo "   ventanas restantes: $count"
[ "$count" -eq 0 ] || fail "quedaron ventanas abiertas"

echo "4) avisos del plugin en el log"
if [ -f "$LOG" ]; then
  problems=$(grep -E "\[WRN\]|\[ERR\]" "$LOG" \
    | grep -E "floating-term|ui-tree" \
    | grep -vE "no loaded plugin with this id" || true)
  if [ -n "$problems" ]; then
    echo "$problems" >&2
    fail "el plugin dejó avisos o errores en el log"
  fi
  echo "   ninguno ✔"
else
  echo "   (no hay log en $LOG; se salta la comprobación)"
fi

echo "OK: la prueba de humo pasó"
