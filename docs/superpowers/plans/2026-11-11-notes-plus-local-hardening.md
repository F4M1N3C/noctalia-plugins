# Notes Plus: local hardening — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Leave the local `notes-plus` + `notes-mobile` system at 100 %: no silent data loss, the mobile and the PC always agree on the notes folder, the "send-current" channel survives the future split into `notes-sync`, and the upstream PRs are prepared locally. Nothing leaves this machine until the user says so.

**Architecture:** Three small Luau modules (`dirs.luau`, `merge.luau`, `channel.luau`) carry the reusable logic; `panel.luau` and `service.luau` consume them; `server.js` mirrors the same folder resolution in Node. The data-loss bug is fixed with a 3-way merge (`merge.resolve`) shared by `flush()` and `onExternalChange()`. The mobile-facing channel moves from `pluginDataDir()/current.json` to `<notesDir>/.current.json`. The widget glyph stops colliding with the official one.

**Tech Stack:** Luau (plugin_api 26, compatible with Lua 5.4 for the test harnesses), Node.js (no dependencies), `noctalia` plugin host, `systemd --user` services.

**Spec:** `~/noctalia-plugins/docs/superpowers/specs/2026-11-11-notes-plus-arquitectura-design.md` (§10 is the scope table this plan implements).

## Global Constraints

- **Todo local.** No `git push`, no PR opened, no upload to the Community store. The user decides when it is 100 %.
- **Lenguaje:** Luau with `--!nonstrict`, written so the Lua 5.4 harness can load it (the harness normalises `+=`/`..=`). API level `plugin_api = 26`.
- **Servidor:** Node without dependencies (`node` from the system, no `npm install`).
- **Pruebas:** `lua5.4 test-panel.lua` (panel harness, 27 checks today), `lua5.4 test-units.lua` (new modules), `./test-api.sh` (isolated instance, 107 checks today).
- **Despliegue local:** every change to `notes-plus/` is synced to `~/.local/share/noctalia/plugins/notes-plus/` with `rsync -a --delete`, verified with `diff -rq`, and the plugin is reloaded (`noctalia msg plugins disable/enable faminec/notes-plus`).
- **IDs:** the editor keeps `faminec/notes-plus`. The bridge becomes `faminec/notes-sync` only in the publication phase (out of this plan).
- **Carpeta de notas de este equipo:** `~/Documents/Notes` (= `$XDG_DOCUMENTS_DIR/Notes`).
- **No tocar** the uncommitted `cmf-buds` changes nor the pre-existing uncommitted changes in `~/notes-mobile` (config.json, server.js, public/app.js, …) beyond what each task names. In `~/notes-mobile` no commits are made; only the named files change.
- **Monorepo commits:** explicit paths only (`git add notes-plus/...`), never the whole tree.

## Review Focus

The five failure modes most likely to bite a real user, most likely first:

1. **El móvil escribe mientras se está editando en el PC** → el autoguardado no pisa la versión del móvil; si las dos versiones difieren, se avisa y no se sobrescribe nada.
2. **La nota se borra o se renombra desde fuera** → el panel no se queda con un nombre fantasma ni guarda sobre un archivo inexistente.
3. **Dos plugins distintos (editor y puente)** → el puente tiene que encontrar la nota abierta aunque el editor sea otro plugin (canal `.current.json` en la carpeta de notas).
4. **La carpeta de notas no existe o no es la de los ajustes** → ni el panel ni el servidor apuntan a carpetas distintas (resolución `$XDG_DOCUMENTS_DIR` idéntica en Luau y en Node).
5. **Un fichero auxiliar dentro de la carpeta de notas** (`.current.json`, `.pinned.json`, `.conflicts/`) nunca aparece como una nota en la lista ni en la API.

---

## File Structure (what gets created or modified)

