#!/usr/bin/env python3
"""Escribe ajustes del plugin en el settings.toml de Noctalia.

Uso:  set-setting.py <clave> <valor> [tipo] [<clave> <valor> [tipo] ...]
       set-setting.py override <clave> <valor> <tipo>
       set-setting.py persist <clave> <valor> <tipo>
       set-setting.py merge

Tipos: bool | int | float | string

Mantiene el formato del fichero (secciones entrecomilladas, claves ordenadas
como las deja Noctalia) y escribe de forma atómica para no corromper la
configuración.

"override" deja el valor solo en la capa temporal (overrides.json), que el
panel vuelca al cerrarse. "persist" lo escribe además en el settings.toml:
es lo que necesitan los atajos de la ventana, que no tienen panel que
vuelque nada.
"""

from __future__ import annotations

import fcntl
import json
import os
import sys
import tempfile

try:
    import tomllib
except ImportError:  # pragma: no cover - python < 3.11
    tomllib = None

# Las rutas del estado las comparte el script: si el helper buscara el
# settings.toml en un sitio y el script en otro, uno escribiria donde el
# otro lee.
from paths import overrides_path, settings_path

PLUGIN_ID = "faminec/lyrics-carousel"
SECTION = f'[plugin_settings."{PLUGIN_ID}"]'

ALLOWED = {
    "font_family", "font_size", "render_mode", "direction", "marker",
    "karaoke", "equalizer", "footer", "hints", "header", "spacing",
    "animation_ms", "ghost", "offset_ms", "width", "height", "anchor",
    "custom_x", "custom_y", "accent", "custom_color", "active_scale",
    "visible_above", "visible_below", "language", "glyph",
}

BOOL_KEYS = {
    "marker", "karaoke", "equalizer", "footer", "hints", "header", "ghost",
}
INT_KEYS = {
    "font_size", "spacing", "animation_ms", "offset_ms", "width", "height",
    "custom_x", "custom_y", "visible_above", "visible_below",
}
FLOAT_KEYS = {"active_scale"}


def format_value(value: str, kind: str) -> str:
    if kind == "bool":
        return "true" if str(value).lower() in ("1", "true", "yes", "on") else "false"
    if kind == "int":
        return str(int(float(value)))
    if kind == "float":
        return str(float(value))
    escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def patch(text: str, key: str, raw_value: str) -> str:
    """Inserta o reemplaza una clave dentro de la sección del plugin."""
    lines = text.split("\n")
    start = None
    end = len(lines)
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped == SECTION:
            start = index
            continue
        if start is not None and stripped.startswith("[") and stripped.endswith("]"):
            end = index
            break
    if start is None:
        block = [SECTION, f"{key} = {raw_value}"]
        prefix = text if text.endswith("\n") else text + "\n"
        if not prefix.strip():
            return "\n".join(block) + "\n"
        return prefix + "\n".join(block) + "\n"

    body = lines[start + 1 : end]
    # El TOML no admite claves duplicadas: si las hay, todo el fichero
    # queda invalido y Noctalia descarta la seccion entera. Se deja solo la
    # primera aparicion de cada clave.
    seen = set()
    clean = []
    for line in body:
        name = line.split("=", 1)[0].strip()
        if name and not name.startswith("["):
            if name in seen:
                continue
            seen.add(name)
        clean.append(line)
    body = clean
    replaced = False
    for index, line in enumerate(body):
        if line.strip().startswith(key + " "):
            if not replaced:
                body[index] = f"{key} = {raw_value}"
                replaced = True
            else:
                # Clave duplicada: el TOML ser\u00eda inv\u00e1lido y Noctalia
                # descartaria toda la secci\u00f3n. Se elimina el duplicado.
                body[index] = None
    body = [line for line in body if line is not None]
    if not replaced:
        insert_at = len(body)
        while insert_at > 0 and body[insert_at - 1].strip() == "":
            insert_at -= 1
        for index in range(insert_at):
            name = body[index].split("=", 1)[0].strip()
            if name and name > key:
                insert_at = index
                break
        body.insert(insert_at, f"{key} = {raw_value}")
    return "\n".join(lines[: start + 1] + body + lines[end:])


