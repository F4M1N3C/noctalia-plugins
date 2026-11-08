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


def pixeles(imagen):
    """Píxeles de una imagen, sin el método que Pillow va a retirar."""
    if hasattr(imagen, "get_flattened_data"):
        return imagen.get_flattened_data()
    return list(imagen.getdata())


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


# visualizer_module() removed - visualizer feature removed

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
            app.args = types.SimpleNamespace(once=True, debug=False)
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


def bloques_osc66(linea):
    """Extrae los bloques OSC 66 de una fila: (metadatos, texto)."""
    patron = re.compile("\x1b\\]66;([^;]*);([^\x07]*)\x07")
    return patron.findall(linea)


def texto_visible(linea):
    """Quita las secuencias de control de una fila y deja el texto.

    El texto de los bloques OSC 66 va dentro de la secuencia, asi que de
    esos se recupera solo el payload.
    """
    linea = re.sub("\x1b\\]66;[^;]*;([^\x07]*)\x07", r"\1", linea)
    return re.sub("\x1b\\][^\x07]*\x07|\x1b\\[[0-9;]*m", "", linea)


def metadatos_osc66(metadatos):
    """Convierte 's=2:n=6:d=10:w=7' en un diccionario."""
    datos = {}
    for parte in metadatos.split(":"):
        if "=" in parte:
            clave, valor = parte.split("=", 1)
            datos[clave] = valor
    return datos


def factor_osc66(datos):
    """Factor de tamaño que calcula kitty con esos metadatos.

    Kitty multiplica el tamaño de la fuente por s y lo reduce despues por
    la fraccion n/d. Con s=1 y n/d=2/10 el texto sale al 20% de su tamaño.
    """
    escala = int(datos.get("s", 1))
    numerador = int(datos.get("n", 0))
    denominador = int(datos.get("d", 0))
    if numerador and denominador:
        return escala * numerador / denominador
    return float(escala)


def image_module():
    """Carga image_renderer para probar la disposición de las líneas."""
    if HERE not in sys.path:
        sys.path.insert(0, HERE)
    import image_renderer

    return image_renderer


def check_layout_imagen():
    """La disposición del modo imagen es simétrica y no solapa bloques.

    En "down" las líneas futuras entran por arriba y las pasadas salen por
    abajo; en "up" al revés. Un signo invertido mete las vecinas dentro del
    bloque activo y el espaciado deja de ser uniforme.
    """
    mod = image_module()

    class App:
        pass

    for direction in ("down", "up"):
        app = App()
        app.cfg = {
            "visible_above": 2,
            "visible_below": 2,
            "direction": direction,
            "spacing": 3,
        }
        renderer = mod.ImageRenderer(app)
        center = 400.0
        size = 20.0
        scale = 1.2
        pos = renderer._layout(5, center, size, scale)
        small_h = size * 1.32
        big_h = size * scale * 1.32
        gap = size * 0.30 * 3
        paso = big_h / 2 + gap + small_h / 2

        check(
            "el layout de imagen dibuja las cinco líneas",
            sorted(pos) == [3, 4, 5, 6, 7],
            repr(sorted(pos)),
        )
        check(
            "el layout de imagen centra la línea activa",
            pos.get(5) == center,
            repr(pos.get(5)),
        )
        check(
            "el layout de imagen deja el mismo hueco a los dos lados",
            abs(abs(pos.get(6, 0) - center) - abs(pos.get(4, 0) - center)) < 1e-6,
            "arriba=%.2f abajo=%.2f" % (pos.get(6, 0), pos.get(4, 0)),
        )
        check(
            "el layout de imagen separa las vecinas del bloque activo",
            abs(pos.get(6, 0) - center) >= paso - 1e-6
            and abs(pos.get(4, 0) - center) >= paso - 1e-6,
            "paso=%.2f real=%.2f/%.2f"
            % (paso, abs(pos.get(6, 0) - center), abs(pos.get(4, 0) - center)),
        )
        if direction == "down":
            check(
                "en down las líneas futuras van arriba",
                pos[7] < pos[6] < center < pos[4] < pos[3],
                repr({k: round(v, 1) for k, v in pos.items()}),
            )
        else:
            check(
                "en up las líneas futuras van abajo",
                pos[3] < pos[4] < center < pos[6] < pos[7],
                repr({k: round(v, 1) for k, v in pos.items()}),
            )


def check_karaoke_imagen_pixel_a_pixel():
    """El karaoke de imagen se rellena a nivel de píxel y con decimales.

    `_draw_karaoke` recibe los caracteres cantados con decimales. El borde
    del relleno se interpola dentro del glifo en curso, así que un
    instante ilumina un trozo de letra y no un salto de palabra entera:
    es lo que hacía parecer que reconocía la velocidad de la canción.
    """
    mod = image_module()
    if mod.Image is None:
        check("el karaoke de imagen se puede medir (Pillow)", False, "sin Pillow")
        return

    texto = "cantando suave la linea"
    cantado = (0, 200, 0)
    pendiente = (0, 90, 0)

    def medir(amount):
        imagen = mod.Image.new("RGBA", (1500, 90), (0, 0, 0, 0))
        pincel = mod.ImageDraw.Draw(imagen)
        renderer = mod.ImageRenderer.__new__(mod.ImageRenderer)
        renderer.fonts = {}
        renderer.font_files = {"prueba": mod.FALLBACK_FONT}
        renderer._draw_karaoke(
            pincel, texto, 45, 20, cantado, pendiente, amount, "prueba"
        )
        datos = pixeles(imagen)
        return sum(1 for px in datos if px[0] == cantado[0] and px[1] == cantado[1])

    def medir_pendiente(amount):
        imagen = mod.Image.new("RGBA", (1500, 90), (0, 0, 0, 0))
        pincel = mod.ImageDraw.Draw(imagen)
        renderer = mod.ImageRenderer.__new__(mod.ImageRenderer)
        renderer.fonts = {}
        renderer.font_files = {"prueba": mod.FALLBACK_FONT}
        renderer._draw_karaoke(
            pincel, texto, 45, 20, cantado, pendiente, amount, "prueba"
        )
        datos = pixeles(imagen)
        return sum(1 for px in datos if px[1] == pendiente[1])

    total = len(texto)
    check(
        "sin cantar nada no hay píxeles cantados",
        medir(0.0) == 0,
        repr(medir(0.0)),
    )

    medios = medir(total / 2)
    check(
        "a mitad de línea está cantada la mitad",
        medir(0.0) < medios < medir(float(total)),
        "medio=%s" % (medios,),
    )
    check(
        "al final no queda nada pendiente",
        medir_pendiente(float(total)) == 0,
        repr(medir_pendiente(float(total))),
    )

    # El relleno es más fino que un carácter: medio glifo ilumina un
    # troco pequeño, no la letra siguiente entera.
    salto_entero = medir(7.0) - medir(6.0)
    salto_medio = medir(6.5) - medir(6.0)
    check(
        "medio carácter ilumina menos que uno entero",
        0 < salto_medio < salto_entero,
        "medio=%s entero=%s" % (salto_medio, salto_entero),
    )
    check(
        "el relleno sigue creciendo dentro del mismo carácter",
        medir(6.25) >= medir(6.0) and medir(6.75) >= medir(6.5),
        "%s %s" % (medir(6.25), medir(6.75)),
    )