```
notes-plus/
  dirs.luau        CREATE  port del oficial: resuelve notes_dir con $XDG_DOCUMENTS_DIR
  merge.luau       CREATE  3-way merge resolver (resolve)
  channel.luau     CREATE  lee/escribe <notesDir>/.current.json de forma atomica
  test-units.lua   CREATE  pruebas de los 3 modulos
  test-mock.luau   CREATE  mock de noctalia compartido (extraido del harness del panel)
  test-driver.lua  CREATE  driver para el round-trip (edita y guarda una nota)
  test-panel.lua   MODIFY  usa test-mock.luau; nuevas pruebas del bug y del canal
  panel.luau       MODIFY  flush() con merge; onExternalChange(); usa dirs/merge/channel; publishCurrent() -> channel
  launcher.luau    MODIFY  usa dirs.resolveNotesDir()
  service.luau     MODIFY  lee el canal desde la carpeta de notas (dirs + channel)
  widget.luau      (sin cambio de logica; el glifo cambia en plugin.toml)
  plugin.toml      MODIFY  notes_dir default -> $XDG_DOCUMENTS_DIR/Notes; widget glyph default -> device-mobile
  translations/es.json, en.json  MODIFY  nuevas claves (conflict, conflict_saved)
notes-mobile/
  server.js        MODIFY  resuelve $XDG_DOCUMENTS_DIR; recarga los ajustes del plugin
  config.json      (sin cambio: plugin_id ya es faminec/notes-plus)
  test-api.sh      MODIFY  pruebas de resolucion de carpeta y de recarga
  test-roundtrip.sh CREATE  round-trip movil -> PC -> movil
docs/superpowers/prs/
  2026-11-11-notes-watch-external-changes.md  CREATE  cuerpo del PR 1 (preparado, no abierto)
  2026-11-11-notes-conflict-fix.md            CREATE  cuerpo del PR 2 (preparado, no abierto)
```

---

### Task 1: Módulos base y arnés de pruebas

**Files:**
- Create: `notes-plus/dirs.luau` (copia literal del oficial, con cabecera de origen)
- Create: `notes-plus/merge.luau`
- Create: `notes-plus/channel.luau`
- Create: `notes-plus/test-units.lua`
- Create: `notes-plus/test-mock.luau`

**Interfaces:**
- Consumes (de Noctalia): `noctalia.getConfig`, `noctalia.getenv`, `noctalia.expandPath`, `noctalia.readFile`, `noctalia.writeFile`, `noctalia.renameFile`, `noctalia.removeFile`, `noctalia.fileInfo`, `noctalia.mkdirAll`, `noctalia.json`.
- Produces:
  - `dirs.resolveNotesDir() -> string` (ruta absoluta de la carpeta de notas).
  - `merge.resolve(base: string, localBuf: string, remote: string) -> {status: string, content: string}`. Statuses: `"same"`, `"local"`, `"remote"`, `"merged"`, `"conflict"`.
  - `channel.currentPath(notesDir: string) -> string`.
  - `channel.write(notesDir: string, payload: {name, content, open, at}) -> boolean`.
  - `channel.read(notesDir: string) -> {name, content, open} | nil`.
  - `test-mock` returns a table `{mock, leer, escribir, existe, listar, json_encode, json_decode, state, botones, bitacora, erroresNotificados, limpia, ...}` so both harnesses share one mock.

- [ ] **Step 1: Write `dirs.luau`** (copiar literalmente `/tmp/opencode/official-plugins/notes/dirs.luau` y añadir la cabecera `-- Ported verbatim from noctalia/notes (MIT). Do not diverge.`). Verificar que el fichero compila con `lua5.4 -e 'dofile("dirs.luau")'` (con un mock mínimo de `noctalia`).

- [ ] **Step 2: Write `merge.luau`** con esta lógica exacta:

```lua
local M = {}

local function isPrefix(s, prefix)
  return s:sub(1, #prefix) == prefix
end

function M.resolve(base, localBuf, remote)
  if localBuf == remote then
    return { status = "same", content = remote }
  end
  if remote == base then
    return { status = "local", content = localBuf }
  end
  if localBuf == base then
    return { status = "remote", content = remote }
  end
  -- Los dos cambiaron: solo se puede combinar si ambos añadieron al final
  -- (base es prefijo de los dos). Si uno edito en medio -> conflicto.
  -- Una base vacia es caso aparte: la nota estaba vacia, asi que los dos
  -- textos son dos cosas distintas, no dos añadidos. Fusionarlos inventaria
  -- un texto que nadie escribio.
  if base ~= "" and isPrefix(localBuf, base) and isPrefix(remote, base) then
    local ls = localBuf:sub(#base + 1)
    local rs = remote:sub(#base + 1)
    if ls == rs then
      return { status = "merged", content = localBuf }
    end
    if isPrefix(rs, ls) then
      return { status = "merged", content = base .. rs }
    end
    if isPrefix(ls, rs) then
      return { status = "merged", content = base .. ls }
    end
    -- Añadidos distintos: se conservan los dos (sin perder texto).
    return { status = "merged", content = base .. ls .. rs }
  end
  return { status = "conflict", content = localBuf }
end

return M
```

