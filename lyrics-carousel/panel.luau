--!nonstrict
-- Panel del carrusel de letras: abre la ventana flotante y ofrece
-- interruptores rápidos.
--
-- Los ajustes viven en el settings.toml de Noctalia
-- (`plugin_settings."faminec/lyrics-carousel"`), que es la misma fuente que
-- usa la página de ajustes del plugin. El panel escribe ahí con un helper
-- Python y recarga la configuración, así que ambos sitios siempre coinciden.
-- El script de Python lee ese mismo fichero, por lo que los cambios se
-- aplican en caliente a la ventana que ya esté abierta.
--
-- Todas las llamadas a la API de Noctalia van envueltas en `safe`: si una de
-- ellas falla (permisos, disco lleno, API que no existe) el panel avisa en
-- lugar de reventar el script.

local PLUGIN_ID = "faminec/lyrics-carousel"
local SECTION = '[plugin_settings."faminec/lyrics-carousel"]'

local DEFAULTS = {
  font_family = "Departure Mono",
  font_size = 22,
  render_mode = "image",
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
  accent = "primary",
  custom_color = "#e46767",
  active_scale = 1.35,
  visible_above = 6,
  visible_below = 6,
}

local BOOL_KEYS = { marker = true, karaoke = true, equalizer = true, footer = true, hints = true, header = true, ghost = true }
local INT_KEYS = { font_size = true, spacing = true, animation_ms = true, offset_ms = true, width = true, height = true, visible_above = true, visible_below = true }
local FLOAT_KEYS = { active_scale = true }

-- Solo monoespaciadas las acepta kitty; las demas solo valen en modo imagen.
local FONT_CHOICES = {
  "Departure Mono",
  "Press Start 2P",
  "Space Mono",
  "NType 82 Mono",
  "Lettera Mono LL",
  "IBM Plex Mono",
}

local IMAGE_ONLY_FONTS = {
  "Nothing Font (5x7)",
  "Ndot 57",
  "Ndot 55",
  "Space Grotesk",
  "NType 82",
}

local ACCENT_CHOICES = { "primary", "green", "yellow", "blue", "magenta", "cyan", "red", "custom" }

local settings = {}
local pending = {}
local generation = 0
local trackTitle = ""
local trackArtist = ""
local launching = false
local lastError = ""

local function tr(key, args)
  local ok, value = pcall(noctalia.tr, key, args)
  if ok and type(value) == "string" then
    return value
  end
  return key
end

-- --------------------------------------------------------- API protegida --

-- Envuelve una llamada a la API de Noctalia: si falla, se avisa y se sigue.
local function safe(label, fn, ...)
  local args = { ... }
  local ok, result = pcall(fn, table.unpack(args))
  if not ok then
    lastError = tr("write_failed")
    noctalia.log("lyrics-carousel: " .. label .. ": " .. tostring(result))
    return nil
  end
  return result
end

-- Cierra el panel sin reventar si la API falla.
local function closePanel()
  local ok, error = pcall(function()
    panel.close()
  end)
  if not ok then
    safe("log", noctalia.log, "lyrics-carousel: close: " .. tostring(error))
  end
end

local function reportError(message)
  lastError = tostring(message or tr("write_failed"))
  safe("log", noctalia.log, "lyrics-carousel: " .. lastError)
end

local function runAsync(argv, callback)
  local ok, started = pcall(noctalia.runAsync, argv, callback)
  if not ok then
    reportError(started)
    return false
  end
  if started == false then
    reportError(tr("write_failed"))
    return false
  end
  return true
end

-- ------------------------------------------------------------- ajustes

local function settingsPath()
  return (noctalia.getenv("HOME") or "") .. "/.local/state/noctalia/settings.toml"
end

local function parseValue(value)
  if value == "true" then
    return true
  elseif value == "false" then
    return false
  end
  local number = tonumber(value)
  if number ~= nil then
    return number
  end
  return value
end

local function refreshSettings()
  settings = {}
end

local function valueOf(key)
  local value = settings[key]
  if value == nil then
    value = safe("getConfig", noctalia.getConfig, key)
  end
  if value == nil then
    return DEFAULTS[key]
  end
  return value