def check_karaoke_imagen_sigue_los_tiempos():
    """El karaoke de imagen usa los tiempos por carácter, como el de texto.

    Si el adaptador da tiempos por carácter, el relleno los respeta: con
    caracteres de 0,2 s cada uno, a los 0,5 s van dos y medio. Antes se
    repartía la duración de la línea entera, así que todas las palabras
    se iluminaban al mismo ritmo y la línea perdía el compás.
    """
    with tempfile.TemporaryDirectory(prefix="lyrics-carousel-cache-") as cache:
        with env_temporal({"XDG_CACHE_HOME": cache}):
            mod = script_module()
            imagen = image_module()
            texto = "hola mundo feliz"
            line = mod.LyricLine(0.0, 6.0, texto)
            line.chars = [round(index * 0.2, 3) for index in range(len(texto))]

            class Tema:
                background = (10, 10, 10)
                foreground = (200, 200, 200)
                past = (120, 120, 120)

            class PincelFalso:
                # ImageDraw no se usa: basta con lo que consulta el render.
                im = types.SimpleNamespace(size=(1500, 900))

                def textlength(self, text, font=None):
                    return len(text) * 12.0

            app = types.SimpleNamespace()
            app.cfg = {
                "karaoke": True,
                "marker": False,
                "ghost": False,
                "direction": "down",
                "spacing": 3,
                "visible_above": 2,
                "visible_below": 2,
            }
            app.state = "lyrics"
            app.lines = [line]
            app.track = mod.Track()
            app.theme = Tema()
            app.karaoke = True
            app.demo = False
            app.position = lambda: 0.5
            app.next_timed_start = lambda index: None
            # Los métodos reales, enganchados al objeto de prueba: así la
            # prueba comprueba el cálculo de verdad, no una copia.
            app.scroll_state = types.MethodType(mod.LyricsCarousel.scroll_state, app)
            app._timed_lines = types.MethodType(mod.LyricsCarousel._timed_lines, app)
            app.karaoke_amount = types.MethodType(
                mod.LyricsCarousel.karaoke_amount, app
            )

            renderer = imagen.ImageRenderer.__new__(imagen.ImageRenderer)
            renderer.app = app
            renderer.fonts = {}
            renderer.font_files = {"prueba": imagen.FALLBACK_FONT}
            renderer._measure_draw = PincelFalso()
            vistas = []
            renderer._draw_karaoke = lambda *args: vistas.append(args)

            renderer._draw_lyrics(
                PincelFalso(), 450.0, 20.0, 1.2, "prueba", (0, 200, 0), 0.5, 0, 900
            )

            check(
                "el render de imagen dibuja el karaoke de la línea activa",
                len(vistas) == 1,
                "llamadas=%s" % (len(vistas),),
            )
            if len(vistas) == 1:
                amount = vistas[0][6]
                check(
                    "el avance tiene decimales (relleno continuo)",
                    abs(amount - round(amount)) > 1e-6,
                    "amount=%r" % (amount,),
                )
                check(
                    "el avance respeta los tiempos por carácter",
                    abs(amount - 2.5) < 0.02,
                    "amount=%r" % (amount,),
                )


def check_transicion_real():
    """ghost activa la transición suave; apagado, el cambio es instantáneo.

    Con `ghost` la duración es fija (~0.9 s) y se recorta al 80 % del hueco
    hasta la línea siguiente. Sin `ghost` no hay animación: el carrusel
    salta de una línea a la siguiente en el instante en que empieza.
    """
    with tempfile.TemporaryDirectory(prefix="lyrics-carousel-cache-") as cache:
        with env_temporal({"XDG_CACHE_HOME": cache}):
            mod = script_module()
            app = object.__new__(mod.LyricsCarousel)
            app.cfg = dict(mod.DEFAULTS)
            app.cfg["ghost"] = True
            app.lines = [
                mod.LyricLine(0.0, 0.0, "uno"),
                mod.LyricLine(4.0, 0.0, "dos"),
                mod.LyricLine(8.0, 0.0, "tres"),
            ]

            # Empieza 0.9 s antes: a mitad de la transición, progreso 0.5.
            index, focus, progress = app.scroll_state(3.55)
            check(
                "la transición suave dura lo previsto",
                index == 0 and focus == 1 and abs(progress - 0.5) < 1e-6,
                "index=%s focus=%s progress=%.4f" % (index, focus, progress),
            )
            check(
                "la curva empieza despacio",
                0.0 < app.scroll_state(3.325)[2] < 0.20,
                "progress=%.4f" % app.scroll_state(3.325)[2],
            )
            check(
                "la curva termina despacio",
                app.scroll_state(3.95)[2] > 0.95,
                "progress=%.4f" % app.scroll_state(3.95)[2],
            )

            # Si la siguiente línea llega antes de 0.9 s, la transición se
            # recorta al 80 % del hueco para no solaparse con la siguiente.
            app.lines = [
                mod.LyricLine(0.0, 0.0, "uno"),
                mod.LyricLine(0.5, 0.0, "dos"),
            ]
            index, focus, progress = app.scroll_state(0.2)
            check(
                "la transición se recorta si la letra va rápida",
                focus == 1 and 0.0 < progress < 0.20,
                "focus=%s progress=%.4f" % (focus, progress),
            )

            # Sin transición suave no hay progreso: el cambio es seco.
            app.lines = [
                mod.LyricLine(0.0, 0.0, "uno"),
                mod.LyricLine(4.0, 0.0, "dos"),
                mod.LyricLine(8.0, 0.0, "tres"),
            ]
            app.cfg["ghost"] = False
            index, focus, progress = app.scroll_state(3.55)
            check(
                "sin ghost el cambio es instantáneo",
                index == 0 and focus == 0 and progress == 0.0,
                "index=%s focus=%s progress=%.4f" % (index, focus, progress),
            )
            check(
                "sin ghost la línea cambia justo en su tiempo",
                app.scroll_state(4.0)[0] == 1,
                "index=%s" % (app.scroll_state(4.0)[0],),
            )


