--!nonstrict
-- Panel del carrusel de letras: abre la ventana flotante y ofrece
-- interruptores rápidos que se guardan en el fichero de overrides.
--
-- Precedencia de los ajustes:
--   overrides.json  >  settings.toml (plugin_settings)  >  valores por defecto
-- El script de Python lee los mismos tres sitios, así que los cambios se
-- aplican en caliente a la ventana que ya esté abierta.

local DEFAULTS = {
  font_family = "Departure Mono",
  font_size = 22,
  direction = "down",
  marker = false,
  karaoke = true,
  equalizer = false,
  footer = false,
  hints = false,
  header = false,
  spacing = 2,
  animation_ms = 650,
  ghost = true,
  offset_ms = 0,
  width = 1200,
  height = 820,
  anchor = "center",
}

local BOOL_KEYS = { marker = true, karaoke = true, equalizer = true, footer = true, hints = true, header = true, ghost = true }
local INT_KEYS = { font_size = true, spacing = true, animation_ms = true, offset_ms = true, width = true, height = true }

-- Solo fuentes monoespaciadas: kitty descarta las proporcionales.
local FONT_CHOICES = {
  "Departure Mono",
  "Press Start 2P",
  "Space Mono",
  "NType 82 Mono",
  "Lettera Mono LL",
  "IBM Plex Mono",
}

local overrides = {}
local trackTitle = ""
local trackArtist = ""
local launching = false

local function tr(key, args)
  return noctalia.tr(key, args)
end

local function dataDir()
  return noctalia.pluginDataDir() or (noctalia.getenv("HOME") or "") .. "/.local/state/noctalia/plugins/data/faminec/lyrics-carousel"
end

local function overridePath()
  return dataDir() .. "/overrides.json"
end

local function loadOverrides()
  local raw = noctalia.readFile(overridePath())
  if raw == nil or raw == "" then
    overrides = {}
    return
  end
  local ok, data = pcall(noctalia.json.decode, raw)
  if ok and type(data) == "table" then
    overrides = data
  else
    overrides = {}
  end
end

local function saveOverrides()
  local dir = dataDir()
  noctalia.mkdirAll(dir)
  noctalia.writeFile(overridePath(), noctalia.json.encode(overrides))
end

local function baseValue(key)
  local value = noctalia.getConfig(key)
  if value == nil then
    return DEFAULTS[key]
  end
  return value
end

local function effective(key)
  local value = overrides[key]
  if value == nil then
    value = baseValue(key)
  end
  if BOOL_KEYS[key] then
    return value == true
  end
  if INT_KEYS[key] then
    return tonumber(value) or DEFAULTS[key]
  end
  return value
end

local function setOverride(key, value)
  overrides[key] = value
  saveOverrides()
  render()
end

local function toggleKey(key)
  setOverride(key, not effective(key))
end

-- ---------------------------------------------------------------- launching

local function shellQuote(value)
  return "'" .. tostring(value):gsub("'", "'\\''") .. "'"
end

local function luaQuote(value)
  local escaped = tostring(value)
  escaped = escaped:gsub("\\", "\\\\")
  escaped = escaped:gsub('"', '\\"')
  escaped = escaped:gsub("\r", "\\r")
  escaped = escaped:gsub("\n", "\\n")
  return '"' .. escaped .. '"'
end

local ANCHORS = {
  ["top-left"] = true,
  ["top-center"] = true,
  ["top-right"] = true,
  ["left-center"] = true,
  ["center"] = true,
  ["right-center"] = true,
  ["bottom-left"] = true,
  ["bottom-center"] = true,
  ["bottom-right"] = true,
}

local ANCHOR_ALIASES = {
  ["topleft"] = "top-left",
  ["topcenter"] = "top-center",
  ["topright"] = "top-right",
  ["left"] = "left-center",
  ["leftcenter"] = "left-center",
  ["middle"] = "center",
  ["centro"] = "center",
  ["right"] = "right-center",
  ["rightcenter"] = "right-center",
  ["bottomleft"] = "bottom-left",
  ["bottomcenter"] = "bottom-center",
  ["bottomright"] = "bottom-right",
  ["top"] = "top-center",
  ["bottom"] = "bottom-center",
  ["arriba"] = "top-center",
  ["abajo"] = "bottom-center",
  ["izquierda"] = "left-center",
  ["derecha"] = "right-center",
}

local function normalizeAnchor(value)
  local key = tostring(value or ""):lower():gsub("%s+", "-"):gsub("_", "-"):gsub("%-+", "-")
  key = key:gsub("^%-", ""):gsub("%-$", "")
  if ANCHORS[key] then
    return key
  end
  return ANCHOR_ALIASES[key] or "center"