end

local function boolOf(key)
  return valueOf(key) == true
end

local function numberOf(key)
  return tonumber(valueOf(key)) or DEFAULTS[key]
end

-- Escribe los cambios pendientes y recarga la configuración de Noctalia.
local function flush()
  if next(pending) == nil then
    return
  end
  local pluginDir = safe("pluginDir", noctalia.pluginDir) or ""
  local argv = { "python3", pluginDir .. "/bin/set-setting.py" }
  local keys = {}
  for key in pairs(pending) do
    keys[#keys + 1] = key
  end
  table.sort(keys)
  for _, key in ipairs(keys) do
    local item = pending[key]
    local kind = "string"
    if BOOL_KEYS[key] then
      kind = "bool"
    elseif INT_KEYS[key] then
      kind = "int"
    elseif FLOAT_KEYS[key] then
      kind = "float"
    end
    argv[#argv + 1] = key
    argv[#argv + 1] = tostring(item.value)
    argv[#argv + 1] = kind
  end
  pending = {}
  runAsync(argv, function(result)
    if result == nil or result.exitCode ~= 0 then
      local detail = ""
      if type(result) == "table" then
        detail = tostring(result.stderr or "")
      end
      reportError(detail ~= "" and detail or tr("write_failed"))
      render()
      return
    end
    lastError = ""
    runAsync({ "noctalia", "msg", "config-reload" }, function()
      -- Noctalia ya tiene el valor en memoria: se limpia la caché local.
      settings = {}
      render()
    end)
  end)
end

local function setSetting(key, value, options)
  options = options or {}
  pending[key] = { value = value }
  settings[key] = value
  generation = generation + 1
  local current = generation
  runAsync({ "sleep", "0.35" }, function()
    if current ~= generation then
      return
    end
    flush()
    if options.relaunch then
      launch()
    end
    if options.geometry then
      applyGeometry()
    end
  end)
  render()
end

local function toggleKey(key)
  setSetting(key, not boolOf(key))
end

-- ---------------------------------------------------------------- lanzar

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
  ["centre"] = "center",
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
  local outputs = safe("outputs", noctalia.outputs) or {}
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
  local started = runAsync({ "hyprctl", "dispatch", expression }, function(result)
    if result == nil or result.exitCode ~= 0 then
      local detail = ""
      if type(result) == "table" then
        detail = tostring(result.stderr or result.stdout or "")
      end
      safe("log", noctalia.log, "lyrics-carousel: " .. detail)
    end
    if callback ~= nil then
      callback(result ~= nil and result.exitCode == 0)
    end
  end)
  if not started and callback ~= nil then
    callback(false)
  end
end

-- Mueve y redimensiona la ventana existente sin recrearla.
local function applyGeometry()
  local width = math.floor(numberOf("width"))
  local height = math.floor(numberOf("height"))
  local screenWidth, screenHeight = outputGeometry()
  local x, y = anchorPosition(normalizeAnchor(valueOf("anchor")), width, height, screenWidth, screenHeight)
  local window = "class:^noctalia-lyrics-carousel$"
  local resize = string.format(
    'hl.dsp.window.resize({ x = %d, y = %d, window = "%s" })', width, height, window
  )
  local move = string.format(
    'hl.dsp.window.move({ x = %d, y = %d, window = "%s" })', x, y, window
  )
  dispatch(resize, function()
    dispatch(move)
  end)
end

local function launch()
  if launching then
    return
  end
  launching = true
  -- Watchdog: si la ventana no llega a crearse, el botón no se queda muerto.
  runAsync({ "sleep", "6" }, function()
    if launching then
      launching = false
      render()
    end
  end)
  refreshSettings()
  local family = tostring(valueOf("font_family"))
  local size = math.floor(numberOf("font_size"))
  local width = math.floor(numberOf("width"))
  local height = math.floor(numberOf("height"))
  local anchor = normalizeAnchor(valueOf("anchor"))

  local screenWidth, screenHeight = outputGeometry()
  local x, y = anchorPosition(anchor, width, height, screenWidth, screenHeight)

  local command = string.format(
    "kitty -o confirm_os_window_close=0 -o font_family=%s -o font_size=%d --class noctalia-lyrics-carousel --title lyrics -e sh -lc %s",
    shellQuote(family),
    size,
    shellQuote("lyrics-carousel")
  )
  local rules = string.format(
    "{ float = true, move = { %d, %d }, size = { %d, %d } }",
    x, y, width, height
  )
  local expression = string.format("hl.dsp.exec_cmd(%s, %s)", luaQuote(command), rules)

  -- Reinicia la ventana anterior para que recoja la tipografía nueva.
  local started = runAsync(
    { "pkill", "-f", "noctalia-lyrics-carousel --title lyrics" },
    function()
      local ok = runAsync({ "sleep", "0.25" }, function()
        dispatch(expression, function(success)
          launching = false
          if not success then
            safe("notifyError", noctalia.notifyError, tr("title"), tr("launch_failed"))
          else
            closePanel()
          end
        end)
      end)
      if not ok then
        launching = false
        dispatch(expression, function(success)
          if not success then
            safe("notifyError", noctalia.notifyError, tr("title"), tr("launch_failed"))
          else
            closePanel()
          end
        end)
        render()
      end
    end
  )
  if not started then
    launching = false
    render()
  end
end

-- ------------------------------------------------------------- cancion

local function readTrack()
  local format = "{{playerInstance}}\t{{status}}\t{{title}}\t{{artist}}"
  runAsync({ "playerctl", "-a", "metadata", "--format", format }, function(result)
    if result == nil or result.exitCode ~= 0 or result.stdout == nil or result.stdout == "" then
      trackTitle = ""
      trackArtist = ""
      render()
      return
    end
    local playing = nil
    local fallback = nil
    for line in result.stdout:gmatch("[^\n]+") do
      local parts = {}
      for part in line:gmatch("[^\t]+") do
        parts[#parts + 1] = part
      end
      if #parts >= 4 then
        local entry = { title = parts[3], artist = parts[4] }
        if parts[2] == "Playing" and playing == nil then
          playing = entry
        elseif fallback == nil and entry.title ~= "" then
          fallback = entry
        end
      end
    end
    local chosen = playing or fallback
    trackTitle = chosen and chosen.title or ""
    trackArtist = chosen and chosen.artist or ""
    render()
  end)
end

-- -------------------------------------------------------------------- UI

local function toggleRow(key, label, glyph)
  return ui.row({ align = "center", gap = 10, paddingH = 4, padding = 4 }, {
    ui.glyph({ name = glyph, size = 14, color = "on_surface_variant" }),
    ui.label({ text = label, fontSize = 12, color = "on_surface", flexGrow = 1 }),
    ui.toggle({
      checked = boolOf(key),
      onChange = function(value)
        setSetting(key, value == true)
      end,
    }),
  })
end

local function chipRow(items)
  local chips = {}
  for _, item in ipairs(items) do
    table.insert(chips, ui.button({
      key = item.key,
      text = item.text,
      variant = item.selected and "tonal" or "ghost",
      fontSize = 11,
      onClick = item.onClick,
    }))
  end
  return ui.row({ gap = 6 }, chips)
end

local function fontChips()
  local current = tostring(valueOf("font_family"))
  local rows = {}
  local row = {}
  local index = 0
  for _, name in ipairs(FONT_CHOICES) do
    index = index + 1
    table.insert(row, ui.button({
      key = "font-" .. name,
      text = name,
      variant = name == current and "tonal" or "ghost",
      fontSize = 11,
      onClick = function()
        setSetting("font_family", name, { relaunch = tostring(valueOf("render_mode")) == "text" })
      end,
    }))
    if index % 3 == 0 then
      table.insert(rows, ui.row({ gap = 6 }, row))
      row = {}
    end
  end
  if #row > 0 then
    table.insert(rows, ui.row({ gap = 6 }, row))
  end
  return ui.column({ gap = 6 }, rows)
end

local function imageOnlyFonts()
  local current = tostring(valueOf("font_family"))
  local rows = {}
  local row = {}
  local index = 0
  for _, name in ipairs(IMAGE_ONLY_FONTS) do
    index = index + 1
    table.insert(row, ui.button({
      key = "font-img-" .. name,
      text = name,
      variant = name == current and "tonal" or "ghost",
      fontSize = 11,
      onClick = function()
        setSetting("font_family", name, { relaunch = tostring(valueOf("render_mode")) == "text" })
      end,
    }))
    if index % 2 == 0 then
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
  local current = math.floor(numberOf("font_size"))
  local items = {}
  for _, size in ipairs({ 11, 14, 18, 22, 26, 33 }) do
    table.insert(items, {
      key = "size-" .. size,
      text = tostring(size),
      selected = size == current,
      onClick = function()
        setSetting("font_size", size, { relaunch = tostring(valueOf("render_mode")) == "text" })
      end,
    })
  end
  return chipRow(items)
end

local function scaleChips()
  local current = numberOf("active_scale")
  local items = {}
  for _, value in ipairs({ 1.0, 1.2, 1.35, 1.6, 2.0 }) do
    table.insert(items, {
      key = "scale-" .. tostring(value),
      text = string.format("%.2f", value),
      selected = math.abs(current - value) < 0.01,
      onClick = function()
        setSetting("active_scale", value)
      end,
    })
  end
  return chipRow(items)
end

local function countChips(key, label)
  local current = math.floor(numberOf(key))
  local items = {}
  for _, value in ipairs({ 0, 2, 4, 6, 8, 12 }) do
    table.insert(items, {
      key = key .. "-" .. value,
      text = tostring(value),
      selected = value == current,
      onClick = function()
        setSetting(key, value)
      end,
    })
  end
  return ui.column({ gap = 4 }, {
    ui.label({ text = label, fontSize = 11, color = "on_surface_variant" }),
    chipRow(items),
  })
end

local function accentChips()
  local current = tostring(valueOf("accent"))
  local items = {}
  for _, name in ipairs(ACCENT_CHOICES) do
    table.insert(items, {
      key = "accent-" .. name,
      text = tr("accent_" .. name),
      selected = name == current,
      onClick = function()
        setSetting("accent", name)
      end,
    })
  end
  return ui.column({ gap = 4 }, {
    chipRow(items),
  })
end

local ANCHOR_CHOICES = {
  "top-left", "top-center", "top-right",
  "left-center", "center", "right-center",
  "bottom-left", "bottom-center", "bottom-right",
}

local function anchorChips()
  local current = normalizeAnchor(valueOf("anchor"))
  local rows = {}
  local row = {}
  local index = 0
  for _, name in ipairs(ANCHOR_CHOICES) do
    index = index + 1
    table.insert(row, ui.button({
      key = "anchor-" .. name,
      text = tr("anchor_" .. name:gsub("-", "_")),
      variant = name == current and "tonal" or "ghost",
      fontSize = 10,
      onClick = function()
        setSetting("anchor", name, { geometry = true })
      end,
    }))
    if index % 3 == 0 then
      table.insert(rows, ui.row({ gap = 6 }, row))
      row = {}
    end
  end
  if #row > 0 then
    table.insert(rows, ui.row({ gap = 6 }, row))
  end
  return ui.column({ gap = 6 }, rows)
end

local function windowSizeChips(key, values)
  local current = math.floor(numberOf(key))
  local items = {}
  for _, value in ipairs(values) do
    table.insert(items, {
      key = key .. "-" .. value,
      text = tostring(value),
      selected = value == current,
      onClick = function()
        setSetting(key, value, { geometry = true })
      end,
    })
  end
  return chipRow(items)
end

function render()
  local direction = tostring(valueOf("direction"))
  local mode = tostring(valueOf("render_mode"))
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
          safe("openSettings", noctalia.openSettings)
        end,
      }),
      ui.button({
        key = "close-panel",
        glyph = "close",
        variant = "ghost",
        tooltip = tr("close"),
        onClick = function()
          closePanel()
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
      ui.glyph({ name = "layers", size = 14, color = "on_surface_variant" }),
      ui.label({ text = tr("render_mode"), fontSize = 12, color = "on_surface", flexGrow = 1 }),
      ui.button({
        key = "mode-text",
        text = tr("mode_text"),
        variant = mode == "text" and "tonal" or "ghost",
        fontSize = 11,
        onClick = function()
          setSetting("render_mode", "text")
        end,
      }),
      ui.button({
        key = "mode-image",
        text = tr("mode_image"),
        variant = mode == "image" and "tonal" or "ghost",
        fontSize = 11,
        onClick = function()
          setSetting("render_mode", "image")
        end,
      }),
    }),
    ui.row({ align = "center", gap = 10, paddingH = 4, padding = 4 }, {
      ui.glyph({ name = "arrow-down-up", size = 14, color = "on_surface_variant" }),
      ui.label({ text = tr("direction"), fontSize = 12, color = "on_surface", flexGrow = 1 }),
      ui.button({
        key = "dir-down",
        text = tr("down"),
        variant = direction == "down" and "tonal" or "ghost",
        fontSize = 11,
        onClick = function()
          setSetting("direction", "down")
        end,
      }),
      ui.button({
        key = "dir-up",
        text = tr("up"),
        variant = direction == "up" and "tonal" or "ghost",
        fontSize = 11,
        onClick = function()
          setSetting("direction", "up")
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
    ui.label({ text = tr("section_lyrics"), fontSize = 11, fontWeight = "bold", color = "on_surface_variant" }),
    ui.column({ gap = 4 }, {
      ui.label({ text = tr("active_scale"), fontSize = 11, color = "on_surface_variant" }),
      scaleChips(),
    }),
    ui.row({ gap = 10 }, {
      ui.column({ flexGrow = 1, gap = 4 }, { countChips("visible_above", tr("visible_above")) }),
      ui.column({ flexGrow = 1, gap = 4 }, { countChips("visible_below", tr("visible_below")) }),
    }),
    ui.column({ gap = 4 }, {
      ui.label({ text = tr("accent"), fontSize = 11, color = "on_surface_variant" }),
      accentChips(),
    }),
    ui.separator({ thickness = 1, color = "outline/0.25", spacing = 6 }),
    ui.label({ text = tr("section_window"), fontSize = 11, fontWeight = "bold", color = "on_surface_variant" }),
    ui.label({ text = tr("anchor"), fontSize = 11, color = "on_surface_variant" }),
    anchorChips(),
    ui.row({ gap = 10 }, {
      ui.column({ flexGrow = 1, gap = 4 }, {
        ui.label({ text = tr("width"), fontSize = 11, color = "on_surface_variant" }),
        windowSizeChips("width", { 800, 1000, 1200, 1400, 1600 }),
      }),
      ui.column({ flexGrow = 1, gap = 4 }, {
        ui.label({ text = tr("height"), fontSize = 11, color = "on_surface_variant" }),
        windowSizeChips("height", { 600, 700, 820, 1000 }),
      }),
    }),
    ui.separator({ thickness = 1, color = "outline/0.25", spacing = 6 }),
    ui.label({ text = tr("section_font"), fontSize = 11, fontWeight = "bold", color = "on_surface_variant" }),
    fontChips(),
    ui.label({ text = tr("font_size"), fontSize = 11, color = "on_surface_variant" }),
    sizeChips(),
    ui.label({ text = tr("image_only_fonts"), fontSize = 10, color = "on_surface_variant" }),
    imageOnlyFonts(),
    ui.label({ text = tr("hint"), fontSize = 10, color = "on_surface_variant" }),
  }

  if lastError ~= "" then
    table.insert(rows, ui.label({ text = lastError, fontSize = 10, color = "error" }))
  end

  panel.render(ui.column({ flexGrow = 1, gap = 8, align = "stretch" }, {
    ui.scroll({ flexGrow = 1, gap = 8 }, rows),
  }))
end

function onOpen()
  refreshSettings()
  readTrack()
  render()
end

function onClose()
  flush()
end

function onConfigChanged()
  settings = {}
  render()
end

function onIpc(event, payload)
  if event == "launch" then
    launch()
  elseif event == "toggle" then
    -- Alterna un ajuste booleano: toggle marker
    if type(payload) == "string" and BOOL_KEYS[payload] then
      toggleKey(payload)
    end
  elseif event == "refresh" then
    settings = {}
    readTrack()
    render()
  end
end

refreshSettings()
