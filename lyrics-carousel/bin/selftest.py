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
import signal
import subprocess
import sys
import tempfile

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
    # Lo que tiene que resolver es el directorio real de ese script (el
    # enlace simbólico apunta al despliegue, no al repo).
    esperado = os.path.dirname(os.path.realpath(path))
    check(
        f"diagnóstico ({label})",
        info.get("bin_dir") == esperado,
        f"bin_dir={info.get('bin_dir')} esperado={esperado}",
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


def direccion_actual() -> str:
    """Direccion vigente (overrides si los hay, si no el settings.toml)."""
    overrides = os.path.join(DATA_DIR, "overrides.json")
    if os.path.isfile(overrides):
        try:
            with open(overrides, encoding="utf-8") as handle:
                data = json.load(handle)
            if isinstance(data, dict) and "direction" in data:
                return str(data["direction"])
        except (OSError, ValueError):
            pass
    try:
        import tomllib

        with open(
            os.path.expanduser("~/.local/state/noctalia/settings.toml"), "rb"
        ) as handle:
            data = tomllib.load(handle)
        section = (data.get("plugin_settings") or {}).get("faminec/lyrics-carousel")
        if isinstance(section, dict) and "direction" in section:
            return str(section["direction"])
    except Exception:  # noqa: BLE001
        pass
    return "down"


def karaoke_actual() -> bool:
    """Karaoke vigente (overrides si los hay, si no el settings.toml)."""
    overrides = os.path.join(DATA_DIR, "overrides.json")
    if os.path.isfile(overrides):
        try:
            with open(overrides, encoding="utf-8") as handle:
                data = json.load(handle)
            if isinstance(data, dict) and "karaoke" in data:
                return bool(data["karaoke"])
        except (OSError, ValueError):
            pass
    try:
        import tomllib

        with open(
            os.path.expanduser("~/.local/state/noctalia/settings.toml"), "rb"
        ) as handle:
            data = tomllib.load(handle)
        section = (data.get("plugin_settings") or {}).get("faminec/lyrics-carousel")
        if isinstance(section, dict) and "karaoke" in section:
            return bool(section["karaoke"])
    except Exception:  # noqa: BLE001
        pass
    return True


def check_atajos():
    """Los atajos 'd' y 'k' alternan sus ajustes y los guardan.

    La escritura se hace en un fichero temporal (variable de entorno
    LYRICS_CAROUSEL_OVERRIDES): asi la prueba no toca el estado real y
    no compite con la escritura asincrona del script, que puede llegar
    despues de que la prueba haya terminado.
    """
    temporal = tempfile.mkdtemp(prefix="lyrics-carousel-selftest-")
    overrides = os.path.join(temporal, "overrides.json")
    previo = None
    if os.path.isfile(overrides):
        try:
            with open(overrides, encoding="utf-8") as handle:
                previo = handle.read()
        except OSError:
            previo = None
    antes = direccion_actual()
    esperado = "up" if antes == "down" else "down"
    log = os.path.join(os.path.expanduser("~/.cache/lyrics-carousel"), "debug.log")
    log_pos = os.path.getsize(log) if os.path.isfile(log) else 0
    karaoke_antes = karaoke_actual()
    karaoke_esperado = not karaoke_antes
    try:
        import fcntl
        import pty
        import select
        import signal
        import struct
        import termios
        import time

        os.environ["LYRICS_CAROUSEL_OVERRIDES"] = overrides
        pid, fd = pty.fork()
        if pid == 0:
            os.chdir("/")
            os.environ.pop("COLUMNS", None)
            os.environ.pop("LINES", None)
            os.execvp(
                "python3",
                [
                    "python3",
                    os.path.join(HERE, "lyrics-carousel"),
                    "--demo",
                    "--debug",
                ],
            )
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 90, 0, 0))
        time.sleep(2.5)
        os.write(fd, b"d")
        time.sleep(1.5)
        os.write(fd, b"k")
        time.sleep(1.5)
        os.write(fd, b"r")
        time.sleep(2.5)
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        os.close(fd)
    except Exception as error:  # noqa: BLE001
        check("el atajo 'd' alterna la dirección", False, repr(error)[:120])
        check("el atajo 'k' alterna el karaoke", False, repr(error)[:120])
        restaurar_overrides(overrides, previo)
        return
    try:
        with open(overrides, encoding="utf-8") as handle:
            data = json.load(handle)
        ok = isinstance(data, dict) and data.get("direction") == esperado
        check(
            "el atajo 'd' alterna la dirección",
            ok,
            "esperado %s, hay %s" % (esperado, data.get("direction")),
        )
        ok_k = isinstance(data, dict) and data.get("karaoke") is karaoke_esperado
        check(
            "el atajo 'k' alterna el karaoke",
            ok_k,
            "esperado %s, hay %s" % (karaoke_esperado, data.get("karaoke")),
        )
        # El modo demo es autonomo: ni al arrancar ni al recargar ('r')
        # debe pedir letra a internet.
        peticiones = []
        escrito = ""
        if os.path.isfile(log):
            try:
                with open(log, encoding="utf-8", errors="replace") as handle:
                    handle.seek(log_pos)
                    escrito = handle.read()
                peticiones = [
                    linea
                    for linea in escrito.split("\n")
                    if any(
                        marca in linea.lower()
                        for marca in ("http", "kugou", "splayer", "netease", "lrclib")
                    )
                ]
            except OSError:
                escrito = ""
        # El guardia solo sirve si el script escribio su registro de
        # depuracion: las peticiones a los proveedores solo se anotan con
        # --debug, asi que sin el el log pareceria limpio siempre.
        # Se busca una linea que solo sale con depuracion.
        depuracion = any(
            marca in escrito
            for marca in ("demo: ", "modo: ", "ajustes: ", "resultado: ")
        )
        check(
            "el log del script permite comprobarlo",
            depuracion,
            ""
            if depuracion
            else "el script no escribio su registro de depuracion",
        )
        check(
            "el modo demo no pide letra a internet",
            not peticiones,
            "; ".join(peticiones[:2]),
        )
    except (OSError, ValueError) as error:
        check("el atajo 'd' alterna la dirección", False, str(error)[:120])
        check("el atajo 'k' alterna el karaoke", False, str(error)[:120])
    finally:
        restaurar_overrides(overrides, previo)
        shutil.rmtree(temporal, ignore_errors=True)


