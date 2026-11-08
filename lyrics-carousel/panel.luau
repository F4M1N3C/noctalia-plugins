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
-- El selector de fuente muestra la lista hasta que el usuario elige
-- "Otra". Es estado de la interfaz, no un ajuste: no se escribe nada.
local fontCustom = nil
-- Un callback asincrono (playerctl, el helper) puede llegar despues de
-- cerrar el panel. Sin esta bandera, el callback redibuja un arbol muerto.
local panelClosed = false

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
  -- El manifiesto solo declara el icono de la barra: el resto de ajustes los
  -- gestiona el panel. `noctalia.getConfig` no los devuelve, asi que el valor
  -- real se lee del settings.toml con el helper (la misma fuente que lee el
  -- script). Es asincrono: cuando llegue, el panel se redibuja con el valor
  -- bueno en vez de con el de por defecto.
  local dir = noctalia.pluginDir()
  if dir == nil or dir == "" then
    return
  end
  runAsync({ "python3", dir .. "/bin/set-setting.py", "read" }, function(result)
    if result == nil or result.exitCode ~= 0 then
      return
    end
    settingsLib.useSaved(result.stdout)
    if not panelClosed then
      render()
    end
  end)
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

-- Limites de los ajustes numericos (lib/settings.luau, LIMITS).
-- El script recorta lo que le llegue; el panel no puede ofrecer mas de lo
-- que el script acepta, o el usuario veria un valor que no se aplica.
-- Ajustes que cambian la geometria de la ventana abierta: al tocarlos hay
-- que moverla o redimensionarla, no basta con guardar el valor.
local GEOMETRY_KEYS = {
  width = true,
  height = true,
  anchor = true,
  custom_x = true,
  custom_y = true,
}

local LIMITS = settingsLib.LIMITS

