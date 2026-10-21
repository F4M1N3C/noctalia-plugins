--!nonstrict
-- Carrusel de fondos: cinta horizontal de tarjetas inclinadas.
--
-- Reproduce el "Resizeable wallpaper carousel with parallax effect" de
-- u/HyperSpazdik (reddit.com/r/hyprland/comments/1vjqvrr) y el plugin
-- github.com/motor-dev/wallpaperCarousel: una fila de tarjetas verticales
-- inclinadas (paralelogramos) que se solapan como una cinta 3D, con la
-- seleccionada más grande y opaca y las vecinas desvaneciéndose.
--
-- Noctalia v5 no expone transformaciones (rotación/skew) en la UI declarativa,
-- así que la inclinación va horneada en la miniatura: el helper de Python
-- genera un PNG con alfa donde el wallpaper va recortado dentro del
-- paralelogramo. La paralaje (el encuadre que se desplaza según la posición
-- de la tarjeta) también se hornea, en tres posiciones por imagen.
--
-- El panel usa un `ui.scroll` como captura de la rueda: el desplazamiento
-- vertical se compensa con el relleno del propio scroll para que la cinta no
-- se mueva de sitio, y su delta mueve el carrusel horizontalmente.

local THUMB_VERSION = "v5"
local SCROLL_STEP = 56 -- px lógicos por dentado de la rueda
local SCROLL_TAIL = 300 -- relleno final del contenido del scroll
local SCROLL_JUMP = 1500 -- px que salta el scroll al recentrarse
local KEY_REPEAT_DELAY = 380 -- ms antes de empezar a repetir
local KEY_REPEAT_RATE = 55 -- ms entre repeticiones
local VIEWPORT_PADDING = 8 -- relleno interno que Noctalia pone al scroll

local IMAGE_EXTENSIONS = {
  [".jpg"] = true,
  [".jpeg"] = true,
  [".png"] = true,
  [".webp"] = true,
  [".avif"] = true,
  [".bmp"] = true,
}

local cfg = {
  directory = "",
  glyph = "wallpaper",
  cardWidth = 250,
  cardHeight = 350,
  skew = 0.35,
  parallax = 1.0,
  selectedScale = 1.08,
  baseScale = 0.75,
  hoverBoost = 0.2,
  scrim = 0.0,
  closeOnApply = true,
  applyAll = true,
  showFilenames = true,
  chrome = false,
}

local wallpapers = {}
local currentDir = ""
local scanError = nil
local selected = 1
local viewPos = 1.0
local animating = false
local opened = false
local generating = false
local pendingEnsure = false
local applying = false
local thumbErrorShown = false
local fileInfoCache = {}
local thumbReady = {}
local thumbRequested = {}

-- Rueda del ratón (capturada por el ui.scroll)
local scrollOffset = 0.0
local scrollSeen = 0.0
local scrollAccum = 0.0
local scrollSettled = true
local scrollResetting = false
local scrollReveal = 0
local scrollComp = nil -- relleno previsto para el siguiente salto del scroll
local pendingRecenter = false
local pendingThumbs = false

-- Puntero y teclado
local hovered = nil
local heldKey = nil
local heldElapsed = 0.0
local heldRepeat = 0.0

-- Forward declarations: render y los ayudantes de navegación se llaman entre sí.
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

local uiScaleCache = nil

local function uiScale()
  if uiScaleCache then
    return uiScaleCache
  end
  local scale = tonumber(noctalia.getSetting("accessibility.ui_scale"))
  if not scale or scale <= 0 then
    scale = 1.0
  end
  uiScaleCache = scale
  return scale
end

-- La miniatura se genera al tamaño de la tarjeta seleccionada (la mayor) y las
-- demás se muestran reducidas, así que nunca hay que escalar hacia arriba.
local function thumbPixelWidth()
  return math.floor(cfg.cardWidth * cfg.selectedScale * uiScale() + 0.5)
end

local function thumbPixelHeight()
  return math.floor(cfg.cardHeight * cfg.selectedScale * uiScale() + 0.5)
end

local thumbPathCache = {}

