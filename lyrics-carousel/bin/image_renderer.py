"""Clase ImageRenderer: dibuja el carrusel como imagen y lo manda a kitty."""

from __future__ import annotations

import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from graphics import GraphicsRenderer, load_font, terminal_cells, text_width  # noqa: E402

try:
    from PIL import Image, ImageDraw
except ImportError:  # pragma: no cover
    Image = None

FALLBACK_FONT = "/usr/share/fonts/TTF/DejaVuSansMono.ttf"


def mmss(seconds):
    """Segundos -> mm:ss."""
    seconds = max(0, int(seconds or 0))
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


class ImageRenderer:
    """Renderiza el carrusel con Pillow y lo muestra con el protocolo de kitty.

    Ventajas sobre el modo texto:
      * la línea activa se dibuja con otro tamaño (active_scale),
      * el desplazamiento es a nivel de píxel,
      * admite cualquier tipografía, no solo monoespaciadas.
    """

    def __init__(self, app):
        self.app = app
        self.gfx = GraphicsRenderer()
        self.fonts = {}
        self.font_files = {}
        self.last_signature = None
        self._measure_draw = None
        self._signature = None
        self.frames = 0
        self.sends = 0

    # -- tipografías ---------------------------------------------------

    def font_file(self, family: str) -> str:
        if family in self.font_files:
            return self.font_files[family]
        path = ""
        try:
            result = subprocess.run(
                ["fc-match", "-f", "%{file}", family],
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
            )
            if result.returncode == 0:
                path = (result.stdout or "").strip().splitlines()[0:1]
                path = path[0] if path else ""
        except (OSError, subprocess.SubprocessError, IndexError):
            path = ""
        if not path or not os.path.isfile(path):
            path = FALLBACK_FONT
        self.font_files[family] = path
        return path

    def font(self, family: str, size: float):
        key = (family, int(round(size)))
        font = self.fonts.get(key)
        if font is None:
            font = load_font(self.font_file(family), key[1])
            self.fonts[key] = font
        return font

    # -- utilidades de dibujo ------------------------------------------

    @staticmethod
    def _mix(color, background, factor):
        return (
            int(background[0] + (color[0] - background[0]) * factor),
            int(background[1] + (color[1] - background[1]) * factor),
            int(background[2] + (color[2] - background[2]) * factor),
        )

    def fit_text(self, text, max_width, size, family):
        """Recorta el texto para que quepa en el ancho disponible."""
        font = self.font(family, size)
        if font is None:
            return text
        if text_width(self._measure_draw, text, font) <= max_width:
            return text
        cut = len(text)
        while cut > 1:
            cut -= 1
            candidate = text[:cut] + "…"
            if text_width(self._measure_draw, candidate, font) <= max_width:
                return candidate
        return "…"

    def _draw_centered(self, draw, text, center_y, size, color, family):
        font = self.font(family, size)
        if font is None:
            return 0.0
        width = text_width(draw, text, font)
        x = (draw.im.size[0] - width) / 2
        draw.text((x, center_y), text, font=font, fill=color, anchor="lm")
        return width

    def _draw_karaoke(self, draw, text, center_y, size, sung, unsung, cut, family):
        font = self.font(family, size)
        if font is None:
            return
        total = text_width(draw, text, font)
        x = (draw.im.size[0] - total) / 2
        head = text[:cut]
        tail = text[cut:]
        if head:
            draw.text((x, center_y), head, font=font, fill=sung, anchor="lm")
            x += text_width(draw, head, font)
        if tail:
            draw.text((x, center_y), tail, font=font, fill=unsung, anchor="lm")

    def _draw_left(self, draw, text, x, y, size, color, family, anchor="lm"):
        font = self.font(family, size)
        if font is None:
            return
        draw.text((x, y), text, font=font, fill=color, anchor=anchor)

    def _draw_right(self, draw, text, right_x, y, size, color, family):
        font = self.font(family, size)
        if font is None:
            return
        width = text_width(draw, text, font)
        draw.text((right_x - width, y), text, font=font, fill=color, anchor="lm")

    # -- disposición ----------------------------------------------------

    def _layout(self, focus, center_y, size, scale):
        """Devuelve las posiciones (centro vertical) de las líneas alrededor de focus.

        En sentido "down" las líneas futuras entran por arriba (como en el modo
        texto) y las pasadas salen por abajo; en "up" al revés.
        """
        app = self.app
        above = app.cfg["visible_above"]
        below = app.cfg["visible_below"]
        down = app.cfg["direction"] == "down"
        small_h = size * 1.32
        big_h = size * scale * 1.32
        gap = size * 0.30 * max(1, app.cfg["spacing"])
        positions = {}
        positions[focus] = center_y

        if down:
            # Arriba las líneas que vienen, abajo las que ya han pasado.
            cursor = center_y - big_h / 2 - gap
            for index in range(focus + 1, focus + 1 + above):
                positions[index] = cursor + small_h / 2
                cursor -= small_h + gap
            cursor = center_y + big_h / 2 + gap
            for index in range(focus - 1, focus - 1 - below, -1):
                positions[index] = cursor - small_h / 2
                cursor += small_h + gap
        else:
            cursor = center_y - big_h / 2 - gap
            for index in range(focus - 1, focus - 1 - above, -1):
                positions[index] = cursor - small_h / 2
                cursor -= small_h + gap
            cursor = center_y + big_h / 2 + gap
            for index in range(focus + 1, focus + 1 + below):
                positions[index] = cursor + small_h / 2
                cursor += small_h + gap
        return positions

    # -- render principal -----------------------------------------------

    def render(self):
        app = self.app
        if Image is None or not self.gfx.supported:
            return False
        cols, rows, xpix, ypix = terminal_cells()
        if xpix <= 0 or ypix <= 0 or cols <= 0 or rows <= 0:
            return False

        cfg = app.cfg
        theme = app.theme
        accent = theme.accent_color(cfg)
        family = cfg["font_family"]
        size = float(cfg["font_size"])
        scale = float(cfg["active_scale"])
        position = app.position()
        duration = app.track.duration if app.track else 0.0

        self.frames += 1
        # Si el cuadro no ha cambiado no se dibuja ni se envía nada.
        signature = self._frame_signature(accent)
        if signature == self.last_signature:
            return True
        self.last_signature = signature

        image = Image.new("RGBA", (xpix, ypix), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        self._measure_draw = draw
        background = theme.background

        # -- cabecera
        top = size * 1.9
        bottom = ypix - size * 1.9
        if cfg["header"]:
            title = app.track.title or "nada sonando"
            artist = app.track.artist or ""
            self._draw_left(draw, title, size * 1.6, top, size * 0.95, theme.bright, family)
            if artist:
                self._draw_left(
                    draw, "— " + artist, size * 1.6, top + size * 1.2,
                    size * 0.8, theme.faint, family,
                )
            rule_y = top + size * 2.0
            ImageDraw.Draw(image).rectangle(
                [size * 1.6, rule_y, xpix - size * 1.6, rule_y + max(1, size * 0.05)],
                fill=self._mix(theme.faint, background, 0.35),
            )
            top = rule_y + size * 0.9
        if cfg["equalizer"]:
            eq = app.equalizer_text()
            self._draw_right(draw, eq, xpix - size * 1.6, top, size * 1.0, accent, family)
            top += size * 1.5

        # -- letra
        center_y = (top + bottom) / 2
        if app.state == "lyrics" and app.lines:
            self._draw_lyrics(draw, center_y, size, scale, family, accent, position, top, bottom)
        else:
            self._draw_state(draw, center_y, size, family, accent)

        # -- pie
        if cfg["footer"]:
            self._draw_footer(draw, xpix, ypix, size, family, accent, position, duration)
        if cfg["hints"]:
            self._draw_hints(draw, size, family)

        self.sends += 1
        return self.gfx.present(image, cols, rows)

    def _frame_signature(self, accent):
        """Huella del cuadro: si no cambia, no se vuelve a enviar la imagen."""
        app = self.app
        cfg = app.cfg
        position = app.position()
        index, focus, progress = app.scroll_state(position)
        parts = [
            index, focus, round(progress * 60), app.state, app.track.title,
            app.track.artist, int(position) if cfg["footer"] else 0,
            accent, cfg["font_family"], cfg["font_size"], cfg["active_scale"],
            cfg["visible_above"], cfg["visible_below"], cfg["direction"],
            cfg["karaoke"], cfg["marker"], cfg["header"], cfg["footer"],
            cfg["hints"], cfg["equalizer"], cfg["spacing"], cfg["ghost"],
        ]
        if app.lines and index < len(app.lines) and cfg["karaoke"]:
            # La huella usa el número de caracteres cantados (no la fracción),
            # así solo cambia cuando avanza una letra.
            line = app.lines[index]
            times = [item.start for item in app.lines]
            end = line.start + (line.duration or 4.0)
            if index + 1 < len(times) and times[index + 1] > line.start:
                end = times[index + 1] if not line.duration else min(end, times[index + 1])
            fraction = max(
                0.0, min(1.0, (position - line.start) / max(0.35, end - line.start))
            )
            parts.append(int(fraction * max(1, len(line.text))))
        return tuple(parts)

    def _draw_lyrics(self, draw, center_y, size, scale, family, accent, position, area_top, area_bottom):
        app = self.app
        theme = app.theme
        background = theme.background
        index, focus, progress = app.scroll_state(position)
        lines = app.lines
        times = [line.start for line in lines]

        pos_a = self._layout(index, center_y, size, scale)
        pos_b = self._layout(focus, center_y, size, scale)

        visible = set(pos_a) | set(pos_b)
        # Escala interpolada: la línea que sale encoge, la que entra crece.
        for line_index in sorted(visible):
            if line_index < 0 or line_index >= len(lines):
                continue
            line = lines[line_index]
            y_a = pos_a.get(line_index)
            y_b = pos_b.get(line_index)
            if y_a is None:
                y = y_b
            elif y_b is None:
                y = y_a
            else:
                y = y_a + (y_b - y_a) * progress

            if line_index == index:
                factor = 1.0 + (scale - 1.0) * (1.0 - progress)
            elif line_index == focus:
                factor = 1.0 + (scale - 1.0) * progress
            else:
                factor = 1.0
            line_size = size * factor

            distance = abs(y - center_y)
            span = max(1.0, (area_bottom - area_top) * 0.5)
            fade = max(0.22, 1.0 - (distance / span) ** 1.0)
            is_sung = line_index == index
            if is_sung:
                color = accent
            else:
                base = theme.foreground if line_index > index else theme.past
                color = self._mix(base, background, fade)
            if app.cfg["ghost"] and 0.0 < progress < 1.0:
                # Atenúa el bloque mientras se mueve (transición suave).
                color = self._mix(color, background, 0.18 * (1.0 - progress))

            text = self.fit_text(
                line.text, draw.im.size[0] - size * 6, size * factor, family
            )
            marker = ""
            if app.cfg["marker"] and is_sung:
                marker = "> "
            if marker:
                self._draw_marker(draw, text, y, line_size, marker, family, accent)
            if is_sung and app.karaoke and app.cfg["karaoke"]:
                end = line.start + (line.duration or 4.0)
                if line_index + 1 < len(times) and times[line_index + 1] > line.start:
                    end = times[line_index + 1] if not line.duration else min(end, times[line_index + 1])
                fraction = max(
                    0.0, min(1.0, (position - line.start) / max(0.35, end - line.start))
                )
                cut = int(round(len(text) * fraction))
                unsung = self._mix(accent, background, 0.45)
                self._draw_karaoke(
                    draw, text, y, line_size, accent, unsung, cut, family
                )
            else:
                self._draw_centered(draw, text, y, line_size, color, family)

    def _draw_marker(self, draw, text, center_y, size, marker, family, color):
        """Marca ">" pegada a la izquierda de la línea activa."""
        font = self.font(family, size)
        if font is None:
            return
        width = text_width(draw, text, font)
        marker_width = text_width(draw, marker, font)
        x = (draw.im.size[0] - width) / 2 - marker_width - size * 0.35
        draw.text((x, center_y), marker, font=font, fill=color, anchor="lm")

    def _draw_state(self, draw, center_y, size, family, accent):
        app = self.app
        theme = app.theme
        if app.state == "loading":
            message = "buscando letra"
            detail = (app.track.title + " — " + app.track.artist).strip(" —")
        elif app.state == "empty":
            message = "sin letra para esta canción"
            detail = "prueba otra fuente o vuelve a intentarlo con [r]"
        else:
            message = "nada sonando"
            detail = "abre YouTube Music o cualquier reproductor MPRIS"
        self._draw_centered(draw, message, center_y, size, theme.faint, family)
        self._draw_centered(draw, detail, center_y + size * 1.6, size * 0.9, theme.bright, family)
        eq = app.equalizer_text()
        self._draw_centered(draw, eq, center_y + size * 3.2, size * 1.1, accent, family)

    def _draw_footer(self, draw, xpix, ypix, size, family, accent, position, duration):
        app = self.app
        theme = app.theme
        y = ypix - size * 1.6
        left = mmss(position)
        right = mmss(duration) if duration > 0 else "--:--"
        ratio = max(0.0, min(1.0, position / duration)) if duration > 0 else 0.0
        margin = size * 1.6
        bar_x0 = margin + size * 3.2
        bar_x1 = xpix - margin - size * 3.2
        bar_width = max(10, bar_x1 - bar_x0)
        self._draw_left(draw, left, margin, y, size * 0.9, theme.faint, family)
        self._draw_right(draw, right, xpix - margin, y, size * 0.9, theme.faint, family)
        filled = int(bar_width * ratio)
        color = self._mix(theme.past, theme.background, 0.6)
        draw.rectangle([bar_x0, y - size * 0.18, bar_x1, y + size * 0.18], fill=color)
        if filled > 0:
            draw.rectangle(
                [bar_x0, y - size * 0.18, bar_x0 + filled, y + size * 0.18], fill=accent
            )

    def _draw_hints(self, draw, size, family):
        app = self.app
        theme = app.theme
        y = app.terminal_pixels()[1] - size * 0.6
        text = "[q] salir  [espacio] pausa  [d] dirección  [k] karaoke  [r] recargar"
        self._draw_left(
            draw, text, size * 1.6, y, size * 0.8,
            self._mix(theme.faint, theme.background, 0.7), family,
        )

