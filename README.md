# Noctalia plugins

Personal plugin source for [Noctalia](https://github.com/noctalia-dev/noctalia). Every
top-level directory is a self-contained Noctalia plugin, laid out exactly like the
[community plugin repository](https://github.com/noctalia-dev/community-plugins), so each
one can be contributed with a single pull request.

| Plugin | Id | What it does |
| --- | --- | --- |
| [floating-term](floating-term/) | `faminec/floating-term` | Launches terminal apps in floating windows with a per-command size, anchor and position. |
| [equalizer](equalizer/) | `faminec/equalizer` | A 10-band graphic equalizer with preamp, bypass and presets on top of EasyEffects. |
| [wallpaper-carousel](wallpaper-carousel/) | `faminec/wallpaper-carousel` | A full-screen wallpaper carousel with vertical cards and a parallax crop. |
| [notes](notes/) | `faminec/notes` | Quick text notes in a side panel, with live sync from outside the panel. |
| [cmf-buds](cmf-buds/) | `faminec/cmf-buds` | Native control of the Nothing CMF Buds Pro 2 over RFCOMM: ANC, EQ, gestures, spatial audio. |
| [lyrics-carousel](lyrics-carousel/) | `faminec/lyrics-carousel` | Synced lyrics rendered in a floating terminal window. |
| [notes-sync](notes-sync/) | `faminec/notes-sync` | Bridge between the notes panel and the phone: status, push messages and a stable IPC contract. |

Every plugin passes the official validator
(`python3 .github/workflows/scripts/validate-plugins.py` in the community repository) and the
Luau checker in `tools/`, which finds globals that are read but never written:

```sh
python3 tools/check-luau-globals.py .
```

That check matters because in Luau a `local function` only exists from its own
declaration onwards: if a function defined earlier calls it, the reference
resolves to a global that is never assigned, and the call fails at runtime with
*attempt to call a nil value*. Declare such functions as locals at the top of
the file (`local render` + `render = function() ... end`).

The state of each plugin and the **testing checklist** live in
[PLUGINS.md](PLUGINS.md).

## Install from this repository

Add the checkout as a plugin source and enable the plugins you want:

```sh
noctalia msg plugins source add dev path ~/noctalia-plugins
noctalia msg plugins enable faminec/floating-term
noctalia msg plugins enable faminec/equalizer
noctalia msg plugins enable faminec/wallpaper-carousel
noctalia msg plugins enable faminec/notes
noctalia msg plugins enable faminec/cmf-buds
noctalia msg plugins enable faminec/lyrics-carousel
noctalia msg plugins enable faminec/notes-sync
```

## Contributing a plugin upstream

The community repository expects **one plugin per pull request**, so open one PR per
directory:

1. Fork `noctalia-dev/community-plugins`.
2. Create a branch that contains only one plugin directory, for example
   `git checkout -b feat/wallpaper-carousel`.
3. Copy the plugin directory (manifest, scripts, `README.md`, `thumbnail.webp` and
   `translations/en.json`) into the fork.
4. Open the pull request against `main` and fill in the template.

The plugin `id` must be `<author>/<plugin>` and the directory name must match the part
after the `/`. `version` follows semver and is bumped on every change, `plugin_api` is
the oldest API level the plugin needs, and `description` is limited to 120
characters. `translations/en.json` is the only translation file that has to be shipped;
other locales are handled by the Noctalia translation platform.

## Layout

```
floating-term/
  plugin.toml            # manifest: id, metadata, entries, settings
  panel.luau             # panel entry
  widget.luau            # bar widget entry
  bin/                   # optional non-UI helpers
  README.md              # the plugin's public page
  thumbnail.webp         # 960×540 store card
  translations/en.json   # every label_key and description_key
```

## License

MIT — see [LICENSE](LICENSE).