end

local function outputGeometry()
  local outputs = noctalia.outputs() or {}
  local chosen = nil
  for _, output in ipairs(outputs) do
    if output.focused then
      chosen = output
      break
    end
  end
  chosen = chosen or outputs[1]
  if chosen ~= nil then
    local width = tonumber(chosen.width) or 0
    local height = tonumber(chosen.height) or 0
    if width >= 320 and height >= 240 then
      return math.floor(width), math.floor(height)
    end
  end
  return 1920, 1080
end

local function anchorPosition(anchor, width, height, screenWidth, screenHeight)
  local margin = 16
  local x
  local y
  if anchor == "top-left" or anchor == "left-center" or anchor == "bottom-left" then
    x = margin
  elseif anchor == "top-right" or anchor == "right-center" or anchor == "bottom-right" then
    x = screenWidth - width - margin
  else
    x = math.floor((screenWidth - width) / 2)
  end
  if anchor == "top-left" or anchor == "top-center" or anchor == "top-right" then
    y = margin
  elseif anchor == "bottom-left" or anchor == "bottom-center" or anchor == "bottom-right" then
    y = screenHeight - height - margin
  else
    y = math.floor((screenHeight - height) / 2)
  end
  return x, y
end

local function dispatch(expression, callback)
  local started = noctalia.runAsync({ "hyprctl", "dispatch", expression }, function(result)
    if result.exitCode ~= 0 then
      local detail = result.stderr or result.stdout or ""
      if detail ~= nil and detail ~= "" then
        noctalia.log("lyrics-carousel: " .. tostring(detail))
      end
    end
    if callback ~= nil then
      callback(result.exitCode == 0)
    end
  end)
  if not started and callback ~= nil then
    callback(false)
  end
end

local function launch()
  if launching then
    return
  end
  launching = true
  local family = tostring(effective("font_family") or DEFAULTS.font_family)
  local size = tonumber(effective("font_size")) or DEFAULTS.font_size
  local width = tonumber(effective("width")) or DEFAULTS.width
  local height = tonumber(effective("height")) or DEFAULTS.height
  local anchor = normalizeAnchor(effective("anchor"))

  local screenWidth, screenHeight = outputGeometry()
  local x, y = anchorPosition(anchor, width, height, screenWidth, screenHeight)

  local command = string.format(
    "kitty -o confirm_os_window_close=0 -o font_family=%s -o font_size=%d --class noctalia-term-lyrics --title lyrics -e sh -lc %s",
    shellQuote(family),
    math.floor(size),
    shellQuote("lyrics-carousel")
  )
  local rules = string.format(
    "{ float = true, move = { %d, %d }, size = { %d, %d } }",
    x, y, width, height
  )
  local expression = string.format("hl.dsp.exec_cmd(%s, %s)", luaQuote(command), rules)

  -- Reinicia la ventana anterior para que recoja la tipografía nueva.
  noctalia.runAsync({ "pkill", "-f", "noctalia-term-lyrics --title lyrics" }, function()
    noctalia.runAsync({ "sleep", "0.25" }, function()
      dispatch(expression, function(ok)
        launching = false
        if not ok then
          noctalia.notifyError(tr("title"), tr("launch_failed"))
        else
          panel.close()
        end
      end)
    end)
  end)
end

-- ------------------------------------------------------------------- mp3 info

