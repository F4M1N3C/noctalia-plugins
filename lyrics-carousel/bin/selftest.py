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

import importlib.machinery
import importlib.util
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import types
from contextlib import contextmanager

# Cargar el script con SourceFileLoader (script_module) escribiria
# bin/__pycache__/*.pyc: el autotest no debe dejar rastro en el plugin.
sys.dont_write_bytecode = True

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


@contextmanager
def env_temporal(valores):
    """Aplica variables de entorno solo durante el bloque.

    Las pruebas no pueden tocar el estado real: el cache de letras, el
    settings.toml y los overrides se redirigen a un directorio temporal.
    """
    anterior = dict(os.environ)
    try:
        os.environ.update(valores)
        yield
    finally:
        os.environ.clear()
        os.environ.update(anterior)


@contextmanager
def estado_temporal(base: str):
    """Estado de Noctalia temporal para el proceso actual.

    Sustituye todas las variables que pueden apuntar al estado real, no
    solo XDG_STATE_HOME: paths.py prioriza LYRICS_CAROUSEL_STATE y
    NOCTALIA_STATE_HOME, asi que con esas definidas el script leeria (y
    escribiria) en los ajustes de verdad.

    Devuelve la ruta del directorio de estado (<base>/.local/state/noctalia).
    """
    anterior = dict(os.environ)
    estado = os.path.join(base, ".local", "state")
    destino = os.path.join(estado, "noctalia")
    os.makedirs(destino, exist_ok=True)
    os.environ["XDG_STATE_HOME"] = estado
    os.environ["NOCTALIA_STATE_HOME"] = estado
    os.environ["LYRICS_CAROUSEL_STATE"] = destino
    os.environ["LYRICS_CAROUSEL_OVERRIDES"] = os.path.join(
        destino,
        "plugins",
        "data",
        "faminec",
        "lyrics-carousel",
        "overrides.json",
    )
    try:
        yield destino
    finally:
        os.environ.clear()
        os.environ.update(anterior)


def script_module():
    """Carga el script como modulo para poder probar sus funciones sueltas.

    El script no tiene extension .py, asi que se carga con SourceFileLoader.
    El nombre del modulo no es "__main__": cargar el script no lo ejecuta.
    """
    loader = importlib.machinery.SourceFileLoader("lyrics_carousel_mod", SCRIPT)
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def leer_ajustes(ruta: str) -> dict:
    """Ajustes del plugin en un settings.toml (vacio si no se puede leer)."""
    try:
        import tomllib

        with open(ruta, "rb") as handle:
            data = tomllib.load(handle)
    except Exception:  # noqa: BLE001
        return {}
    section = (data.get("plugin_settings") or {}).get("faminec/lyrics-carousel")
    return section if isinstance(section, dict) else {}


def esperar_ajuste(ruta: str, clave: str, valor, segundos: float = 10.0) -> bool:
    """Espera a que el script guarde un ajuste en el settings.toml.

    El script escribe en segundo plano (el helper va en un proceso aparte),
    asi que el valor no aparece de golpe: se espera un poco.
    """
    limite = time.monotonic() + segundos
    while time.monotonic() < limite:
        if leer_ajustes(ruta).get(clave) == valor:
            return True
        time.sleep(0.2)
    return False


EQ_CHARS = "▁▂▃▄▅▆▇█"


def filas_ecualizador(rows) -> list:
    """Filas que dibujan el ecualizador (los bloques de la barra)."""
    return [i for i, row in enumerate(rows) if any(ch in row for ch in EQ_CHARS)]


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