-- El tamaño de la miniatura depende del escalado de la interfaz, así que
-- entra en la clave de caché: si el usuario lo cambia, las tarjetas se
-- regeneran al tamaño correcto.
local function thumbPath(source, bucket)
  local cacheKey = source .. "|" .. tostring(bucket) .. "|" .. tostring(uiScale())
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
    tostring(thumbPixelWidth()),
    tostring(thumbPixelHeight()),
    string.format("%.2f", bucket),
    string.format("%.2f", cfg.skew),
    THUMB_VERSION,
  }, "|")
  local path = cacheDir .. "/" .. hashText(key) .. ".png"
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
  uiScaleCache = nil
  cfg.directory = noctalia.getConfig("directory") or ""
  cfg.glyph = noctalia.getConfig("glyph") or "wallpaper"
  cfg.cardWidth = clamp(tonumber(noctalia.getConfig("card_width")) or 250, 140, 640)
  cfg.cardHeight = clamp(tonumber(noctalia.getConfig("card_height")) or 350, 180, 900)
  cfg.skew = clamp(tonumber(noctalia.getConfig("skew")) or 0.35, 0.0, 0.8)
  cfg.parallax = clamp(tonumber(noctalia.getConfig("parallax")) or 1.0, 0.0, 1.5)
  cfg.selectedScale = clamp(tonumber(noctalia.getConfig("selected_scale")) or 1.08, 1.0, 1.6)
  cfg.baseScale = clamp(tonumber(noctalia.getConfig("base_scale")) or 0.75, 0.4, 1.0)
  cfg.hoverBoost = clamp(tonumber(noctalia.getConfig("hover_boost")) or 0.2, 0.0, 0.6)
  cfg.scrim = clamp(tonumber(noctalia.getConfig("scrim")) or 0.0, 0.0, 0.9)
  cfg.closeOnApply = noctalia.getConfig("close_on_apply") ~= false
  cfg.applyAll = noctalia.getConfig("apply_all") ~= false
  cfg.showFilenames = noctalia.getConfig("show_filenames") ~= false
  cfg.chrome = noctalia.getConfig("chrome") == true
end

local function scanWallpapers()
  wallpapers = {}
  fileInfoCache = {}
  thumbReady = {}
  thumbRequested = {}
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

  -- El filtrado va con sub() y tablas en vez de patrones: el VM de Noctalia
  -- mide el presupuesto con un reloj por instruccion, asi que un `match` por
  -- archivo (821 archivos) se comia 18 ms del presupuesto de 25 ms.
  local found = {}
  local count = 0
  for index = 1, #names do
    local name = names[index]
    if type(name) == "string" then
      local tail = name:sub(-5):lower()
      if IMAGE_EXTENSIONS[tail:sub(-4)] or IMAGE_EXTENSIONS[tail] then
        if name:sub(1, 1) ~= "." then
          count = count + 1
          found[count] = joinPath(currentDir, name)
        end
      end
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

local function focusedOutput()
  local outputs = noctalia.outputs() or {}
  local connector = focusedConnector()
  for _, output in ipairs(outputs) do
    if output.name == connector then
      return output
    end
  end
  return outputs[1]
end

-- El panel ocupa el output menos la barra (el shell reserva ese hueco), así
-- que el alto visible se estima a partir del output. El panel mide en px de
-- la superficie, pero sus props se escalan: de ahí los dos factores.
local function panelHeight()
  local output = focusedOutput()
  local height = tonumber(output and output.height) or 1080
  if height < 240 then
    height = 1080
  end
  return math.max(240, height - 48)
end

local function viewportHeight()
  return (panelHeight() - VIEWPORT_PADDING * 2) / uiScale()
end

local function viewportWidth()
  local output = focusedOutput()
  local width = tonumber(output and output.width) or 1920
  if width < 320 then
    width = 1920
  end
  return math.max(320, width / uiScale())
end

-- Métricas de la cinta: cuántas tarjetas entran en pantalla y cuánto relleno
-- vertical necesita el scroll para compensar su propio desplazamiento.
--
-- El scroll coloca su contenido en `padding - desplazamiento`, y el relleno
-- se mide en px de la superficie mientras que las props van en px lógicos:
-- por eso el relleno tiene que llevar la cuenta de la escala.
local function metrics()
  local viewport = viewportHeight()
  local ribbonHeight = cfg.cardHeight
  -- Relleno que deja la cinta centrada: el scroll la sube lo mismo que la
  -- baja, así que el desplazamiento y el relleno se cancelan.
  local pad = (viewport - ribbonHeight) / 2
  if pad < 0 then
    pad = 0
  end
  -- Distancia desde la cinta hasta el ancla. El ancla tiene que quedar por
  -- debajo de la ventana para que al revelarla el scroll salte hacia arriba,
  -- y a la vez el salto tiene que dejar la cinta en el mismo sitio.
  local anchorGap = viewport - 1 - pad - ribbonHeight
  if anchorGap < 0 then
    anchorGap = 0
  end
  -- La fila se centra en la pantalla, así que el grupo entero (las tarjetas
  -- más el relleno que genera el desplazamiento) tiene que caber: si no, el
  -- centro se sale de sitio. De ahí el margen de dos ranuras.
  local slots = viewportWidth() / cfg.cardWidth
  local half = math.max(1, math.floor((slots - 3) / 2))
  return {
    half = half,
    viewport = viewport,
    ribbonHeight = ribbonHeight,
    pad = pad,
    anchorGap = anchorGap,
  }
