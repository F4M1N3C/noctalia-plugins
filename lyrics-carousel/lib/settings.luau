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
  direction = "down",
  marker = false,
  karaoke = true,
  footer = false,
  hints = false,
  header = false,
  spacing = 2,
  ghost = true,
  offset_ms = 0,
  width = 1200,
  height = 820,
  anchor = "center",
  custom_x = 100,
  custom_y = 100,
  accent = "primary",
  custom_color = "#e46767",
  active_scale = 1.35,
  visible_above = 6,
  visible_below = 6,
  glyph = "music",
  visualizer = true,
  visualizer_position = "bottom",
  visualizer_coverage = 25,
  translate_lyrics = false,
}

local BOOL_KEYS = {
  marker = true, karaoke = true, footer = true,
  hints = true, header = true, ghost = true,
  visualizer = true,
}
local INT_KEYS = {
  font_size = true, spacing = true, offset_ms = true,
  width = true, height = true, visible_above = true, visible_below = true,
  custom_x = true, custom_y = true,
  visualizer_coverage = true,
}
local FLOAT_KEYS = { active_scale = true }

M.BOOL_KEYS = BOOL_KEYS
M.INT_KEYS = INT_KEYS
M.FLOAT_KEYS = FLOAT_KEYS
M.DEFAULTS = DEFAULTS

--- Rangos (min, max) de los ajustes numericos.
---
--- El manifiesto solo declara el icono de la barra, asi que estos rangos ya
--- no estan en dos sitios: los aplica el panel antes de escribir y el script
--- al leerlos. Las dos copias tienen que coincidir (lo comprueba el
--- autotest): si el panel dejara pasar un valor que el script descarta, el
--- usuario veria un numero que no se aplica.
local LIMITS = {
  font_size = { 6, 96 },
  spacing = { 1, 6 },
  offset_ms = { -3000, 3000 },
  width = { 400, 3840 },
  height = { 200, 2160 },
  custom_x = { 0, 10000 },
  custom_y = { 0, 10000 },
  visible_above = { 0, 20 },
  visible_below = { 0, 20 },
  active_scale = { 1.0, 2.5 },
  visualizer_coverage = { 5, 50 },
}

M.LIMITS = LIMITS

--- Patrones de los ajustes de texto libre.
---
--- El glifo es un nombre de icono de Material Symbols y el color es un
--- hexadecimal: si se guarda cualquier otra cosa, la barra se queda sin
--- icono o la ventana sin color. Los patrones viven aqui y no en el
--- panel para que las dos entradas (panel y widget) apliquen los
--- mismos: el IPC del widget tambien puede escribir estos ajustes.
local PATTERNS = {
  glyph = "^[a-z0-9-]+$",
  custom_color = "^#%x%x%x%x%x%x$",
  -- La fuente es texto libre, pero vacia dejaria la ventana sin tipografia:
  -- el campo del panel y el IPC del widget tienen que rechazarla igual. Un
  -- salto de linea tampoco vale: la fuente se pasa al comando de kitty.
  font_family = "^[^\n]+$",
  visualizer_position = "^(top|bottom|left|right)$",
}

M.PATTERNS = PATTERNS

--- Valida el formato de un ajuste de texto libre.
---
--- Devuelve el valor si cumple el patron y nil si no. Los ajustes sin
--- patron (o sin limite) se devuelven tal cual.
function M.validate(key, value)
  local pattern = PATTERNS[key]
  if pattern == nil then
    return value
  end
  if type(value) ~= "string" or value:match(pattern) == nil then
    return nil
  end
  return value
end

--- Recorta un valor a los limites de su ajuste.
---
--- Vive aqui y no en el panel para que las dos entradas (panel y widget)
--- recorten igual: si cada una lo hiciera por su cuenta, el widget
--- dejaria guardar un 500 en un campo que el panel limita a 96.
function M.clamp(key, value)
  local limit = LIMITS[key]
  if limit == nil then
    return value
  end
  local number = tonumber(value)
  if number == nil then
    return nil
  end
  if number < limit[1] then
    number = limit[1]
  elseif number > limit[2] then
    number = limit[2]
  end
  if INT_KEYS[key] then
    number = math.floor(number)
  end
  return number
end

--- Normaliza un valor a booleano.
---
--- Noctalia no siempre entrega los interruptores como booleanos: el control
--- `ui.toggle` pasa el valor como la cadena "true" o "false". Comparar con
--- `== true` haria que un interruptor encendido se leyera apagado.
---
--- Vive aqui y no en el panel para que el panel y el widget lean los valores
--- igual: si cada uno normalizara por su cuenta, un dia leerian distinto.
function M.truthy(value)
  if type(value) == "boolean" then
    return value
  end
  if type(value) == "number" then
    return value ~= 0
  end
  if type(value) == "string" then
    local text = value:lower():gsub("%s+", "")
    return text == "true" or text == "1" or text == "yes" or text == "on"
  end
  return false
end

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

--- Valor efectivo de un ajuste: overrides > configuracion > guardado > defecto.
function M.value(key)
  local override = M.overrides()[key]
  if override ~= nil then
    return override
  end
  local value = noctalia.getConfig(key)
  if value ~= nil then
    return value
  end
  -- El manifiesto solo declara el icono de la barra: el resto de ajustes los
  -- gestiona el panel. `noctalia.getConfig` unicamente devuelve las claves
  -- que conoce, asi que para las demas se usa lo que hay guardado en el
  -- settings.toml (lo lee el panel con M.useSaved). Es la misma fuente que
  -- lee el script: sin esta lectura el panel ensenaria los valores por
  -- defecto en lugar de los del usuario.
  local guardado = M.saved()[key]
  if guardado ~= nil then
    return guardado
  end
  return DEFAULTS[key]