def check_atajos():
    """Los atajos 'd' y 'k' alternan sus ajustes y los guardan de verdad.

    Todo ocurre en un directorio temporal (entorno_de_prueba): el script
    escribe en el settings.toml y en los overrides, y la prueba no debe
    tocar el estado real del usuario ni competir con la escritura
    asincrona del script.
    """
    temporal = tempfile.mkdtemp(prefix="lyrics-carousel-selftest-")
    estado = os.path.join(temporal, ".local", "state")
    cache = os.path.join(temporal, ".cache")
    ajustes = os.path.join(estado, "noctalia", "settings.toml")
    os.makedirs(os.path.dirname(ajustes), exist_ok=True)
    os.makedirs(cache, exist_ok=True)
    with open(ajustes, "w", encoding="utf-8") as handle:
        handle.write("")
    entorno = entorno_de_prueba(temporal)
    log = os.path.join(cache, "lyrics-carousel", "debug.log")
    try:
        import fcntl
        import pty
        import select
        import signal
        import struct
        import termios

        pid, fd = pty.fork()
        if pid == 0:
            os.chdir("/")
            os.execvpe(
                "python3",
                [
                    "python3",
                    os.path.join(HERE, "lyrics-carousel"),
                    "--demo",
                    "--debug",
                ],
                entorno,
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
        check("el atajo 'd' guarda la dirección", False, repr(error)[:120])
        check("el atajo 'k' guarda el karaoke", False, repr(error)[:120])
        shutil.rmtree(temporal, ignore_errors=True)
        return
    try:
        # El valor tiene que quedar en el settings.toml: si solo se queda
        # en la capa de overrides, el usuario lo pierde al reiniciar.
        ok = esperar_ajuste(ajustes, "direction", "up")
        check(
            "el atajo 'd' guarda la dirección",
            ok,
            "esperado up, hay %s" % (leer_ajustes(ajustes).get("direction"),),
        )
        ok_k = esperar_ajuste(ajustes, "karaoke", False)
        check(
            "el atajo 'k' guarda el karaoke",
            ok_k,
            "esperado false, hay %s" % (leer_ajustes(ajustes).get("karaoke"),),
        )
        # El modo demo es autonomo: ni al arrancar ni al recargar ('r')
        # debe pedir letra a internet.
        peticiones = []
        escrito = ""
        if os.path.isfile(log):
            try:
                with open(log, encoding="utf-8", errors="replace") as handle:
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
    finally:
        shutil.rmtree(temporal, ignore_errors=True)


def check_desfase_scroll():
    """El scroll usa la posicion con el desfase aplicado.

    El resaltado ya usaba position() (con desfase) pero el scroll usaba la
    posicion cruda: con offset_ms distinto de cero la linea resaltada no era
    la que estaba en el centro.
    """
    with tempfile.TemporaryDirectory(prefix="lyrics-carousel-cache-") as cache:
        with env_temporal({"XDG_CACHE_HOME": cache}):
            mod = script_module()
            app = object.__new__(mod.LyricsCarousel)
            app.args = types.SimpleNamespace(once=True)
            app.cfg = dict(mod.DEFAULTS)
            app.cfg["offset_ms"] = 500
            app.demo = False
            app.track = mod.Track("cancion", "artista", duration=300.0, status="Playing")
            app.track.position = 10.0
            app.track.stamp = time.monotonic()
            app.stop_requested = False
            app.output_broken = False
            app.dirty = False
            app.lines = []
            posiciones = []
            app._poll_data = lambda: None
            app.update_size = lambda: None
            app.draw = lambda force=False: None
            app._read_keys = lambda: []
            app._setup_terminal = lambda interactive: None
            app._restore_terminal = lambda interactive: None
            app._update_scroll = lambda position: posiciones.append(position)
            app.run()
            esperado = app.position()
            ok = bool(posiciones) and abs(posiciones[0] - esperado) < 0.05
            check(
                "el desfase se aplica al scroll",
                ok,
                "scroll=%s esperado=%s" % (posiciones[:1], round(esperado, 3)),
            )


def check_busqueda_letra():
    """La busqueda espera 15 s y no marca la cache negativa al agotarse."""
    with tempfile.TemporaryDirectory(prefix="lyrics-carousel-cache-") as cache:
        with env_temporal({"XDG_CACHE_HOME": cache}):
            mod = script_module()
            check(
                "el plazo de búsqueda de letra son 15 s",
                getattr(mod, "SEARCH_TIMEOUT", None) == 15.0,
                "SEARCH_TIMEOUT=%s" % (getattr(mod, "SEARCH_TIMEOUT", None),),
            )
            mod.load_lyrics_settings = lambda: {"sources": ["lrclib"]}
            marcados = []
            mod.mark_missing = lambda track: marcados.append(track)
            track = mod.Track("cancion", "artista", duration=120.0)

            # Un proveedor que no responde: se agota el plazo y la cache
            # negativa NO se marca (la letra puede llegar despues).
            mod.SEARCH_TIMEOUT = 0.4

            def lento(track, log):
                time.sleep(3.0)
                return [], None

            mod.fetch_lrclib = lento
            mod.fetch_lyrics(track, True, lambda message: None)
            check(
                "una búsqueda que agota el plazo no marca la caché negativa",
                not marcados,
                "se marcaron %d" % len(marcados),
            )

            # Todos los proveedores terminan sin letra: la cache negativa
            # se marca (no tiene sentido reintentar cada 60 s la misma
            # cancion).
            marcados.clear()
            mod.SEARCH_TIMEOUT = 5.0
            mod.fetch_lrclib = lambda track, log: ([], None)
            mod.fetch_lyrics(track, True, lambda message: None)
            check(
                "una búsqueda terminada sin letra marca la caché negativa",
                len(marcados) == 1,
                "se marcaron %d" % len(marcados),
            )


def check_reintento_letra():
    """Una letra vacia se reintenta a los 60 s (no a los 180)."""
    with tempfile.TemporaryDirectory(prefix="lyrics-carousel-cache-") as cache:
        with env_temporal({"XDG_CACHE_HOME": cache}):
            mod = script_module()
            check(
                "el reintento de letra vacía son 60 s",
                getattr(mod, "RETRY_SECONDS", None) == 60,
                "RETRY_SECONDS=%s" % (getattr(mod, "RETRY_SECONDS", None),),
            )
            app = object.__new__(mod.LyricsCarousel)
            app.args = types.SimpleNamespace(debug=False)
            app.demo = False
            app._player = None
            app.state = "empty"
            app.track = mod.Track("cancion", "artista")
            app.last_cfg = time.monotonic()
            app.last_reload = time.monotonic()
            app.theme = mod.Theme()
            arranques = []

            class FetcherFalso:
                def take(self):
                    return None

                def start(self, track, force=False):
                    arranques.append(force)

            app.fetcher = FetcherFalso()
            app.last_fetch = time.monotonic() - 61
            app._poll_data()
            check(
                "una letra vacía se reintenta pasados los 60 s",
                len(arranques) == 1,
                "arranques=%s" % (arranques,),
            )
            arranques.clear()
            app.last_fetch = time.monotonic() - 10
            app._poll_data()
            check(
                "una letra vacía no se reintenta antes de los 60 s",
                not arranques,
                "arranques=%s" % (arranques,),
            )


def check_ecualizador_fila():
    """El ecualizador ocupa su propia fila: la letra no la pisa."""
    with tempfile.TemporaryDirectory(prefix="lyrics-carousel-cache-") as cache:
        with env_temporal({"XDG_CACHE_HOME": cache}):
            mod = script_module()
            app = object.__new__(mod.LyricsCarousel)
            app.cfg = dict(mod.DEFAULTS)
            app.language = "en"
            app.texts = mod.TEXTS["en"]
            app.cfg["header"] = False
            app.width = 80
            app.height = 20
            app.theme = mod.Theme()
            app.track = mod.Track()
            app.demo = False
            app.lines = []
            app.source = ""
            app.synced = False
            app.state = "idle"
            app.active_index = 0
            app.last_active = -1
            app.moving = False
            app.scroll = 0.0
            app.status_message = ""

            app.cfg["equalizer"] = False
            sin_ecualizador = filas_ecualizador(app.build_frame())
            app.cfg["equalizer"] = True
            con_ecualizador = filas_ecualizador(app.build_frame())
            ok = (
                len(sin_ecualizador) == 1
                and len(con_ecualizador) == 2
                and con_ecualizador[1] == sin_ecualizador[0] + 1
            )
            check(
                "el ecualizador reserva su fila",
                ok,
                "sin=%s con=%s" % (sin_ecualizador, con_ecualizador),
            )


def check_rutas_estado():
    """El directorio de estado respeta NOCTALIA_STATE_HOME y XDG_STATE_HOME."""
    with tempfile.TemporaryDirectory(prefix="lyrics-carousel-cache-") as cache:
        with env_temporal({"XDG_CACHE_HOME": cache}):
            mod = script_module()
            helper = getattr(mod, "state_dir", None)
            if not callable(helper):
                check(
                    "el directorio de estado respeta XDG_STATE_HOME",
                    False,
                    "no hay helper state_dir",
                )
                check(
                    "el directorio de estado respeta NOCTALIA_STATE_HOME",
                    False,
                    "no hay helper state_dir",
                )
                return
            anterior = dict(os.environ)
            try:
                # LYRICS_CAROUSEL_STATE manda sobre todo lo demas: sin
                # quitarla, estas comprobaciones mirarian el estado de la
                # caja de arena y no el que piden.
                os.environ.pop("LYRICS_CAROUSEL_STATE", None)
                os.environ.pop("NOCTALIA_STATE_HOME", None)
                os.environ["XDG_STATE_HOME"] = "/tmp/xdg-state-prueba"
                check(
                    "el directorio de estado respeta XDG_STATE_HOME",
                    helper() == "/tmp/xdg-state-prueba/noctalia",
                    helper(),
                )
                os.environ["NOCTALIA_STATE_HOME"] = "/tmp/noctalia-state-prueba"
                check(
                    "el directorio de estado respeta NOCTALIA_STATE_HOME",
                    helper() == "/tmp/noctalia-state-prueba/noctalia",
                    helper(),
                )
                os.environ.pop("NOCTALIA_STATE_HOME", None)
                os.environ.pop("XDG_STATE_HOME", None)
                esperado = os.path.expanduser("~/.local/state/noctalia")
                check(
                    "el directorio de estado usa el de Noctalia por defecto",
                    helper() == esperado,
                    helper(),
                )
            finally:
                os.environ.clear()
                os.environ.update(anterior)


def check_idioma_ventana():
    """La ventana habla el idioma pedido (--lang en / --lang es)."""
    with tempfile.TemporaryDirectory(prefix="lyrics-carousel-idioma-") as temporal:
        estado = os.path.join(temporal, ".local", "state", "noctalia")
        os.makedirs(estado, exist_ok=True)
        ajustes = os.path.join(estado, "settings.toml")
        with open(ajustes, "w", encoding="utf-8") as handle:
            handle.write(
                '[plugin_settings."faminec/lyrics-carousel"]\n'
                "hints = true\n"
                'render_mode = "text"\n'
            )
        entorno = entorno_de_prueba(temporal)
        for lang, esperado in (("en", "[q] quit"), ("es", "[q] salir")):
            try:
                proceso = subprocess.run(
                    [sys.executable, SCRIPT, "--demo", "--once", "--lang", lang],
                    capture_output=True,
                    text=True,
                    timeout=30,
                    env=entorno,
                    cwd="/",
                )
            except (OSError, subprocess.SubprocessError) as error:
                check("la ventana tiene los textos en %s" % lang, False, repr(error)[:120])
                continue
            check(
                "la ventana tiene los textos en %s" % lang,
                esperado in proceso.stdout,
                "salida=%s" % proceso.stdout[-160:].replace("\n", " "),
            )


def check_limites_ajustes():
    """Los limites del script son los del manifiesto."""
    with tempfile.TemporaryDirectory(prefix="lyrics-carousel-limites-") as temporal:
        with env_temporal(
            {
                "XDG_CACHE_HOME": os.path.join(temporal, "cache"),
            }
        ), estado_temporal(temporal) as destino:
            os.makedirs(os.path.join(destino, "plugins", "data"), exist_ok=True)
            with open(os.path.join(destino, "settings.toml"), "w", encoding="utf-8") as handle:
                handle.write(
                    '[plugin_settings."faminec/lyrics-carousel"]\n'
                    "width = 100\n"
                    "height = 100\n"
                    "offset_ms = 99999\n"
                )
            mod = script_module()
            cfg = mod.load_settings()
        check("el ancho se limita como el manifiesto", cfg["width"] == 400, str(cfg["width"]))
        check("el alto se limita como el manifiesto", cfg["height"] == 200, str(cfg["height"]))
        check(
            "el desfase se limita como el manifiesto",
            cfg["offset_ms"] == 3000,
            str(cfg["offset_ms"]),
        )


def check_readme():
    """El README documenta lo que el manifiesto declara.

    La tienda exige que el README mencione cada dependencia del manifiesto
    con su nombre exacto, que documente cada entrada (widget, panel) con su
    id y que liste los comandos IPC. Si el manifiesto cambia y el README no,
    el plugin se rechaza en la revision de la tienda; aqui se avisa antes.
    """
    manifest_path = os.path.join(PLUGIN_DIR, "plugin.toml")
    readme_path = os.path.join(PLUGIN_DIR, "README.md")
    try:
        import tomllib

        with open(manifest_path, "rb") as handle:
            manifest = tomllib.load(handle)
    except Exception as error:  # noqa: BLE001
        check("el manifiesto se puede leer", False, repr(error)[:120])
        return
    try:
        with open(readme_path, encoding="utf-8") as handle:
            readme = handle.read()
    except OSError as error:
        check("el README se puede leer", False, repr(error)[:120])
        return

    plugin_id = manifest.get("id", "")
    check("el README cita el id del plugin", f"`{plugin_id}`" in readme, plugin_id)

    # Cada dependencia del manifiesto, con su nombre exacto.
    dependencias = manifest.get("dependencies") or []
    for dependencia in dependencias:
        check(
            f"el README menciona la dependencia `{dependencia}`",
            f"`{dependencia}`" in readme,
            dependencia,
        )

    # Cada entrada (widget, panel) con su id.
    entradas = []
    for clave in ("widget", "panel", "service", "launcher_provider"):
        for entrada in manifest.get(clave) or []:
            entradas.append((clave, entrada.get("id", "")))
    for clave, entrada_id in entradas:
        check(
            f"el README documenta la entrada {clave} `{entrada_id}`",
            f"`{entrada_id}`" in readme,
            entrada_id,
        )

    # El comando IPC del panel, exacto.
    for clave, entrada_id in entradas:
        if clave != "panel":
            continue
        comando = f"noctalia msg panel-toggle {plugin_id}:{entrada_id}"
        check(f"el README trae el comando IPC del panel", comando in readme, comando)

    # Los eventos IPC que el panel y el widget atienden tienen que estar
    # documentados: la plantilla de la tienda los pide cuando el plugin
    # hace algo mas que abrir el panel.
    eventos = set()
    entradas_por_id = {}
    for clave, entrada_id in entradas:
        entradas_por_id[entrada_id] = entrada
    for entrada_id, entrada in entradas_por_id.items():
        entrada_path = os.path.join(PLUGIN_DIR, entrada.get("entry", entrada_id + ".luau"))
        try:
            with open(entrada_path, encoding="utf-8") as handle:
                fuente = handle.read()
        except OSError:
            continue
        for nombre in ("launch", "toggle", "set", "refresh"):
            if f'event == "{nombre}"' in fuente:
                eventos.add(nombre)
    for evento in sorted(eventos):
        comandos = [
            f"noctalia msg plugin {plugin_id}:{entrada_id} all {evento}"
            for entrada_id in entradas_por_id
        ]
        check(
            f"el README documenta el evento IPC `{evento}`",
            any(comando in readme for comando in comandos),
            evento,
        )


def check_titulo_vacio_no_rebusca():
    """Un tema sin titulo (solo artista) no relanza la busqueda en bucle.

    La guarda de _apply_track comparaba la clave y ademas exigia que el tema
    nuevo tuviera titulo. Con un tema sin titulo la condicion nunca se
    cumplia y cada sondeo volvia a pedir la letra.
    """
    with tempfile.TemporaryDirectory(prefix="lyrics-carousel-cache-") as cache:
        with env_temporal({"XDG_CACHE_HOME": cache}):
            mod = script_module()
            app = object.__new__(mod.LyricsCarousel)
            app.args = types.SimpleNamespace(force=False)
            app.track = mod.Track()
            app.track_key = ""
            app.state = "idle"
            app.lines = []
            app.source = ""
            app.synced = False
            app.dirty = False
            app.last_fetch = 0.0
            app.log = lambda message: None
            arranques = []

            class FetcherFalso:
                def start(self, track, force=False):
                    arranques.append(track.key)

            app.fetcher = FetcherFalso()
            tema = mod.Track("", "Artista", "Album", 100.0)
            for _ in range(5):
                app._apply_track(tema)
            check(
                "un tema sin título no relanza la búsqueda",
                len(arranques) == 1,
                "búsquedas=%d" % len(arranques),
            )


def check_timeout_adaptador():
    """El adaptador lento (4 s) no se corta antes de responder.

    El plazo de 3 s mataba a NetEase y QQ Music, que a veces tardan mas:
    la letra se perdia aunque el adaptador fuera a devolverla.
    """
    with tempfile.TemporaryDirectory(prefix="lyrics-carousel-adapter-") as temporal:
        cache = os.path.join(temporal, "cache")
        os.makedirs(cache, exist_ok=True)
        with env_temporal({"XDG_CACHE_HOME": cache}):
            mod = script_module()
            os.makedirs(mod.CACHE_DIR, exist_ok=True)
            script = os.path.join(temporal, "lyric_sources.py")
            with open(script, "w", encoding="utf-8") as handle:
                handle.write(
                    "import json, time\n"
                    "time.sleep(4)\n"
                    "print(json.dumps({'lines': [{'time': 1000, 'duration': 0, 'text': 'hola'}]}))\n"
                )
            original = mod.find_lyric_adapter
            mod.find_lyric_adapter = lambda: script
            try:
                lines, source = mod.run_adapter(
                    "splayer",
                    mod.Track("cancion", "artista", duration=200.0),
                    {},
                    lambda message: None,
                )
            finally:
                mod.find_lyric_adapter = original
            check(
                "el adaptador lento no se corta",
                len(lines) == 1,
                "líneas=%d fuente=%s" % (len(lines), source),
            )


def check_tiempos_reales_no_se_pisan():
    """estimate_times rellena las lineas sin tiempo, no las que ya lo tienen."""
    with tempfile.TemporaryDirectory(prefix="lyrics-carousel-cache-") as cache:
        with env_temporal({"XDG_CACHE_HOME": cache}):
            mod = script_module()
            lines = [
                mod.LyricLine(-1.0, 0.0, "a"),
                mod.LyricLine(-1.0, 0.0, "b"),
                mod.LyricLine(-1.0, 0.0, "c"),
                mod.LyricLine(42.0, 4.0, "d"),
            ]
            mod.estimate_times(lines, 200.0)
            check(
                "estimate_times respeta los tiempos reales",
                abs(lines[3].start - 42.0) < 0.01,
                "start=%.3f" % lines[3].start,
            )


def check_lineas_ordenadas():
    """El resaltado ignora las lineas sin tiempo al buscar por posicion."""
    with tempfile.TemporaryDirectory(prefix="lyrics-carousel-cache-") as cache:
        with env_temporal({"XDG_CACHE_HOME": cache}):
            mod = script_module()
            app = object.__new__(mod.LyricsCarousel)
            app.cfg = dict(mod.DEFAULTS)
            app.lines = [
                mod.LyricLine(-1.0, 0.0, "sin tiempo"),
                mod.LyricLine(10.0, 0.0, "suena"),
                mod.LyricLine(-1.0, 0.0, "sin tiempo 2"),
                mod.LyricLine(20.0, 0.0, "final"),
            ]
            index, _, _ = app.scroll_state(15.0)
            check(
                "el resaltado ignora las líneas sin tiempo",
                app.lines[index].text == "suena",
                "línea resaltada=%r" % (app.lines[index].text,),
            )


def check_modo_imagen_no_se_rearma():
    """Un modo imagen desactivado por fallos no se reactiva solo.

    Cuando el modo imagen falla varias veces, el script lo desactiva y
    escribe "text" en los ajustes. La recarga siguiente trae "text", asi
    que el modo imagen no se rearma solo (si se rearmara, el fallo se
    repetiria en bucle). Solo se rearma cuando el usuario lo pide otra
    vez: entonces el valor efectivo pasa de "text" a "image".

    La prueba monta la secuencia real: tres fallos de draw_image (que
    antes dejaban self.cfg["render_mode"]="text" en memoria) y una
    recarga que todavia trae "image" porque el helper no ha escrito.
    """
    with tempfile.TemporaryDirectory(prefix="lyrics-carousel-cache-") as cache:
        with env_temporal({"XDG_CACHE_HOME": cache}):
            mod = script_module()

            def app_nuevo(render_mode: str, font_size: int) -> object:
                app = object.__new__(mod.LyricsCarousel)
                app.args = types.SimpleNamespace(
                    direction=None,
                    no_karaoke=False,
                    render_mode=None,
                    active_scale=None,
                    accent=None,
                    lang=None,
                    force=False,
                )
                app.cfg = dict(mod.DEFAULTS)
                app.cfg["render_mode"] = render_mode
                app.cfg["font_size"] = font_size
                app.image_disabled = True
                app.image_failures = 3
                app.image = None
                app.log = lambda message: None
                app._set_language = lambda value: None
                app.texts = {}
                app.status_message = ""
                app.dirty = False
                app.need_clear = False
                app.pending_overrides = {}
                return app

            original = mod.load_settings
            original_graphics = sys.modules.get("graphics")
            try:
                # 0) Secuencia real de fallos: tres renders que revientan
                #    desactivan el modo imagen y dejan "text" guardado.
                guardados = []

                class RenderizadorQueFalla:
                    gfx = types.SimpleNamespace(supported=True)

                    def render(self):
                        raise RuntimeError("fallo simulado")

                app = app_nuevo("image", 22)
                app.image_disabled = False
                app.image_failures = 0
                app.image = RenderizadorQueFalla()
                app.last_mode = "image"
                app._save_override = (
                    lambda key, value, kind="string": guardados.append(
                        (key, value, kind)
                    )
                )
                app._draw_text_frame = lambda force=False: None
                for _ in range(3):
                    app.draw_image()
                check(
                    "tres fallos desactivan el modo imagen",
                    app.image_disabled is True and app.image_failures >= 3,
                    "image_disabled=%s fallos=%s"
                    % (app.image_disabled, app.image_failures),
                )
                check(
                    "el script deja el modo texto guardado tras los fallos",
                    guardados == [("render_mode", "text", "string")],
                    str(guardados),
                )
                check(
                    "draw_image no cambia la configuracion en memoria",
                    app.cfg.get("render_mode") == "image",
                    "render_mode=%s" % app.cfg.get("render_mode"),
                )

                # use_image no es tautologico: hay un renderizador que si
                # soporta imagenes y terminal_cells devuelve tamaño. Aun
                # asi no se usa porque el modo esta desactivado.
                falso = types.ModuleType("graphics")
                falso.terminal_cells = lambda: (80, 24, 1920, 1080)
                sys.modules["graphics"] = falso
                check(
                    "un modo imagen desactivado no se usa aunque el renderizador sirva",
                    app.use_image() is False,
                    "render_mode=%s" % app.cfg.get("render_mode"),
                )
                app.image_disabled = False
                check(
                    "control: sin el fallo el renderizador se usaria",
                    app.use_image() is True,
                    "render_mode=%s" % app.cfg.get("render_mode"),
                )
                app.image_disabled = True

                # La recarga trae "image" (el helper aun no ha escrito
                # "text"): no puede rearmar el modo que acaba de fallar.
                mod.load_settings = lambda: {
                    **mod.DEFAULTS,
                    "render_mode": "image",
                    "font_size": 30,
                }
                app._reload_config()
                check(
                    "un cambio que no es el modo no rearma el modo imagen",
                    app.image_disabled is True and app.image_failures >= 3,
                    "image_disabled=%s fallos=%s"
                    % (app.image_disabled, app.image_failures),
                )

                # 2) El usuario pide el modo imagen otra vez (el valor
                #    efectivo pasa de "text" a "image"): se rearma.
                app = app_nuevo("text", 22)
                mod.load_settings = lambda: {
                    **mod.DEFAULTS,
                    "render_mode": "image",
                    "font_size": 30,
                }
                app._reload_config()
                check(
                    "el usuario puede volver a pedir el modo imagen",
                    app.image_disabled is False
                    and app.cfg.get("render_mode") == "image",
                    "image_disabled=%s render_mode=%s"
                    % (app.image_disabled, app.cfg.get("render_mode")),
                )

                # 3) El usuario pide el modo texto: el fallo anterior se
                #    limpia, asi que pedir imagen despues vuelve a
                #    funcionar aunque el valor efectivo no cambie.
                app = app_nuevo("image", 22)
                mod.load_settings = lambda: {
                    **mod.DEFAULTS,
                    "render_mode": "text",
                    "font_size": 30,
                }
                app._reload_config()
                check(
                    "pedir el modo texto limpia el fallo anterior",
                    app.image_disabled is False
                    and app.image_failures == 0,
                    "image_disabled=%s image_failures=%s"
                    % (app.image_disabled, app.image_failures),
                )
            finally:
                mod.load_settings = original
                if original_graphics is None:
                    sys.modules.pop("graphics", None)
                else:
                    sys.modules["graphics"] = original_graphics


def _app_de_config(mod):
    """Instancia minima para probar _reload_config sin abrir la ventana."""
    app = object.__new__(mod.LyricsCarousel)
    app.args = types.SimpleNamespace(
        direction=None,
        no_karaoke=False,
        render_mode=None,
        active_scale=None,
        accent=None,
        lang=None,
        force=False,
    )
    app.cfg = dict(mod.DEFAULTS)
    app.direction = 1
    app.karaoke = True
    app.spacing = 2
    app.image = None
    app.image_disabled = False
    app.image_failures = 0
    app.status_message = ""
    app.dirty = False
    app.need_clear = False
    app.pending_overrides = {}
    app.log = lambda message: None
    app.tr = lambda key, args=None: key
    app._set_language = lambda value: None
    return app


def check_cache_una_sola_vez():
    """Solo el proveedor que gana escribe la cache (no todos)."""
    with tempfile.TemporaryDirectory(prefix="lyrics-carousel-cache-") as cache:
        with env_temporal({"XDG_CACHE_HOME": cache}):
            mod = script_module()
            mod.load_lyrics_settings = lambda: {
                "sources": ["lrclib", "netease"],
                "credentials": {},
                "translation": "zh-Hans",
            }
            mod.load_cache = lambda track: None
            mod.missing_recent = lambda track: False
            mod.SEARCH_TIMEOUT = 5.0
            guardados = []
            mod.save_cache = lambda *args: guardados.append(args)

            def lrclib(track, log):
                return [mod.LyricLine(1.0, 0.0, "gana")], None

            def adaptador(source, track, settings, log):
                if source == "netease":
                    time.sleep(0.4)
                    return [mod.LyricLine(2.0, 0.0, "pierde")], None
                return [], None

            mod.fetch_lrclib = lrclib
            mod.run_adapter = adaptador
            mod.fetch_lyrics(mod.Track("cancion", "artista", duration=100.0), True, lambda m: None)
            # El hilo perdedor sigue vivo un momento: la cache solo puede
            # haberse escrito una vez, con el ganador.
            time.sleep(0.6)
            check(
                "solo el proveedor ganador escribe la caché",
                len(guardados) == 1,
                "escrituras=%d" % len(guardados),
            )


def check_aviso_se_limpia():
    """El aviso de modo imagen desactivado se borra al volver a texto."""
    with tempfile.TemporaryDirectory(prefix="lyrics-carousel-cache-") as cache:
        with env_temporal({"XDG_CACHE_HOME": cache}):
            mod = script_module()
            app = _app_de_config(mod)
            app.cfg["render_mode"] = "image"
            app.status_message = "image_disabled"
            original = mod.load_settings
            mod.load_settings = lambda: {**mod.DEFAULTS, "render_mode": "text"}
            try:
                app._reload_config()
            finally:
                mod.load_settings = original
            check(
                "el aviso de modo imagen se limpia al pasar a texto",
                app.status_message == "",
                repr(app.status_message),
            )


def check_lyrics_settings_state_dir():
    """La configuracion de Lyrics se lee del estado de Noctalia real."""
    with tempfile.TemporaryDirectory(prefix="lyrics-carousel-estado-") as temporal:
        with estado_temporal(temporal) as estado:
            with open(os.path.join(estado, "settings.toml"), "w", encoding="utf-8") as handle:
                handle.write(
                    '[plugin_settings."h465855hgg/lyrics"]\n'
                    'lyrics_sources = ["lrclib"]\n'
                )
            mod = script_module()
            ajustes = mod.load_lyrics_settings()
        check(
            "las fuentes de letra se leen del estado de Noctalia",
            ajustes.get("sources") == ["lrclib"],
            str(ajustes.get("sources")),
        )


def check_karaoke_usa_tiempos_reales():
    """El karaoke usa el siguiente tiempo real, no el de la siguiente linea.

    Las lineas sin marca de tiempo valen -1: si el relleno del karaoke
    toma "la siguiente de la lista", la linea activa se queda sin final
    (o se acorta de golpe) y el resaltado se descuadra.
    """
    with tempfile.TemporaryDirectory(prefix="lyrics-carousel-cache-") as cache:
        with env_temporal({"XDG_CACHE_HOME": cache}):
            mod = script_module()
            app = object.__new__(mod.LyricsCarousel)
            app.lines = [
                mod.LyricLine(10.0, 0, "primera"),
                mod.LyricLine(-1, 0, "sin tiempo"),
                mod.LyricLine(20.0, 0, "tercera"),
            ]
            siguiente = getattr(app, "next_timed_start", None)
            ok = siguiente is not None and siguiente(0) == 20.0
            check("el karaoke usa el siguiente tiempo real", ok, str(siguiente))
            if siguiente is not None:
                check(
                    "la ultima linea no tiene tiempo siguiente",
                    siguiente(2) is None,
                    str(siguiente(2)),
                )


def check_estimate_times_no_adelanta_las_sin_tiempo():
    """Las líneas sin tiempo no se colocan delante de las reales.

    Una letra con LRC a medias (unas líneas con tiempo y otras sin él) no
    puede repartir los tiempos al azar: si la línea sin tiempo está al
    final de la lista, no puede empezar a sonar en el segundo 6 y dejarse
    la parte con tiempos reales sin resaltar.
    """
    with tempfile.TemporaryDirectory(prefix="lyrics-carousel-cache-") as cache:
        with env_temporal({"XDG_CACHE_HOME": cache}):
            mod = script_module()

            # Caso del revisor: la línea sin tiempo va al final.
            lines = [
                mod.LyricLine(30.0, 0, "con tiempo"),
                mod.LyricLine(60.0, 0, "con tiempo"),
                mod.LyricLine(-1, 0, "sin tiempo"),
            ]
            mod.estimate_times(lines, 200.0)
            check(
                "la línea sin tiempo no adelanta a las reales",
                lines[2].start > lines[1].start,
                str([line.start for line in lines]),
            )
            check(
                "los tiempos reales no se mueven",
                abs(lines[0].start - 30.0) < 0.01 and abs(lines[1].start - 60.0) < 0.01,
                str([line.start for line in lines]),
            )

            # Una línea sin tiempo en medio queda entre sus vecinas.
            lines = [
                mod.LyricLine(10.0, 0, "primera"),
                mod.LyricLine(-1, 0, "sin tiempo"),
                mod.LyricLine(20.0, 0, "tercera"),
            ]
            mod.estimate_times(lines, 200.0)
            check(
                "la línea sin tiempo queda entre las reales",
                lines[0].start < lines[1].start < lines[2].start,
                str([line.start for line in lines]),
            )

            # Caso límite: varias líneas sin tiempo antes de una real muy
            # temprana. No pueden acabar todas en el segundo 0 (ni
            # desordenarse): tienen que repartirse sin salirse del origen.
            lines = [
                mod.LyricLine(-1, 0, "a"),
                mod.LyricLine(-1, 0, "b"),
                mod.LyricLine(-1, 0, "c"),
                mod.LyricLine(2.0, 0, "real"),
            ]
            mod.estimate_times(lines, 200.0)
            inicios = [line.start for line in lines]
            check(
                "las líneas sin tiempo se reparten sin solaparse",
                inicios[0] < inicios[1] < inicios[2] < inicios[3],
                str(inicios),
            )
            check(
                "las líneas sin tiempo quedan antes de la real",
                inicios[0] >= 0.0 and inicios[2] < 2.0,
                str(inicios),
            )


def check_estimate_times_dentro_de_la_cancion():
    """Las líneas sin tiempo se quedan dentro de la canción.

    El hueco entre líneas no se deriva de la duración: con una canción de
    200 s, una línea sin tiempo al final acababa en el segundo 226 (fuera
    de la canción, así que nunca se resaltaba). Y si la lista de líneas
    viene desordenada, la estimación tiene que caer después de la línea
    anterior (no en un hueco calculado con una duración que no le
    correspondía).
    """
    with tempfile.TemporaryDirectory(prefix="lyrics-carousel-cache-") as cache:
        with env_temporal({"XDG_CACHE_HOME": cache}):
            mod = script_module()

            # Una línea sin tiempo al final: se queda a cuatro segundos de
            # la última real, dentro de la canción.
            lines = [
                mod.LyricLine(30.0, 0, "con tiempo"),
                mod.LyricLine(-1, 0, "sin tiempo"),
            ]
            mod.estimate_times(lines, 200.0)
            check(
                "la línea sin tiempo del final no se sale de la canción",
                30.0 < lines[1].start < 200.0,
                str([line.start for line in lines]),
            )
            check(
                "la línea sin tiempo del final va justo detrás de la real",
                lines[1].start <= 30.0 + 4.0,
                str([line.start for line in lines]),
            )

            # Lista desordenada: la estimación cae después de la línea
            # anterior (la siguiente real viene antes en el tiempo, así que
            # el hueco intermedio no sirve).
            lines = [
                mod.LyricLine(30.0, 0, "con tiempo"),
                mod.LyricLine(-1, 0, "sin tiempo"),
                mod.LyricLine(10.0, 0, "con tiempo"),
            ]
            mod.estimate_times(lines, 200.0)
            check(
                "con la lista desordenada la estimación va detrás de la anterior",
                30.0 < lines[1].start < 200.0,
                str([line.start for line in lines]),
            )

            # Varias líneas sin tiempo al final: todas dentro de la
            # canción y sin solaparse.
            lines = [
                mod.LyricLine(180.0, 0, "con tiempo"),
                mod.LyricLine(-1, 0, "a"),
                mod.LyricLine(-1, 0, "b"),
                mod.LyricLine(-1, 0, "c"),
                mod.LyricLine(-1, 0, "d"),
                mod.LyricLine(-1, 0, "e"),
            ]
            mod.estimate_times(lines, 200.0)
            inicios = [line.start for line in lines]
            check(
                "las líneas sin tiempo del final no se salen de la canción",
                all(inicio < 200.0 for inicio in inicios[1:]),
                str(inicios),
            )
            check(
                "las líneas sin tiempo del final se reparten en orden",
                inicios[1] < inicios[2] < inicios[3] < inicios[4] < inicios[5],
                str(inicios),
            )

            # La última línea real puede caer justo al final (o más allá):
            # las estimadas no pueden acabar en el segundo 104 de una
            # canción de 100 s.
            lines = [
                mod.LyricLine(100.0, 0, "con tiempo"),
                mod.LyricLine(-1, 0, "sin tiempo"),
                mod.LyricLine(-1, 0, "sin tiempo 2"),
            ]
            mod.estimate_times(lines, 100.0)
            inicios = [line.start for line in lines]
            check(
                "las estimadas tras una real al final no se salen de la canción",
                all(0.0 <= inicio <= 100.0 for inicio in inicios[1:]),
                str(inicios),
            )

            # Entre dos reales, la siguiente puede estar más allá del final
            # de la canción: el hueco se recorta a la duración.
            lines = [
                mod.LyricLine(10.0, 0, "con tiempo"),
                mod.LyricLine(-1, 0, "sin tiempo"),
                mod.LyricLine(200.0, 0, "con tiempo"),
            ]
            mod.estimate_times(lines, 100.0)
            check(
                "una estimada entre dos reales no se sale de la canción",
                0.0 <= lines[1].start <= 100.0,
                str([line.start for line in lines]),
            )

            # La primera real en el segundo 0 no deja hueco delante: las
            # estimadas se quedan en el origen, no saltan detrás de ella.
            lines = [
                mod.LyricLine(-1, 0, "sin tiempo"),
                mod.LyricLine(-1, 0, "sin tiempo 2"),
                mod.LyricLine(0.0, 0, "con tiempo"),
            ]
            mod.estimate_times(lines, 100.0)
            inicios = [line.start for line in lines]
            check(
                "sin hueco antes de la primera real las estimadas no se adelantan",
                inicios[0] <= inicios[2] and inicios[1] <= inicios[2] and inicios[0] <= inicios[1],
                str(inicios),
            )

            # Sin ninguna ancla también manda la duración: una canción
            # corta no puede dejar líneas en el segundo 13.
            lines = [mod.LyricLine(-1, 0, "línea %d" % indice) for indice in range(10)]
            mod.estimate_times(lines, 10.0)
            inicios = [line.start for line in lines]
            check(
                "sin anclas las estimadas caben en una canción corta",
                all(0.0 <= inicio <= 10.0 for inicio in inicios),
                str(inicios),
            )


def check_geometria_se_recorta_a_la_pantalla():
    """La ventana nunca puede ser más grande que la pantalla.

    El panel recorta el ancho y el alto al monitor; el script hacía su
    propia cuenta y no lo hacía: el mismo ajuste daba geometrías
    distintas según quién la aplicase, y Hyprland aceptaba una ventana
    mayor que el monitor.
    """
    with tempfile.TemporaryDirectory(prefix="lyrics-carousel-cache-") as cache:
        with env_temporal({"XDG_CACHE_HOME": cache}):
            mod = script_module()
            llamadas = []
            original_monitor = mod.focused_monitor
            original_run = mod.subprocess.run
            try:
                mod.focused_monitor = lambda: {"width": 800, "height": 600}
                mod.subprocess.run = lambda args, **kwargs: (
                    llamadas.append(args[-1])
                    or types.SimpleNamespace(returncode=0, stdout="", stderr="")
                )
                cfg = dict(mod.DEFAULTS)
                cfg["width"] = 2000
                cfg["height"] = 1500
                cfg["anchor"] = "center"
                mod.apply_geometry(cfg)
            finally:
                mod.focused_monitor = original_monitor
                mod.subprocess.run = original_run
            resize = [c for c in llamadas if "resize" in c]
            check(
                "la ventana se recorta al ancho de la pantalla",
                bool(resize) and "x = 800" in resize[0],
                str(llamadas),
            )
            check(
                "la ventana se recorta al alto de la pantalla",
                bool(resize) and "y = 600" in resize[0],
                str(llamadas),
            )


def check_lrc_horas():
    """Un LRC con horas ([01:02:03]) no se descarta."""
    with tempfile.TemporaryDirectory(prefix="lyrics-carousel-cache-") as cache:
        with env_temporal({"XDG_CACHE_HOME": cache}):
            mod = script_module()
            lines = mod.parse_lrc("[01:02:03]hola")
            check(
                "un LRC con horas se interpreta",
                len(lines) == 1 and abs(lines[0].start - 3723.0) < 0.01,
                str([line.start for line in lines]),
            )


def check_lrc_minutos():
    """Un LRC con mas de 99 minutos ([100:00]) no se descarta."""
    with tempfile.TemporaryDirectory(prefix="lyrics-carousel-cache-") as cache:
        with env_temporal({"XDG_CACHE_HOME": cache}):
            mod = script_module()
            lines = mod.parse_lrc("[100:00]hola")
            check(
                "un LRC con tres digitos de minutos se interpreta",
                len(lines) == 1 and abs(lines[0].start - 6000.0) < 0.01,
                str([line.start for line in lines]),
            )


def check_lrc_decimales():
    """Un LRC con cuatro o seis decimales no se descarta."""
    with tempfile.TemporaryDirectory(prefix="lyrics-carousel-cache-") as cache:
        with env_temporal({"XDG_CACHE_HOME": cache}):
            mod = script_module()
            lines = mod.parse_lrc("[00:12.1234]hola")
            check(
                "un LRC con cuatro decimales se interpreta",
                len(lines) == 1 and abs(lines[0].start - 12.1234) < 0.001,
                str([line.start for line in lines]),
            )
            # Seis decimales: el tiempo se guarda con milisegundos (lo que
            # necesita el karaoke), pero la linea no se descarta.
            lines = mod.parse_lrc("[00:12.123456]hola")
            check(
                "un LRC con seis decimales se interpreta",
                len(lines) == 1 and abs(lines[0].start - 12.123) < 0.001,
                str([line.start for line in lines]),
            )


def check_texto_entre_angulos():
    """Las etiquetas mejoradas no se comen el texto normal entre < >."""
    with tempfile.TemporaryDirectory(prefix="lyrics-carousel-cache-") as cache:
        with env_temporal({"XDG_CACHE_HOME": cache}):
            mod = script_module()
            lines = mod.parse_lrc("[00:01.00]I <3 you > me")
            texto = lines[0].text if lines else ""
            check(
                "el texto con < y > se conserva",
                "<3" in texto,
                repr(texto),
            )


def check_cache_no_objeto():
    """Un cache con un JSON que no es un objeto no lanza."""
    with tempfile.TemporaryDirectory(prefix="lyrics-carousel-cache-") as cache:
        with env_temporal({"XDG_CACHE_HOME": cache}):
            mod = script_module()
            mod.CACHE_DIR = cache
            track = mod.Track("cancion", "artista", duration=100.0)
            path = os.path.join(cache, mod.cache_key(track) + ".json")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("[]")
            try:
                resultado = mod.load_cache(track)
            except Exception as error:  # noqa: BLE001
                resultado = error
            check(
                "un cache que no es un objeto no lanza",
                resultado is None,
                repr(resultado)[:120],
            )


def check_espacio_no_rompe():
    """Si playerctl falla, la tecla de pausa no mata la ventana."""
    with tempfile.TemporaryDirectory(prefix="lyrics-carousel-cache-") as cache:
        with env_temporal({"XDG_CACHE_HOME": cache}):
            mod = script_module()
            app = object.__new__(mod.LyricsCarousel)
            app.track = mod.Track("cancion", "artista", player="mpv")
            app._player = None
            original = mod.subprocess.run

            def falla(*args, **kwargs):
                raise OSError("no hay playerctl")

            mod.subprocess.run = falla
            try:
                resultado = app.handle_key(" ")
            except Exception as error:  # noqa: BLE001
                resultado = error
            finally:
                mod.subprocess.run = original
            check(
                "un playerctl que falla no mata la ventana",
                resultado is True,
                repr(resultado)[:120],
            )


def check_atajo_no_se_pierde():
    """Pulsar 'd' no se revierte si la config aun tiene el valor viejo."""
    with tempfile.TemporaryDirectory(prefix="lyrics-carousel-cache-") as cache:
        with env_temporal({"XDG_CACHE_HOME": cache}):
            mod = script_module()
            app = _app_de_config(mod)
            app._save_override = lambda key, value, kind="string": app.pending_overrides.__setitem__(
                key, value
            )
            app.handle_key("d")
            original = mod.load_settings
            mod.load_settings = lambda: dict(mod.DEFAULTS)
            try:
                app._reload_config()
            finally:
                mod.load_settings = original
            check(
                "el atajo 'd' no se pierde en la recarga",
                app.cfg.get("direction") == "up"
                and app.direction == -1,
                "direction=%s cfg=%s" % (app.direction, app.cfg.get("direction")),
            )


def check_panel_cubre_manifiesto():
    """Cada ajuste del manifiesto se puede cambiar desde el panel.

    La pagina de ajustes de Noctalia y el panel tienen que ofrecer lo mismo:
    un ajuste que solo exista en la pagina de ajustes hace que el usuario
    crea que el panel esta completo cuando no lo esta.
    """
    try:
        import tomllib

        with open(os.path.join(PLUGIN_DIR, "plugin.toml"), "rb") as handle:
            manifest = tomllib.load(handle)
    except Exception as error:  # noqa: BLE001
        check("el manifiesto se puede leer para el panel", False, repr(error)[:120])
        return
    try:
        with open(os.path.join(PLUGIN_DIR, "panel.luau"), encoding="utf-8") as handle:
            panel = handle.read()
    except OSError as error:
        check("el panel se puede leer", False, repr(error)[:120])
        return
    for setting in manifest.get("setting", []):
        key = setting.get("key", "")
        # El panel puede tocar el ajuste de tres formas: escribirlo
        # directamente (setSetting), a traves de una fila de interruptor
        # (toggleRow) o con un control cuya clave es el propio ajuste
        # (key = "...").
        expuesto = (
            f'setSetting("{key}"' in panel
            or f'toggleRow("{key}"' in panel
            or f'key = "{key}"' in panel
            or f'numberOf("{key}")' in panel
            or f'valueOf("{key}")' in panel
            or f'countChips("{key}"' in panel
            or f'sizeStepper("{key}"' in panel
            or f'sliderRow("{key}"' in panel
            or f'inputRow("{key}"' in panel
        )
        check(f"el panel expone `{key}`", expuesto, key)


def check_panel_attached():
    """El panel se abre pegado al widget, no en el centro de la pantalla."""
    try:
        import tomllib

        with open(os.path.join(PLUGIN_DIR, "plugin.toml"), "rb") as handle:
            manifest = tomllib.load(handle)
    except Exception as error:  # noqa: BLE001
        check("el manifiesto se puede leer para la colocacion", False, repr(error)[:120])
        return
    panel = (manifest.get("panel") or [{}])[0]
    check(
        "el panel se abre attached",
        panel.get("placement") == "attached",
        str(panel.get("placement")),
    )
    check(
        "el panel se abre junto al widget",
        panel.get("open_near_click") is True,
        str(panel.get("open_near_click")),
    )


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
    # El script escribe su diagnóstico en la caché: sin aislar
    # XDG_CACHE_HOME el autotest deja un debug.log en la caché real.
    entorno = entorno_de_prueba(temporal)
    entorno["LYRICS_CAROUSEL_OVERRIDES"] = overrides
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


def entorno_de_prueba(base: str) -> dict:
    """Entorno aislado: ninguna variable puede apuntar al estado real.

    paths.state_dir() prioriza LYRICS_CAROUSEL_STATE y NOCTALIA_STATE_HOME
    por encima de XDG_STATE_HOME, y paths.overrides_path() prioriza
    LYRICS_CAROUSEL_OVERRIDES: aislar solo HOME (o solo XDG_STATE_HOME) no
    basta. Con cualquiera de esas variables definidas (lo habitual en un
    escritorio) el volcado escribe en los ajustes de verdad y borra la
    capa de overrides del usuario.

    Todas las pruebas que lanzan el script o el helper usan esta funcion:
    el aislamiento tiene que estar en un unico sitio, o se olvida en
    alguna.
    """
    env = dict(os.environ)
    estado = os.path.join(base, ".local", "state")
    env["HOME"] = base
    env["XDG_STATE_HOME"] = estado
    env["NOCTALIA_STATE_HOME"] = estado
    env["XDG_CACHE_HOME"] = os.path.join(base, ".cache")
    env["LYRICS_CAROUSEL_STATE"] = os.path.join(estado, "noctalia")
    env["LYRICS_CAROUSEL_OVERRIDES"] = os.path.join(
        estado,
        "noctalia",
        "plugins",
        "data",
        "faminec",
        "lyrics-carousel",
        "overrides.json",
    )
    # Los subprocesos importan paths/graphics/image_renderer: sin esto
    # dejarian bin/__pycache__/*.pyc en el plugin.
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.pop("COLUMNS", None)
    env.pop("LINES", None)
    return env


def probar_helper_volcado(fake_home: str) -> dict:
    """Ejecuta el helper con un override y su volcado al settings.toml.

    Se separa en su propia funcion para que las pruebas puedan repetirla
    con un entorno distinto (por ejemplo, con XDG_STATE_HOME apuntando al
    estado "real") y comprobar que no lo tocan.

    Devuelve un diccionario con lo ocurrido.
    """
    resultado = {
        "crea_directorio": False,
        "vuelca": False,
        "detalle": "",
        "settings": "",
        "env": {},
    }
    fake_state = os.path.join(fake_home, ".local", "state", "noctalia")
    os.makedirs(fake_state, exist_ok=True)
    fake_settings = os.path.join(fake_state, "settings.toml")
    with open(fake_settings, "w", encoding="utf-8") as handle:
        handle.write("")
    env = entorno_de_prueba(fake_home)
    resultado["env"] = env
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
        resultado["crea_directorio"] = result.returncode == 0 and os.path.isdir(fake_dir)
        resultado["detalle"] = result.stderr.strip()[:120]
        # El volcado se intenta siempre: si el helper no ha podido
        # escribir, el merge tambien fallara y se vera igual. Asi la
        # prueba reproduce el caso dangerous: con el estado real en
        # XDG_STATE_HOME, el volcado happens ahi y no en el temporal.
        merge = subprocess.run(
            [sys.executable, HELPER, "merge"],
            capture_output=True,
            text=True,
            timeout=15,
            env=env,
        )
        with open(fake_settings, encoding="utf-8") as handle:
            resultado["settings"] = handle.read()
        resultado["vuelca"] = merge.returncode == 0 and "marker = true" in resultado["settings"]
        resultado["detalle"] = merge.stderr.strip()[:120]
    except (OSError, subprocess.SubprocessError) as error:
        resultado["detalle"] = repr(error)[:120]
    return resultado


def check_estado_real_intocable():
    """El autotest no puede escribir en el estado real del usuario.

    paths.state_dir() prioriza LYRICS_CAROUSEL_STATE y NOCTALIA_STATE_HOME
    por encima de XDG_STATE_HOME, y paths.overrides_path() prioriza
    LYRICS_CAROUSEL_OVERRIDES. Con cualquiera de esas variables definidas
    (lo habitual en un escritorio) el volcado escribe en los ajustes de
    verdad y borra la capa de overrides del usuario.

    La prueba demuestra las dos mitades: sin aislamiento el volcado SI
    llega a la trampa (si no, comprobar que no llega no probaria nada), y
    con el aislamiento la trampa queda intacta.
    """
    with tempfile.TemporaryDirectory(prefix="lyrics-carousel-estado-") as temporal:
        trampa = os.path.join(temporal, "estado-real")
        datos = os.path.join(
            trampa, "noctalia", "plugins", "data", "faminec", "lyrics-carousel"
        )
        os.makedirs(datos, exist_ok=True)
        settings = os.path.join(trampa, "noctalia", "settings.toml")
        overrides = os.path.join(datos, "overrides.json")
        contenido = '[plugin_settings."faminec/lyrics-carousel"]\nfont_size = 22\n'

        def preparar_trampa():
            with open(settings, "w", encoding="utf-8") as handle:
                handle.write(contenido)
            with open(overrides, "w", encoding="utf-8") as handle:
                json.dump({"font_size": 22}, handle)

        preparar_trampa()

        # 1) El entorno del usuario: el estado de verdad esta en las
        #    variables que prioriza paths.py. Sin aislamiento, el volcado
        #    llega ahi (y borra la capa de overrides).
        hostil = dict(os.environ)
        hostil["NOCTALIA_STATE_HOME"] = trampa
        hostil["XDG_STATE_HOME"] = trampa
        hostil["LYRICS_CAROUSEL_STATE"] = os.path.join(trampa, "noctalia")
        hostil["LYRICS_CAROUSEL_OVERRIDES"] = overrides
        subprocess.run(
            [sys.executable, HELPER, "override", "font_size", "30", "int"],
            capture_output=True,
            text=True,
            timeout=15,
            env=hostil,
        )
        with open(overrides, encoding="utf-8") as handle:
            override_alcanzado = json.load(handle)
        check(
            "sin aislamiento el volcado llega a la capa de overrides",
            override_alcanzado.get("font_size") == 30,
            str(override_alcanzado),
        )
        subprocess.run(
            [sys.executable, HELPER, "merge"],
            capture_output=True,
            text=True,
            timeout=15,
            env=hostil,
        )
        with open(settings, encoding="utf-8") as handle:
            alcanzado = handle.read()
        check(
            "sin aislamiento el volcado llega al settings.toml",
            "font_size = 30" in alcanzado,
            alcanzado[:100],
        )

        # 2) Con el aislamiento, la trampa queda como estaba y el volcado
        #    va al temporal.
        preparar_trampa()
        with tempfile.TemporaryDirectory() as temporal2:
            resultado = probar_helper_volcado(temporal2)
        check("el volcado va al temporal", resultado["vuelca"], resultado["detalle"])
        with open(settings, encoding="utf-8") as handle:
            despues = handle.read()
        check(
            "el autotest no toca el settings.toml real",
            despues == contenido,
            despues[:100],
        )
        with open(overrides, encoding="utf-8") as handle:
            overrides_despues = json.load(handle)
        check(
            "el autotest no toca la capa de overrides real",
            overrides_despues.get("font_size") == 22,
            str(overrides_despues),
        )


def check_limites_desde_el_manifiesto():
    """El helper recorta con los rangos que declara el manifiesto.

    Los limites viven en plugin.toml: si el helper los codificara, un
    cambio en el manifiesto dejaria al plugin escribiendo valores que su
    propia pagina de ajustes no permite. Ademas el recorte tiene que
    aplicar a cualquier via de escritura (el IPC del widgetincluded).
    """
    import tomllib

    manifiesto = os.path.join(os.path.dirname(HERE), "plugin.toml")
    try:
        with open(manifiesto, "rb") as handle:
            datos = tomllib.load(handle)
    except (OSError, ValueError) as error:
        check("el manifiesto declara limites", False, repr(error)[:120])
        return
    limites = {}
    for campo in datos.get("setting", []):
        if campo.get("min") is not None or campo.get("max") is not None:
            limites[campo["key"]] = (campo.get("min"), campo.get("max"))
    check("el manifiesto declara limites", bool(limites), str(sorted(limites))[:120])
    if not limites:
        return

    # La copia que usa la interfaz (lib/settings.luau) tiene que ser la
    # misma que la del manifiesto: si divergen, el panel deja escribir
    # valores que su propia pagina de ajustes no permite.
    lib = os.path.join(os.path.dirname(HERE), "lib", "settings.luau")
    copia = {}
    try:
        with open(lib, encoding="utf-8") as handle:
            texto = handle.read()
    except OSError as error:
        check("los limites de la interfaz son los del manifiesto", False, repr(error)[:120])
        texto = ""
    bloque = re.search(r"local LIMITS = \{(.*?)\n\}", texto, re.S)
    if bloque:
        for linea in bloque.group(1).splitlines():
            encontrado = re.match(
                r"\s*(\w+)\s*=\s*\{\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*\}", linea
            )
            if encontrado:
                copia[encontrado.group(1)] = (
                    float(encontrado.group(2)),
                    float(encontrado.group(3)),
                )
    esperado = {
        clave: (float(bajo), float(alto))
        for clave, (bajo, alto) in limites.items()
        if bajo is not None and alto is not None
    }
    check(
        "los limites de la interfaz son los del manifiesto",
        copia == esperado,
        f"interfaz={sorted(copia.items())} manifiesto={sorted(esperado.items())}",
    )

    # Sin tomllib (Python < 3.11) el manifiesto se lee con una expresion
    # regular: si no, el recorte desapareceria en silencio y el helper
    # escribiria valores que la pagina de ajustes no permite.
    import importlib.util

    spec = importlib.util.spec_from_file_location("set_setting_sin_tomllib", HELPER)
    helper = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(helper)
    except Exception as error:  # noqa: BLE001
        check("el helper se puede cargar", False, repr(error)[:120])
        helper = None
    if helper is not None and hasattr(helper, "manifest_limits_sin_tomllib"):
        sin_tomllib = helper.manifest_limits_sin_tomllib(manifiesto)
        esperado_limites = {
            clave: (bajo, alto)
            for clave, (bajo, alto) in limites.items()
        }
        check(
            "sin tomllib se leen los mismos limites del manifiesto",
            sin_tomllib == esperado_limites,
            f"regex={sorted(sin_tomllib.items())} manifiesto={sorted(esperado_limites.items())}",
        )

        # El fallback no puede depender de que el manifiesto use solo el
        # formato mas simple: cualquier bloque que no sea [[setting]] debe
        # cortar el ajuste anterior, y los valores pueden ir entre comillas
        # simples, con signo + o en notacion cientifica.
        with tempfile.NamedTemporaryFile(
            "w", suffix=".toml", delete=False, encoding="utf-8"
        ) as handle:
            handle.write(
                "[[setting]]\n"
                'key = "font_size"\n'
                "min = +6\n"
                "max = 1e2\n"
                "\n"
                "[[panel]]\n"
                "min = 1\n"
                "max = 2\n"
                "\n"
                "[[setting]]\n"
                "key = 'active_scale'\n"
                "min = 1.0\n"
                "max = 2.5\n"
            )
            manifiesto_raro = handle.name
        try:
            limites_raros = helper.manifest_limits_sin_tomllib(manifiesto_raro)
        finally:
            os.unlink(manifiesto_raro)
        check(
            "el fallback corta en cualquier bloque y acepta otros formatos",
            limites_raros == {"font_size": (6, 100), "active_scale": (1, 2.5)},
            str(limites_raros),
        )

        # Y el recorte tiene que funcionar con esos limites.
        original_tomllib = helper.tomllib
        try:
            helper.tomllib = None
            helper._MANIFEST_LIMITS = None
            check(
                "sin tomllib el helper sigue recortando",
                helper.clamp_value("font_size", 9999) == limites.get("font_size", (0, 0))[1],
                str(helper.clamp_value("font_size", 9999)),
            )
        finally:
            helper.tomllib = original_tomllib
            helper._MANIFEST_LIMITS = None
    else:
        check("el helper tiene fallback para leer el manifiesto", False)

    clave = "font_size"
    if clave not in limites:
        clave = sorted(limites)[0]
    bajo, alto = limites[clave]

    def guardar(valor: str) -> object:
        with tempfile.TemporaryDirectory() as temporal:
            env = entorno_de_prueba(temporal)
            subprocess.run(
                [sys.executable, HELPER, "override", clave, valor, "int"],
                capture_output=True,
                text=True,
                timeout=15,
                env=env,
            )
            ruta = os.path.join(
                temporal,
                ".local/state/noctalia/plugins/data/faminec/lyrics-carousel",
                "overrides.json",
            )
            try:
                with open(ruta, encoding="utf-8") as handle:
                    return json.load(handle).get(clave)
            except (OSError, ValueError):
                return None

    if alto is not None:
        check("el helper recorta por arriba", guardar(str(alto + 1000)) == alto, str(alto))
    if bajo is not None:
        check("el helper recorta por abajo", guardar(str(bajo - 1000)) == bajo, str(bajo))

    # El script tambien recorta, y con los mismos limites: si el script
    # aceptara mas que el manifiesto, la pagina de ajustes y la ventana no
    # contarian la misma historia.
    def cargar(valores: dict) -> dict:
        with tempfile.TemporaryDirectory(prefix="lyrics-carousel-limites-") as temporal:
            with env_temporal(
                {
                    "XDG_CACHE_HOME": os.path.join(temporal, "cache"),
                }
            ), estado_temporal(temporal) as destino:
                with open(os.path.join(destino, "settings.toml"), "w", encoding="utf-8") as handle:
                    handle.write('[plugin_settings."faminec/lyrics-carousel"]\n')
                    for clave, valor in valores.items():
                        handle.write(f"{clave} = {valor}\n")
                mod = script_module()
                return mod.load_settings()

    for etiqueta, elegir in (("arriba", lambda bajo, alto: alto), ("abajo", lambda bajo, alto: bajo)):
        valores = {}
        for clave, (bajo, alto) in limites.items():
            valores[clave] = elegir(bajo, alto) + (1000 if etiqueta == "arriba" else -1000)
        cfg = cargar(valores)
        for clave, (bajo, alto) in limites.items():
            esperado = alto if etiqueta == "arriba" else bajo
            if esperado is None:
                continue
            obtenido = cfg.get(clave)
            check(
                f"el script recorta {clave} por {etiqueta}",
                obtenido is not None and abs(float(obtenido) - float(esperado)) < 0.001,
                str(obtenido),
            )


def check_formatos_del_helper():
    """El helper valida el formato, no solo los rangos.

    El panel y el IPC del widget aplican los patrones de lib/settings.luau
    (glifo, color, familia). El helper es otra via de escritura: si no
    validara, cualquier llamada podria dejar un icono inexistente o un
    color invalido en los ajustes. Un valor rechazado no se guarda ni en
    los overrides ni en el settings.toml.
    """
    casos = (
        ("glyph", "headphones", "string", True),
        ("glyph", "music_note", "string", False),
        ("glyph", "Music!", "string", False),
        ("custom_color", "#12ab34", "string", True),
        ("custom_color", "#fff", "string", False),
        ("custom_color", "rojo", "string", False),
        ("font_family", "Iosevka", "string", True),
        ("font_family", "", "string", False),
    )
    for clave, valor, tipo, valido in casos:
        with tempfile.TemporaryDirectory(prefix="lyrics-carousel-formatos-") as temporal:
            env = entorno_de_prueba(temporal)
            estado = os.path.join(temporal, ".local", "state", "noctalia")
            os.makedirs(estado, exist_ok=True)
            ajustes_path = os.path.join(estado, "settings.toml")
            with open(ajustes_path, "w", encoding="utf-8") as handle:
                handle.write("")
            proceso = subprocess.run(
                [sys.executable, HELPER, "persist", clave, valor, tipo],
                capture_output=True,
                text=True,
                timeout=15,
                env=env,
            )
            overrides_path = os.path.join(
                estado,
                "plugins",
                "data",
                "faminec",
                "lyrics-carousel",
                "overrides.json",
            )
            try:
                with open(overrides_path, encoding="utf-8") as handle:
                    overrides = json.load(handle)
            except (OSError, ValueError):
                overrides = {}
            ajustes = leer_ajustes(ajustes_path)
            if valido:
                check(
                    f"el helper guarda {clave}={valor!r}",
                    proceso.returncode == 0
                    and ajustes.get(clave) == valor,
                    f"código={proceso.returncode} ajustes={ajustes.get(clave)!r}",
                )
            else:
                check(
                    f"el helper rechaza {clave}={valor!r}",
                    proceso.returncode != 0
                    and clave not in overrides
                    and clave not in ajustes,
                    f"código={proceso.returncode} overrides={overrides!r} ajustes={ajustes.get(clave)!r}",
                )


def main(argv):
    verbose = "--verbose" in argv

    # Caja de arena para todo el autotest.
    #
    # Las variables que puede tener el usuario para apuntar al estado de
    # Noctalia (NOCTALIA_STATE_HOME, XDG_STATE_HOME, LYRICS_CAROUSEL_STATE
    # y LYRICS_CAROUSEL_OVERRIDES) se sustituyen por rutas temporales
    # antes de hacer nada. Asi ninguna prueba, ni las que lanzan el script
    # como subproceso, puede escribir en los ajustes de verdad: con
    # LYRICS_CAROUSEL_STATE definida (que es lo que hace paths.py
    # funcionar) el volcado del helper llegaba al estado real.
    caja = tempfile.mkdtemp(prefix="lyrics-carousel-autotest-")
    estado_caja = os.path.join(caja, ".local", "state")
    os.makedirs(os.path.join(estado_caja, "noctalia"), exist_ok=True)
    os.environ["HOME"] = caja
    os.environ["XDG_STATE_HOME"] = estado_caja
    os.environ["NOCTALIA_STATE_HOME"] = estado_caja
    os.environ["XDG_CACHE_HOME"] = os.path.join(caja, ".cache")
    os.environ["LYRICS_CAROUSEL_STATE"] = os.path.join(estado_caja, "noctalia")
    os.environ["LYRICS_CAROUSEL_OVERRIDES"] = os.path.join(
        estado_caja,
        "noctalia",
        "plugins",
        "data",
        "faminec",
        "lyrics-carousel",
        "overrides.json",
    )
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    # Bytecode que ya hubiera (de una ejecucion anterior): al final solo
    # se avisa de los .pyc nuevos, que son los que deja este autotest.
    cache_plugin = os.path.join(HERE, "__pycache__")
    bytecode_antes = (
        set(os.listdir(cache_plugin)) if os.path.isdir(cache_plugin) else set()
    )

    # 1) el helper tiene que estar al lado del script (ruta real, no la del
    #    enlace simbólico por el que se puede lanzar).
    check("helper presente", os.path.isfile(HELPER), HELPER)
    check("helper ejecutable", os.access(HELPER, os.X_OK))

    # 2) el directorio de datos se puede crear y escribir. Se hace en un
    #    temporal: el autotest no puede crear ni escribir en el directorio
    #    de datos real del usuario.
    with tempfile.TemporaryDirectory(prefix="lyrics-carousel-datos-") as temporal:
        datos_prueba = os.path.join(temporal, "datos")
        try:
            os.makedirs(datos_prueba, exist_ok=True)
            created = os.path.isdir(datos_prueba)
        except OSError as error:
            created = False
            check("directorio de datos", False, str(error))
        if created:
            check("directorio de datos", True, datos_prueba)

            # 3) el directorio de datos se puede usar (escribir y leer).
            probe = os.path.join(datos_prueba, "selftest.json")
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

    # 3-bis) el directorio de datos real solo se mira, nunca se escribe:
    #     si no existe todavia, el plugin lo creara al escribir.
    if os.path.isdir(DATA_DIR):
        check("directorio de datos real escribible", os.access(DATA_DIR, os.W_OK), DATA_DIR)
    else:
        padre = os.path.dirname(DATA_DIR)
        check(
            "directorio de datos real escribible",
            os.path.isdir(padre) and os.access(padre, os.W_OK),
            padre,
        )

    # 4) el helper responde, crea el directorio si falta y vuelca los
    #    overrides al settings.toml. Todo con un HOME temporal y el estado
    #    aislado: si se usara el real, el autotest dejaria cambiados los
    #    ajustes del usuario (el volcado escribe en el settings.toml de
    #    verdad).
    with tempfile.TemporaryDirectory() as fake_home:
        resultado = probar_helper_volcado(fake_home)
        check(
            "el helper crea el directorio",
            resultado["crea_directorio"],
            resultado["detalle"],
        )
        check(
            "el helper vuelca al settings.toml",
            resultado["vuelca"],
            resultado["detalle"],
        )

    # 4b) el atajo 'd' del script alterna la direccion y la guarda.
    #     Es la prueba de que el script, el helper y el overrides
    #     funcionan juntos de verdad.
    check_atajos()

    # 4b-bis) el autotest no puede escribir en el estado real: con
    #     XDG_STATE_HOME o NOCTALIA_STATE_HOME definidos (lo habitual), el
    #     volcado del helper dejaria cambiados los ajustes del usuario.
    check_estado_real_intocable()

    # 4c) si la terminal se cierra, el script tiene que salir: si se
    #      queda, sigue dibujando en el vacio indefinidamente.
    check_salida_al_cerrar()

    # 4d) el comportamiento del script: desfase, plazo de busqueda de la
    #      letra, reintento, fila del ecualizador, rutas del estado,
    #      idioma de la ventana y limites de los ajustes.
    check_desfase_scroll()
    check_busqueda_letra()
    check_reintento_letra()
    check_ecualizador_fila()
    check_rutas_estado()
    check_idioma_ventana()
    check_limites_ajustes()
    check_limites_desde_el_manifiesto()
    check_formatos_del_helper()
    check_titulo_vacio_no_rebusca()
    check_timeout_adaptador()
    check_tiempos_reales_no_se_pisan()
    check_lineas_ordenadas()
    check_modo_imagen_no_se_rearma()
    check_cache_una_sola_vez()
    check_aviso_se_limpia()
    check_lyrics_settings_state_dir()
    check_lrc_horas()
    check_lrc_minutos()
    check_lrc_decimales()
    check_karaoke_usa_tiempos_reales()
    check_estimate_times_no_adelanta_las_sin_tiempo()
    check_estimate_times_dentro_de_la_cancion()
    check_geometria_se_recorta_a_la_pantalla()
    check_texto_entre_angulos()
    check_cache_no_objeto()
    check_espacio_no_rompe()
    check_atajo_no_se_pierde()
    check_panel_cubre_manifiesto()
    check_panel_attached()

    # 4e) el README documenta lo que el manifiesto declara: si el manifiesto
    #     cambia y el README no, la tienda rechaza el plugin.
    check_readme()

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
    nuevos = []
    if os.path.isdir(cache_plugin):
        nuevos = sorted(
            name
            for name in os.listdir(cache_plugin)
            if name.endswith(".pyc") and name not in bytecode_antes
        )
    check("sin bytecode nuevo en el plugin", not nuevos, ", ".join(nuevos))

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
    shutil.rmtree(caja, ignore_errors=True)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
