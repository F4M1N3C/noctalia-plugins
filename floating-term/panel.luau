--!nonstrict
-- Panel de lanzamiento: una fila por comando configurado.
--
-- Cada comando puede tener su propia geometría en el ajuste `layouts`:
--   cava      = bottom-center, 1610x584
--   unimatrix = right-center, 869x1424
--   lavat     = bottom-left, 802x582
--
-- La ventana se abre con una regla de ejecución de Hyprland 0.56:
--   hl.dsp.exec_cmd("<terminal> ...", { float = true, move = {x,y}, size = {w,h} })
-- Las coordenadas de `move` son relativas al monitor, igual que en las
-- window rules de Hyprland.

local commands = {}
local layouts = {}
local fonts = {}
local cfg = {
  terminal = "kitty",
  width = 900,
  height = 520,
  x = 120,
  y = 140,
  margin = 16,
  output = "",
  closeOnLaunch = true,
  reuseExisting = true,
}

local function tr(key, args)
  return noctalia.tr(key, args)
end

local function trim(value)
  return (tostring(value):gsub("^%s+", ""):gsub("%s+$", ""))
end

local function loadConfig()
  local rawCommands = noctalia.getConfig("commands")
  commands = type(rawCommands) == "table" and rawCommands or {}
  local rawLayouts = noctalia.getConfig("layouts")
  layouts = type(rawLayouts) == "table" and rawLayouts or {}
  local rawFonts = noctalia.getConfig("fonts")
  fonts = type(rawFonts) == "table" and rawFonts or {}

  cfg.terminal = tostring(noctalia.getConfig("terminal") or "kitty")
  cfg.width = tonumber(noctalia.getConfig("width")) or 900
  cfg.height = tonumber(noctalia.getConfig("height")) or 520
  cfg.x = tonumber(noctalia.getConfig("x")) or 120
  cfg.y = tonumber(noctalia.getConfig("y")) or 140
  cfg.margin = tonumber(noctalia.getConfig("margin")) or 16
  local output = trim(noctalia.getConfig("output") or "")
  if output:lower() == "focused" then
    output = ""
  end
  cfg.output = output
  cfg.closeOnLaunch = noctalia.getConfig("close_on_launch") ~= false
  cfg.reuseExisting = noctalia.getConfig("reuse_existing") ~= false
end

local function shellQuote(value)
  return "'" .. tostring(value):gsub("'", "'\\''") .. "'"
end

-- Cadena Lua entre comillas dobles, para incrustarla en la expresión que
-- recibe hyprctl dispatch.
local function luaQuote(value)
  local escaped = tostring(value)
  escaped = escaped:gsub("\\", "\\\\")
  escaped = escaped:gsub('"', '\\"')
  escaped = escaped:gsub("\r", "\\r")
  escaped = escaped:gsub("\n", "\\n")
  return '"' .. escaped .. '"'
end

local function slug(name)
  local result = tostring(name):lower():gsub("[^%w]+", "-")
  result = result:gsub("^%-+", ""):gsub("%-+$", "")
  if result == "" then
    return "app"
  end
  return result
end

-- "Familia, 22" o solo "Familia". Devuelve familia y tamaño opcional.
local function parseFont(value)
  if type(value) ~= "string" then
    return nil
  end
  local raw = trim(value)
  if raw == "" then
    return nil
  end
  local family, size = raw:match("^(.-)%s*,%s*(%d+)%s*$")
  if family == nil or trim(family) == "" then
    return raw, nil
  end
  local number = tonumber(size)
  if number == nil or number <= 0 then
    return trim(family), nil
  end
  return trim(family), math.floor(number)
end

-- Solo kitty permite elegir tipografía por ventana con -o.
local function fontFlags(name)
  if cfg.terminal:find("kitty", 1, true) == nil then
    return ""
  end
  local family, size = parseFont(fonts[name])
  if family == nil then
    return ""
  end
  local flags = " -o font_family=" .. shellQuote(family)
  if size ~= nil then
    flags = flags .. " -o font_size=" .. tostring(size)
  end
  return flags