- [ ] **Step 3: Write `channel.luau`**:

```lua
local M = {}

function M.currentPath(notesDir)
  return notesDir .. "/.current.json"
end

function M.write(notesDir, payload)
  if notesDir == "" or notesDir == nil then
    return false
  end
  local noctalia = _G.noctalia
  local encoded = noctalia.json.encode({
    name = payload.name or "",
    content = payload.content or "",
    open = payload.open == true,
    at = payload.at or "",
  })
  if encoded == nil then
    return false
  end
  local tmp = notesDir .. "/.current.json.tmp"
  local ok = noctalia.writeFile(tmp, encoded)
  if not ok then
    return false
  end
  local renamed = noctalia.renameFile(tmp, notesDir .. "/.current.json")
  if not renamed then
    noctalia.removeFile(tmp)
    return false
  end
  return true
end

function M.read(notesDir)
  if notesDir == "" or notesDir == nil then
    return nil
  end
  local noctalia = _G.noctalia
  local raw = noctalia.readFile(notesDir .. "/.current.json")
  if raw == nil or raw == "" then
    return nil
  end
  local ok, decoded = pcall(noctalia.json.decode, raw)
  if not ok or type(decoded) ~= "table" then
    return nil
  end
  if type(decoded.name) ~= "string" then
    return nil
  end
  return {
    name = decoded.name,
    content = decoded.content or "",
    open = decoded.open == true,
  }
end

return M
```

- [ ] **Step 4: Extract the mock from `test-panel.lua` into `test-mock.luau`**, returning a table with the mock and all helpers. Adjust `test-panel.lua` to do `local M = dofile(scriptDir() .. "/test-mock.luau")` and use `M.mock`, `M.state`, `M.botones`, etc. Run `lua5.4 test-panel.lua` → must print `27` checks passed, 0 failures (the existing count, before the new tests of Task 2).

- [ ] **Step 5: Write `test-units.lua`** with a small mock (getConfig returns `notes_dir = "/tmp/notes-units"` and `XDG_DOCUMENTS_DIR` simulation) and at least these checks:

  - `merge`: `"same"` (local==remote), `"local"` (remote==base), `"remote"` (local==base), `"merged"` both-appended, `"merged"` one-is-prefix, `"conflict"` (both edited in the middle), `"conflict"` (base empty, local and remote differ).
  - `channel`: write creates `<dir>/.current.json`; read returns the payload; read of a missing file → nil; read of a corrupt file → nil; write is atomic (tmp + rename recorded in `bitacora`); no temp file left behind.
  - `dirs`: default resolves to `<documents>/Notes`; a configured absolute path is returned as-is; `$XDG_DOCUMENTS_DIR/sub` resolves the prefix; the legacy fallback kicks in when the resolved default does not exist but `~/Documents/Notes` does.

  Run: `lua5.4 test-units.lua` → expected `N correctos, 0 fallos` with N ≥ 20.

- [ ] **Step 6: Commit** (monorepo, paths only):

```bash
cd ~/noctalia-plugins
git add notes-plus/dirs.luau notes-plus/merge.luau notes-plus/channel.luau notes-plus/test-units.lua notes-plus/test-mock.luau
git commit -m "feat(notes-plus): add dirs, merge and channel modules + shared test mock"
```

---

### Task 2: El autoguardado no pisa cambios externos

