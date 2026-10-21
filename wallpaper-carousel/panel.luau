--!nonstrict
-- Carrusel de fondos: panel a pantalla completa con tarjetas verticales.
-- Cada tarjeta usa una miniatura recortada con un desplazamiento distinto
-- (parallax) según su posición respecto a la tarjeta seleccionada.

local CACHE_W = 360
local CACHE_H = 600
local THUMB_ZOOM = 1.35
local THUMB_VERSION = "v4"
local BUCKETS = { -1.0, -0.5, 0.0, 0.5, 1.0 }
local IMAGE_EXTENSIONS = {
  jpg = true,
  jpeg = true,
  png = true,
  webp = true,
  avif = true,
  bmp = true,
}

local cfg = {
  directory = "",
  glyph = "wallpaper",
  cardScale = 1.0,
  gap = 18,
  visible = 9,
  parallax = 1.0,
  minimal = true,
  closeOnApply = true,
  applyAll = true,
  showFilenames = true,
}

local wallpapers = {}
local currentDir = ""
local scanError = nil
local selected = 1
local viewPos = 1
local animating = false
local opened = false
local generating = false
local pendingEnsure = false
local applying = false
local thumbErrorShown = false
local fileInfoCache = {}
local thumbReady = {}

-- Forward declarations: render and the navigation helpers call each other.
local render, selectIndex, move, randomWallpaper, apply, reload

local function tr(key, args)
  return noctalia.tr(key, args)
end

local function clamp(value, low, high)
  if value < low then
    return low
  elseif value > high then
    return high
  end
  return value
end

local function expand(path)
  if type(path) ~= "string" then
    return ""
  end
  if path == "~" then
    return noctalia.getenv("HOME") or path
  end
  if path:sub(1, 2) == "~/" then
    return (noctalia.getenv("HOME") or "") .. path:sub(2)
  end
  return path
end

local function basename(path)
  return tostring(path or ""):match("([^/]+)$") or tostring(path or "")
end