def parse_args(argv):
    pairs = []
    index = 0
    while index < len(argv):
        key = argv[index]
        if index + 1 >= len(argv):
            raise ValueError(f"falta el valor de {key}")
        value = argv[index + 1]
        kind = "string"
        if index + 2 < len(argv) and argv[index + 2] in ("bool", "int", "float", "string"):
            kind = argv[index + 2]
            index += 1
        pairs.append((key, value, kind))
        index += 2
    return pairs


def ensure_dir(path: str) -> bool:
    """Garantiza que el directorio exista.

    El directorio de datos del plugin lo crea Noctalia, pero puede no existir
    (si se borra a mano o si el plugin nunca ha guardado nada) y entonces ni
    el lock ni la escritura podrian crearse.
    """
    directory = os.path.dirname(path)
    if not directory:
        return True
    try:
        os.makedirs(directory, exist_ok=True)
        return True
    except OSError as error:
        print(f"no se pudo crear {directory}: {error}", file=sys.stderr)
        return False


def overrides_path_now() -> str:
    """Ruta actual del fichero de overrides (se lee cada vez)."""
    return overrides_path()


def read_overrides():
    try:
        with open(overrides_path_now(), encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def write_overrides(data) -> bool:
    path = overrides_path_now()
    if not ensure_dir(path):
        return False
    directory = os.path.dirname(path)
    try:
        temporary = ""
        handle = tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=directory, delete=False, suffix=".tmp"
        )
        temporary = handle.name
        with handle:
            json.dump(data, handle, ensure_ascii=False, indent=1, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = ""
    except OSError as error:
        print(f"no se pudo escribir los overrides: {error}", file=sys.stderr)
        return False
    return True


def set_override(key: str, value: str, kind: str) -> int:
    """Guarda un ajuste en el fichero de overrides (no lo vigila Noctalia).

    Varias escrituras pueden solaparse (el panel escribe sin esperar), asi que
    la lectura-modificacion-escritura va con lock: si no, la segunda pisa a la
    primera.
    """
    path = overrides_path_now()
    lock_path = path + ".lock"
    if not ensure_dir(lock_path):
        return 1
    try:
        lock = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o644)
    except OSError as error:
        print(f"no se pudo abrir el lock: {error}", file=sys.stderr)
        return 1
    try:
        fcntl.flock(lock, fcntl.LOCK_EX)
        data = read_overrides()
        data[key] = parse_value(value, kind)
        if not write_overrides(data):
            return 1
        return 0
    finally:
        try:
            fcntl.flock(lock, fcntl.LOCK_UN)
        except OSError:
            pass
        os.close(lock)


def remove_override(key: str, value) -> bool:
    """Quita una clave de los overrides si sigue teniendo ese valor.

    El valor se comprueba: si el panel ha cambiado esa clave mientras
    tanto, su cambio se respeta y no se toca (el panel vuelca lo suyo al
    cerrarse).
    """
    path = overrides_path_now()
    lock_path = path + ".lock"
    if not ensure_dir(lock_path):
        return False
    try:
        lock = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o644)
    except OSError:
        return False
    try:
        fcntl.flock(lock, fcntl.LOCK_EX)
        data = read_overrides()
        if key not in data or data[key] != value:
            return False
        del data[key]
        return write_overrides(data)
    finally:
        try:
            fcntl.flock(lock, fcntl.LOCK_UN)
        except OSError:
            pass
        os.close(lock)


def parse_value(value: str, kind: str):
    if kind == "bool":
        return str(value).lower() in ("1", "true", "yes", "on")
    if kind == "int":
        return int(float(value))
    if kind == "float":
        return float(value)
    return value


def merge_overrides() -> int:
    """Vuelca los overrides al settings.toml y borra el fichero."""
    data = read_overrides()
    if not data:
        return 0
    pairs = []
    for key, value in data.items():
        if key not in ALLOWED:
            continue
        if isinstance(value, bool):
            pairs.append((key, "true" if value else "false", "bool"))
        elif isinstance(value, int):
            pairs.append((key, str(value), "int"))
        elif isinstance(value, float):
            pairs.append((key, str(value), "float"))
        else:
            pairs.append((key, str(value), "string"))
    if not pairs:
        try:
            os.remove(overrides_path_now())
        except OSError:
            pass
        return 0
    code = write_settings(pairs)
    if code == 0:
        try:
            os.remove(overrides_path_now())
        except OSError:
            pass
    return code


