#!/usr/bin/env python3
"""Verificación automática de los plugins de Noctalia.

Ejercita **todos** los paneles, widgets y servicios de cada plugin, captura el
log de Noctalia **por offset de bytes** (no por número de líneas, que se
rompe al rotar el log) y comprueba que no queda ningún error ni aviso
inesperado.

Después ejecuta los validadores estáticos:
  · tools/check-ui-resources.py  (glifos, variantes, traducciones, manejadores)
  · tools/check-locals.py        (locals usados antes de declararse)
  · tools/check-luau-globals.py  (globales leídos y nunca escritos)

Y, opcionalmente, el autotest de los propios validadores:
  · tools/selftest.py

Uso:  python3 tools/verify-plugins.py [--no-ui] [--selftest] [plugin ...]
Devuelve 1 si algo falla.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import noctalia_api as api  # noqa: E402

HOME = os.path.expanduser("~")
LOG = os.path.join(HOME, ".cache/noctalia/noctalia.log")
PLUGIN_DIR = os.path.join(HOME, ".local/share/noctalia/plugins")

# Avisos que no dependen de los plugins: el settings.toml guarda ajustes de
# plugins que no están instalados. Se listan aparte, nunca se ocultan.
EXPECTED = ("no loaded plugin with this id",)

# Patrones que siempre son un fallo.
FAIL_PATTERNS = (
    ("[ERR]", "error"),
    ("exceeded its CPU budget", "presupuesto de CPU"),
    ("attempt to call a nil value", "llamada a nil"),
    ("missing glyph", "glifo inexistente"),
    ("unknown button variant", "variante de botón inválida"),
    ("plugin translation key", "clave de traducción inexistente"),
    ("unrecognized widget type", "tipo de widget desconocido"),
    ("syntax error", "error de sintaxis"),
    ("failed to load", "no se pudo cargar"),
    ("exceeded its memory budget", "presupuesto de memoria"),
    ("stack overflow", "desbordamiento de pila"),
)

# Validadores estáticos que se ejecutan sobre el repo.
STATIC_CHECKS = (
    "check-ui-resources.py",
    "check-locals.py",
    "check-luau-globals.py",
)


def log_size() -> int:
    try:
        return os.path.getsize(LOG)
    except OSError:
        return 0


def read_since(offset: int) -> str:
    try:
        with open(LOG, "rb") as handle:
            handle.seek(offset)
            return handle.read().decode("utf-8", "replace")
    except OSError:
        return ""


def run(cmd, timeout=20):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None


def msg(*args) -> None:
    run(["noctalia", "msg", *args])


def manifest_of(plugin: str) -> dict:
    import tomllib

    path = os.path.join(PLUGIN_DIR, plugin, "plugin.toml")
    try:
        with open(path, "rb") as handle:
            return tomllib.load(handle)
    except Exception:  # noqa: BLE001
        return {}


def plugin_id(plugin: str) -> str:
    return manifest_of(plugin).get("id", plugin)


def entries_of(plugin: str, entry_type: str) -> list[str]:
    """Ids de todas las entradas de un tipo (`panel`, `widget`, ...)."""
    data = manifest_of(plugin)
    ident = data.get("id", plugin)
    return [
        "%s:%s" % (ident, entry.get("id", entry_type))
        for entry in data.get(entry_type, []) or []
        if entry.get("id")
    ]


def bool_settings(plugin: str) -> list[str]:
    """Ajustes booleanos del plugin (para probar la escritura)."""
    data = manifest_of(plugin)
    return [
        setting.get("key")
        for setting in data.get("setting", []) or []
        if setting.get("type") == "bool" and setting.get("key")
    ]


def current_bool(plugin: str, key: str) -> bool:
    """Valor actual del ajuste (settings.toml si está, si no el del manifiesto)."""
    import tomllib

    try:
        with open(os.path.join(HOME, ".local/state/noctalia/settings.toml"), "rb") as handle:
            data = tomllib.load(handle)
        section = (data.get("plugin_settings") or {}).get(plugin_id(plugin)) or {}
        if key in section and isinstance(section[key], bool):
            return section[key]
    except Exception:  # noqa: BLE001
        pass
    for setting in manifest_of(plugin).get("setting", []) or []:
        if setting.get("key") == key:
            return bool(setting.get("default"))
    return False


def exercise(plugin: str) -> None:
    """Abre y cierra todas las entradas del plugin."""
    for panel in entries_of(plugin, "panel"):
        msg("panel-toggle", panel)
        time.sleep(1.2)
        msg("panel-toggle", panel)
        time.sleep(0.7)

    # Se prueba tambien la escritura de un ajuste: se reescribe el MISMO
    # valor, asi la configuracion no cambia pero se ejercitan la
    # escritura y la recarga de la configuracion.
    keys = bool_settings(plugin)
    if keys:
        value = current_bool(plugin, keys[0])
        for panel in entries_of(plugin, "panel")[:1]:
            msg(
                "plugin", panel, "all", "set",
                "%s=%s bool" % (keys[0], "true" if value else "false"),
            )
            time.sleep(2.0)

    for widget in entries_of(plugin, "widget"):
        msg("panel-toggle", widget)
        time.sleep(1.0)
        msg("panel-toggle", widget)
        time.sleep(0.5)


def classify(text: str):
    problems = []
    expected = 0
    for line in text.split("\n"):
        if not line.strip():
            continue
        if any(marker in line for marker in EXPECTED):
            expected += 1
            continue
        for marker, label in FAIL_PATTERNS:
            if marker in line:
                problems.append((label, line))
                break
    return problems, expected


def static_checks(root: str):
    failures = []
    for script in STATIC_CHECKS:
        path = os.path.join(root, "tools", script)
        if not os.path.isfile(path):
            failures.append((script, "no se encontró el script"))
            continue
        result = run([sys.executable, path, "--json", root], timeout=180)
        if result is None:
            failures.append((script, "no se pudo ejecutar"))
            continue
        try:
            data = json.loads(result.stdout or "{}")
        except json.JSONDecodeError:
            failures.append((script, "salida ilegible:\n%s" % result.stdout[-400:]))
            continue
        if isinstance(data, list):  # formato antiguo
            items = data
            revisados = None
        else:
            items = data.get("hallazgos", [])
            revisados = data.get("ficheros_revisados")
        # Guarda anti-vacio: un revisor que no ha mirado ningún fichero no
        # puede decir "todo bien". Si no dice cuántos revisó, se avisa.
        if revisados is None:
            failures.append((script, "no informa de cuántos ficheros revisó"))
        elif revisados == 0:
            failures.append((script, "no ha revisado ningún fichero"))
        def describe(item):
            line = item.get("linea", item.get("linea_local", 0))
            message = item.get("mensaje") or item.get("problema") or ""
            name = item.get("nombre")
            if name:
                message = "%s: %s" % (name, message)
            return "  %s:%s  %s" % (item.get("fichero"), line, message)

        errors = [i for i in items if i.get("nivel", "error") == "error"]
        warnings = [i for i in items if i.get("nivel") == "aviso"]
        if errors:
            failures.append(
                (script, "\n".join(describe(item) for item in errors[:20]))
            )
        if warnings:
            print("--- %s: %d aviso(s) ---" % (script, len(warnings)))
            for item in warnings[:15]:
                print(describe(item))
    return failures


def coverage(root: str):
    """Cuantos ficheros .luau se han podido revisar de verdad."""
    from pathlib import Path

    compiled = 0
    skipped = []
    for path in api.luau_files(Path(root)):
        source = path.read_text(encoding="utf-8", errors="replace")
        if api.compile_ok(source) or api.compile_ok(api.normalize(source)):
            compiled += 1
        else:
            skipped.append(str(path))
    return compiled, skipped


def main(argv):
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-ui", action="store_true", help="no tocar la interfaz")
    parser.add_argument("--selftest", action="store_true", help="ejecutar el autotest de los validadores")
    parser.add_argument("--root", default=os.path.join(HOME, "noctalia-plugins"))
    parser.add_argument("plugins", nargs="*")
    args = parser.parse_args(argv[1:])

    plugins = args.plugins
    if not plugins:
        plugins = sorted(
            name
            for name in os.listdir(PLUGIN_DIR)
            if os.path.isdir(os.path.join(PLUGIN_DIR, name))
            and os.path.isfile(os.path.join(PLUGIN_DIR, name, "plugin.toml"))
        )

    failures = []

    if args.selftest:
        print("=== autotest de los validadores ===")
        result = run([sys.executable, os.path.join(args.root, "tools", "selftest.py")], timeout=300)
        print((result.stdout if result else "").strip())
        if result is None or result.returncode != 0:
            failures.append(("selftest.py", "el autotest de los validadores falló"))

    offset = log_size()
    if not args.no_ui:
        for plugin in plugins:
            exercise(plugin)
        time.sleep(2)
    text = read_since(offset)
    problems, expected = classify(text)

    print("plugins ejercitados: %d" % len(plugins))
    print("entradas abiertas: %d" % sum(
        len(entries_of(p, "panel")) + len(entries_of(p, "widget")) for p in plugins
    ))
    print("líneas de log revisadas: %d" % len(text.split("\n")))
    print("avisos esperados (ajustes de plugins no instalados): %d" % expected)
    if problems:
        print("--- PROBLEMAS (%d) ---" % len(problems))
        for label, line in problems[:40]:
            print("  [%s] %s" % (label, line[-220:]))
    else:
        print("--- sin errores ni avisos inesperados ---")

    compiled, skipped = coverage(args.root)
    print("ficheros .luau revisados a fondo: %d" % compiled)
    if skipped:
        print("revisados solo con análisis textual: %d" % len(skipped))
        for path in skipped[:10]:
            print("  %s" % path)

    print("=== validadores estáticos ===")
    failures += static_checks(args.root)
    for script, detail in failures:
        print("--- fallo de %s ---\n%s" % (script, detail))

    return 1 if (problems or failures) else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
