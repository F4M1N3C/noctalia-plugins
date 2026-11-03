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

local settingsLib = require("./lib/settings.luau")

-- Los valores por defecto y la lista de claves viven en lib/settings.luau
-- para que el panel, el widget y el script compartan una sola fuente.

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

-- Claves completas: el validador de recursos necesita verlas literales, no
-- concatenadas ("accent_" .. name), o las marca como inexistentes.
local ACCENT_KEYS = {
  primary = "accent_primary",
  green = "accent_green",
  yellow = "accent_yellow",
  blue = "accent_blue",
  magenta = "accent_magenta",
  cyan = "accent_cyan",
  red = "accent_red",
  custom = "accent_custom",
}

-- Las funciones se llaman entre sí (un ajuste lanza la ventana, la ventana
-- avisa al panel, el panel vuelve a dibujar). En Luau un `local function`
-- solo existe desde su declaración: sin estas declaraciones, las llamadas
-- de arriba se resolverían contra un global sin valor (nil).
local render
local launch
local applyGeometry
local closePanel

local settings = {}
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
closePanel = function()
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

-- Vacia los cambios locales: a partir de aqui manda la configuracion real.
local function refreshSettings()
  settings = {}
  settingsLib.refresh()
end

local function valueOf(key)
  -- Lo que el panel acaba de cambiar tiene prioridad; si no, el valor
  -- efectivo (overrides + configuracion de Noctalia).
  local value = settings[key]
  if value ~= nil then
    return value
  end
  return settingsLib.value(key)
end

-- Noctalia entrega los valores de los controles como cadenas: un interruptor
-- manda "true" / "false" (no un booleano). La normalizacion vive en
-- lib/settings.luau para que el panel y el widget la compartan.
local truthy = settingsLib.truthy

local function boolOf(key)
  return truthy(valueOf(key))
end

local function numberOf(key)
  return tonumber(valueOf(key)) or settingsLib.DEFAULTS[key]
end

-- Escribe un ajuste en la capa de overrides del plugin.
--
-- No se escribe en el settings.toml con el panel abierto: Noctalia vigila ese
-- fichero y al cambiarlo recarga la configuracion, lo quecierra el panel que
-- el usuario tiene delante y descarta los clics siguientes. Los overrides se
-- vuelcan al settings.toml al cerrar el panel (ver onClose).
local pendingWrites = 0

local function writeSetting(key, value)
  pendingWrites = pendingWrites + 1
  settingsLib.write(key, value, function(ok)
    pendingWrites = pendingWrites - 1
    if not ok then
      reportError(tr("write_failed"))
      render()
    end
  end)
end

local function setSetting(key, value, options)
  options = options or {}
  settings[key] = value
  -- Se escribe al instante: el widget lo aplica en el acto (lee los
  -- overrides cada 1,2 s) y el panel sigue abierto para más cambios.
  writeSetting(key, value)
  if options.relaunch then
    launch()
  end
  if options.geometry then
    applyGeometry()
  end
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
  ["custom"] = true,
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
applyGeometry = function()
  local width = math.floor(numberOf("width"))
  local height = math.floor(numberOf("height"))
  local anchor = normalizeAnchor(valueOf("anchor"))
  local screenWidth, screenHeight = outputGeometry()
  local x, y
  if anchor == "custom" then
    x = math.floor(numberOf("custom_x"))
    y = math.floor(numberOf("custom_y"))
  else
    x, y = anchorPosition(anchor, width, height, screenWidth, screenHeight)
  end
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

