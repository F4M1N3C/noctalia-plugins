--!nonstrict
-- Ajustes del plugin Lyrics Carousel compartidos por el panel y el widget.
--
-- Los cambios se guardan primero en una capa de overrides (un JSON pequeño
-- que Noctalia no vigila) y se vuelcan al settings.toml al cerrar el panel.
-- Motivo: escribir el settings.toml hace que Noctalia recargue la
-- configuracion, lo que cierra el panel que el usuario tiene delante y
-- descarta los clics siguientes.

local M = {}

local PLUGIN_ID = "faminec/lyrics-carousel"

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

local BOOL_KEYS = {
  marker = true, karaoke = true, equalizer = true, footer = true,
  hints = true, header = true, ghost = true,
}
local INT_KEYS = {
  font_size = true, spacing = true, animation_ms = true, offset_ms = true,
  width = true, height = true, visible_above = true, visible_below = true,
}
local FLOAT_KEYS = { active_scale = true }

M.BOOL_KEYS = BOOL_KEYS
M.INT_KEYS = INT_KEYS
M.FLOAT_KEYS = FLOAT_KEYS
M.DEFAULTS = DEFAULTS

local function overridesPath()
  local dir = noctalia.pluginDataDir()
  if dir == nil then
    return nil
  end
  return dir .. "/overrides.json"
end

local function readOverrides()
  local path = overridesPath()
  if path == nil then
    return {}
  end
  local raw = noctalia.readFile(path)
  if raw == nil or raw == "" then
    return {}
  end
  local ok, data = pcall(noctalia.json.decode, raw)
  if not ok or type(data) ~= "table" then
    return {}
  end
  return data
end

-- El panel consulta decenas de valores por render: el fichero de overrides
-- se cachea para no leerlo en cada consulta. La cache se invalida al
-- escribir (M.refresh) y tiene una caducidad corta por si el cambio viene
-- de fuera. Ojo: os.clock() es tiempo de CPU, no de reloj, asi que para la
-- caducidad se usa os.time().
local cached = {}
local cachedAt = 0
local CACHE_SECONDS = 2

function M.overrides()
  local now = os.time()
  if cachedAt ~= 0 and (now - cachedAt) < CACHE_SECONDS then
    return cached
  end
  cached = readOverrides()
  cachedAt = now
  return cached
end

--- Fuerza a releer los overrides (despues de escribir).
function M.refresh()
  cachedAt = 0
  cached = {}
end

--- Valor efectivo de un ajuste: overrides > configuracion > defecto.
function M.value(key)
  local override = readOverrides()[key]
  if override ~= nil then
    return override
  end
  local value = noctalia.getConfig(key)
  if value == nil then
    return DEFAULTS[key]
  end
  return value
end

function M.kindOf(key)
  if BOOL_KEYS[key] then
    return "bool"
  elseif INT_KEYS[key] then
    return "int"
  elseif FLOAT_KEYS[key] then
    return "float"
  end
  return "string"
end

--- Escribe un ajuste en la capa de overrides (inmediato, sin recargar).
function M.write(key, value)
  local dir = noctalia.pluginDir()
  if dir == nil then
    return false
  end
  return noctalia.runAsync({
    "python3",
    dir .. "/bin/set-setting.py",
    "override",
    key,
    tostring(value),
    M.kindOf(key),
  }, function(result)
    if result == nil or result.exitCode ~= 0 then
      local detail = ""
      if type(result) == "table" then
        detail = tostring(result.stderr or result.stdout or "")
      end
      noctalia.log(
        "lyrics-carousel: no se pudo guardar " .. key
          .. (detail ~= "" and (": " .. detail) or "")
      )
    end
  end) and true or false
end

--- Vuelca los overrides al settings.toml (para que la pagina de ajustes y el
--- panel muestran lo mismo).
function M.merge()
  local dir = noctalia.pluginDir()
  if dir == nil then
    return false
  end
  return noctalia.runAsync({
    "python3",
    dir .. "/bin/set-setting.py",
    "merge",
  }, function(result)
    if result == nil or result.exitCode ~= 0 then
      noctalia.log("lyrics-carousel: no se pudieron volcar los ajustes")
    end
  end) and true or false
end

--- Interpreta la carga de un IPC: "clave=valor [tipo]" o "clave valor [tipo]".
function M.parse(payload)
  if type(payload) ~= "string" then
    return nil
  end
  local key
  local rest
  local head, tail = payload:match("^%s*([^=%s]+)%s*=%s*(.-)%s*$")
  if head ~= nil then
    key = head
    rest = tail or ""
  else
    local pieces = {}
    for piece in payload:gmatch("%S+") do
      pieces[#pieces + 1] = piece
    end
    if #pieces < 2 then
      return nil
    end
    key = table.remove(pieces, 1)
    rest = table.concat(pieces, " ")
  end
  key = key:gsub("^-+", "")
  if DEFAULTS[key] == nil then
    return nil
  end
  -- El tipo puede ser el ultimo token; el valor es el resto.
  local kind = "string"
  local pieces = {}
  for piece in rest:gmatch("%S+") do
    pieces[#pieces + 1] = piece
  end
  local last = pieces[#pieces]
  if last == "bool" or last == "int" or last == "float" or last == "string" then
    kind = last
    table.remove(pieces)
  end
  local value = table.concat(pieces, " ")
  if kind == "bool" then
    value = value == "true" or value == "1"
  elseif kind == "int" then
    value = tonumber(value) or value
  elseif kind == "float" then
    value = tonumber(value) or value
  end
  return key, value, kind
end

--- Fija un ajuste (o lo alterna si no hay valor).
function M.apply(key, value)
  if value == nil then
    local current = M.value(key)
    if type(current) == "boolean" then
      value = not current
    else
      return nil
    end
  end
  M.write(key, value)
  return value
end

return M
