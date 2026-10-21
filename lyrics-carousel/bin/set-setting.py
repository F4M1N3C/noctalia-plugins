#!/usr/bin/env python3
"""Escribe ajustes del plugin en el settings.toml de Noctalia.

Uso:  set-setting.py <clave> <valor> [tipo] [<clave> <valor> [tipo] ...]

Tipos: bool | int | float | string

Mantiene el formato del fichero (secciones entrecomilladas, claves ordenadas
como las deja Noctalia) y escribe de forma atómica para no corromper la
configuración.
"""

from __future__ import annotations

import os
import sys
import tempfile

try:
    import tomllib
except ImportError:  # pragma: no cover - python < 3.11
    tomllib = None

PLUGIN_ID = "faminec/lyrics-carousel"
SECTION = f'[plugin_settings."{PLUGIN_ID}"]'
SETTINGS = os.path.expanduser("~/.local/state/noctalia/settings.toml")

ALLOWED = {
    "font_family", "font_size", "render_mode", "direction", "marker",
    "karaoke", "equalizer", "footer", "hints", "header", "spacing",
    "animation_ms", "ghost", "offset_ms", "width", "height", "anchor",
    "accent", "custom_color", "active_scale", "visible_above", "visible_below",
}

BOOL_KEYS = {
    "marker", "karaoke", "equalizer", "footer", "hints", "header", "ghost",
}
INT_KEYS = {
    "font_size", "spacing", "animation_ms", "offset_ms", "width", "height",
    "visible_above", "visible_below",
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
    for index, line in enumerate(body):
        if line.strip().startswith(key + " "):
            body[index] = f"{key} = {raw_value}"
            break
    else:
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


def main(argv):
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

    try:
        with open(SETTINGS, encoding="utf-8") as handle:
            text = handle.read()
    except OSError as error:
        print(f"no se pudo leer: {error}", file=sys.stderr)
        return 1

    updated = text
    for key, value, kind in pairs:
        updated = patch(updated, key, format_value(value, kind))
    if updated == text:
        return 0

    directory = os.path.dirname(SETTINGS)
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
        os.replace(temporary, SETTINGS)
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
        with open(SETTINGS, "rb") as handle:
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
