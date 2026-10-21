--!nonstrict
-- Panel de lanzamiento: una tarjeta por widget de terminal.
--
-- Cada tarjeta abre (o enfoca) su terminal flotante. La cabecera trae las
-- acciones: abrir todo, rotar las ventanas, cerrarlas todas y editar la
-- lista de widgets.
--
-- La posición y el tamaño de cada ventana salen de `layouts`; el botón de
-- "abrir todo" además rota las ventanas ya abiertas entre sí.

local util = require("./lib/util.luau")
local defaults = require("./lib/defaults.luau")
local layoutLib = require("./lib/layout.luau")
local storeLib = require("./lib/store.luau")
local win = require("./lib/windows.luau")
local preview = require("./lib/preview.luau")

local DEBOUNCE_MS = 700
local PANEL_WIDTH = 620
local PANEL_PADDING = 12
local CARD_GAP = 10
local CARD_PADDING = 8
local PREVIEW_RATIO = 0.58
-- Margen de tolerancia: dos ventanas que se tocan (1-2 px) no cuentan como
-- solapadas, así una posición configurada no se mueve por un roce.
local OVERLAP_TOLERANCE = 4

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
  rotation = "clockwise",
  rotationSizes = false,
  columns = 2,
  cardPreview = "auto",
  avoidCollisions = true,
}

local state = {
  commands = {},
  layouts = {},
  store = nil,
  windows = {},
  editing = false,
  editTarget = nil,
  editSession = 0,
  form = { name = "", command = "", layout = "" },
  lastLaunch = {},
  launching = {},
  open = false,
}

-- Las funciones se referencian entre sí (una tarjeta llama a render() y
-- render() dibuja las tarjetas), así que se declaran antes de definirlas.
local render
local card
local header
local editorCard
local launch
local startEditing
local deleteWidget
local saveForm
local refreshWindows
local captureThumbs
local openAll
local rotateWindows
local closeAllWindows

local function tr(key, args)
  return noctalia.tr(key, args)
end

local function append(list, node)
  if node ~= nil then
    table.insert(list, node)
  end
  return list
end

-- ---------------------------------------------------------------- ajustes --

local function loadConfig()
  cfg.terminal = tostring(noctalia.getConfig("terminal") or "kitty")
  cfg.width = tonumber(noctalia.getConfig("width")) or 900
  cfg.height = tonumber(noctalia.getConfig("height")) or 520
  cfg.x = tonumber(noctalia.getConfig("x")) or 120
  cfg.y = tonumber(noctalia.getConfig("y")) or 140
  cfg.margin = tonumber(noctalia.getConfig("margin")) or 16

  local output = util.trim(noctalia.getConfig("output") or "")
  if output:lower() == "focused" then
    output = ""
  end
  cfg.output = output

  cfg.closeOnLaunch = noctalia.getConfig("close_on_launch") ~= false
  cfg.reuseExisting = noctalia.getConfig("reuse_existing") ~= false
  cfg.rotation = tostring(noctalia.getConfig("rotation") or "clockwise")
  cfg.rotationSizes = noctalia.getConfig("rotation_sizes") == true
  cfg.columns = math.floor(util.clamp(tonumber(noctalia.getConfig("columns")) or 2, 1, 3))
  cfg.cardPreview = tostring(noctalia.getConfig("card_preview") or "auto")
  cfg.avoidCollisions = noctalia.getConfig("avoid_collisions") ~= false
end

local function widgetNames()
  return util.sortedKeys(state.commands)
end

-- Fusiona defaults + Ajustes + store propio y aplica los borrados.
local function loadWidgets()
  local base = defaults.load()
  state.store = state.store or storeLib.load()
  state.commands = storeLib.merge(
    base.commands,
    noctalia.getConfig("commands"),
    state.store.commands,
    state.store.removed
  )
  state.layouts = storeLib.merge(
    base.layouts,
    noctalia.getConfig("layouts"),
    state.store.layouts,
    state.store.removed
  )
  noctalia.log("floating-term: widgets -> " .. table.concat(widgetNames(), ", "))