**Files:**
- Modify: `notes-plus/panel.luau:154-211` (`publishCurrent`, `flush`) and `notes-plus/panel.luau:801-845` (`onExternalChange`)
- Modify: `notes-plus/translations/es.json`, `notes-plus/translations/en.json` (new keys `errors.conflict`, `errors.conflict_saved`)
- Modify: `notes-plus/test-panel.lua` (new checks)
- Test: `notes-plus/test-panel.lua`

**Interfaces:**
- Consumes: `merge.resolve(base, localBuf, remote)`, `channel.write`, `dirs.resolveNotesDir()` (Task 1).
- Produces: `flush()` no longer overwrites an externally changed file; a conflict keeps the local text, writes a safety copy to `<notesDir>/.conflicts/<name>-<timestamp>.md`, and notifies once.

Behavior of `flush()`:
1. If `not dirty or current == nil` → return (unchanged).
2. `remote = noctalia.readFile(notePath(current)) or ""`.
3. `r = merge.resolve(loadedContent, buffer, remote)`.
4. `"local"` or `"merged"` → write `r.content` to disk, `loadedContent = r.content`, `dirty = false`, `lastNote/lastContent`, `noctalia.state.set("notes_content", r.content)`, `publishCurrent()` (→ `channel.write`).
5. `"same"` → `dirty = false`, no write.
6. `"remote"` → adopt: `buffer = r.content`, `loadedContent = r.content`, `dirty = false`, `publishCurrent()`.
7. `"conflict"` → **no write**. Safety copy to `<notesDir>/.conflicts/<name>-<timestamp>.md` (folder created with `noctalia.mkdirAll`), `noctalia.notifyError(tr("title"), tr("errors.conflict"))` once, keep `dirty = true` and the buffer intact.

`onExternalChange()`:
- When the open note's content on disk differs from `loadedContent` and the buffer is dirty, use `merge.resolve(loadedContent, buffer, contents)` instead of the current "graft the tail" logic. `"conflict"` → keep the buffer, safety copy, notify once. `"merged"`/`"remote"` → adopt as resolved. `"local"` → the disk is the base, leave the buffer.
- The safety copy's file name sanitises `/` and `..` and uses `noctalia.formatTime("%Y%m%d-%H%M%S"):gsub("[^%w%-]", "-")`.

- [ ] **Step 1: Write the failing tests** in `test-panel.lua`. New checks (after the existing "un cambio externo se publica" block):

```lua
-- El autoguardado no pisa un cambio externo incompatible.
escribir(DIR .. "/renombrada.md", "contenido nuevo")
state.open_note = "renombrada.md"
pcall(onOpen, {})
-- Simular que el usuario tiene texto sin guardar:
pcall(onEdited, "mi version local")
escribir(DIR .. "/renombrada.md", "version del movil") -- cambio externo incompatible
erroresNotificados = {}
pcall(update) -- autosave
check("el autoguardado no pisa un cambio externo", "version del movil", leer(DIR .. "/renombrada.md"))
check("con cambios incompatibles se avisa", true, #erroresNotificados >= 1)
-- copia de seguridad del texto local
local conflictFiles = listar(DIR .. "/.conflicts")
check("se guarda una copia del texto local", true, #conflictFiles >= 1)

-- Sin cambios externos, el autoguardado sigue guardando.
limpia()
escribir(DIR .. "/nota2.md", "base")
state.open_note = "nota2.md"
pcall(onOpen, {})
pcall(onEdited, "base editada")
pcall(update)
check("sin cambios externos, el autoguardado guarda", "base editada", leer(DIR .. "/nota2.md"))

-- Un añadido externo se combina con el texto local.
limpia()
escribir(DIR .. "/nota3.md", "hola")
state.open_note = "nota3.md"
pcall(onOpen, {})
pcall(onEdited, "hola mundo")
escribir(DIR .. "/nota3.md", "hola!")
pcall(update)
check("un añadido externo se combina", "hola mundo!", leer(DIR .. "/nota3.md"))
```

- [ ] **Step 2: Run the tests to confirm they fail** → `lua5.4 test-panel.lua` must show the new checks as `FALLA`.

- [ ] **Step 3: Implement the merge in `flush()` and `onExternalChange()`** following the behavior above. Add the helper `local function safetyCopy(name, content)` and the keys `errors.conflict` ("La nota cambió fuera mientras la editabas; no se ha sobrescrito. Tu texto se guardó en .conflicts/.") and `errors.conflict_saved` ("Se guardó una copia de tu texto en .conflicts/.").

