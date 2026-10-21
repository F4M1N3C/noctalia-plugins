"""Renderizador por imagen del carrusel de letras (protocolo de gráficos de kitty).

Ventajas frente al modo texto:
  * La línea activa se puede dibujar con otro tamaño de letra (active_scale).
  * El desplazamiento es a nivel de píxel, no de fila de terminal.
  * Admite cualquier TTF/OTF, también los que kitty rechaza por no ser
    monoespaciados.

El tamaño en píxeles del terminal se saca de TIOCGWINSZ (ws_xpixel/ws_ypixel),
que kitty rellena, así que la imagen encaja 1:1 en la rejilla de celdas.
"""

from __future__ import annotations

import base64
import fcntl
import os
import struct
import sys
import termios
import zlib

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:  # pragma: no cover
    Image = None


def terminal_cells(fd=None):
    """(cols, rows, xpix, ypix) del terminal."""
    fd = fd if fd is not None else sys.stdout.fileno()
    try:
        raw = fcntl.ioctl(fd, termios.TIOCGWINSZ, b"\0" * 8)
    except OSError:
        return 0, 0, 0, 0
    rows, cols, xpix, ypix = struct.unpack("HHHH", raw)
    return cols, rows, xpix, ypix


def is_kitty() -> bool:
    return os.environ.get("KITTY_WINDOW_ID") is not None


class GraphicsRenderer:
    """Dibuja el carrusel en un canvas y lo manda a kitty."""

    IMAGE_ID = 77

    def __init__(self, out=None):
        self.out = out or sys.stdout
        self.image_id = self.IMAGE_ID
        self.placement_id = 78
        self.last_size = (0, 0)
        self.supported = is_kitty()
        self.broken = False
        self.write_errors = 0

    # -- canvas ---------------------------------------------------------

    def new_canvas(self, width, height):
        if Image is None:
            return None
        return Image.new("RGBA", (max(1, width), max(1, height)), (0, 0, 0, 0))

    # -- envío ----------------------------------------------------------

    def _send(self, payload: bytes, cols: int, rows: int, width: int, height: int):
        """Transmite los datos de la imagen (sin colocarla).

        Solo el primer trozo lleva los datos de control; el resto únicamente
        el flag m (protocolo de gráficos de kitty).
        """
        if self.broken:
            return False
        encoded = base64.b64encode(payload).decode("ascii")
        chunk = 4096
        parts = [encoded[i : i + chunk] for i in range(0, len(encoded), chunk)] or [""]
        try:
            for index, part in enumerate(parts):
                more = 1 if index < len(parts) - 1 else 0
                if index == 0:
                    # Sin clave "a" la imagen solo se transmite; la
                    # colocación se hace después con a=p.
                    control = (
                        f"f=32,s={width},v={height},o=z,i={self.image_id},q=2,m={more}"
                    )
                else:
                    control = f"m={more}"
                self.out.write(f"\x1b_G{control};{part}\x1b\\")
            self.out.flush()
        except OSError:
            # El terminal se ha redimensionado o cerrado: no es un fallo fatal.
            self.write_errors += 1
            if self.write_errors > 30:
                self.broken = True
            return False
        return True

    def present(self, image, cols: int, rows: int):
        """Manda la imagen y la deja colocada en la ventana.

        Se usa el formato crudo RGBA (f=32) comprimido con zlib: es unas tres
        veces más rápido de codificar que PNG y pesa lo mismo.

        Para actualizar en el sitio se borra la imagen anterior, se
        transmiten los datos nuevos y se vuelve a colocar con el mismo id de
        colocación (C=1 evita que el cursor se mueva). Todo va dentro de una
        actualización sincronizada para que no parpadee.
        """
        if image is None or cols <= 0 or rows <= 0:
            return False
        width, height = image.size
        try:
            payload = zlib.compress(image.tobytes(), 1)
        except Exception:  # noqa: BLE001
            return False
        try:
            self.out.write("\x1b[?2026h")
            # Se borra la imagen anterior (y sus colocaciones).
            self.out.write(f"\x1b_Ga=d,d=I,i={self.image_id},q=2\x1b\\")
            ok = self._send(payload, cols, rows, width, height)
            # Se coloca la imagen nueva en la esquina con el mismo id.
            # El cursor marca el sitio: va a la esquina superior izquierda.
            self.out.write("\x1b[1;1H")
            self.out.write(
                f"\x1b_Ga=p,i={self.image_id},p={self.placement_id},"
                f"c={cols},r={rows},C=1,q=2\x1b\\"
            )
            self.out.write("\x1b[?2026l")
            self.out.flush()
        except OSError:
            self.write_errors += 1
            if self.write_errors > 30:
                self.broken = True
            return False
        self.last_size = (cols, rows)
        return ok

    def clear(self):
        """Quita la imagen de la pantalla."""
        self.out.write(f"\x1b_Ga=d,d=I,i={self.image_id},q=2\x1b\\")
        self.out.flush()


def load_font(path: str, size: int):
    if Image is None or not path:
        return None
    try:
        return ImageFont.truetype(path, max(1, int(size)))
    except OSError:
        return None


def text_width(draw, text, font) -> float:
    if not text:
        return 0.0
    try:
        return draw.textlength(text, font=font)
    except AttributeError:
        return font.getsize(text)[0]
