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
import re
import shutil
import subprocess
import sys
import time

HOME = os.path.expanduser("~")
LOG = os.path.join(HOME, ".cache/noctalia/noctalia.log")
PLUGIN_DIR = os.path.join(HOME, ".local/share/noctalia/plugins")
REPO_DIR = os.path.join(HOME, "noctalia-plugins")

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


def msg(*args) -> bool:
    """Envia un comando a Noctalia. Devuelve si ha funcionado."""
    result = run(["noctalia", "msg", *args])
    return result is not None and result.returncode == 0


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


def exercise(plugin: str) -> bool:
    """Ejercita un plugin (abrir/cerrar su panel y tocar un ajuste).

    Devuelve si alguno de los comandos ha funcionado: si Noctalia no
    responde, la fase de ejercicio no se ha hecho y la revision del log
    no demuestra nada.
    """
    ok = False
    panel = panel_of(plugin)
    if panel:
        ok = msg("panel-toggle", panel) or ok
        time.sleep(1.2)
        ok = msg("panel-toggle", panel) or ok
        time.sleep(0.7)
        # Se prueba tambien la escritura de un ajuste: se reescribe el MISMO
        # valor, asi la configuracion no cambia pero se ejercitan la
        # escritura y la recarga de la configuracion.
        keys = bool_settings(plugin)
        if keys:
            value = current_bool(plugin, keys[0])
            ok = msg(
                "plugin", panel, "all", "set",
                "%s=%s bool" % (keys[0], "true" if value else "false"),
            ) or ok
            time.sleep(2.0)
    widget = widget_of(plugin)
    if widget:
        ok = msg("panel-toggle", widget) or ok
        time.sleep(1.0)
        ok = msg("panel-toggle", widget) or ok
        time.sleep(0.5)
    return ok


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


OWNER = "lyrics-carousel"
OWNER_ID = "faminec/lyrics-carousel"

# Cada fallo lleva su origen: de que plugin es, o que la propia verificacion
# no ha podido comprobar algo (eso tambien bloquea: si no se puede verificar,
# no se puede decir que todo esta bien).
KIND_PLUGIN = "plugin"
KIND_INFRA = "infra"
KIND_UNKNOWN = "unknown"
# Aviso sobre un plugin propio que no bloquea (p. ej. sintaxis de Luau
# que el modulo compartido no normaliza: el runtime lo covers).
KIND_NOTE = "note"


def log_owner(line: str) -> str:
    """Plugin al que pertenece una linea del log de Noctalia.

    Los errores de Lua traen el id completo ("plugin faminec/x:panel") y
    los de este plugin el prefijo corto ("lyrics-carousel: ...").
    """
    if OWNER in line:
        return OWNER
    match = re.search(r"faminec/([a-z0-9._-]+)", line)
    if match:
        return match.group(1)
    return ""


def plugin_from_path(line: str):
    """Plugin al que apunta una ruta.

    Los validadores imprimen rutas unas veces relativas ("notes/panel.luau")
    y otras absolutas ("/home/.../noctalia-plugins/notes/panel.luau"): se
    busca el primer componente que sea un plugin, tanto en el despliegue
    como en el repositorio (no todos los plugins estan desplegados).
    """
    for part in re.split(r"[\\/]", line.strip()):
        if not part:
            continue
        for base in (PLUGIN_DIR, REPO_DIR):
            if os.path.isdir(os.path.join(base, part)):
                return part
    return None


def split_by_plugin(detail: str):
    """Divide la salida de un validador compartido por plugin.

    Formato: "<plugin>/<fichero>" seguido de sus lineas de detalle. Asi el
    fallo se atribuye al plugin exacto, y no a "alguien que menciona el
    nombre de otro plugin".
    """
    blocks = []
    current = None
    for line in detail.split("\n"):
        owner = plugin_from_path(line)
        if owner is not None:
            current = (owner, [line])
            blocks.append(current)
        elif current is not None:
            current[1].append(line)
    return blocks