- [ ] **Step 4: Run the tests** → `lua5.4 test-panel.lua` must show all checks (old + new) as `ok`.

- [ ] **Step 5: Commit:**

```bash
cd ~/noctalia-plugins
git add notes-plus/panel.luau notes-plus/translations/es.json notes-plus/translations/en.json notes-plus/test-panel.lua
git commit -m "fix(notes-plus): flush() no longer overwrites externally changed notes"
```

---

### Task 3: El canal de la nota abierta pasa a `.current.json`

**Files:**
- Modify: `notes-plus/panel.luau:154-192` (`publishCurrent` → `channel.write`)
- Modify: `notes-plus/service.luau:228-275` (`dataRoot`, `notesCurrentFile`, `readCurrentNote` → `dirs` + `channel`)
- Modify: `notes-plus/test-panel.lua` (the `current()` helper reads `DIR .. "/.current.json"`)

**Interfaces:**
- Consumes: `channel.write(notesDir, payload)`, `channel.read(notesDir)`, `dirs.resolveNotesDir()`.
- Produces: the panel publishes to `<notesDir>/.current.json`; the service reads from there; the old `pluginDataDir()/current.json` is no longer written.

- [ ] **Step 1: Update the panel.** Replace the body of `publishCurrent()` with a call to `channel.write(notesDir, {name = current or lastNote, content = current ~= nil and buffer or lastContent, open = current ~= nil, at = noctalia.formatTime("%Y-%m-%d %H:%M:%S")})`. Drop the now-unused `noctalia.pluginDataDir()`/`mkdirAll` logic.

- [ ] **Step 2: Update the service.** Replace `dataRoot()`/`notesCurrentFile()` with:

```lua
local function notesDir()
  local ok, dirs = pcall(require, "./dirs.luau")
  if ok and type(dirs) == "table" and type(dirs.resolveNotesDir) == "function" then
    return dirs.resolveNotesDir()
  end
  -- Fallback for a service that cannot load dirs.luau.
  return noctalia.expandPath("~/Documents/Notes")
end

local function readCurrentNote()
  local ok, channel = pcall(require, "./channel.luau")
  if ok and type(channel) == "table" and type(channel.read) == "function" then
    return channel.read(notesDir())
  end
  return nil
end
```

  Keep the rest of `readCurrentNote`'s contract (`{name, content, open}` or nil).

- [ ] **Step 3: Update the panel harness.** Change `current()` to read `DIR .. "/.current.json"` and add the check `"el canal esta en la carpeta de notas"` (the file exists at `DIR .. "/.current.json"`).

- [ ] **Step 4: Run `lua5.4 test-panel.lua`** → all checks pass.

- [ ] **Step 5: Commit:**

```bash
cd ~/noctalia-plugins
git add notes-plus/panel.luau notes-plus/service.luau notes-plus/test-panel.lua
git commit -m "feat(notes-plus): move the open-note channel to <notesDir>/.current.json"
```

---

### Task 4: La carpeta de notas se resuelve igual en el plugin y en el servidor

**Files:**
- Modify: `notes-plus/panel.luau` (the `do` block at L45-56 → `notesDir = dirs.resolveNotesDir()`)
- Modify: `notes-plus/launcher.luau:19-26` (`settings()` → `dirs.resolveNotesDir()`)
- Modify: `notes-plus/plugin.toml` (`notes_dir` default → `"$XDG_DOCUMENTS_DIR/Notes"`)
- Modify: `notes-mobile/server.js` (`expandPath` + the legacy fallback)
- Modify: `notes-mobile/test-api.sh` (new checks)

**Interfaces:**
- Produces: `notesDir` in the plugin and `NOTES_DIR` in the server are always the same absolute path for the same settings, including on localized systems (e.g. `~/Documentos/Notes`).

- [ ] **Step 1: Wire `dirs.luau` in the panel.** Replace the `do ... end` block at the top of `panel.luau` with:

