-- El panel usa require("./merge.luau"): en Lua 5.4 hay que aadir la carpeta
-- del plugin al package.path para que el modulo se encuentre.
local function _scriptDir()
  local src = debug.getinfo(1, "S").source
  if src:sub(1, 1) == "@" then
    return src:sub(2):match("^(.*)[/\\][^/\\]*$") or "."
  end
  return "."
end
package.path = _scriptDir() .. "/?.luau;" .. package.path

-- ------------------------------------------------------------- simulador

-- Carpeta propia de esta ejecucion: con un nombre fijo, dos pruebas a la vez
-- (por ejemplo, dos sesiones) se pisan y fallan sin que nada este roto.
local DIR = os.getenv("NOTES_TEST_DIR")
  or ("/tmp/notes-panel-test-" .. tostring(math.random(1000000, 9999999)))
local DATA_DIR = DIR .. "/data"

local pins = {}

-- Bitacora de las operaciones con ficheros: sirve para comprobar que la nota
-- actual se publica de forma atomica (se escribe a un temporal y se renombra)
-- y no escribiendo el fichero final a medias.
local bitacora = {}

local function limpia()
  os.execute("rm -rf " .. DIR)
  os.execute("mkdir -p " .. DIR .. " " .. DATA_DIR)
  pins = {}
  for i in pairs(bitacora) do bitacora[i] = nil end
  if erroresNotificados then for i in pairs(erroresNotificados) do erroresNotificados[i] = nil end end
  if botones then for i in pairs(botones) do botones[i] = nil end end
end

-- El mock usa el disco de verdad: las notas y el current.json son ficheros
-- reales, asi que se prueban de verdad las escrituras atomicas (temporal +
-- renombrado) y las lecturas a medias.
local function escribir(path, content)
  local f = io.open(path, "w")
  if f == nil then
    return false
  end
  f:write(content)
  f:close()
  return true
end

local function leer(path)
  local f = io.open(path, "r")
  if f == nil then
    return nil
  end
  local c = f:read("*a")
  f:close()
  return c
end

local function existe(path)
  local f = io.open(path, "r")
  if f == nil then
    return false
  end
  f:close()
  return true
end