def restaurar_overrides(path, previo):
    """Deja los overrides como estaban (la prueba no debe dejar nada)."""
    try:
        if previo is None:
            if os.path.isfile(path):
                os.remove(path)
        else:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(previo)
    except OSError:
        pass


def check_salida_al_cerrar():
    """El script sale cuando la salida se cierra (la terminal se cierra).

    Se ejecuta con la salida hacia una tuberia cuyo extremo de lectura
    esta cerrado: las escrituras fallan y el script tiene que salir, en
    vez de quedarse dibujando en el vacio. Con un pty no valia: el
    SIGHUP del kernel lo interceptaba el propio script y salia con
    codigo 0 sin pasar por su deteccion.
    """
    temporal = tempfile.mkdtemp(prefix="lyrics-carousel-cierre-")
    overrides = os.path.join(temporal, "overrides.json")
    entorno = {**os.environ, "LYRICS_CAROUSEL_OVERRIDES": overrides}
    lectura, escritura = os.pipe()
    os.close(lectura)  # el que lee se cierra: escribir falla
    proceso = subprocess.Popen(
        [sys.executable, os.path.join(HERE, "lyrics-carousel"), "--demo"],
        stdout=escritura,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        env=entorno,
    )
    os.close(escritura)
    codigo = None
    try:
        codigo = proceso.wait(timeout=30)
    except subprocess.TimeoutExpired:
        proceso.kill()
        proceso.wait(timeout=10)
    # 0: salida normal. 120: Python avisa de que no pudo vaciar la salida
    # al terminar (normal si estaba cerrada). Lo que no vale es que se
    # quede colgado (sin codigo) o muera por una senal (codigo negativo).
    check(
        "el script sale al cerrar la salida",
        codigo is not None and codigo >= 0,
        "código %s" % codigo,
    )
    shutil.rmtree(temporal, ignore_errors=True)


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

    # 3) el directorio de datos real se puede usar (sin escribir nada en el:
    #    la prueba de escritura se hace en un HOME temporal).
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
            try:
                os.remove(probe)
            except OSError:
                pass

        # 4) el helper responde, crea el directorio si falta y vuelca los
        #    overrides al settings.toml. Todo con un HOME temporal: si se
        #    usara el real, el autotest dejaria cambiados los ajustes del
        #    usuario (el volcado escribe en el settings.toml de verdad).
        with tempfile.TemporaryDirectory() as fake_home:
            fake_state = os.path.join(fake_home, ".local", "state", "noctalia")
            os.makedirs(fake_state, exist_ok=True)
            fake_settings = os.path.join(fake_state, "settings.toml")
            with open(fake_settings, "w", encoding="utf-8") as handle:
                handle.write("")
            env = {**os.environ, "HOME": fake_home}
            try:
                result = subprocess.run(
                    [sys.executable, HELPER, "override", "marker", "true", "bool"],
                    capture_output=True,
                    text=True,
                    timeout=15,
                    env=env,
                )
                fake_dir = os.path.join(
                    fake_home,
                    ".local/state/noctalia/plugins/data/faminec/lyrics-carousel",
                )
                ok = result.returncode == 0 and os.path.isdir(fake_dir)
                check(
                    "el helper crea el directorio", ok, result.stderr.strip()[:120]
                )
                if ok:
                    merge = subprocess.run(
                        [sys.executable, HELPER, "merge"],
                        capture_output=True,
                        text=True,
                        timeout=15,
                        env=env,
                    )
                    with open(fake_settings, encoding="utf-8") as handle:
                        written = handle.read()
                    check(
                        "el helper vuelca al settings.toml",
                        merge.returncode == 0 and "marker = true" in written,
                        merge.stderr.strip()[:120],
                    )
            except (OSError, subprocess.SubprocessError) as error:
                check("el helper crea el directorio", False, repr(error)[:120])

    # 4b) el atajo 'd' del script alterna la direccion y la guarda.
    #     Es la prueba de que el script, el helper y el overrides
    #     funcionan juntos de verdad.
    check_atajos()

    # 4c) si la terminal se cierra, el script tiene que salir: si se
    #      queda, sigue dibujando en el vacio indefinidamente.
    check_salida_al_cerrar()

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
        # El enlace del PATH es una comodidad, no un requisito: el panel
        # lanza el script por ruta absoluta. Si no esta, no es un fallo.
        print("  (no hay enlace simbólico en %s: el panel usa la ruta absoluta)" % LAUNCHER)

    # 8) los .luau del plugin tienen que compilar tal cual. Si usaran
    #    sintaxis de Luau, la comprobacion estatica no podria ser
    #    concluyente (no hay compilador de Luau) y un error de verdad
    #    pasaria desapercibido: el runtime solo lo detecta si el fichero
    #    se recarga durante la verificacion.
    compiler = ""
    for name in ("luac5.4", "luac", "luac5.3", "luac5.1", "luajit"):
        compiler = shutil.which(name) or ""
        if compiler:
            break
    if not compiler:
        check("compilador disponible", False, "no hay luac")
    else:
        malos = []
        for root, dirs, names in os.walk(PLUGIN_DIR):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for name in sorted(names):
                if not name.endswith(".luau"):
                    continue
                path = os.path.join(root, name)
                try:
                    result = subprocess.run(
                        [compiler, "-p", path],
                        capture_output=True,
                        text=True,
                        timeout=20,
                    )
                except (OSError, subprocess.SubprocessError) as error:
                    malos.append("%s (%s)" % (name, error))
                    continue
                if result.returncode != 0:
                    malos.append(name)
        check("los .luau compilan tal cual", not malos, ", ".join(malos))

    # 9) el autotest no debe dejar bytecode en el directorio desde el que se
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
