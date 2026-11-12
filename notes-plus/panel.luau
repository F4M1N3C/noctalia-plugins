--!nonstrict
-- Markdown notes in a full-height side panel.
--
-- Notes are plain .md files in the configured notes directory. The panel shows
-- a note list and a multiline editor with idle autosave (flushes after a short
-- pause in typing, on navigation, and on panel close).
--
-- Fork of the official `noctalia/notes` plugin (MIT) with two additions:
--   * a directory watcher that folds in changes made outside the panel (the
--     `notes-mobile` server, Syncthing, a text editor, ...);
--   * an `onIpc` handler so other tools can refresh the panel or open a note.

local merge = require("./merge.luau")
local channel = require("./channel.luau")

local AUTOSAVE_IDLE_TICKS = 2 -- 1s panel ticks with no edits before a flush
local SCRATCHPAD_BASE = "scratchpad"
local PANEL_ID = "faminec/notes-plus:panel"

local notesDir = ""
local suffix = ".md" -- "." .. the configured extension, resolved in onOpen
local files = {}
local view = "list" -- "list" | "editor" | "sync"
local current = nil -- filename ("foo.md") while the editor is open
local buffer = ""
local loadedContent = "" -- what the file held when we last read/wrote it
-- Ultima nota con la que se trabajo, aunque el panel este cerrado: es la que
-- se puede mandar al celular desde el panel de sincronizacion.
local lastNote = ""
local lastContent = ""
local editorRev = 0 -- bumped to reseed the editor input after external changes
local dirty = false
local idleTicks = 0
local pendingDelete = nil -- filename awaiting the second (confirm) click
local sortByDate = false
local pins = {} -- filename -> true; persisted in a sidecar next to the notes
local hoveredKey = nil
local cornerRadiusScale = 1.0
local closeButton = true
local watchedSignature = nil -- fingerprint of the notes dir, to spot outside edits
-- Contenido del disco que ya se sabe incompatible con lo que hay en el
-- editor: evita avisar y copiar el texto una y otra vez.
local conflictRemote = nil

local render
local onExternalChange -- forward declaration, defined near the bottom
local checkExternalChanges -- forward declaration, defined near the bottom

-- Resolve the notes directory as early as possible so the watcher can spot
-- outside edits even before the panel has been opened for the first time.
do
  local dir = noctalia.getConfig("notes_dir")
  if type(dir) == "string" and dir ~= "" then
    notesDir = noctalia.expandPath(dir)
  end
  local extension = noctalia.string.trim(noctalia.getConfig("extension")):gsub("^%.", "")
  if extension ~= "" then
    suffix = "." .. extension
  end
end

noctalia.setUpdateInterval(1000)

local function tr(key, params)
  if params ~= nil then
    return noctalia.tr(key, params)
  end
  return noctalia.tr(key)
end

