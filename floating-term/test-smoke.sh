#!/usr/bin/env bash
# Prueba de humo del plugin `faminec/floating-term` sobre el escritorio.
#
# Necesita Hyprland con Noctalia y el plugin activados. Abre el panel, lanza
# todos los widgets, comprueba que están todos, los rota, comprueba que las
# posiciones se permutan y los cierra. Al final revisa **todas** las líneas
# nuevas del log y falla si hay cualquier [WRN] o [ERR], sea del plugin o no.
#
#   ./test-smoke.sh                  # usa el plugin instalado
#   ./test-smoke.sh /ruta/otra       # usa el manifiesto de otra copia
#
# Sale con código distinto de 0 si algo falla.
#
# Variables: NOCTALIA_LOG (ruta del log), OPEN_TIMEOUT, ROTATE_TIMEOUT,
# CLOSE_TIMEOUT (segundos de espera máxima de cada paso).

set -u

PLUGIN_ID="faminec/floating-term"
PANEL="$PLUGIN_ID:panel"
PLUGIN_DIR="${1:-$HOME/.local/share/noctalia/plugins/floating-term}"
LOG="${NOCTALIA_LOG:-$HOME/.cache/noctalia/noctalia.log}"
STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/noctalia"
SETTINGS="$STATE_DIR/settings.toml"
STORE="$STATE_DIR/plugins/data/$PLUGIN_ID/store.json"

OPEN_TIMEOUT="${OPEN_TIMEOUT:-45}"
ROTATE_TIMEOUT="${ROTATE_TIMEOUT:-15}"
CLOSE_TIMEOUT="${CLOSE_TIMEOUT:-20}"

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

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 no está en el PATH; hace falta para leer la configuración" >&2
  exit 2
fi

[ -f "$PLUGIN_DIR/plugin.toml" ] || fail "no encuentro el manifiesto en $PLUGIN_DIR/plugin.toml"

# Número de widgets que deben acabar abiertos: los comandos no vacíos que
# resultan de fusionar el manifiesto, los Ajustes y el store del panel, menos
# los borrados. Es la misma precedencia que usa `lib/store.luau`.
expected_line=$(python3 - "$PLUGIN_DIR/plugin.toml" "$SETTINGS" "$STORE" <<'PY'
import json
import sys
import tomllib

manifest_path, settings_path, store_path = sys.argv[1:4]

base = {}
with open(manifest_path, "rb") as handle:
    manifest = tomllib.load(handle)
for setting in manifest.get("setting", []):
    if setting.get("key") == "commands" and isinstance(setting.get("default"), dict):
        base = setting["default"]

config = {}
try:
    with open(settings_path, "rb") as handle:
        settings = tomllib.load(handle)
    block = settings.get("plugin_settings", {}).get("faminec/floating-term", {})
    config = block.get("commands", {}) or {}
except FileNotFoundError:
    pass

store = {}
try:
    with open(store_path, encoding="utf-8") as handle:
        store = json.load(handle)
except FileNotFoundError:
    pass

commands = {name: value for name, value in base.items() if isinstance(value, str) and value}
commands.update({name: value for name, value in config.items() if isinstance(value, str) and value})
commands.update({name: value for name, value in (store.get("commands") or {}).items() if isinstance(value, str)})
for name in store.get("removed") or []:
    commands.pop(name, None)

names = sorted(name for name, value in commands.items() if value)
print(len(names), " ".join(names))
PY
) || fail "no se pudo leer la configuración de widgets"
read -r expected names <<<"$expected_line"
[ "$expected" -ge 1 ] || fail "no hay ningún widget configurado"
echo "widgets esperados: $expected ($names)"

# Línea del log desde la que empieza la prueba: al final solo se revisa lo
# que se escriba a partir de aquí.
baseline=0
if [ -f "$LOG" ]; then
  baseline=$(wc -l <"$LOG")
fi

plugin_geometry() {
  hyprctl clients -j 2>/dev/null | python3 -c '
import json
import sys

try:
    clients = json.load(sys.stdin)
except Exception:
    clients = []

for client in sorted(
    (c for c in clients if c.get("class", "").startswith("noctalia-term-")),
    key=lambda c: c.get("class", ""),
):
    at = client.get("at") or [0, 0]
    print(client.get("class", ""), int(at[0]), int(at[1]))
'
}

plugin_count() {
  plugin_geometry | grep -c . || true
}

# Espera a que haya exactamente $1 ventanas del plugin, hasta $2 segundos.
wait_count() {
  local target="$1" deadline=$((SECONDS + $2))
  while :; do
    [ "$(plugin_count)" -eq "$target" ] && return 0
    [ "$SECONDS" -ge "$deadline" ] && return 1
    sleep 0.3
  done
}

# Espera a que la geometría deje de cambiar durante ~1 s. El contador llega a
# su número en cuanto la ventana existe, pero el plugin coloca y redimensiona
# un instante después: sin esto, el "antes" de la rotación sería una foto a
# medio colocar y la permutación no cuadraría.
wait_stable() {
  local deadline=$((SECONDS + 10)) previous current stable=0
  previous=$(plugin_geometry)
  while [ "$SECONDS" -lt "$deadline" ]; do
    sleep 0.4
    current=$(plugin_geometry)
    if [ "$current" = "$previous" ]; then
      stable=$((stable + 1))
      [ "$stable" -ge 2 ] && return 0
    else
      stable=0
      previous="$current"
    fi
  done
  return 1
}

