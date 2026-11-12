# PR body (local, sin abrir) — feat(notes): watch the notes folder for changes made outside the panel

- **Repo:** `noctalia-dev/official-plugins`
- **Rama local:** `feat/notes-watch-external-changes`
- **Commit:** `d281f2f` (sobre `main` = `7ae96a6`)
- **Estado:** preparado en local. NO se hace push y NO se abre el PR hasta que el usuario lo ordene.

## Summary

The Notes panel only reacted to changes that the Notes launcher itself published
through the `notes_bump` state key. Any edit made outside the plugin — a mobile
client, a sync tool (Syncthing, Nextcloud…), a text editor — stayed invisible
until the panel was closed and opened again, and the open editor kept showing a
stale version of the note.

The panel now takes a cheap fingerprint of the notes folder on every tick (file
names, size and mtime) and folds outside edits into the open editor. A new
`watch` setting (boolean, default `true`) turns the polling off.

## Motivation

Notes are plain files in a folder, and that folder is shared with everything else
on the machine. The moment a second writer exists — a phone app writing through
the same folder, a sync client, `vim` — the panel and the file on disk drift
apart, and the panel has no way to notice:

- the list of notes does not show a note that was just created on the phone;
- the open editor shows text that no longer exists on disk;
- the next autosave writes that stale buffer over the newer file (see the
  companion PR *"do not overwrite changes made outside the panel"*, which fixes
  the data loss; this PR is what makes the change visible in the first place).

The launcher already solved part of this for its own quick-capture entries by
bumping `notes_bump`. This PR generalises the same idea to any writer.

## Type of Change

- [ ] Bug fix
- [x] New feature
- [ ] Breaking change
- [ ] Refactoring
- [ ] Build / packaging

## Related Issue

<!-- Example: Closes #123 -->

None yet — reporting the behaviour would need a place in the tracker.

## Testing

Automated (Luau panel driven through the shared mock, out of tree):

- a note created outside the panel shows up in the list without reopening it;
- the editor shows the content that is on disk;
- an edit made outside while the editor is open is picked up on the next tick;
- with `watch = false` nothing is picked up.

Manual:

- Notes panel open, note edited from a second application → the panel refreshes
  within a second.
- `watch` off in the plugin settings → the panel stops refreshing.

## Manual Coverage

- [ ] Tested on Niri
- [x] Tested on Hyprland
- [ ] Tested on Sway
- [ ] Tested on another compositor:
- [x] Tested with different bar positions and density settings
- [ ] Tested at different interface scaling values
- [x] Tested with multiple monitors

## Screenshots / Videos

<!-- Include screenshots or videos for UI, visual, animation, or layout changes. -->

None: no visual change, only the panel starts noticing outside edits. The new
setting appears in the plugin settings.

## Checklist

- [x] This PR is ready for review, or it is marked as Draft.
- [x] I self-reviewed the changes.
- [x] I added or updated `translations/en.json`, or this PR adds no new user-facing strings.
- [x] I did not edit non-English translation files unless this PR is explicitly for translation tooling, an import/export sync, or a maintainer-requested locale change.

## Additional Notes

- The fingerprint only covers the note files and the `.pinned.json` sidecar, so
  unrelated files in the notes folder do not trigger a refresh.
- The open note is also compared by content when the fingerprint did not change
  (same second, same size), so fast edits are not missed.
- Polling happens on the panel tick, so the cost is one `listDir` plus one
  `fileInfo` per note, only while the panel is open.
- `watch` defaults to `true`; users who prefer the old behaviour can turn it off.
- The plugin's `en.json` is the only translation file touched: the other locales
  are maintained by the tooling/sync.