end

local function classMap()
  local map = {}
  for _, name in ipairs(widgetNames()) do
    map[util.classFor(name)] = name
  end
  return map
end

-- --------------------------------------------------------------- geometría --

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

local function resolveGeometry(name)
  local spec = layoutLib.parseLayout(state.layouts[name])
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
      x, y = layoutLib.anchorPosition(anchor, width, height, screenWidth, screenHeight, cfg.margin)
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
  local raw = state.layouts[name]
  if type(raw) ~= "string" or util.trim(raw) == "" then
    return tr("layout_global", { width = math.floor(cfg.width), height = math.floor(cfg.height) })
  end

  local spec = layoutLib.parseLayout(raw)
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

-- ------------------------------------------------------------- ventanas --

local function rectsOverlap(a, b)
  local tolerance = OVERLAP_TOLERANCE
  return a.x + tolerance < b.x + b.w
    and b.x + tolerance < a.x + a.w
    and a.y + tolerance < b.y + b.h
    and b.y + tolerance < a.y + a.h
end

-- Zonas ocupadas por las ventanas del plugin en el monitor de destino.
local function collectOccupied(clients, monitors, targetOutput)
  local occupied = {}
  for _, client in ipairs(clients or {}) do
    if win.isPluginClass(client.class) then
      local monitor = (monitors or {})[client.monitor]
      if monitor ~= nil and (targetOutput == "" or monitor.name == targetOutput) then
        table.insert(occupied, {
          x = client.x - monitor.x,
          y = client.y - monitor.y,
          w = client.w,
          h = client.h,
        })
      end
    end
  end
  return occupied
end

-- Posición más cercana a la deseada que no choque con otra ventana abierta.
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

local function findByClass(clients, class)
  for _, client in ipairs(clients or {}) do
    if client.class == class then
      return client
    end
  end
  return nil
end

-- ------------------------------------------------------------- miniaturas --

captureThumbs = function()
  if cfg.cardPreview == "mock" then
    return
  end
  if not preview.toolsAvailable() then
    return
  end

  local entries = {}
  for _, name in ipairs(widgetNames()) do
    local window = state.windows[name]
    if window ~= nil and window.w > 0 and window.h > 0 then
      table.insert(entries, {
        name = name,
        output = window.monitor.name,
        x = window.x,
        y = window.y,
        w = window.w,
        h = window.h,
      })
    end
  end

  if #entries == 0 then
    return
  end

  preview.capture(entries, function()
    if state.open then
      render()
    end
  end)
end

-- ------------------------------------------------------------- acciones --

local function refresh()
  refreshWindows(function()
    if state.open then
      render()
    end
  end)
end

refreshWindows = function(callback)
  win.list(function(clients)
    win.monitors(function(monitors)
      local map = classMap()
      local windows = win.pluginWindows(clients, monitors, function(class)
        return map[class]
      end)

      state.windows = {}
      for _, window in ipairs(windows) do
        if window.name ~= nil then
          state.windows[window.name] = window
        end
      end

      captureThumbs()

      if callback ~= nil then
        callback()
      end
    end)
  end)
end