# El panel solo atiende el IPC cuando está abierto. `panel-open` es
# idempotente (no alterna): si ya estaba abierto lo deja como está. Cuando lo
# abre de verdad, el plugin deja "widgets ->" en el log; si esa línea no
# aparece en un segundo es que ya estaba abierto.
ensure_panel() {
  local mark=0 deadline
  if [ -f "$LOG" ]; then
    mark=$(wc -l <"$LOG")
  fi
  noctalia msg panel-open "$PANEL" >/dev/null 2>&1 || fail "el panel no se pudo abrir"
  deadline=$((SECONDS + 1))
  while [ "$SECONDS" -lt "$deadline" ]; do
    if [ -f "$LOG" ] && tail -n +"$((mark + 1))" "$LOG" | grep -q "floating-term: widgets ->"; then
      return 0
    fi
    sleep 0.1
  done
}

# El plugin analiza `plugin.toml` una vez y lo guarda en memoria; el host solo
# recarga el script cuando cambia un `.luau`, no cuando cambia el manifiesto.
# Se toca el mtime del panel instalado (sin cambiar su contenido) para que la
# prueba arranque con los comandos que hay ahora mismo en disco.
INSTALLED_PANEL="$HOME/.local/share/noctalia/plugins/floating-term/panel.luau"
if [ -f "$INSTALLED_PANEL" ]; then
  touch "$INSTALLED_PANEL"
  sleep 1.5
fi

echo "0) partir de cero"
ensure_panel
noctalia msg plugin "$PANEL" all close-all >/dev/null 2>&1 || fail "el IPC close-all no respondió"
wait_count 0 "$CLOSE_TIMEOUT" || fail "quedaron ventanas abiertas al empezar: $(plugin_geometry)"

echo "1) abrir todos los widgets"
noctalia msg plugin "$PANEL" all open-all >/dev/null 2>&1 || fail "el IPC open-all no respondió"
if ! wait_count "$expected" "$OPEN_TIMEOUT"; then
  echo "   abiertas: $(plugin_geometry | tr '\n' ' ')" >&2
  fail "se esperaban $expected ventanas y hay $(plugin_count)"
fi
wait_stable || fail "las ventanas no terminaron de colocarse"
echo "   ventanas abiertas: $(plugin_count) ✔"

echo "2) rotar"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
cat >"$tmp/check_rotation.py" <<'PY'
import sys


def load(path):
    out = {}
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            parts = line.split()
            if len(parts) == 3:
                out[parts[0]] = (int(parts[1]), int(parts[2]))
    return out


before = load(sys.argv[1])
after = load(sys.argv[2])
if set(before) != set(after):
    print("las ventanas abiertas cambiaron al rotar", file=sys.stderr)
    sys.exit(1)
if sorted(before.values()) != sorted(after.values()):
    print("la rotación no fue una permutación de posiciones", file=sys.stderr)
    sys.exit(1)
if before == after:
    print("ninguna ventana cambió de posición", file=sys.stderr)
    sys.exit(1)
print(
    "permutación: "
    + ", ".join(
        f"{name}: {before[name]} -> {after[name]}"
        for name in sorted(before)
        if before[name] != after[name]
    )
)
PY
plugin_geometry >"$tmp/before"
noctalia msg plugin "$PANEL" all rotate >/dev/null 2>&1 || fail "el IPC rotate no respondió"
deadline=$((SECONDS + ROTATE_TIMEOUT))
rotated=0
while [ "$SECONDS" -lt "$deadline" ]; do
  plugin_geometry >"$tmp/after"
  if python3 "$tmp/check_rotation.py" "$tmp/before" "$tmp/after" >"$tmp/check" 2>&1; then
    rotated=1
    break
  fi
  sleep 0.3
done
if [ "$rotated" -ne 1 ]; then
  cat "$tmp/check" >&2
  echo "   antes:" >&2
  sed 's/^/     /' "$tmp/before" >&2
  echo "   después:" >&2
  sed 's/^/     /' "$tmp/after" >&2
  fail "la rotación no permutó las posiciones de las ventanas"
fi
cat "$tmp/check"

echo "3) cerrar todas"
ensure_panel
noctalia msg plugin "$PANEL" all close-all >/dev/null 2>&1 || fail "el IPC close-all no respondió"
if ! wait_count 0 "$CLOSE_TIMEOUT"; then
  echo "   restantes: $(plugin_geometry | tr '\n' ' ')" >&2
  fail "quedaron $(plugin_count) ventanas abiertas"
fi
echo "   ventanas restantes: 0 ✔"

echo "4) avisos y errores nuevos en el log durante la prueba"
if [ -f "$LOG" ]; then
  problems=$(tail -n +"$((baseline + 1))" "$LOG" | grep -E "\[WRN\]|\[ERR\]" || true)
  if [ -n "$problems" ]; then
    echo "$problems" >&2
    fail "el log recibió avisos o errores durante la prueba"
  fi
  echo "   ninguno ✔"
else
  echo "   (no hay log en $LOG; se salta la comprobación)"
fi

noctalia msg panel-close "$PANEL" >/dev/null 2>&1 || true

echo "OK: la prueba de humo pasó"
