# Floating Term

Launch terminal apps in floating windows with a per-command size, anchor and position, so
`cava` can open at the bottom center, `unimatrix` on the right and `lavat` on the left
without covering each other.

## Plugin

| Field | Value |
| --- | --- |
| ID | `faminec/floating-term` |
| Entries | Bar widget: `launcher`; panel: `panel` |

## Requirements

The following executables must be installed and available on `PATH`:

- `kitty` — the default terminal the plugin launches.
- `hyprland` — the compositor; the plugin uses the Hyprland 0.56 Lua API to float and
  place every window.
- `playerctl` — only needed by the bundled `lyrics` command.

The default command set also expects `cava`, `cbonsai`, `unimatrix`, `pipes.sh`, `lavat`
and `btop`. Every entry is editable, so any of them can be replaced or removed.

## Usage

Add the `launcher` widget from Noctalia's widget picker. Clicking it opens the launcher
panel, where every configured command is a row. Clicking a row starts the command in a
floating terminal window.

The panel can also be opened directly:

```sh
noctalia msg panel-toggle faminec/floating-term:panel
```

A specific command can be launched through IPC:

```sh
noctalia msg plugin faminec/floating-term:panel all launch cava
```

Each terminal gets its own class (`noctalia-term-<name>`) and is started with a Hyprland
execution rule:

```lua
hl.dsp.exec_cmd("<terminal> ...", { float = true, move = { x, y }, size = { w, h } })
```

If the command's window is already open, the plugin focuses it and re-applies its
geometry instead of opening a second window.

### The lyrics carousel

`bin/lyrics-carousel` is a small self-contained widget shipped with the plugin. It reads
the active MPRIS player with `playerctl`, looks the current lyrics up (LRCLIB, NetEase,
and the Noctalia Lyrics plugin adapter when it is installed) and shows them in a vertical
carousel with the active line highlighted character by character.

Shortcuts inside the widget: `q` quits, `space` pauses, `d` reverses the scroll
direction, `k` toggles the karaoke effect and `r` searches for the lyrics again.

## Settings

Configure the plugin in **Settings → Plugins → Floating Term** (the gear button in the
panel opens the same page).

| Setting | Type | Default | Description |
| --- | --- | --- | --- |
| `commands` | `string_map` | `cava`, `cbonsai`, `unimatrix`, `pipes`, `lavat`, `btop`, `lyrics` | Name = shell command. Every entry becomes a row in the panel. |
| `layouts` | `string_map` | see below | Size, anchor and optional offset for every command. |
| `fonts` | `string_map` | `lyrics = Departure Mono, 22` | Font per command (`kitty` only), written as `Family, size`. |
| `margin` | `int` | `16` | Margin in pixels from the monitor edges for anchored layouts. |
| `output` | `string` | empty | Monitor connector the windows open on (for example `DP-1`). Empty = focused monitor. |
| `reuse_existing` | `bool` | `true` | Focus the existing window instead of opening another one. |
| `terminal` | `string` | `kitty` | Terminal command used to launch the apps. |
| `width` | `int` | `900` | Fallback width for commands without a `layouts` entry. |
| `height` | `int` | `520` | Fallback height for commands without a `layouts` entry. |
| `x` | `int` | `120` | Fallback X position (monitor coordinates). |
| `y` | `int` | `140` | Fallback Y position (monitor coordinates). |
| `glyph` | `glyph` | `terminal-2` | Bar icon. |
| `close_on_launch` | `bool` | `true` | Close the panel as soon as a command is launched. |

### Layout format

```toml
[plugin_settings."faminec/floating-term".layouts]
cava      = "bottom-center, 1610x584"
cbonsai   = "top-center, 801x582"
unimatrix = "right-center, 869x1424"
pipes     = "bottom-right, 900x520"
btop      = "top-left, 928x800"
lavat     = "bottom-left, 802x582"
lyrics    = "center, 1200x820"
```

Anchors: `top-left`, `top-center`, `top-right`, `left-center`, `center`,
`right-center`, `bottom-left`, `bottom-center`, `bottom-right`. Short aliases such as
`top`, `bottom`, `left`, `right` and `middle` are accepted too.

The size is optional (`width`/`height` are used when it is missing) and so is the
offset:

```toml
# Bottom center, shifted 40 px right and 10 px up.
cava = "bottom-center, 1610x584, 40, -10"

# Absolute monitor coordinates.
lavat = "custom, 802x582, 1753, 258"

# The same, written as key = value.
btop = "x=8 y=8 w=928 h=800"
```

## IPC

```sh
noctalia msg panel-toggle faminec/floating-term:panel
noctalia msg plugin faminec/floating-term:panel all launch <command>
noctalia msg plugin faminec/floating-term:panel all refresh
```

## Notes

- The geometry uses the Hyprland 0.56 Lua API (`hl.dsp.exec_cmd`), so no
  `windowrules.lua` change is needed.
- The size is re-applied shortly after the window is created, because the
  `persistent_size` rule in `windowrules.lua` restores the remembered size of the class
  and can override the requested one.
- Outside Hyprland the plugin falls back to `noctalia.runInTerminal(command)`, without
  geometry.
- `kitty` is started with `-o confirm_os_window_close=0` so closing the window does not
  show a confirmation dialog.
- The `fonts` setting is only applied when the terminal is `kitty`; it is translated to
  `-o font_family=... -o font_size=...`.
- The `lyrics` command makes network requests to the lyrics providers; every other
  command is fully local.
