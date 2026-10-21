# Notes

Quick text notes in a side panel, with live sync from outside the panel. This is a fork
of Noctalia's official `noctalia/notes` plugin (MIT) that adds a folder watcher: changes
made by another tool — a phone app, Syncthing, a plain text editor — show up in the open
panel on their own, and a small IPC bridge lets other tools refresh the panel or open a
specific note.

## Plugin

| Field | Value |
| --- | --- |
| ID | `faminec/notes` |
| Entries | Panel: `panel`; launcher provider: `launcher`; bar widget: `notes`; service: `service` |
| Launcher Prefix | `/nt` |

## Requirements

None. The plugin only reads and writes plain text files in the notes folder.

## Usage

Open the panel from the bar widget or with:

```sh
noctalia msg panel-toggle faminec/notes:panel
```

The panel lists every note in the notes folder, plus a permanent scratchpad. Selecting a
note opens it in the editor; `+` creates a new one, the clipboard button creates a note
from the clipboard, and the trash button deletes the selected note.

The launcher provider is registered under the `/nt` prefix. Type `/nt` followed by a
word to search your notes, `/nt ` followed by text to create a note from it, and pick
one of the offered actions:

| Entry | What it does |
| --- | --- |
| `Open Notes` | Browse all notes |
| `New Note` | Start an empty note |
| `New Note From Clipboard` | Start a note prefilled with the clipboard |
| `Add to Scratchpad` | Append the text to the scratchpad |

Picking a note opens the panel with that note already selected.

## Settings

Settings live in *Settings → Plugins → Notes*.

| Setting | Type | Default | Description |
| --- | --- | --- | --- |
| `notes_dir` | `folder` | `~/Documents/Notes` | Folder where the note files are stored. |
| `extension` | `string` | `md` | Extension of the note files, without the dot. Only files with this extension are listed. |
| `watch` | `bool` | `true` | Refresh the panel when the notes change outside of it. |

## IPC

The `service` entry is a bridge for other tools. It is always alive while the plugin is
enabled, so it can be used even when the panel is closed.

```sh
noctalia msg plugin faminec/notes:service all refresh
noctalia msg plugin faminec/notes:service all open-note "my note.md"
noctalia msg plugin faminec/notes:service all open-home
```

| Event | Effect |
| --- | --- |
| `refresh` | Bumps the notes counter so the open panel reloads the folder immediately. |
| `open-note` | Queues the given note file and opens the panel on it. |
| `open-home` | Opens the panel on the note list. |

## Open note channel

The plugin writes the note that is currently open to
`~/.local/state/noctalia/plugins/data/faminec/notes/current.json`:

```json
{ "name": "my note.md", "content": "…", "at": "2026-10-21 17:22:23" }
```

It is rewritten whenever a note is opened or saved. `faminec/notes-sync` reads
it to know which note is open, and any other tool can read it too.

## Notes

- Notes are plain files in `notes_dir`; the scratchpad is a special note called
  `scratchpad` that is always present and cannot be deleted from the panel.
- With `watch` enabled, changes made outside the panel (phone app, sync client, editor)
  are picked up automatically.
- The fork keeps the MIT license of the original `noctalia/notes` plugin.