-- Abre (o enfoca) un widget. El debounce evita que un doble clic rápido
-- abra dos ventanas iguales.
launch = function(name, opts)
  opts = opts or {}
  local command = state.commands[name]
  if type(command) ~= "string" or command == "" then
    noctalia.notifyError(tr("title"), tr("missing_command", { name = tostring(name) }))
    return
  end

  local class = util.classFor(name)
  local now = noctalia.nowMs()
  local last = state.lastLaunch[class]
  if last ~= nil and (now - last) < DEBOUNCE_MS then
    return
  end
  if state.launching[class] then
    return
  end
  state.lastLaunch[class] = now
  state.launching[class] = true

  local geometry = resolveGeometry(name)

  local function finish(doRefresh)
    state.launching[class] = nil
    if opts.onDone ~= nil then
      opts.onDone()
      return
    end
    if doRefresh ~= false then
      refresh()
    end
  end

  win.list(function(clients)
    win.monitors(function(monitors)
      if cfg.avoidCollisions then
        local occupied = collectOccupied(clients, monitors, geometry.output)
        geometry.x, geometry.y = avoidCollisions(geometry, occupied, geometry.auto)
      end

      local existing = findByClass(clients, class)
      if existing ~= nil and cfg.reuseExisting then
        win.focusExisting(class, geometry, function()
          finish(true)
        end)
      else
        win.spawn({
          terminal = cfg.terminal,
          class = class,
          name = name,
          command = command,
          geometry = geometry,
          monitor = cfg.output ~= "" and cfg.output or nil,
          onError = function()
            noctalia.notifyError(tr("title"), tr("launch_failed"))
          end,
        }, function()
          -- La miniatura se toma cuando la ventana ya está mapeada.
          noctalia.runAsync({ "sleep", "1.2" }, function()
            refresh()
          end)
          finish(false)
        end)
      end
    end)
  end)
end

-- Rota las ventanas abiertas entre sí.
rotateWindows = function()
  win.list(function(clients)
    win.monitors(function(monitors)
      local map = classMap()
      local windows = win.pluginWindows(clients, monitors, function(class)
        return map[class]
      end)

      if #windows < 2 then
        noctalia.notify(tr("title"), tr("nothing_to_rotate"))
        return
      end

      win.rotate(windows, cfg.rotation, cfg.rotationSizes, function()
        refresh()
      end)
    end)
  end)
end

-- Abre los widgets que falten, uno detrás de otro (así cada uno ve las
-- ventanas que ya están abiertas y no se pisan). Si ya estaban todos
-- abiertos, los rota.
openAll = function()
  win.list(function(clients)
    win.monitors(function(monitors)
      local map = classMap()
      local windows = win.pluginWindows(clients, monitors, function(class)
        return map[class]
      end)

      local open = {}
      for _, window in ipairs(windows) do
        if window.name ~= nil then
          open[window.name] = true
        end
      end

      local missing = {}
      for _, name in ipairs(widgetNames()) do
        if not open[name] then
          table.insert(missing, name)
        end
      end

      if #missing == 0 then
        if #windows >= 2 then
          win.rotate(windows, cfg.rotation, cfg.rotationSizes, function()
            refresh()
          end)
        else
          noctalia.notify(tr("title"), tr("nothing_to_rotate"))
        end
        return
      end

      local index = 0
      local function nextWidget()
        index = index + 1
        local name = missing[index]
        if name == nil then
          refresh()
          return
        end
        launch(name, {
          quiet = true,
          onDone = function()
            nextWidget()
          end,
        })
      end

      nextWidget()
    end)
  end)
end

closeAllWindows = function()
  win.list(function(clients)
    win.monitors(function(monitors)
      local map = classMap()
      local windows = win.pluginWindows(clients, monitors, function(class)
        return map[class]
      end)
      win.closeAll(windows, function()
        refresh()
      end)
    end)
  end)
end

-- ------------------------------------------------------------- edición --

-- Aplica los cambios de un widget (los usa el formulario del panel y el IPC).
local function applyWidget(name, command, layout)
  name = util.trim(name)
  command = util.trim(command)
  layout = util.trim(layout)

  if name == "" then
    return false, tr("need_name")
  end

  if state.store == nil then
    loadWidgets()
  end

  storeLib.upsert(state.store, name, command ~= "" and command or nil, layout ~= "" and layout or nil)
  local saved, err = storeLib.save(state.store)
  if not saved then
    return false, tr("save_failed", { detail = tostring(err or "") })
  end

  loadWidgets()
  return true, nil
end

-- Borra un widget (los usa el panel y el IPC).
local function removeWidget(name)
  if state.store == nil then
    loadWidgets()
  end

  storeLib.remove(state.store, name)
  local saved, err = storeLib.save(state.store)
  if not saved then
    return false, tr("save_failed", { detail = tostring(err or "") })
  end
  loadWidgets()
  return true, nil