local function shortDirectory(path)
  local home = noctalia.getenv("HOME") or ""
  if home ~= "" and path:sub(1, #home) == home then
    return "~" .. path:sub(#home + 1)
  end
  return path
end

local function joinPath(dir, name)
  if dir:sub(-1) == "/" then
    return dir .. name
  end
  return dir .. "/" .. name
end

-- FNV-1a de 32 bits. La multiplicación por 65599 cabe exactamente en un
-- double de Luau, así que no hace falta bit32 ni una implementación nativa.
local function hashText(text)
  local hash = 2166136261
  for index = 1, #text do
    hash = (hash * 65599 + string.byte(text, index)) % 4294967296
  end
  return string.format("%08x", math.floor(hash))
end

local function fileInfoFor(path)
  local cached = fileInfoCache[path]
  if cached ~= nil then
    return cached
  end
  local info = noctalia.fileInfo(path)
  if type(info) ~= "table" then
    info = {}
  end
  fileInfoCache[path] = info
  return info
end

local function cacheDirectory()
  local dataDir = noctalia.pluginDataDir()
  if not dataDir then
    return nil
  end
  local path = dataDir .. "/thumbs"
  noctalia.mkdirAll(path)
  return path
end

local thumbPathCache = {}
local function thumbPath(source, bucket)
  local cacheKey = source .. "|" .. tostring(bucket)
  local cached = thumbPathCache[cacheKey]
  if cached ~= nil then
    return cached
  end
  local cacheDir = cacheDirectory()
  if not cacheDir then
    thumbPathCache[cacheKey] = source
    return source
  end
  local info = fileInfoFor(source)
  local key = table.concat({
    source,
    tostring(info.mtime or 0),
    tostring(info.size or 0),
    tostring(CACHE_W),
    tostring(CACHE_H),
    string.format("%.2f", bucket),
    THUMB_VERSION,
  }, "|")
  local path = cacheDir .. "/" .. hashText(key) .. ".jpg"
  thumbPathCache[cacheKey] = path
  return path
end

local function imagePathFor(source, bucket)
  local path = thumbPath(source, bucket)
  if path == source then
    return source
  end
  local ready = thumbReady[path]
  if ready == nil then
    ready = noctalia.fileExists(path)
    thumbReady[path] = ready
  end
  if ready then
    return path
  end
  return nil
end

local function loadConfig()
  cfg.directory = noctalia.getConfig("directory") or ""
  cfg.glyph = noctalia.getConfig("glyph") or "wallpaper"
  cfg.cardScale = clamp(tonumber(noctalia.getConfig("card_scale")) or 1.0, 0.7, 1.4)
  cfg.gap = math.floor(clamp(tonumber(noctalia.getConfig("gap")) or 18, 4, 48))
  cfg.visible = math.floor(clamp(tonumber(noctalia.getConfig("visible")) or 0, 0, 11))
  cfg.minimal = noctalia.getConfig("minimal") ~= false
  cfg.parallax = clamp(tonumber(noctalia.getConfig("parallax")) or 1.0, 0.0, 1.5)
  cfg.closeOnApply = noctalia.getConfig("close_on_apply") ~= false
  cfg.applyAll = noctalia.getConfig("apply_all") ~= false
  cfg.showFilenames = noctalia.getConfig("show_filenames") ~= false
end

local function scanWallpapers()
  wallpapers = {}
  fileInfoCache = {}
  thumbReady = {}
  scanError = nil

  local configured = cfg.directory
  if configured ~= "" then
    currentDir = expand(configured):gsub("/+$", "")
  else
    currentDir = noctalia.wallpaperDirectory() or ""
  end
  if currentDir == "" then
    scanError = "no directory"
    return
  end
  currentDir = expand(currentDir):gsub("/+$", "")

  local names, listError = noctalia.listDir(currentDir)
  if not names then
    scanError = tostring(listError or "list failed")
    return
  end

  local found = {}
  for _, name in ipairs(names) do
    local extension = tostring(name):match("%.([%w]+)$")
    if extension and not tostring(name):match("^%.") and IMAGE_EXTENSIONS[extension:lower()] then
      table.insert(found, joinPath(currentDir, name))
    end
  end

  table.sort(found)
  wallpapers = found
end

local function focusedConnector()
  return noctalia.focusedOutputName()
end

local function currentWallpaperPath()
  local connector = focusedConnector()
  local path = connector and noctalia.wallpaperPath(connector) or nil
  if path then
    return path
  end
  local outputs = noctalia.outputs() or {}
  if outputs[1] then
    return noctalia.wallpaperPath(outputs[1].name)
  end
  return nil
end

local function indexOfPath(path)
  if not path or path == "" then
    return nil
  end
  for index, candidate in ipairs(wallpapers) do
    if candidate == path then
      return index
    end
  end
  return nil
end

local function outputSize()
  local outputs = noctalia.outputs() or {}
  local connector = focusedConnector()
  local chosen = outputs[1]
  for _, output in ipairs(outputs) do
    if output.name == connector then
      chosen = output
      break
    end
  end
  local width = tonumber(chosen and chosen.width) or 1920
  local height = tonumber(chosen and chosen.height) or 1080
  if width < 320 then
    width = 1920
  end
  if height < 240 then
    height = 1080
  end
  return width, height
end

local function cardLayout()
  local width, height = outputSize()
  local cardHeight = math.floor(math.min(height * 0.46, width * 0.30) * cfg.cardScale)
  cardHeight = math.max(180, cardHeight)

  -- El ancho de la tarjeta seleccionada es algo mayor, como en la referencia.
  local selectedWidth = math.floor(cardHeight * 0.62)
  local normalWidth = math.floor(cardHeight * 0.43)
  local normalHeight = math.floor(cardHeight * 0.94)
  local gap = cfg.gap

  local desiredHalf
  if (cfg.visible or 0) <= 0 then
    -- Modo automático: tantas tarjetas como quepan en la pantalla.
    desiredHalf = math.max(1, math.floor((width / 2 - selectedWidth / 2) / (normalWidth + gap)))
    desiredHalf = math.min(desiredHalf, 6)
  else
    desiredHalf = math.floor(cfg.visible / 2)
    desiredHalf = math.max(1, math.min(5, desiredHalf))
  end

  local half = desiredHalf
  while half > 1 do
    local before = 0
    for _ = 1, half do
      before = before + normalWidth + gap
    end
    local padding = width / 2 - selectedWidth / 2 - before
    if padding >= 32 then
      break
    end
    half = half - 1
  end

  return {
    width = width,
    height = height,
    cardHeight = cardHeight,
    selectedWidth = selectedWidth,
    normalWidth = normalWidth,
    normalHeight = normalHeight,
    gap = gap,
    half = half,
  }
end

local function cardWidth(index, layout)
  if index == selected then
    return layout.selectedWidth
  end
  return layout.normalWidth
end

local function cardHeight(index, layout)
  if index == selected then
    return layout.cardHeight
  end
  return layout.normalHeight
end

local function bucketFor(index, layout)
  if cfg.parallax <= 0 or layout.half <= 0 then
    return 0.0
  end
  local relative = (index - viewPos) / layout.half
  relative = clamp(relative * cfg.parallax, -1.0, 1.0)
  -- Cinco posiciones discretas; la caché guarda todas para que el cambio sea
  -- inmediato al navegar.
  return math.floor(relative * 4 + 0.5) / 2
end

local function ensureThumbs()
  if #wallpapers == 0 then
    return
  end
  local cacheDir = cacheDirectory()
  if not cacheDir then
    return
  end

  -- Se generan las miniaturas de todas las tarjetas visibles, no solo las
  -- cercanas a la seleccionada.
  local half = cardLayout().half
  local first = selected - half
  local last = selected + half
  local items = {}
  local seen = {}

  for index = first, last do
    local source = wallpapers[index]
    if source then
      for _, bucket in ipairs(BUCKETS) do
        local output = thumbPath(source, bucket)
        if not seen[output] and not noctalia.fileExists(output) then
          seen[output] = true
          table.insert(items, {
            source = source,
            output = output,
            width = CACHE_W,
            height = CACHE_H,
            offset = bucket,
            zoom = THUMB_ZOOM,
          })
        end
      end
    end
  end

  if #items == 0 then
    return
  end
  if generating then
    pendingEnsure = true
    return
  end

  local dataDir = noctalia.pluginDataDir()
  local pluginDir = noctalia.pluginDir()
  if not dataDir or not pluginDir then
    return
  end
  local batchPath = dataDir .. "/batch.json"
  local ok, encoded = pcall(function()
    return noctalia.json.encode(items)
  end)
  if not ok or not encoded then
    return
  end
  if not noctalia.writeFile(batchPath, encoded) then
    return
  end

  generating = true
  local started = noctalia.runAsync({
    "python3",
    pluginDir .. "/bin/thumbs.py",
    batchPath,
  }, function(result)
    generating = false
    thumbReady = {}
    if result.exitCode ~= 0 and not thumbErrorShown then
      thumbErrorShown = true
      local detail = (result.stderr or ""):gsub("%s+$", "")
      noctalia.log("wallpaper-carousel thumbnails: " .. detail)
      if detail ~= "" then
        noctalia.notifyError(tr("thumb_error"), detail)
      end
    end
    if opened then
      render()
    end
    if pendingEnsure then
      pendingEnsure = false
      ensureThumbs()
    end
  end)
  if not started then
    generating = false
  end
end

local function releaseHeldKeys()
  -- No hay estado que liberar; se deja la función por claridad del ciclo de
  -- vida del panel y para poder ampliar la interacción más adelante.
end

local function renderEmpty()
  panel.render(ui.column({
    flexGrow = 1,
    fill = "surface",
    padding = 28,
    gap = 18,
    align = "center",
    justify = "center",
  }, {
    ui.glyph({ name = "photo-off", size = 52, color = "on_surface_variant" }),
    ui.label({
      text = tr("empty", { directory = shortDirectory(currentDir) }),
      fontSize = 18,
      fontWeight = "bold",
      color = "on_surface",
      textAlign = "center",
      maxLines = 2,
    }),
    ui.label({
      text = tr("empty_hint"),
      fontSize = 12,
      color = "on_surface_variant",
      textAlign = "center",
    }),
    ui.row({ gap = 8, align = "center" }, {
      ui.button({
        text = tr("refresh"),
        glyph = "refresh",
        onClick = function()
          reload(false)
        end,
      }),
      ui.button({
        text = tr("settings"),
        glyph = "settings",
        variant = "ghost",
        onClick = function()
          noctalia.openSettings()
        end,
      }),
    }),
  }))
end

render = function()
  if #wallpapers == 0 then
    renderEmpty()
    return
  end

  local layout = cardLayout()
  local first = selected - layout.half
  local last = selected + layout.half
  local nodes = {}

  local beforeSelected = 0
  for index = first, selected - 1 do
    beforeSelected = beforeSelected + cardWidth(index, layout) + layout.gap
  end
  local basePadding = layout.width / 2 - layout.selectedWidth / 2 - beforeSelected
  local shift = (selected - viewPos) * (layout.normalWidth + layout.gap)
  local padding = math.max(0, basePadding + shift)

  for index = first, last do
    local width = cardWidth(index, layout)
    local height = cardHeight(index, layout)
    local source = wallpapers[index]
    if not source then
      table.insert(nodes, ui.box({
        key = "placeholder-" .. index,
        width = width,
        height = height,
        fill = "#00000000",
      }))
    else
      local isSelected = index == selected
      local distance = math.abs(index - selected)
      local opacity = 1.0
      if not isSelected then
        if distance == 1 then
          opacity = 0.78
        elseif distance == 2 then
          opacity = 0.50
        else
          opacity = 0.28
        end
      end

      local bucket = bucketFor(index, layout)
      local imagePath = imagePathFor(source, bucket)
      local border = isSelected and "primary" or "outline/0.55"
      local borderWidth = isSelected and 2 or 1
      local radius = isSelected and 18 or 14
      local onClick = function()
        if not isSelected then
          selectIndex(index)
        end
      end

      local preview
      if imagePath then
        preview = ui.image({
          path = imagePath,
          width = width,
          height = height,
          fit = "cover",
          radius = radius,
          border = border,
          borderWidth = borderWidth,
          tooltip = basename(source),
          onClick = onClick,
        })
      else
        preview = ui.column({
          width = width,
          height = height,
          fill = "surface_variant/0.65",
          radius = radius,
          border = border,
          borderWidth = borderWidth,
          align = "center",
          justify = "center",
          tooltip = basename(source),
          onClick = onClick,
        }, {
          ui.glyph({
            name = "photo",
            size = math.max(18, math.floor(width * 0.18)),
            color = isSelected and "primary/0.8" or "on_surface_variant/0.55",
          }),
        })
      end

      local cardChildren = {
        preview,
        ui.label({
          text = isSelected and string.format("%02d", index) or "",
          fontSize = isSelected and 12 or 10,
          fontWeight = isSelected and "bold" or "normal",
          color = isSelected and "primary" or "on_surface_variant",
          maxLines = 1,
          textAlign = "center",
        }),
      }

      table.insert(nodes, ui.column({
        key = source,
        width = width,
        gap = 5,
        align = "center",
        opacity = opacity,
      }, cardChildren))
    end
  end

  local carousel = ui.row({
    key = "carousel",
    gap = layout.gap,
    paddingH = padding,
    align = "center",
    justify = "start",
  }, nodes)

  local selectedPath = wallpapers[selected]
  local selectedThumb = selectedPath and imagePathFor(selectedPath, 0) or nil
  local footerPreview
  if selectedThumb then
    footerPreview = ui.image({
      path = selectedThumb,
      width = 44,
      height = 44,
      fit = "cover",
      radius = 9,
      border = "outline/0.5",
      borderWidth = 1,
    })
  else
    footerPreview = ui.box({ width = 44, height = 44, radius = 9, fill = "surface_variant" })
  end

  local footerText = cfg.showFilenames and basename(selectedPath) or tr("title")
  local headerButtons = {
    ui.button({
      glyph = "chevron-left",
      variant = "ghost",
      tooltip = tr("prev"),
      onClick = function() move(-1) end,
    }),
    ui.button({
      glyph = "chevron-right",
      variant = "ghost",
      tooltip = tr("next"),
      onClick = function() move(1) end,
    }),
    ui.button({
      glyph = "shuffle",
      variant = "ghost",
      tooltip = tr("random"),
      onClick = randomWallpaper,
    }),
    ui.button({
      glyph = "folder",
      variant = "ghost",
      tooltip = tr("folder"),
      onClick = function()
        if currentDir ~= "" then
          noctalia.runAsync({ "xdg-open", currentDir })
        end
      end,
    }),
    ui.button({
      glyph = "refresh",
      variant = "ghost",
      tooltip = tr("refresh"),
      onClick = function() reload(true) end,
    }),
    ui.button({
      glyph = "settings",
      variant = "ghost",
      tooltip = tr("settings"),
      onClick = function() noctalia.openSettings() end,
    }),
    ui.button({
      glyph = "close",
      variant = "ghost",
      tooltip = tr("close"),
      onClick = function() panel.close() end,
    }),
  }

  local headerChildren = {
    ui.column({ gap = 3, flexGrow = 1, align = "start" }, {
      ui.label({
        text = tr("title"),
        fontSize = 23,
        fontWeight = "bold",
        color = "on_surface",
      }),
      ui.label({
        text = tr("subtitle", {
          count = #wallpapers,
          directory = shortDirectory(currentDir),
        }),
        fontSize = 12,
        color = "on_surface_variant",
        maxLines = 1,
      }),
    }),
  }
  for _, button in ipairs(headerButtons) do
    table.insert(headerChildren, button)
  end
  local header = ui.row({ gap = 8, align = "center", paddingH = 2 }, headerChildren)

  local footer = ui.row({
    gap = 12,
    align = "center",
    paddingH = 2,
    paddingV = 8,
  }, {
    footerPreview,
    ui.column({ gap = 2, flexGrow = 1, align = "start" }, {
      ui.label({
        text = footerText,
        fontSize = 12,
        fontWeight = "bold",
        color = "on_surface",
        maxLines = 1,
      }),
      ui.label({
        text = tr("hint"),
        fontSize = 10,
        color = "on_surface_variant",
        maxLines = 1,
      }),
    }),
    ui.column({ gap = 3, width = 150, align = "stretch" }, {
      ui.label({
        text = tr("size"),
        fontSize = 10,
        color = "on_surface_variant",
      }),
      ui.slider({
        min = 0.7,
        max = 1.4,
        step = 0.05,
        value = cfg.cardScale,
        onChange = function(value)
          cfg.cardScale = clamp(tonumber(value) or cfg.cardScale, 0.7, 1.4)
          render()
        end,
      }),
    }),
    ui.button({
      text = tr("apply"),
      glyph = "check",
      variant = "primary",
      enabled = selectedPath ~= nil,
      onClick = apply,
    }),
  })

  local rootChildren = {}
  if not cfg.minimal then
    table.insert(rootChildren, header)
    table.insert(rootChildren, ui.separator({ color = "outline/0.35" }))
  end
  table.insert(rootChildren, ui.column({
    flexGrow = 1,
    justify = "center",
    align = "stretch",
  }, {
    carousel,
  }))
  if not cfg.minimal then
    table.insert(rootChildren, ui.separator({ color = "outline/0.25" }))
    table.insert(rootChildren, footer)
  else
    -- Modo minimalista: solo un pie compacto con el botón de aplicar.
    table.insert(rootChildren, ui.row({
      gap = 8,
      align = "center",
      justify = "end",
      paddingH = 2,
      paddingV = 4,
    }, {
      footerPreview,
      ui.label({
        text = footerText,
        fontSize = 11,
        color = "on_surface_variant",
        maxLines = 1,
      }),
      ui.button({
        text = tr("apply"),
        glyph = "check",
        variant = "primary",
        enabled = selectedPath ~= nil,
        onClick = apply,
      }),
    }))
  end

  panel.render(ui.column({
    flexGrow = 1,
    fill = "#00000000",
    padding = cfg.minimal and 12 or 24,
    gap = cfg.minimal and 6 or 14,
    align = "stretch",
  }, rootChildren))
end

selectIndex = function(index)
  if #wallpapers == 0 then
    return
  end
  index = clamp(index, 1, #wallpapers)
  if index == selected then
    return
  end
  selected = index
  animating = true
  panel.setNeedsFrameTick(true)
  render()
end

move = function(delta)
  selectIndex(selected + delta)
end

randomWallpaper = function()
  if #wallpapers <= 1 then
    return
  end
  local nextIndex = selected
  while nextIndex == selected do
    nextIndex = math.random(1, #wallpapers)
  end
  selectIndex(nextIndex)
end

apply = function()
  if applying or #wallpapers == 0 then
    return
  end
  local path = wallpapers[selected]
  if not noctalia.fileExists(path) then
    noctalia.notifyError(tr("apply_failed"), tr("missing_file"))
    return
  end
  applying = true
  if cfg.applyAll then
    noctalia.setWallpaper(path)
  else
    local connector = focusedConnector()
    if connector then
      noctalia.setWallpaper(connector, path)
    else
      noctalia.setWallpaper(path)
    end
  end
  applying = false
  noctalia.notify(tr("applied"), basename(path))
  if cfg.closeOnApply then
    panel.close()
  else
    render()
  end
end

reload = function(keepSelection)
  local previous = keepSelection and wallpapers[selected] or currentWallpaperPath()
  loadConfig()
  scanWallpapers()
  if #wallpapers == 0 then
    selected = 1
    viewPos = 1
    animating = false
    panel.setNeedsFrameTick(false)
    render()
    return
  end
  selected = indexOfPath(previous) or indexOfPath(currentWallpaperPath()) or 1
  viewPos = selected
  animating = false
  panel.setNeedsFrameTick(false)
  render()
  ensureThumbs()
end

function onOpen(_context)
  opened = true
  noctalia.state.set("carousel.open", true)
  math.randomseed(os.time())
  loadConfig()
  scanWallpapers()
  selected = indexOfPath(currentWallpaperPath()) or 1
  viewPos = selected
  animating = false
  thumbErrorShown = false
  panel.setNeedsFrameTick(false)
  render()
  ensureThumbs()
end

function onClose()
  opened = false
  animating = false
  noctalia.state.set("carousel.open", false)
end

function onConfigChanged()
  if opened then
    reload(true)
  end
end

function onFrameTick(deltaMs)
  if not animating then
    panel.setNeedsFrameTick(false)
    return
  end
  local dt = tonumber(deltaMs) or 16
  local difference = selected - viewPos
  if math.abs(difference) < 0.005 then
    viewPos = selected
    animating = false
    panel.setNeedsFrameTick(false)
    render()
    ensureThumbs()
    return
  end
  -- Constante de tiempo mayor y proporcional a la distancia: el desplazamiento
  -- se ve (y con él el movimiento interno de las miniaturas).
  local timeConstant = 130 + math.min(420, math.abs(difference) * 10)
  local factor = 1 - math.exp(-dt / timeConstant)
  viewPos = viewPos + difference * factor
  render()
end

function onKey(chord, pressed)
  if not pressed or #wallpapers == 0 then
    return
  end
  if chord == "Left" or chord == "k" then
    move(-1)
  elseif chord == "Right" or chord == "j" then
    move(1)
  elseif chord == "Return" or chord == "space" then
    apply()
  elseif chord == "Home" then
    selectIndex(1)
  elseif chord == "End" then
    selectIndex(#wallpapers)
  elseif chord == "r" then
    randomWallpaper()
  elseif chord == "Escape" then
    panel.close()
  end
end

local lastWheelTime = 0

function onScroll(axis, steps, _startsGesture)
  if #wallpapers == 0 then
    return
  end
  if axis ~= "vertical" and axis ~= "horizontal" then
    return
  end
  local now = os.clock()
  if now - lastWheelTime < 0.07 then
    return
  end
  lastWheelTime = now
  if (steps or 0) > 0 then
    move(1)
  else
    move(-1)
  end
end

function onIpc(event, _payload)
  if event == "refresh" and opened then
    reload(true)
  end
end
