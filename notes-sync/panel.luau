--!nonstrict
-- Panel de sincronizacion: el puente entre el computador y el celular.
--
-- Muestra el estado del servidor y del celular y ofrece las acciones del
-- contrato IPC:
--
--   * abrir el panel de notas en el computador
--   * mandar al celular la nota que esta abierta
--   * sincronizar ahora
--   * abrir los ajustes del plugin de notas

local PANEL_ID = "faminec/notes-sync:panel"

local sync = {}
local busy = false

local function tr(key, params)
  if params ~= nil then
    return noctalia.tr(key, params)
  end
  return noctalia.tr(key)
end

local function notesPluginId()
  local id = noctalia.getConfig("notes_plugin")
  if type(id) == "string" and id ~= "" then
    return id
  end
  return "faminec/notes"
end

local function notesPanelId()
  return notesPluginId() .. ":panel"
end

-- La nota abierta la publica el servicio (que la lee del canal compartido con
-- el plugin de notas).
local function currentNote()
  local sync = noctalia.state.get("notes_sync")
  if type(sync) == "table" and type(sync.currentNote) == "string" then
    return sync.currentNote ~= "" and sync.currentNote or nil
  end
  return nil
end

-- ------------------------------------------------------- estado del servidor

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

local function serverRow()
  local s = readSync()
  if s.serverUp then
    return statusRow(tr("label_server"), tr("value_online"), "primary")
  end
  return statusRow(tr("label_server"), tr("value_offline"), "error")
end

local function phoneRow()
  local s = readSync()
  if s.phoneConnected then
    return statusRow(tr("label_phone"), tr("value_connected"), "primary")
  end
  return statusRow(tr("label_phone"), tr("value_disconnected"), "on_surface_variant")
end

local function pendingRow()
  local s = readSync()
  local pending = tonumber(s.pending) or 0
  local color = "on_surface_variant"
  if pending > 0 then
    color = "warning"
  end
  return statusRow(tr("label_pending"), tostring(pending), color)
end

local function notesRow()
  local s = readSync()
  return statusRow(tr("label_notes"), tostring(tonumber(s.notes) or 0), "on_surface")
end

local function lastSeenRow()
  local s = readSync()
  local seen = tonumber(s.lastSeen) or 0
  if seen == 0 then
    return statusRow(tr("label_last_seen"), tr("value_never"), "on_surface_variant")
  end
  local minutes = math.floor((os.time() * 1000 - seen) / 60000)
  local text
  if minutes < 1 then
    text = tr("value_just_now")
  elseif minutes < 60 then
    text = tr("value_minutes", { count = minutes })
  else
    text = tr("value_hours", { count = math.floor(minutes / 60) })
  end
  return statusRow(tr("label_last_seen"), text, "on_surface_variant")
end

local function urlRow()
  local s = readSync()
  return statusRow(tr("label_url"), tostring(s.url or ""), "on_surface_variant")
end

-- ------------------------------------------------------------------ acciones

-- Cita un texto para el shell (las comillas simples de dentro se cierran y
-- se reabren).
local function shellQuote(text)
  local s = tostring(text)
  s = s:gsub("'", "'\\''")
  return "'" .. s .. "'"
end

local function serviceId()
  return PANEL_ID:gsub(":panel$", ":service")
end

local function onOpenNotes()
  noctalia.runAsync("noctalia msg panel-open " .. shellQuote(notesPanelId()))
end

local function onSendCurrent()
  local name = currentNote()
  if name == nil then
    noctalia.notifyError(tr("title"), tr("errors.no_note_open"))
    return
  end
  busy = true
  render()
  -- Se delega en el servicio: el es el que habla con el servidor.
  noctalia.runAsync(
    "noctalia msg plugin "
      .. shellQuote(serviceId())
      .. " all cmd "
      .. shellQuote('{"op":"send-current"}')
  )
  busy = false
  render()
end

local function onRefresh()
  noctalia.runAsync("noctalia msg plugin " .. shellQuote(serviceId()) .. " all refresh")
end

local function onOpenSettings()
  noctalia.openSettings()
end

-- ------------------------------------------------------------------ render

local render

local function body()
  local s = readSync()
  local rows = {}

  table.insert(rows, ui.label({
    text = tr("title"),
    fontSize = 16,
    fontWeight = "bold",
    color = "on_surface",
  }))

  table.insert(rows, ui.row({ gap = 8, align = "center" }, {
    serverRow(),
  }))
  table.insert(rows, phoneRow())
  table.insert(rows, pendingRow())
  table.insert(rows, notesRow())
  table.insert(rows, lastSeenRow())
  table.insert(rows, urlRow())

  if s.error ~= nil and s.error ~= "" then
    table.insert(rows, ui.label({ text = tostring(s.error), color = "error", fontSize = 11 }))
  end

  table.insert(rows, ui.label({ text = " ", fontSize = 4 }))

  table.insert(rows, ui.row({ gap = 8 }, {
    ui.button({ glyph = "notes", variant = "primary", onClick = "onOpenNotes" }),
    ui.button({
      glyph = "send",
      variant = "ghost",
      onClick = "onSendCurrent",
      enabled = not busy and currentNote() ~= nil,
    }),
  }))

  table.insert(rows, ui.row({ gap = 8 }, {
    ui.button({ glyph = "refresh", variant = "ghost", onClick = "onRefresh" }),
    ui.button({ glyph = "settings", variant = "ghost", onClick = "onOpenSettings" }),
  }))

  return ui.column({ flexGrow = 1, gap = 8, align = "stretch" }, rows)
end

render = function()
  panel.render(body())
end

function onOpen(_context)
  render()
end

function update()
  render()
end

noctalia.state.watch("notes_sync", function()
  render()
end)

render()