end

startEditing = function(name)
  state.editing = true
  state.editTarget = name
  state.editSession = state.editSession + 1
  if name ~= nil then
    state.form = {
      name = name,
      command = state.commands[name] or "",
      layout = state.layouts[name] or "",
    }
  else
    state.form = { name = "", command = "", layout = "" }
  end
  render()
end

saveForm = function()
  local name = util.trim(state.form.name)
  local command = util.trim(state.form.command)
  local layout = util.trim(state.form.layout)

  if name == "" then
    noctalia.notifyError(tr("title"), tr("need_name"))
    return
  end

  local target = state.editTarget
  if target ~= nil and target ~= name then
    removeWidget(target)
  end

  local applied, err = applyWidget(name, command, layout)
  if not applied then
    noctalia.notifyError(tr("title"), err)
    return
  end

  state.editing = false
  state.editTarget = nil
  state.form = { name = "", command = "", layout = "" }
  render()
end

deleteWidget = function(name)
  local removed, err = removeWidget(name)
  if not removed then
    noctalia.notifyError(tr("title"), err)
    return
  end

  -- Si la ventana estaba abierta, se cierra para no dejarla huérfana.
  local window = state.windows[name]
  if window ~= nil then
    win.closeWindow(window.address, function()
      refresh()
    end)
  end

  render()
end

-- ---------------------------------------------------------------- vista --

local function cardWidth()
  local columns = cfg.columns
  local usable = PANEL_WIDTH - (2 * PANEL_PADDING) - ((columns - 1) * CARD_GAP)
  return math.floor(usable / columns) - (2 * CARD_PADDING)
end

local function previewHeight()
  return math.floor(cardWidth() * PREVIEW_RATIO)
end

-- Miniatura sintética: una terminal falsa con el nombre del widget.
local function mockPreview(name)
  local width = cardWidth()
  local height = previewHeight()
  local children = {}

  append(children, ui.row({ gap = 4, align = "center", padding = 6 }, {
    ui.box({ width = 7, height = 7, radius = 4, fill = "error/0.7" }),
    ui.box({ width = 7, height = 7, radius = 4, fill = "primary/0.7" }),
    ui.box({ width = 7, height = 7, radius = 4, fill = "primary/0.4" }),
  }))
  append(children, ui.row({ paddingH = 8, flexGrow = 1 }, {
    ui.label({
      text = name,
      fontSize = 12,
      fontFamily = "monospace",
      color = "on_surface/0.85",
      maxLines = 2,
      flexGrow = 1,
    }),
  }))

  -- Unas líneas de texto falsas para que la tarjeta parezca una terminal.
  local ratios = { 0.62, 0.44, 0.78 }
  for _, ratio in ipairs(ratios) do
    append(children, ui.row({ paddingH = 12, paddingV = 3 }, {
      ui.box({
        width = math.floor((width - 24) * ratio),
        height = 6,
        radius = 3,
        fill = "on_surface/0.12",
      }),
    }))
  end

  return ui.column({
    width = width,
    height = height,
    fill = "#00000040",
    radius = 8,
    border = "outline/0.25",
    borderWidth = 1,
    justify = "start",
    align = "stretch",
  }, children)
end

local function cardPreview(name)
  if cfg.cardPreview ~= "mock" then
    local window = state.windows[name]
    if window ~= nil then
      local path = preview.cached(name, preview.signature(window))
      if path ~= nil then
        return ui.image({
          path = path,
          width = cardWidth(),
          height = previewHeight(),
          fit = "cover",
          radius = 8,
          border = "outline/0.25",
          borderWidth = 1,
        })
      end
    end
  end
  return mockPreview(name)
end

