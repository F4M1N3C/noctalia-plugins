--!nonstrict
-- Miniaturas de los widgets.
--
-- Cuando un widget está abierto se captura su zona de pantalla con `grim` y se
-- recorta con Pillow (bin/snapshot.py). La captura se cachea por geometría: si
-- la ventana no se ha movido, se reutiliza la imagen anterior.
--
-- Si no hay `grim`, o el script falla, el panel dibuja una miniatura
-- sintética (sin dependencias).

local util = require("./util.luau")

local M = {}

local CAPTURE_WIDTH = 320
local CAPTURE_HEIGHT = 190
local batchCounter = 0

-- FNV-1a de 32 bits (la multiplicación por 65599 cabe en un double de Luau).
local function hashText(text)
  local hash = 2166136261
  for index = 1, #text do
    hash = (hash * 65599 + string.byte(text, index)) % 4294967296
  end
  return string.format("%08x", math.floor(hash))
end

-- La carpeta de caché no cambia durante la vida del runtime: crearla en cada
-- llamada cargaba al panel de disco y hacia que onOpen se pasara del
-- presupuesto de CPU de Luau.
local cachedDir = nil

function M.cacheDir()
  if cachedDir ~= nil then
    if cachedDir == false then
      return nil
    end
    return cachedDir
  end
  local dir = noctalia.pluginDataDir()
  if dir == nil then
    cachedDir = false
    return nil
  end
  local path = dir .. "/thumbs"
  -- mkdirAll puede fallar (permisos, disco lleno): se comprueba antes de
  -- seguir, y si falla se avisa en vez de reventar el script.
  local created, createError = pcall(noctalia.mkdirAll, path)
  if not created or createError == false then
    noctalia.log("floating-term: no se pudo crear " .. path)
    cachedDir = false
    return nil
  end
  cachedDir = path
  return path
end

function M.signature(window)
  return string.format("%d,%d,%d,%d", window.x, window.y, window.w, window.h)
end

function M.thumbPath(name, signature)
  local dir = M.cacheDir()
  if dir == nil then
    return nil
  end
  return string.format("%s/%s-%s.png", dir, util.slug(name), hashText(signature))
end

function M.cached(name, signature)
  local path = M.thumbPath(name, signature)
  if path == nil then
    return nil
  end
  if noctalia.fileExists(path) then
    return path
  end
  return nil
end

function M.toolsAvailable()
  if not noctalia.commandExists("grim") then
    return false
  end
  if not noctalia.commandExists("python3") then
    return false
  end
  local script = util.pluginPath("bin/snapshot.py")
  if script == nil then
    return false
  end
  return noctalia.fileExists(script)
end

-- Rutas de las miniaturas que las tarjetas están usando ahora mismo.
-- `windows` acepta una lista o un mapa de ventanas abiertas (con `name`, `x`,
-- `y`, `w` y `h`).
function M.currentPaths(windows)
  local paths = {}
  for _, window in pairs(windows or {}) do
    if type(window) == "table" and window.name ~= nil then
      local path = M.thumbPath(window.name, M.signature(window))
      if path ~= nil then
        paths[path] = true
      end
    end
  end
  return paths
end

-- Borra las miniaturas que ya no usa ninguna tarjeta y los archivos de lote
-- que se hayan quedado por el camino.
--
-- Se borra por *uso* y no por widget: si dos capturas se cruzan (la ventana se
-- movió mientras se capturaba), la limpieza anterior podía borrar justo el
-- fichero que el árbol de la UI tenía referenciado y el host se quejaba con
-- "image failed to load". Con esta lista, lo que se usa nunca se borra.
function M.pruneUnused(currentPaths)
  local dir = M.cacheDir()
  if dir == nil then
    return
  end
  local files = noctalia.listDir(dir)
  if files == nil then
    return
  end
  for _, file in ipairs(files) do
    if file:sub(1, 6) == "batch-" or file == "batch.json" then
      pcall(noctalia.removeFile, dir .. "/" .. file)
    elseif file:sub(-4) == ".png" and not currentPaths[dir .. "/" .. file] then
      pcall(noctalia.removeFile, dir .. "/" .. file)
    end
  end
end

-- Captura las ventanas indicadas. `entries` = { {name, output, x, y, w, h} }
function M.capture(entries, callback)
  if #entries == 0 then
    if callback ~= nil then
      callback()
    end
    return
  end

  local dir = M.cacheDir()
  local script = util.pluginPath("bin/snapshot.py")
  if dir == nil or script == nil then
    if callback ~= nil then
      callback()
    end
    return
  end

  local items = {}
  for _, entry in ipairs(entries) do
    local signature = M.signature(entry)
    local path = M.thumbPath(entry.name, signature)
    if path ~= nil and not noctalia.fileExists(path) then
      table.insert(items, {
        name = entry.name,
        output = entry.output,
        x = math.floor(entry.x),
        y = math.floor(entry.y),
        w = math.floor(entry.w),
        h = math.floor(entry.h),
        width = CAPTURE_WIDTH,
        height = CAPTURE_HEIGHT,
        out = path,
      })
    end
  end

  if #items == 0 then
    if callback ~= nil then
      callback()
    end
    return
  end

  local ok, encoded = pcall(noctalia.json.encode, items)
  if not ok or encoded == nil then
    if callback ~= nil then
      callback()
    end
    return
  end

  -- Cada captura usa su propio archivo de lote: si dos refrescos se cruzan,
  -- uno no puede pisar el lote del otro.
  batchCounter = batchCounter + 1
  local batchPath = string.format("%s/batch-%d-%d.json", dir, os.time(), batchCounter)
  if not noctalia.writeFile(batchPath, encoded) then
    if callback ~= nil then
      callback()
    end
    return
  end

  local started = noctalia.runAsync({
    "python3",
    script,
    batchPath,
  }, function(result)
    -- El archivo de lote ya no sirve: se borra para no dejar basura.
    pcall(noctalia.removeFile, batchPath)
    if result.exitCode ~= 0 then
      local detail = util.trim(result.stderr or "")
      if detail ~= "" then
        noctalia.log("floating-term: captura: " .. detail)
      end
    end
    -- La limpieza de miniaturas antiguas la hace quien llama, que sabe qué
    -- tarjetas hay ahora mismo.
    if callback ~= nil then
      callback()
    end
  end)
  if not started then
    pcall(noctalia.removeFile, batchPath)
    if callback ~= nil then
      callback()
    end
  end
end

return M
