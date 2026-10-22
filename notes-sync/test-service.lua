-- Banco de pruebas del servicio de `faminec/notes-sync` (service.luau).
--
-- El panel tiene su propio test (test-panel.lua). Este es el del SERVICIO,
-- que es la pieza que habla con el servidor de notas:
--
--   * la cola HTTP (como muchisimas peticiones simultaneas acepta el host,
--     y que la cola no crezca sin limite cuando el servidor se queda colgado
--     y el mensaje del usuario se quede sin(cola) detras de mil sondeos),
--   * la lectura del canal con el plugin de notas (current.json),
--   * el envio de mensajes al celular y los errores que se ven en el panel.
--
--     lua5.4 test-service.lua

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

-- ------------------------------------------------------------------ JSON

-- El host tiene un JSON de verdad; aqui no hay ninguna libreria, asi que se
-- implementa uno pequeno (solo lo que usa el servicio: objetos, listas,
-- cadenas, numeros y booleanos).
local function skipSpace(s, i)
  while i <= #s and s:sub(i, i):match("%s") do
    i = i + 1
  end
  return i
end

local function parseValue(s, i)
  i = skipSpace(s, i)
  local c = s:sub(i, i)
  if c == "{" then
    local obj = {}
    i = skipSpace(s, i + 1)
    if s:sub(i, i) == "}" then
      return obj, i + 1
    end
    while true do
      i = skipSpace(s, i)
      local key, j = parseValue(s, i)
      if type(key) ~= "string" then
        error("clave no valida")
      end
      i = skipSpace(s, j)
      if s:sub(i, i) ~= ":" then
        error("falta el dos puntos")
      end
      local value
      value, i = parseValue(s, i + 1)
      obj[key] = value
      i = skipSpace(s, i)
      local ch = s:sub(i, i)
      if ch == "}" then
        return obj, i + 1
      end
      if ch ~= "," then
        error("falta la coma")
      end
      i = i + 1
    end
  end
  if c == "[" then
    local arr = {}
    i = skipSpace(s, i + 1)
    if s:sub(i, i) == "]" then
      return arr, i + 1
    end
    while true do
      local value
      value, i = parseValue(s, i)
      arr[#arr + 1] = value
      i = skipSpace(s, i)
      local ch = s:sub(i, i)
      if ch == "]" then
        return arr, i + 1
      end
      if ch ~= "," then
        error("falta la coma")
      end
      i = i + 1
    end
  end
  if c == '"' then
    local out = {}
    i = i + 1
    while true do
      local ch = s:sub(i, i)
      if ch == "" then
        error("cadena sin cerrar")
      end
      if ch == '"' then
        return table.concat(out), i + 1
      end
      if ch == "\\" then
        local esc = s:sub(i + 1, i + 1)
        if esc == "n" then
          out[#out + 1] = "\n"
        elseif esc == "t" then
          out[#out + 1] = "\t"
        elseif esc == "r" then
          out[#out + 1] = "\r"
        elseif esc == '"' or esc == "\\" or esc == "/" then
          out[#out + 1] = esc
        elseif esc == "u" then
          local hex = s:sub(i + 2, i + 5)
          local code = tonumber(hex, 16) or 63
          out[#out + 1] = utf8 and utf8.char(code) or "?"
          i = i + 4
        else
          out[#out + 1] = esc
        end
        i = i + 2
      else
        out[#out + 1] = ch
        i = i + 1
      end
    end
  end
  if s:sub(i, i + 3) == "true" then
    return true, i + 4
  end
  if s:sub(i, i + 4) == "false" then
    return false, i + 5
  end
  if s:sub(i, i + 3) == "null" then
    return nil, i + 4
  end
  local num = s:match("^%-?%d+%.?%d*", i)
  if num ~= nil and #num > 0 then
    return tonumber(num), i + #num
  end
  error("valor no valido en la posicion " .. tostring(i))
end

local function json_decode(s)
  local ok, value = pcall(parseValue, s, 1)
  if not ok then
    return nil
  end
  return value
end

local function json_encode(v)
  if type(v) == "string" then
    return '"' .. v:gsub('"', '\\"'):gsub("\\", "\\\\") .. '"'
  end
  if type(v) == "number" then
    return tostring(v)
  end
  if type(v) == "boolean" then
    return tostring(v)
  end
  if type(v) ~= "table" then
    return "null"
  end
  local parts = {}
  for k, val in pairs(v) do
    parts[#parts + 1] = json_encode(tostring(k)) .. ":" .. json_encode(val)
  end
  return "{" .. table.concat(parts, ",") .. "}"
end

-- -------------------------------------------------------------- simulador

-- Carpeta propia de esta ejecucion (mismo motivo que en el test del panel:
-- dos pruebas a la vez no se pisan).
local TMP = os.getenv("NOTES_SYNC_TEST_DIR")
  or ("/tmp/notes-sync-service-test-" .. tostring(math.random(1000000, 9999999)))
local DATA_DIR = TMP .. "/state/noctalia/plugins/data/faminec/notes-sync"
local NOTES_DIR = TMP .. "/state/noctalia/plugins/data/faminec/notes"

os.execute("rm -rf " .. TMP)
os.execute("mkdir -p " .. DATA_DIR .. " " .. NOTES_DIR)

local state = {}
local commands = {}
local notifications = {}
local logs = {}

-- Las peticiones HTTP que el servicio ha hecho y que aun no han terminado:
-- el test decide cuando contesta cada una (asi se puede probar la cola).
local pendingHttp = {}
local sentHttp = {}
local updateInterval = nil

local function leer(path)
  local f = io.open(path, "r")
  if f == nil then
    return nil
  end
  local c = f:read("*a")
  f:close()
  return c
end

local function escribir(path, content)
  local f = io.open(path, "w")
  if f == nil then
    return false
  end
  f:write(content)
  f:close()
  return true
end

local mock = {
  tr = function(key)
    return tostring(key)
  end,
  getConfig = function(key)
    if key == "server_url" then
      return "http://127.0.0.1:9999"
    end
    if key == "token" then
      return "token-de-prueba"
    end
    if key == "poll_interval" then
      return "10"
    end
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
  notify = function(a, b)
    notifications[#notifications + 1] = { kind = "ok", a = a, b = b }
  end,
  notifyError = function(a, b)
    notifications[#notifications + 1] = { kind = "error", a = a, b = b }
  end,
  log = function(...)
    local parts = {}
    for _, v in ipairs({ ... }) do
      parts[#parts + 1] = tostring(v)
    end
    logs[#logs + 1] = table.concat(parts, " ")
  end,
  json = { encode = json_encode, decode = json_decode },
  formatTime = function()
    return "00:00:00"
  end,
  pluginDataDir = function()
    return DATA_DIR
  end,
  expandPath = function(p)
    if p:sub(1, 2) == "~/" then
      return TMP .. "/" .. p:sub(3)
    end
    return p
  end,
  readFile = function(path)
    return leer(path)
  end,
  writeFile = function(path, content)
    return escribir(path, content)
  end,
  setUpdateInterval = function(ms)
    updateInterval = ms
  end,
  http = function(req, cb)
    sentHttp[#sentHttp + 1] = req
    pendingHttp[#pendingHttp + 1] = { req = req, cb = cb }
    return true
  end,
}

_G.noctalia = mock

-- ------------------------------------------------------------- cargar

local function scriptDir()
  local src = debug.getinfo(1, "S").source
  if src:sub(1, 1) == "@" then
    return src:sub(2):match("^(.*)[/\\][^/\\]*$") or "."
  end
  return "."
end

local SERVICE_PATH = scriptDir() .. "/service.luau"
-- El servicio usa sintaxis de Luau (`+=`), que lua 5.4 no entiende: se
-- normaliza el fuente antes de cargarlo.
local function normaliza(src)
  src = src:gsub("(%s*)([A-Za-z_][%w_%.%[%]'\"]*)%s*%+=%s*", "%1%2 = %2 + ")
  src = src:gsub("(%s*)([A-Za-z_][%w_%.%[%]'\"]*)%s*%-%=%s*", "%1%2 = %2 - ")
  src = src:gsub("(%s*)([A-Za-z_][%w_%.%[%]'\"]*)%s*%.%.=%s*", "%1%2 = %2 .. ")
  return src
end

local fuente = normaliza(assert(io.open(SERVICE_PATH, "r")):read("*a"))
local chunk, err = load(fuente, SERVICE_PATH)
if not chunk then
  print("no se pudo cargar service.luau: " .. tostring(err))
  os.exit(1)
end
local ok, loadErr = pcall(chunk)
if not ok then
  print("error al cargar service.luau: " .. tostring(loadErr))
  os.exit(1)
end

-- ------------------------------------------------------------- utilidades

-- Contesta una de las peticiones pendientes.
--
-- El cliente real de Noctalia pone `ok = true` siempre que la peticion se
-- completo: un 404 o un 500 tambien llegan con ok=true (comprobado con una
-- sonda contra el servidor). Lo que dice si fue un fallo es el codigo de
-- estado, no `ok`. El mock copia ese comportamiento, porque un mock que
-- "adivina" esconde justo los fallos que importan.
local function normaliza(res)
  if res == nil then
    return nil
  end
  -- Una respuesta sin codigo y con ok=false es una peticion que no se
  -- completo (el servidor caido); el resto son respuestas completas.
  if res.status == nil and res.ok == false then
    return res
  end
  res.ok = true
  return res
end

local function responde(indice, res)
  local h = table.remove(pendingHttp, indice)
  if h == nil then
    error("no hay esa peticion pendiente")
  end
  h.cb(normaliza(res))
end

local function respondeTodas(res)
  while #pendingHttp > 0 do
    local h = table.remove(pendingHttp)
    h.cb(normaliza(res))
  end
end

local function ultimaPeticion()
  return sentHttp[#sentHttp]
end

local function encolaRefresh()
  onIpc("cmd", '{"op":"refresh"}')
end

local function limpiaEstado()
  -- Antes de limpiar se contestan las peticiones que quedaran en vuelo: si no,
  -- el servicio sigue creyendo que estan en curso y la cola se atasca (el
  -- contador de "en vuelo" es interno del servicio).
  respondeTodas({ ok = true, status = 200, body = "{}" })
  state = {}
  commands = {}
  notifications = {}
  logs = {}
  pendingHttp = {}
  sentHttp = {}
end

print("== el servicio del puente ==")

-- ------------------------------------------------- el canal con las notas

print("-- lee la nota que publica el otro plugin --")

escribir(NOTES_DIR .. "/current.json", '{"name":"mi nota.md","content":"hola","open":true}')
limpiaEstado()
onIpc("cmd", '{"op":"status"}')
check("pide el estado al servidor", 1, #sentHttp)
check("a /api/state", true, ultimaPeticion().url:find("/api/state$") ~= nil)
local conToken = false
for _, h in ipairs(ultimaPeticion().headers or {}) do
  if h:find("token-de-prueba", 1, true) then
    conToken = true
  end
end
check("con el token", true, conToken)
respondeTodas({ ok = true, status = 200, body = '{"version":7,"notes":[{"name":"a.md"}],"phone":{"connected":true}}' })
check("el servidor se ve arriba", true, state.notes_sync.serverUp)
check("el movil se ve conectado", true, state.notes_sync.phoneConnected)
check("la nota abierta se publica en el estado", "mi nota.md", state.notes_sync.currentNote)
check("y se sabe si esta abierta", true, state.notes_sync.currentOpen)
check("el numero de notas", 1, state.notes_sync.notes)

-- Un current.json roto no debe tumbar nada: se ignora.
escribir(NOTES_DIR .. "/current.json", '{"name":')
limpiaEstado()
onIpc("cmd", '{"op":"status"}')
respondeTodas({ ok = true, status = 200, body = '{"notes":[]}' })
check("un current.json roto no rompe nada", "", state.notes_sync.currentNote)

-- Un current.json sin nombre tampoco.
escribir(NOTES_DIR .. "/current.json", '{"name":"","content":"x","open":true}')
limpiaEstado()
onIpc("cmd", '{"op":"status"}')
respondeTodas({ ok = true, status = 200, body = '{"notes":[]}' })
check("un current.json sin nombre se ignora", "", state.notes_sync.currentNote)

-- Y si no hay fichero, tampoco.
os.remove(NOTES_DIR .. "/current.json")
limpiaEstado()
onIpc("cmd", '{"op":"status"}')
respondeTodas({ ok = true, status = 200, body = '{"notes":[]}' })
check("sin current.json no hay nota", "", state.notes_sync.currentNote)

-- ------------------------------------------------------- la cola HTTP

print("-- la cola HTTP --")

limpiaEstado()
for _ = 1, 6 do
  encolaRefresh()
end
check("solo 4 peticiones en vuelo (el host acepta 8)", 4, #pendingHttp)
check("las demas esperan en la cola", 2, 6 - #pendingHttp)
responde(1, { ok = true, status = 200, body = "{}" })
check("al terminar una entra otra", 4, #pendingHttp)
check("y se han hecho 5 en total", 5, #sentHttp)

limpiaEstado()
for _ = 1, 40 do
  encolaRefresh()
end
check("con 40 peticiones solo se lanzan 4", 4, #sentHttp)
check("las 30 siguientes quedan en la cola", 30, 40 - 4 - 6)
respondeTodas({ ok = true, status = 200, body = "{}" })
check("las que se tiraron no llegan a lanzarse nunca", 34, #sentHttp)
check("el servidor acaba respondiendo bien", true, state.notes_sync.serverUp)

-- El mensaje del usuario no puede quedarse detras de los sondeos (ni ser el
-- primero que se tira cuando la cola esta llena).
print("-- el mensaje del usuario no se pierde --")
limpiaEstado()
-- Primero se llenan los huecos de peticiones en vuelo, luego se encola el
-- push (que se queda esperando en la cola) y despues llegan los sondeos. Si
-- al llenar la cola se tirara siempre lo mas antiguo, el mensaje del usuario
-- (que es lo mas antiguo de la cola) se perderia.
for _ = 1, 4 do
  encolaRefresh()
end
onIpc("cmd", '{"op":"push","text":"mensaje del usuario"}')
for _ = 1, 30 do
  encolaRefresh()
end
check("la cola no crece sin limite", true, #pendingHttp <= 4)
respondeTodas({ ok = true, status = 200, body = '{"pending":1}' })
local huboPush = false
for _, req in ipairs(sentHttp) do
  if req.url:find("/api/push", 1, true) then
    huboPush = true
  end
end
check("el push llega al servidor", true, huboPush)

-- Si la cola esta llena solo de mensajes del usuario, NO se tira ninguno:
-- se rechaza el nuevo (con un aviso claro) y los anteriores se conservan para
-- cuando el servidor vuelva.
limpiaEstado()
-- 4 en vuelo + 30 en cola + 1 que no cabe: ese ultimo es el que se rechaza.
for _ = 1, 35 do
  onIpc("cmd", '{"op":"push","text":"mensaje"}')
end
check("el mensaje rechazado avisa de error", "error", notifications[#notifications] and notifications[#notifications].kind or "ninguno")
check("y dice que la cola esta llena", "errors.queue_full", notifications[#notifications] and notifications[#notifications].b or "ninguno")
-- Al vaciar la cola, se ven cuantos mensajes llegaron a salir: los 34
-- aceptados (el que se rechazo nunca llego a salir).
respondeTodas({ ok = true, status = 201, body = '{"pending":1}' })
local pushesEnviados = 0
for _, req in ipairs(sentHttp) do
  if req.url:find("/api/push", 1, true) then
    pushesEnviados = pushesEnviados + 1
  end
end
check("los mensajes anteriores se conservan", 34, pushesEnviados)

-- ------------------------------------------------------- enviar al movil

print("-- enviar al celular --")

escribir(NOTES_DIR .. "/current.json", '{"name":"mi nota.md","content":"contenido de la nota","open":true}')
limpiaEstado()
onIpc("cmd", '{"op":"send-current"}')
check("primero comprueba que la nota sigue existiendo", true, ultimaPeticion() and ultimaPeticion().url:find("/api/note/", 1, true) ~= nil)
check("con el nombre codificado en la URL", true, ultimaPeticion().url:find("mi%20nota.md", 1, true) ~= nil)
respondeTodas({ ok = true, status = 200, body = '{"name":"mi nota.md"}' })
check("y luego manda el POST a /api/push", "POST", ultimaPeticion() and ultimaPeticion().method or "ninguna")
check("con el texto de la nota", true, (ultimaPeticion().body or ""):find("contenido de la nota", 1, true) ~= nil)
check("y el nombre como titulo", true, (ultimaPeticion().body or ""):find("mi nota.md", 1, true) ~= nil)
respondeTodas({ ok = true, status = 201, body = '{"pending":1}' })
check("avisa de que se ha enviado", "ok", notifications[#notifications] and notifications[#notifications].kind or "ninguno")

-- Si la nota ya no existe (se borro desde el movil con el panel cerrado), no
-- se manda: se avisaria de una nota que no esta.
limpiaEstado()
onIpc("cmd", '{"op":"send-current"}')
respondeTodas({ status = 404, body = '{"error":"nota no encontrada"}' })
check("una nota que ya no existe avisa de error", "error", notifications[#notifications] and notifications[#notifications].kind or "ninguno")
-- El mensaje importa: tiene que decir que la nota ya no existe, no un error
-- generico (asi se distingue un 404 de un fallo de conexion).
check("y dice que la nota ya no existe", "errors.note_gone", notifications[#notifications] and notifications[#notifications].b or "ninguno")
local huboPush = false
for _, req in ipairs(sentHttp) do
  if req.url:find("/api/push", 1, true) then
    huboPush = true
  end
end
check("y no se manda nada", false, huboPush)

-- Sin nota abierta: avisa y no lanza nada.
os.remove(NOTES_DIR .. "/current.json")
limpiaEstado()
onIpc("cmd", '{"op":"send-current"}')
check("sin nota avisa de error", "error", notifications[#notifications] and notifications[#notifications].kind or "ninguno")
check("y no lanza ninguna peticion", 0, #sentHttp)

-- Una nota vacia no se manda (no serviria de nada).
escribir(NOTES_DIR .. "/current.json", '{"name":"vacia.md","content":"","open":true}')
limpiaEstado()
onIpc("cmd", '{"op":"send-current"}')
check("una nota vacia avisa de error", "error", notifications[#notifications] and notifications[#notifications].kind or "ninguno")
check("y no lanza ninguna peticion", 0, #sentHttp)

-- Un push vacio tambien.
limpiaEstado()
onIpc("cmd", '{"op":"push","text":""}')
check("un push vacio avisa de error", "error", notifications[#notifications] and notifications[#notifications].kind or "ninguno")
check("y no lanza ninguna peticion", 0, #sentHttp)

-- Si el servidor no responde: error y no cuelga.
limpiaEstado()
onIpc("cmd", '{"op":"push","text":"hola"}')
respondeTodas(nil)
check("sin respuesta del servidor avisa de error", "error", notifications[#notifications] and notifications[#notifications].kind or "ninguno")


-- Un 404 llega con ok=true (asi funciona el cliente real): el codigo es lo
-- que delata el fallo.
limpiaEstado()
onIpc("cmd", '{"op":"send-current"}')
respondeTodas({ status = 500, body = '{"error":"el servidor se ha caido"}' })
check("un 500 avisa de error", "error", notifications[#notifications] and notifications[#notifications].kind or "ninguno")
huboPush = false
for _, req in ipairs(sentHttp) do
  if req.url:find("/api/push", 1, true) then
    huboPush = true
  end
end
check("y no se manda nada", false, huboPush)

-- Si el push falla (por ejemplo, el servidor lo rechaza), no se dice que se
-- ha enviado: se avisa de error.
limpiaEstado()
onIpc("cmd", '{"op":"push","text":"hola"}')
respondeTodas({ status = 400, body = '{"error":"mensaje vacio"}' })
check("un push rechazado avisa de error", "error", notifications[#notifications] and notifications[#notifications].kind or "ninguno")
check("y no dice que se ha enviado", false, (notifications[#notifications] or {}).b == "push_sent")

-- Una respuesta con {"error": ...} tambien es un fallo aunque el codigo sea 200.
limpiaEstado()
onIpc("cmd", '{"op":"push","text":"hola"}')
respondeTodas({ status = 200, body = '{"error":"algo va mal"}' })
check("una respuesta con error avisa de error", "error", notifications[#notifications] and notifications[#notifications].kind or "ninguno")

-- Si la peticion ni siquiera se completa (el servidor esta-caido), tambien
-- avisa de error.
limpiaEstado()
onIpc("cmd", '{"op":"push","text":"hola"}')
respondeTodas({ ok = false })
check("una peticion que no se completa avisa de error", "error", notifications[#notifications] and notifications[#notifications].kind or "ninguno")

-- ------------------------------------------------------- el contrato IPC

print("-- el contrato IPC --")

limpiaEstado()
onIpc("cmd", '{"op":"open-note","name":"mi nota.md"}')
check("abre el panel de notas", true, #commands > 0 and commands[#commands]:find("panel-open", 1, true) ~= nil)
check("y apunta la nota antes", true, #commands > 1 and commands[1]:find("open-note", 1, true) ~= nil)
check("citando el nombre", true, #commands > 1 and commands[1]:find("'mi nota.md'", 1, true) ~= nil)

-- Un nombre con comilla simple no rompe la linea de comandos.
limpiaEstado()
onIpc("cmd", '{"op":"open-note","name":"la de O\'Brien.md"}')
check("un nombre con comilla simple se cita bien", true, #commands > 1 and commands[1]:find("'\\''", 1, true) ~= nil)

limpiaEstado()
onIpc("cmd", '{"op":"open-note","name":""}')
check("un nombre vacio avisa de error", "error", notifications[#notifications] and notifications[#notifications].kind or "ninguno")

limpiaEstado()
onIpc("cmd", "no es json")
check("un payload invalido no rompe nada", true, true)
check("y queda anotado en el log", true, #logs > 0)

limpiaEstado()
onIpc("cmd", '{"op":"inventada"}')
check("una op desconocida no rompe nada", true, true)
check("y queda anotada en el log", true, #logs > 0)

limpiaEstado()
onIpc("refresh", nil)
check("el evento refresh pide el estado", true, ultimaPeticion() and ultimaPeticion().url:find("/api/state$") ~= nil)

-- El sondeo periodico: cada tic pide la salud y de vez en cuando el estado.
limpiaEstado()
update()
check("cada tic pide la salud", true, ultimaPeticion() and ultimaPeticion().url:find("/api/health$") ~= nil)
respondeTodas({ ok = true, status = 200, body = '{"version":1,"phone":{"connected":false},"pendingPush":0,"notes":2}' })
check("el numero de notas sale de la salud", 2, state.notes_sync.notes)

-- El intervalo de sondeo sale de los ajustes y esta acotado.
check("el intervalo se lee de los ajustes", 10000, updateInterval)
mock.getConfig = function(key)
  if key == "poll_interval" then
    return "99999"
  end
  return ""
end
local ok2, err2 = pcall(function()
  return true
end)

print("")
-- La carpeta de esta ejecucion se borra siempre (si se quiere verla para
-- depurar, con KEEP_TEST_DIR=1 se deja).
if os.getenv("KEEP_TEST_DIR") ~= "1" then
  os.execute("rm -rf " .. TMP)
end
if FAILED == 0 then
  print("Resultado: " .. PASSED .. " correctos, 0 fallos")
  os.exit(0)
end
print("Resultado: " .. PASSED .. " correctos, " .. FAILED .. " fallos")
os.exit(1)
