# Notes Sync

Bridge between the Noctalia notes panel and your phone. It watches the
`notes-mobile` server, shows its status in the bar, and lets you push the
open note to the phone. It also exposes a small, stable IPC contract so other
tools can drive the notes panel.

This is the companion of the `faminec/notes` plugin: that one owns the notes,
this one owns the connection.

## Plugin

| Field | Value |
| --- | --- |
| ID | `faminec/notes-sync` |
| Entries | Panel: `panel`; service: `service`; bar widget: `widget` |

## Requirements

- The `notes-mobile` server running (see `~/notes-mobile`).
- The `faminec/notes` plugin enabled in Noctalia.

## Usage

Open the panel from the bar widget (or with):

```sh
noctalia msg panel-toggle faminec/notes-sync:panel
```

The panel shows whether the server answers, whether a phone is connected, how
many messages are queued for it, and how many notes the folder has. From there
you can open the notes panel on the computer, send the note you have open to
the phone, sync now, or jump to the settings.

### Bar widget

| Color | Meaning |
| --- | --- |
| Green | The phone is connected |
| Amber | Messages are queued for the phone |
| Grey | The phone is not connected |
| Red | The server is not answering |

## Settings

Settings live in *Settings → Plugins → Notes Sync*.

| Setting | Type | Default | Description |
| --- | --- | --- | --- |
| `server_url` | `string` | `http://127.0.0.1:8787` | Address of the `notes-mobile` server. |
| `token` | `password` | *(empty)* | Access token. When empty it is read from `~/notes-mobile/config.json`. |
| `notes_plugin` | `string` | `faminec/notes` | Id of the notes plugin this plugin drives. |
| `poll_interval` | `int` | `10` | Seconds between server status checks. |

## IPC

The `service` entry is always alive while the plugin is enabled, so it can be
used even when the panel is closed. Every command takes a JSON payload.

```sh
noctalia msg plugin faminec/notes-sync:service all refresh
noctalia msg plugin faminec/notes-sync:service all cmd '{"op":"status"}'
noctalia msg plugin faminec/notes-sync:service all cmd '{"op":"open-notes"}'
noctalia msg plugin faminec/notes-sync:service all cmd '{"op":"open-note","name":"my note.md"}'
noctalia msg plugin faminec/notes-sync:service all cmd '{"op":"send-current"}'
noctalia msg plugin faminec/notes-sync:service all cmd '{"op":"push","text":"hello","title":"From the PC"}'
```

| `op` | Effect |
| --- | --- |
| `status` | Refreshes the published status right away. |
| `open-notes` | Opens the notes panel on the computer. |
| `open-note` | Opens the given note in the notes panel. |
| `send-current` | Sends the note that is open in the notes panel to the phone. |
| `push` | Queues a message for the phone. |
| `refresh` | Same as `status`; also accepted as a bare event. |

## Published state

The service publishes a snapshot under `notes_sync`:

| Field | Type | Meaning |
| --- | --- | --- |
| `serverUp` | `bool` | The server answered the last check. |
| `phoneConnected` | `bool` | A phone is connected to the server. |
| `pending` | `number` | Messages queued for the phone. |
| `notes` | `number` | Notes in the folder. |
| `lastSeen` | `number` | Timestamp of the last phone connection. |
| `url` | `string` | Server address in use. |
| `checkedAt` | `string` | Time of the last check. |
| `error` | `string` | Last error, if any. |
| `currentNote` | `string` | Note currently open in the notes panel. |

## How the two plugins talk

`noctalia.state` is **scoped per plugin**: a key set by one plugin is not
visible to another. The channel between `faminec/notes` and `faminec/notes-sync`
is a small file instead:

```
~/.local/state/noctalia/plugins/data/faminec/notes/current.json
```

```json
{ "name": "my note.md", "content": "…", "at": "2026-10-21 17:22:23" }
```

The notes plugin rewrites it whenever a note is opened or saved; the sync
plugin reads it to know which note is open and what it contains. Any other
tool can read it too.

## Notes

- The plugin never writes to the notes folder itself: all writes go through the
  `notes-mobile` server, which keeps backups of every note it overwrites.
- Requests to the server go through a small queue: the host only accepts eight
  simultaneous requests per script.
- Note names arrive from the phone, so every command is shell-quoted.
