# Term Deck

A launcher for terminal apps that live in floating windows. Every command gets its own
card, its own size and anchor, and the whole set can be re-arranged with one click.

## Plugin

| Field | Value |
| --- | --- |
| ID | `faminec/floating-term` |
| Entries | Bar widget: `launcher`; panel: `panel` |

## Requirements

The following executables must be installed and available on `PATH`:

- `kitty` — the terminal the plugin launches.
- `hyprland` — the compositor; the plugin uses the Hyprland 0.56 Lua API to float and
  place every window.
- `grim` — optional, used to take the preview screenshot of an open window.
- `python3` with `python-pillow` — optional, used to crop those screenshots.

## Usage

Add the `launcher` widget from Noctalia's widget picker. Clicking it opens the deck: one
card per command, with a live preview of the window when it is already open. Clicking a
card launches the command in a floating terminal window.

The panel can also be opened directly:

```sh
noctalia msg panel-toggle faminec/floating-term:panel
```

### Opening and re-arranging everything

The **grid button** in the panel header opens every configured command at once. When all
of them are already open, the same button rotates them: each window takes the slot of
the next one, so the set can be re-arranged with a single click. The rotation direction
is configurable (clockwise, counterclockwise, opposite, pairs or shuffle) and it can
also swap the sizes between the windows.

Each terminal is started with its own class (`noctalia-term-<name>`) and a Hyprland
execution rule:

```lua
hl.dsp.exec_cmd("<terminal> ...", { float = true, move = { x, y }, size = { w, h } })
```

If a command is already open, the plugin focuses it and re-applies its geometry instead
of opening a second window. When two windows would land on the same area, the plugin
moves the new one to the closest free slot.

## Settings

Configure the plugin in **Settings → Plugins → Term Deck** (the gear button in the panel
opens the same page).

| Setting | Type | Default | Description |
| --- | --- | --- | --- |
| `commands` | `string_map` | `cava`, `cbonsai`, `unimatrix`, `pipes`, `lavat`, `btop` | Name = shell command. Every entry becomes a card. |
| `layouts` | `string_map` | see below | Size, anchor and optional offset for every command. |
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
| `rotation` | `select` | `clockwise` | How the windows are rotated: `clockwise`, `counterclockwise`, `opposite`, `pairs` or `shuffle`. |
| `rotation_sizes` | `bool` | `false` | Swap the sizes between the windows when rotating. |
| `columns` | `int` | `2` | Columns of the card grid (1 to 3). |
| `card_preview` | `select` | `auto` | Card preview: `auto` (screenshot when possible), `screenshot` or `mock`. |
| `avoid_collisions` | `bool` | `true` | Move a window to the closest free slot when its layout collides with another one. |

### Layout format

```toml
[plugin_settings."faminec/floating-term".layouts]
cava      = "bottom-center, 1610x584"
cbonsai   = "top-center, 801x582"
unimatrix = "right-center, 869x1424"
pipes     = "bottom-right, 900x520"
btop      = "top-left, 928x800"
lavat     = "bottom-left, 802x582"
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
noctalia msg plugin faminec/floating-term:panel all open-all
noctalia msg plugin faminec/floating-term:panel all rotate
noctalia msg plugin faminec/floating-term:panel all close-all
noctalia msg plugin faminec/floating-term:panel all refresh
```

The panel entry is only reachable over IPC while the panel is open; the other session's
runtime is created on demand.

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
- The list of commands is merged at runtime: the manifest defaults, whatever is set in
  the plugin settings and whatever is edited in the panel. Adding a command in the
  settings never removes the others, and the defaults can be removed from the panel.
- The card previews take a screenshot of the window area with `grim` and crop it with
  Pillow. `grim` does not accept an output and a geometry at the same time, so the
  helper captures the whole output and crops it itself.
- The plugin spawns `kitty`, `hyprctl` and (for the previews) `grim`; it makes no network
  requests.
