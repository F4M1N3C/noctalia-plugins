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
# POR QUE ADEMAS COMPRUEBA Y REINTENTA
#
# El watcher descarta cualquier aviso que llegue menos de 100 ms despues del
# anterior (mismo fichero, file_watcher.cpp: "elapsed.count() < 100"). Si la
# recarga con el fichero incompleto y la del fichero completo llegan juntas,
# solo se atiende la primera y el plugin se queda roto aunque el fichero en
# disco este bien. Por eso, si la carga falla, el despliegue repite el
# renombrado (un aviso nuevo, ya fuera de la ventana del throttle) y vuelve a
# comprobar; y si sigue fallando, sale con error.
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

copiar_uno() {
  local f="$1"
  local origen="$raiz/$f"
  local destino_final="$destino/$f"
  local temporal
  [ -f "$origen" ] || return 0
  temporal="$(dirname "$destino_final")/.$(basename "$destino_final").tmp.$$"
  cp "$origen" "$temporal"
  chmod --reference="$origen" "$temporal" 2>/dev/null || true
  mv -f "$temporal" "$destino_final"   # rename: atomico
}

desplegar() {
  mkdir -p "$destino/bin" "$destino/translations"
  for f in "${ficheros[@]}"; do
    copiar_uno "$f"
  done
}

# Lineas del log a partir de las cuales hay que mirar (0 = log sin usar).
lineas_previas() {
  [ -f "$log" ] && wc -l < "$log" || echo 0
}

# Momento de la ultima escritura del log (0 = no existe).
log_mtime() {
  [ -f "$log" ] && stat -c %Y "$log" 2>/dev/null || echo 0
}

# Comprueba la carga: debe haber recarga del script y no debe haber error.
# Devuelve 0 si la carga esta comprobada, 1 si ha fallado y 2 si no se puede
# comprobar (el log del shell esta congelado y no se escribe nada).
comprobar_carga() {
  local desde="$1"
  local espera="${2:-6}"
  local i lineas_ok=0 nuevas
  for ((i = 0; i < espera * 5; i++)); do
    sleep 0.2
    [ -f "$log" ] || continue
    lineas_ok=1
    nuevas="$(tail -n +$((desde + 1)) "$log" 2>/dev/null || true)"
    if printf '%s' "$nuevas" | grep -qE "luau_load failed|unhealthy|disabled after repeated"; then
      echo "FALLO: el shell no ha podido cargar el script:" >&2
      printf '%s\n' "$nuevas" | grep -E "luau_load failed|unhealthy|disabled after repeated" | tail -3 >&2
      return 1
    fi
    if printf '%s' "$nuevas" | grep -q "hot reload"; then
      return 0
    fi
  done
  if [ "$lineas_ok" = 0 ]; then
    echo "aviso: no hay log en $log; no se puede comprobar la carga" >&2
    return 2
  fi
  # El log lleva mucho sin escribirse: esta congelado. No se puede exigir una
  # recarga que no se va a registrar, asi que esto no se cuenta como fallo.
  local ahora mtime
  ahora="$(date +%s)"
  mtime="$(log_mtime)"
  if [ $((ahora - mtime)) -gt 60 ]; then
    echo "aviso: el log del shell lleva mas de 60 s sin escribirse (congelado);" >&2
    echo "       no se puede comprobar la carga" >&2
    return 2
  fi
  echo "aviso: el shell no ha registrado recarga en ${espera}s; revisa $log" >&2
  return 1
}

# Comprobacion de la carga en el shell, con reintento (ver cabecera).
if [ -f "$log" ]; then
  # La marca se toma ANTES de desplegar: si se tomara despues, la linea de
  # recarga podria quedar fuera de la ventana y la comprobacion no serviria.
  desde="$(lineas_previas)"
  sleep 0.4
  desplegar
  echo "desplegado en $destino"

  # Los ficheros desplegados tienen que ser identicos a los del repositorio.
  for f in "${ficheros[@]}"; do
    [ -f "$raiz/$f" ] || continue
    if ! cmp -s "$raiz/$f" "$destino/$f"; then
      echo "ERROR: $f desplegado no coincide con el del repositorio" >&2
      exit 1
    fi
  done
  echo "contenido verificado ✓"

  set +e
  comprobar_carga "$desde" 6
  estado=$?
  set -e
  if [ "$estado" = 0 ]; then
    echo "carga comprobada ✓"
  elif [ "$estado" = 2 ]; then
    # El log esta congelado: no hay forma de comprobarlo y no es un fallo.
    echo "carga no comprobable; se deja el despliegue como esta" >&2
  else
    echo "reintentando el despliegue (el watcher puede haber descartado el aviso)..." >&2
    sleep 0.4
    desde="$(lineas_previas)"
    desplegar
    sleep 0.4
    set +e
    comprobar_carga "$desde" 6
    estado=$?
    set -e
    if [ "$estado" = 0 ]; then
      echo "carga comprobada en el reintento ✓"
    elif [ "$estado" = 2 ]; then
      echo "carga no comprobable (log congelado); se deja el despliegue como esta" >&2
    else
      echo "ERROR: el shell no carga el plugin tras desplegar" >&2
      tail -n +$((desde + 1)) "$log" 2>/dev/null | tail -5 >&2 || true
      exit 1
    fi
  fi
else
  mkdir -p "$destino/bin" "$destino/translations"
  desplegar
  echo "desplegado en $destino (sin log: no se puede comprobar la carga)"
fi
