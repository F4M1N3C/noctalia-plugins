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
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import types
from contextlib import contextmanager

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

    Todo ocurre en un directorio temporal (HOME, XDG_STATE_HOME y
    XDG_CACHE_HOME): el script escribe en el settings.toml y en los
    overrides, y la prueba no debe tocar el estado real del usuario ni
    competir con la escritura asincrona del script.
    """
    temporal = tempfile.mkdtemp(prefix="lyrics-carousel-selftest-")
    home = os.path.join(temporal, "home")
    estado = os.path.join(temporal, "state")
    cache = os.path.join(temporal, "cache")
    overrides = os.path.join(temporal, "overrides.json")
    for path in (home, estado, cache):
        os.makedirs(path, exist_ok=True)
    ajustes = os.path.join(estado, "noctalia", "settings.toml")
    os.makedirs(os.path.dirname(ajustes), exist_ok=True)
    with open(ajustes, "w", encoding="utf-8") as handle:
        handle.write("")
    entorno = {
        **os.environ,
        "HOME": home,
        "XDG_STATE_HOME": estado,
        "XDG_CACHE_HOME": cache,
        "LYRICS_CAROUSEL_OVERRIDES": overrides,
    }
    entorno.pop("COLUMNS", None)
    entorno.pop("LINES", None)
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
        estado = os.path.join(temporal, "state")
        cache = os.path.join(temporal, "cache")
        home = os.path.join(temporal, "home")
        for path in (estado, cache, home):
            os.makedirs(path, exist_ok=True)
        ajustes = os.path.join(estado, "noctalia", "settings.toml")
        os.makedirs(os.path.dirname(ajustes), exist_ok=True)
        with open(ajustes, "w", encoding="utf-8") as handle:
            handle.write(
                '[plugin_settings."faminec/lyrics-carousel"]\n'
                "hints = true\n"
                'render_mode = "text"\n'
            )
        entorno = {
            **os.environ,
            "HOME": home,
            "XDG_STATE_HOME": estado,
            "XDG_CACHE_HOME": cache,
        }
        entorno.pop("COLUMNS", None)
        entorno.pop("LINES", None)
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
        estado = os.path.join(temporal, "state")
        ajustes = os.path.join(estado, "noctalia", "settings.toml")
        os.makedirs(os.path.dirname(ajustes), exist_ok=True)
        with open(ajustes, "w", encoding="utf-8") as handle:
            handle.write(
                '[plugin_settings."faminec/lyrics-carousel"]\n'
                "width = 100\n"
                "height = 100\n"
                "offset_ms = 99999\n"
            )
        with env_temporal(
            {
                "XDG_CACHE_HOME": os.path.join(temporal, "cache"),
                "XDG_STATE_HOME": estado,
            }
        ):
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
                len(arranques) <= 1,
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
    """Un modo imagen desactivado por fallos no se reactiva solo."""
    with tempfile.TemporaryDirectory(prefix="lyrics-carousel-cache-") as cache:
        with env_temporal({"XDG_CACHE_HOME": cache}):
            mod = script_module()
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
            app.cfg["render_mode"] = "text"
            app.image_disabled = True
            app.image_failures = 3
            app.image = None
            app.log = lambda message: None
            app._set_language = lambda value: None
            app.dirty = False
            app.need_clear = False

            original = mod.load_settings
            mod.load_settings = lambda: dict(mod.DEFAULTS)
            try:
                app._reload_config()
            finally:
                mod.load_settings = original
            check(
                "el modo imagen desactivado no se rearma",
                app.image_disabled is True
                and app.cfg.get("render_mode") == "text",
                "image_disabled=%s render_mode=%s"
                % (app.image_disabled, app.cfg.get("render_mode")),
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
    check_titulo_vacio_no_rebusca()
    check_timeout_adaptador()
    check_tiempos_reales_no_se_pisan()
    check_lineas_ordenadas()
    check_modo_imagen_no_se_rearma()
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
