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
| `anchor` | `string` | `center` | Window anchor: `center`, `top-left`, `bottom-right`… or `custom` (uses custom_x/custom_y). |
| `custom_x` | `int` | `100` | Custom horizontal position (only with anchor = custom). |
| `custom_y` | `int` | `100` | Custom vertical position (only with anchor = custom). |
| `accent` | `select` | `primary` | Colour of the active line: `primary` (follows the wallpaper), an ANSI colour or `custom`. |
| `custom_color` | `string` | `#e46767` | Hex colour used when `accent = custom`. |
| `active_scale` | `double` | `1.35` | Size multiplier of the line being sung (image and text mode). |
| `visible_above` | `int` | `6` | Lines visible above the active one. |
| `visible_below` | `int` | `6` | Lines visible below the active one. |
| `glyph` | `glyph` | `music` | Bar icon. |

The position and the size are applied live to the running window, without recreating
it. The font only needs a restart in text mode; in image mode it applies instantly.

## Changelog (round 2)

- Width/height controls are now steppers (− / value / +) with hover-to-adjust;
  only 3 controls per row, no visual collision.
- Font family and font size apply live in image mode (font cache invalidated on
  change). In text mode, font size applies live via kitty remote control and
  active line scaling uses the kitty text sizing protocol (OSC 66).
- The window is no longer closed/reopened when changing settings; it stays open.
- Window position is now a dropdown (9 anchors + custom) with X/Y coordinate
  inputs when "custom" is selected.
- Active line size (active_scale) now works in both image mode and text mode.
- Added regression tests for each of the above.

## IPC

```sh
noctalia msg panel-toggle faminec/lyrics-carousel:panel
```

## Diagnostics

```sh
python3 ~/.local/share/noctalia/plugins/lyrics-carousel/bin/selftest.py --verbose
lyrics-carousel --diagnostics
```

The self-test checks the installation assumptions: the helper is next to the
script, the data directory can be created, the overrides round-trip, the
external tools are available and — importantly — that the script finds its
sibling modules and the helper when it is launched through the symbolic link
in `~/.local/bin` (which is how the panel starts it). It also checks that
every `.luau` of the plugin compiles as it is (so a syntax error is never
mistaken for Luau-only syntax) and that the `d` and `k` shortcuts really
toggle the direction and the karaoke and save them (the overrides are left
as they were). It also checks that the demo mode does not ask any lyrics
provider for anything — and that the script's debug log is actually being
written, so that check is not vacuous.

The self-test never touches the real state: the overrides file can be
redirected with the `LYRICS_CAROUSEL_OVERRIDES` environment variable (the
script and the helper both honour it), and the test uses a temporary one.
That also avoids a race: the script writes asynchronously, so a write
could land after the test had finished and end up applied to the real
settings the next time the panel is closed.

`--diagnostics` prints the same information for the running script as JSON.
Both are used by `tools/verify-plugins.py`.

The verifier itself has a regression battery, which simulates failures
(a broken `.luau`, a self-test that fails without naming the plugin, a
validator that crashes, a missing compiler, a missing log, no shared
validators) and checks that each one is reported and blocks the pass.
It works on temporary copies of the repository, the deployment and the
state, so it never touches the real installation.

The battery reads the verifier's result in JSON (`--json`), so it checks
the behaviour (which failures, of which plugin, blocking or not) and not
the wording of the messages. Each scenario isolates its cause: a PATH with the usual tools minus the one
it wants to be missing, so a scenario about a missing compiler does not
also break the validators. No assertion can pass in the void: if the
verifier does not return JSON, or the self-tests did not run, the battery
says so instead of taking it for a pass. It also checks that the exit code
and the code reported in the JSON always agree:

A `.luau` that only uses Luau syntax is not an error: type annotations are
stripped first (the shared normaliser mangles them) and the rest is
normalised with the shared `noctalia_api` module and compiled again. If it
still does not compile, but the file has type annotations, it is reported
as a warning (not a failure): it may be Luau syntax the normaliser does
not cover yet.

For this plugin that ambiguity does not exist: the self-test checks that
every `.luau` compiles as it is, so a syntax error is always unambiguous
and is caught statically (and by the self-test too, so there are two
independent ways of noticing it).

The verifier always states what it could and could not check: how many
`.luau` compiled, how many only use Luau syntax, how many are inconclusive,
and it fails (instead of passing) when a check could not be run at all
(missing validator, missing compiler, missing log, Noctalia not
responding). A file that cannot be read (invalid UTF-8) is reported, not
skipped, and the verifier never dies with a traceback: if something
escapes, it says so and exits with an error.

The runtime part is checked too: the panel is opened and closed, the
widget is asked to open it, and a setting is written through the widget.
Every step is checked: the answer must be `dispatched 1`, otherwise the
event was lost and the step did not happen — and even a delivered event
is not enough, so the overrides file is checked too: if the helper fails,
the event is delivered and nothing is written. The write goes through the
widget because it is always instantiated, while the panel entry only
exists while the panel is open and takes a few seconds to be ready (sending
the event too early loses it without a trace).

If the panel has pending changes (the overrides file exists), the verifier
does not write anything: it would overwrite them. It says so instead.

Two more cases are reported instead of being passed over: if the log was
rotated while the verification was running (nothing could be reviewed) and
if the deployed copy is out of date (its self-test is missing).

```sh
python3 ~/.local/share/noctalia/plugins/lyrics-carousel/tools/check-verifier.py
```

## Notes

- The window is opened with `hl.dsp.exec_cmd(...)` and the class
  `noctalia-lyrics-carousel`; the script can also be run by hand as `lyrics-carousel`.
- The panel starts the script by its absolute path (`python3 <plugin>/bin/lyrics-carousel`),
  so it does not depend on the `PATH` nor on the executable bit.
- Outside kitty (or without Pillow) the script falls back to text mode on its own,
  and it says so in `~/.cache/lyrics-carousel/debug.log` instead of doing it silently.
- The accent colour is read from the theme Noctalia generates for kitty, so it follows
  the wallpaper.
- Kitty only accepts monospaced fonts, so in text mode the usable list is
  `Departure Mono`, `Press Start 2P`, `Space Mono`, `NType 82 Mono`, `Lettera Mono LL`
  and `IBM Plex Mono`. Image mode accepts any font.
- The plugin makes network requests to the lyrics providers; nothing else leaves the
  machine.
