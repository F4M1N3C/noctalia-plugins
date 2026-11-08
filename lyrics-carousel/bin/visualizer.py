"""Visualizador de audio del carrusel.

Lanza `cava` con una configuracion propia, lee las barras por su salida
estandar y las deja listas para que el renderizador de imagen las dibuje de
fondo, a todo el ancho de la ventana. Si `cava` no esta instalado, no arranca o
deja de responder, se generan barras suaves de reserva: el fondo nunca queda
muerto ni rompe la ventana.
"""

from __future__ import annotations

import math
import shutil
import subprocess
import threading
import time

# Barras que se piden a cava. Con 64 el fondo tiene detalle suficiente en una
# ventana de 1500 px sin que cada barra quede mas fina que un par de pixeles.
BARS = 64
FRAMERATE = 60
MAX_RANGE = 100
# Tras un fallo no se reintenta en cada cuadro: cava puede tardar en arrancar
# y no tiene sentido lanzar un proceso por frame.
RESTART_SECONDS = 5.0
# Un cuadro de cava mas viejo que esto ya no se usa: si el proceso se queda
# colgado, el fondo vuelve a las barras simuladas.
STALE_SECONDS = 1.5

CONFIG = f"""[general]
bars = {BARS}
framerate = {FRAMERATE}
sensitivity = 100

[input]
method = pipewire
source = auto

[output]
method = raw
raw_target = /dev/stdout
data_format = ascii
ascii_max_range = {MAX_RANGE}
bar_delimiter = 59
frame_delimiter = 10
"""


def parse_frame(line, count=BARS, max_range=MAX_RANGE):
    """Convierte una linea de cava en niveles de 0 a 1.

    Cava escribe un valor por barra separado por `;` y una linea por cuadro.
    La linea termina en `;`, asi que el ultimo hueco se descarta. Devuelve
    None si la linea no tiene exactamente `count` valores validos: asi una
    salida a medias (el proceso esta arrancando) no pinta barras rotas.
    """
    if not isinstance(line, str):
        return None
    pieces = [piece for piece in line.strip().split(";") if piece != ""]
    if len(pieces) != count:
        return None
    levels = []
    for piece in pieces:
        try:
            value = float(piece)
        except ValueError:
            return None
        if not math.isfinite(value) or value < 0.0:
            return None
        levels.append(min(1.0, value / float(max_range)))
    return levels


def simulated_levels(count=BARS, now=None):
    """Barras de reserva con envolvente central y varias ondas.

    Se usan cuando cava no esta disponible. La suma de ondas de periodos
    distintos evita que el fondo parezca una senal periodica y el movimiento
    es lento: es un adorno detras de la letra, no un dato del audio.
    """
    current = time.monotonic() if now is None else float(now)
    center = (count - 1) / 2.0
    span = max(1.0, center)
    levels = []
    for index in range(count):
        phase = index * 0.29
        wave = 0.52 + 0.26 * math.sin(current * 1.7 + phase)
        wave += 0.16 * math.sin(current * 0.7 - phase * 1.7)
        wave += 0.06 * math.sin(current * 2.9 + phase * 0.5)
        envelope = 0.55 + 0.45 * (1.0 - abs(index - center) / span)
        levels.append(max(0.0, min(1.0, wave * envelope)))
    return levels


class Visualizer:
    """Proceso cava y ultimo cuadro de barras disponible."""

    def __init__(self, log=None, count=BARS):
        self.count = count
        self.log = log if callable(log) else (lambda message: None)
        self.demo = False
        self._cava = shutil.which("cava")
        self._process = None
        self._thread = None
        self._lock = threading.Lock()
        self._bars = [0.0] * count
        self._stamp = 0.0
        self._last_start = 0.0

    # -- ciclo de vida ---------------------------------------------------

    def start(self):
        """Arranca cava si no esta vivo (idempotente)."""
        if self._process is not None and self._process.poll() is None:
            return True
        if self._cava is None:
            return False
        now = time.monotonic()
        if now - self._last_start < RESTART_SECONDS and self._last_start > 0.0:
            return False
        self._last_start = now
        try:
            process = subprocess.Popen(
                [self._cava, "-p", "/dev/stdin"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                bufsize=1,
            )
        except OSError as error:
            self.log(f"visualizador: no se pudo lanzar cava: {error!r}")
            return False
        try:
            process.stdin.write(CONFIG)
            process.stdin.close()
        except OSError as error:
            self.log(f"visualizador: cava no acepto la configuracion: {error!r}")
            try:
                process.terminate()
            except OSError:
                pass
            return False
        self._process = process
        self._thread = threading.Thread(
            target=self._read, args=(process,), name="lyrics-cava", daemon=True
        )
        self._thread.start()
        return True

    def _read(self, process):
        """Lee las lineas de cava hasta que el proceso termina."""
        try:
            for line in process.stdout:
                levels = parse_frame(line, self.count)
                if levels is None:
                    continue
                with self._lock:
                    self._bars = levels
                    self._stamp = time.monotonic()
        except (OSError, ValueError) as error:  # pragma: no cover - tuberia rota
            self.log(f"visualizador: lectura interrumpida: {error!r}")
        finally:
            try:
                process.stdout.close()
            except (OSError, AttributeError):
                pass
            with self._lock:
                self._process = None

    def stop(self):
        """Termina cava y deja el ultimo cuadro como estaba."""
        with self._lock:
            process = self._process
            self._process = None
        if process is None:
            return
        try:
            process.terminate()
            process.wait(timeout=1.0)
        except (OSError, subprocess.SubprocessError):
            try:
                process.kill()
            except OSError:
                pass

    # -- lectura ---------------------------------------------------------

    def snapshot(self, simulate=None):
        """Ultimo cuadro de barras (0..1) o las simuladas si no hay datos.

        `simulate` fuerza las barras de reserva: el modo demo no tiene audio
        real y asi la ventana de muestra sigue teniendo vida.
        """
        if simulate is None:
            simulate = self.demo
        if simulate:
            return simulated_levels(self.count)
        if self._process is None:
            self.start()
        with self._lock:
            bars = list(self._bars)
            stamp = self._stamp
        if stamp > 0.0 and time.monotonic() - stamp < STALE_SECONDS:
            return bars
        return simulated_levels(self.count)

    def signature(self):
        """Huella barata para saber si el fondo ha cambiado de verdad."""
        return tuple(round(level * 40) for level in self.snapshot())