card = function(name)
  local running = state.windows[name] ~= nil
  local command = state.commands[name] or ""
  local layout = layoutText(name)

  local titleRow = {}
  append(titleRow, ui.label({
    text = name,
    fontWeight = "bold",
    color = "on_surface",
    maxLines = 1,
    flexGrow = 1,
  }))
  if running then
    append(titleRow, ui.glyph({ name = "circle-dot", size = 10, color = "primary" }))
  end
  if state.editing then
    append(titleRow, ui.button({
      key = "edit-" .. name,
      glyph = "pencil",
      variant = "ghost",
      tooltip = tr("edit_widget"),
      onClick = function()
        startEditing(name)
      end,
    }))
    append(titleRow, ui.button({
      key = "delete-" .. name,
      glyph = "trash",
      variant = "ghost",
      tooltip = tr("delete_widget"),
      onClick = function()
        deleteWidget(name)
      end,
    }))
  end

  local cardProps = {
    key = "card-" .. name,
    flexGrow = 1,
    gap = 6,
    padding = CARD_PADDING,
    radius = 12,
    fill = "surface_variant/0.35",
    border = "outline/0.2",
    borderWidth = 1,
    -- Comando y posición salen en el tooltip al pasar el ratón por encima.
    tooltip = string.format("%s\n%s", command, layout),
  }

  if not state.editing then
    cardProps.onClick = function()
      launch(name)
    end
  end

  local children = {}
  append(children, cardPreview(name))
  append(children, ui.row({ gap = 6, align = "center" }, titleRow))

  return ui.column(cardProps, children)
end

editorCard = function()
  local session = state.editSession
  local children = {}

  append(children, ui.label({
    text = state.editTarget ~= nil and tr("edit_widget") or tr("add_widget"),
    fontWeight = "bold",
    color = "on_surface",
  }))
  append(children, ui.input({
    key = "form-name-" .. session,
    value = state.form.name,
    placeholder = tr("field_name"),
    controlSize = "sm",
    onChange = function(value)
      state.form.name = value
    end,
  }))
  append(children, ui.input({
    key = "form-command-" .. session,
    value = state.form.command,
    placeholder = tr("field_command"),
    controlSize = "sm",
    onChange = function(value)
      state.form.command = value
    end,
  }))
  append(children, ui.input({
    key = "form-layout-" .. session,
    value = state.form.layout,
    placeholder = tr("field_layout"),
    controlSize = "sm",
    onChange = function(value)
      state.form.layout = value
    end,
  }))
  append(children, ui.button({
    text = tr("save"),
    glyph = "check",
    variant = "primary",
    onClick = saveForm,
  }))

  return ui.column({
    key = "editor",
    flexGrow = 1,
    gap = 6,
    padding = CARD_PADDING,
    radius = 12,
    fill = "surface_variant/0.35",
    border = "primary/0.5",
    borderWidth = 1,
    align = "stretch",
  }, children)
end

header = function()
  local outputLabel = cfg.output ~= "" and cfg.output or tr("focused_output")
  local subtitle = tr("subtitle", {
    terminal = cfg.terminal,
    margin = math.floor(cfg.margin),
    output = outputLabel,
  })

  local title = ui.row({
    gap = 8,
    align = "center",
    flexGrow = 1,
    tooltip = subtitle,
  }, {
    ui.glyph({ name = "terminal-2", size = 18, color = "primary" }),
    ui.label({ text = tr("title"), fontSize = 16, fontWeight = "bold", color = "on_surface" }),
  })

  local buttons = {}
  append(buttons, ui.button({
    key = "open-all",
    glyph = "layout-grid",
    variant = "ghost",
    tooltip = tr("open_all"),
    onClick = openAll,
  }))
  append(buttons, ui.button({
    key = "rotate",
    glyph = "rotate-clockwise",
    variant = "ghost",
    tooltip = tr("rotate"),
    onClick = rotateWindows,
  }))
  append(buttons, ui.button({
    key = "close-all",
    glyph = "window-off",
    variant = "ghost",
    tooltip = tr("close_all"),
    onClick = closeAllWindows,
  }))
  append(buttons, ui.button({
    key = "edit",
    glyph = state.editing and "check" or "pencil",
    variant = "ghost",
    tooltip = tr("edit_mode"),
    onClick = function()
      if state.editing then
        state.editing = false
        state.editTarget = nil
        render()
      else
        startEditing(nil)
      end
    end,
  }))
  append(buttons, ui.button({
    key = "open-settings",
    glyph = "settings",
    variant = "ghost",
    tooltip = tr("open_settings"),
    onClick = function()
      noctalia.openSettings()
    end,
  }))
  append(buttons, ui.button({
    key = "close-panel",
    glyph = "x",
    variant = "ghost",
    tooltip = tr("close"),
    onClick = function()
      panel.close()
    end,
  }))

  return ui.row({ gap = 4, align = "center" }, { title, ui.row({ gap = 2, align = "center" }, buttons) })