local function listar(path)
  local out = {}
  local p = io.popen("ls -A " .. path .. " 2>/dev/null")
  if p == nil then
    return out
  end
  for line in p:lines() do
    out[#out + 1] = line
  end
  p:close()
  return out
end

local function json_encode(v)
  -- Solo lo que usa el panel: una tabla plana de cadenas.
  if type(v) ~= "table" then
    return tostring(v)
  end
  local partes = {}
  for k, val in pairs(v) do
    if type(val) == "string" then
      partes[#partes + 1] = string.format('"%s":"%s"', tostring(k), val)
    else
      partes[#partes + 1] = string.format('"%s":%s', tostring(k), tostring(val))
    end
  end
  return "{" .. table.concat(partes, ",") .. "}"
end

local function json_decode(s)
  local out = {}
  for k, v in s:gmatch('"([^"]*)":"([^"]*)"') do
    out[k] = v
  end
  -- Tambien los valores sin comillas (true/false/numeros)
  for k, v in s:gmatch('"([^"]*)":([^,}]+)') do
    if out[k] == nil then
      local t = v:gsub("^%s+", ""):gsub("%s+$", "")
      if t == "true" then
        out[k] = true
      elseif t == "false" then
        out[k] = false
      else
        out[k] = t
      end
    end
  end
  return out
end

-- Los botones que crea el panel se guardan aqui para poder pulsar el de
-- confirmar el borrado (su onClick es el que llama a deleteNote).
local botones = {}

local function ui_button(props)
  props = props or {}
  botones[#botones + 1] = props
  return props
end

local state = {}
local erroresNotificados = {}

local mock = {
  getConfig = function(key)
    if key == "notes_dir" then
      return DIR
    end
    if key == "extension" then
      return "md"
    end
    return ""
  end,
  getSetting = function()
    return 1
  end,
  expandPath = function(p)
    return p
  end,
  setUpdateInterval = function() end,
  tr = function(key)
    return key
  end,
  log = function() end,
  notifyError = function(a, b)
    -- En Noctalia esto solo muestra un aviso: no interrumpe el panel.
    erroresNotificados[#erroresNotificados + 1] = tostring(a) .. " " .. tostring(b)
  end,
  formatTime = function(fmt)
    return "2026-01-01 00.00.00"
  end,
  pluginDataDir = function()
    return DATA_DIR
  end,
  mkdirAll = function(path)
    -- De verdad crea la carpeta: el panel guarda las copias de conflicto en
    -- <notesDir>/.conflicts/.
    os.execute("mkdir -p '" .. tostring(path) .. "'")
    return true
  end,
  readFile = function(path)
    return leer(path)
  end,
  writeFile = function(path, content)
    if path:match("%.pinned%.json$") then
      pins = json_decode(content)
    end
    bitacora[#bitacora + 1] = { op = "write", path = path }
    return escribir(path, content)
  end,
  renameFile = function(from, to)
    bitacora[#bitacora + 1] = { op = "rename", from = from, to = to }
    local ok = os.rename(from, to)
    if not ok then
      return false, "no se pudo renombrar"
    end
    return true
  end,
  removeFile = function(path)
    local ok = os.remove(path)
    return ok, ok and nil or "no se pudo borrar"
  end,
  fileExists = function(path)
    return existe(path)
  end,
  fileInfo = function(path)
    local content = leer(path)
    if content == nil then
      return nil
    end
    return { size = #content, mtime = 1700000000000 }
  end,
  listDir = function(path)
    return listar(path)
  end,
  json = { encode = json_encode, decode = json_decode },
  string = {
    trim = function(s)
      return (s:gsub("^%s+", ""):gsub("%s+$", ""))
    end,
  },
  state = {
    get = function(key)
      return state[key]
    end,
    set = function(key, value)
      state[key] = value
    end,
    watch = function() end,
  },
}

_G.noctalia = mock
_G.panel = {
  render = function() end,
  close = function() end,
  setWantsSecondTicks = function() end,
}
_G.ui = setmetatable({}, {
  __index = function(_, key)
    if key == "button" then
      return ui_button
    end
    return function()
      return {}
    end
  end,
})

-- Los modulos del plugin (merge, dirs, channel) se cargan a mano: el require
-- de Lua 5.4 convierte los puntos del nombre en carpetas, de modo que
-- "./merge.luau" no se encuentra solo. El runtime de Noctalia si lo resuelve.
for _, modName in ipairs({ "merge", "dirs", "channel" }) do
  package.loaded["./" .. modName .. ".luau"] = dofile(_scriptDir() .. "/" .. modName .. ".luau")
end

-- ------------------------------------------------------------- cargar

local function scriptDir()
  local src = debug.getinfo(1, "S").source
  if src:sub(1, 1) == "@" then
    return src:sub(2):match("^(.*)[/\\][^/\\]*$") or "."
  end
  return "."
end

-- El panel usa sintaxis de Luau (`+=`), que lua 5.4 no entiende: se
-- normaliza el fuente antes de cargarlo (los `+=` se convierten en `x = x + y`).
local function normaliza(src)
  src = src:gsub("(%s*)([A-Za-z_][%w_%.%[%]'\"]*)%s*%+=%s*", "%1%2 = %2 + ")
  src = src:gsub("(%s*)([A-Za-z_][%w_%.%[%]'\"]*)%s*%.%.=%s*", "%1%2 = %2 .. ")
  return src
end

local PANEL_PATH = scriptDir() .. "/panel.luau"
local fuente = normaliza(assert(io.open(PANEL_PATH, "r")):read("*a"))
local chunk, err = load(fuente, PANEL_PATH)
if not chunk then
  print("no se pudo cargar panel.luau: " .. tostring(err))
  os.exit(1)
end
local ok, loadErr = pcall(chunk)
if not ok then
  print("error al cargar panel.luau: " .. tostring(loadErr))
  os.exit(1)
end


return {
  mock = mock,
  state = state,
  botones = botones,
  bitacora = bitacora,
  erroresNotificados = erroresNotificados,
  pins = pins,
  DIR = DIR,
  DATA_DIR = DATA_DIR,
  limpia = limpia,
  escribir = escribir,
  leer = leer,
  existe = existe,
  listar = listar,
  json_encode = json_encode,
  json_decode = json_decode,
  ui_button = ui_button,
  normaliza = normaliza,
  scriptDir = scriptDir,
  PANEL_PATH = PANEL_PATH,
}