local function clampSetting(key, value)
  -- Recorte y formato: los dos vienen de la libreria compartida, para que
  -- el panel y el widget apliquen las mismas reglas al mismo ajuste.
  value = settingsLib.clamp(key, value)
  if value == nil then
    return nil
  end
  return settingsLib.validate(key, value)
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
  value = clampSetting(key, value)
  if value == nil then
    return
  end
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
  local screenWidth, screenHeight = outputGeometry()
  -- La ventana nunca puede ser mayor que el monitor: Hyprland acepta el
  -- tamano, pero la deja cortada y sin forma de moverla.
  local width = math.min(math.floor(numberOf("width")), screenWidth)
  local height = math.min(math.floor(numberOf("height")), screenHeight)
  local anchor = normalizeAnchor(valueOf("anchor"))
  local x, y
  if anchor == "custom" then
    x = math.floor(numberOf("custom_x"))
    y = math.floor(numberOf("custom_y"))
  else
    x, y = anchorPosition(anchor, width, height, screenWidth, screenHeight)
  end
  local window = "class:^noctalia-lyrics-carousel$"
  -- keep_aspect_ratio = false es imprescindible: sin esa flag el
  -- despachador de Hyprland 0.57 mantiene la proporcion y descarta el
  -- cambio de tamano (la ventana se queda con el tamano que ya tenia).
  local resize = string.format(
    'hl.dsp.window.resize({ x = %d, y = %d, window = "%s", keep_aspect_ratio = false })',
    width,
    height,
    window
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
  local screenWidth, screenHeight = outputGeometry()
  local width = math.min(math.floor(numberOf("width")), screenWidth)
  local height = math.min(math.floor(numberOf("height")), screenHeight)
  local anchor = normalizeAnchor(valueOf("anchor"))

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
  -- La ventana se crea con el tamaño en pixeles que mandan las reglas de
  -- exec_cmd; dentro de kitty el script lee el tamaño real del terminal
  -- (kitty lo publica en TIOCGWINSZ), asi que no hace falta pasar nada por
  -- variables de entorno.
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

-- Todas las fuentes que ofrece el panel, en el orden en que se muestran.
local function fontNames()
  local names = {}
  for _, name in ipairs(FONT_CHOICES) do
    table.insert(names, name)
  end
  return names
end

local function fontListed(name)
  for _, candidate in ipairs(fontNames()) do
    if candidate == name then
      return true
    end
  end
  return false
end

local function fontIndex(name)
  for index, candidate in ipairs(fontNames()) do
    if candidate == name then
      return index - 1
    end
  end
  return nil
end

-- Un solo selector de fuente: la lista de disponibles y una ultima opcion
-- para escribir una que no este. Antes habia dos listas de chips y un campo
-- siempre visible, y no se sabia cual de los tres mandaba.
local function fontSelector()
  local names = fontNames()
  local current = tostring(valueOf("font_family"))
  local custom = fontCustom == true or not fontListed(current)
  local options = {}
  for index, name in ipairs(names) do
    options[index] = name
  end
  table.insert(options, tr("font_custom"))
  local selected = #names
  if not custom then
    selected = fontIndex(current) or 0
  end
  return ui.select({
    key = "font-select",
    options = options,
    selectedIndex = selected,
    controlSize = "sm",
    onChange = function(value)
      local index = tonumber(value) or 0
      if index >= #names then
        fontCustom = true
        render()
        return
      end
      fontCustom = false
      setSetting("font_family", names[index + 1])
    end,
  })
end

local function accentChips()
  local current = tostring(valueOf("accent"))
  local rows = {}
  local row = {}
  for index, name in ipairs(ACCENT_CHOICES) do
    table.insert(row, {
      key = "accent-" .. name,
      text = tr(ACCENT_KEYS[name]),
      selected = name == current,
      onClick = function()
        setSetting("accent", name)
      end,
    })
    -- Cuatro por fila: con los ocho en una sola fila los nombres se
    -- apretaban y el ultimo quedaba fuera del panel.
    if index % 4 == 0 then
      table.insert(rows, chipRow(row))
      row = {}
    end
  end
  if #row > 0 then
    table.insert(rows, chipRow(row))
  end
  return ui.column({ gap = 4 }, rows)
end

-- La rejilla representa la pantalla: tres filas de tres botones, en el
-- mismo orden en que el usuario ve las posiciones.
local ANCHOR_GRID = {
  { "top-left", "top-center", "top-right" },
  { "left-center", "center", "right-center" },
  { "bottom-left", "bottom-center", "bottom-right" },
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

-- Nueve botones con el nombre de cada posicion dentro. Se pulsan
-- directamente: no hay que abrir un desplegable para ver donde cae cada
-- uno. La posicion personalizada es el decimo boton, debajo de la rejilla.
local function anchorButtons()
  local current = normalizeAnchor(valueOf("anchor"))
  local rows = {}
  for _, names in ipairs(ANCHOR_GRID) do
    local buttons = {}
    for _, name in ipairs(names) do
      table.insert(buttons, ui.button({
        key = "anchor-" .. name,
        text = tr(ANCHOR_KEYS[name]),
        variant = name == current and "secondary" or "ghost",
        fontSize = 10,
        flexGrow = 1,
        onClick = function()
          setSetting("anchor", name, { geometry = true })
        end,
      }))
    end
    table.insert(rows, ui.row({ gap = 6 }, buttons))
  end
  table.insert(rows, ui.button({
    key = "anchor-custom",
    text = tr("anchor_custom"),
    variant = current == "custom" and "secondary" or "ghost",
    fontSize = 10,
    onClick = function()
      setSetting("anchor", "custom", { geometry = true })
    end,
  }))
  return ui.column({ gap = 6, align = "stretch" }, rows)
end

-- Botones "-" y "+" de un valor numerico.
--
-- El hover no toca nada: antes el ajuste se cambiaba al pasar el raton por
-- encima, y un ancho que se encogia solo al mover el puntero era un fallo.
local function sizeStepper(key, min, max, step)
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
-- del panel: no puede ofrecer mas de lo que el script acepta.
local function sliderRow(key, label, min, max, step, integer)
  -- El valor mostrado se recorta: si el ajuste esta fuera de rango (por
  -- ejemplo escrito a mano en el settings.toml), el deslizador tiene que
  -- ensenar el valor real, no uno que el script va a descartar.
  local current = clampSetting(key, numberOf(key))
  if current == nil then
    current = min
  end
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
local function inputRow(key, label, placeholder)
  -- El patron de cada campo vive en lib/settings.luau (PATTERNS): el
  -- widget lo usa por su IPC y los dos tienen que aplicar el mismo.
  local pattern = settingsLib.PATTERNS[key]
  return ui.column({ gap = 4 }, {
    ui.label({ text = label, fontSize = 11, color = "on_surface_variant" }),
    ui.input({
      key = key,
      value = tostring(valueOf(key)),
      placeholder = placeholder,
      controlSize = "sm",
      onChange = function(value)
        if type(value) == "string" and (pattern == nil or value:match(pattern)) then
          setSetting(key, value)
        end
      end,
    }),
  })
end

render = function()
  if panelClosed then
    return
  end
  local direction = tostring(valueOf("direction"))
  local accent = tostring(valueOf("accent"))
  local currentFont = tostring(valueOf("font_family"))
  local customFont = fontCustom == true or not fontListed(currentFont)
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

    -- Presentación -------------------------------------------------------
    ui.label({ text = tr("section_display"), fontSize = 11, fontWeight = "bold", color = "on_surface_variant" }),
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
    -- Qué se dibuja dentro de la ventana --------------------------------
    toggleRow("header", tr("header"), "heading"),
    toggleRow("marker", tr("marker"), "chevron-right"),
    toggleRow("karaoke", tr("karaoke"), "sun"),
    toggleRow("ghost", tr("ghost"), "sparkles"),
    toggleRow("footer", tr("footer"), "clock"),
    toggleRow("hints", tr("hints"), "keyboard"),
    toggleRow("visualizer", tr("visualizer"), "wave-sine"),

    -- Visualizador: opciones condicionales (posición y cobertura) -------
    (function()
      local visualizerOn = boolOf("visualizer")
      if not visualizerOn then
        return ui.column({})
      end
      local position = tostring(valueOf("visualizer_position"))
      return ui.column({ gap = 4 }, {
        ui.row({ align = "center", gap = 8 }, {
          ui.glyph({ name = "keyframe-align-vertical", size = 14, color = "on_surface_variant" }),
          ui.label({ text = tr("visualizer_position"), fontSize = 12, color = "on_surface", flexGrow = 1 }),
          ui.button({
            key = "viz-pos-top",
            text = tr("top"),
            variant = position == "top" and "secondary" or "ghost",
            fontSize = 11,
            onClick = function() setSetting("visualizer_position", "top") end,
          }),
          ui.button({
            key = "viz-pos-bottom",
            text = tr("bottom"),
            variant = position == "bottom" and "secondary" or "ghost",
            fontSize = 11,
            onClick = function() setSetting("visualizer_position", "bottom") end,
          }),
          ui.button({
            key = "viz-pos-left",
            text = tr("left"),
            variant = position == "left" and "secondary" or "ghost",
            fontSize = 11,
            onClick = function() setSetting("visualizer_position", "left") end,
          }),
          ui.button({
            key = "viz-pos-right",
            text = tr("right"),
            variant = position == "right" and "secondary" or "ghost",
            fontSize = 11,
            onClick = function() setSetting("visualizer_position", "right") end,
          }),
        }),
        sliderRow("visualizer_coverage", tr("visualizer_coverage"), 5, 50, 5, true),
      })
    end)(),

    -- Letra --------------------------------------------------------------
    ui.separator({ thickness = 1, spacing = 6 }),
    ui.label({ text = tr("section_lyrics"), fontSize = 11, fontWeight = "bold", color = "on_surface_variant" }),
    sliderRow("active_scale", tr("active_scale"), 1.0, 2.5, 0.05, false),
    ui.row({ gap = 10 }, {
      ui.column({ flexGrow = 1, gap = 4 }, {
        sliderRow("visible_above", tr("visible_above"), 0, 20, 1, true),
      }),
      ui.column({ flexGrow = 1, gap = 4 }, {
        sliderRow("visible_below", tr("visible_below"), 0, 20, 1, true),
      }),
    }),
    sliderRow("spacing", tr("spacing"), 1, 6, 1, true),
    sliderRow("offset_ms", tr("offset_ms"), -3000, 3000, 10, true),

    -- Color --------------------------------------------------------------
    ui.separator({ thickness = 1, spacing = 6 }),
    ui.label({ text = tr("section_color"), fontSize = 11, fontWeight = "bold", color = "on_surface_variant" }),
    ui.column({ gap = 4 }, {
      ui.label({ text = tr("accent"), fontSize = 11, color = "on_surface_variant" }),
      accentChips(),
    }),
    (function()
      if accent == "custom" then
        return inputRow("custom_color", tr("custom_color"), tr("color_placeholder"))
      end
      return ui.column({})
    end)(),

    -- Tipografía ---------------------------------------------------------
    ui.separator({ thickness = 1, spacing = 6 }),
    ui.label({ text = tr("section_font"), fontSize = 11, fontWeight = "bold", color = "on_surface_variant" }),
    ui.label({ text = tr("font_family"), fontSize = 11, color = "on_surface_variant" }),
    fontSelector(),
    ui.label({ text = tr("font_hint"), fontSize = 10, color = "on_surface_variant" }),
    (function()
      if customFont then
        return inputRow("font_family", tr("font_custom_name"), tr("font_placeholder"))
      end
      return ui.column({})
    end)(),
    sliderRow("font_size", tr("font_size"), 6, 96, 1, true),

    -- Ventana ------------------------------------------------------------
    ui.separator({ thickness = 1, spacing = 6 }),
    ui.label({ text = tr("section_window"), fontSize = 11, fontWeight = "bold", color = "on_surface_variant" }),
    ui.label({ text = tr("anchor"), fontSize = 11, color = "on_surface_variant" }),
    anchorButtons(),
    (function()
      if normalizeAnchor(valueOf("anchor")) == "custom" then
        local function coordinateInput(key, label)
          return ui.column({ flexGrow = 1, gap = 4 }, {
            ui.label({ text = label, fontSize = 10, color = "on_surface_variant" }),
            ui.input({
              -- El campo de texto no se controla desde el árbol: necesita una
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
        -- Los límites son los de este panel: el script
        -- recorta lo que le llegue, así que el panel no puede ofrecer más.
        sizeStepper("width", 400, 3840, 100),
      }),
      ui.column({ flexGrow = 1, gap = 4 }, {
        ui.label({ text = tr("height"), fontSize = 11, color = "on_surface_variant" }),
        sizeStepper("height", 200, 2160, 50),
      }),
    }),
  }

  if lastError ~= "" then
    table.insert(rows, ui.label({ text = lastError, fontSize = 10, color = "error" }))
  end

  panel.render(ui.column({ flexGrow = 1, gap = 8, align = "stretch" }, {
    ui.scroll({ flexGrow = 1, gap = 8 }, rows),
  }))
end

function onOpen()
  panelClosed = false
  -- Cada apertura vuelve a deducir si la fuente actual está en la lista:
  -- así una fuente elegida a mano no deja el campo abierto para siempre.
  fontCustom = nil
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
  settingsLib.merge(function(ok)
    refreshSettings()
    if not ok then
      -- El cambio se queda en la capa de overrides: si el usuario no se
      -- entera, cree que se ha guardado y al reiniciar lo pierde.
      reportError(tr("write_failed"))
      safe("notifyError", noctalia.notifyError, tr("title"), tr("write_failed"))
    end
  end)
end

function onClose()
  -- La recarga que dispara Noctalia ya no molesta: el panel se esta cerrando.
  panelClosed = true
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
      -- setSetting recorta el valor a los limites del panel y refresca
      -- la vista: escribir `settings` antes saltaria ese recorte.
      setSetting(key, value, { geometry = GEOMETRY_KEYS[key] == true })
    end
  elseif event == "refresh" then
    refreshSettings()
    readTrack()
    render()
  end
end

refreshSettings()