end

local function fontLabel(name)
  local family, size = parseFont(fonts[name])
  if family == nil then
    return nil
  end
  if size ~= nil then
    return string.format("%s %dpx", family, size)
  end
  return family
end

-- Anclas aceptadas. Se normalizan espacios, guiones y guiones bajos.
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
  ["medio"] = "center",
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
  ["arriba-izquierda"] = "top-left",
  ["arriba-centro"] = "top-center",
  ["arriba-derecha"] = "top-right",
  ["izquierda-centro"] = "left-center",
  ["derecha-centro"] = "right-center",
  ["abajo-izquierda"] = "bottom-left",
  ["abajo-centro"] = "bottom-center",
  ["abajo-derecha"] = "bottom-right",
}

local function normalizeAnchor(token)
  local key = trim(token):lower()
  key = key:gsub("%s+", "-"):gsub("_", "-")
  key = key:gsub("%-+", "-"):gsub("^%-", ""):gsub("%-$", "")
  if ANCHORS[key] then
    return key
  end
  return ANCHOR_ALIASES[key]
end

-- Formatos admitidos:
--   bottom-center
--   bottom-center, 1610x584
--   right-center 869x1424
--   bottom-left, 802x582, 0, -24      (desplazamiento desde el ancla)
--   custom, 900x520, 120, 140         (coordenadas absolutas del monitor)
--   x=120 y=140 w=900 h=520
--   120,140 900x520
local function parseLayout(value)
  if type(value) ~= "string" then
    return nil
  end
  local raw = trim(value)
  if raw == "" then
    return nil
  end
  raw = raw:gsub("×", "x")

  local spec = { dx = 0, dy = 0, valid = true }

  -- Formato explícito con clave=valor.
  local kv = {}
  for key, number in raw:gmatch("([%a_]+)%s*=%s*(-?%d+)") do
    kv[key:lower()] = tonumber(number)
  end
  if kv.x ~= nil or kv.y ~= nil or kv.w ~= nil or kv.h ~= nil then
    if kv.x == nil or kv.y == nil then
      return { valid = false }
    end
    spec.custom = true
    spec.dx = kv.x
    spec.dy = kv.y
    spec.width = kv.w
    spec.height = kv.h
    return spec
  end

  local width, height = raw:match("(%d+)%s*[xX]%s*(%d+)")
  if width ~= nil then
    spec.width = tonumber(width)
    spec.height = tonumber(height)
  end

  -- Quita el tamaño para quedarnos con ancla y desplazamientos.
  local cleaned = raw:gsub("%d+%s*[xX]%s*%d+", " ")
  local numbers = {}

  for token in cleaned:gmatch("[^,%s]+") do
    local lower = token:lower()
    local anchor = normalizeAnchor(token)
    if anchor ~= nil then
      if spec.anchor ~= nil then
        return { valid = false }
      end
      spec.anchor = anchor
    elseif lower == "auto" or lower == "libre" or lower == "free" then
      spec.auto = true
    elseif lower == "custom" or lower == "absolute" or lower == "abs" or lower == "at" then
      spec.custom = true
    else
      local number = tonumber(token)
      if number == nil then
        return { valid = false }
      end
      table.insert(numbers, number)
    end
  end

  if spec.auto then
    -- "auto" busca un hueco libre; opcionalmente "auto, 900x520".
    spec.anchor = "center"
  elseif spec.custom then
    if #numbers < 2 then
      return { valid = false }
    end
    spec.dx = numbers[1]
    spec.dy = numbers[2]
  elseif spec.anchor ~= nil then
    if #numbers >= 2 then
      spec.dx = numbers[1]
      spec.dy = numbers[2]
    elseif #numbers == 1 then
      spec.dx = numbers[1]
    end
  elseif #numbers >= 2 then
    -- "120, 140" sin ancla: coordenadas absolutas.
    spec.custom = true
    spec.dx = numbers[1]
    spec.dy = numbers[2]
  elseif spec.width ~= nil then
    spec.anchor = "center"
  else
    return { valid = false }
  end

  return spec
