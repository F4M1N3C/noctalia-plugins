"""Clase ImageRenderer: dibuja el carrusel como imagen y lo manda a kitty."""

from __future__ import annotations

import math
import os
import subprocess
import sys

# realpath: el modulo puede alcanzarse por un enlace simbolico y sus
# hermanos (graphics) viven en el directorio real.
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))

from graphics import GraphicsRenderer, load_font, terminal_cells, text_width  # noqa: E402

try:
    from PIL import Image, ImageChops, ImageDraw, ImageFilter
except ImportError:  # pragma: no cover
    Image = None

FALLBACK_FONT = "/usr/share/fonts/TTF/DejaVuSansMono.ttf"

# Cuadros por segundo de la imagen. En reposo (karaoke y fondo animado) 30
# bastan; mientras el carrusel se desplaza se sube a 60, que es cuando el
# ojo nota el tirón. La huella del cuadro evita reenviar lo que no cambia.
IMAGE_FPS = 30
MOTION_FPS = 60


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

    def invalidate_fonts(self):
        """Limpia la cache de fuentes (tras un cambio de font_family/font_size)."""
        self.fonts.clear()
        self.font_files.clear()

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

    @staticmethod
    def _imagen_de(draw):
        """La imagen completa que está dibujando `draw`.

        ImageDraw no guarda la imagen: `draw.im` es el núcleo interno (sirve
        para saber el tamaño, pero no para componer capas). La imagen entera
        hace falta para recortar y pegar el trozo cantado, así que se busca
        primero la de verdad.
        """
        for atributo in ("_image", "image", "im"):
            candidata = getattr(draw, atributo, None)
            if candidata is not None and hasattr(candidata, "crop"):
                return candidata
        return None

    def _draw_karaoke(self, draw, text, center_y, size, sung, unsung, amount, family):
        """Rellena la línea cantada de izquierda a derecha, píxel a píxel.

        `amount` son los caracteres cantados con decimales. El avance se
        interpola dentro del glifo en curso, así que el relleno no salta
        de letra en letra pero sigue el ritmo real de la letra: una
        sílaba larga tarda más en llenarse, que es lo que hacía parecer
        que reconocía la velocidad de la canción.

        El resplandor es de verdad un resplandor: la capa cantada se
        difumina y se compone debajo del texto nítido, así que el brillo
        sale varios píxeles hacia fuera. Antes era un halo de un píxel (la
        misma frase pegada ocho veces alrededor), que solo pintaba un
        contorno y se veía como un pegamento.

        El borde del relleno se desvanece con una rampa de alfa: la letra
        cantada se funde con la que falta en vez de cortar en seco, y el
        ojo sigue la luz que avanza.
        """
        font = self.font(family, size)
        if font is None:
            return
        base = self._imagen_de(draw)
        if base is None:
            return
        total = text_width(draw, text, font)
        x = (base.size[0] - total) / 2
        length = len(text)
        draw.text((x, center_y), text, font=font, fill=unsung, anchor="lm")
        if length <= 0:
            return
        amount = max(0.0, min(float(length), amount))
        if amount <= 0.0:
            return
        if amount >= length:
            sung_px = total
        else:
            steps = max(1, int(amount))
            sung_px = 0.0
            for index in range(steps):
                sung_px += text_width(draw, text[index], font)
            if steps < length:
                sung_px += (amount - steps) * text_width(draw, text[steps], font)
        if sung_px <= 0.0:
            return

        # El resplandor se difumina: el radio sale del tamaño de la letra
        # y el margen deja sitio para que el halo quepa entero.
        radio = max(2.0, size * 0.22)
        left, top, right, bottom = draw.textbbox(
            (x, center_y), text, font=font, anchor="lm"
        )
        pad = max(4, int(size * 0.8) + int(radio * 2))
        box = (
            max(0, int(left) - pad),
            max(0, int(top) - pad),
            min(base.size[0], int(math.ceil(right)) + pad),
            min(base.size[1], int(math.ceil(bottom)) + pad),
        )
        width = box[2] - box[0]
        height = box[3] - box[1]
        if width <= 0 or height <= 0:
            return

        # Borde cantado, en píxeles dentro de la caja de la línea.
        limit = max(1, min(width, int(math.ceil(sung_px + x - box[0]))))

        def capa(color):
            """La frase entera sobre una capa recortada a la línea."""
            layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
            ImageDraw.Draw(layer).text(
                (x - box[0], center_y - box[1]),
                text,
                font=font,
                fill=color,
                anchor="lm",
            )
            return layer

        # El trozo cantado se recorta con crop (un píxel más no cambia nada):
        # así el borde del relleno cae dentro del glifo en curso y el avance
        # es continuo en vez de saltar de palabra en palabra.
        corte = (0, 0, limit, height)
        completa = capa(sung)
        nitido = completa.crop(corte)

        # El resplandor, en dos radios: el ancho da el halo suave y el
        # corto el brillo pegado a la letra. Se difumina la mascara de
        # la letra y se pinta del color del resplandor: si se difumina la
        # capa entera, el negro transparente de fuera se cuela en el
        # color y el halo sale sucio.
        forma = completa.getchannel("A")

        # El resplandor no se corta en el borde de lo cantado: llega un
        # poco mas alla y se apaga alli. Si se recortase en seco, el halo
        # acababa en una pared vertical de luz al lado de la letra que
        # falta, que se veía como un tajo.
        rampa = max(2, int(size * 0.5))
        mascara = Image.new("L", (width, height), 0)
        if limit > 0:
            ImageDraw.Draw(mascara).rectangle(
                [0, 0, limit - 1, height - 1], fill=255
            )
        if rampa > 0:
            caida = Image.new("L", (rampa, 1))
            caida.putdata(
                [
                    int(255 * (1.0 - (indice + 1) / float(rampa)))
                    for indice in range(rampa)
                ]
            )
            caida = caida.resize((rampa, height), Image.Resampling.NEAREST)
            mascara.paste(caida, (limit, 0))

        def difusa(color, sigma):
            """La forma de la letra difuminada, del color pedido.

            La mascara se difumina a cuarta parte y se amplia: el halo es
            una luz suave, asi que no se nota, y el modo imagen va a 20
            cuadros por segundo y no puede gastar la mitad del tiempo en
            difuminar.
            """
            pequena = forma.resize(
                (max(1, width // 4), max(1, height // 4)),
                Image.Resampling.BILINEAR,
            ).filter(ImageFilter.GaussianBlur(max(0.5, sigma / 4.0)))
            alfa = ImageChops.multiply(
                pequena.resize((width, height), Image.Resampling.BILINEAR),
                mascara,
            )
            halo = Image.new(
                "RGBA", (width, height), (color[0], color[1], color[2], 0)
            )
            halo.putalpha(alfa)
            return halo

        resplandor = difusa(self._mix(sung, unsung, 0.45), radio)
        nucleo = difusa(sung, radio / 2.0)

        # El borde del relleno se suaviza: una rampa de alfa en las últimas
        # columnas funde la letra cantada con la que todavía no se ha
        # cantado, en vez de cortar el color en seco.
        if rampa < limit:
            suave = Image.new("L", (limit, height), 255)
            valores = [
                int(255 * (indice + 1) / float(rampa)) for indice in range(rampa)
            ]
            columna = Image.new("L", (rampa, 1))
            columna.putdata(valores)
            columna = columna.resize((rampa, height), Image.Resampling.NEAREST)
            suave.paste(columna, (limit - rampa, 0))
            nitido.putalpha(ImageChops.multiply(nitido.getchannel("A"), suave))

        # El orden importa: el halo va debajo, el texto nítido encima. Los
        # dos halos se funden en una sola capa para no componer dos veces
        # sobre la imagen entera.
        base.alpha_composite(
            Image.alpha_composite(resplandor, nucleo), (box[0], box[1])
        )
        base.alpha_composite(nitido, (box[0], box[1]))

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
            cursor = center_y - big_h / 2 - gap - small_h / 2
            for index in range(focus + 1, focus + 1 + above):
                positions[index] = cursor
                cursor -= small_h + gap
            cursor = center_y + big_h / 2 + gap + small_h / 2
            for index in range(focus - 1, focus - 1 - below, -1):
                positions[index] = cursor
                cursor += small_h + gap
        else:
            cursor = center_y - big_h / 2 - gap - small_h / 2
            for index in range(focus - 1, focus - 1 - above, -1):
                positions[index] = cursor
                cursor -= small_h + gap
            cursor = center_y + big_h / 2 + gap + small_h / 2
            for index in range(focus + 1, focus + 1 + below):
                positions[index] = cursor
                cursor += small_h + gap
        return positions

    # -- fondo ----------------------------------------------------------

    def _draw_visualizer(self, image, xpix, ypix, accent):
        """Barras de cava de fondo, en la zona configurada y detras de la letra.

        Se dibujan primero (la letra va encima) con alfa bajo: el fondo se ve
        como un ecualizador real sin tapar el texto. La zona y cobertura
        se configuran en el panel (visualizer_position, visualizer_coverage).
        """
        visualizer = getattr(self.app, "visualizer", None)
        if visualizer is None:
            return
        position = getattr(self.app, "visualizer_position", "bottom")
        coverage = getattr(self.app, "visualizer_coverage", 25) / 100.0
        
        try:
            levels = visualizer.snapshot(simulate=bool(getattr(self.app, "demo", False)))
        except Exception:  # noqa: BLE001 - el fondo nunca tumba el cuadro
            return
        if not levels:
            return
        
        count = len(levels)
        color = self._mix(accent, self.app.theme.background, 0.55)
        paint = ImageDraw.Draw(image)
        
        if position in ("top", "bottom"):
            # Banda horizontal
            band_h = max(2, int(ypix * coverage))
            if position == "bottom":
                y0 = ypix - band_h
            else:
                y0 = 0
            slot = xpix / float(count)
            gap = max(1.0, slot * 0.24)
            width = max(1, int(slot - gap))
            for index, level in enumerate(levels):
                level = max(0.0, min(1.0, float(level)))
                h = max(1.0, band_h * level)
                x0 = index * slot + gap / 2.0
                alpha = int(34 + 58 * level)
                if position == "bottom":
                    paint.rectangle(
                        [x0, ypix - h, x0 + width, ypix],
                        fill=color + (alpha,),
                    )
                    # Tapa superior
                    if h > 4.0:
                        paint.rectangle(
                            [x0, ypix - h, x0 + width, ypix - h + 2],
                            fill=color + (min(170, alpha + 55),),
                        )
                else:
                    paint.rectangle(
                        [x0, 0, x0 + width, h],
                        fill=color + (alpha,),
                    )
                    # Tapa inferior
                    if h > 4.0:
                        paint.rectangle(
                            [x0, h - 2, x0 + width, h],
                            fill=color + (min(170, alpha + 55),),
                        )
        else:
            # Banda vertical (left/right)
            band_w = max(2, int(xpix * coverage))
            if position == "right":
                x0 = xpix - band_w
            else:
                x0 = 0
            slot = ypix / float(count)
            gap = max(1.0, slot * 0.24)
            width = max(1, int(slot - gap))
            for index, level in enumerate(levels):
                level = max(0.0, min(1.0, float(level)))
                w = max(1.0, band_w * level)
                y0 = index * slot + gap / 2.0
                alpha = int(34 + 58 * level)
                if position == "right":
                    paint.rectangle(
                        [xpix - w, y0, xpix, y0 + width],
                        fill=color + (alpha,),
                    )
                    # Tapa izquierda
                    if w > 4.0:
                        paint.rectangle(
                            [xpix - w, y0, xpix - w + 2, y0 + width],
                            fill=color + (min(170, alpha + 55),),
                        )
                else:
                    paint.rectangle(
                        [0, y0, w, y0 + width],
                        fill=color + (alpha,),
                    )
                    # Tapa derecha
                    if w > 4.0:
                        paint.rectangle(
                            [w - 2, y0, w, y0 + width],
                            fill=color + (min(170, alpha + 55),),
                        )

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
        # Si el cuadro no ha cambiado no se dibuja ni se envía nada. El
        # tamaño va en la huella: si la ventana se redimensiona hay que
        # reenviar la imagen aunque el contenido sea el mismo.
        signature = self._frame_signature(accent) + (cols, rows, xpix, ypix)
        if signature == self.last_signature:
            return True
        self.last_signature = signature

        image = Image.new("RGBA", (xpix, ypix), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        self._measure_draw = draw
        background = theme.background

        # -- fondo: barras del visualizador, a todo el ancho y detras de todo
        self._draw_visualizer(image, xpix, ypix, accent)

        # -- cabecera
        top = size * 1.9
        bottom = ypix - size * 1.9
        if cfg["header"]:
            title = app.track.title or app.tr("nothing_playing")
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

        # -- letra
        center_y = (top + bottom) / 2
        if app.state == "lyrics" and app.lines:
            self._draw_lyrics(draw, center_y, size, scale, family, accent, position, top, bottom)
        else:
            self._draw_state(draw, center_y, size, family)

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
            index, focus, round(progress * MOTION_FPS), app.state, app.track.title,
            app.track.artist, int(position) if cfg["footer"] else 0,
            accent, cfg["font_family"], cfg["font_size"], cfg["active_scale"],
            cfg["visible_above"], cfg["visible_below"], cfg["direction"],
            cfg["karaoke"], cfg["marker"], cfg["header"], cfg["footer"],
            cfg["hints"], cfg["spacing"], cfg["ghost"],
            round(position * MOTION_FPS),
        ]
        # El fondo se mueve aunque la letra no cambie: su huella entra en la
        # del cuadro o la imagen se quedaria congelada entre lineas.
        visualizer = getattr(app, "visualizer", None)
        if visualizer is not None:
            parts.append(visualizer.signature())
        return tuple(parts)

    def _draw_lyrics(self, draw, center_y, size, scale, family, accent, position, area_top, area_bottom):
        app = self.app
        theme = app.theme
        background = theme.background
        index, focus, progress = app.scroll_state(position)
        lines = app.lines

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
                siguiente = app.next_timed_start(line_index)
                if siguiente is not None and siguiente > line.start:
                    end = siguiente if not line.duration else min(end, siguiente)
                # El mismo cálculo que el modo texto: si el adaptador da
                # tiempos por carácter el relleno los respeta, y si no
                # reparte la duración de la línea entre los caracteres.
                amount = app.karaoke_amount(line, text, position, end)
                unsung = self._mix(accent, background, 0.45)
                self._draw_karaoke(
                    draw, text, y, line_size, accent, unsung, amount, family
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

    def _draw_state(self, draw, center_y, size, family):
        app = self.app
        theme = app.theme
        if app.state == "loading":
            message = app.tr("searching_lyrics")
            detail = (app.track.title + " — " + app.track.artist).strip(" —")
        elif app.state == "empty":
            message = app.tr("no_lyrics_title")
            detail = app.tr("try_another_source")
        else:
            message = app.tr("nothing_playing")
            detail = app.tr("open_player")
        self._draw_centered(draw, message, center_y, size, theme.faint, family)
        self._draw_centered(draw, detail, center_y + size * 1.6, size * 0.9, theme.bright, family)

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
        xpix, ypix = app.terminal_pixels()
        y = ypix - size * 0.6
        candidates = app.texts.get("hints") or [""]
        self._measure_draw = draw
        limit = max(1.0, xpix - size * 3.2)
        text = candidates[0]
        font = self.font(family, size * 0.8)
        if font is not None:
            for candidate in candidates:
                if text_width(draw, candidate, font) <= limit:
                    text = candidate
                    break
            else:
                text = self.fit_text(candidates[0], limit, size * 0.8, family)
        # La fila entera queda centrada en la ventana: antes empezaba a la
        # izquierda y el sobrante se acumulaba a la derecha.
        self._draw_centered(
            draw, text, y, size * 0.8,
            self._mix(theme.faint, theme.background, 0.7), family,
        )

