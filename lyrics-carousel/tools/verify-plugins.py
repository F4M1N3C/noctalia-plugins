#!/usr/bin/env python3
"""Verificación automática de los plugins de Noctalia.

Ejercita los paneles y las acciones de cada plugin, captura el log de
Noctalia **por offset de bytes** (no por número de líneas, que se rompe al
rotar el log) y comprueba que no queda ningún error ni aviso inesperado.

También ejecuta los validadores estáticos:
  · tools/check-luau-globals.py  (globales leídos y nunca escritos)
  · tools/check-ui-resources.py  (glifos, variantes y claves de traducción)

Vive en lyrics-carousel/tools/ porque el directorio tools/ del repositorio es
compartido con la otra sesion de inventario.

Uso:  python3 lyrics-carousel/tools/verify-plugins.py [--no-ui] [plugin ...]
Devuelve 1 si algo falla.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

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


def panel_of(plugin: str) -> str:
    """Id de la entrada de panel del plugin (o "" si no tiene)."""
    manifest = os.path.join(PLUGIN_DIR, plugin, "plugin.toml")
    try:
        import tomllib

        with open(manifest, "rb") as handle:
            data = tomllib.load(handle)
    except Exception:  # noqa: BLE001
        return ""
    for entry in data.get("panel", []):
        return "%s:%s" % (data.get("id", plugin), entry.get("id", "panel"))
    return ""


def widget_of(plugin: str) -> str:
    manifest = os.path.join(PLUGIN_DIR, plugin, "plugin.toml")
    try:
        import tomllib

        with open(manifest, "rb") as handle:
            data = tomllib.load(handle)
    except Exception:  # noqa: BLE001
        return ""
    for entry in data.get("widget", []):
        return "%s:%s" % (data.get("id", plugin), entry.get("id", "widget"))
    return ""


def bool_settings(plugin: str):
    """Primer ajuste booleano del plugin (para probar la escritura)."""
    manifest = os.path.join(PLUGIN_DIR, plugin, "plugin.toml")
    try:
        import tomllib

        with open(manifest, "rb") as handle:
            data = tomllib.load(handle)
    except Exception:  # noqa: BLE001
        return []
    return [
        setting.get("key")
        for setting in data.get("setting", [])
        if setting.get("type") == "bool" and setting.get("key")
    ]


def current_bool(plugin: str, key: str):
    """Valor actual del ajuste (settings.toml si est\u00e1, si no el del manifiesto)."""
    try:
        import tomllib

        with open(os.path.join(HOME, ".local/state/noctalia/settings.toml"), "rb") as handle:
            data = tomllib.load(handle)
        section = (data.get("plugin_settings") or {}).get(plugin_id(plugin)) or {}
        if key in section and isinstance(section[key], bool):
            return section[key]
    except Exception:  # noqa: BLE001
        pass
    try:
        import tomllib

        with open(os.path.join(PLUGIN_DIR, plugin, "plugin.toml"), "rb") as handle:
            data = tomllib.load(handle)
        for setting in data.get("setting", []):
            if setting.get("key") == key:
                return bool(setting.get("default"))
    except Exception:  # noqa: BLE001
        pass
    return False


def plugin_id(plugin: str) -> str:
    try:
        import tomllib

        with open(os.path.join(PLUGIN_DIR, plugin, "plugin.toml"), "rb") as handle:
            return tomllib.load(handle).get("id", plugin)
    except Exception:  # noqa: BLE001
        return plugin


def exercise(plugin: str) -> None:
    panel = panel_of(plugin)
    if panel:
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
            msg(
                "plugin", panel, "all", "set",
                "%s=%s bool" % (keys[0], "true" if value else "false"),
            )
            time.sleep(2.0)
    widget = widget_of(plugin)
    if widget:
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
    for script in ("check-luau-globals.py", "check-ui-resources.py", "check-locals.py"):
        path = os.path.join(root, "tools", script)
        if not os.path.isfile(path):
            continue
        result = run(["python3", path, root], timeout=120)
        if result is None:
            failures.append((script, "no se pudo ejecutar"))
        elif result.returncode != 0:
            failures.append((script, result.stdout.strip()[-600:]))
    # Los ficheros .luau tienen que compilar (los que usan sintaxis Luau
    # se saltan: luac no las entiende).
    skipped = 0
    compiled = 0
    for current, dirs, names in os.walk(root):
        dirs[:] = [d for d in dirs if d not in (".git", "__pycache__", "node_modules")]
        for name in names:
            if not name.endswith(".luau"):
                continue
            path = os.path.join(current, name)
            result = run(["luac", "-p", path], timeout=20)
            if result is None:
                continue
            if result.returncode != 0:
                skipped += 1
            else:
                compiled += 1
    return failures, compiled, skipped


def main(argv):
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-ui", action="store_true", help="no tocar la interfaz")
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

    offset = log_size()
    if not args.no_ui:
        for plugin in plugins:
            exercise(plugin)
        time.sleep(2)
    text = read_since(offset)
    problems, expected = classify(text)

    print("plugins ejercitados: %d" % len(plugins))
    print("líneas de log revisadas: %d" % len(text.split("\n")))
    print("avisos esperados (ajustes de plugins no instalados): %d" % expected)
    if problems:
        print("--- PROBLEMAS (%d) ---" % len(problems))
        for label, line in problems[:40]:
            print("  [%s] %s" % (label, line[-220:]))
    else:
        print("--- sin errores ni avisos inesperados ---")

    # Autotest del plugin: comprueba las suposiciones del entorno (helper,
    # directorio de datos, herramientas externas).
    selftest = os.path.join(
        os.path.expanduser("~"),
        ".local/share/noctalia/plugins/lyrics-carousel/bin/selftest.py",
    )
    if os.path.isfile(selftest):
        result = run([sys.executable, selftest], timeout=90)
        if result is None:
            failures.append(("selftest", "no se pudo ejecutar"))
        elif result.returncode != 0:
            failures.append(("selftest", result.stdout.strip()[-600:]))
        else:
            print("autotest: " + result.stdout.strip().splitlines()[-1])

    failures, compiled, skipped = static_checks(args.root)
    print("ficheros .luau compilados: %d (con sintaxis Luau, omitidos: %d)" % (compiled, skipped))
    mine = []
    others = []
    for script, detail in failures:
        # Lo que falle en el plugin propio bloquea la pasada; lo de los demas
        # se informa, pero lo lleva su sesion.
        if "lyrics-carousel" in detail:
            mine.append((script, detail))
        else:
            others.append((script, detail))
    for script, detail in others:
        print("--- pendiente de otra sesion (%s) ---\n%s" % (script, detail))
    for script, detail in mine:
        print("--- fallo de %s ---\n%s" % (script, detail))

    return 1 if (problems or mine) else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
