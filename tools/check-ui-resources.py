#!/usr/bin/env python3
"""Valida los recursos de la UI de los plugins: glifos y variantes.

Noctalia usa el set de iconos **Tabler** (no Lucide) y solo admite algunas
variantes de botón. Un nombre de glifo o una variante que no existen se
registran como aviso en el log ("missing glyph: x", "unknown button variant
'x'") y el elemento se dibuja vacío o con el estilo por defecto.

Este revisor extrae los literales de `ui.glyph({ name = "..." })` y de
`variant = "..."` y los contrasta con las listas reales.

Uso:  python3 tools/check-ui-resources.py [carpeta ...]
"""

from __future__ import annotations

import json
import os
import re
import sys

TABLER = "/usr/share/noctalia/assets/fonts/tabler.json"

# Variantes que Noctalia acepta en ui.button (las usa el resto de plugins).
VARIANTS = {"ghost", "primary", "secondary", "destructive"}

GLYPH_RE = re.compile(r'ui\.glyph\(\s*\{[^}]*?name\s*=\s*"([^"]+)"', re.S)
GLYPH_ANY_RE = re.compile(r'name\s*=\s*"([a-z0-9-]+)"')
# Glifos que se pasan como argumento a un helper (toggleRow("k", "texto", "icono")).
GLYPH_ARG_RE = re.compile(
    r'toggleRow\(\s*"[^"]+"\s*,\s*(?:"[^"]+"|tr\([^)]*\))\s*,\s*"([^"]+)"'
)
VARIANT_RE = re.compile(r'variant\s*=\s*"([^"]+)"')
TR_RE = re.compile(r'\btr\(\s*"([^"]+)"')


def main(argv):
    roots = argv[1:] or ["."]
    if not os.path.isfile(TABLER):
        print("no se encontró la lista de iconos (%s)" % TABLER, file=sys.stderr)
        return 0
    icons = set(json.load(open(TABLER, encoding="utf-8")).keys())

    files = []
    for root in roots:
        if os.path.isfile(root):
            files.append(root)
            continue
        for current, dirs, names in os.walk(root):
            dirs[:] = [d for d in dirs if d not in (".git", "__pycache__", "node_modules")]
            for name in names:
                if name.endswith(".luau"):
                    files.append(os.path.join(current, name))

    problems = 0
    for path in sorted(files):
        src = open(path, encoding="utf-8", errors="replace").read()
        found = []
        for match in GLYPH_RE.finditer(src):
            name = match.group(1)
            if name not in icons:
                line = src[: match.start()].count("\n") + 1
                found.append((line, "glifo inexistente: %s" % name))
        # Nombres de glifo que llegan por variable no se pueden validar; los
        # literales sueltos se comprueban contra la lista de la UI.
        for match in GLYPH_ARG_RE.finditer(src):
            name = match.group(1)
            # Las claves de traducción llevan punto: no son glifos.
            if "." in name:
                continue
            if name not in icons:
                line = src[: match.start()].count("\n") + 1
                found.append((line, "glifo inexistente: %s" % name))
        for match in VARIANT_RE.finditer(src):
            value = match.group(1)
            if value not in VARIANTS:
                line = src[: match.start()].count("\n") + 1
                found.append((line, "variante de botón no válida: %s" % value))
        if found:
            print(path)
            for line, reason in found:
                print("  línea %-5d %s" % (line, reason))
            problems += len(found)
    # Claves de traducción: cada plugin declara sus claves en
    # translations/en.json; si el panel pide una que no existe, Noctalia
    # avisa en el log y muestra la clave en vez del texto.
    plugin_dirs = sorted({os.path.dirname(os.path.dirname(f)) for f in files})
    for directory in plugin_dirs:
        translation = os.path.join(directory, "translations", "en.json")
        if not os.path.isfile(translation):
            continue
        try:
            data = json.load(open(translation, encoding="utf-8"))
        except (OSError, ValueError):
            continue
        # Si el plugin tiene su propia capa de traducción (M.tr), las claves
        # no tienen por qué estar en translations/en.json.
        own_i18n = False
        for candidate in sorted(files):
            if not candidate.startswith(directory + os.sep):
                continue
            body = open(candidate, encoding="utf-8", errors="replace").read()
            if re.search(r"function\s+M\.tr\s*\(", body):
                own_i18n = True
                break
        if own_i18n:
            continue

        available = set()

        def collect(prefix, value):
            if isinstance(value, dict):
                for key, item in value.items():
                    collect(prefix + key + "." if prefix else key, item)
            else:
                available.add(prefix)

        collect("", data)
        for path in sorted(files):
            if not path.startswith(directory + os.sep):
                continue
            body = open(path, encoding="utf-8", errors="replace").read()
            for match in TR_RE.finditer(body):
                key = match.group(1)
                if key in available:
                    continue
                if key.startswith("settings.") and key.count(".") > 1:
                    continue  # claves de la página de ajustes
                line = body[: match.start()].count("\n") + 1
                print("%s" % path)
                print("  línea %-5d clave de traducción inexistente: %s" % (line, key))
                problems += 1

    print("---")
    print("%d fichero(s) revisados, %d aviso(s)" % (len(files), problems))
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
