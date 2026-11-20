#!/usr/bin/env python3
"""Valida los recursos de la UI de los plugins: glifos y variantes.

Noctalia usa el set de iconos **Tabler** (no Lucide) y solo admite algunas
variantes de botón. Un nombre de glifo o una variante que no existen se
registran como aviso en el log ("missing glyph: x", "unknown button variant
'x'") y el elemento se dibuja vacío o con el estilo por defecto.

Este revisor extrae los literales de `ui.glyph({ name = "..." })` y de
`variant = "..."` y los contrasta con las listas reales.

Uso:  python3 tools/check-ui-resources.py [--json] [carpeta ...]
"""

from __future__ import annotations

import json
import os
import re
import sys

TABLER = "/usr/share/noctalia/assets/fonts/tabler.json"

# Variantes que Noctalia acepta en ui.button (las usa el resto de plugins).
VARIANTS = {"default", "ghost", "primary", "secondary", "destructive", "outline"}

GLYPH_RE = re.compile(r'ui\.glyph\(\s*\{[^}]*?name\s*=\s*"([^"]+)"', re.S)
GLYPH_ANY_RE = re.compile(r'name\s*=\s*"([a-z0-9-]+)"')
# Glifos que se pasan como argumento a un helper (toggleRow("k", "texto", "icono")).
GLYPH_ARG_RE = re.compile(
    r'toggleRow\(\s*"[^"]+"\s*,\s*(?:"[^"]+"|tr\([^)]*\))\s*,\s*"([^"]+)"'
)
VARIANT_RE = re.compile(r'variant\s*=\s*"([^"]+)"')
TR_RE = re.compile(r'\btr\(\s*"([^"]+)"')


def main(argv):
    json_mode = "--json" in argv[1:]
    roots = [arg for arg in argv[1:] if arg != "--json"] or ["."]
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

    findings = []
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
        for line, reason in found:
            findings.append(
                {"fichero": path, "linea": line, "mensaje": reason, "nivel": "error"}
            )

    # Claves de traducción: cada plugin declara sus claves en
    # translations/en.json; si el panel pide una que no existe, Noctalia
    # avisa en el log y muestra la clave en vez del texto.
    # El plugin de un fichero es el ancestro que contiene plugin.toml, no "dos
    # niveles hacia arriba": eso solo acertaba en plugins con subcarpetas.
    def plugin_root(path):
        current = os.path.dirname(os.path.abspath(path))
        while True:
            if os.path.isfile(os.path.join(current, "plugin.toml")):
                return current
            parent = os.path.dirname(current)
            if parent == current:
                return None
            current = parent

    plugin_dirs = sorted({root for root in (plugin_root(f) for f in files) if root is not None})
    for directory in plugin_dirs:
        prefix_path = directory + os.sep
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
            if not os.path.abspath(candidate).startswith(prefix_path):
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
                    collect(prefix + key + ".", item)
            else:
                # `prefix` carries a trailing dot down the recursion; the leaf is
                # the dotted path without it.
                available.add(prefix.rstrip("."))

        collect("", data)
        for path in sorted(files):
            if not os.path.abspath(path).startswith(prefix_path):
                continue
            body = open(path, encoding="utf-8", errors="replace").read()
            for match in TR_RE.finditer(body):
                key = match.group(1)
                if key in available:
                    continue
                if key.startswith("settings.") and key.count(".") > 1:
                    continue  # claves de la página de ajustes
                line = body[: match.start()].count("\n") + 1
                findings.append(
                    {
                        "fichero": path,
                        "linea": line,
                        "mensaje": "clave de traducción inexistente: %s" % key,
                        "nivel": "error",
                    }
                )

    if json_mode:
        print(
            json.dumps(
                {
                    "herramienta": "check-ui-resources.py",
                    "ficheros_revisados": len(files),
                    "hallazgos": findings,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        current = None
        for item in findings:
            if item["fichero"] != current:
                current = item["fichero"]
                print(current)
            print("  línea %-5d %s" % (item["linea"], item["mensaje"]))
        print("---")
        print("%d fichero(s) revisados, %d aviso(s)" % (len(files), len(findings)))
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
