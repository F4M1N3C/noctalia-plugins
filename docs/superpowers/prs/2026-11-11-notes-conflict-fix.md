# PR body (local, sin abrir) — fix(notes): do not overwrite changes made outside the panel

- **Repo:** `noctalia-dev/official-plugins`
- **Rama local:** `fix/notes-dont-overwrite-external-changes`
- **Commit:** `2d239ef` (sobre `main` = `7ae96a6`)
- **Estado:** preparado en local. NO se hace push y NO se abre el PR hasta que el usuario lo ordene.

## Summary

`flush()` wrote the editor buffer straight to disk whenever the note was dirty.
It never looked at what was on the file, so any change made outside the panel
between the last read and the save was silently thrown away.

The file on disk is now read before writing and both versions are compared:

| disk | editor | result |
|---|---|---|
| unchanged | changed | the editor text is saved (normal case) |
| changed | unchanged | the disk version is adopted |
| changed | changed, both grew from the same base | the two are combined |
| changed | changed, incompatible | **nothing is written**: the user is warned and their text is kept in `.conflicts/` |

## Motivation

Reproduction (any second writer on the notes folder — a phone app, Syncthing,
another editor):

1. Open `shopping.md` in the Notes panel. The editor holds the text `milk`.
2. Change the file from outside to `milk, eggs`.
3. Type `bread` in the panel and wait for the autosave (2 idle ticks).

The file on disk ends up as `bread`: `milk, eggs` is gone, with no warning, no
undo and no backup. The same happens when the panel is closed with unsaved
edits, because `onClose()` calls `flush()` too.

The conflict is silent because the panel never compares its buffer with the
file. This PR adds that comparison, and when the two versions cannot be
combined the user's text is written to `.conflicts/<note>-<timestamp>.md` inside
the notes folder (a hidden folder, like the existing `.pinned.json` sidecar) so
nothing is lost when the panel closes.

## Type of Change

- [x] Bug fix
- [ ] New feature
- [ ] Breaking change
- [ ] Refactoring
- [ ] Build / packaging

## Related Issue

<!-- Example: Closes #123 -->

None yet — reporting the data loss would need a place in the tracker.

## Testing

Automated (Luau panel driven through the shared mock, out of tree):

- a note with no outside change is saved as before, with no warning;
- a note changed outside is **not** overwritten: the disk text survives, the
  editor keeps the user's text and a warning is shown;
- the user's text is copied to `.conflicts/` and the copy holds it verbatim;
- the warning is shown once, not on every autosave tick;
- when only the outside version changed, it is adopted;
- when both sides grew from the same base, the two texts are combined.

Manual:

- Notes panel open, note edited from a second application → autosave warns and
  the file keeps the outside text; the editor still shows what was typed.
- Same without touching the editor → the outside text is adopted silently.

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

None: no visual change in the layout. The only new UI is the warning toast.

## Checklist

- [x] This PR is ready for review, or it is marked as Draft.
- [x] I self-reviewed the changes.
- [x] I added or updated `translations/en.json`, or this PR adds no new user-facing strings.
- [x] I did not edit non-English translation files unless this PR is explicitly for translation tooling, an import/export sync, or a maintainer-requested locale change.

## Additional Notes

- The two versions are only combined when both are strict extensions of the same
  base, which keeps the result predictable: `abc` + `abc+PC` and `abc+phone`
  become `abc+PC+phone`. Anything else is treated as a conflict and nothing is
  written.
- The copy in `.conflicts/` is not part of the notes list (hidden folder), and
  the folder is not deleted automatically; the user can remove it once the text
  has been merged.
- This PR is independent of the companion PR *"watch the notes folder for
  changes made outside the panel"*: the comparison happens at save time, so the
  data is safe even without the watcher. With the watcher, the outside change
  is also visible in the editor before saving.
