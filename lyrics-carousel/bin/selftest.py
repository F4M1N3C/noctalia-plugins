#!/usr/bin/env python3
"""Autotest del plugin Lyrics Carousel.

Comprueba las suposiciones del entorno de instalación, que son la causa
raíz de los fallos más molestos: el helper puede no estar donde se espera
(el script se lanza por un enlace simbólico), el directorio de datos puede no
existir y pueden faltar herramientas externas.

Uso:  python3 bin/selftest.py [--verbose]
Devuelve 1 si algo falla.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN_DIR = os.path.dirname(HERE)
HELPER = os.path.join(HERE, "set-setting.py")
DATA_DIR = os.path.expanduser(
    "~/.local/state/noctalia/plugins/data/faminec/lyrics-carousel"
)

results = []


def check(name: str, ok: bool, detail: str = ""):
    results.append((name, ok, detail))
    return ok


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
            check("el helper crea el directorio", False, str(error))

    # 5) herramientas externas.
    for tool in ("kitty", "fc-match", "playerctl", "hyprctl"):
        check(f"herramienta {tool}", shutil.which(tool) is not None)

    # 6) Pillow (modo imagen).
    try:
        import PIL  # noqa: F401

        check("pillow", True)
    except ImportError as error:
        check("pillow", False, str(error))

    # 7) el script se resuelve a si mismo con realpath (el enlace simbolico
    #    de ~/.local/bin no puede romper la localizacion del helper).
    try:
        import importlib.machinery

        module = importlib.machinery.SourceFileLoader(
            "lyrics_carousel_selftest", os.path.join(HERE, "lyrics-carousel")
        ).load_module()
        resolved = os.path.dirname(os.path.realpath(module.__file__))
        check("helper junto al script", resolved == HERE, resolved)
    except Exception as error:  # noqa: BLE001
        check("helper junto al script", False, repr(error)[:120])

    failed = 0
    for name, ok, detail in results:
        if not ok:
            failed += 1
        if verbose or not ok:
            print("  %s %s%s" % ("ok " if ok else "FALLO", name, (" -> " + detail) if detail else ""))
    print("%d comprobación(es), %d fallo(s)" % (len(results), failed))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