def persist_override(key: str, value: str, kind: str) -> int:
    """Guarda el ajuste y lo deja escrito en el settings.toml.

    La capa de overrides es temporal (la vuelca el panel al cerrarse). Un
    atajo de la ventana no tiene panel que la vuelque, asi que el valor se
    escribe tambien en el settings.toml: si no, se perderia al reiniciar
    la sesion.

    Primero se escribe en los overrides: si la escritura del settings.toml
    falla, el valor sigue en vigor durante la sesion y el panel lo vuelca
    al cerrarse. Si la escritura va bien, la clave se quita de los
    overrides para que no tape un cambio posterior hecho en la pagina de
    ajustes.
    """
    if set_override(key, value, kind) != 0:
        return 1
    code = write_settings([(key, value, kind)])
    if code != 0:
        return code
    remove_override(key, parse_value(value, kind))
    return 0


def main(argv):
    if len(argv) >= 2 and argv[1] == "override":
        if len(argv) < 5:
            print("uso: set-setting.py override <clave> <valor> <tipo>", file=sys.stderr)
            return 2
        if argv[2] not in ALLOWED:
            print(f"clave desconocida: {argv[2]}", file=sys.stderr)
            return 2
        return set_override(argv[2], argv[3], argv[4])
    if len(argv) >= 2 and argv[1] == "persist":
        if len(argv) < 5:
            print("uso: set-setting.py persist <clave> <valor> <tipo>", file=sys.stderr)
            return 2
        if argv[2] not in ALLOWED:
            print(f"clave desconocida: {argv[2]}", file=sys.stderr)
            return 2
        return persist_override(argv[2], argv[3], argv[4])
    if len(argv) >= 2 and argv[1] == "merge":
        return merge_overrides()
    if len(argv) < 3:
        print("uso: set-setting.py <clave> <valor> [tipo] ...", file=sys.stderr)
        return 2
    try:
        pairs = parse_args(argv[1:])
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 2

    for key, _, _ in pairs:
        if key not in ALLOWED:
            print(f"clave desconocida: {key}", file=sys.stderr)
            return 2

    return write_settings(pairs)


def write_settings(pairs) -> int:
    """Escribe los ajustes en el settings.toml (con lock).

    El script y el panel pueden escribir a la vez: con un fichero de lock
    la lectura-modificacion-escritura se serializa y no se pisan.
    """
    settings = settings_path()
    lock_path = settings + ".lock"
    if not ensure_dir(lock_path):
        return 1
    try:
        lock = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o644)
    except OSError as error:
        print(f"no se pudo abrir el lock: {error}", file=sys.stderr)
        return 1
    try:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            with open(settings, encoding="utf-8") as handle:
                text = handle.read()
        except OSError as error:
            print(f"no se pudo leer: {error}", file=sys.stderr)
            return 1
        return _write(text, pairs)
    finally:
        try:
            fcntl.flock(lock, fcntl.LOCK_UN)
        except OSError:
            pass
        os.close(lock)


def _write(text, pairs):
    updated = text
    for key, value, kind in pairs:
        updated = patch(updated, key, format_value(value, kind))
    if updated == text:
        return 0

    settings = settings_path()
    if not ensure_dir(settings):
        return 1
    directory = os.path.dirname(settings)
    temporary = ""
    try:
        handle = tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=directory, delete=False, suffix=".tmp"
        )
        temporary = handle.name
        with handle:
            handle.write(updated)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, settings)
        temporary = ""
    except OSError as error:
        if temporary:
            try:
                os.unlink(temporary)
            except OSError:
                pass
        print(f"no se pudo escribir: {error}", file=sys.stderr)
        return 1

    # Comprobación: el fichero debe seguir siendo un TOML válido y tener los
    # valores escritos. Si algo falla, se avisa con código de error.
    if tomllib is None:
        return 0
    try:
        with open(settings, "rb") as handle:
            check = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as error:
        print(f"el fichero quedó ilegible: {error}", file=sys.stderr)
        return 1
    section = (check.get("plugin_settings") or {}).get(PLUGIN_ID) or {}
    for key, value, _ in pairs:
        if key not in section:
            print(f"no se pudo guardar {key}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
