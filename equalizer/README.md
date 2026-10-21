# Equalizer

A 10-band graphic equalizer for Noctalia, built on top of EasyEffects, with a preamp, a
bypass switch and a few presets.

## Plugin

| Field | Value |
| --- | --- |
| ID | `faminec/equalizer` |
| Entries | Bar widget: `widget`; panel: `panel`; service: `service` |

## Requirements

The following executables must be installed and available on `PATH`:

- `easyeffects` — the host of the equalizer. The service starts it hidden if it is not
  running yet.
- `python3` — used by `bin/eqctl`, the helper that talks to the EasyEffects socket.

EasyEffects must be reachable through `$XDG_RUNTIME_DIR/EasyEffectsServer`. The plugin
creates the `Noctalia EQ` preset in `~/.local/share/easyeffects/output/` when it is
missing.

## Usage

Add the `widget` bar icon and click it to open the equalizer panel. The panel shows the
ten bands (31, 62, 125, 250, 500, 1k, 2k, 4k, 8k and 16k Hz), the preamp
(-12 dB to +12 dB), a bypass switch and the presets.

The panel can also be opened directly:

```sh
noctalia msg panel-toggle faminec/equalizer:panel
```

The `service` entry makes sure EasyEffects is running and the preset is loaded when the
session starts.

The helper can also be used on its own:

```sh
EQ=bin/eqctl

python3 "$EQ" status
python3 "$EQ" ensure
python3 "$EQ" set-band 0 3.5        # band 0 (31 Hz) to +3.5 dB
python3 "$EQ" set-preamp -2.0
python3 "$EQ" bypass 1              # 1 = bypass, 0 = active
python3 "$EQ" apply --bands 0,0,0,0,0,0,0,0,0,0 --preamp 0
python3 "$EQ" reset
python3 "$EQ" open                  # opens the EasyEffects window
```

## Settings

Configure the plugin in **Settings → Plugins → Equalizer**.

| Setting | Type | Default | Description |
| --- | --- | --- | --- |
| `pipeline` | `select` | `output` | `output` applies the equalizer to playback, `input` to the microphone. |
| `preset` | `string` | `Noctalia EQ` | EasyEffects preset that holds the equalizer. It is created automatically when missing. |
| `glyph` | `glyph` | `adjustments-horizontal` | Bar icon. |

## IPC

```sh
noctalia msg panel-toggle faminec/equalizer:panel
```

## Notes

- The active preset is stored in the EasyEffects JSON preset file, and the panel state in
  `~/.local/state/noctalia/plugins/data/faminec/equalizer/state.json`.
- When the panel opens it reloads `Noctalia EQ` if EasyEffects has another preset
  loaded, so the sliders always control the expected equalizer.
- If EasyEffects is used for other things, change the preset name in the plugin
  settings.
- The plugin only talks to EasyEffects through its local socket; it makes no network
  requests.