def check_transicion_visual_fluida():
    """La transición ghost se ve: tamaño gradual y colores que cruzan.

    Se mide el render de verdad (píxeles), no los cálculos intermedios:
      * la línea que va a ser principal crece de 1.0 a `active_scale` de
        forma continua (varios tamaños intermedios, no un salto);
      * esa línea entra en blanco y termina en el color principal;
      * la línea que deja de ser principal sale del color principal y
        termina en el color de las líneas ya cantadas.
    """
    mod = image_module()
    if mod.Image is None:
        check("la transición visual se puede medir (Pillow)", False, "sin Pillow")
        return

    FONDO = (12, 12, 18)
    BLANCO = (240, 240, 245)
    PASADO = (110, 110, 120)
    ROJO = (220, 60, 60)
    SIZE = 20.0
    SCALE = 1.6

    class Tema:
        background = FONDO
        foreground = BLANCO
        past = PASADO

    class Linea:
        def __init__(self, text):
            self.text = text
            self.start = 0.0
            self.duration = 4.0
            self.chars = []

    class App:
        pass

    def render(progress, textos, estado=None, karaoke=False, direction="down"):
        """Dibuja el carrusel con una sola línea con texto y devuelve la imagen."""
        app = App()
        app.theme = Tema()
        app.cfg = {
            "visible_above": 2,
            "visible_below": 2,
            "direction": direction,
            "spacing": 3,
            "marker": False,
            "karaoke": karaoke,
        }
        app.lines = [Linea(texto) for texto in textos]
        app.karaoke = karaoke
        app.next_timed_start = lambda indice: None
        app.karaoke_amount = lambda *args: 999.0 if karaoke else 0.0
        # La línea 1 es la principal y la 2 la que va a tomarser el puesto.
        app.scroll_state = lambda posicion: estado or (1, 2, progress)
        renderer = mod.ImageRenderer.__new__(mod.ImageRenderer)
        renderer.app = app
        renderer.fonts = {}
        renderer.font_files = {"prueba": mod.FALLBACK_FONT}
        imagen = mod.Image.new("RGBA", (900, 800), (0, 0, 0, 0))
        pincel = mod.ImageDraw.Draw(imagen)
        renderer._measure_draw = pincel
        renderer._draw_lyrics(
            pincel, 400.0, SIZE, SCALE, "prueba", ROJO, 0.0, 60.0, 740.0
        )
        return imagen

    def alto(imagen):
        caja = imagen.getbbox()
        return 0 if caja is None else caja[3] - caja[1]

    def color_opaco(imagen):
        """El RGB del glifo más opaco (el color con el que se pintó)."""
        caja = imagen.getbbox()
        if caja is None:
            return (0, 0, 0)
        region = imagen.crop(caja)
        colores = region.getcolors(maxcolors=200000) or []
        if not colores:
            return (0, 0, 0)
        cuenta, pixel = max(colores, key=lambda par: par[1][3])
        return pixel[:3]

    def distancia(uno, otro):
        return sum((uno[i] - otro[i]) ** 2 for i in range(3)) ** 0.5

    entrante = ["", "", "ENTRANTE", "", ""]
    saliente = ["", "SALIENTE", "", ""]

    # -- tamaño: la entrante crece de 1.0 a `scale`, sin saltos.
    altos = [alto(render(p, entrante)) for p in (0.25, 0.5, 0.75, 1.0)]
    check(
        "la línea entrante crece de forma continua",
        len(set(altos)) == 4 and altos[0] < altos[1] < altos[2] < altos[3],
        repr(altos),
    )
    check(
        "la línea entrante alcanza el tamaño principal",
        altos[-1] > altos[0] * 1.25,
        "altos=%r" % (altos,),
    )

    # -- tamaño: la saliente encoge de `scale` a 1.0 (no debe romperse).
    altos_salida = [alto(render(p, saliente)) for p in (0.0, 0.25, 0.5, 0.75, 1.0)]
    check(
        "la línea saliente encoge de forma continua",
        altos_salida[0] > altos_salida[1] > altos_salida[2] > altos_salida[3]
        and altos_salida[4] <= altos_salida[3],
        repr(altos_salida),
    )

    # -- color de la entrante: blanco -> color principal.
    inicio = color_opaco(render(0.15, entrante))
    check(
        "la línea entrante empieza en blanco",
        distancia(inicio, BLANCO) < distancia(inicio, ROJO),
        "color=%r" % (inicio,),
    )
    final = color_opaco(render(1.0, entrante))
    check(
        "la línea entrante termina en el color principal",
        distancia(final, ROJO) < 12,
        "color=%r" % (final,),
    )

    # -- color de la saliente: color principal -> color de las cantadas.
    inicio_salida = color_opaco(render(0.0, saliente))
    check(
        "la línea saliente empieza en el color principal",
        distancia(inicio_salida, ROJO) < 12,
        "color=%r" % (inicio_salida,),
    )
    final_salida = color_opaco(render(1.0, saliente))
    check(
        "la línea saliente termina en el color de las ya cantadas",
        distancia(final_salida, PASADO) < 45
        and distancia(final_salida, ROJO) > 60,
        "color=%r" % (final_salida,),
    )

    # -- la entrante no parpadea: antes y al empezar la transición se ve igual.
    antes = render(0.0, entrante, estado=(1, 1, 0.0))
    check(
        "la línea entrante no parpadea al empezar la transición",
        alto(antes) > 0 and alto(render(0.0, entrante)) > 0,
        "antes=%r despues=%r" % (alto(antes), alto(render(0.0, entrante))),
    )

    # -- con karaoke (el modo por defecto) la saliente también cambia de color.
    karaoke_inicio = color_opaco(render(0.0, saliente, karaoke=True))
    karaoke_final = color_opaco(render(1.0, saliente, karaoke=True))
    check(
        "con karaoke la saliente pasa del color principal al de las cantadas",
        distancia(karaoke_inicio, ROJO) < distancia(karaoke_inicio, BLANCO)
        and distancia(karaoke_final, PASADO) < 45
        and distancia(karaoke_final, ROJO) > 60,
        "inicio=%r final=%r" % (karaoke_inicio, karaoke_final),
    )

    # -- en sentido "up" el relevo es el mismo, pero subiendo.
    for sentido in ("up",):
        altos_up = [alto(render(p, entrante, direction=sentido)) for p in (0.25, 0.5, 0.75, 1.0)]
        color_up = color_opaco(render(1.0, entrante, direction=sentido))
        color_salida_up = color_opaco(render(1.0, saliente, direction=sentido))
        check(
            "en sentido up la entrante crece y acaba en el color principal",
            altos_up[0] < altos_up[1] < altos_up[2] < altos_up[3]
            and distancia(color_up, ROJO) < 12,
            "altos=%r color=%r" % (altos_up, color_up),
        )
        check(
            "en sentido up la saliente acaba en el color de las cantadas",
            distancia(color_salida_up, PASADO) < 45
            and distancia(color_salida_up, ROJO) > 60,
            "color=%r" % (color_salida_up,),
        )


def check_ritmo_de_frames():
    """El bucle late a 60 fps de verdad: el plazo va desde el inicio del frame.

    Dormir el intervalo entero DESPUÉS del trabajo hacía que el ciclo real
    fuera `trabajo + intervalo`: 36 fps en vez de 60, y con eso el
    carrusel se veía a tirones.
    """
    mod = script_module()
    resto = mod.resto_para_siguiente_frame
    intervalo = 1.0 / 60.0

    check(
        "el plazo se cuenta desde el inicio del frame",
        abs(resto(0.0, 0.008, intervalo) - (intervalo - 0.008)) < 1e-9,
        repr(resto(0.0, 0.008, intervalo)),
    )
    check(
        "un frame a tiempo duerme lo que falta",
        abs(resto(0.0, 0.0, intervalo) - intervalo) < 1e-9,
        repr(resto(0.0, 0.0, intervalo)),
    )
    check(
        "un frame tardío no duerme",
        resto(0.0, 0.05, intervalo) == 0.0,
        repr(resto(0.0, 0.05, intervalo)),
    )
    check(
        "el resto nunca es negativo",
        resto(10.0, 20.0, intervalo) == 0.0,
        repr(resto(10.0, 20.0, intervalo)),
    )
    check(
        "los fps reales se miden entre frames",
        abs(mod.fps_real(180, 3.0) - 60.0) < 1e-9
        and mod.fps_real(0, 1.0) == 0.0
        and mod.fps_real(60, 0.0) == 0.0,
        repr((mod.fps_real(180, 3.0), mod.fps_real(0, 1.0))),
    )


def check_karaoke_sin_resplandor():
    """El karaoke es el brillo de la letra, sin sombra difuminada alrededor.

    Antes la linea cantada se dibujaba dos veces: la nitida y una copia
    difuminada (el halo). Ese halo era una sombra que ademas costaba 3,2 ms
    por cuadro (el GaussianBlur) y hacia que el carrusel bajara de 60 fps.
    """
    mod = image_module()
    if mod.Image is None:
        check("el karaoke sin resplandor se puede medir (Pillow)", False, "sin Pillow")
        return

    texto = "cantando"
    imagen = mod.Image.new("RGBA", (600, 90), (0, 0, 0, 0))
    pincel = mod.ImageDraw.Draw(imagen)
    renderer = mod.ImageRenderer.__new__(mod.ImageRenderer)
    renderer.fonts = {}
    renderer.font_files = {"prueba": mod.FALLBACK_FONT}
    renderer._draw_karaoke(
        pincel, texto, 45, 20, (0, 200, 0), (0, 90, 0), float(len(texto)), "prueba"
    )

    # La letra se dibuja centrada: la caja va en la misma x.
    fuente = renderer.font("prueba", 20)
    x = (imagen.size[0] - pincel.textlength(texto, font=fuente)) / 2
    caja = pincel.textbbox((x, 45), texto, font=fuente, anchor="lm")
    # Fuera de la caja del texto (con 2 px de tolerancia por el antialiasing
    # del propio glifo) no puede quedar ni un pixel: ahi vivia el halo.
    fuera = 0
    for indice, px in enumerate(pixeles(imagen)):
        if px[3] == 0:
            continue
        px_x = indice % imagen.size[0]
        px_y = indice // imagen.size[0]
        if (
            px_x < caja[0] - 2
            or px_x > caja[2] + 2
            or px_y < caja[1] - 2
            or px_y > caja[3] + 2
        ):
            fuera += 1
    check(
        "el karaoke no deja sombra alrededor de la letra",
        fuera == 0,
        "pixeles fuera=%d" % fuera,
    )
    check(
        "la letra cantada sigue pintada",
        sum(1 for px in pixeles(imagen) if px[1] == 200 and px[3] == 255) > 0,
    )


