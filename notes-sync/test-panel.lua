-- Banco de pruebas del plugin `faminec/notes-sync` (panel.luau).
--
-- Se carga el panel con un API de Noctalia simulado y se comprueban los
-- manejadores que antes rompian:
--
--   * `onSendCurrent` llamaba a `render()` antes de que existiera el `local`
--     (en Luau un `local` solo existe desde su declaracion: la llamada
--     caia en un global nil -> "attempt to call a nil value").
--   * `onOpenNotes` / `onRefresh` montan comandos de shell: los nombres de
--     nota vienen del celular y tienen que ir citados.
--
-- Se ejecuta con `lua5.4 test-panel.lua` (la semántica de `local` es la de
-- Luau: un `local` solo existe desde su declaración).

local FAILED = 0
local PASSED = 0

local function check(name, expected, got)
  if expected == got then
    PASSED = PASSED + 1
    print(string.format("  ok   %-58s %s", name, tostring(got)))
  else
    FAILED = FAILED + 1
    print(string.format("  FALLA %-58s esperado=%s obtenido=%s", name, tostring(expected), tostring(got)))
  end
end

-- ----------------------------------------------------------------- simulador

local state = {}
local commands = {}
local notifications = {}
local settingsOpened = 0
local rendered = 0

local function json_encode(v)
  if type(v) ~= "table" then
    return tostring(v)
  end
  local parts = {}
  for k, val in pairs(v) do
    parts[#parts + 1] = string.format('"%s":"%s"', tostring(k), tostring(val))
  end
  return "{" .. table.concat(parts, ",") .. "}"
end

local function json_decode(s)
  local out = {}
  for k, v in s:gmatch('"([^"]+)":"([^"]*)"') do
    out[k] = v
  end
  return out
end

local mock = {
  tr = function(key, params)
    if params and params.count then
      return tostring(key) .. ":" .. tostring(params.count)
    end
    return tostring(key)
  end,
  getConfig = function(key)
    if key == "notes_plugin" then
      return "faminec/notes"
    end
    return ""
  end,
  getSetting = function()
    return 1
  end,
  state = {
    get = function(key)
      return state[key]
    end,
    set = function(key, value)
      state[key] = value
    end,
    watch = function() end,
  },
  runAsync = function(cmd)
    commands[#commands + 1] = cmd
  end,
  openSettings = function()
    settingsOpened = (settingsOpened or 0) + 1
  end,
  notify = function(a, b)
    notifications[#notifications + 1] = { kind = "ok", a = a, b = b }
  end,
  notifyError = function(a, b)
    notifications[#notifications + 1] = { kind = "error", a = a, b = b }
  end,
  json = { encode = json_encode, decode = json_decode },
  formatTime = function(fmt)
    return "00:00:00"
  end,
  readFile = function()
    return nil
  end,
  writeFile = function()
    return true
  end,
  pluginDataDir = function()
    return "/tmp/notes-sync-test"
  end,
  log = function() end,
}

_G.noctalia = mock
_G.panel = {
  render = function()
    rendered = rendered + 1
  end,
  close = function() end,
}
_G.ui = setmetatable({}, {
  __index = function()
    return function()
      return {}
    end
  end,
})

-- --------------------------------------------------------------- cargar el panel

-- El panel se carga desde el directorio del propio script, para que el test
-- se pueda ejecutar desde cualquier sitio.
local function scriptDir()
  local src = debug.getinfo(1, "S").source
  if src:sub(1, 1) == "@" then
    return src:sub(2):match("^(.*)[/\\][^/\\]*$") or "."
  end
  return "."
end

local DIR = scriptDir()
local PANEL_PATH = DIR .. "/panel.luau"

local chunk, err = loadfile(PANEL_PATH)
if not chunk then
  print("no se pudo cargar panel.luau: " .. tostring(err))
  os.exit(1)
end
local ok, loadErr = pcall(chunk)
if not ok then
  print("error al cargar panel.luau: " .. tostring(loadErr))
  os.exit(1)
end

-- El panel se pinta al cargarse.
check("el panel se pinta al cargar", 1, rendered > 0 and 1 or 0)

-- ------------------------------------------------- onSendCurrent (el que fallaba)

state.notes_sync = { currentNote = "mi nota.md" }
commands = {}
rendered = 0
local okSend, errSend = pcall(function()
  onSendCurrent()
end)
check("onSendCurrent no revienta", true, okSend)
if not okSend then
  print("     error: " .. tostring(errSend))
end
check("onSendCurrent lanza el comando al servicio", true, (#commands > 0))
check(
  "el comando va al servicio correcto",
  true,
  (#commands > 0 and string.find(commands[1], "faminec/notes-sync:service", 1, true) ~= nil)
)
check("el payload JSON va citado", true, (#commands > 0 and string.find(commands[1], "'{\"op\":\"send-current\"}'", 1, true) ~= nil))
check("onSendCurrent repinta el panel", true, rendered > 0)

-- Sin nota abierta: avisa y no lanza nada.
state.notes_sync = { currentNote = "" }
commands = {}
notifications = {}
local okNoNote = pcall(function()
  onSendCurrent()
end)
check("onSendCurrent sin nota no revienta", true, okNoNote)
check("sin nota avisa de error", "error", notifications[1] and notifications[1].kind or "ninguno")
check("sin nota no lanza comando", 0, #commands)

-- ----------------------------------------------------- onOpenNotes y onRefresh

commands = {}
pcall(function()
  onOpenNotes()
end)
check("onOpenNotes lanza panel-open", true, (#commands > 0 and string.find(commands[1], "panel-open", 1, true) ~= nil))
check("onOpenNames cita el id del panel", true, (#commands > 0 and string.find(commands[1], "'faminec/notes:panel'", 1, true) ~= nil))

commands = {}
pcall(function()
  onRefresh()
end)
check("onRefresh lanza refresh al servicio", true, (#commands > 0 and string.find(commands[1], "all refresh", 1, true) ~= nil))

-- ------------------------------------------- onOpenSettings y onOpen

settingsOpened = 0
pcall(function()
  onOpenSettings()
end)
check("onOpenSettings abre los ajustes", 1, settingsOpened)

-- Al abrir el panel se pide estado fresco: sin eso, el boton de enviar puede
-- quedarse deshabilitado hasta el siguiente tic del servicio.
commands = {}
pcall(function()
  onOpen("panel")
end)
check("onOpen pide estado fresco al servicio", true, (#commands > 0 and string.find(commands[1], "all refresh", 1, true) ~= nil))

-- --------------------------------------------------- cita de nombres de nota
-- Un nombre con comilla simple no debe romper la linea de comandos.
local quoted = nil
do
  local src = io.open(PANEL_PATH, "r")
  local text = src:read("*a")
  src:close()
  local i = text:find("local function shellQuote")
  if i then
    quoted = text:sub(i, i + 400)
  end
end
check("el panel cita los textos para el shell", true, quoted ~= nil and quoted:find("'\\\\''") ~= nil)

-- ------------------------------------------------- regresion: handlers globales
--
-- Los manejadores que el panel referencia por nombre (`onClick = "onXxx"`)
-- tienen que ser GLOBALES: Noctalia los busca en el ambito global de la
-- entrada. Si son `local function`, Noctalia no los encuentra y el boton
-- se queda muerto sin avisar.
do
  local src = io.open(PANEL_PATH, "r")
  local text = src:read("*a")
  src:close()
  local referenced = {}
  for name in text:gmatch('onClick%s*=%s*"([%w_]+)"') do
    referenced[#referenced + 1] = name
  end
  check("el panel referencia handlers por nombre", true, #referenced > 0)
  for _, name in ipairs(referenced) do
    local global_def = text:find("\nfunction " .. name .. "%s*%(") ~= nil
      or text:find("^function " .. name .. "%s*%(") ~= nil
    local local_def = text:find("local function " .. name .. "%s*%(") ~= nil
    check(
      "el handler '" .. name .. "' es global (no local)",
      true,
      global_def and not local_def
    )
  end
end

print()
print(string.format("Resultado: %d correctos, %d fallos", PASSED, FAILED))
os.exit(FAILED == 0 and 0 or 1)
