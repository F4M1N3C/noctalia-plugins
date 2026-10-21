# Lyrics Carousel

Synced lyrics in a floating terminal window, in the spirit of `cava`, `lavat` or
`unimatrix`. The plugin reads the current track from your MPRIS player, looks the
lyrics up, and renders them in a kitty window that scrolls line by line.

## Plugin

| Field | Value |
| --- | --- |
| ID | `faminec/lyrics-carousel` |
| Entries | Bar widget: `widget`; panel: `panel` |

## Requirements

The following executables must be installed and available on `PATH`:

- `kitty` — the terminal the carousel is drawn in.
- `hyprland` — the compositor; the plugin floats and positions the kitty window.
- `playerctl` — reads the title, artist and playback position from the MPRIS player.
- `python3` — runs the carousel script.

Only monospaced fonts work in kitty. `Departure Mono` (the default), `Press Start 2P`,
`Space Mono`, `NType 82 Mono`, `Lettera Mono LL` and `IBM Plex Mono` are known to work.

## Usage

Add the `widget` entry to a bar to get a music icon in the bar; clicking it opens the
control panel.

```sh
noctalia msg panel-toggle faminec/lyrics-carousel:panel
```

The panel holds the quick toggles (direction, marker, karaoke glow, visualiser, time
bar, keyboard hints, header). Toggling one writes to
`~/.local/state/noctalia/plugins/data/faminec/lyrics-carousel/overrides.json`, which the
running window re-reads about once a second, so the changes apply live. Changing the
font needs a restart of the window.

Inside the terminal window:

| Key | Action |
| --- | --- |
| `q` | Quit the window |
| `space` | Pause / resume the carousel |
| `d` | Reverse the scroll direction |
| `k` | Toggle the karaoke glow |
| `r` | Look the lyrics up again |

### Where the lyrics come from

The script reuses the source adapter of Noctalia's own Lyrics plugin, so it shares the
same sources and the same configuration: LRCLIB, NetEase, SPlayer, QQ Music and Kugou,
plus Spotify, Apple Music and Musixmatch when you have credentials for them.

The sources are queried **in parallel** and the first one to answer wins, so the lyrics
usually show up in under a second. Results are cached in `~/.cache/lyrics-carousel` so
known songs are not looked up twice.

## Settings

Settings live in *Settings → Plugins → Lyrics Carousel*.

| Setting | Type | Default | Description |
| --- | --- | --- | --- |
| `font_family` | `string` | `Departure Mono` | Monospaced font used in the kitty window. |
| `font_size` | `int` | `22` | Font size in pixels (8–48). |
| `direction` | `select` | `down` | `down` scrolls up from the bottom, `up` scrolls down. |
| `marker` | `bool` | `false` | Draw a `>` next to the active line. |
| `karaoke` | `bool` | `true` | Light the active line character by character. |
| `equalizer` | `bool` | `false` | Animated sound visualiser bars. |
| `footer` | `bool` | `false` | Elapsed time and a progress bar. |
| `hints` | `bool` | `false` | Keyboard hints at the bottom. |
| `header` | `bool` | `false` | Title, artist and status tags. |
| `spacing` | `int` | `2` | Blank lines between lyric blocks (1–6). |
| `animation_ms` | `int` | `650` | Scroll animation duration (0–3000). |
| `ghost` | `bool` | `true` | Dim the block while it moves. |
| `offset_ms` | `int` | `0` | Shift used to fine-tune the sync (-3000–3000). |
| `width` | `int` | `1200` | Window width (400–3840). |
| `height` | `int` | `820` | Window height (200–2160). |
| `anchor` | `string` | `center` | Window anchor, for example `center` or `bottom-right`. |
| `glyph` | `glyph` | `music` | Bar widget icon. |

## Notes

- The window is opened with `hl.dsp.exec_cmd(...)` and gets the class
  `noctalia-term-lyrics`; changing the font restarts it.
- The script reads the plugin settings from `~/.local/state/noctalia/settings.toml`
  (`plugin_settings."faminec/lyrics-carousel"`) plus the panel overrides file.
- Outside Hyprland the script can be run by hand as `lyrics-carousel`.