def check_tamano_fraccionario():
    """El tamaño de la letra es continuo: no escalona en píxeles enteros.

    Con la caché por entero, el renglón que crece daba un salto de 1 px cada
    pocos cuadros y se notaba como un escaloncito.
    """
    mod = image_module()
    if mod.Image is None:
        check("el tamaño fraccionario se puede medir (Pillow)", False, "sin Pillow")
        return

    renderer = mod.ImageRenderer.__new__(mod.ImageRenderer)
    renderer.fonts = {}
    renderer.font_files = {"prueba": mod.FALLBACK_FONT}
    imagen = mod.Image.new("RGBA", (600, 90), (0, 0, 0, 0))
    pincel = mod.ImageDraw.Draw(imagen)

    def ancho(tam):
        return pincel.textlength("Hola", font=renderer.font("prueba", tam))

    # 25,1 y 25,4 con la caché por entero caían en la misma fuente (25):
    # la letra no podia crecer de forma continua.
    a, b = ancho(25.1), ancho(25.4)
    check(
        "el tamaño de la letra es continuo, no escalonado",
        abs(a - b) > 0.5,
        "ancho=%.2f/%.2f" % (a, b),
    )
    check(
        "la caché distingue tamaños distintos",
        renderer.font("prueba", 25.1) is not renderer.font("prueba", 25.4),
    )
    check(
        "la caché reutiliza el mismo tamaño",
        renderer.font("prueba", 25.1) is renderer.font("prueba", 25.12),
    )


def check_glow_real():
    """La letra cantada es nitida: brillo de la letra, sin halo difuminado.

    Antes la linea cantada se dibujaba dos veces: la nitida y una copia
    difuminada (el halo). Ese halo era una sombra ademas de caro (dos
    GaussianBlur por cuadro, 3,2 ms) y hacia que el carrusel bajara de
    60 fps. Lo que se conserva es el relleno con su borde suavizado.
    """
    mod = image_module()
    if mod.Image is None:
        check("el resplandor se puede medir (Pillow)", False, "sin Pillow")
        return

    texto = "cantando"
    cantado = (0, 200, 0)
    pendiente = (0, 90, 0)
    imagen = mod.Image.new("RGBA", (400, 80), (0, 0, 0, 0))
    pincel = mod.ImageDraw.Draw(imagen)
    renderer = mod.ImageRenderer.__new__(mod.ImageRenderer)
    renderer.fonts = {}
    renderer.font_files = {"prueba": mod.FALLBACK_FONT}
    renderer._draw_karaoke(pincel, texto, 40, 20, cantado, pendiente, 4.0, "prueba")

    # Lo que queda del resplandor lejos de la letra. El halo difuminado
    # salia de la caja del texto; ahora no queda nada fuera de ella.
    fuente = renderer.font("prueba", 20)
    x = (imagen.size[0] - pincel.textlength(texto, font=fuente)) / 2
    caja = pincel.textbbox((x, 40), texto, font=fuente, anchor="lm")
    fuera_caja = 0
    for indice, px in enumerate(pixeles(imagen)):
        if px[3] == 0:
            continue
        px_x = indice % imagen.size[0]
        px_y = indice // imagen.size[0]
        if (
            px_x < caja[0] - 2
            or px_x > caja[2] + 2
            or px_y < caja[1] - 2
            or px_y > caja[3] + 2
        ):
            fuera_caja += 1
    check(
        "no queda halo difuminado lejos de la letra",
        fuera_caja == 0,
        "pixeles=%s" % (fuera_caja,),
    )

    # Y mas alla del borde de lo cantado no hay luz de otro color: lo que
    # queda es el borde del relleno (tonos entre cantado y pendiente), no
    # una sombra derramada al lado.
    ultimo = 0
    for indice, px in enumerate(pixeles(imagen)):
        if px[3] > 0 and px[:3] == cantado:
            ultimo = max(ultimo, indice % imagen.size[0])
    mas_alla = 0
    for indice, px in enumerate(pixeles(imagen)):
        x = indice % imagen.size[0]
        if x <= ultimo or px[3] == 0:
            continue
        rojo, verde, azul = px[:3]
        if not (
            pendiente[0] <= rojo <= cantado[0]
            and pendiente[1] <= verde <= cantado[1]
            and pendiente[2] <= azul <= cantado[2]
        ):
            mas_alla += 1
    check(
        "no hay luz derramada mas alla de lo cantado",
        mas_alla == 0,
        "pixeles=%s" % (mas_alla,),
    )

    # El borde del relleno se desvanece: hay varios tonos intermedios entre
    # lo cantado y lo que falta, no un salto de un color a otro.
    intermedios = set()
    for px in pixeles(imagen):
        if px[3] == 0:
            continue
        rojo, verde, azul = px[:3]
        if rojo == cantado[0] and verde == cantado[1] and azul == cantado[2]:
            continue
        if rojo == pendiente[0] and verde == pendiente[1] and azul == pendiente[2]:
            continue
        intermedios.add((rojo, verde, azul))
    check(
        "el borde del relleno se suaviza",
        len(intermedios) >= 3,
        "tonos=%s" % (len(intermedios),),
    )

    # Los tonos intermedios son mezclas de lo cantado y lo que falta: si
    # alguno se sale de ese rango, el resplandor esta sucio (el negro
    # transparente de fuera se cuela en el color al difuminarlo).
    fuera = [
        color
        for color in intermedios
        if not (
            pendiente[0] <= color[0] <= cantado[0]
            and pendiente[1] <= color[1] <= cantado[1]
            and pendiente[2] <= color[2] <= cantado[2]
        )
    ]
    check(
        "el relleno no ensucia los colores de la letra",
        not fuera,
        "colores=%s" % (sorted(fuera)[:5],),
    )




def check_recarga_por_senal():
    """SIGUSR1 recarga la letra en la ventana abierta tras vaciar la caché."""
    with tempfile.TemporaryDirectory(prefix="lyrics-carousel-cache-") as cache:
        with env_temporal({"XDG_CACHE_HOME": cache}):
            mod = script_module()
            app = object.__new__(mod.LyricsCarousel)
            app.cfg = dict(mod.DEFAULTS)
            app.demo = False
            app.track = mod.Track("Tema", "Artista")
            app.reload_requested = False
            llamadas = []
            app.reload_lyrics = lambda force=False: llamadas.append(force)

            app._on_reload_signal(signal.SIGUSR1, None)
            check(
                "la señal deja pedida la recarga",
                app.reload_requested is True,
                repr(app.reload_requested),
            )
            check(
                "la recarga pedida se atiende una sola vez",
                app._consume_reload() is True
                and llamadas == [True]
                and app.reload_requested is False,
                "llamadas=%s flag=%s" % (llamadas, app.reload_requested),
            )
            check(
                "sin señal no se recarga nada",
                app._consume_reload() is False and llamadas == [True],
                "llamadas=%s" % (llamadas,),
            )

            # El PID de la ventana: el panel señaliza ese proceso y no busca
            # por línea de comandos (SIGUSR1 mata por defecto).
            app.reload_requested = False
            app.log = lambda message: None
            app._announce_pid()
            ruta = mod.pid_path()
            try:
                with open(ruta, encoding="utf-8") as handle:
                    escrito = handle.read().strip()
            except OSError:
                escrito = ""
            check(
                "la ventana deja escrito su PID",
                escrito == str(os.getpid()),
                "escrito=%r" % (escrito,),
            )
            app._forget_pid()
            check(
                "al cerrarse la ventana borra su PID",
                not os.path.exists(ruta),
                ruta,
            )


def check_tamano_terminal_real():
    """update_size() respeta las celdas reales de la terminal.

    La ventana puede tener menos de 30x12 celdas (por ejemplo con una
    fuente grande). Inventar ese minimo hace que cada fila se desborde y
    la letra se parta en trozos.
    """
    with tempfile.TemporaryDirectory(prefix="lyrics-carousel-cache-") as cache:
        with env_temporal({"XDG_CACHE_HOME": cache}):
            mod = script_module()
            app = object.__new__(mod.LyricsCarousel)
            app.width = 0
            app.height = 0
            app.dirty = False
            original = mod.shutil.get_terminal_size
            mod.shutil.get_terminal_size = lambda fallback=None: os.terminal_size(
                (23, 9)
            )
            try:
                app.update_size()
            finally:
                mod.shutil.get_terminal_size = original
            check("el ancho usa las celdas reales", app.width == 23, str(app.width))
            check("el alto usa las celdas reales", app.height == 9, str(app.height))


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