```lua
local dirs = require("./dirs.luau")
notesDir = dirs.resolveNotesDir()
local extension = noctalia.string.trim(noctalia.getConfig("extension")):gsub("^%.", "")
if extension ~= "" then
  suffix = "." .. extension
end
```

- [ ] **Step 2: Wire `dirs.luau` in the launcher.** In `settings()`, replace `noctalia.expandPath(noctalia.getConfig("notes_dir"))` with `dirs.resolveNotesDir()`.

- [ ] **Step 3: Update `plugin.toml`.** Change `default = "~/Documents/Notes"` to `default = "$XDG_DOCUMENTS_DIR/Notes"`. Add a comment matching the official's.

- [ ] **Step 4: Update `server.js`.** Replace `expandPath` with a version that resolves the `$XDG_DOCUMENTS_DIR` prefix and applies the legacy fallback. Add a `documentsDir()` helper that reads `XDG_DOCUMENTS_DIR` from `~/.config/user-dirs.dirs` (honouring `XDG_CONFIG_HOME`), falling back to `~/Documents`. Apply the legacy fallback only when the configured value is exactly the default.

```js
function documentsDir() {
  const home = HOME;
  const configHome = process.env.XDG_CONFIG_HOME || path.join(home, ".config");
  try {
    const raw = fs.readFileSync(path.join(configHome, "user-dirs.dirs"), "utf8");
    for (const line of raw.split("\n")) {
      const m = line.match(/^\s*XDG_DOCUMENTS_DIR\s*=\s*"([^"]*)"/);
      if (m) {
        let v = m[1];
        if (v.startsWith("$HOME")) v = path.join(home, v.slice(5));
        v = v.replace(/\/+$/, "");
        if (v && v !== home) return v;
      }
    }
  } catch { /* no user-dirs.dirs: default */ }
  return path.join(home, "Documents");
}

function expandPath(p) {
  if (!p) return p;
  if (p === "~") return HOME;
  if (p.startsWith("~/")) return path.join(HOME, p.slice(2));
  const DEFAULT = "$XDG_DOCUMENTS_DIR/Notes";
  const LEGACY = path.join(HOME, "Documents", "Notes");
  if (p === DEFAULT) {
    const resolved = path.join(documentsDir(), "Notes");
    if (resolved !== LEGACY && !fs.existsSync(resolved) && fs.existsSync(LEGACY)) return LEGACY;
    return resolved;
  }
  const rest = p.match(/^\$XDG_DOCUMENTS_DIR(\/.*)?$/);
  if (rest) {
    return path.join(documentsDir(), (rest[1] || "").replace(/^\/+/, ""));
  }
  return p;
}
```

- [ ] **Step 5: Add tests to `test-api.sh`.** Three new checks (mirror the existing style): "el servidor resuelve $XDG_DOCUMENTS_DIR" (temp config with `notes_dir = "$XDG_DOCUMENTS_DIR/Notes"` → `/api/state` dir equals `<documents>/Notes`), "el servidor usa la carpeta legacy si la nueva no existe", "el servidor respeta una ruta absoluta configurada".

- [ ] **Step 6: Run `lua5.4 test-panel.lua` and `./test-api.sh`** → both green.

- [ ] **Step 7: Commit (monorepo paths only; server repo left uncommitted per the global constraints):**

```bash
cd ~/noctalia-plugins
git add notes-plus/panel.luau notes-plus/launcher.luau notes-plus/plugin.toml
git commit -m "feat(notes-plus): resolve notes_dir via dirs.luau ($XDG_DOCUMENTS_DIR)"
```

---

### Task 5: El widget del puente usa un glifo propio

**Files:**
- Modify: `notes-plus/plugin.toml` (widget glyph default `notes` → `device-mobile`)
- Modify: `notes-plus/widget.luau` (fallback string `"notes"` → `"device-mobile"`)
- Modify: `notes-plus/translations/es.json`, `en.json` (no new key needed; the glyph picker is generic)

**Interfaces:** none new. Visual result: the bar no longer shows two identical `notes` icons.

- [ ] **Step 1: Edit `plugin.toml`** — `default = "notes"` under `[[widget.setting]] key = "glyph"` → `default = "device-mobile"`.