launch = function()
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
  local x, y
  if anchor == "custom" then
    x = math.floor(numberOf("custom_x"))
    y = math.floor(numberOf("custom_y"))
  else
    x, y = anchorPosition(anchor, width, height, screenWidth, screenHeight)
  end

  -- Se lanza el script por ruta absoluta (y con python3): depender del
  -- PATH exigiria un enlace simbolico en ~/.local/bin que el plugin no
  -- crea, y asi tampoco hace falta el bit de ejecucion.
  local script = "lyrics-carousel"
  local pluginDir = noctalia.pluginDir()
  if pluginDir ~= nil and pluginDir ~= "" then
    script = "python3 " .. pluginDir .. "/bin/lyrics-carousel"
  end
  local command = string.format(
    "kitty -o confirm_os_window_close=0 -o font_family=%s -o font_size=%d --class noctalia-lyrics-carousel --title lyrics -e sh -lc %s",
    shellQuote(family),
    size,
    shellQuote(script)
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
          end
        end)
      end)
      if not ok then
        launching = false
        dispatch(expression, function(success)
          if not success then
            safe("notifyError", noctalia.notifyError, tr("title"), tr("launch_failed"))
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
  return ui.row({ key = "row-" .. key, align = "center", gap = 10, paddingH = 4, padding = 4 }, {
    ui.glyph({ name = glyph, size = 14, color = "on_surface_variant" }),
    ui.label({ text = label, fontSize = 12, color = "on_surface", flexGrow = 1 }),
    ui.toggle({
      key = "toggle-" .. key,
      checked = boolOf(key),
      onChange = function(value)
        setSetting(key, truthy(value))
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
      variant = item.selected and "secondary" or "ghost",
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
      variant = name == current and "secondary" or "ghost",
      fontSize = 11,
      onClick = function()
        setSetting("font_family", name)
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
      variant = name == current and "secondary" or "ghost",
      fontSize = 11,
      onClick = function()
        setSetting("font_family", name)
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
        setSetting("font_size", size)
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
  local values = { 0, 2, 4, 6, 8, 12 }
  local rows = {}
  local row = {}
  local index = 0
  for _, value in ipairs(values) do
    index = index + 1
    table.insert(row, ui.button({
      key = key .. "-" .. value,
      text = tostring(value),
      variant = value == current and "secondary" or "ghost",
      fontSize = 11,
      onClick = function()
        setSetting(key, value)
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
  return ui.column({ gap = 4 }, {
    ui.label({ text = label, fontSize = 11, color = "on_surface_variant" }),
    ui.column({ gap = 6 }, rows),
  })
end

local function accentChips()
  local current = tostring(valueOf("accent"))
  local items = {}
  for _, name in ipairs(ACCENT_CHOICES) do
    table.insert(items, {
      key = "accent-" .. name,
      text = tr(ACCENT_KEYS[name]),
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

-- Vacía la caché de letras (el script la guarda en ~/.cache/lyrics-carousel).
-- Se lanza el script con --clear-cache: es el que sabe qué son las letras y
-- qué no (el log de diagnóstico se conserva).
local function clearLyricsCache()
  local dir = noctalia.pluginDir()
  if dir == nil or dir == "" then
    reportError(tr("clear_cache_failed"))
    return
  end
  runAsync({ "python3", dir .. "/bin/lyrics-carousel", "--clear-cache" }, function(result)
    if result == nil or result.exitCode ~= 0 then
      reportError(tr("clear_cache_failed"))
    end
    render()
  end)
end

local ANCHOR_CHOICES = {
  "top-left", "top-center", "top-right",
  "left-center", "center", "right-center",
  "bottom-left", "bottom-center", "bottom-right",
  "custom",
}

local ANCHOR_KEYS = {
  ["top-left"] = "anchor_top_left",
  ["top-center"] = "anchor_top_center",
  ["top-right"] = "anchor_top_right",
  ["left-center"] = "anchor_left_center",
  center = "anchor_center",
  ["right-center"] = "anchor_right_center",
  ["bottom-left"] = "anchor_bottom_left",
  ["bottom-center"] = "anchor_bottom_center",
  ["bottom-right"] = "anchor_bottom_right",
  custom = "anchor_custom",
}

-- El desplegable de posicion. Noctalia indexa desde 0: el indice que llega en
-- onChange es la posicion dentro de la lista, no un numero de orden.
local function anchorSelect()
  local current = normalizeAnchor(valueOf("anchor"))
  local options = {}
  for _, name in ipairs(ANCHOR_CHOICES) do
    table.insert(options, tr(ANCHOR_KEYS[name]))
  end
  local selectedIndex = 0
  for i, name in ipairs(ANCHOR_CHOICES) do
    if name == current then
      selectedIndex = i - 1
      break
    end
  end
  return ui.select({
    key = "anchor-select",
    options = options,
    selectedIndex = selectedIndex,
    controlSize = "sm",
    onChange = function(value)
      local name = ANCHOR_CHOICES[(tonumber(value) or 0) + 1]
      if name ~= nil then
        setSetting("anchor", name, { geometry = true })
      end
    end,
  })
end

-- Botones "-" y "+" de un valor numerico.
--
-- El hover no toca nada: antes el ajuste se cambiaba al pasar el raton por
-- encima, y un ancho que se encogia solo al mover el puntero era un fallo.
local function sizeStepper(key, label, min, max, step)
  local current = math.floor(numberOf(key))
  local function bump(delta)
    local newValue = math.floor(numberOf(key)) + delta
    if newValue < min then
      newValue = min
    elseif newValue > max then
      newValue = max
    end
    if newValue == math.floor(numberOf(key)) then
      return
    end
    setSetting(key, newValue, { geometry = true })
  end
  return ui.row({ align = "center", gap = 6 }, {
    ui.button({
      key = key .. "-dec",
      text = "-",
      variant = "ghost",
      fontSize = 12,
      onClick = function()
        bump(-step)
      end,
    }),
    ui.label({ text = tostring(current), fontSize = 12, color = "on_surface", flexGrow = 1 }),
    ui.button({
      key = key .. "-inc",
      text = "+",
      variant = "ghost",
      fontSize = 12,
      onClick = function()
        bump(step)
      end,
    }),
  })
end

-- Deslizador con su etiqueta y el valor a la derecha. Los limites son los
-- del manifiesto: el panel no puede ofrecer mas de lo que el script acepta.
local function sliderRow(key, label, min, max, step, integer)
  local current = tonumber(numberOf(key)) or min
  local fmt = integer and "%d" or "%.2f"
  return ui.column({ gap = 4 }, {
    ui.row({ align = "center", gap = 8 }, {
      ui.label({ text = label, fontSize = 11, color = "on_surface_variant", flexGrow = 1 }),
      ui.label({ text = string.format(fmt, current), fontSize = 11, color = "on_surface" }),
    }),
    ui.slider({
      key = key,
      min = min,
      max = max,
      step = step,
      value = current,
      flexGrow = 1,
      onChange = function(value)
        local number = tonumber(value)
        if number == nil then
          return
        end
        if integer then
          number = math.floor(number)
        end
        setSetting(key, number)
      end,
    }),
  })
end

-- Campo de texto con validacion. Solo se guarda lo que cumple el patron: un
-- color a medias o un nombre de glifo con mayusculas dejaria la ventana sin
-- color o sin icono.
local function inputRow(key, label, placeholder, pattern)
  return ui.column({ gap = 4 }, {
    ui.label({ text = label, fontSize = 11, color = "on_surface_variant" }),
    ui.input({
      key = key,
      value = tostring(valueOf(key)),
      placeholder = placeholder,
      controlSize = "sm",
      onChange = function(value)
        if type(value) == "string" and value:match(pattern) then
          setSetting(key, value)
        end
      end,
    }),
  })
end

render = function()
  local direction = tostring(valueOf("direction"))
  local mode = tostring(valueOf("render_mode"))
  local language = tostring(valueOf("language"))
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
        -- "x" es el nombre real en el set de Tabler; "close" también
        -- funciona (alias de Noctalia) pero el validador no lo conoce.
        glyph = "x",
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
      variant = "primary",
      onClick = launch,
    }),
    ui.separator({ thickness = 1, spacing = 6 }),
    ui.label({ text = tr("section_display"), fontSize = 11, fontWeight = "bold", color = "on_surface_variant" }),
    ui.row({ align = "center", gap = 10, paddingH = 4, padding = 4 }, {
      ui.glyph({ name = "layout", size = 14, color = "on_surface_variant" }),
      ui.label({ text = tr("render_mode"), fontSize = 12, color = "on_surface", flexGrow = 1 }),
      ui.button({
        key = "mode-text",
        text = tr("mode_text"),
        variant = mode == "text" and "secondary" or "ghost",
        fontSize = 11,
        onClick = function()
          setSetting("render_mode", "text")
        end,
      }),
      ui.button({
        key = "mode-image",
        text = tr("mode_image"),
        variant = mode == "image" and "secondary" or "ghost",
        fontSize = 11,
        onClick = function()
          setSetting("render_mode", "image")
        end,
      }),
    }),
    ui.row({ align = "center", gap = 10, paddingH = 4, padding = 4 }, {
      ui.glyph({ name = "arrows-vertical", size = 14, color = "on_surface_variant" }),
      ui.label({ text = tr("direction"), fontSize = 12, color = "on_surface", flexGrow = 1 }),
      ui.button({
        key = "dir-down",
        text = tr("down"),
        variant = direction == "down" and "secondary" or "ghost",
        fontSize = 11,
        onClick = function()
          setSetting("direction", "down")
        end,
      }),
      ui.button({
        key = "dir-up",
        text = tr("up"),
        variant = direction == "up" and "secondary" or "ghost",
        fontSize = 11,
        onClick = function()
          setSetting("direction", "up")
        end,
      }),
    }),
    ui.row({ align = "center", gap = 10, paddingH = 4, padding = 4 }, {
      ui.glyph({ name = "language", size = 14, color = "on_surface_variant" }),
      ui.label({ text = tr("language"), fontSize = 12, color = "on_surface", flexGrow = 1 }),
      ui.button({
        key = "lang-auto",
        text = tr("language_auto"),
        variant = language == "auto" and "secondary" or "ghost",
        fontSize = 11,
        onClick = function()
          setSetting("language", "auto")
        end,
      }),
      ui.button({
        key = "lang-en",
        text = tr("language_en"),
        variant = language == "en" and "secondary" or "ghost",
        fontSize = 11,
        onClick = function()
          setSetting("language", "en")
        end,
      }),
      ui.button({
        key = "lang-es",
        text = tr("language_es"),
        variant = language == "es" and "secondary" or "ghost",
        fontSize = 11,
        onClick = function()
          setSetting("language", "es")
        end,
      }),
    }),
    inputRow("glyph", tr("glyph"), "music", "^[a-z0-9-]+$"),
    toggleRow("karaoke", tr("karaoke"), "sun"),
    toggleRow("marker", tr("marker"), "chevron-right"),
    toggleRow("header", tr("header"), "heading"),
    toggleRow("footer", tr("footer"), "clock"),
    toggleRow("hints", tr("hints"), "keyboard"),
    toggleRow("equalizer", tr("equalizer"), "wave-sine"),
    toggleRow("ghost", tr("ghost"), "sparkles"),
    ui.separator({ thickness = 1, spacing = 6 }),
    ui.label({ text = tr("section_lyrics"), fontSize = 11, fontWeight = "bold", color = "on_surface_variant" }),
    ui.column({ gap = 4 }, {
      ui.label({ text = tr("active_scale"), fontSize = 11, color = "on_surface_variant" }),
      scaleChips(),
    }),
    ui.row({ gap = 10 }, {
      ui.column({ flexGrow = 1, gap = 4 }, { countChips("visible_above", tr("visible_above")) }),
      ui.column({ flexGrow = 1, gap = 4 }, { countChips("visible_below", tr("visible_below")) }),
    }),
    sliderRow("spacing", tr("spacing"), 1, 6, 1, true),
    sliderRow("animation_ms", tr("animation_ms"), 0, 3000, 50, true),
    sliderRow("offset_ms", tr("offset_ms"), -3000, 3000, 10, true),
    ui.column({ gap = 4 }, {
      ui.label({ text = tr("accent"), fontSize = 11, color = "on_surface_variant" }),
      accentChips(),
      inputRow("custom_color", tr("custom_color"), "#rrggbb", "^#%x%x%x%x%x%x$"),
    }),
    ui.separator({ thickness = 1, spacing = 6 }),
    ui.label({ text = tr("section_window"), fontSize = 11, fontWeight = "bold", color = "on_surface_variant" }),
    ui.label({ text = tr("anchor"), fontSize = 11, color = "on_surface_variant" }),
    anchorSelect(),
    (function()
      if normalizeAnchor(valueOf("anchor")) == "custom" then
        local function coordinateInput(key, label)
          return ui.column({ flexGrow = 1, gap = 4 }, {
            ui.label({ text = label, fontSize = 10, color = "on_surface_variant" }),
            ui.input({
              -- El campo de texto no se controla desde el arbol: necesita una
              -- clave estable para que conserve lo que el usuario teclea.
              key = key,
              value = tostring(math.floor(numberOf(key))),
              controlSize = "sm",
              onChange = function(v)
                local n = tonumber(v)
                if n == nil then
                  return
                end
                local value = math.floor(n)
                if value == math.floor(numberOf(key)) then
                  return
                end
                setSetting(key, value, { geometry = true })
              end,
            }),
          })
        end
        return ui.row({ gap = 10 }, {
          coordinateInput("custom_x", tr("custom_x")),
          coordinateInput("custom_y", tr("custom_y")),
        })
      end
      return ui.column({})
    end)(),
    ui.row({ gap = 10 }, {
      ui.column({ flexGrow = 1, gap = 4 }, {
        ui.label({ text = tr("width"), fontSize = 11, color = "on_surface_variant" }),
        -- Los limites son los del manifiesto (plugin.toml): el script
        -- recorta lo que le llegue, asi que el panel no puede ofrecer mas.
        sizeStepper("width", tr("width"), 400, 3840, 100),
      }),
      ui.column({ flexGrow = 1, gap = 4 }, {
        ui.label({ text = tr("height"), fontSize = 11, color = "on_surface_variant" }),
        sizeStepper("height", tr("height"), 200, 2160, 50),
      }),
    }),
    ui.separator({ thickness = 1, spacing = 6 }),
    ui.label({ text = tr("section_font"), fontSize = 11, fontWeight = "bold", color = "on_surface_variant" }),
    fontChips(),
    ui.label({ text = tr("font_size"), fontSize = 11, color = "on_surface_variant" }),
    sizeChips(),
    ui.label({ text = tr("image_only_fonts"), fontSize = 10, color = "on_surface_variant" }),
    imageOnlyFonts(),
    ui.separator({ thickness = 1, spacing = 6 }),
    ui.button({
      key = "clear-cache",
      text = tr("clear_cache"),
      variant = "secondary",
      fontSize = 11,
      onClick = clearLyricsCache,
    }),
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

-- Vuelca los overrides al settings.toml: asi la pagina de ajustes del plugin
-- y el panel muestran lo mismo. Espera a que terminen las escrituras que
-- estaban en vuelo para no perder el ultimo cambio.
local function mergeOverrides(attempts)
  if pendingWrites > 0 and (attempts or 0) < 20 then
    runAsync({ "sleep", "0.1" }, function()
      mergeOverrides((attempts or 0) + 1)
    end)
    return
  end
  settingsLib.merge()
  refreshSettings()
end

function onClose()
  -- La recarga que dispara Noctalia ya no molesta: el panel se esta cerrando.
  mergeOverrides(0)
end

function onConfigChanged()
  refreshSettings()
  render()
end

function onIpc(event, payload)
  if event == "launch" then
    launch()
  elseif event == "toggle" then
    -- Alterna un ajuste booleano: toggle marker
    if type(payload) == "string" and settingsLib.BOOL_KEYS[payload] then
      toggleKey(payload)
    end
  elseif event == "set" then
    -- Fija un ajuste: "set font_size=26 int" o "set font_size 26 int"
    local key, value = settingsLib.parse(payload)
    if key ~= nil then
      settings[key] = value
      setSetting(key, value)
    end
  elseif event == "refresh" then
    refreshSettings()
    readTrack()
    render()
  end
end

refreshSettings()
