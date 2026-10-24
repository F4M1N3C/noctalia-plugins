# Notes Plus

Plugin fusionado de `faminec/notes` y `faminec/notes-sync` para Noctalia Shell.

## Plugin
- id: `faminec/notes-plus`
- version: `1.0.0`
- panel: `panel` (`panel.luau`)
- service: `service` (`service.luau`)
- widget: `widget` (`widget.luau`)
- settings: `notes_dir`, `extension`, `watch`, `server_url`, `token`, `poll_interval`, `glyph`, `show_text`

## Usage
- Panel: `noctalia msg panel-toggle faminec/notes-plus:panel`
- Launcher: abrir lista de notas y edición rápida
- Widget: `noctalia msg widget-toggle faminec/notes-plus:widget`
- Sync view: click the cloud button in the notes panel header
- Service: `noctalia msg service-start faminec/notes-plus:service`
- Notes live at `~/Documents/Notes` (files `.md`)

## Settings
- `notes_dir`: folder where `.md` notes are stored (default `~/Documents/Notes`)
- `extension`: file extension without dot (default `md`)
- `watch`: refresh panel when files change outside it (default `true`)
- `server_url`: address of notes-mobile server (default `http://127.0.0.1:8787`)
- `token`: authentication token for sync (default empty)
- `poll_interval`: polling frequency in seconds (default `10`)
- `glyph`: widget glyph (default `notes`)
- `show_text`: show label text in widget (default `false`)

## Notes
- Mantiene la UI de `notes` como base (panel principal)
- Integra funcionalidades de sincronización con `notes-mobile` desde `notes-sync`
- Las notas viven en `~/Documents/Notes` (archivos `.md`)
- El plugin mantiene PWA `notes-mobile` y el servicio `notes-mobile-tunnel` activo.