- [ ] **Step 2: Edit `widget.luau`** — `noctalia.getConfig("glyph") or "notes"` → `... or "device-mobile"`.

- [ ] **Step 3: Deploy and verify visually.** Sync to the installed copy, reload the plugin, then capture the bar region with `grim -g "$(slurp)"` reduced with `magick` and analyse it with the `screen-analysis` skill (subagent with model `nvidia/nvidia/nemotron-3.5-super-vl-120b-a12b`) to confirm there is a single `notes` glyph (the official) and a `device-mobile` glyph (the bridge), not two `notes`.

- [ ] **Step 4: Commit:**

```bash
cd ~/noctalia-plugins
git add notes-plus/plugin.toml notes-plus/widget.luau
git commit -m "feat(notes-plus): use device-mobile glyph to avoid collision with official notes"
```

---

### Task 6: El servidor apunta al plugin y a la carpeta correctos, y se entera de los cambios

**Files:**
- Modify: `notes-mobile/server.js` (`readPluginSettings` → also resolve `notes_dir`; reload settings when the file changes)
- Modify: `notes-mobile/test-api.sh` (new checks)

**Interfaces:**
- Produces: `NOTES_DIR` tracks the plugin's setting without a server restart; `/api/state` reports `plugin` and `dir`.

- [ ] **Step 1: Make `readPluginSettings()` reusable and mtime-aware.** Refactor so a `reloadPluginSettings()` re-reads `~/.local/state/noctalia/settings.toml` when its mtime changes, re-resolves `NOTES_DIR` and `EXT`, and is called at the start of every request handler (cheap: one `stat`).

- [ ] **Step 2: Add tests to `test-api.sh`:** "el servidor vuelve a leer los ajustes del plugin si cambian" (write a `[plugin_settings."faminec/notes-plus"]` section with a new `notes_dir` into a temp `XDG_STATE_HOME`, hit `/api/state`, assert the new dir), "el servidor reporta el plugin_id correcto" (`plugin` field equals `faminec/notes-plus`).

- [ ] **Step 3: Run `./test-api.sh`** → green.

- [ ] **Step 4:** No commit in `~/notes-mobile` (per the global constraints); the change is verified locally.

---

### Task 7: Pruebas de extremo a extremo (móvil → PC → móvil)

**Files:**
- Create: `notes-plus/test-driver.lua`
- Create: `notes-mobile/test-roundtrip.sh`
- Modify: `notes-plus/test-panel.lua` (extracted mock already in Task 1; add a "nota nueva desde el PC se guarda" check)

**Interfaces:**
- `test-driver.lua` usage: `lua5.4 test-driver.lua --dir <dir> --note <name> --text <text>` → opens the note, sets the buffer to `<text>`, saves (flush), prints `OK` on success and exits 0; exits 1 on failure.
- `test-roundtrip.sh`: starts a server instance on a free port pointing at a temp dir, writes a note via the API (simulating the phone), runs the panel driver to edit it (simulating the PC), reads it back via the API, asserts the new content. Prints `Resultado: N correctos, 0 fallos`.

- [ ] **Step 1: Write `test-driver.lua`** using `test-mock.luau` (the same mock as the panel harness). It accepts `--dir`, `--note`, `--text`, opens the note with `state.open_note`, calls `onEdited(text)`, then `update()` (autosave) or `onFlushNow()`, and prints `OK` if the file on disk equals `text`.

- [ ] **Step 2: Write `test-roundtrip.sh`** mirroring `test-api.sh`'s instance startup (free ports, temp config, isolated `XDG_STATE_HOME`). Steps:

```bash
# 1. phone writes
curl -s -X POST .../api/note -d '{"name":"roundtrip.md","content":"desde el movil"}'
# 2. panel edits
NOTES_TEST_DIR="$TMP/notes" lua5.4 test-driver.lua --dir "$TMP/notes" --note "roundtrip.md" --text "editado en el PC"
# 3. phone reads
curl .../api/note/roundtrip.md  -> content == "editado en el PC"
```

- [ ] **Step 3: Run `./test-roundtrip.sh`** → `0 fallos`.

- [ ] **Step 4: Run the full local suite** to confirm nothing regressed:

```bash
cd ~/noctalia-plugins/notes-plus && lua5.4 test-panel.lua && lua5.4 test-units.lua
cd ~/notes-mobile && ./test-api.sh && ./test-roundtrip.sh
```

- [ ] **Step 5: Commit (monorepo only):**

```bash
cd ~/noctalia-plugins
git add notes-plus/test-driver.lua notes-plus/test-panel.lua
git commit -m "test(notes-plus): round-trip driver and e2e scenario"
```

---

### Task 8: Los 2 PRs al oficial, preparados en local (sin abrirlos)

**Files:**
- Work in: `/tmp/opencode/official-plugins` (clone of `noctalia-dev/official-plugins`, branch `main`)
- Create: `~/noctalia-plugins/docs/superpowers/prs/2026-11-11-notes-watch-external-changes.md`
- Create: `~/noctalia-plugins/docs/superpowers/prs/2026-11-11-notes-conflict-fix.md`

**Interfaces:** none new. Deliverable = two local branches with commits ready to push, plus the PR bodies following the repo's `<!-- noctalia-pr-template:v1 -->` template.

- [ ] **Step 1: Inspect the repo's PR template and CI.** Read `/tmp/opencode/official-plugins/.github/PULL_REQUEST_TEMPLATE.md` and the workflow that validates plugins, to know which translation files must be updated and what the body must contain.

- [ ] **Step 2: Branch PR 1 — `feat/notes-watch-external-changes`.** From `main`, port the fork's `checkExternalChanges()` + `dirSignature()` + the `watch` setting (plugin.toml + translations) into `notes/panel.luau` and `notes/plugin.toml`. Commit with a message like `feat(notes): watch the notes directory for external changes`.

- [ ] **Step 3: Branch PR 2 — `fix/notes-dont-overwrite-external-changes`.** From `main`, inline a minimal `resolve(base, local, remote)` helper into `notes/panel.luau` and make `flush()` refuse to overwrite when the file changed on disk and the buffer is dirty (notify + keep the edits). Commit with `fix(notes): never overwrite a note changed externally`.

- [ ] **Step 4: Write the PR bodies** in `~/noctalia-plugins/docs/superpowers/prs/`, following the repo's template: title, summary, what changed, how to test, checklist. Include the reproduction case for the data-loss bug (mobile writes while the panel is dirty → the mobile's version survives).

- [ ] **Step 5: Do not push and do not open the PRs.** Verify with `git -C /tmp/opencode/official-plugins branch` that both branches exist locally with their commits, and `git -C /tmp/opencode/official-plugins log --oneline <branch>` shows them.

- [ ] **Step 6: Commit the PR bodies to the monorepo:**

```bash
cd ~/noctalia-plugins
git add docs/superpowers/prs/
git commit -m "docs(notes): prepare upstream PR bodies for watch and conflict fix (local only)"
```

---

## Verification (whole plan)

Run, in order, after all tasks:

```bash
cd ~/noctalia-plugins/notes-plus
lua5.4 test-panel.lua     # expect: 0 fallos (old 27 + new)
lua5.4 test-units.lua     # expect: 0 fallos
cd ~/notes-mobile
./test-api.sh             # expect: 0 fallos
./test-roundtrip.sh       # expect: 0 fallos
# deploy + verify
rsync -a --delete --exclude '__pycache__' ~/noctalia-plugins/notes-plus/ ~/.local/share/noctalia/plugins/notes-plus/
diff -rq ~/noctalia-plugins/notes-plus ~/.local/share/noctalia/plugins/notes-plus
noctalia msg plugins disable faminec/notes-plus
noctalia msg plugins enable faminec/notes-plus
```

And confirm, with the `screen-analysis` skill, that the bar now shows one `notes` glyph (official) and one `device-mobile` glyph (bridge), not two `notes`.

## Handoff

Plan complete and saved to `docs/superpowers/plans/2026-11-11-notes-plus-local-hardening.md`. Does it capture what you want? I will implement it natively in this session (Native execution), because the eight tasks share tight interfaces and the plan carries the design — the cost of a fresh context per task is not worth it here. Confirm, or pick Subagent-driven if you want an independent reviewer per task.