local function readTrack()
  noctalia.runAsync({ "playerctl", "-a", "metadata", "--format", "{{title}}\t{{artist}}" }, function(result)
    if result.exitCode ~= 0 or result.stdout == nil or result.stdout == "" then
      trackTitle = ""
      trackArtist = ""
      render()
      return
    end
    local first = result.stdout:split("\n")[1] or ""
    local parts = {}
    for part in first:gmatch("[^\t]+") do
      parts[#parts + 1] = part
    end
    trackTitle = parts[1] or ""
    trackArtist = parts[2] or ""
    render()
  end)
end

-- --------------------------------------------------------------------- UI

local function toggleRow(key, label, glyph)
  return ui.row({ align = "center", gap = 10, paddingH = 4, padding = 4 }, {
    ui.glyph({ name = glyph, size = 14, color = "on_surface_variant" }),
    ui.label({ text = label, fontSize = 12, color = "on_surface", flexGrow = 1 }),
    ui.toggle({
      checked = effective(key),
      onChange = function(value)
        setOverride(key, value == true)
      end,
    }),
  })
end

local function fontChips()
  local current = tostring(effective("font_family"))
  local rows = {}
  local row = {}
  for index, name in ipairs(FONT_CHOICES) do
    local selected = name == current
    table.insert(row, ui.button({
      key = "font-" .. name,
      text = name,
      variant = selected and "tonal" or "ghost",
      fontSize = 11,
      onClick = function()
        setOverride("font_family", name)
        launch()
      end,
    }))
    if index % 3 == 0 and index < #FONT_CHOICES then
      table.insert(rows, ui.row({ gap = 6 }, row))
      row = {}
    end
  end
  if #row > 0 then
    table.insert(rows, ui.row({ gap = 6 }, row))
  end
  return ui.column({ gap = 6 }, rows)
end

local function sizeChips()
  local chips = {}
  local current = tonumber(effective("font_size"))
  for _, size in ipairs({ 14, 18, 22, 26, 30 }) do
    local selected = size == current
    table.insert(chips, ui.button({
      key = "size-" .. size,
      text = tostring(size),
      variant = selected and "tonal" or "ghost",
      fontSize = 11,
      onClick = function()
        setOverride("font_size", size)
        launch()
      end,
    }))
  end
  return ui.row({ gap = 6 }, chips)
end

function render()
  local direction = tostring(effective("direction"))
  local subtitle = tr("subtitle")
  if trackTitle ~= "" then
    subtitle = trackTitle
    if trackArtist ~= "" then
      subtitle = subtitle .. " — " .. trackArtist
    end
  end

  local rows = {
    ui.row({ align = "center", gap = 8 }, {
      ui.glyph({ name = "music", size = 18, color = "primary" }),
      ui.label({ text = tr("title"), fontSize = 16, fontWeight = "bold", color = "on_surface", flexGrow = 1 }),
      ui.button({
        key = "open-settings",
        glyph = "settings",
        variant = "ghost",
        tooltip = tr("open_settings"),
        onClick = function()
          noctalia.openSettings()
        end,
      }),
      ui.button({
        key = "close-panel",
        glyph = "close",
        variant = "ghost",
        tooltip = tr("close"),
        onClick = function()
          panel.close()
        end,
      }),
    }),
    ui.label({ text = subtitle, fontSize = 11, color = "on_surface_variant" }),
    ui.button({
      key = "launch",
      text = tr("launch"),
      variant = "tonal",
      onClick = launch,
    }),
    ui.separator({ thickness = 1, color = "outline/0.25", spacing = 6 }),
    ui.label({ text = tr("section_display"), fontSize = 11, fontWeight = "bold", color = "on_surface_variant" }),
    ui.row({ align = "center", gap = 10, paddingH = 4, padding = 4 }, {
      ui.glyph({ name = "arrow-down-up", size = 14, color = "on_surface_variant" }),
      ui.label({ text = tr("direction"), fontSize = 12, color = "on_surface", flexGrow = 1 }),
      ui.button({
        key = "dir-down",
        text = tr("down"),
        variant = direction == "down" and "tonal" or "ghost",
        fontSize = 11,
        onClick = function()
          setOverride("direction", "down")
        end,
      }),
      ui.button({
        key = "dir-up",
        text = tr("up"),
        variant = direction == "up" and "tonal" or "ghost",
        fontSize = 11,
        onClick = function()
          setOverride("direction", "up")
        end,
      }),
    }),
    toggleRow("karaoke", tr("karaoke"), "sun"),
    toggleRow("marker", tr("marker"), "chevron-right"),
    toggleRow("header", tr("header"), "heading"),
    toggleRow("footer", tr("footer"), "timer"),
    toggleRow("hints", tr("hints"), "keyboard"),
    toggleRow("equalizer", tr("equalizer"), "audio-lines"),
    toggleRow("ghost", tr("ghost"), "sparkles"),
    ui.separator({ thickness = 1, color = "outline/0.25", spacing = 6 }),
    ui.label({ text = tr("section_font"), fontSize = 11, fontWeight = "bold", color = "on_surface_variant" }),
    fontChips(),
    ui.row({ align = "center", gap = 8 }, {
      ui.label({ text = tr("font_size"), fontSize = 11, color = "on_surface_variant" }),
      sizeChips(),
    }),
    ui.label({ text = tr("hint"), fontSize = 10, color = "on_surface_variant" }),
  }

  panel.render(ui.column({ flexGrow = 1, gap = 8, align = "stretch" }, rows))
end

function onOpen()
  loadOverrides()
  readTrack()
  render()
end

function onClose()
end

function onConfigChanged()
  loadOverrides()
  render()
end

function onIpc(event, payload)
  if event == "launch" then
    launch()
  elseif event == "refresh" then
    loadOverrides()
    readTrack()
    render()
  end
end

loadOverrides()