end

local function layoutSpec(name)
  local raw = layouts[name]
  if type(raw) ~= "string" or trim(raw) == "" then
    return nil
  end
  return parseLayout(raw)
end

local function outputGeometry()
  local outputs = noctalia.outputs() or {}
  local wanted = cfg.output
  local chosen = nil
  local focused = nil

  for _, output in ipairs(outputs) do
    if output.focused then
      focused = output
    end
    if wanted ~= "" and output.name == wanted then
      chosen = output
    end
  end

  chosen = chosen or focused or outputs[1]
  if chosen ~= nil then
    local width = tonumber(chosen.width) or 0
    local height = tonumber(chosen.height) or 0
    if width >= 320 and height >= 240 then
      return math.floor(width), math.floor(height), chosen.name or ""
    end
  end

  return 1920, 1080, ""
end

local function anchorPosition(anchor, width, height, screenWidth, screenHeight)
  local margin = math.max(0, math.floor(cfg.margin))
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

local function resolveGeometry(name)
  local spec = layoutSpec(name)
  local width = cfg.width
  local height = cfg.height
  local custom = false
  local dx = 0
  local dy = 0
  local anchor = nil
  local auto = false

  if spec ~= nil and spec.valid then
    width = spec.width or width
    height = spec.height or height
    custom = spec.custom == true
    dx = spec.dx or 0
    dy = spec.dy or 0
    anchor = spec.anchor
    auto = spec.auto == true
  end

  width = math.max(100, math.floor(width))
  height = math.max(50, math.floor(height))

  local screenWidth, screenHeight, outputName = outputGeometry()
  local x
  local y

  if custom then
    x = math.floor(dx)
    y = math.floor(dy)
  else
    if anchor ~= nil then
      x, y = anchorPosition(anchor, width, height, screenWidth, screenHeight)
    else
      x = math.floor(cfg.x)
      y = math.floor(cfg.y)
    end
    x = x + math.floor(dx)
    y = y + math.floor(dy)
  end

  return {
    x = x,
    y = y,
    width = width,
    height = height,
    output = outputName,
    anchor = anchor,
    custom = custom,
    auto = auto,
  }
end

local function layoutText(name)
  local raw = layouts[name]
  if type(raw) ~= "string" or trim(raw) == "" then
    return tr("layout_global", { width = math.floor(cfg.width), height = math.floor(cfg.height) })
  end

  local spec = parseLayout(raw)
  if spec == nil or not spec.valid then
    return tr("layout_invalid")
  end

  local width = spec.width or math.floor(cfg.width)
  local height = spec.height or math.floor(cfg.height)
  if spec.auto then
    return string.format("%s · %d×%d", tr("layout_auto"), width, height)
  end
  if spec.custom then
    return string.format(
      "%s · %d×%d · %d,%d",
      tr("layout_custom"),
      width,
      height,
      math.floor(spec.dx or 0),
      math.floor(spec.dy or 0)
    )
  end

  return string.format("%s · %d×%d", spec.anchor, width, height)
end