local function displayName(file)
  return file:sub(1, #file - #suffix)
end

local function hasSuffix(name)
  return #name > #suffix and name:sub(-#suffix) == suffix
end

local function notePath(file)
  return notesDir .. "/" .. file
end

local function scratchName()
  return SCRATCHPAD_BASE .. suffix
end

-- Pins live in a hidden sidecar inside the notes directory so they sync and
-- survive restarts with the notes themselves.
local function pinsPath()
  return notesDir .. "/.pinned.json"
end

local function loadPins()
  pins = {}
  local raw = noctalia.readFile(pinsPath())
  if raw ~= nil then
    -- Un fichero corrupto no debe tumbar el panel.
    local ok, decoded = pcall(noctalia.json.decode, raw)
    if not ok then
      noctalia.log("notes: no se pudo leer el fichero de fijados")
      return
    end
    if type(decoded) == "table" then
      for name, value in pairs(decoded) do
        if type(name) == "string" and value == true then
          pins[name] = true
        end
      end
    end
  end
end

local function savePins()
  local encoded = noctalia.json.encode(pins)
  if encoded == nil then
    return
  end
  local ok, err = noctalia.writeFile(pinsPath(), encoded)
  if not ok then
    noctalia.notifyError(tr("title"), err or "")
  end
end

local function refreshFiles()
  files = {}
  local list = noctalia.listDir(notesDir)
  if list ~= nil then
    for _, name in ipairs(list) do
      if hasSuffix(name) and name ~= scratchName() and name:sub(1, 1) ~= "." then
        table.insert(files, name)
      end
    end
  end
  -- Pinned notes first, then the selected order within each group.
  local mtimes = {}
  if sortByDate then
    for _, name in ipairs(files) do
      local info = noctalia.fileInfo(notePath(name))
      mtimes[name] = info ~= nil and info.mtime or 0
    end
  end
  table.sort(files, function(a, b)
    local aPinned = pins[a] == true
    local bPinned = pins[b] == true
    if aPinned ~= bPinned then
      return aPinned
    end
    if sortByDate and mtimes[a] ~= mtimes[b] then
      return mtimes[a] > mtimes[b]
    end
    return a < b
  end)
end

-- Publica la nota abierta en un fichero dentro de la carpeta de notas.
--
-- El canal vive en la carpeta de notas (y no en el directorio de datos del
-- plugin) para que lo pueda leer otro plugin (el puente) y cualquier otra
-- herramienta: la carpeta de notas ya es el punto de encuentro entre el
-- computador y el celular. Precedente: el oficial guarda ahí `.pinned.json`.
local function publishCurrent()
  if notesDir == "" then
    return
  end
  local ok = channel.write(notesDir, {
    name = current or lastNote,
    content = current ~= nil and buffer or lastContent,
    -- `open` dice si el panel tiene esa nota abierta ahora mismo. Cuando se
    -- cierra, la nota sigue siendo la "ultima nota" para poder mandarla al
    -- celular desde el panel de sincronizacion (los dos paneles no pueden
    -- estar abiertos a la vez: Noctalia solo muestra uno).
    open = current ~= nil,
    at = noctalia.formatTime("%Y-%m-%d %H:%M:%S"),
  })
  if not ok then
    noctalia.log("notes: no se pudo publicar la nota actual")
  end
end

-- Guarda el texto del usuario cuando la nota cambio fuera y las dos versiones
-- no se pueden combinar. Sin esta copia, al cerrar el panel se perderia lo
-- que habia escrito: el autoguardado deja de pisar el cambio externo, pero el
-- texto sigue ahi hasta que se cierre.
local function conflictCopy(noteName, content)
  if notesDir == "" then
    return nil
  end
  local dir = notesDir .. "/.conflicts"
  local ok = noctalia.mkdirAll(dir)
  if not ok then
    return nil
  end
  local stamp = noctalia.formatTime("%Y%m%d-%H%M%S"):gsub("[^%w%-]", "-")
  local safe = noteName:gsub("[^%w%._%-]", "_")
  local path = dir .. "/" .. safe .. "-" .. stamp .. ".md"
  if not noctalia.writeFile(path, content) then
    return nil
  end
  return path
end

local function flush()
  if not dirty or current == nil then
    return
  end
  -- Antes de guardar se lee lo que hay en disco. Si la nota cambio fuera
  -- (el movil, una sincronizacion, otro editor), guardar a ciegas pisaria ese
  -- cambio: se combinan los dos textos cuando se puede y, cuando no, no se
  -- escribe nada.
  local remote = noctalia.readFile(notePath(current)) or ""
  local r = merge.resolve(loadedContent, buffer, remote)
  if r.status == "conflict" then
    if conflictRemote ~= remote then
      conflictRemote = remote
      local path = conflictCopy(current, buffer)
      noctalia.notifyError(tr("title"), tr("errors.conflict"))
      if path ~= nil then
        noctalia.notifyError(tr("title"), tr("errors.conflict_saved"))
      end
    end
    return
  end
  conflictRemote = nil
  if r.status == "local" or r.status == "merged" then
    local ok, err = noctalia.writeFile(notePath(current), r.content)
    if not ok then
      noctalia.notifyError(tr("title"), err or tr("save_failed"))
      return
    end
  end
  -- "same" y "remote": el disco ya tiene lo que toca, solo se adopta.
  buffer = r.content
  loadedContent = r.content
  dirty = false
  lastNote = current or lastNote
  lastContent = buffer
  -- El contenido guardado se publica para que otros plugins puedan usarlo
  -- (por ejemplo, para mandarlo al celular).
  noctalia.state.set("notes_content", buffer)
  publishCurrent()
end

local function openNote(file)
  flush()
  local contents = noctalia.readFile(notePath(file))
  buffer = contents or ""
  loadedContent = buffer
  current = file
  view = "editor"
  dirty = false
  idleTicks = 0
  pendingDelete = nil
  -- Se publica la nota abierta para que otros plugins (por ejemplo
  -- faminec/notes-sync) puedan actuar sobre ella sin adivinar.
  lastNote = file
  lastContent = buffer
  noctalia.state.set("notes_current", file)
  noctalia.state.set("notes_content", buffer)
  publishCurrent()
  render()
end

local function deleteNote(file)
  local ok, err = noctalia.removeFile(notePath(file))
  if not ok then
    noctalia.notifyError(tr("title"), err or "")
  end
  if pins[file] ~= nil then
    pins[file] = nil
    savePins()
  end
  if current == file then
    current = nil
    buffer = ""
    dirty = false
    view = "list"
    -- La nota abierta se acaba de borrar: se publica para que el canal con
    -- el otro plugin no mande una nota que ya no existe.
    lastNote = ""
    lastContent = ""
    publishCurrent()
  end
  pendingDelete = nil
  refreshFiles()
  render()
end

local function uniqueNoteName()
  local base = noctalia.formatTime("%Y-%m-%d %H.%M.%S")
  local name = base .. suffix
  local counter = 2
  while noctalia.fileExists(notePath(name)) do
    name = base .. " (" .. counter .. ")" .. suffix
    counter += 1
  end
  return name
end

local function deleteControls(file)
  return {
    ui.label({ text = tr("confirm_delete"), color = "error" }),
    ui.button({
      glyph = "check",
      variant = "primary",
      onClick = function()
        deleteNote(file)
      end,
    }),
    ui.button({
      glyph = "xmark",
      variant = "ghost",
      onClick = function()
        pendingDelete = nil
        render()
      end,
    }),
  }
end

local function togglePin(file)
  pins[file] = not pins[file] and true or nil
  savePins()
  refreshFiles()
  render()
end

local function listRow(file)
  local pinned = pins[file] == true
  local isHovered = hoveredKey == file
  -- Label elides natively with maxLines=1; the row wrapper supplies the click target.
  local titleChildren = {
    ui.label({
      text = displayName(file),
      maxLines = 1,
      flexGrow = 1,
      color = isHovered and "surface" or "on_surface",
    }),
  }
  if pinned then
    table.insert(titleChildren, 1, ui.glyph({
      name = "pinned",
      size = 14,
      color = isHovered and "surface" or "on_surface",
    }))
  end
  local children = {
    ui.row({
      key = file,
      flexGrow = 1,
      gap = 6,
      align = "center",
      padding = 8,
      paddingH = 12,
      fill = isHovered and "tertiary" or "surface",
      radius = 6 * cornerRadiusScale,
      onHover = "onRowHover",
      onClick = function()
        openNote(file)
      end,
    }, titleChildren),
  }
  if pendingDelete == file then
    for _, node in ipairs(deleteControls(file)) do
      table.insert(children, node)
    end
  else
    table.insert(children, ui.button({
      glyph = pinned and "pinned-off" or "pin",
      variant = "ghost",
      onClick = function()
        togglePin(file)
      end,
    }))
    table.insert(children, ui.button({
      glyph = "trash",
      variant = "ghost",
      onClick = function()
        pendingDelete = file
        render()
      end,
    }))
  end
  -- Pin state is part of the key: retained buttons keep a previously set
  -- glyph, so the row is recreated when it flips.
  return ui.row({ key = "note-" .. file .. (pinned and "-pinned" or ""), gap = 6, align = "center" }, children)
end

local function listView()
  local scratchFile = scratchName()
  local isHovered = hoveredKey == scratchFile
  local rows = {
    -- The scratchpad is always present (created on first write) and not deletable from here.
    ui.row({ key = "scratchpad", gap = 6, align = "center" }, {
      ui.row({
        key = scratchFile,
        flexGrow = 1,
        gap = 6,
        align = "center",
        padding = 8,
        paddingH = 12,
        fill = isHovered and "tertiary" or "surface",
        radius = 6 * cornerRadiusScale,
        onHover = "onRowHover",
        onClick = "onOpenScratchpad",
      }, {
        ui.glyph({
            name = "pinned",
            size = 14,
            color = isHovered and "surface" or "on_surface",
          }),
        ui.label({
            text = tr("scratchpad"),
            maxLines = 1,
            flexGrow = 1,
            color = isHovered and "surface" or "on_surface",
          }),
      }),
    }),
  }
  for _, file in ipairs(files) do
    table.insert(rows, listRow(file))
  end
  if #files == 0 then
    table.insert(rows, ui.label({ text = tr("empty"), color = "on_surface_variant" }))
  end
  return ui.scroll({ flexGrow = 1, gap = 4 }, rows)
end

local function editorStatusLine()
  local words = select(2, buffer:gsub("%S+", ""))
  local chars = utf8.len(buffer) or #buffer
  local status = dirty and tr("editing") or tr("saved")
  return status .. "  ·  " .. noctalia.tr("counts", { words = words, chars = chars })
end

local function editorHeader()
  local trailing
  if pendingDelete == current then
    trailing = deleteControls(current, "noteEditorDelete", 0)
  else
    trailing = {
      ui.button({ glyph = "trash", variant = "ghost", onClick = "onEditorDelete" }),
    }
  end
  local children = {
    ui.button({ glyph = "arrow-left", variant = "ghost", onClick = "onBack" }),
    ui.input({
      key = "rename-" .. current,
      value = displayName(current),
      onSubmit = "onRename",
      -- The scratchpad's identity is its name; renaming it would just respawn it.
      enabled = current ~= scratchName(),
      flexGrow = 1,
    }),
  }
  for _, node in ipairs(trailing) do
    table.insert(children, node)
  end
  return ui.row({ gap = 6, align = "center" }, children)
end

local function editorView()
  return ui.column({ flexGrow = 1, gap = 8, align = "stretch" }, {
    editorHeader(),
    ui.input({
      -- The rev reseeds the (uncontrolled) editor when the file changed under us.
      key = "editor-" .. current .. "-" .. editorRev,
      value = buffer,
      multiline = true,
      focus = true,
      flexGrow = 1,
      placeholder = tr("editor_placeholder"),
      onChange = "onEdited",
      onSubmit = "onFlushNow",
    }),
    ui.label({
      text = editorStatusLine(),
      fontSize = 11,
      color = "on_surface_variant",
    }),
  })
end

-- --------------------------------------------------------------- sync view
--
-- Lo que antes era el panel de `faminec/notes-sync`, integrado aqui como una
-- vista mas: se abre con el boton de ajustes de la cabecera y muestra el
-- estado del servidor, del celular, la cola de mensajes y la nota actual.
-- El servicio del plugin publica todo en `noctalia.state` ("notes_sync").

local function readSync()
  local value = noctalia.state.get("notes_sync")
  if type(value) == "table" then
    return value
  end
  return {}
end

local function statusRow(label, value, color)
  return ui.row({ gap = 8, align = "center" }, {
    ui.label({ text = label, color = "on_surface_variant", fontSize = 12, flexGrow = 1 }),
    ui.label({ text = value, color = color or "on_surface", fontSize = 12 }),
  })
end

local function syncCurrentNote()
  local s = readSync()
  if type(s.currentNote) == "string" and s.currentNote ~= "" then
    return s.currentNote, s.currentOpen == true
  end
  return nil, false
end

local function syncView()
  local s = readSync()
  local rows = {}

  table.insert(rows, statusRow(
    tr("label_server"),
    s.serverUp and tr("value_online") or tr("value_offline"),
    s.serverUp and "primary" or "error"
  ))
  table.insert(rows, statusRow(
    tr("label_phone"),
    s.phoneConnected and tr("value_connected") or tr("value_disconnected"),
    s.phoneConnected and "primary" or "on_surface_variant"
  ))
  local pending = tonumber(s.pending) or 0
  table.insert(rows, statusRow(
    tr("label_pending"),
    tostring(pending),
    pending > 0 and "warning" or "on_surface_variant"
  ))
  table.insert(rows, statusRow(tr("label_notes"), tostring(tonumber(s.notes) or 0), "on_surface"))

  local seen = tonumber(s.lastSeen) or 0
  local seenText
  if seen == 0 then
    seenText = tr("value_never")
  else
    local minutes = math.floor((os.time() * 1000 - seen) / 60000)
    if minutes < 1 then
      seenText = tr("value_just_now")
    elseif minutes < 60 then
      seenText = tr("value_minutes", { count = minutes })
    else
      seenText = tr("value_hours", { count = math.floor(minutes / 60) })
    end
  end
  table.insert(rows, statusRow(tr("label_last_seen"), seenText, "on_surface_variant"))

  local name, isOpen = syncCurrentNote()
  if name == nil then
    table.insert(rows, statusRow(tr("label_note"), tr("value_no_note"), "on_surface_variant"))
  elseif isOpen then
    table.insert(rows, statusRow(tr("label_note"), name, "on_surface"))
  else
    table.insert(rows, statusRow(tr("label_note"), tr("value_last_note", { name = name }), "on_surface"))
  end

  table.insert(rows, statusRow(tr("label_url"), tostring(s.url or ""), "on_surface_variant"))
  if s.error ~= nil and s.error ~= "" then
    table.insert(rows, ui.label({ text = tostring(s.error), color = "error", fontSize = 11 }))
  end

  table.insert(rows, ui.label({ text = " ", fontSize = 4 }))
  table.insert(rows, ui.row({ gap = 8 }, {
    ui.button({ glyph = "notes", variant = "primary", onClick = "onBackToNotes" }),
    ui.button({
      glyph = "send",
      variant = "ghost",
      onClick = "onSendCurrent",
      enabled = name ~= nil,
    }),
  }))
  table.insert(rows, ui.row({ gap = 8 }, {
    ui.button({ glyph = "refresh", variant = "ghost", onClick = "onRefreshSync" }),
    ui.button({ glyph = "settings", variant = "ghost", onClick = "onOpenSyncSettings" }),
  }))

  return ui.column({ flexGrow = 1, gap = 8, align = "stretch" }, rows)
end

function onOpenSync()
  view = "sync"
  -- Pide estado fresco al servicio: sin esto la vista podria tardar hasta un
  -- tic de sondeo en reflejar el estado real.
  noctalia.runAsync("noctalia msg plugin " .. PANEL_ID:gsub(":panel$", ":service") .. " all refresh")
  render()
end

function onBackToNotes()
  view = "list"
  refreshFiles()
  render()
end

function onRefreshSync()
  noctalia.runAsync("noctalia msg plugin " .. PANEL_ID:gsub(":panel$", ":service") .. " all refresh")
end

function onSendCurrent()
  local name = syncCurrentNote()
  if name == nil then
    noctalia.notifyError(tr("title"), tr("errors.no_note_open"))
    return
  end
  noctalia.runAsync(
    "noctalia msg plugin "
      .. PANEL_ID:gsub(":panel$", ":service")
      .. " all cmd '{\"op\":\"send-current\"}'"
  )
end

function onOpenSyncSettings()
  noctalia.openSettings()
end

render = function()
  local isEditor = view == "editor" and current ~= nil
  local isSync = view == "sync"
  local header = {
    ui.label({ text = tr("title"), fontSize = 16, fontWeight = "bold", color = "on_surface", flexGrow = 1 }),
  }
  if isSync then
    table.insert(header, ui.button({
      key = "header-back",
      glyph = "arrow-left",
      variant = "ghost",
      onClick = "onBackToNotes",
    }))
  else
    if not isEditor then
      table.insert(header, ui.button({
        key = "header-sort",
        glyph = sortByDate and "history" or "sort-ascending-letters",
        variant = "ghost",
        onClick = "onToggleSort",
      }))
      table.insert(header, ui.button({
        key = "header-sync",
        glyph = "cloud",
        variant = "ghost",
        onClick = "onOpenSync",
      }))
    end
    table.insert(header, ui.button({ key = "header-new", glyph = "plus", variant = "primary", onClick = "onNewNote" }))
  end
  if closeButton then
    table.insert(header, ui.button({ key = "header-close", glyph = "xmark", variant = "ghost", onClick = "onClosePanel" }))
  end
  panel.render(ui.column({ flexGrow = 1, gap = 12, align = "stretch" }, {
    ui.row({ align = "center", gap = 8 }, header),
    isSync and syncView() or (isEditor and editorView() or listView()),
  }))
end

function onOpen(_context)
  notesDir = noctalia.expandPath(noctalia.getConfig("notes_dir"))
  cornerRadiusScale = noctalia.getSetting("shell.corner_radius_scale")
  closeButton = noctalia.getSetting("shell.show_close_buttons") ~= false
  local extension = noctalia.string.trim(noctalia.getConfig("extension")):gsub("^%.", "")
  if extension == "" then
    noctalia.notifyError(tr("title"), tr("bad_extension"))
    extension = "md"
  end
  suffix = "." .. extension
  -- A note left open under a different extension setting no longer matches.
  if current ~= nil and not hasSuffix(current) then
    current = nil
    buffer = ""
    dirty = false
    view = "list"
  end
  local ok, err = noctalia.mkdirAll(notesDir)
  if not ok then
    noctalia.notifyError(tr("title"), err or "")
  end
  loadPins()
  refreshFiles()
  pendingDelete = nil
  panel.setWantsSecondTicks(true)
  -- The launcher entry hands over a target through the shared state: either
  -- the note list ("open_home") or a specific note ("open_note").
  if noctalia.state.get("open_home") == true then
    noctalia.state.set("open_home", false)
    flush()
    view = "list"
    current = nil
    buffer = ""
    dirty = false
    render()
    return
  end
  local target = noctalia.state.get("open_note")
  if type(target) == "string" and target ~= "" then
    noctalia.state.set("open_note", "")
    openNote(target)
    return
  end
  render()
end

function onOpenScratchpad()
  openNote(scratchName())
end

function onClose()
  flush()
  -- El panel se cierra: ya no hay ninguna nota ABIERTA, pero la ultima con
  -- la que se trabajo sigue publicada (para poder mandarla al celular).
  current = nil
  buffer = ""
  noctalia.state.set("notes_current", "")
  publishCurrent()
end

function update()
  if dirty then
    idleTicks += 1
    if idleTicks >= AUTOSAVE_IDLE_TICKS then
      flush()
      render()
    end
  end
  checkExternalChanges()
end

function onEdited(value)
  buffer = value
  idleTicks = 0
  dirty = true
  -- Re-render on every edit: the status line carries the live word/char count.
  render()
end

function onToggleSort()
  sortByDate = not sortByDate
  refreshFiles()
  render()
end

function onFlushNow(value)
  buffer = value
  dirty = true
  flush()
  render()
end

function onNewNote()
  flush()
  local name = uniqueNoteName()
  local ok, err = noctalia.writeFile(notePath(name), "")
  if not ok then
    noctalia.notifyError(tr("title"), err or tr("save_failed"))
    return
  end
  refreshFiles()
  openNote(name)
end

function onRename(value)
  if current == nil then
    return
  end
  local name = noctalia.string.trim(value):gsub("/", "")
  if name == "" or name == displayName(current) then
    render()
    return
  end
  local target = name .. suffix
  if noctalia.fileExists(notePath(target)) then
    noctalia.notifyError(tr("title"), tr("rename_exists"))
    render()
    return
  end
  flush()
  local ok, err = noctalia.renameFile(notePath(current), notePath(target))
  if not ok then
    noctalia.notifyError(tr("title"), err or "")
    render()
    return
  end
  if pins[current] ~= nil then
    pins[current] = nil
    pins[target] = true
    savePins()
  end
  current = target
  lastNote = target
  -- El estado publico tambien se renombra: si no, el resto de plugins leen
  -- un nombre que ya no existe.
  noctalia.state.set("notes_current", target)
  refreshFiles()
  -- La nota ya no se llama igual: se vuelve a publicar para que el canal con
  -- el otro plugin no mande un nombre que ya no existe.
  publishCurrent()
  render()
end

function onEditorDelete()
  pendingDelete = current
  render()
end

function onBack()
  flush()
  view = "list"
  current = nil
  buffer = ""
  pendingDelete = nil
  noctalia.state.set("notes_current", "")
  publishCurrent()
  refreshFiles()
  render()
end

function onClosePanel()
  panel.close()
end

function onRowHover(state, key)
  hoveredKey = (state == "true") and key or nil
  render()
end

-- The launcher entry bumps "notes_bump" after writing note files (quick-capture
-- appends, new notes). Fold external changes into the open editor: an appended
-- tail is grafted onto whatever is being typed; other divergence only replaces
-- the buffer when there are no unsaved edits.
function onExternalChange()
  if notesDir == "" then
    return -- never opened; nothing resolved yet
  end
  -- El estado publico se mantiene al dia (por si el nombre cambio fuera).
  noctalia.state.set("notes_current", current or "")
  loadPins()
  refreshFiles()
  if current ~= nil then
    if not noctalia.fileExists(notePath(current)) then
      -- La nota se borro o se renombro desde fuera (el movil, una
      -- sincronizacion). Sin esto el panel se queda con un fantasma: un
      -- nombre que ya no existe y un editor vacio, y el canal con el otro
      -- plugin mandaria esa nota inexistente.
      current = nil
      buffer = ""
      loadedContent = ""
      dirty = false
      view = "list"
      lastNote = ""
      lastContent = ""
      noctalia.state.set("notes_current", "")
      publishCurrent()
      render()
      return
    end
    local contents = noctalia.readFile(notePath(current)) or ""
    if contents ~= loadedContent and contents ~= conflictRemote then
      -- La nota cambio desde fuera (el movil, un editor, una sincronizacion).
      -- Se compara con lo que hay en el editor: si solo cambio fuera, se
      -- adopta; si los dos anadieron texto, se combinan; si las dos versiones
      -- son incompatibles, no se pisa nada y el texto del usuario se guarda
      -- en .conflicts/.
      local r = merge.resolve(loadedContent, buffer, contents)
      if r.status == "remote" or r.status == "same" then
        buffer = r.content
        loadedContent = r.content
        dirty = false
        idleTicks = 0
        editorRev += 1
        conflictRemote = nil
        publishCurrent()
      elseif r.status == "merged" then
        local ok = noctalia.writeFile(notePath(current), r.content)
        if ok then
          buffer = r.content
          loadedContent = r.content
          dirty = false
          idleTicks = 0
          editorRev += 1
          conflictRemote = nil
          publishCurrent()
        end
      else
        conflictRemote = contents
        local path = conflictCopy(current, buffer)
        noctalia.notifyError(tr("title"), tr("errors.conflict"))
        if path ~= nil then
          noctalia.notifyError(tr("title"), tr("errors.conflict_saved"))
        end
        -- El buffer no se toca: el autoguardado lo intentara otra vez y, si
        -- el usuario deja de editar, el texto se queda a salvo en la copia.
        publishCurrent()
      end
    end
  end
  render()
end

-- Cheap fingerprint of the notes directory: file names plus size and mtime.
-- It spots edits made outside the panel (mobile app, sync tool, text editor).
local function dirSignature()
  if notesDir == "" then
    return ""
  end
  local list = noctalia.listDir(notesDir)
  if list == nil then
    return ""
  end
  table.sort(list)
  local parts = {}
  for _, name in ipairs(list) do
    -- Solo las notas y el archivo de fijados: otros archivos de la carpeta
    -- no interesan al panel.
    local isNote = name:sub(1, 1) ~= "." and hasSuffix(name)
    local isPins = name == ".pinned.json"
    if isNote or isPins then
      local info = noctalia.fileInfo(notePath(name))
      local size = info ~= nil and info.size or 0
      local mtime = info ~= nil and info.mtime or 0
      table.insert(parts, name .. ":" .. size .. ":" .. mtime)
    end
  end
  return table.concat(parts, "|")
end

-- Called on every panel tick: pulls in whatever changed outside the panel.
function checkExternalChanges()
  if notesDir == "" then
    return
  end
  if noctalia.getConfig("watch") == false then
    return
  end
  local signature = dirSignature()
  local changed = signature ~= watchedSignature
  watchedSignature = signature
  if not changed and current ~= nil then
    -- Same second, same size: compare the contents of the open note.
    local contents = noctalia.readFile(notePath(current)) or ""
    changed = contents ~= loadedContent
  end
  if changed then
    onExternalChange()
  end
end

-- IPC entry point: `noctalia msg plugin faminec/notes:panel all <event> [payload]`
function onIpc(event, payload)
  local ok, err = pcall(function()
    if event == "refresh" then
      watchedSignature = nil
      onExternalChange()
      return
    end
    if event == "open-note" then
      if type(payload) == "string" and payload ~= "" then
        openNote(hasSuffix(payload) and payload or (payload .. suffix))
      end
      return
    end
    if event == "open-home" then
      flush()
      view = "list"
      current = nil
      buffer = ""
      dirty = false
      refreshFiles()
      render()
    end
  end)
  if not ok then
    noctalia.log("notes: onIpc failed: " .. tostring(err))
  end
end

noctalia.state.watch("notes_bump", function(_value)
  onExternalChange()
end)

-- El servicio publica el estado del servidor/celular en `notes_sync`. La
-- vista de sincronizacion lo pinta: hay que repintar cuando llegue.
noctalia.state.watch("notes_sync", function(_value)
  if view == "sync" then
    render()
  end
end)
