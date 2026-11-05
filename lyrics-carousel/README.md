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
- `hyprland` — the compositor; the window is opened with the Hyprland 0.57 Lua API.
- `playerctl` — reads the active MPRIS player.
- `python3` with `python-pillow` — draws the lyrics in image mode.

The lyrics themselves come from the Noctalia Lyrics plugin's source adapter
(`lyric_sources.py`), so the same providers and the same configuration are reused:
LRCLIB, NetEase, SPlayer, QQ Music, Kugou and, with credentials, Spotify, Apple Music
or Musixmatch.

## Usage

Add the `widget` bar icon and click it to open the lyrics window. The panel opens
attached to the widget and holds every setting of the plugin.

The panel can also be opened directly:

```sh
noctalia msg panel-toggle faminec/lyrics-carousel:panel
```

### Two rendering modes

| Mode | What it uses | Advantages | Trade-offs |
| --- | --- | --- | --- |
| `image` (default) | Pillow and the kitty graphics protocol | The active line is drawn larger, the scroll is pixel-accurate and any font works | Needs kitty and Pillow; the text cannot be selected |
| `text` | The terminal itself | Lightweight and crisp, the text is selectable | One font size for the whole window |

In image mode the window is drawn as a transparent PNG the size of the window
(1200×820 px by default), so the desktop wallpaper stays visible through it.

The providers are queried in parallel and the first one to answer wins. The search
waits up to 15 seconds, so a slow provider is not thrown away; if nobody has answered
by then, the lookup is retried a minute later. The result is cached in
`~/.cache/lyrics-carousel`.

### Keyboard shortcuts

| Key | Action |
| --- | --- |
| `q` | Quit |
| `space` | Pause / resume |
| `d` | Reverse the scroll direction |
| `k` | Toggle the karaoke effect |
| `r` | Look the lyrics up again |

`d` and `k` write their value to `settings.toml`, so the change survives a restart
and shows up in the settings page. Writing that file makes Noctalia reload the
configuration, so a panel that happened to be open at that moment is closed.

## Settings

Configure the plugin in **Settings → Plugins → Lyrics Carousel** or from the panel.
The panel mirrors all the settings of the manifest — including the custom accent
colour, the line spacing, the transition and offset times, and the bar icon — with the
same `min`/`max`/`step` ranges. It keeps its own changes in a small overrides file and
pours them into `settings.toml` when it is closed, so the settings page and the panel
always end up showing the same values without the panel closing under the user's
fingers. The script re-reads the settings every 0.5 s, so changes apply live to a
window that is already open.

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
| `anchor` | `select` | `center` | Window anchor: `center`, `top-left`, `bottom-right`… or `custom` (uses custom_x/custom_y). |
| `custom_x` | `int` | `100` | Custom horizontal position (only with anchor = custom). |
| `custom_y` | `int` | `100` | Custom vertical position (only with anchor = custom). |
| `accent` | `select` | `primary` | Colour of the active line: `primary` (follows the wallpaper), an ANSI colour or `custom`. |
| `custom_color` | `string` | `#e46767` | Hex colour used when `accent = custom`. |
| `active_scale` | `double` | `1.35` | Size multiplier of the line being sung (image and text mode). In text mode it is drawn with kitty's text sizing protocol (`OSC 66`), which can only draw a few sizes: the line is drawn at `s × n/d`, the closest one to the factor, and it takes two rows of the grid. |
| `visible_above` | `int` | `6` | Lines visible above the active one. |
| `visible_below` | `int` | `6` | Lines visible below the active one. |
| `language` | `select` | `auto` | Language of the texts inside the window: `auto` (the system language), `en` or `es`. |
| `glyph` | `glyph` | `music` | Bar icon. |

The position and the size are applied live to the running window, without recreating
it. In image mode the font family and the font size also apply live (the font cache
is invalidated on change); in text mode kitty fixes both when the window opens, so
the window has to be opened again for them to change.

## Changelog

### 2.1.0

- The panel is rebuilt around the settings that change the look of the window: one
  font dropdown (with the fonts kitty accepts and an option to type any other),
  the nine anchor positions of the window as a 3×3 grid with their names, the
  accent colours as a palette of chips, and the colour, the bar icon and the
  visualiser in their own sections. The custom colour only shows up when the
  accent is `custom`, and the visualiser is replaced by a note when the header
  is on.
- The active line is drawn at the right size in text mode: it uses kitty's text
  sizing protocol with the metadata that kitty understands (`s × n/d`), so the
  factor is applied instead of being drawn at 20% of its size, and the text is
  split into the blocks that kitty needs to keep the characters together.
- The window uses the real size of the terminal. It used to assume a minimum of
  30×12 cells, which made every row overflow and the lyrics break apart in
  windows with a large font.
- The panel now exposes every setting of the manifest: `spacing`, `animation_ms`,
  `offset_ms`, `custom_color` and `glyph` are no longer settings-page only.
- Numeric controls use sliders with the manifest ranges (`font_size`, `active_scale`,
  `visible_above`, `visible_below`) and clamp every value, including the ones received
  over IPC: a window can no longer be wider or taller than the screen.
- The panel opens `attached` to the widget, next to the click, instead of floating in
  the centre of the screen.
- The panel no longer redraws itself after it has been closed, reports a failed merge
  instead of losing the changes silently, and applies size changes received over IPC
  to the window that is already open.
