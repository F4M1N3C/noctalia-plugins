#!/usr/bin/env bash
# Despliegue del plugin en el directorio de plugins de Noctalia.
#
# POR QUE ES ATOMICO
#
# El shell no vigila el fichero: vigila el DIRECTORIO del plugin y recarga el
# script en cuanto ve IN_CLOSE_WRITE o IN_MOVED_TO (src/core/files/
# file_watcher.cpp, disparo "WriteCompleted"). Si el fichero se copia a trozos
# (o una redireccion lo deja a medias y lo cierra), la recarga puede leer un
# script incompleto y el plugin deja de cargar:
#
#   [ERR] [luau] plugin ...:panel: luau_load failed: ...:4: Expected ')' ...
#
# Ese error deja la entrada rota hasta la siguiente escritura. Escribir a un
# temporal y renombrarlo genera un IN_MOVED_TO: el shell solo llega a ver el
# fichero completo, nunca a medias.
#
# Ademas comprueba despues que la carga ha ido bien, para que un fallo de
# carga no pase desapercibido.
#
# Uso:  bin/deploy.sh [directorio_destino]

set -euo pipefail

raiz="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
destino="${1:-${NOCTALIA_PLUGIN_DIR:-$HOME/.local/share/noctalia/plugins/wallpaper-carousel}}"
log="${NOCTALIA_LOG:-$HOME/.cache/noctalia/noctalia.log}"

ficheros=(
  panel.luau
  widget.luau
  plugin.toml
  README.md
  translations/en.json
  translations/es.json
  bin/thumbs.py
)

# Comprobacion de sintaxis ANTES de desplegar: si el script no compila, el
# shell lo cargara y dejara la entrada rota ("luau_load failed"), y el
# error se queda hasta la siguiente escritura. Mejor no desplegarlo.
if command -v luac5.1 >/dev/null 2>&1; then
  for f in "${ficheros[@]}"; do
    [ -f "$raiz/$f" ] || continue
    case "$f" in
      *.luau)
        if ! luac5.1 -p "$raiz/$f" >/dev/null 2>&1; then
          echo "ERROR: $f no compila; no se despliega nada" >&2
          luac5.1 -p "$raiz/$f" || true
          exit 1
        fi
        ;;
    esac
  done
  echo "sintaxis correcta ✓"
else
  echo "aviso: luac5.1 no esta disponible; se despliega sin comprobar la sintaxis" >&2
fi

mkdir -p "$destino/bin" "$destino/translations"

for f in "${ficheros[@]}"; do
  origen="$raiz/$f"
  [ -f "$origen" ] || continue
  destino_final="$destino/$f"
  temporal="$(dirname "$destino_final")/.$(basename "$destino_final").tmp.$$"
  cp "$origen" "$temporal"
  chmod --reference="$origen" "$temporal" 2>/dev/null || true
  mv -f "$temporal" "$destino_final"   # rename: atomico
done

echo "desplegado en $destino"

# Comprobacion: el shell deberia haber recargado el script sin errores.
if [ -f "$log" ]; then
  sleep 2
  echo "--- ultimas lineas del shell sobre este plugin ---"
  grep -E "wallpaper-carousel" "$log" | grep -E "hot reload|luau_load failed|unhealthy|disabled after" | tail -5 || echo "(sin novedades)"
fi
