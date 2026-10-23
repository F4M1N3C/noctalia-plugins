# ntime

Timer and clock plugin for Noctalia with multiple modes and font selection.

## Plugin

| Field | Value |
| --- | --- |
| ID | `faminec/ntime` |
| Entries | Widget: `widget`; Panel: `panel`; Service: `service` |

## Usage

Add the `widget` bar icon to display the timer/clock. Click the widget to cycle through modes (clock → countdown → countup → clock). Open the panel for full configuration:

```sh
noctalia msg panel-toggle faminec/ntime:panel
```

The panel allows:
- Switching between modes: Clock, Countdown, Countup
- Selecting fonts: tty-clock (retro squares), Digital, Blocks
- Adjusting the countdown timer via mouse scroll
- Setting the timer duration

## Modes

- **Clock**: Shows the current system time (HH:MM:SS).
- **Countdown**: Configurable countdown timer. Starts with the duration set in settings.
- **Countup**: Continuous count-up timer from start time.

## Settings

| Setting | Type | Default | Description |
| --- | --- | --- | --- |
| `mode` | `select` | `clock` | Timer mode: clock, countdown, or countup. |
| `font` | `select` | `tty-clock` | Display font: tty-clock, digital, or blocks. |
| `duration` | `int` | `25` | Default duration for countdown mode (minutes). |

## Requirements

The following executables must be installed and available on `PATH`:

- `noctalia` — Noctalia terminal client.
- `kitty` — (optional) For the floating terminal display.
- `python3` — Used by the plugin internals.

## IPC

```sh
noctalia msg panel-toggle faminec/ntime:panel
```

Panel-specific IPC commands:

- `noctalia msg panel-toggle faminec/ntime:panel` — Open/close the ntime panel.
- `noctalia msg ipc faminec/ntime:panel set_mode clock` — Set mode to clock.
- `noctalia msg ipc faminec/ntime:panel set_mode countdown` — Set mode to countdown.
- `noctalia msg ipc faminec/ntime:panel set_mode countup` — Set mode to countup.
- `noctalia msg ipc faminec/ntime:panel set_font tty-clock` — Set font to tty-clock.
- `noctalia msg ipc faminec/ntime:panel set_font digital` — Set font to digital.
- `noctalia msg ipc faminec/ntime:panel set_font blocks` — Set font to blocks.
- `noctalia msg ipc faminec/ntime:panel adjust_timer 5` — Adjust countdown timer by +5 minutes.
- `noctalia msg ipc faminec/ntime:panel adjust_timer -3` — Adjust countdown timer by -3 minutes.