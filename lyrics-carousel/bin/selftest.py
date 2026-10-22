#!/usr/bin/env python3
"""Autotest del plugin Lyrics Carousel.

Comprueba las suposiciones del entorno de instalación, que son la causa raíz
de los fallos más molestos: el script puede lanzarse por un enlace simbólico
(en ese caso sus módulos hermanos y el helper no están en el mismo
directorio), el directorio de datos puede no existir y pueden faltar
herramientas externas.

Uso:  python3 bin/selftest.py [--verbose]
Devuelve 1 si algo falla.

El autotest no deja rastro: no importa el script (eso escribiría bytecode en
el directorio desde el que se lanza), lo ejecuta como proceso con
--diagnostics.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
PLUGIN_DIR = os.path.dirname(HERE)
HELPER = os.path.join(HERE, "set-setting.py")
SCRIPT = os.path.join(HERE, "lyrics-carousel")
DATA_DIR = os.path.expanduser(
    "~/.local/state/noctalia/plugins/data/faminec/lyrics-carousel"
)
# Por donde se lanza de verdad: el enlace simbólico del PATH.
LAUNCHER = os.path.expanduser("~/.local/bin/lyrics-carousel")

results = []


def check(name: str, ok: bool, detail: str = ""):
    results.append((name, ok, detail))
    return ok


def run_script(path: str, cwd: str = "/"):
    """Ejecuta el script con --diagnostics y devuelve el JSON."""
    process = subprocess.run(
        [sys.executable, path, "--diagnostics"],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=cwd,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    if process.returncode != 0:
        raise RuntimeError(
            f"salida {process.returncode}: {process.stderr.strip()[:200]}"
        )
    return json.loads(process.stdout)


def check_diagnostics(label: str, path: str):
    """Comprueba que el script encuentra sus modulos y su helper."""
    try:
        info = run_script(path)
    except Exception as error:  # noqa: BLE001
        check(f"diagnóstico ({label})", False, repr(error)[:160])
        return None
    check(
        f"diagnóstico ({label})",
        info.get("bin_dir") == HERE,
        f"bin_dir={info.get('bin_dir')}",
    )
    check(
        f"módulos hermanos ({label})",
        bool(info.get("image_renderer")) and bool(info.get("graphics")),
        info.get("image_error") or "",
    )
    check(
        f"helper localizado ({label})",
        bool(info.get("helper_exists")),
        info.get("helper") or "",
    )
    return info


def main(argv):
    verbose = "--verbose" in argv

    # 1) el helper tiene que estar al lado del script (ruta real, no la del
    #    enlace simbólico por el que se puede lanzar).
    check("helper presente", os.path.isfile(HELPER), HELPER)
    check("helper ejecutable", os.access(HELPER, os.X_OK))

    # 2) el directorio de datos se puede crear.
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        created = os.path.isdir(DATA_DIR)
    except OSError as error:
        created = False
        check("directorio de datos", False, str(error))
    if created:
        check("directorio de datos", True, DATA_DIR)

    # 3) ida y vuelta de los overrides.
    if created:
        probe = os.path.join(DATA_DIR, "selftest.json")
        try:
            with open(probe, "w", encoding="utf-8") as handle:
                json.dump({"selftest": True}, handle)
            with open(probe, encoding="utf-8") as handle:
                data = json.load(handle)
            os.remove(probe)
            check("escritura de overrides", data.get("selftest") is True)
        except (OSError, ValueError) as error:
            check("escritura de overrides", False, str(error))

        # 4) el helper responde y crea el directorio si falta.
        try:
            shutil.rmtree(DATA_DIR, ignore_errors=True)
            result = subprocess.run(
                [sys.executable, HELPER, "override", "marker", "true", "bool"],
                capture_output=True,
                text=True,
                timeout=15,
            )
            ok = result.returncode == 0 and os.path.isdir(DATA_DIR)
            check("el helper crea el directorio", ok, result.stderr.strip()[:120])
            if ok:
                subprocess.run(
                    [sys.executable, HELPER, "merge"], capture_output=True, timeout=15
                )
        except (OSError, subprocess.SubprocessError) as error:
            check("el helper crea el directorio", False, repr(error)[:120])

    # 5) herramientas externas.
    for tool in ("kitty", "fc-match", "playerctl", "hyprctl"):
        check(f"herramienta {tool}", shutil.which(tool) is not None)

    # 6) Pillow (modo imagen).
    try:
        import PIL  # noqa: F401

        check("pillow", True)
    except ImportError as error:
        check("pillow", False, str(error))

    # 7) el script se resuelve a si mismo con realpath: lanzado por el
    #    enlace simbolico del PATH tiene que encontrar igual sus modulos
    #    hermanos (image_renderer, graphics) y el helper. Sin esto el modo
    #    imagen se caia en silencio al modo texto.
    check_diagnostics("ruta real", SCRIPT)
    if os.path.exists(LAUNCHER):
        check_diagnostics("enlace simbólico", LAUNCHER)
    else:
        check("enlace simbólico disponible", False, LAUNCHER)

    # 8) el autotest no debe dejar bytecode en el directorio desde el que se
    #    lanza el script.
    launcher_dir = os.path.dirname(LAUNCHER)
    cache = os.path.join(launcher_dir, "__pycache__")
    leftovers = []
    if os.path.isdir(cache):
        leftovers = [n for n in os.listdir(cache) if n.startswith("lyrics-carousel")]
    check("sin bytecode en el lanzador", not leftovers, ", ".join(leftovers))

    failed = 0
    for name, ok, detail in results:
        if not ok:
            failed += 1
        if verbose or not ok:
            print(
                "  %s %s%s"
                % ("ok " if ok else "FALLO", name, (" -> " + detail) if detail else "")
            )
    print("%d comprobación(es), %d fallo(s)" % (len(results), failed))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