def check_sin_modo_texto():
    """La configuracion y el codigo ya no tienen modo texto.

    Dejar claves muertas en DEFAULTS hace que el panel o un IPC puedan
    escribir valores que la ventana ignora: si el modo texto volviera a
    colarse, el usuario veria controles que no hacen nada.
    """
    with tempfile.TemporaryDirectory(prefix="lyrics-carousel-cache-") as cache:
        with env_temporal({"XDG_CACHE_HOME": cache}):
            mod = script_module()
            for key in ("render_mode", "equalizer", "animation_ms", "language"):
                check(
                    "el script no tiene el ajuste %s" % key,
                    key not in mod.DEFAULTS,
                    repr(sorted(mod.DEFAULTS)),
                )
            for name in (
                "equalizer_text", "_equalizer", "_equalizer_only", "_header",
                "_footer", "_hints", "_idle_block", "_line_color",
            ):
                check(
                    "el script no conserva %s" % name,
                    not hasattr(mod.LyricsCarousel, name),
                    name,
                )
            check(
                "no quedan helpers de ancho de terminal",
                not hasattr(mod, "cell_width") and not hasattr(mod, "truncate"),
                "cell_width/truncate",
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


def _app_de_config(mod):
    """Instancia minima para probar _reload_config sin abrir la ventana."""
    app = object.__new__(mod.LyricsCarousel)
    app.args = types.SimpleNamespace(
        direction=None,
        no_karaoke=False,
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


def check_tiempos_por_palabra():
    """Una letra solo cuenta como karaoke real si trae tiempos por carácter.

    Los proveedores de nivel de línea (LRCLIB casi siempre) dan un tiempo
    por línea: el karaoke reparte la duración a partes iguales y no sigue
    la voz. Los de nivel de palabra traen un tiempo por carácter, que es
    lo que hace que el relleno parezca reconocer la canción.
    """
    with tempfile.TemporaryDirectory(prefix="lyrics-carousel-cache-") as cache:
        with env_temporal({"XDG_CACHE_HOME": cache}):
            mod = script_module()
            con_tiempos = mod.LyricLine(0.0, 2.0, "hola")
            con_tiempos.chars = [0.0, 0.1, 0.2, 0.3]
            sin_tiempos = mod.LyricLine(2.0, 2.0, "mundo")
            otra = mod.LyricLine(4.0, 2.0, "otra")
            check(
                "la mitad de las líneas con tiempos ya cuenta como palabra",
                mod.lines_have_chars([con_tiempos, sin_tiempos]),
                "no se detectaron los tiempos",
            )
            check(
                "una sola línea con tiempos entre varias no basta",
                not mod.lines_have_chars([con_tiempos, sin_tiempos, otra]),
                "se coló una letra de nivel de línea",
            )
            check(
                "una letra vacía no tiene tiempos por palabra",
                not mod.lines_have_chars([]),
                "una lista vacía no puede contar",
            )


def check_fetch_prefiere_palabra():
    """La primera letra se publica; la de palabra la mejora y va a la caché.

    LRCLIB suele responder antes, pero con tiempos por línea. NetEase
    puede traer tiempos por palabra. Quedarse con el primero dejaba la
    caché sin `chars` para siempre y el karaoke repartía la línea a
    partes iguales.
    """
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
            mod.WORD_GRACE = 1.5
            guardados = []
            mod.save_cache = lambda *args: guardados.append(args)

            def linea(texto, con_chars=False):
                line = mod.LyricLine(1.0, 2.0, texto)
                if con_chars:
                    line.chars = [1.0 + index * 0.1 for index in range(len(texto))]
                return line

            def lrclib(track, log):
                return [linea("letra por linea")], None

            def adaptador(source, track, settings, log):
                time.sleep(0.35)
                return [linea("letra por palabra", True)], None

            mod.fetch_lrclib = lrclib
            mod.run_adapter = adaptador
            actualizaciones = []
            lines, source, synced = mod.fetch_lyrics(
                mod.Track("cancion", "artista", duration=100.0),
                True,
                lambda message: None,
                on_update=lambda *args: actualizaciones.append(args),
            )
            check(
                "el resultado final trae tiempos por palabra",
                mod.lines_have_chars(lines),
                "source=%s" % (source,),
            )
            check(
                "gana el proveedor con tiempos por palabra",
                source == "netease",
                "source=%s" % (source,),
            )
            check(
                "la primera letra se publica sin esperar",
                bool(actualizaciones) and actualizaciones[0][1] == "lrclib",
                str([item[1] for item in actualizaciones]),
            )
            check(
                "la mejora se publica cuando llega",
                len(actualizaciones) >= 2
                and mod.lines_have_chars(actualizaciones[-1][0]),
                str([item[1] for item in actualizaciones]),
            )
            check(
                "la caché se queda con la versión por palabra",
                bool(guardados) and mod.lines_have_chars(guardados[-1][1]),
                "escrituras=%d" % len(guardados),
            )


def check_fetch_palabra_no_espera():
    """Si la primera letra ya trae tiempos por palabra, no se espera a nadie."""
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
            mod.SEARCH_TIMEOUT = 3.0
            mod.WORD_GRACE = 3.0
            mod.save_cache = lambda *args: None

            texto = "letra por palabra"
            line = mod.LyricLine(1.0, 2.0, texto)
            line.chars = [1.0 + index * 0.1 for index in range(len(texto))]

            def lrclib(track, log):
                return [mod.LyricLine(1.0, 2.0, texto, line.chars)], None

            def adaptador(source, track, settings, log):
                time.sleep(2.0)
                return [mod.LyricLine(5.0, 2.0, "tarde")], None

            mod.fetch_lrclib = lrclib
            mod.run_adapter = adaptador
            inicio = time.monotonic()
            lines, source, synced = mod.fetch_lyrics(
                mod.Track("cancion", "artista", duration=100.0),
                True,
                lambda message: None,
            )
            transcurrido = time.monotonic() - inicio
            check(
                "con tiempos por palabra no se espera al proveedor lento",
                transcurrido < 1.0,
                "tardó %.2f s" % transcurrido,
            )
            check(
                "la letra con tiempos por palabra gana",
                source == "lrclib" and mod.lines_have_chars(lines),
                "source=%s" % (source,),
            )


def check_mejora_no_pisa_cache():
    """Una búsqueda de mejora sin tiempos por palabra no reescribe la caché."""
    with tempfile.TemporaryDirectory(prefix="lyrics-carousel-cache-") as cache:
        with env_temporal({"XDG_CACHE_HOME": cache}):
            mod = script_module()
            mod.load_lyrics_settings = lambda: {
                "sources": ["lrclib"],
                "credentials": {},
                "translation": "zh-Hans",
            }
            mod.load_cache = lambda track: None
            mod.missing_recent = lambda track: False
            mod.SEARCH_TIMEOUT = 2.0
            mod.WORD_GRACE = 0.2
            mod.save_cache = lambda *args: None
            mod.fetch_lrclib = lambda track, log: (
                [mod.LyricLine(1.0, 2.0, "letra por linea")],
                None,
            )
            mod.run_adapter = lambda source, track, settings, log: ([], None)
            guardados = []
            mod.save_cache = lambda *args: guardados.append(args)
            mod.fetch_lyrics(
                mod.Track("cancion", "artista", duration=100.0),
                True,
                lambda message: None,
                upgrade=True,
            )
            check(
                "una mejora sin tiempos no pisa la caché existente",
                not guardados,
                "escrituras=%d" % len(guardados),
            )


def check_cache_se_mejora_sola():
    """Una caché de nivel de línea se mejora en segundo plano al mostrarse."""
    with tempfile.TemporaryDirectory(prefix="lyrics-carousel-cache-") as cache:
        with env_temporal({"XDG_CACHE_HOME": cache}):
            mod = script_module()
            line = mod.LyricLine(1.0, 2.0, "letra por linea")
            original_cache = mod.load_cache
            original_recent = getattr(mod, "word_checked_recent", None)
            mod.load_cache = lambda track: ([line], "lrclib", True)
            mod.word_checked_recent = lambda track: False

            class FetcherFalso:
                def __init__(self):
                    self.arranques = []

                def start(self, track, force=False, upgrade=False):
                    self.arranques.append((force, upgrade))

                def take(self):
                    return None

            try:
                app = _app_de_config(mod)
                app.track = mod.Track("cancion", "artista", duration=100.0)
                app.lines = []
                app.source = ""
                app.synced = False
                app.state = "idle"
                app.dirty = False
                app.last_fetch = 0.0
                app.fetcher = FetcherFalso()
                app.reload_lyrics()
                check(
                    "la letra cacheada se muestra al instante",
                    app.state == "lyrics" and app.lines == [line],
                    "estado=%s líneas=%d" % (app.state, len(app.lines)),
                )
                check(
                    "la caché de línea se mejora en segundo plano",
                    app.fetcher.arranques == [(True, True)],
                    repr(app.fetcher.arranques),
                )

                # Si ya se comprobó hace poco, no se repite la búsqueda en
                # cada arranque de la canción.
                mod.word_checked_recent = lambda track: True
                app = _app_de_config(mod)
                app.track = mod.Track("cancion", "artista", duration=100.0)
                app.lines = []
                app.source = ""
                app.synced = False
                app.state = "idle"
                app.dirty = False
                app.last_fetch = 0.0
                app.fetcher = FetcherFalso()
                app.reload_lyrics()
                check(
                    "una comprobación reciente no repite la búsqueda",
                    app.fetcher.arranques == [],
                    repr(app.fetcher.arranques),
                )
            finally:
                mod.load_cache = original_cache
                if original_recent is None:
                    del mod.word_checked_recent
                else:
                    mod.word_checked_recent = original_recent


def check_resultado_no_pisa_letra_igual():
    """Un resultado de la misma calidad no vuelve a colocar el carrusel."""
    with tempfile.TemporaryDirectory(prefix="lyrics-carousel-cache-") as cache:
        with env_temporal({"XDG_CACHE_HOME": cache}):
            mod = script_module()
            original_mark = getattr(mod, "mark_word_checked", None)
            mod.mark_word_checked = lambda track: None
            try:
                app = object.__new__(mod.LyricsCarousel)
                app.track = mod.Track("cancion", "artista", duration=100.0)
                actual = mod.LyricLine(1.0, 2.0, "letra por linea")
                app.lines = [actual]
                app.source = "lrclib"
                app.synced = True
                app.state = "lyrics"
                app.dirty = False
                app._snap_scroll = lambda: None
                aplicar = getattr(app, "_apply_fetched", None)
                if aplicar is None:
                    check("aplicar un resultado no pisa la letra actual", False, "falta _apply_fetched")
                    return
                otra = mod.LyricLine(1.0, 2.0, "otra letra por linea")
                check(
                    "una letra de la misma calidad no se vuelve a aplicar",
                    aplicar([otra], "netease", True) is False
                    and app.source == "lrclib"
                    and app.lines == [actual],
                    "source=%s" % (app.source,),
                )
                palabra = mod.LyricLine(1.0, 2.0, "letra por palabra")
                palabra.chars = [1.0 + index * 0.1 for index in range(len(palabra.text))]
                check(
                    "una letra con tiempos por palabra sí reemplaza",
                    aplicar([palabra], "netease", True) is True
                    and app.source == "netease",
                    "source=%s" % (app.source,),
                )
                check(
                    "una búsqueda vacía no borra la letra actual",
                    aplicar([], "", False) is False and bool(app.lines),
                    "líneas=%d" % len(app.lines),
                )
            finally:
                if original_mark is None:
                    del mod.mark_word_checked
                else:
                    mod.mark_word_checked = original_mark


def check_lrc_mejorado_a_caracteres():
    """Un LRC con marcas <mm:ss.xx> se convierte en tiempos por carácter.

    Es el formato que trae la letra sincronizada palabra a palabra en
    algunos proveedores: sin esto se descartaban las marcas y el karaoke
    repartía la línea entera a partes iguales.
    """
    with tempfile.TemporaryDirectory(prefix="lyrics-carousel-cache-") as cache:
        with env_temporal({"XDG_CACHE_HOME": cache}):
            mod = script_module()
            lines = mod.parse_lrc(
                "[00:10.00]<00:10.00>Hola <00:10.50>mundo\n"
                "[00:12.00]siguiente"
            )
            line = lines[0] if lines else None
            texto = line.text if line else ""
            chars = line.chars if line else []
            check(
                "el LRC mejorado conserva el texto sin las marcas",
                texto == "Hola mundo",
                repr(texto),
            )
            check(
                "el LRC mejorado da un tiempo por carácter",
                len(chars) == len("Hola mundo"),
                repr(chars),
            )
            check(
                "el primer carácter entra en la marca de la línea",
                bool(chars) and abs(chars[0] - 10.0) < 0.01,
                repr(chars[:2]),
            )
            check(
                "la segunda palabra entra en su propia marca",
                len(chars) > 5 and abs(chars[5] - 10.5) < 0.01,
                repr(chars[4:7]),
            )
            check(
                "los tiempos por carácter no retroceden",
                all(
                    antes <= despues + 1e-6
                    for antes, despues in zip(chars, chars[1:])
                ),
                repr(chars),
            )


def check_lrclib_prefiere_letra_mejorada():
    """Entre dos candidatos iguales gana el que trae tiempos por palabra."""
    with tempfile.TemporaryDirectory(prefix="lyrics-carousel-cache-") as cache:
        with env_temporal({"XDG_CACHE_HOME": cache}):
            mod = script_module()
            original = mod._http_json
            candidatos = [
                {
                    "trackName": "cancion",
                    "artistName": "artista",
                    "duration": 100,
                    "syncedLyrics": "[00:01.00]hola\n[00:05.00]mundo",
                },
                {
                    "trackName": "cancion",
                    "artistName": "artista",
                    "duration": 100,
                    "syncedLyrics": "[00:01.00]<00:01.00>hola <00:01.50>mundo",
                },
            ]
            mod._http_json = lambda *args, **kwargs: candidatos
            try:
                lines, error = mod.fetch_lrclib(
                    mod.Track("cancion", "artista", duration=100.0),
                    lambda message: None,
                )
            finally:
                mod._http_json = original
            check(
                "se prefiere la letra con tiempos por palabra",
                mod.lines_have_chars(lines),
                "error=%r" % (error,),
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

            # Dos líneas reales con el MISMO tiempo no dejan hueco: la
            # estimada no puede colocarse detrás de la siguiente, porque
            # el resaltado volvería hacia atrás (la línea que va después
            # en la lista ya se habría cantado).
            lines = [
                mod.LyricLine(10.0, 0, "primera"),
                mod.LyricLine(-1, 0, "sin tiempo"),
                mod.LyricLine(10.0, 0, "segunda"),
            ]
            mod.estimate_times(lines, 200.0)
            check(
                "sin hueco entre dos reales del mismo tiempo la estimada no va detrás",
                lines[1].start <= lines[2].start,
                str([line.start for line in lines]),
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
    """La geometría de la ventana la aplica el panel, no el script.

    El panel recorta el ancho y el alto al monitor y usa la API de
    Noctalia (que sí funciona). El script intentaba hacer lo mismo con
    `hyprctl dispatch` y una cuenta propia: la cuenta usaba el monitor
    completo (no el area utilizable) y el resize se descartaba en
    silencio, así que la ventana acababa fuera de la pantalla.
    """
    mod = script_module()
    check(
        "el script no redimensiona la ventana por su cuenta",
        not hasattr(mod, "apply_geometry"),
        "apply_geometry sigue en el script",
    )


def check_tamano_de_la_ventana_por_hyprctl():
    """El tamaño de la ventana se lee de Hyprland, en píxeles.

    El ajuste width/height es el tamaño de la ventana en píxeles (lo que el
    panel usa al crearla). La celda del terminal es otra medida: antes el
    script guardaba las celdas (96x30) y la ventana se creaba de 96x30
    píxeles, es decir, diminuta.
    """
    mod = script_module()
    original = mod.subprocess.run
    try:
        mod.subprocess.run = lambda args, **kwargs: types.SimpleNamespace(
            returncode=0,
            stdout=json.dumps([
                {"class": "otra-ventana", "size": [800, 600]},
                {"class": "noctalia-lyrics-carousel", "size": [1300, 900]},
            ]),
            stderr="",
        )
        check(
            "el tamaño de la ventana se lee de Hyprland",
            mod.window_size_px() == (1300, 900),
            str(mod.window_size_px()),
        )
        mod.subprocess.run = lambda args, **kwargs: types.SimpleNamespace(
            returncode=0, stdout="[]", stderr=""
        )
        check(
            "sin ventana del carrusel no hay tamaño",
            mod.window_size_px() is None,
            str(mod.window_size_px()),
        )
    finally:
        mod.subprocess.run = original


def check_redimensionado_manual_se_guarda():
    """El tamaño que elige el usuario a mano se guarda en píxeles.

    Redimensionar la ventana con el ratón no pasa por el panel, así que el
    script lo guarda. Va a la capa de overrides (no al settings.toml):
    escribir el settings.toml hace que Noctalia recargue la configuración
    y cierre el panel que estuviera abierto.
    """
    with tempfile.TemporaryDirectory(prefix="lyrics-carousel-cache-") as cache:
        with env_temporal({"XDG_CACHE_HOME": cache}):
            mod = script_module()
            app = object.__new__(mod.LyricsCarousel)
            app.demo = False
            app.args = types.SimpleNamespace(debug=False)
            app.cfg = dict(mod.DEFAULTS)
            app._last_size_check = 0.0
            guardados = []
            app._save_override = (
                lambda key, value, kind="string", persist=True: guardados.append(
                    (key, value, kind, persist)
                )
            )
            original = mod.window_size_px
            try:
                mod.window_size_px = lambda: (1300, 900)
                app.check_manual_resize()
                check(
                    "el ancho redimensionado se guarda",
                    any(k == "width" and v == 1300 for k, v, _, _ in guardados),
                    str(guardados),
                )
                check(
                    "el alto redimensionado se guarda",
                    any(k == "height" and v == 900 for k, v, _, _ in guardados),
                    str(guardados),
                )
                check(
                    "el tamaño se guarda en la capa de overrides",
                    bool(guardados) and all(persist is False for _, _, _, persist in guardados),
                    str(guardados),
                )

                # El tamaño que ya está en los ajustes no se vuelve a guardar.
                guardados.clear()
                app.cfg["width"] = 1300
                app.cfg["height"] = 900
                app._last_size_check = 0.0
                app.check_manual_resize()
                check(
                    "un tamaño que ya está guardado no se repite",
                    not guardados,
                    str(guardados),
                )

                # Una ventana diminuta (por ejemplo a medio arrastrar) no vale.
                guardados.clear()
                mod.window_size_px = lambda: (55, 15)
                app._last_size_check = 0.0
                app.check_manual_resize()
                check(
                    "una ventana diminuta no se guarda",
                    not guardados,
                    str(guardados),
                )
            finally:
                mod.window_size_px = original


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
        # El icono de la barra se configura en esta pagina y no en el panel:
        # pertenece al widget de la barra, no a la ventana de letras. Es la
        # unica clave que se permite fuera del panel.
        if key == "glyph":
            continue
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


def check_hints_centrados():
    """La fila de atajos queda centrada en la ventana de imagen.

    Antes empezaba en el margen izquierdo y el sobrante se acumulaba a la
    derecha: parecía descuadrada. Ahora se dibuja con el mismo centrado que
    el resto de textos.
    """
    mod = image_module()
    if mod.Image is None:
        check("los hints se pueden medir (Pillow)", False, "sin Pillow")
        return

    imagen = mod.Image.new("RGBA", (1000, 200), (0, 0, 0, 0))
    pincel = mod.ImageDraw.Draw(imagen)
    app = types.SimpleNamespace(
        texts={"hints": ["pulsa [q] para salir"]},
        theme=types.SimpleNamespace(
            background=(10, 10, 10),
            faint=(120, 120, 120),
        ),
        terminal_pixels=lambda: (1000, 200),
        demo=False,
    )
    renderer = mod.ImageRenderer.__new__(mod.ImageRenderer)
    renderer.app = app
    renderer.fonts = {}
    renderer.font_files = {"prueba": mod.FALLBACK_FONT}
    renderer._measure_draw = pincel
    renderer._draw_hints(pincel, 20.0, "prueba")

    caja = imagen.getbbox()
    check("los atajos se dibujan", caja is not None, repr(caja))
    if caja is not None:
        centro = (caja[0] + caja[2]) / 2.0
        check(
            "los atajos quedan centrados",
            abs(centro - 500.0) <= 2.0,
            "centro=%.1f bbox=%s" % (centro, caja),
        )




def check_translate_lyrics_false_default():
    """translate_lyrics default false."""
    mod = script_module()
    check(
        "translate_lyrics default false",
        mod.DEFAULTS.get("translate_lyrics") == False,
        mod.DEFAULTS.get("translate_lyrics"),
    )


def check_reparto_de_ajustes():
    """El manifiesto no duplica lo que ya se cambia en el panel.

    El usuario no considera necesarias las opciones de la configuracion de
    Noctalia que ya estan en el panel, asi que el manifiesto solo declara lo
    que el panel no ofrece. Si alguien vuelve a anadir una clave que el panel
    ya controla, la pagina de ajustes y el panel vuelven a ofrecer lo mismo
    con dos limites distintos.

    La excepcion es `glyph`: es el icono del widget de la barra, que se
    configura en esta pagina y no en la ventana de letras.
    """
    try:
        import tomllib

        with open(os.path.join(PLUGIN_DIR, "plugin.toml"), "rb") as handle:
            manifest = tomllib.load(handle)
    except Exception as error:  # noqa: BLE001
        check("el manifiesto se puede leer para el reparto", False, repr(error)[:120])
        return
    declaradas = {
        setting.get("key", "")
        for setting in manifest.get("setting", [])
        if setting.get("key")
    }
    solo_en_ajustes = {"glyph"}

    # Lo que el panel controla: es la lista de claves de lib/settings.luau
    # (DEFAULTS), no un texto suelto, para que la prueba no se quede vieja.
    lib = os.path.join(PLUGIN_DIR, "lib", "settings.luau")
    del_panel = set()
    try:
        with open(lib, encoding="utf-8") as handle:
            texto = handle.read()
    except OSError as error:
        check("la lista de claves se puede leer", False, repr(error)[:120])
        return
    bloque = re.search(r"local DEFAULTS = \{(.*?)\n\}", texto, re.S)
    if bloque:
        for encontrado in re.finditer(r"^\s{2}(\w+)\s*=", bloque.group(1), re.M):
            del_panel.add(encontrado.group(1))
    check("la lista de claves del panel se puede leer", bool(del_panel))

    duplicados = sorted((declaradas - solo_en_ajustes) & del_panel)
    check(
        "el manifiesto no repite los ajustes del panel",
        not duplicados,
        "duplicados=%s" % (duplicados,),
    )
    check(
        "el manifiesto solo deja lo que no esta en el panel",
        declaradas <= solo_en_ajustes,
        "declaradas=%s" % (sorted(declaradas),),
    )
    check(
        "el icono de la barra sigue en el manifiesto",
        "glyph" in declaradas,
        str(sorted(declaradas)),
    )


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


def check_limites_del_panel_y_el_script():
    """El panel y el script recortan con los mismos rangos.

    El manifiesto solo declara el icono de la barra, asi que los rangos ya no
    viven en plugin.toml: los aplica el panel antes de escribir
    (lib/settings.luau) y el script al leerlos. Si divergieran, el panel
    dejaria guardar un valor que la ventana despues descarta, y el usuario
    veria un numero que no se aplica.
    """
    lib = os.path.join(os.path.dirname(HERE), "lib", "settings.luau")
    copia = {}
    try:
        with open(lib, encoding="utf-8") as handle:
            texto = handle.read()
    except OSError as error:
        check("el panel declara limites", False, repr(error)[:120])
        return
    bloque = re.search(r"local LIMITS = \{(.*?)\n\}", texto, re.S)
    if bloque:
        for linea in bloque.group(1).splitlines():
            encontrado = re.match(
                r"\s*(\w+)\s*=\s*\{\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*\}",
                linea,
            )
            if encontrado:
                copia[encontrado.group(1)] = (
                    float(encontrado.group(2)),
                    float(encontrado.group(3)),
                )
    check("el panel declara limites", bool(copia), str(sorted(copia))[:120])
    if not copia:
        return

    # La copia del script: los recortes de load_settings.
    try:
        with open(os.path.join(HERE, "lyrics-carousel"), encoding="utf-8") as handle:
            guion = handle.read()
    except OSError as error:
        check("el script se puede leer", False, repr(error)[:120])
        return
    recortes = {}
    for encontrado in re.finditer(
        r'cfg\["(\w+)"\]\s*=\s*max\(\s*(-?[\d.]+)\s*,\s*min\(\s*(-?[\d.]+)\s*,',
        guion,
    ):
        recortes[encontrado.group(1)] = (
            float(encontrado.group(2)),
            float(encontrado.group(3)),
        )
    check(
        "el script recorta con los rangos del panel",
        recortes == copia,
        f"script={sorted(recortes.items())} panel={sorted(copia.items())}",
    )

    # El helper ya no recorta rangos: el manifiesto no los declara. Lo que
    # conserva es el formato (patrones) y la escritura atomica. Comprobar que
    # NO recorta es tan importante como lo contrario: si alguien vuelve a
    # poner limites en el manifiesto, el helper perderia valores en silencio.
    import importlib.util

    spec = importlib.util.spec_from_file_location("set_setting_sin_tomllib", HELPER)
    helper = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(helper)
    except Exception as error:  # noqa: BLE001
        check("el helper se puede cargar", False, repr(error)[:120])
        return
    check(
        "el helper tiene fallback para leer los limites",
        hasattr(helper, "manifest_limits_sin_tomllib"),
    )
    if not hasattr(helper, "manifest_limits_sin_tomllib"):
        return

    # El fallback sin tomllib sigue leyendo lo que haya en el manifiesto: se
    # prueba con un manifiesto de mentira porque el real ya no declara rangos.
    with tempfile.NamedTemporaryFile(
        "w", suffix=".toml", delete=False, encoding="utf-8"
    ) as handle:
        handle.write(
            "[[setting]]\n"
            'key = "font_size"\n'
            "min = 6\n"
            "max = 96\n"
            "\n"
            "[[panel]]\n"
            "min = 1\n"
            "max = 2\n"
        )
        manifiesto_simple = handle.name
    try:
        if helper.tomllib is not None:
            with open(manifiesto_simple, "rb") as handle:
                datos = helper.tomllib.load(handle)
            con_tomllib = {
                campo["key"]: (campo.get("min"), campo.get("max"))
                for campo in datos.get("setting", [])
                if campo.get("min") is not None or campo.get("max") is not None
            }
            check(
                "sin tomllib se leen los mismos limites",
                helper.manifest_limits_sin_tomllib(manifiesto_simple) == con_tomllib,
                f"regex={sorted(helper.manifest_limits_sin_tomllib(manifiesto_simple).items())}"
                f" tomllib={sorted(con_tomllib.items())}",
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

        # Y el recorte del helper funciona si el manifiesto los trae de verdad.
        original = helper._MANIFEST_LIMITS
        try:
            helper._MANIFEST_LIMITS = {"font_size": (6, 96)}
            check(
                "con limites en el manifiesto el helper recorta",
                helper.clamp_value("font_size", 9999) == 96,
                str(helper.clamp_value("font_size", 9999)),
            )
        finally:
            helper._MANIFEST_LIMITS = original
    finally:
        os.unlink(manifiesto_simple)

    # Lo que de verdad protege al usuario: un valor fuera de rango que
    # llegue al settings.toml (un IPC, el fichero editado a mano) se recorta
    # al leerlo.
    def cargar(valores: dict) -> dict:
        with tempfile.TemporaryDirectory(prefix="lyrics-carousel-limites-") as temporal:
            with env_temporal(
                {
                    "XDG_CACHE_HOME": os.path.join(temporal, "cache"),
                }
            ), estado_temporal(temporal) as destino:
                with open(
                    os.path.join(destino, "settings.toml"), "w", encoding="utf-8"
                ) as handle:
                    handle.write('[plugin_settings."faminec/lyrics-carousel"]\n')
                    for clave, valor in valores.items():
                        handle.write(f"{clave} = {valor}\n")
                mod = script_module()
                return mod.load_settings()

    for etiqueta, elegir in (
        ("arriba", lambda bajo, alto: alto),
        ("abajo", lambda bajo, alto: bajo),
    ):
        valores = {}
        for clave, (bajo, alto) in copia.items():
            valores[clave] = elegir(bajo, alto) + (1000 if etiqueta == "arriba" else -1000)
        cfg = cargar(valores)
        for clave, (bajo, alto) in copia.items():
            esperado = alto if etiqueta == "arriba" else bajo
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
        ("font_family", "Iosevka\nMono", "string", False),
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


def check_helper_acepta_las_claves_nuevas():
    """El helper conoce todas las claves que el panel y el script usan.

    El helper es otra via de escritura (la del panel y la de los atajos de
    la ventana). Si le falta una clave en su lista, responde "clave
    desconocida" y el ajuste se pierde en silencio: el interruptor del
    visualizador no se guardaba por eso.
    """
    casos = (
        ("visualizer", "false", "bool", False),
        ("translate_lyrics", "true", "bool", True),
        ("visualizer_position", "left", "string", "left"),
        ("visualizer_position", "arriba", "string", None),
        ("visualizer_coverage", "40", "int", 40),
    )
    for clave, valor, tipo, esperado in casos:
        with tempfile.TemporaryDirectory(prefix="lyrics-carousel-claves-") as temporal:
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
            ajustes = leer_ajustes(ajustes_path)
            if esperado is None:
                check(
                    f"el helper rechaza {clave}={valor!r}",
                    proceso.returncode != 0 and clave not in ajustes,
                    f"código={proceso.returncode} ajustes={ajustes.get(clave)!r}",
                )
            else:
                check(
                    f"el helper guarda {clave}={valor!r}",
                    proceso.returncode == 0 and ajustes.get(clave) == esperado,
                    f"código={proceso.returncode} ajustes={ajustes.get(clave)!r}",
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
    check_layout_imagen()
    check_karaoke_imagen_pixel_a_pixel()
    check_karaoke_sin_resplandor()
    check_tamano_fraccionario()
    check_karaoke_imagen_sigue_los_tiempos()
    check_transicion_real()
    check_transicion_visual_fluida()
    check_ritmo_de_frames()
    check_glow_real()
    check_recarga_por_senal()
    check_tamano_terminal_real()
    check_rutas_estado()
    check_sin_modo_texto()
    check_limites_ajustes()
    check_limites_del_panel_y_el_script()
    check_formatos_del_helper()
    check_titulo_vacio_no_rebusca()
    check_timeout_adaptador()
    check_tiempos_reales_no_se_pisan()
    check_lineas_ordenadas()
    check_cache_una_sola_vez()
    check_tiempos_por_palabra()
    check_fetch_prefiere_palabra()
    check_fetch_palabra_no_espera()
    check_mejora_no_pisa_cache()
    check_cache_se_mejora_sola()
    check_resultado_no_pisa_letra_igual()
    check_lyrics_settings_state_dir()
    check_lrc_horas()
    check_lrc_minutos()
    check_lrc_decimales()
    check_karaoke_usa_tiempos_reales()
    check_estimate_times_no_adelanta_las_sin_tiempo()
    check_estimate_times_dentro_de_la_cancion()
    check_geometria_se_recorta_a_la_pantalla()
    check_tamano_de_la_ventana_por_hyprctl()
    check_redimensionado_manual_se_guarda()
    check_texto_entre_angulos()
    check_lrc_mejorado_a_caracteres()
    check_lrclib_prefiere_letra_mejorada()
    check_cache_no_objeto()
    check_espacio_no_rompe()
    check_atajo_no_se_pierde()
    check_panel_cubre_manifiesto()
    check_hints_centrados()
    check_translate_lyrics_false_default()
    check_reparto_de_ajustes()
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
