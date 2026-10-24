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

local THUMB_VERSION = "v6"
-- Tamaño logico del panel. El host no expone el tamaño de la superficie al
-- script y el manifiesto no acepta "fill" fuera del modo flotante, asi que el
-- panel declara este mismo tamaño en plugin.toml y la cinta se calcula con el.
-- Es una ventana flotante grande: "attached near trigger" coloca esta misma
-- ventana junto al boton de la barra y el clic fuera la cierra.
local PANEL_WIDTH = 1720
local PANEL_HEIGHT = 1000
local SCROLL_STEP = 56 -- px de superficie por dentado de la rueda
-- Margen para el umbral del paso. Un dentado mueve el scroll exactamente 56
-- px, pero el shell lo reparte en varios saltos y al sumarlos uno a uno se
-- queda unas centesimas por debajo (55,99). Sin este margen el paso se
-- perdia y la cinta solo avanzaba un fondo de cada dos dentados.
local SCROLL_EPS = 0.5 -- px
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

local SHAPES = {
  skew = true,
  rect = true,
  square = true,
  triangle = true,
  ellipse = true,
}

local cfg = {
  directory = "",
  glyph = "wallpaper",
  cardWidth = 300,
  cardHeight = 400,
  skew = 0.35,
  shape = "skew",
  parallax = 1.0,
  selectedScale = 1.08,
  baseScale = 0.88,
  hoverBoost = 0.2,
  scrim = 0.0,
  closeOnApply = true,
  applyAll = true,
  showFilenames = true,
  chrome = false,
  wheel = true,
  openRandom = true,
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

-- Carga inicial troceada. El panel tiene que abrirse al instante: el shell
-- aborta un callback que se pasa de su presupuesto de CPU (25 ms) y el panel
-- se queda a medias. Asi que onOpen no hace trabajo pesado: el escaneo del
-- directorio, la localizacion del fondo actual y el calculo de las miniaturas
-- se hacen en el frame tick, en trozos con presupuesto de tiempo.
local pendingInit = false
local initStage = 0
local scanNames = nil
local scanCursor = 0
local scanFound = {}
local scanTotal = 0
local pendingThumbs = false
-- Fondo a conservar cuando la recarga viene de un cambio de ajustes.
local keepSelectionPath = nil
-- Por donde va el calculo de miniaturas: sin cursor, cada troceo empezaria
-- por el mismo sitio y la carga no se acabaria nunca.
local thumbCursor = nil
-- Presupuesto por trozo: una cuarta parte del presupuesto del shell, para
-- dejar margen a lo demas que hace el tick.
local CHUNK_SECONDS = 0.006
local SCAN_CHUNK_FILES = 150
local THUMB_CHUNK_WALLPAPERS = 4

-- Rueda del ratón (capturada por el ui.scroll)
local scrollOffset = 0.0
local scrollAccum = 0.0
local scrollResetting = false
local scrollReveal = 0
local scrollComp = nil -- relleno previsto para el siguiente salto del scroll
local anchorOffset = nil -- distancia real del ancla (medida, px de superficie)
-- Correccion fina del hueco hasta el ancla: se calcula con el salto real.
local anchorGapAdjust = 0
local lastRecenterComp = nil -- relleno usado en el ultimo recentrado
-- Offset esperado basado en los pasos procesados (para compensacion robusta
-- frente a posibles animaciones del shell o valores reportados inconsistentes).
local expectedScrollOffset = 0.0

-- Puntero y teclado
local hovered = nil
local heldKey = nil
local heldElapsed = 0.0
local heldRepeat = 0.0

-- Doble clic: el host solo entrega `onClick` (no hay `onDoubleClick`), asi que
-- el segundo clic dentro de esta ventana aplica la tarjeta del primero.
local DOUBLE_CLICK_MS = 450
local lastClickIndex = nil
local lastClickMs = 0

-- Que fondo hay en cada hueco de la cinta. La cinta es circular y los huecos
-- quedan fijos (de -half a +half), asi que el mapa se rehace en cada render.
local slotIndex = {}

-- Forward declarations: render y los ayudantes de navegación se llaman entre sí.
local render, selectIndex, move, randomWallpaper, apply, reload, recenterScroll

local function tr(key, args)
  return noctalia.tr(key, args)
end

-- El host solo vuelve a pedir frames cuando el flag pasa de falso a true, asi
-- que hay que apagarlo cuando no hay nada que animar: si no, tras recargar el
-- plugin el tick se queda muerto y la rueda y la animacion dejan de funcionar.
local function wakeUp()
  panel.setNeedsFrameTick(true)
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
  local info = fileInfoFor(source)
  -- La clave incluye mtime y tamaño: si el wallpaper se edita, la ruta de la
  -- miniatura cambia y no se queda la imagen vieja cacheada.
  local cacheKey = table.concat({
    source,
    tostring(bucket),
    string.format("%.2f", uiScale()),
    tostring(info.mtime or 0),
    tostring(info.size or 0),
  }, "|")
  local cached = thumbPathCache[cacheKey]
  if cached ~= nil then
    return cached
  end
  local cacheDir = cacheDirectory()
  if not cacheDir then
    thumbPathCache[cacheKey] = source
    return source
  end
  local key = table.concat({
    source,
    tostring(info.mtime or 0),
    tostring(info.size or 0),
    tostring(thumbPixelWidth()),
    tostring(thumbPixelHeight()),
    string.format("%.2f", bucket),
    string.format("%.2f", cfg.skew),
    cfg.shape,
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
  cfg.cardWidth = clamp(tonumber(noctalia.getConfig("card_width")) or 300, 140, 640)
  cfg.cardHeight = clamp(tonumber(noctalia.getConfig("card_height")) or 400, 180, 900)
  cfg.skew = clamp(tonumber(noctalia.getConfig("skew")) or 0.35, 0.0, 0.8)
  cfg.shape = tostring(noctalia.getConfig("card_shape") or "skew")
  if not SHAPES[cfg.shape] then
    cfg.shape = "skew"
  end
  cfg.parallax = clamp(tonumber(noctalia.getConfig("parallax")) or 1.0, 0.0, 1.5)
  cfg.selectedScale = clamp(tonumber(noctalia.getConfig("selected_scale")) or 1.08, 1.0, 1.6)
  cfg.baseScale = clamp(tonumber(noctalia.getConfig("base_scale")) or 0.88, 0.4, 1.0)
  cfg.hoverBoost = clamp(tonumber(noctalia.getConfig("hover_boost")) or 0.2, 0.0, 0.6)
  cfg.scrim = clamp(tonumber(noctalia.getConfig("scrim")) or 0.0, 0.0, 0.9)
  cfg.closeOnApply = noctalia.getConfig("close_on_apply") ~= false
  cfg.applyAll = noctalia.getConfig("apply_all") ~= false
  cfg.showFilenames = noctalia.getConfig("show_filenames") ~= false
  cfg.chrome = noctalia.getConfig("chrome") == true
  cfg.wheel = noctalia.getConfig("wheel") ~= false
  cfg.openRandom = noctalia.getConfig("open_random") ~= false
end

-- Prepara el escaneo: resuelve el directorio y saca la lista de nombres. El
-- filtrado de esa lista se hace en trozos (scanChunk) porque recorrer 800
-- archivos de golpe se pasa del presupuesto del callback.
local function scanBegin()
  wallpapers = {}
  fileInfoCache = {}
  thumbReady = {}
  thumbRequested = {}
  thumbPathCache = {}
  scanError = nil
  scanNames = nil
  scanCursor = 0
  scanFound = {}
  scanTotal = 0

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
  scanNames = names
end

-- Un trozo del filtrado del listado. Devuelve true si queda trabajo.
--
-- El filtrado va con sub() y tablas en vez de patrones: el VM de Noctalia
-- mide el presupuesto con un reloj por instruccion, asi que un `match` por
-- archivo (821 archivos) se comia 18 ms del presupuesto de 25 ms.
local function scanChunk()
  if scanNames == nil then
    return false
  end
  local total = #scanNames
  local deadline = os.clock() + CHUNK_SECONDS
  local processed = 0
  while scanCursor < total do
    scanCursor = scanCursor + 1
    processed = processed + 1
    local name = scanNames[scanCursor]
    if type(name) == "string" then
      local tail = name:sub(-5):lower()
      if IMAGE_EXTENSIONS[tail:sub(-4)] or IMAGE_EXTENSIONS[tail] then
        if name:sub(1, 1) ~= "." then
          scanTotal = scanTotal + 1
          scanFound[scanTotal] = joinPath(currentDir, name)
        end
      end
    end
    if processed >= SCAN_CHUNK_FILES or os.clock() >= deadline then
      return true
    end
  end

  -- Fin del listado: se ordena y la lista queda lista.
  table.sort(scanFound)
  wallpapers = scanFound
  scanNames = nil
  scanFound = {}
  return false
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
  -- Reserva el pie del panel (pie o etiqueta de nombre) para que la cinta se
  -- centre en el hueco que queda para el scroll.
  local chrome = 0
  if cfg.chrome then
    chrome = chrome + 56
  end
  if cfg.showFilenames and not cfg.chrome then
    chrome = chrome + 36
  end
  -- PANEL_HEIGHT es el tamaño logico declarado en el manifiesto (ventana
  -- flotante). Si el monitor es mas pequeño, el host lo recorta y se usa el
  -- valor menor para no dibujar fuera de la superficie.
  local output = focusedOutput()
  local available = PANEL_HEIGHT
  if output and tonumber(output.height) and tonumber(output.height) > 0 then
    available = math.min(available, tonumber(output.height) - 48)
  end
  return math.max(240, available - chrome)
end

local function viewportHeight()
  return (panelHeight() - VIEWPORT_PADDING * 2) / uiScale()
end

local function viewportWidth()
  local output = focusedOutput()
  local available = PANEL_WIDTH
  if output and tonumber(output.width) and tonumber(output.width) > 0 then
    available = math.min(available, tonumber(output.width) - 32)
  end
  return math.max(320, available / uiScale())
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
  -- Distancia desde la cinta hasta el ancla del scroll, en px lógicos.
  --
  -- El ancla tiene que quedar por debajo de la ventana (para que al revelarla
  -- el scroll salte hacia arriba) y a la vez el salto tiene que dejar la cinta
  -- en el mismo sitio de la pantalla. Esa segunda condición pide que el ancla
  -- quede a `viewport - pad - 1` del borde del contenido; como el ancla va
  -- detrás de la cinta, del hueco se descuenta su altura y la del ancla.
  -- El ajuste fino se mide sobre el salto real y se corrige solo.
  local anchorGap = math.max(0, viewport - pad - 1 - ribbonHeight - 1 + anchorGapAdjust)
  -- Las tarjetas laterales llenan su hueco: el paso de la cinta es el ancho de
  -- la tarjeta por la escala lateral, asi que no quedan huecos entre ellas y la
  -- cinta se lee como un rectangulo continuo. La seleccionada, algo mayor, se
  -- solapa con las vecinas como en la cinta de referencia.
  local slot = math.max(1, math.floor(cfg.cardWidth * cfg.baseScale + 0.5))
  -- Cuántas tarjetas caben a cada lado del centro.
  local slots = viewportWidth() / slot
  local half = math.max(1, math.floor((slots - 1) / 2))
  return {
    half = half,
    slot = slot,
    viewport = viewport,
    ribbonHeight = ribbonHeight,
    pad = pad,
    anchorGap = anchorGap,
  }
end

-- Calcula las miniaturas del entorno de la seleccionada. Cada miniatura
-- cuesta una consulta al disco (y el disco puede ir lento), asi que se
-- calcula en trozos: devuelve true si queda trabajo pendiente.
local function ensureThumbs()
  if #wallpapers == 0 then
    return false
  end
  local cacheDir = cacheDirectory()
  if not cacheDir then
    return false
  end

  -- Se encolan las miniaturas de un rango amplio alrededor de la seleccionada
  -- (para que al desplazarse siempre haya imágenes listas). El helper descarta
  -- las que ya existen, así que repetir el trabajo es barato.
  local half = math.max(metrics().half, 6)
  local first = selected - half
  local last = selected + half
  local items = {}
  local seen = {}
  local deadline = os.clock() + CHUNK_SECONDS
  local processed = 0
  local truncated = false
  -- Se continua por donde se dejo. El cursor puede quedar pasado el ultimo
  -- (el rango ya esta cubierto): entonces el bucle no se ejecuta y el trabajo
  -- se da por terminado. Si la seleccion cambia, el cursor se reinicia (lo
  -- hace selectIndex), porque el rango es otro.
  local start = first
  if thumbCursor and thumbCursor > first then
    start = thumbCursor
  end

  for index = start, last do
    local source = wallpapers[index]
    if source then
      for _, bucket in ipairs({ -1, 0, 1 }) do
        local output = thumbPath(source, bucket)
        if not seen[output] and not thumbRequested[output] then
          seen[output] = true
          table.insert(items, {
            source = source,
            output = output,
            width = thumbPixelWidth(),
            height = thumbPixelHeight(),
            offset = bucket * cfg.parallax,
            zoom = 1.35,
            skew = cfg.skew,
            shape = cfg.shape,
          })
        end
      end
    end
    processed = processed + 1
    thumbCursor = index + 1
    if processed >= THUMB_CHUNK_WALLPAPERS or os.clock() >= deadline then
      truncated = index < last
      break
    end
  end

  if truncated then
    pendingThumbs = true
  else
    -- El rango esta cubierto: se limpia el cursor y la marca de trabajo
    -- pendiente (si no, el troceo se repetiria para siempre).
    thumbCursor = nil
    pendingThumbs = false
  end
  if #items == 0 then
    return pendingThumbs
  end
  if generating then
    -- El generador esta ocupado: los items se descartan, pero no se marcan
    -- como pedidos (si se marcaran, no se volverian a pedir nunca y las
    -- tarjetas se quedarian sin imagen).
    pendingEnsure = true
    return pendingThumbs
  end

  local dataDir = noctalia.pluginDataDir()
  local pluginDir = noctalia.pluginDir()
  if not dataDir or not pluginDir then
    return pendingThumbs
  end
  local batchPath = dataDir .. "/batch.json"
  local ok, encoded = pcall(function()
    return noctalia.json.encode(items)
  end)
  if not ok or not encoded then
    return pendingThumbs
  end
  if not noctalia.writeFile(batchPath, encoded) then
    return pendingThumbs
  end
  -- Ahora si quedan pedidos: se marcan para no volver a generarlos.
  for _, item in ipairs(items) do
    thumbRequested[item.output] = true
  end

  generating = true
  local started = noctalia.runAsync({
    "python3",
    pluginDir .. "/bin/thumbs.py",
    batchPath,
  }, function(result)
    generating = false
    thumbReady = {}
    if result.exitCode ~= 0 then
      -- Se limpia lo pedido para que la proxima vez se vuelva a intentar.
      thumbRequested = {}
    end
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
      if ensureThumbs() then
        pendingThumbs = true
      end
    end
  end)
  if not started then
    generating = false
  end
  return pendingThumbs
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
        text = tr("open_settings"),
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
  local slot = tonumber(key)
  if slot == nil then
    return
  end
  local hoverStarted = os.clock()
  local index = slotIndex[slot]
  local nextHovered = nil
  if state == "true" then
    nextHovered = index
  end
  if nextHovered ~= hovered then
    hovered = nextHovered
    render()
  end
  noctalia.log(string.format("wc-budget onCardHover end cost=%.2f ms", (os.clock() - hoverStarted) * 1000))
end

-- Un clic elige la tarjeta; dos clics seguidos aplican la elegida. El host no
-- distingue doble clic, asi que se mide el intervalo con `nowMs()` (reloj de
-- pared: `os.clock()` es CPU y no avanza mientras se espera).
--
-- El segundo clic aplica la tarjeta del PRIMER clic, no la que haya bajo el
-- puntero: al elegir, la cinta empieza a deslizarse y la tarjeta se mueve de
-- hueco, asi que el hueco del segundo clic ya no es el mismo.
function onCardClick(key)
  local slot = tonumber(key)
  if slot == nil then
    return
  end
  local index = slotIndex[slot]
  if index == nil then
    return
  end
  local now = noctalia.nowMs() or 0
  if lastClickIndex ~= nil and now - lastClickMs <= DOUBLE_CLICK_MS then
    lastClickIndex = nil
    lastClickMs = 0
    apply()
    return
  end
  lastClickIndex = index
  lastClickMs = now
  if index ~= selected then
    selectIndex(index)
  end
end

render = function()
  if #wallpapers == 0 then
    renderEmpty()
    return
  end

  local m = metrics()
  local count = #wallpapers
  local center = math.floor(viewPos)
  local fraction = viewPos - center
  local nodes = {}
  slotIndex = {}

  -- La cinta es circular: cada hueco toma el fondo que le toca con modulo, de
  -- modo que SIEMPRE hay tarjetas a los dos lados, tambien al abrir cerca del
  -- principio o del final de la carpeta. Sin esto el primer y el ultimo fondo
  -- dejaban medio panel vacio.
  local half = m.half
  if count <= 1 then
    half = 0
  elseif count - 1 < half then
    half = count - 1
  end

  for offset = -half, half do
    local index = ((center + offset - 1) % count) + 1
    slotIndex[offset] = index
    local source = wallpapers[index]
    if source then
      -- Distancia al centro visible de la cinta: se mide en huecos, no en
      -- indices, para que la vuelta circular no hunda el brillo.
      local relative = offset - fraction
      local distance = math.abs(relative)
      local falloff = 1.0 / (1.0 + distance * distance)

      -- El recorte cambia cuando la tarjeta cruza el centro mientras la cinta
      -- se desplaza, no de golpe al terminar la animacion: la seleccionada
      -- siempre acaba con el recorte central (bucket 0).
      local bucket = 0
      if cfg.parallax > 0 then
        if relative >= 0.5 then
          bucket = 1
        elseif relative <= -0.5 then
          bucket = -1
        end
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

      -- La clave es el hueco (-half..half), no el indice: con la cinta
      -- circular dos huecos pueden mostrar el mismo fondo y las claves de los
      -- nodos tienen que ser unicas. onCardClick/onCardHover traducen el hueco
      -- con slotIndex.
      local preview
      if imagePath then
        preview = ui.image({
          key = tostring(offset),
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
          key = tostring(offset),
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
        key = "card-" .. tostring(offset),
        width = m.slot,
        height = m.ribbonHeight,
        align = "center",
        justify = "center",
        opacity = opacity,
      }, {
        preview,
      }))
    end
  end

  -- Desplazamiento de la cinta: la fila se alinea al principio y un relleno
  -- inicial coloca la tarjeta seleccionada en el centro de la pantalla. Al
  -- avanzar, el relleno se encoge y la cinta se desliza hacia la izquierda.
  --
  -- Con la cinta circular siempre hay huecos a ambos lados, asi que el relleno
  -- no depende de ninguna condicion de borde.
  local lead = viewportWidth() / 2 - m.slot / 2 - fraction * m.slot
  -- El `ui.spacer` de Noctalia nace con flexGrow = 1: si se deja crecer se
  -- come todo el ancho sobrante de la fila y el ancho del lead no se aplica,
  -- así que la cinta se quedaba a la derecha del todo. Con flexGrow = 0
  -- ocupa justo el ancho pedido.
  table.insert(nodes, 1, ui.spacer({
    key = "lead",
    width = math.max(0, math.floor(lead + 0.5)),
    height = 1,
    flexGrow = 0,
  }))

  local ribbon = ui.row({
    key = "ribbon",
    width = math.floor(viewportWidth()),
    gap = 0,
    align = "center",
    justify = "start",
  }, nodes)

  local children = {
    ribbon,
    ui.spacer({ key = "anchor-gap", width = 1, height = m.anchorGap, flexGrow = 0 }),
    -- Dos anclas con claves alternas: Noctalia sólo vuelve a revelar un
    -- descendente cuando la clave del `revealKey` cambia, así que se van
    -- turnando para poder recentrar el scroll tantas veces como haga falta.
    ui.box({ key = "anchor-0", width = 1, height = 1 }),
    ui.box({ key = "anchor-1", width = 1, height = 1 }),
    ui.spacer({ key = "tail", width = 1, height = cfg.wheel and SCROLL_TAIL or 0, flexGrow = 0 }),
  }

  -- El relleno vertical del scroll compensa su propio desplazamiento: la
  -- cinta se queda quieta en pantalla aunque el scroll se mueva. El scroll
  -- mide en px de la superficie y el relleno se pasa en px lógicos, así que
  -- el desplazamiento va dividido por la escala.
  --
  -- IMPORTANTE: usamos expectedScrollOffset (lo que nosotros esperamos que
  -- sea el scroll basándonos en los pasos procesados) en lugar de scrollOffset
  -- (lo que el shell reporta), para evitar el desfase de un frame que causa
  -- el "parpadeo" vertical. El contenido visual del scroll se posiciona en
  -- (paddingV * scale - scrollOffset); al hacer paddingV = expectedOffset/scale
  -- + m.pad, la posición queda fija en m.pad aunque el shell reporte valores
  -- intermedios durante su animación interna.
  local compensation = scrollComp
  if compensation == nil then
    compensation = expectedScrollOffset / uiScale() + m.pad
  end
  if not cfg.wheel then
    compensation = m.pad
  end

  local scroll = ui.scroll({
    key = "carousel-scroll",
    flexGrow = 1,
    fill = "#00000000",
    paddingV = compensation,
    onScroll = "onScroll",
    revealKey = scrollReveal % 2 == 0 and "anchor-0" or "anchor-1",
    -- Intento de deshabilitar la barra de scroll nativa (prop no documentada
    -- pero presente en el C++ ScrollViewProps). Si el reconcilier la pasa,
    -- oculta la barra y evita saltos de layout por su aparición.
    scrollbarVisible = false,
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

  -- El nombre del archivo es un ajuste propio: se muestra aunque el pie este
  -- apagado, para que "Mostrar nombres" funcione por si solo. Con el pie
  -- encendido ya lo pinta el propio pie y no se duplica.
  if cfg.showFilenames and not cfg.chrome then
    local selectedPath = wallpapers[selected]
    if selectedPath then
      table.insert(rootChildren, ui.row({
        key = "filename",
        paddingH = 16,
        paddingV = 10,
        align = "center",
        justify = "center",
      }, {
        ui.label({
          text = basename(selectedPath),
          fontSize = 12,
          color = "on_surface",
          textAlign = "center",
          maxLines = 1,
        }),
      }))
    end
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
  -- Cambia la seleccion, y con ella el rango de miniaturas: el cursor del
  -- troceo se reinicia para no dejar huecos.
  thumbCursor = nil
  -- Un salto largo (dar la vuelta, ir al primero o al último) coloca la
  -- cinta directamente: si no, recorrería los cientos de fondos de golpe. Un
  -- avance de pocos pasos, en cambio, sí se desliza.
  if math.abs(selected - viewPos) > 4 then
    viewPos = selected
    animating = false
  else
    animating = true
  end
  wakeUp()
  render()
  -- Las miniaturas del entorno se piden en cada cambio de seleccion: si solo
  -- se pidieran al final de la animacion, un salto al principio o al final de
  -- la lista (Home, End, aleatorio o la vuelta de la cinta) dejaria las
  -- tarjetas sin imagen. El calculo va troceado: si queda trabajo, lo
  -- continua el frame tick.
  if ensureThumbs() then
    pendingThumbs = true
  end
end

move = function(delta)
  if #wallpapers == 0 then
    return
  end
  lastClickIndex = nil
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
  lastClickIndex = nil
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
  -- Una recarga por cambio de ajustes hace el mismo trabajo pesado que la
  -- carga inicial, asi que va por el mismo camino troceado.
  pendingInit = true
  initStage = 0
  pendingThumbs = false
  keepSelectionPath = previous
  wallpapers = {}
  selected = 1
  viewPos = 1.0
  animating = false
  hovered = nil
  scrollOffset = 0
  expectedScrollOffset = 0
  scrollAccum = 0
  lastClickIndex = nil
  lastClickMs = 0
  -- El frame tick no se apaga: lo NeedsFrameTick alimenta la carga troceada,
  -- la animacion de la cinta y la repeticion de las teclas.
  wakeUp()
end

-- Recentra el scroll: el ancla está tan abajo que al revelarla el scroll
-- salta SCROLL_JUMP px hacia arriba, dejando sitio para seguir subiendo. El
-- relleno se adelanta al salto para que la cinta no dé un tirón.
recenterScroll = function()
  local m = metrics()
  local scale = uiScale()
  -- El scroll salta hacia arriba para reabrir el recorrido. El salto se
  -- calcula con el relleno que Noctalia va a dejar puesto (revealKey apunta
  -- al ancla), de modo que la cinta no se mueve ni un píxel.
  -- Objetivo del salto, en px lógicos.
  local target = scrollOffset / scale + SCROLL_JUMP
  -- Distancia del ancla al inicio del contenido, en px lógicos. La primera
  -- vez se estima; a partir de ahi se mide con el salto real.
  local offset = anchorOffset or (m.viewport - m.pad - 1)
  scrollComp = target - offset - 1 + m.viewport
  scrollResetting = true
  scrollReveal = scrollReveal + 1
  -- El scroll mide en px de la superficie: el objetivo va escalado.
  scrollOffset = target * scale
  expectedScrollOffset = scrollOffset
  scrollAccum = 0
  lastRecenterComp = scrollComp
  render()
  scrollComp = nil
end

function onOpen(_context)
  opened = true
  noctalia.state.set("carousel.open", true)
  math.randomseed(os.time())
  loadConfig()
  -- Marcadores de presupuesto: el shell anota cada linea con su hora, asi que
  -- la diferencia entre los dos es lo que tardo el callback (lo comprueba
  -- bin/check-callback-budget.py).
  local onOpenStarted = os.clock()
  noctalia.log("wc-budget onOpen begin")
  -- Aqui no se hace trabajo pesado. El shell aborta un callback que se pasa
  -- de su presupuesto de CPU (25 ms) y el panel se queda a medias: escanear
  -- el directorio, localizar el fondo actual y calcular las miniaturas van al
  -- frame tick, en trozos.
  pendingInit = true
  initStage = 0
  pendingThumbs = false
  keepSelectionPath = nil
  wallpapers = {}
  selected = 1
  viewPos = 1.0
  animating = false
  hovered = nil
  heldKey = nil
  lastClickIndex = nil
  lastClickMs = 0
  scrollOffset = 0
  expectedScrollOffset = 0
  scrollAccum = 0
  scrollResetting = false
  thumbErrorShown = false
  -- El frame tick sirve para la carga inicial troceada, para la animacion de
  -- la cinta y para la repeticion de las teclas.
  wakeUp()
  noctalia.log(string.format("wc-budget onOpen end cost=%.2f ms", (os.clock() - onOpenStarted) * 1000))
end

function onClose()
  opened = false
  animating = false
  heldKey = nil
  -- Si el panel se cerrara con un reinicio a medias, el primer evento de la
  -- sesion nueva se tragaria sin motivo.
  scrollResetting = false
  scrollAccum = 0
  expectedScrollOffset = 0
  -- Al cerrar se apaga el tick: al reabrir tiene que volver a encenderse (y
  -- el host solo pide frames en esa transicion).
  panel.setNeedsFrameTick(false)
  noctalia.state.set("carousel.open", false)
end

function onConfigChanged()
  if opened then
    reload(true)
  end
end

-- Desplazamiento vertical del scroll. El scroll se usa solo como sensor de la
-- rueda: su desplazamiento se compensa con el relleno del propio scroll (para
-- que la cinta no se mueva de sitio) y el salto accumulated mueve el carrusel.
function onScroll(offset, _maxOffset)
  local newOffset = tonumber(offset) or 0
  local scrollStarted = os.clock()
  wakeUp()

  -- El recentro: el shell acaba de saltar al ancla. Ese salto es nuestro, no
  -- del usuario, y es el unico desplazamiento que el shell hace por su cuenta
  -- (el resto lo mueve la rueda), asi que va antes de nada: si se mezclara
  -- con la cuenta, el dentado siguiente se perderia.
  --
  -- El relleno del scroll no genera ningun evento: la cinta se mantiene quieta
  -- porque el contenido se coloca en (relleno - desplazamiento) y ambos crecen
  -- a la vez, asi que el shell no mueve el scroll al cambiar el relleno.
  if scrollResetting then
    scrollResetting = false
    scrollOffset = newOffset
    scrollAccum = 0
    -- El salto real mide donde está el ancla. Con ese dato el relleno del
    -- scroll se calcula al milimetro y el recentrado no mueve la cinta.
    if lastRecenterComp then
      local scale = uiScale()
      local viewport = panelHeight() - VIEWPORT_PADDING * 2
      -- Distancia real del ancla dentro del contenido (px lógicos).
      local measured = (newOffset - lastRecenterComp * scale - scale + viewport) / scale
      local ideal = viewport / scale - metrics().pad - 1
      anchorOffset = measured
      -- Y el hueco hasta el ancla se ajusta para que el salto deje la cinta
      -- en el mismo sitio de la pantalla.
      local correction = measured - ideal
      if correction > 60 then
        correction = 60
      elseif correction < -60 then
        correction = -60
      end
      anchorGapAdjust = anchorGapAdjust - correction
      lastRecenterComp = nil
    end
    render()
    return
  end

  -- Cuando el scroll llega al principio no puede seguir subiendo: se recentra
  -- saltando hacia abajo para reabrir el recorrido.
  if newOffset <= 0.5 then
    scrollOffset = newOffset
    recenterScroll()
    return
  end

  -- El desplazamiento se acumula aqui y no en el frame tick: la rueda no puede
  -- depender de un mecanismo que el shell puede no ejecutar. Se avanza la
  -- cinta en cuanto hay un dentado completo y el resto se guarda para el
  -- siguiente.
  local delta = newOffset - scrollOffset
  scrollOffset = newOffset
  -- Sincronizar offset esperado: si el shell reporta un salto grande (animación
  -- o recálculo), nos alineamos a lo reportado; si es un dentado normal,
  -- avanzamos el esperado en SCROLL_STEP por paso procesado.
  if math.abs(delta) > SCROLL_STEP * 2 then
    expectedScrollOffset = newOffset
  end
  if math.abs(delta) > 0.5 then
    -- Un salto mucho mayor que un dentado no lo ha dado el usuario: el shell
    -- se reposiciona solo (al recalcular el relleno o al revelar el ancla) y
    -- eso no debe mover la cinta de golpe. Se sincroniza y se sigue.
    if math.abs(delta) > SCROLL_STEP * 2 then
      scrollAccum = 0
      render()
      return
    end
    -- Al cambiar de sentido lo que queda acumulado pertenece al sentido
    -- contrario, asi que no sirve: si se conserva, el resto y el dentado
    -- nuevo no llegan a completar un paso y el primer dentado del giro nuevo
    -- se traga (la cinta se queda quieta un dentado y luegoresponde).
    if scrollAccum ~= 0 and (delta > 0) ~= (scrollAccum > 0) then
      scrollAccum = 0
    end
    scrollAccum = scrollAccum + delta
    local steps = math.floor((math.abs(scrollAccum) + SCROLL_EPS) / SCROLL_STEP)
    if steps > 0 then
      local direction = scrollAccum > 0 and 1 or -1
      scrollAccum = scrollAccum - direction * steps * SCROLL_STEP
      -- Avanzar el offset esperado en surface px por cada paso procesado.
      expectedScrollOffset = expectedScrollOffset + direction * steps * SCROLL_STEP
      move(direction * steps)
    else
      -- Aunque no haya salto completo, el relleno del scroll cambia: hay que
      -- repintar para que la cinta no se mueva de sitio.
      render()
    end
  end
  noctalia.log(string.format("wc-budget onScroll end cost=%.2f ms", (os.clock() - scrollStarted) * 1000))
end

function onFrameTick(deltaMs)
  local dt = tonumber(deltaMs) or 16

  -- 0. Carga inicial troceada: escaneo del directorio, eleccion del fondo
  -- actual y miniaturas. Cada etapa va en un trozo, para que ni este callback
  -- ni el de onOpen se passen del presupuesto de CPU del shell.
  if pendingInit then
    local stageStarted = os.clock()
    if initStage == 0 then
      scanBegin()
      initStage = 1
    elseif initStage == 1 then
      if not scanChunk() then
        initStage = 2
      end
    elseif initStage == 2 then
      -- Posicion de apertura: por defecto, un fondo aleatorio (la cinta es
      -- circular, asi que siempre se ven tarjetas a los dos lados). Al cambiar
      -- ajustes se conserva el fondo que estaba seleccionado, y con
      -- `open_random` apagado se abre en el fondo actual del escritorio.
      local keep = keepSelectionPath
      keepSelectionPath = nil
      if keep then
        selected = indexOfPath(keep) or indexOfPath(currentWallpaperPath()) or 1
      elseif cfg.openRandom and #wallpapers > 1 then
        selected = math.random(1, #wallpapers)
      else
        selected = indexOfPath(currentWallpaperPath()) or 1
      end
      viewPos = selected
      animating = false
      scrollOffset = 0
      scrollAccum = 0
      scrollResetting = false
      initStage = 3
    elseif initStage == 3 then
      if not ensureThumbs() then
        initStage = 4
      end
    else
      -- Etapa 4: la cinta ya esta montada. El scroll arranca en cero, sin
      -- recorrido hacia arriba: se recentra para que la rueda pueda ir en
      -- ambos sentidos.
      if #wallpapers > 0 and cfg.wheel then
        recenterScroll()
      else
        render()
      end
      initStage = 5
      pendingInit = false
    end
    noctalia.log(string.format("wc-budget init stage %d cost=%.2f ms cursor=%s", initStage, (os.clock() - stageStarted) * 1000, tostring(thumbCursor)))
  elseif pendingThumbs then
    local thumbsStarted = os.clock()
    if not ensureThumbs() then
      pendingThumbs = false
    end
    noctalia.log(string.format("wc-budget thumbs cost=%.2f ms", (os.clock() - thumbsStarted) * 1000))
  end

  -- 1. Autorepeat de las flechas: la pulsación repetida del teclado no llega
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

  -- 2. Animación de la cinta: la posición visible persigue a la seleccionada.
  local difference = selected - viewPos
  if math.abs(difference) < 0.002 then
    if animating then
      viewPos = selected
      animating = false
      render()
      if ensureThumbs() then
        pendingThumbs = true
      end
    end
  else
    local timeConstant = 120 + math.min(380, math.abs(difference) * 12)
    local factor = 1 - math.exp(-dt / timeConstant)
    viewPos = viewPos + difference * factor
    render()
  end

  -- 3. Si no queda nada que mover, se apaga el frame tick (ver wakeUp): el
  --    host solo vuelve a pedir frames cuando el flag pasa de falso a true.
  local busy = animating or heldKey ~= nil or pendingInit or pendingThumbs
  if not busy then
    panel.setNeedsFrameTick(false)
  end
end

function onKey(chord, pressed)
  if #wallpapers == 0 then
    return
  end
  wakeUp()
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
      lastClickIndex = nil
      selectIndex(1)
    end
  elseif chord == "End" then
    if pressed then
      lastClickIndex = nil
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

-- Al cargar la entrada el flag del frame tick se pone a false. El host solo
-- vuelve a pedir frames cuando el flag pasa de false a true, asi que tras una
-- recarga en caliente (que deja el flag en true) el tick se quedaria muerto:
-- con el flag a false, el siguiente wakeUp() lo vuelve a encender.
panel.setNeedsFrameTick(false)