end

render = function()
  if not state.open then
    return
  end

  local cards = {}
  for _, name in ipairs(widgetNames()) do
    table.insert(cards, card(name))
  end

  if state.editing then
    table.insert(cards, editorCard())
  end

  if #cards == 0 then
    table.insert(cards, ui.label({
      text = tr("empty"),
      color = "on_surface_variant",
      padding = 12,
      flexGrow = 1,
    }))
  end

  -- Filas de `columns` tarjetas.
  local rows = {}
  local row = {}
  local count = 0
  for _, node in ipairs(cards) do
    table.insert(row, node)
    count = count + 1
    if count == cfg.columns then
      table.insert(rows, ui.row({ gap = CARD_GAP, align = "stretch" }, row))
      row = {}
      count = 0
    end
  end
  if count > 0 then
    table.insert(rows, ui.row({ gap = CARD_GAP, align = "stretch" }, row))
  end

  panel.render(ui.column({
    flexGrow = 1,
    gap = 10,
    align = "stretch",
    padding = PANEL_PADDING,
  }, {
    header(),
    ui.scroll({ flexGrow = 1, gap = CARD_GAP, justify = "center" }, rows),
  }))
end

-- ------------------------------------------------------------- ciclo de vida --

function onOpen(_context)
  local t0 = os.clock()
  state.open = true
  loadConfig()
  local t1 = os.clock()
  loadWidgets()
  local t2 = os.clock()
  noctalia.log(string.format("floating-term: T loadConfig=%.2fms loadWidgets=%.2fms", (t1-t0)*1000, (t2-t1)*1000))
  state.editing = false
  state.editTarget = nil
  local t3 = os.clock()
  render()
  local t4 = os.clock()
  noctalia.log(string.format("floating-term: T render=%.2fms total=%.2fms", (t4-t3)*1000, (t4-t0)*1000))
  refreshWindows(function()
    if state.open then
      render()
    end
  end)
end

function onClose()
  state.open = false
end

function onConfigChanged()
  loadConfig()
  loadWidgets()
  if state.open then
    render()
  end
end

function onIpc(event, payload)
  if event == "launch" then
    loadConfig()
    loadWidgets()
    launch(payload)
  elseif event == "open-all" then
    loadConfig()
    loadWidgets()
    openAll()
  elseif event == "rotate" then
    loadConfig()
    loadWidgets()
    rotateWindows()
  elseif event == "close-all" then
    closeAllWindows()
  elseif event == "add" then
    -- "nombre|comando|posición"
    loadConfig()
    loadWidgets()
    local parts = {}
    for part in tostring(payload or ""):gmatch("[^|]+") do
      parts[#parts + 1] = part
    end
    local applied, err = applyWidget(parts[1] or "", parts[2] or "", parts[3] or "")
    if not applied then
      noctalia.notifyError(tr("title"), err)
      return
    end
    if state.open then
      render()
    end
  elseif event == "remove" then
    loadConfig()
    loadWidgets()
    local removed, err = removeWidget(tostring(payload or ""))
    if not removed then
      noctalia.notifyError(tr("title"), err)
      return
    end
    if state.open then
      render()
    end
  elseif event == "refresh" then
    loadConfig()
    loadWidgets()
    if state.open then
      render()
    end
    refreshWindows(function()
      if state.open then
        render()
      end
    end)
  end
end