end

local function ensureThumbs()
  if #wallpapers == 0 then
    return
  end
  local cacheDir = cacheDirectory()
  if not cacheDir then
    return
  end

  -- Se encolan las miniaturas de un rango amplio alrededor de la seleccionada
  -- (para que al desplazarse siempre haya imágenes listas). El helper descarta
  -- las que ya existen, así que repetir el trabajo es barato.
  local half = math.max(metrics().half, 6)
  local first = selected - half
  local last = selected + half
  local items = {}
  local seen = {}

  for index = first, last do
    local source = wallpapers[index]
    if source then
      for _, bucket in ipairs({ -1, 0, 1 }) do
        local output = thumbPath(source, bucket)
        if not seen[output] and not thumbRequested[output] then
          seen[output] = true
          thumbRequested[output] = true
          table.insert(items, {
            source = source,
            output = output,
            width = thumbPixelWidth(),
            height = thumbPixelHeight(),
            offset = bucket * cfg.parallax,
            zoom = 1.35,
            skew = cfg.skew,
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
      if detail == "" then
        detail = string.format("exit %d", result.exitCode)
      end
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

-- ¿Está el puntero sobre esta tarjeta?
function onCardHover(state, key)
  local index = tonumber(key)
  if index == nil then
    return
  end
  local nextHovered = nil
  if state == "true" then
    nextHovered = index
  end
  if nextHovered ~= hovered then
    hovered = nextHovered
    render()
  end
end

function onCardClick(key)
  local index = tonumber(key)
  if index == nil then
    return
  end
  if index ~= selected then
    selectIndex(index)
  end
  apply()
end

render = function()
  if #wallpapers == 0 then
    renderEmpty()
    return
  end

  local m = metrics()
  local center = math.floor(viewPos)
  local fraction = viewPos - center
  local nodes = {}

  for offset = -m.half, m.half do
    local index = center + offset
    local source = wallpapers[index]
    if source then
      -- Caída suave con la distancia: la seleccionada es la única opaca.
      local distance = math.abs(index - viewPos)
      local falloff = 1.0 / (1.0 + distance * distance)

      local bucket = 0
      if cfg.parallax > 0 then
        bucket = offset > 0 and 1 or (offset < 0 and -1 or 0)
      end

      local imagePath = imagePathFor(source, bucket)
      local isHovered = hovered == index

      local scale = cfg.baseScale + (cfg.selectedScale - cfg.baseScale) * falloff
      if isHovered then
        scale = cfg.baseScale + (cfg.selectedScale - cfg.baseScale + cfg.hoverBoost) * falloff
      end

      local opacity = isHovered and 1.0 or (0.1 + 0.9 * falloff)
      local cardWidth = math.floor(cfg.cardWidth * scale + 0.5)
      local cardHeight = math.floor(cfg.cardHeight * scale + 0.5)

      local preview
      if imagePath then
        preview = ui.image({
          key = tostring(index),
          path = imagePath,
          width = cardWidth,
          height = cardHeight,
          fit = "cover",
          onClick = "onCardClick",
          onHover = "onCardHover",
          tooltip = basename(source),
        })
      else
        preview = ui.box({
          key = tostring(index),
          width = cardWidth,
          height = cardHeight,
          fill = "surface_variant/0.4",
          radius = 6,
          onClick = "onCardClick",
          onHover = "onCardHover",
          tooltip = basename(source),
        })
      end

      table.insert(nodes, ui.column({
        key = "card-" .. tostring(index),
        width = cfg.cardWidth,
        height = m.ribbonHeight,
        align = "center",
        justify = "center",
        opacity = opacity,
      }, {
        preview,
      }))
    end
  end

  -- Desplazamiento fraccionario de la cinta: la fila se centra en la
  -- pantalla y el relleno final la empuja hacia la izquierda lo justo para
  -- que la tarjeta seleccionada llegue al centro.
  table.insert(nodes, ui.spacer({
    key = "shift",
    width = math.floor(2 * fraction * cfg.cardWidth + 0.5),
    height = 1,
  }))

  local ribbon = ui.row({
    key = "ribbon",
    width = math.floor(viewportWidth()),
    gap = 0,
    align = "center",
    justify = "center",
  }, nodes)

  local children = {
    ribbon,
    ui.spacer({ key = "anchor-gap", width = 1, height = m.anchorGap }),
    -- Dos anclas con claves alternas: Noctalia sólo vuelve a revelar un
    -- descendente cuando la clave del `revealKey` cambia, así que se van
    -- turnando para poder recentrar el scroll tantas veces como haga falta.
    ui.box({ key = "anchor-0", width = 1, height = 1 }),
    ui.box({ key = "anchor-1", width = 1, height = 1 }),
    ui.spacer({ key = "tail", width = 1, height = SCROLL_TAIL }),
  }

  -- El relleno vertical del scroll compensa su propio desplazamiento: la
  -- cinta se queda quieta en pantalla aunque el scroll se mueva. El scroll
  -- mide en px de la superficie y el relleno se pasa en px lógicos, así que
  -- el desplazamiento va dividido por la escala.
  local compensation = scrollComp
  if compensation == nil then
    compensation = scrollOffset / uiScale() + m.pad
  end

  local scroll = ui.scroll({
    key = "carousel-scroll",
    flexGrow = 1,
    fill = "#00000000",
    paddingV = compensation,
    onScroll = "onScroll",
    revealKey = scrollReveal % 2 == 0 and "anchor-0" or "anchor-1",
  }, children)

  local rootChildren = { scroll }

  if cfg.chrome then
    local selectedPath = wallpapers[selected]
    local selectedThumb = selectedPath and imagePathFor(selectedPath, 0) or nil
    local footerPreview
    if selectedThumb then
      footerPreview = ui.image({
        path = selectedThumb,
        width = 40,
        height = 40,
        fit = "cover",
        radius = 8,
      })
    else
      footerPreview = ui.box({ width = 40, height = 40, radius = 8, fill = "surface_variant" })
    end
    table.insert(rootChildren, ui.row({
      gap = 12,
      align = "center",
      paddingH = 12,
      paddingV = 8,
    }, {
      footerPreview,
      ui.column({ gap = 2, flexGrow = 1, align = "start" }, {
        ui.label({
          text = cfg.showFilenames and basename(selectedPath) or tr("title"),
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
      ui.button({
        text = tr("apply"),
        glyph = "check",
        variant = "primary",
        enabled = selectedPath ~= nil,
        onClick = apply,
      }),
    }))
  end

  local scrim = cfg.scrim
  local fill = "#00000000"
  if scrim > 0 then
    fill = string.format("#%02X%02X%02X%02X", 0, 0, 0, math.floor(scrim * 255 + 0.5))
  end

  panel.render(ui.column({
    flexGrow = 1,
    fill = fill,
    padding = 0,
    gap = 0,
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
  if #wallpapers == 0 then
    return
  end
  local next = selected + delta
  -- La cinta es circular: al pasar del final vuelve al principio.
  while next > #wallpapers do
    next = next - #wallpapers
  end
  while next < 1 do
    next = next + #wallpapers
  end
  selectIndex(next)
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
    viewPos = 1.0
    animating = false
    panel.setNeedsFrameTick(false)
    render()
    return
  end
  selected = indexOfPath(previous) or indexOfPath(currentWallpaperPath()) or 1
  viewPos = selected
  animating = false
  scrollOffset = 0
  scrollSeen = 0
  scrollAccum = 0
  panel.setNeedsFrameTick(false)
  render()
  ensureThumbs()
end

-- Recentra el scroll: el ancla está tan abajo que al revelarla el scroll
-- salta SCROLL_JUMP px hacia arriba, dejando sitio para seguir subiendo. El
-- relleno se adelanta al salto para que la cinta no dé un tirón.
local function recenterScroll()
  local m = metrics()
  local scale = uiScale()
  -- El scroll salta hacia arriba para reabrir el recorrido. El salto se
  -- calcula con el relleno que Noctalia va a dejar puesto (revealKey apunta
  -- al ancla), de modo que la cinta no se mueve ni un píxel.
  local target = scrollOffset + SCROLL_JUMP * scale
  local anchorOffset = (m.ribbonHeight + m.anchorGap) * scale
  local viewport = panelHeight() - VIEWPORT_PADDING * 2
  scrollComp = (target - anchorOffset - scale + viewport) / scale
  scrollResetting = true
  scrollReveal = scrollReveal + 1
  scrollOffset = target
  scrollSeen = target
  scrollAccum = 0
  scrollSettled = true
  render()
  scrollComp = nil
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
  hovered = nil
  heldKey = nil
  scrollOffset = 0
  scrollSeen = 0
  scrollAccum = 0
  scrollSettled = true
  scrollResetting = false
  thumbErrorShown = false
  -- El frame tick se queda activo siempre: sirve para la animación de la
  -- cinta, para el autorepeat de las teclas y para consumir la rueda.
  panel.setNeedsFrameTick(true)
  render()
  -- El scroll arranca en cero, sin recorrido hacia arriba: se recentra en el
  -- primer frame para que la rueda pueda ir en ambos sentidos. Las miniaturas
  -- tambien se piden ahi, para que onOpen no se coma el presupuesto de CPU.
  pendingRecenter = true
  pendingThumbs = true
end

function onClose()
  opened = false
  animating = false
  heldKey = nil
  panel.setNeedsFrameTick(false)
  noctalia.state.set("carousel.open", false)
end

function onConfigChanged()
  if opened then
    reload(true)
  end
end

-- Desplazamiento vertical del scroll. No mueve el carrusel directamente: se
-- acumula el delta y se aplica cuando el scroll se estabiliza, para que un
-- solo dentado mueva un solo fondo aunque la animación dure varios frames.
function onScroll(offset, _maxOffset)
  local newOffset = tonumber(offset) or 0

  if scrollResetting then
    scrollResetting = false
    scrollOffset = newOffset
    scrollSeen = newOffset
    scrollAccum = 0
    scrollSettled = true
    render()
    return
  end

  -- Cuando el scroll llega al principio no puede seguir subiendo: se recentra
  -- saltando hacia abajo para reabrir el recorrido.
  if newOffset <= 0.5 then
    recenterScroll()
    return
  end

  scrollOffset = newOffset
end

function onFrameTick(deltaMs)
  local dt = tonumber(deltaMs) or 16

  -- 0. El primer frame recentra el scroll, para que la rueda tenga recorrido
  --    hacia arriba desde el principio, y pide las miniaturas.
  if pendingRecenter then
    pendingRecenter = false
    recenterScroll()
  end
  if pendingThumbs then
    pendingThumbs = false
    ensureThumbs()
  end

  -- 1. Rueda del ratón: se acumula mientras el scroll se mueve y se aplica
  --    el salto cuando se para.
  if math.abs(scrollOffset - scrollSeen) > 0.5 then
    scrollAccum = scrollAccum + (scrollOffset - scrollSeen)
    scrollSeen = scrollOffset
    scrollSettled = false
  elseif not scrollSettled then
    scrollSettled = true
    local accumulated = scrollAccum
    scrollAccum = 0
    local steps = math.floor(math.abs(accumulated) / SCROLL_STEP + 0.5)
    if steps > 0 then
      move(accumulated > 0 and steps or -steps)
    end
  end

  -- 2. Autorepeat de las flechas: la pulsación repetida del teclado no llega
  --    al script, así que se reproduce aquí con el frame tick.
  if heldKey then
    heldElapsed = heldElapsed + dt
    if heldElapsed >= KEY_REPEAT_DELAY then
      heldRepeat = heldRepeat + dt
      while heldRepeat >= KEY_REPEAT_RATE do
        heldRepeat = heldRepeat - KEY_REPEAT_RATE
        move(heldKey)
      end
    end
  end

  -- 3. Animación de la cinta: la posición visible persigue a la seleccionada.
  local difference = selected - viewPos
  if math.abs(difference) < 0.002 then
    if animating then
      viewPos = selected
      animating = false
      render()
      ensureThumbs()
    end
    return
  end
  local timeConstant = 120 + math.min(380, math.abs(difference) * 12)
  local factor = 1 - math.exp(-dt / timeConstant)
  viewPos = viewPos + difference * factor
  render()
end

function onKey(chord, pressed)
  if #wallpapers == 0 then
    return
  end
  if chord == "Left" or chord == "h" or chord == "k" then
    if pressed then
      heldKey = -1
      heldElapsed = 0
      heldRepeat = 0
      move(-1)
    else
      heldKey = nil
    end
  elseif chord == "Right" or chord == "l" or chord == "j" then
    if pressed then
      heldKey = 1
      heldElapsed = 0
      heldRepeat = 0
      move(1)
    else
      heldKey = nil
    end
  elseif chord == "Return" or chord == "space" then
    if pressed then
      apply()
    end
  elseif chord == "Home" then
    if pressed then
      selectIndex(1)
    end
  elseif chord == "End" then
    if pressed then
      selectIndex(#wallpapers)
    end
  elseif chord == "r" then
    if pressed then
      randomWallpaper()
    end
  elseif chord == "Escape" then
    panel.close()
  end
end

function onIpc(event, _payload)
  if event == "refresh" and opened then
    reload(true)
  elseif event == "next" and opened then
    move(1)
  elseif event == "prev" and opened then
    move(-1)
  end
end