local function dispatch(expression, callback)
  local started = noctalia.runAsync({ "hyprctl", "dispatch", expression }, function(result)
    if result.exitCode ~= 0 then
      local detail = result.stderr or result.stdout or ""
      detail = trim(detail)
      if detail ~= "" then
        noctalia.log("floating-term: " .. detail)
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

local function windowSelector(class)
  return "class:^" .. class .. "$"
end

local function rectsOverlap(a, b)
  return a.x < b.x + b.w and b.x < a.x + a.w and a.y < b.y + b.h and b.y < a.y + a.h
end

-- Rectángulos de las ventanas del plugin que ya están abiertas.
local function openTermWindows(callback)
  local started = noctalia.runAsync({ "hyprctl", "clients", "-j" }, function(result)
    local rects = {}
    if result.exitCode == 0 and type(result.stdout) == "string" and result.stdout ~= "" then
      local ok, clients = pcall(noctalia.json.decode, result.stdout)
      if ok and type(clients) == "table" then
        for _, client in ipairs(clients) do
          local class = client.class
          if type(class) == "string" and class:find("noctalia%-term%-") then
            local at = client.at or {}
            local size = client.size or {}
            table.insert(rects, {
              x = tonumber(at[1]) or 0,
              y = tonumber(at[2]) or 0,
              w = tonumber(size[1]) or 0,
              h = tonumber(size[2]) or 0,
            })
          end
        end
      end
    end
    callback(rects)
  end)
  if not started then
    callback({})
  end
end

-- Busca la posición más cercana a la deseada que no choque con ninguna
-- ventana ya abierta del plugin. Con `auto` se recorre la pantalla de arriba
-- abajo y de izquierda a derecha y se usa el primer hueco libre.
local function avoidCollisions(geometry, occupied, auto)
  local screenWidth, screenHeight = outputGeometry()
  local margin = math.max(0, math.floor(cfg.margin))

  local function fits(x, y)
    if x < 0 or y < 0 then
      return false
    end
    if x + geometry.width > screenWidth or y + geometry.height > screenHeight then
      return false
    end
    for _, other in ipairs(occupied) do
      if rectsOverlap({ x = x, y = y, w = geometry.width, h = geometry.height }, other) then
        return false
      end
    end
    return true
  end

  if not auto and fits(geometry.x, geometry.y) then
    return geometry.x, geometry.y
  end

  local step = 48
  local best = nil
  local bestDistance = nil
  local maxX = screenWidth - geometry.width
  local maxY = screenHeight - geometry.height
  local y = margin
  while y <= maxY do
    local x = margin
    while x <= maxX do
      if fits(x, y) then
        if auto then
          return x, y
        end
        local dx = x - geometry.x
        local dy = y - geometry.y
        local distance = dx * dx + dy * dy
        if bestDistance == nil or distance < bestDistance then
          bestDistance = distance
          best = { x = x, y = y }
        end
      end
      x = x + step
    end
    y = y + step
  end

  if best == nil then
    return geometry.x, geometry.y
  end
  return best.x, best.y
end

local function focusExisting(class, geometry, callback)
  local selector = windowSelector(class)
  local quoted = luaQuote(selector)

  local move = string.format(
    "hl.dsp.window.move({ x = %d, y = %d, window = %s })",
    geometry.x,
    geometry.y,
    quoted
  )
  local resize = string.format(
    "hl.dsp.window.resize({ x = %d, y = %d, window = %s })",
    geometry.width,
    geometry.height,
    quoted
  )
  local focus = string.format("hl.dsp.focus({ window = %s })", quoted)

  local function resizeAndMove()
    dispatch(resize, function()
      dispatch(move, function()
        dispatch(focus, function()
          if callback ~= nil then
            callback()
          end
        end)
      end)
    end)
  end

  if cfg.output ~= "" then
    local toMonitor = string.format(
      "hl.dsp.window.move({ monitor = %s, window = %s })",
      luaQuote(cfg.output),
      quoted
    )
    dispatch(toMonitor, resizeAndMove)
  else
    resizeAndMove()
  end
end

local function findExisting(class, callback)
  local started = noctalia.runAsync({ "hyprctl", "clients", "-j" }, function(result)
    if result.exitCode ~= 0 or type(result.stdout) ~= "string" or result.stdout == "" then
      callback(nil)
      return
    end

    local ok, clients = pcall(noctalia.json.decode, result.stdout)
    if not ok or type(clients) ~= "table" then
      callback(nil)
      return
    end

    for _, client in ipairs(clients) do
      if client.class == class then
        callback(client)
        return
      end
    end
    callback(nil)
  end)

  if not started then
    callback(nil)
  end
end

-- Hyprland aplica `persistent_size` al mapear la ventana, así que el tamaño
-- pedido en exec_cmd puede ser pisado. Reaplicamos la geometría un instante
-- después de crear la ventana.
local function enforceGeometry(class, geometry, callback)
  local started = noctalia.runAsync({ "sleep", "0.6" }, function()
    focusExisting(class, geometry, callback)
  end)
  if not started and callback ~= nil then
    callback()
  end
end

local function spawn(name, class, command, geometry, callback)
  -- Kitty pregunta antes de cerrar una ventana con un proceso vivo; para un
  -- lanzador de apps de terminal es más cómodo que cierre sin confirmación.
  local closeOpt = cfg.terminal:find("kitty", 1, true) ~= nil and " -o confirm_os_window_close=0" or ""
  local full = string.format(
    "%s%s%s --class %s --title %s -e sh -lc %s",
    cfg.terminal,
    closeOpt,
    fontFlags(name),
    shellQuote(class),
    shellQuote(name),
    shellQuote(command)
  )

  local monitorRule = ""
  if cfg.output ~= "" then
    monitorRule = string.format(", monitor = %s", luaQuote(cfg.output))
  end

  local rules = string.format(
    "{ float = true%s, move = { %d, %d }, size = { %d, %d } }",
    monitorRule,
    geometry.x,
    geometry.y,
    geometry.width,
    geometry.height
  )
  local expression = string.format("hl.dsp.exec_cmd(%s, %s)", luaQuote(full), rules)
  dispatch(expression, function(success)
    if not success then
      noctalia.notifyError(tr("title"), tr("launch_failed"))
    end
    enforceGeometry(class, geometry, callback)
  end)
end

local function launch(name, keepOpen)
  local command = commands[name]
  if type(command) ~= "string" or command == "" then
    noctalia.notifyError(tr("title"), tr("missing_command", { name = tostring(name) }))
    return
  end

  local class = "noctalia-term-" .. slug(name)
  local geometry = resolveGeometry(name)

  local function finish()
    if cfg.closeOnLaunch and not keepOpen then
      panel.close()
    end
  end

  local hyprland = noctalia.getenv("HYPRLAND_INSTANCE_SIGNATURE")
  if hyprland ~= nil and noctalia.commandExists("hyprctl") then
    -- Si la posición deseada choca con otra ventana del plugin ya abierta,
    -- se busca la posición libre más cercana.
    openTermWindows(function(occupied)
      geometry.x, geometry.y = avoidCollisions(geometry, occupied, geometry.auto)
      if cfg.reuseExisting then
        findExisting(class, function(existing)
          if existing ~= nil then
            focusExisting(class, geometry, finish)
          else
            spawn(name, class, command, geometry, finish)
          end
        end)
      else
        spawn(name, class, command, geometry, finish)
      end
    end)
  else
    -- Fuera de Hyprland no hay geometría, pero al menos se puede lanzar.
    noctalia.runInTerminal(command)
    finish()
  end
end

local function sortedNames()
  local names = {}
  for name in pairs(commands) do
    table.insert(names, name)
  end
  table.sort(names, function(a, b)
    return a:lower() < b:lower()
  end)
  return names
end

-- Pares de comandos cuyas cajas se solapan con la geometría actual.
-- Los comandos en modo "auto" se colocan en tiempo de ejecución, así que no
-- se pueden comparar de antemano.
local function detectOverlaps()
  local rects = {}
  for _, name in ipairs(sortedNames()) do
    local geometry = resolveGeometry(name)
    if not geometry.auto then
      table.insert(rects, {
        name = name,
        x = geometry.x,
        y = geometry.y,
        w = geometry.width,
        h = geometry.height,
      })
    end
  end

  local pairs = {}
  for i = 1, #rects do
    for j = i + 1, #rects do
      if rectsOverlap(rects[i], rects[j]) then
        table.insert(pairs, { rects[i].name, rects[j].name })
      end
    end
  end
  return pairs
end

local function commandRow(name)
  local layout = layoutText(name)
  local font = fontLabel(name)
  local tooltip = commands[name] .. "\n" .. layout
  if font ~= nil then
    tooltip = tooltip .. "\n" .. font
  end
  local lowered = tostring(name):lower()
  local glyph = "terminal-2"
  if lowered:find("lyric", 1, true) or lowered:find("music", 1, true) then
    glyph = "music"
  end
  return ui.row({
    key = "command-" .. name,
    flexGrow = 1,
    gap = 10,
    align = "center",
    padding = 10,
    paddingH = 12,
    fill = "surface_variant/0.35",
    radius = 10,
    tooltip = tooltip,
    onClick = function()
      launch(name)
    end,
  }, {
    ui.glyph({ name = glyph, size = 16, color = "primary" }),
    ui.column({ gap = 2, flexGrow = 1, align = "stretch" }, {
      ui.row({ gap = 8, align = "center" }, {
        ui.label({ text = name, fontWeight = "bold", color = "on_surface", maxLines = 1, flexGrow = 1 }),
        ui.label({ text = layout, fontSize = 10, color = "on_surface_variant", maxLines = 1 }),
      }),
      ui.label({ text = commands[name], fontSize = 11, color = "on_surface_variant", maxLines = 1 }),
    }),
    ui.glyph({ name = "player-play", size = 14, color = "on_surface_variant" }),
  })
end

local function render()
  local rows = {}
  for _, name in ipairs(sortedNames()) do
    table.insert(rows, commandRow(name))
  end
  if #rows == 0 then
    table.insert(rows, ui.label({
      text = tr("empty"),
      color = "on_surface_variant",
      padding = 12,
    }))
  end

  local overlaps = detectOverlaps()
  local warnings = {}
  for _, pair in ipairs(overlaps) do
    table.insert(warnings, pair[1] .. " + " .. pair[2])
  end
  local overlapWarning = nil
  if #warnings > 0 then
    overlapWarning = ui.row({
      key = "overlap-warning",
      gap = 8,
      align = "center",
      padding = 8,
      paddingH = 12,
      fill = "error/0.12",
      radius = 10,
      tooltip = tr("overlap_tooltip"),
    }, {
      ui.glyph({ name = "alert-triangle", size = 14, color = "error" }),
      ui.label({
        text = tr("overlap_warning", { pairs = table.concat(warnings, ", ") }),
        fontSize = 11,
        color = "error",
        flexGrow = 1,
        maxLines = 3,
      }),
    })
  end

  local outputLabel = cfg.output ~= "" and cfg.output or tr("focused_output")

  local children = {}
  table.insert(children, ui.row({ align = "center", gap = 8 }, {
    ui.glyph({ name = "terminal-2", size = 18, color = "primary" }),
    ui.label({ text = tr("title"), fontSize = 16, fontWeight = "bold", color = "on_surface", flexGrow = 1 }),
    ui.button({
      key = "open-all",
      glyph = "layout-grid",
      variant = "ghost",
      tooltip = tr("open_all"),
      onClick = function()
        for _, name in ipairs(sortedNames()) do
          launch(name, true)
        end
      end,
    }),
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
  }))
  table.insert(children, ui.label({
    text = tr("subtitle", {
      terminal = cfg.terminal,
      margin = math.floor(cfg.margin),
      output = outputLabel,
    }),
    fontSize = 11,
    color = "on_surface_variant",
  }))
  if overlapWarning ~= nil then
    table.insert(children, overlapWarning)
  end
  table.insert(children, ui.scroll({ flexGrow = 1, gap = 8 }, rows))
  table.insert(children, ui.label({ text = tr("hint"), fontSize = 11, color = "on_surface_variant" }))

  panel.render(ui.column({ flexGrow = 1, gap = 12, align = "stretch" }, children))
end

function onOpen(_context)
  loadConfig()
  render()
end

function onClose()
end

function onConfigChanged()
  loadConfig()
  render()
end

function onIpc(event, payload)
  if event == "launch" then
    loadConfig()
    launch(payload)
  elseif event == "refresh" then
    loadConfig()
    render()
  end
end