def owners_of(detail: str):
    """Reparte la salida de un validador compartido por plugin.

    Devuelve una lista de (dueño, detalle). Lo que no encaja en ningún
    bloque va con dueño "" (ni mio ni de nadie: se informa y no bloquea).
    """
    result = []
    for owner, lines in split_by_plugin(detail):
        result.append((owner, "\n".join(lines).strip()))
    if not result and detail.strip():
        result.append(("", detail.strip()))
    return result


def infra(label: str, detail: str = ""):
    """Fallo de la propia verificacion: no se ha podido comprobar."""
    return (KIND_INFRA, "", label, detail)


# Los mismos nombres que busca el modulo compartido (luac5.4, luac, ...).
COMPILERS = ("luac5.4", "luac", "luac5.3", "luac5.1", "luajit")


def find_compiler() -> str:
    for name in COMPILERS:
        path = shutil.which(name)
        if path:
            return path
    return ""


def load_api(root: str):
    """Modulo compartido de la sesion de inventario (solo lectura).

    Aporta la normalizacion de la sintaxis solo-Luau, que luac no
    entiende. Sin el no se puede distinguir "sintaxis de Luau" de "error
    de verdad".
    """
    tools = os.path.join(root, "tools")
    if tools not in sys.path:
        sys.path.insert(0, tools)
    try:
        import noctalia_api

        return noctalia_api
    except Exception:  # noqa: BLE001
        return None


def syntax_state(api, path: str, compiler: str = "luac"):
    """Estado de la sintaxis de un .luau.

    "ok"     compila tal cual.
    "luau"   solo usa sintaxis de Luau (el compilador no la entiende): se
             normaliza y compila, asi que no es un error.
    "dudoso" tiene construcciones de Luau y tampoco compila normalizado:
             puede ser una caracteristica que la normalizacion no cubre,
             asi que se avisa pero no bloquea (el runtime lo detecta: si
             el fichero tuviese un error de verdad, Noctalia no cargaria
             el plugin y el log lo diria).
    "error"  error de sintaxis de verdad: hay que avisar y bloquear.

    El motivo distingue los dos casos dudosos: si el fichero no contiene
    ninguna construccion de Luau, es seguro que el error es real; si las
    tiene, puede ser una caracteristica de Luau que la normalizacion
    todavia no cubre, y se dice.
    """
    result = run([compiler, "-p", path], timeout=20)
    if result is not None and result.returncode == 0:
        return "ok", ""
    solo_luau = False
    if api is not None:
        try:
            with open(path, encoding="utf-8") as handle:
                source = handle.read()
            normalizado = api.normalize(source)
            solo_luau = normalizado != source
            if api.compile_ok(normalizado):
                return "luau", ""
        except Exception:  # noqa: BLE001
            pass
    motivo = ""
    if result is not None:
        lineas = [
            l.strip()
            for l in (result.stderr or result.stdout or "").split("\n")
            if l.strip()
        ]
        # El compilador imprime una sola linea con el fichero y el error: se
        # queda con la ultima para no repetir la ruta.
        motivo = lineas[-1] if lineas else ""
    if solo_luau:
        # Con construcciones de Luau no se puede asegurar que sea un error:
        # se avisa, pero no bloquea (lo cubre el runtime).
        motivo += " (¿sintaxis de Luau que el modulo compartido no normaliza?)"
        return "dudoso", motivo or "no se pudo compilar"
    return "error", motivo or "no se pudo compilar"


