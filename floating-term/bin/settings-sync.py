#!/usr/bin/env python3
"""Sincroniza los mapas de widgets del plugin con settings.toml.

Uso:
  settings-sync.py commands '<json>' layouts '<json>'
  settings-sync.py --stdin   # lee {"commands":{...}, "layouts":{...}}

Las claves y valores se escriben en:
  [plugin_settings."faminec/floating-term".commands]
  [plugin_settings."faminec/floating-term".layouts]

El resto del fichero (y de la seccion del plugin) se conserva. Escritura
atomica. La ruta se puede redirigir con NOCTALIA_SETTINGS para las pruebas.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile

PLUGIN_ID = "faminec/floating-term"
SECTION = f'[plugin_settings."{PLUGIN_ID}"]'
SUB_COMMANDS = f'{SECTION}.commands'
SUB_LAYOUTS = f'{SECTION}.layouts'


def settings_path() -> str:
    return os.path.expanduser(os.environ.get("NOCTALIA_SETTINGS") or "~/.local/state/noctalia/settings.toml")


def lock_path(path: str) -> str:
    return path + ".lock"


def toml_key(key: str) -> str:
    return json.dumps(key)


def toml_value(value: str) -> str:
    escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def render_map(name: str, data: dict) -> list[str]:
    lines = [f"    [plugin_settings.\"{PLUGIN_ID}\".{name}]"]
    for key in sorted(data):
        lines.append(f"    {toml_key(key)} = {toml_value(data[key])}")
    lines.append("")
    return lines


def split_top_level_sections(text: str):
    """Devuelve (prefix, sections) donde cada section es (header, body_lines)."""
    lines = text.split("\n")
    # Encontrar secciones de nivel top ([...]) y sub-secciones indentadas.
    sections = []
    current_header = None
    current_body = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            if current_header is not None:
                sections.append((current_header, current_body))
            current_header = stripped
            current_body = []
        else:
            if current_header is None:
                # texto previo (comentarios/cabecera) se acumula como seccion None
                if sections and sections[-1][0] is None:
                    sections[-1][1].append(line)
                else:
                    sections.append((None, [line]))
            else:
                current_body.append(line)
    if current_header is not None:
        sections.append((current_header, current_body))
    return sections


def plugin_section_index(sections):
    for index, (header, _) in enumerate(sections):
        if header == SECTION:
            return index
    return None


def remove_subtables(sections):
    """Elimina las sub-tablas commands/layouts del plugin del listado."""
    out = []
    for header, body in sections:
        if header == SUB_COMMANDS or header == SUB_LAYOUTS:
            continue
        out.append((header, body))
    return out


def upsert_plugin_section(sections, commands, layouts):
    sections = remove_subtables(sections)
    index = plugin_section_index(sections)
    if index is None:
        sections.append((SECTION, []))
        index = len(sections) - 1
    header, body = sections[index]
    # Quitar lineas vacias finales del cuerpo.
    while body and body[-1].strip() == "":
        body.pop()
    # Insertar sub-tablas al final del cuerpo.
    if commands is not None:
        body.append("")
        body.extend(render_map("commands", commands))
    if layouts is not None:
        body.append("")
        body.extend(render_map("layouts", layouts))
    sections[index] = (header, body)
    return sections


def render_sections(sections) -> str:
    out = []
    for header, body in sections:
        if header is not None:
            out.append(header)
        out.extend(body)
    text = "\n".join(out)
    if not text.endswith("\n"):
        text += "\n"
    return text


def main() -> int:
    args = sys.argv[1:]
    commands = None
    layouts = None

    if args and args[0] == "--stdin":
        payload = json.load(sys.stdin)
        if "commands" in payload:
            commands = payload["commands"]
        if "layouts" in payload:
            layouts = payload["layouts"]
    else:
        index = 0
        while index < len(args):
            key = args[index]
            value = args[index + 1] if index + 1 < len(args) else None
            index += 2
            if key == "commands":
                commands = json.loads(value) if value is not None else {}
            elif key == "layouts":
                layouts = json.loads(value) if value is not None else {}
            else:
                print(f"clave desconocida: {key}", file=sys.stderr)
                return 2

    path = settings_path()
    if not os.path.exists(path):
        print(f"no existe {path}", file=sys.stderr)
        return 1

    with open(path, "r", encoding="utf-8") as handle:
        text = handle.read()

    sections = split_top_level_sections(text)
    sections = upsert_plugin_section(sections, commands, layouts)
    new_text = render_sections(sections)

    if new_text == text:
        return 0

    fd, tmp = tempfile.mkstemp(prefix="settings-sync-", dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(new_text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
