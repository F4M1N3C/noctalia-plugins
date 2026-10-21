# CMF Buds

Native control of the **Nothing CMF Buds Pro 2** (model `B172`) from the Noctalia bar,
without the Nothing X mobile app. The plugin talks the vendor's **RFCOMM** protocol
through a small Python daemon and exposes everything the earbuds can change: noise
cancellation, volume, equalizer, Ultra Bass, case-dial gestures, spatial audio, in-ear
detection, low-latency mode, multipoint, battery, "ring my buds" and the ear-fit test.

## Plugin

| Field | Value |
| --- | --- |
| ID | `faminec/cmf-buds` |
| Entries | Bar widget: `widget`; panels: `panel-sound`, `panel-controls`, `panel-actions`, `panel-system`; service: `service` |

## Requirements

The following executables must be installed and available on `PATH`:

- `python3` — runs the RFCOMM daemon and its client.
- `bluetoothctl` — device discovery over BlueZ.
- `pactl` — system volume on the headphone's PipeWire sink.

Hardware and system requirements:

- The earbuds must already be paired with BlueZ and connected over Bluetooth audio.
- You must be in the `input` group to read `/dev/input/event*` for the local shortcut
  macros.
- The Nothing X app on your phone keeps the RFCOMM channel busy; close it before using
  the panel, otherwise the daemon cannot connect.

Enable the plugin with:

```sh
noctalia msg plugins enable faminec/cmf-buds
```

## Usage

Add the `widget` entry to a bar, then click it to open the control panel (it reopens the
last tab you used).

```sh
noctalia msg panel-toggle faminec/cmf-buds:panel-sound
noctalia msg panel-toggle faminec/cmf-buds:panel-controls
noctalia msg panel-toggle faminec/cmf-buds:panel-actions
noctalia msg panel-toggle faminec/cmf-buds:panel-system
```

| Panel | Size | Contents |
| --- | --- | --- |
| `panel-sound` | 600×910 | ANC (off / transparency / cancellation plus adaptive, high, mid, low levels), system volume and the EQ (Balanced, Rock, Electronic, Pop, Vocals, Classical and a custom bass/mid/treble curve from -6 to +6, plus five Ultra Bass levels) |
| `panel-controls` | 600×560 | Touch gestures for each bud and for the case (single, double, triple, hold, double hold, dial) and a per-bud "ring my buds" button |
| `panel-actions` | 600×1010 | Local shortcut macros: which shell command runs when the case dial is turned |
| `panel-system` | 600×930 | Spatial audio, in-ear detection, low latency, dual connection, ear-fit test, device information and reconnect |

Switching tabs closes the current panel and opens the new one, so the window resizes to
match the section.

### Widget gestures

| Gesture | Effect |
| --- | --- |
| Click | Open the control panel |
| Scroll | Volume up/down by `volume_step` percent |
| Right click | Cycle the ANC mode (off → transparency → cancellation) |
| Hover | Tooltip with connection, ANC, battery, EQ and volume |

### Local shortcut macros

The earbuds do not store commands: their firmware only accepts a fixed set of actions
(play, next, volume, ANC, …). What reaches the PC is the resulting *action*, not the raw
press, so the macros are built on the PC side:

1. The case dial is mapped to the volume-control action, so turning it changes the
   volume of the headphone sink. That change is the signal.
2. The daemon watches the sink with `pactl subscribe` and detects it.
3. Modifiers (SUPER, CTRL, ALT, SHIFT) are read from `/dev/input/event*`, so
   "SUPER + dial" is distinguishable from a plain "dial".
4. When a rule matches, the command runs; if `restore` is enabled the volume is put
   back so the dial does not change it when it is acting as a shortcut.

Two rules ship by default: **dial up + SUPER** goes to the next workspace and
**dial down + SUPER** to the previous one. Without SUPER the dial keeps behaving like
a volume knob.

## Settings

Settings live in *Settings → Plugins → CMF Buds*.

| Setting | Type | Default | Description |
| --- | --- | --- | --- |
| `device_name` | `string` | `CMF Buds Pro 2` | Bluetooth name to look for. |
| `device_mac` | `string` | *(empty)* | Pin the MAC address when several headsets are around. |
| `glyph` | `glyph` | `headphones` | Bar widget icon. |
| `volume_step` | `int` | `5` | Percent changed per scroll step (1–25). |
| `poll_seconds` | `int` | `60` | How often the device state is polled (20–300). |

## Notes

- `service` starts `bin/budsctl.py daemon` (a persistent daemon guarded by `flock` with
  a Unix socket and a `state.json`) and pings it every 20 seconds.
- The daemon speaks RFCOMM over the device's SDP channel 15, frames commands with the
  `[0x55, 0x60, 0x01, cmd, len, fsn]` header and a CRC16-ARC, and publishes the state to
  `state.json`.
- `widget` and the panels read that state and send commands through the socket, so the UI
  never blocks.
- Volume is changed on the device's PipeWire sink (`bluez_output.<MAC>.1`).
- State is persisted under `~/.local/state/noctalia/plugins/data/faminec/cmf-buds/`:
  `state.json`, `local_actions.json`, `daemon.sock`, `daemon.sock.lock` and `daemon.log`.
- The `fonts/` directory ships Doto and Space Grotesk with their OFL licences.

### Protocol credits

- [SoaOaoS/something-x](https://github.com/SoaOaoS/something-x) — the desktop Nothing X
  app, the base of the reverse engineering work.
- [maniacx/BudsLink](https://github.com/maniacx/BudsLink) — reference implementation of
  the Nothing earbud RFCOMM commands.

### Limitations

- The RFCOMM channel is busy while the Nothing X app is connected to the same device.
- There is no firmware update support.
- Some devices only report the battery of one side, or none; the UI shows `—`.
- The case dial does not expose the "double hold" action.
- Nothing X on the phone still overrides the settings while it is connected.
