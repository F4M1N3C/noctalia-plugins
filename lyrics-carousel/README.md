# Lyrics Carousel

Carrusel de letras sincronizadas en una ventana flotante de kitty, al estilo de
`cava`, `lavat` o `unimatrix`.

- Widget de barra (`faminec/lyrics-carousel:widget`) con el icono de música.
- Panel (`faminec/lyrics-carousel:panel`) con interruptores rápidos.
- Script propio (`bin/lyrics-carousel`) que lee el reproductor MPRIS con
  `playerctl` y busca la letra.

## Dos modos de dibujo

| Modo | Qué usa | Ventajas | Inconvenientes |
| --- | --- | --- | --- |
| `image` (por defecto) | Pillow + protocolo de gráficos de kitty | La línea activa se dibuja más grande, el desplazamiento es a nivel de píxel y admite cualquier tipografía | Necesita kitty y Pillow; el texto no es seleccionable |
| `text` | La propia terminal | Ligero, nítido, el texto es seleccionable | Un solo tamaño de letra para toda la ventana |

En modo imagen la ventana se dibuja como una imagen PNG con transparencia
(1653×1368 px en una ventana de 87×36 celdas), así que el fondo de pantalla se
sigue viendo a través.

## De dónde sale la letra

El script reutiliza el adaptador de fuentes del plugin Lyrics de Noctalia
(`lyric_sources.py`), así que comparte con él las mismas fuentes y la misma
configuración: LRCLIB, NetEase, SPlayer, QQ Music, Kugou y, si tienes
credenciales, Spotify, Apple Music o Musixmatch.

Las fuentes se consultan **en paralelo** y gana la primera que responde, así que
normalmente la letra aparece en menos de un segundo. El resultado se guarda en
`~/.cache/lyrics-carousel` para no volver a buscar lo que ya sabes.

## Ajustes

Todos los ajustes viven en el `settings.toml` de Noctalia
(`[plugin_settings."faminec/lyrics-carousel"]`). El panel los escribe ahí con
`bin/set-setting.py` y recarga la configuración, de modo que **la página de
ajustes y el panel muestran siempre lo mismo** (no hay dos fuentes de verdad).
El script lee ese mismo fichero cada 1,2 s, así que los cambios se aplican en
caliente a la ventana que ya esté abierta.

| Clave | Por defecto | Descripción |
| --- | --- | --- |
| `font_family` | `Departure Mono` | Tipografía de la letra. |
| `font_size` | `22` | Tamaño de la letra en píxeles. |
| `render_mode` | `image` | `image` (Pillow) o `text` (terminal). |
| `direction` | `down` | `down`: las letras entran por arriba. `up`: por abajo. |
| `marker` | `false` | Marca `>` junto a la línea activa. |
| `karaoke` | `true` | Ilumina la línea activa carácter a carácter. |
| `equalizer` | `false` | Barras animadas. |
| `footer` | `false` | Tiempo transcurrido y barra de progreso. |
| `hints` | `false` | Atajos de teclado abajo. |
| `header` | `false` | Título, artista y etiquetas de estado. |
| `spacing` | `2` | Separación entre renglones. |
| `animation_ms` | `650` | Duración del desplazamiento entre líneas. |
| `ghost` | `true` | Atenúa el bloque mientras se mueve. |
| `offset_ms` | `0` | Desfase para afinar la sincronía. |
| `width` / `height` | `1200` / `820` | Tamaño de la ventana. |
| `anchor` | `center` | Posición: `center`, `top-left`, `bottom-right`... |
| `accent` | `primary` | Color de la línea activa: `primary` (sigue al fondo), ANSI o `custom`. |
| `custom_color` | `#e46767` | Color hexadecimal para `accent = custom`. |
| `active_scale` | `1.35` | Multiplicador de tamaño de la línea que se canta (modo imagen). |
| `visible_above` / `visible_below` | `6` / `6` | Renglones visibles a cada lado. |
| `glyph` | `music` | Icono de la barra. |

La posición y el tamaño de la ventana se aplican **en caliente** sobre la
ventana existente (sin recrearla). La tipografía solo necesita reiniciar la
ventana en modo texto; en modo imagen se aplica al instante.

## Tipografías

Kitty solo acepta fuentes monoespaciadas, así que en modo texto la lista es:

- `Departure Mono` — pixel lo-fi, la que más se parece al logo de OpenCode.
- `Press Start 2P` — pixel 8×8 clásico, el aire de `tty-clock`.
- `Space Mono`, `NType 82 Mono`, `Lettera Mono LL` — de la colección Nothing.
- `IBM Plex Mono` — el cuerpo tipográfico de la web de OpenCode.

En modo imagen se puede usar cualquier otra (`Nothing Font (5x7)`, `Ndot 57`…),
también las proporcionales.

## Atajos dentro de la ventana

- `q` salir
- `espacio` pausar / reanudar
- `d` invertir el sentido del carrusel
- `k` activar o desactivar el efecto karaoke
- `r` volver a buscar la letra

Los atajos `d` y `k` además guardan el valor en el `settings.toml`.

## Notas

- La ventana se abre con `hl.dsp.exec_cmd(...)` y la clase
  `noctalia-lyrics-carousel`; el script se puede lanzar a mano con `lyrics-carousel`.
- Fuera de kitty (o sin Pillow) el script cae al modo texto automáticamente.
- El color de acento se lee del tema que Noctalia genera para kitty, así que
  sigue al fondo de pantalla.