- A track with an artist but no title no longer restarts the lyric search on every
  poll.
- Slow source adapters get 22 seconds instead of 3, so NetEase and QQ Music are not
  killed in the middle of an answer.
- Estimated times never overwrite real LRC times, and lines without a time no longer
  break the highlight order: they keep their place in the song instead of starting
  to sing six seconds in, and they never end up outside the song (including the
  lines before the first real timestamp or after the last one).
- Image mode is not re-armed by an unrelated settings reload after the script
  disables it for repeated failures: only an explicit change back to `image`
  turns it on again.
- The settings helper validates formats as well as ranges, so a malformed
  `glyph`, `custom_color` or an empty `font_family` cannot be written through
  any entry point, not just the panel and the widget IPC.
- The karaoke fill ends at the next real timestamp, not at the next line of the list
  (lines without a time are not timestamps and used to cut the fill short).
- A failed image renderer stays disabled instead of re-arming on every settings
  reload, and it can be switched on again on request.
- `[hh:mm:ss]`, three-digit minutes and up to six decimals are accepted in LRC files,
  text between angle brackets (`I <3 you`) is preserved, only the winning provider
  writes the cache, and the lyrics settings and adapter are found under
  `NOCTALIA_STATE_HOME` / `XDG_STATE_HOME`.
- The window is always clipped to the monitor, also when it is resized over IPC.
- The font family can be typed by hand (the manifest declares it as free text), and
  the bar icon and the custom colour are validated before they are saved — on every
  write path, including the IPC of the widget.
- The value ranges are read from the manifest even on Python versions without
  `tomllib`, so the clamping never disappears silently.

### 2.0.0

- The panel's switches really turn on and off: Noctalia hands the value over as the
  string `"true"`, which was never equal to `true`.
- The window position dropdown was one position off and saved the previous anchor;
  it now offers the ten anchors of the manifest.
- The width and height steppers no longer change the value when the mouse merely
  passes over them.
- `offset_ms` is applied to the scroll as well as to the highlight, so the line in
  the middle is the one that is being sung.
- The lyric lookup waits 15 seconds instead of 4 and no longer marks a song as
  "no lyrics" while a provider is still answering; an empty result is retried every
  minute.
- The sound visualiser keeps its own row instead of drawing over the lyrics.
- The texts of the window are in English and Spanish (`--lang`, or the `language`
  setting; `auto` follows the system language).
- `d` and `k` are saved in `settings.toml`, so they survive a restart.
- The settings, the overrides and the data directory follow `NOCTALIA_STATE_HOME`
  and `XDG_STATE_HOME`, like Noctalia itself.
- The window position is a dropdown in the settings page as well, and the panel can
  empty the cache of lyrics.

## IPC

The panel is opened with:

```sh
noctalia msg panel-toggle faminec/lyrics-carousel:panel
```

Both entries also accept messages, which is handy for keyboard shortcuts:

```sh
noctalia msg plugin faminec/lyrics-carousel:panel all launch
noctalia msg plugin faminec/lyrics-carousel:panel all toggle karaoke
noctalia msg plugin faminec/lyrics-carousel:panel all set font_size 26 int
noctalia msg plugin faminec/lyrics-carousel:panel all refresh

noctalia msg plugin faminec/lyrics-carousel:widget all launch
noctalia msg plugin faminec/lyrics-carousel:widget all toggle karaoke
noctalia msg plugin faminec/lyrics-carousel:widget all set font_size 26 int
noctalia msg plugin faminec/lyrics-carousel:widget all refresh
```

| Event | `panel` | `widget` |
| --- | --- | --- |
| `launch` | Opens the lyrics window (starts the script). | Toggles the panel. |
| `toggle <key>` | Flips a switch. | Flips a switch. |
| `set <key> <value> [type]` | Sets a setting. | Sets a setting. |
| `refresh` | Re-reads the settings and the track, and redraws the panel. | Redraws the bar icon. |

`toggle` only works with the switches — `marker`, `karaoke`, `equalizer`, `footer`,
`hints`, `header` and `ghost` — because flipping a number makes no sense.

The value of `set` can also be written as `key=value`. Its type (`bool`, `int`,
`float` or `string`) is optional: without it, the type is deduced from the setting,
so `set karaoke true` stores a boolean and not the string `"true"`.

```sh
noctalia msg plugin faminec/lyrics-carousel:widget all set font_size 26 int
noctalia msg plugin faminec/lyrics-carousel:widget all set font_family="Departure Mono"
```

`set` and `toggle` write to the same overrides file the panel uses, so the change is
poured into `settings.toml` when the panel is closed and is visible in the settings
page afterwards.

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
toggle the direction and the karaoke and save them in the `settings.toml`. It
also checks that the demo mode does not ask any lyrics provider for anything —
and that the script's debug log is actually being written, so that check is not
vacuous.

The self-test never touches the real state: it runs the script with a temporary
`HOME`, `XDG_STATE_HOME` and `XDG_CACHE_HOME`, so the settings file, the
overrides and the cache of lyrics are all written in a throwaway directory. The
overrides file can also be redirected on its own with the
`LYRICS_CAROUSEL_OVERRIDES` environment variable (the script and the helper both
honour it). That also avoids a race: the script writes asynchronously, so a write
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
