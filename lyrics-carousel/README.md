# Lyrics Carousel

Synced lyrics in a floating kitty window, in the spirit of `cava`, `lavat` or `unimatrix`.

## Plugin

| Field | Value |
| --- | --- |
| ID | `faminec/lyrics-carousel` |
| Entries | Bar widget: `widget`; panel: `panel` |

## Requirements

The following executables must be installed and available on `PATH`:

- `kitty` — the terminal the window runs in, and the graphics protocol used by the image
  renderer.
- `hyprland` — the compositor; the window is opened with the Hyprland 0.56 Lua API.
- `playerctl` — reads the active MPRIS player.
- `python3` with `python-pillow` — draws the lyrics in image mode.

The lyrics themselves come from the Noctalia Lyrics plugin's source adapter
(`lyric_sources.py`), so the same providers and the same configuration are reused:
LRCLIB, NetEase, SPlayer, QQ Music, Kugou and, with credentials, Spotify, Apple Music
or Musixmatch.

## Usage

Add the `widget` bar icon and click it to open the lyrics window. The panel that opens
with it holds the quick switches.

The panel can also be opened directly:

```sh
noctalia msg panel-toggle faminec/lyrics-carousel:panel
```

### Two rendering modes

| Mode | What it uses | Advantages | Trade-offs |
| --- | --- | --- | --- |
| `image` (default) | Pillow and the kitty graphics protocol | The active line is drawn larger, the scroll is pixel-accurate and any font works | Needs kitty and Pillow; the text cannot be selected |
| `text` | The terminal itself | Lightweight and crisp, the text is selectable | One font size for the whole window |

In image mode the window is drawn as a transparent PNG (1653×1368 px in an 87×36 cell
window), so the desktop wallpaper stays visible through it.

The providers are queried in parallel and the first one to answer wins, so the lyrics
usually show up in under a second. The result is cached in `~/.cache/lyrics-carousel`.

### Keyboard shortcuts

| Key | Action |
| --- | --- |
| `q` | Quit |
| `space` | Pause / resume |
| `d` | Reverse the scroll direction |
| `k` | Toggle the karaoke effect |
| `r` | Look the lyrics up again |

`d` and `k` also write their value to `settings.toml`.

## Settings

Configure the plugin in **Settings → Plugins → Lyrics Carousel**. The panel writes the
same file and reloads the configuration, so the settings page and the panel always
agree; the script re-reads that file every 1.2 s, so changes apply live to a window
that is already open.

| Setting | Type | Default | Description |
| --- | --- | --- | --- |
| `font_family` | `string` | `Departure Mono` | Font used for the lyrics. |
| `font_size` | `int` | `22` | Size of the lyrics, in pixels. |
| `render_mode` | `select` | `image` | `image` (Pillow) or `text` (terminal). |
| `direction` | `select` | `down` | `down`: the lyrics come in from the top. `up`: from the bottom. |
| `marker` | `bool` | `false` | Shows a `>` next to the active line. |
| `karaoke` | `bool` | `true` | Lights the active line character by character. |
| `equalizer` | `bool` | `false` | Animated bars. |
| `footer` | `bool` | `false` | Elapsed time and a progress bar. |
| `hints` | `bool` | `false` | Keyboard hints at the bottom. |
| `header` | `bool` | `false` | Title, artist and status tags. |
| `spacing` | `int` | `2` | Space between the lines. |
| `animation_ms` | `int` | `650` | Duration of the scroll between lines. |
| `ghost` | `bool` | `true` | Dims the block while it moves. |
| `offset_ms` | `int` | `0` | Offset to fine-tune the synchronisation. |
| `width` | `int` | `1200` | Window width. |
| `height` | `int` | `820` | Window height. |
| `anchor` | `string` | `center` | Window anchor: `center`, `top-left`, `bottom-right`… |
| `accent` | `select` | `primary` | Colour of the active line: `primary` (follows the wallpaper), an ANSI colour or `custom`. |
| `custom_color` | `string` | `#e46767` | Hex colour used when `accent = custom`. |
| `active_scale` | `double` | `1.35` | Size multiplier of the line being sung (image mode). |
| `visible_above` | `int` | `6` | Lines visible above the active one. |
| `visible_below` | `int` | `6` | Lines visible below the active one. |
| `glyph` | `glyph` | `music` | Bar icon. |

The position and the size are applied live to the running window, without recreating
it. The font only needs a restart in text mode; in image mode it applies instantly.

## IPC

```sh
noctalia msg panel-toggle faminec/lyrics-carousel:panel
```

## Notes

- The window is opened with `hl.dsp.exec_cmd(...)` and the class
  `noctalia-lyrics-carousel`; the script can also be run by hand as `lyrics-carousel`.
- Outside kitty (or without Pillow) the script falls back to text mode on its own.
- The accent colour is read from the theme Noctalia generates for kitty, so it follows
  the wallpaper.
- Kitty only accepts monospaced fonts, so in text mode the usable list is
  `Departure Mono`, `Press Start 2P`, `Space Mono`, `NType 82 Mono`, `Lettera Mono LL`
  and `IBM Plex Mono`. Image mode accepts any font.
- The plugin makes network requests to the lyrics providers; nothing else leaves the
  machine.
