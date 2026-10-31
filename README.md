# Noctalia plugins

Plugins for [Noctalia](https://github.com/noctalia-dev/noctalia), the Hyprland shell. Each
plugin lives in its own top-level directory, laid out exactly like the
[community plugin repository](https://github.com/noctalia-dev/community-plugins), so it can be
contributed there with a single pull request.

| Plugin | Id | What it does |
| --- | --- | --- |
| [terminal-widgets](terminal-widgets/) | `faminec/terminal-widgets` | Launches terminal apps in floating windows: one card per command, with a preview of the window and its own size and position. |

![The Terminal Widgets panel](terminal-widgets/screenshots/panel.webp)

## Install

Add this repository as a plugin source and enable the plugin:

```sh
noctalia msg plugins source add dev path https://github.com/F4M1N3C/noctalia-plugins
noctalia msg plugins enable faminec/terminal-widgets
```

Then add the **launcher** widget from Noctalia's widget picker, or open the panel directly:

```sh
noctalia msg panel-toggle faminec/terminal-widgets:panel
```

The [plugin README](terminal-widgets/README.md) is the full documentation: every setting, the
layout format, the IPC commands and how to run the tests.

## Requirements

- **Noctalia** with plugin API 43 or newer.
- **Hyprland** 0.56 or newer: the plugin uses the Hyprland Lua API to float and place the
  windows, so no `windowrules.lua` change is needed.
- **kitty** (or any other terminal, configurable in the settings).
- **hyprctl** (it comes with the `hyprland` package): it lists, moves, resizes, focuses and
  closes the windows.
- **grim** and **python3** with Pillow, only for the card previews. Without them the cards
  fall back to a static preview and everything else keeps working.

## Development

The tests live with the plugin and need no desktop:

```sh
lua5.4 terminal-widgets/test-panel.lua          # unit tests
lua5.4 terminal-widgets/test-panel.lua /path/to/another/copy   # run them against another copy
./terminal-widgets/test-smoke.sh                 # live check: open all → rotate → close all
```

The repository also carries the checks the CI runs:

```sh
./tools/validate-community.sh terminal-widgets   # the official community validator
python3 tools/check-locals.py terminal-widgets   # locals used before they are declared
python3 tools/check-luau-globals.py terminal-widgets  # globals read but never written
```

Those two Luau checkers matter because in Luau a `local` only exists from its own declaration
onwards: if a function defined earlier calls it, the reference resolves to a global that is
never assigned and the call fails at runtime with *attempt to call a nil value*.

## License

[MIT](LICENSE)