end

--- Valores guardados en el settings.toml.
---
--- El panel los trae con el helper (`set-setting.py read`) y los deja aqui
--- con M.useSaved. No caducan: un valor solo cambia cuando el usuario lo
--- cambia, y cada via de cambio (el panel, la pagina de ajustes, el IPC del
--- widget) vuelve a pedirlos. Devolver el ultimo conocido es mejor que
--- ensenar los valores por defecto.
local saved = nil

--- Carga los valores leidos del settings.toml (JSON del helper).
function M.useSaved(raw)
  if type(raw) ~= "string" or raw == "" then
    return false
  end
  local ok, data = pcall(noctalia.json.decode, raw)
  if not ok or type(data) ~= "table" then
    return false
  end
  saved = data
  return true
end

function M.saved()
  return saved or {}
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
---
--- El callback recibe true si el helper ha guardado el ajuste y false si no:
--- sin el, quien llama no puede saber si el cambio se ha perdido.
function M.write(key, value, callback)
  local function finish(ok)
    M.refresh()
    if callback ~= nil then
      callback(ok)
    end
  end

  local dir = noctalia.pluginDir()
  if dir == nil then
    finish(false)
    return false
  end

  local ok, started = pcall(noctalia.runAsync, {
    "python3",
    dir .. "/bin/set-setting.py",
    "override",
    key,
    tostring(value),
    M.kindOf(key),
  }, function(result)
    local guardado = result ~= nil and result.exitCode == 0
    if not guardado then
      local detail = ""
      if type(result) == "table" then
        detail = tostring(result.stderr or result.stdout or "")
      end
      noctalia.log(
        "lyrics-carousel: no se pudo guardar " .. key
          .. (detail ~= "" and (": " .. detail) or "")
      )
    end
    finish(guardado)
  end)
  if not ok then
    noctalia.log("lyrics-carousel: no se pudo guardar " .. key .. ": " .. tostring(started))
    finish(false)
    return false
  end
  if started == false then
    finish(false)
    return false
  end
  return true
end

--- Vuelca los overrides al settings.toml (para que la pagina de ajustes y el
--- panel muestren lo mismo).
function M.merge(callback)
  local dir = noctalia.pluginDir()
  if dir == nil then
    if callback ~= nil then
      callback(false)
    end
    return false
  end
  local ok, started = pcall(noctalia.runAsync, {
    "python3",
    dir .. "/bin/set-setting.py",
    "merge",
  }, function(result)
    M.refresh()
    local guardado = result ~= nil and result.exitCode == 0
    if not guardado then
      noctalia.log("lyrics-carousel: no se pudieron volcar los ajustes")
    end
    if callback ~= nil then
      callback(guardado)
    end
  end)
  if not ok then
    if callback ~= nil then
      callback(false)
    end
    return false
  end
  if started ~= true then
    if callback ~= nil then
      callback(false)
    end
    return false
  end
  return true
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
  local kind = nil
  local pieces = {}
  for piece in rest:gmatch("%S+") do
    pieces[#pieces + 1] = piece
  end
  local last = pieces[#pieces]
  -- Solo se come el token si queda un valor detras: "font_family string"
  -- significa la fuente "string", no un valor vacio de tipo string.
  if #pieces > 1 and (last == "bool" or last == "int" or last == "float" or last == "string") then
    kind = last
    table.remove(pieces)
  end
  local value = table.concat(pieces, " ")
  -- Sin token de tipo se deduce de la clave: "set karaoke true" tiene que
  -- guardar un booleano, no la cadena "true" (el panel y el script lo
  -- leian de forma distinta y se contradician).
  if kind == nil then
    kind = M.kindOf(key)
  end
  if kind == "bool" then
    local text = value:lower():gsub("%s+", "")
    value = (text == "true" or text == "1" or text == "yes" or text == "on")
  elseif kind == "int" then
    local number = tonumber(value)
    if number == nil then
      return nil
    end
    value = math.floor(number)
  elseif kind == "float" then
    local number = tonumber(value)
    if number == nil then
      return nil
    end
    value = number
  end
  return key, value, kind
end

--- Fija un ajuste (o lo alterna si no hay valor).
---
--- Si no se pasa valor, se alterna: solo tiene sentido en un interruptor, asi
--- que en cualquier otro ajuste no se toca nada. El valor actual se lee con
--- la misma normalizacion que el panel, para que "true" (cadena) se lea igual
--- en los dos sitios.
function M.apply(key, value)
  if value == nil then
    if not BOOL_KEYS[key] then
      return nil
    end
    value = not M.truthy(M.value(key))
  else
    -- El recorte va aqui y no solo en el helper: el widget escribe por
    -- IPC y su valor tiene que ser el mismo que veria el panel.
    value = M.clamp(key, value)
    if value == nil then
      -- Rechazar en silencio deja al usuario (y al log) sin saber por que
      -- el IPC no ha cambiado nada.
      noctalia.log("lyrics-carousel: valor fuera de rango para " .. tostring(key))
      return nil
    end
    -- Lo mismo con el formato: un glifo con mayusculas o un color que
    -- no es un hexadecimal dejarian la barra o la ventana sin icono o
    -- sin color.
    value = M.validate(key, value)
    if value == nil then
      noctalia.log("lyrics-carousel: formato no válido para " .. tostring(key))
      return nil
    end
  end
  M.write(key, value)
  return value
end

return M