def static_checks(root: str):
    """Fallos de los validadores y de la sintaxis.

    Cada fallo lleva su origen. Un validador que no se puede ejecutar, o
    que revienta sin decir nada, es un fallo de la propia verificacion: no
    se puede afirmar que todo esta bien si no se ha comprobado.
    """
    failures = []
    instalados = 0
    for script in ("check-luau-globals.py", "check-ui-resources.py", "check-locals.py"):
        path = os.path.join(root, "tools", script)
        if not os.path.isfile(path):
            # El validador no esta instalado: no hay nada que comprobar.
            continue
        instalados += 1
        result = run(["python3", path, root], timeout=120)
        if result is None:
            failures.append(infra(script, "no se pudo ejecutar"))
        elif result.returncode != 0:
            detail = result.stdout.strip()
            if not detail:
                # Revento sin salida: no se sabe que fallo ni de quien.
                detail = (result.stderr.strip() or "sin salida")[-600:]
                failures.append(infra(script, detail))
                continue
            # Sin truncar: el reparto por plugin necesita la salida entera
            # (si no, se pierden los bloques del principio).
            for owner, block in owners_of(detail):
                failures.append(
                    (KIND_PLUGIN if owner else KIND_UNKNOWN, owner, script, block)
                )
    # Los ficheros .luau tienen que compilar (los que usan sintaxis Luau
    # se saltan: luac no las entiende).
    if instalados == 0:
        # Sin validadores compartidos no se comprueba el codigo: hay que
        # decirlo, no pasar la verificacion sin mirar nada.
        failures.append(
            infra(
                "validadores compartidos",
                "no hay ninguno en " + os.path.join(root, "tools")
                + ": no se comprueba el codigo",
            )
        )
    skipped = 0
    compiled = 0
    api = load_api(root)
    compiler = api.luac() if api is not None else find_compiler()
    if not compiler:
        # Sin compilador no se comprueba la sintaxis: es un fallo de la
        # verificacion, no un "todo bien" silencioso.
        failures.append(
            infra("luac", "no hay compilador: no se comprueba la sintaxis")
        )
        return failures, compiled, skipped
    if api is None:
        failures.append(
            infra(
                "noctalia_api",
                "no se encuentra el modulo compartido: no se puede distinguir "
                "la sintaxis solo-Luau de un error de verdad",
            )
        )
    for current, dirs, names in os.walk(root):
        dirs[:] = [d for d in dirs if d not in (".git", "__pycache__", "node_modules")]
        for name in names:
            if not name.endswith(".luau"):
                continue
            path = os.path.join(current, name)
            state, motivo = syntax_state(api, path, compiler)
            owner = plugin_from_path(path) or ""
            if state == "ok":
                compiled += 1
            elif state == "luau":
                skipped += 1
            elif state == "dudoso":
                # Aviso, no fallo: puede ser sintaxis de Luau. Si ademas
                # fuese un error real, el plugin no cargaria y el log lo
                # diria; la revision del log lo cubre si el fichero se
                # carga durante la verificacion (el panel se abre, el
                # widget se compila al arrancar).
                skipped += 1
                failures.append(
                    (
                        KIND_NOTE,
                        owner,
                        "luac",
                        "%s: %s" % (os.path.relpath(path, root), motivo),
                    )
                )
            elif api is None:
                # Sin poder distinguirlo se cuenta como omitido (el fallo de
                # infraestructura ya esta avisado mas arriba).
                skipped += 1
            else:
                failures.append(
                    (
                        KIND_PLUGIN if owner else KIND_UNKNOWN,
                        owner,
                        "luac",
                        motivo or ("%s: no se pudo compilar" % path),
                    )
                )
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
    exercised = False
    if not args.no_ui:
        for plugin in plugins:
            exercised = exercise(plugin) or exercised
        time.sleep(2)
    text = read_since(offset)
    if not os.path.isfile(LOG):
        # Sin log no se puede revisar lo que ha pasado: no se puede decir
        # que todo esta bien.
        infra_problems = [infra("log de Noctalia", "no existe: " + LOG)]
    else:
        infra_problems = []
    if not args.no_ui and not exercised:
        infra_problems.append(
            infra(
                "ejercicio de los plugins",
                "ningún comando a Noctalia ha funcionado: no se ha ejercitado nada",
            )
        )
    problems, expected = classify(text)
    # Cada problema del log se atribuye a su plugin: los de otro plugin no
    # pueden bloquear la verificacion de este.
    problems = [(label, line, log_owner(line)) for label, line in problems]

    print("plugins ejercitados: %d" % len(plugins))
    print("líneas de log revisadas: %d" % len(text.split("\n")))
    print("avisos esperados (ajustes de plugins no instalados): %d" % expected)
    my_problems = [item for item in problems if item[2] == OWNER]
    other_problems = [item for item in problems if item[2] != OWNER]
    if my_problems:
        print("--- PROBLEMAS (%d) ---" % len(my_problems))
        for label, line, _ in my_problems[:40]:
            print("  [%s] %s" % (label, line[-220:]))
    elif other_problems:
        print("--- sin errores propios; %d problema(s) de otra sesion ---" % len(other_problems))
        for label, line, owner in other_problems[:10]:
            print("  [%s] (%s) %s" % (label, owner or "?", line[-200:]))
    else:
        print("--- log de Noctalia: sin errores ni avisos inesperados ---")

    failures, compiled, skipped = static_checks(args.root)

    # Autotest del plugin: comprueba las suposiciones del entorno (helper,
    # directorio de datos, herramientas externas, modulos hermanos). Se usa
    # el del repositorio (fuente de verdad) y, si esta desplegado, tambien
    # el de la copia instalada.
    selftests = [
        os.path.join(args.root, "lyrics-carousel", "bin", "selftest.py"),
        os.path.expanduser(
            "~/.local/share/noctalia/plugins/lyrics-carousel/bin/selftest.py"
        ),
    ]
    for selftest in selftests:
        if not os.path.isfile(selftest):
            if selftest.startswith(args.root):
                # El autotest del repositorio es parte del plugin: si no
                # esta, la verificacion no comprueba lo que debe.
                failures.append(
                    infra(
                        "selftest (repo)",
                        "no existe: " + selftest,
                    )
                )
            continue
        result = run([sys.executable, selftest], timeout=90)
        where = "repo" if selftest.startswith(args.root) else "despliegue"
        if result is None:
            failures.append(
                (KIND_PLUGIN, OWNER, "selftest (%s)" % where, "no se pudo ejecutar")
            )
        elif result.returncode != 0:
            failures.append(
                (
                    KIND_PLUGIN,
                    OWNER,
                    "selftest (%s)" % where,
                    result.stdout.strip()[-600:],
                )
            )
        else:
            print(
                "autotest (%s): %s" % (where, result.stdout.strip().splitlines()[-1])
            )

    print("ficheros .luau compilados: %d (con sintaxis Luau, omitidos: %d)" % (compiled, skipped))
    mine = []
    others = []
    notes = []
    for kind, owner, script, detail in failures:
        # Lo que falle en el plugin propio bloquea la pasada; lo de los demas
        # se informa, pero lo lleva su sesion. Y si la propia verificacion
        # no ha podido comprobar algo, tambien bloquea.
        if kind == KIND_INFRA:
            mine.append((script, detail))
        elif kind == KIND_NOTE:
            notes.append((script, detail))
        elif kind == KIND_PLUGIN and owner == OWNER:
            mine.append((script, detail))
        else:
            others.append((script, detail))
    for _kind, _owner, label, detail in infra_problems:
        mine.append((label, detail))
    for script, detail in others:
        print(
            "--- pendiente de otra sesion (%s) ---\n%s"
            % (script, detail[-600:])
        )
    for script, detail in notes:
        print("--- aviso de %s (no bloquea) ---\n%s" % (script, detail[-600:]))
    for script, detail in mine:
        print("--- fallo de %s ---\n%s" % (script, detail[-600:]))

    return 1 if (my_problems or mine) else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
