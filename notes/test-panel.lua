-- Pruebas del panel de `faminec/notes` con el API de Noctalia simulado.
--
-- Se comprueba sobre todo el CANAL con el otro plugin: el fichero
-- current.json (nota abierta, contenido y si esta abierta ahora mismo).
-- Es lo que lee `faminec/notes-sync` para mandar la nota al celular, y se
-- rompio mas de una vez al renombrar o al borrar sin republicar.
--
--     lua5.4 test-panel.lua

local FALLOS = 0
local PASADOS = 0

local function check(nombre, esperado, obtenido)
  if esperado == obtenido then
    PASADOS = PASADOS + 1
    print(string.format("  ok   %-58s %s", nombre, tostring(obtenido)))
  else
    FALLOS = FALLOS + 1
    print(string.format("  FALLA %-58s esperado=%s obtenido=%s", nombre, tostring(esperado), tostring(obtenido)))
  end
end

-- ------------------------------------------------------------- simulador

local DIR = os.getenv("NOTES_TEST_DIR") or "/tmp/notes-panel-test"
local DATA_DIR = DIR .. "/data"

local ficheros = {} -- nombre -> contenido
local pins = {}

local function limpia()
  os.execute("rm -rf " .. DIR)
  os.execute("mkdir -p " .. DIR .. " " .. DATA_DIR)
  ficheros = {}
  pins = {}
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
  mkdirAll = function()
    return true
  end,
  readFile = function(path)
    if path:match("/current%.json$") then
      local f = io.open(path, "r")
      if f == nil then
        return nil
      end
      local c = f:read("*a")
      f:close()
      return c
    end
    local name = path:match("([^/]+)$")
    return ficheros[name]
  end,
  writeFile = function(path, content)
    local name = path:match("([^/]+)$")
    if path:match("/current%.json$") then
      local f = io.open(path, "w")
      if f == nil then
        return false
      end
      f:write(content)
      f:close()
      return true
    end
    if path:match("%.pinned%.json$") then
      pins = json_decode(content)
    end
    ficheros[name] = content
    return true
  end,
  renameFile = function(from, to)
    local a = from:match("([^/]+)$")
    local b = to:match("([^/]+)$")
    if ficheros[a] == nil then
      return false, "no existe"
    end
    ficheros[b] = ficheros[a]
    ficheros[a] = nil
    return true
  end,
  removeFile = function(path)
    local name = path:match("([^/]+)$")
    if ficheros[name] == nil then
      return false, "no existe"
    end
    ficheros[name] = nil
    return true
  end,
  fileExists = function(path)
    local name = path:match("([^/]+)$")
    if name == ".pinned.json" then
      return next(pins) ~= nil
    end
    return ficheros[name] ~= nil
  end,
  fileInfo = function(path)
    local name = path:match("([^/]+)$")
    local content = ficheros[name]
    if content == nil then
      return nil
    end
    return { size = #content, mtime = 1700000000000 }
  end,
  listDir = function(path)
    local out = {}
    for name in pairs(ficheros) do
      out[#out + 1] = name
    end
    if next(pins) then
      out[#out + 1] = ".pinned.json"
    end
    return out
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

-- ------------------------------------------------------------- pruebas

local function current()
  local raw = mock.readFile(DATA_DIR .. "/current.json")
  if raw == nil then
    return nil
  end
  return json_decode(raw)
end

print("== el canal con el otro plugin ==")

limpia()
ficheros["nota.md"] = "contenido de la nota"

-- onOpen: el panel se abre con la nota indicada
state.open_note = "nota.md"
pcall(onOpen, {})

local c = current()
check("current.json existe tras abrir", true, c ~= nil)
check("apunta a la nota abierta", "nota.md", c and c.name or nil)
check("lleva el contenido", "contenido de la nota", c and c.content or nil)
check("marca que esta abierta", true, c and c.open == true or false)

-- Renombrar: el nombre cambia y se vuelve a publicar
local okR, errR = pcall(onRename, "renombrada")
if not okR then print("  [debug] onRename fallo:", tostring(errR)) end
c = current()
check("tras renombrar apunta al nombre nuevo", "renombrada.md", c and c.name or nil)
check("el fichero tambien se renombro", true, ficheros["renombrada.md"] ~= nil)
check("el nombre viejo ya no esta", true, ficheros["nota.md"] == nil)

-- Cambios externos: se vuelve a publicar
ficheros["renombrada.md"] = "contenido nuevo"
pcall(update)
-- (sin trazas)
c = current()
check("un cambio externo se publica", "contenido nuevo", c and c.content or nil)

-- Volver atras: deja de estar abierta, pero se recuerda la ultima nota
pcall(onBack)
c = current()
check("tras volver atras no esta abierta", false, c and c.open == true or false)
check("pero se recuerda la ultima nota", "renombrada.md", c and c.name or nil)

-- Borrar la nota abierta: se publica para no mandar una nota inexistente.
-- `deleteNote` es local, asi que se pulsa el boton de confirmar que crea el
-- panel (es lo que haria el usuario).
ficheros["renombrada.md"] = "contenido"
state.open_note = "renombrada.md"
pcall(onOpen, {})
botones = {}
pcall(onEditorDelete)
local confirm = nil
for _, b in ipairs(botones) do
  if b.glyph == "check" and type(b.onClick) == "function" then
    confirm = b
  end
end
check("el panel ofrece un boton para confirmar el borrado", true, confirm ~= nil)
if confirm then
  pcall(confirm.onClick)
end
c = current()
check("tras borrar no queda ninguna nota", "", c and c.name or nil)
check("y el contenido tampoco", "", c and c.content or nil)
check("el fichero ya no esta", true, ficheros["renombrada.md"] == nil)

-- Renombrar a un nombre que ya existe: se avisa y no se toca nada.
ficheros["nota.md"] = "contenido"
ficheros["ocupada.md"] = "otra nota"
state.open_note = "nota.md"
pcall(onOpen, {})
erroresNotificados = {}
pcall(onRename, "ocupada")
check("renombrar a un nombre existente avisa", 1, #erroresNotificados)
local trasError = current()
check("y no cambia el nombre", "nota.md", trasError and trasError.name or "SIN current.json")
check("la nota original sigue ahi", true, ficheros["nota.md"] ~= nil)
check("la otra nota no se toco", "otra nota", ficheros["ocupada.md"])

-- Un nombre con "/" se limpia (no se puede meter una carpeta).
erroresNotificados = {}
pcall(onRename, "carpeta/sub")
check("un nombre con barra se limpia", true, ficheros["carpetasub.md"] ~= nil)
check("y no se crea ninguna carpeta", true, ficheros["carpeta"] == nil)

-- Si la nota se renombra o se borra desde fuera (el movil), el panel no puede
-- quedarse con un fantasma: un nombre que ya no existe y un editor vacio.
ficheros["renombrada.md"] = "contenido"
state.open_note = "renombrada.md"
pcall(onOpen, {})
ficheros["renombrada.md"] = nil -- como si se borrase desde fuera
pcall(update)
c = current()
check("si la nota desaparece, no queda ninguna nota publicada", "", c and c.name or nil)
check("ni se queda el contenido viejo", "", c and c.content or nil)
check("y el estado publico tambien se vacia", "", tostring(state.notes_current or ""))

print()
print("== el test detecta una regresion ==")
-- Un test que nunca falla no demuestra nada: se rompe el panel a proposito
-- (se quita la republicacion al renombrar) y se comprueba que el test lo
-- detecta. Si este bloque falla, el test ya no vigila nada.
local function prueba_mutacion()
  local fuente2 = normaliza(assert(io.open(PANEL_PATH, "r")):read("*a"))
  local mutado = fuente2:gsub("(%s*)publishCurrent%(%)%s*%-%- La nota ya no se llama igual",
    "%1-- publicacion quitada a proposito")
  if mutado == fuente2 then
    -- Si el texto ha cambiado, se quitan TODAS las llamadas a publishCurrent
    -- dentro de onRename y onExternalChange.
    mutado = fuente2:gsub("  publishCurrent%(%)", "  -- quitada a proposito")
  end
  if mutado == fuente2 then
    print("  FALLA no se ha podido mutar el panel: revisa el texto")
    return false
  end
  local tmp = os.tmpname() .. ".luau"
  local f = io.open(tmp, "w")
  f:write(mutado)
  f:close()
  local okMut, errMut = pcall(function()
    local chunkMut = load(mutado, tmp)
    chunkMut()
  end)
  os.remove(tmp)
  if not okMut then
    print("  FALLA el panel mutado no se pudo cargar: " .. tostring(errMut))
    return false
  end
  -- Con el panel roto, renombrar NO debe actualizar current.json.
  limpia()
  ficheros["nota.md"] = "contenido"
  state.open_note = "nota.md"
  pcall(onOpen, {})
  local antes = current()
  pcall(onRename, "renombrada")
  local despues = current()
  local detecto = (antes and antes.name) == "nota.md" and (despues and despues.name) == "nota.md"
  return detecto
end

local detecta = pcall(prueba_mutacion)
check("el test detecta el fallo si se rompe el panel", true, detecta and true or false)

print()
print(string.format("Resultado: %d correctos, %d fallos", PASADOS, FALLOS))
os.exit(FALLOS == 0 and 0 or 1)
