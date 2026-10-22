--!nonstrict
-- Servicio de sincronizacion entre el panel de notas del computador y el
-- celular.
--
-- El plugin `faminec/notes` se ocupa de las notas; este se ocupa del puente:
--
--   * Vigila el servidor de `notes-mobile` y publica su estado en
--     `noctalia.state` ("notes_sync") para que el widget y el panel lo pinten.
--   * Encola mensajes hacia el celular (push) a traves de la API del servidor.
--   * Expone un contrato IPC estable, con payload JSON, para que otras
--     herramientas (o el propio celular) controlen el panel de notas.
--
-- Contrato IPC:
--
--   noctalia msg plugin faminec/notes-sync:service all refresh
--   noctalia msg plugin faminec/notes-sync:service all cmd '{"op":"status"}'
--   noctalia msg plugin faminec/notes-sync:service all cmd '{"op":"open-notes"}'
--   noctalia msg plugin faminec/notes-sync:service all cmd '{"op":"open-note","name":"mi nota.md"}'
--   noctalia msg plugin faminec/notes-sync:service all cmd '{"op":"send-current"}'
--   noctalia msg plugin faminec/notes-sync:service all cmd '{"op":"push","text":"hola"}'
--
-- El estado que publica el servicio:
--
--   noctalia.state "notes_sync" = {
--     serverUp = bool, phoneConnected = bool, pending = number,
--     notes = number, lastSeen = number, url = string,
--     checkedAt = "HH:MM:SS", error = string,
--   }

local MAX_IN_FLIGHT = 4 -- el host acepta 8; se deja margen para otras acciones
-- Si el servidor se queda colgado (acepta la conexion pero no contesta), las
-- peticiones se quedan en vuelo y la cola crece sin limite. Los sondeos viejos
-- no sirven de nada (el estado se vuelve a pedir) y, lo peor, empujan las
-- acciones del usuario (que si importan) hasta el final de la cola. Asi que la
-- cola tiene un tope.
local MAX_QUEUE = 30
-- Que se puede tirar y que no. Cada peticion declara su prioridad y hay una
-- sola regla: cuando la cola esta llena se tira lo mas desechable (primero
-- un sondeo y despues una comprobacion). El mensaje del usuario NO se tira
-- nunca: si la cola esta llena solo de mensajes, se rechaza el nuevo (el
-- usuario se entera) y los anteriores se conservan para cuando el servidor
-- vuelva.
local PRIO_SONDEO = 1 -- el estado se vuelve a pedir: da igual perderlo
local PRIO_COMPROBACION = 2 -- una comprobacion: se vuelve a hacer
local PRIO_MENSAJE = 3 -- el mensaje del usuario: no se tira nunca

local inFlight = 0
local queue = {}
local fullStateTick = 0

local function tr(key, params)
  if params ~= nil then
    return noctalia.tr(key, params)
  end
  return noctalia.tr(key)
end

-- ------------------------------------------------------------------ ajustes

local function notesPluginId()
  local id = noctalia.getConfig("notes_plugin")
  if type(id) == "string" and id ~= "" then
    return id
  end
  return "faminec/notes"
end

local function notesPanelId()
  return notesPluginId() .. ":panel"
end

local function serverUrl()
  local url = noctalia.getConfig("server_url")
  if type(url) ~= "string" or url == "" then
    url = "http://127.0.0.1:8787"
  end
  -- Sin barra final: las rutas se concatenan tal cual.
  return (url:gsub("/+$", ""))
end

-- El token se puede dejar vacio en los ajustes: si es asi se lee del
-- config.json del servidor (que es donde esta por defecto).
local function serverToken()
  local token = noctalia.getConfig("token")
  if type(token) == "string" and token ~= "" then
    return token
  end
  local path = noctalia.expandPath("~/notes-mobile/config.json")
  local raw = noctalia.readFile(path)
  if raw == nil then
    return ""
  end
  local ok, decoded = pcall(noctalia.json.decode, raw)
  if ok and type(decoded) == "table" and type(decoded.token) == "string" then
    return decoded.token
  end
  return ""
end

local function pollIntervalMs()
  local secs = tonumber(noctalia.getConfig("poll_interval"))
  if secs == nil or secs <= 0 then
    return 10000
  end
  return math.min(secs, 600) * 1000
end

-- --------------------------------------------------------------------- HTTP
--
-- El host acepta como maximo ocho peticiones simultaneas por script: si se
-- supera, la llamada se rechaza y no se avisa. Por eso todo pasa por una cola.

local function pump()
  while inFlight < MAX_IN_FLIGHT and #queue > 0 do
    local job = table.remove(queue, 1)
    inFlight += 1
    local started = noctalia.http(job.req, function(res)
      inFlight -= 1
      job.cb(res)
      pump()
    end)
    if not started then
      inFlight -= 1
      job.cb(nil)
    end
  end
end

local function request(path, method, body, cb, priority)
  local headers = {}
  local token = serverToken()
  if token ~= "" then
    table.insert(headers, "Authorization: Bearer " .. token)
  end
  if body ~= nil then
    table.insert(headers, "Content-Type: application/json")
  end
  -- Cola llena: se tira lo mas desechable y se avisa a quien lo pidio, para
  -- que no se quede esperando a un servidor que no contesta.
  if #queue >= MAX_QUEUE then
    local dropped = nil
    for _, p in ipairs({ PRIO_SONDEO, PRIO_COMPROBACION }) do
      for i, job in ipairs(queue) do
        if job.priority == p then
          dropped = table.remove(queue, i)
          break
        end
      end
      if dropped ~= nil then
        break
      end
    end
    if dropped == nil then
      -- En la cola solo hay mensajes del usuario: no se tira ninguno. Se
      -- rechaza el nuevo (y el usuario se entera) y los anteriores se
      -- conservan para cuando el servidor vuelva.
      cb(nil, tr("errors.queue_full"))
      return
    end
    dropped.cb(nil)
  end
  table.insert(queue, {
    req = {
      url = serverUrl() .. path,
      method = method or "GET",
      headers = headers,
      body = body,
    },
    cb = cb,
    priority = priority or PRIO_MENSAJE,
  })
  pump()
end

local function jsonRequest(path, method, payload, cb, priority)
  local encoded = nil
  if payload ~= nil then
    local ok, res = pcall(noctalia.json.encode, payload)
    if not ok or res == nil then
      cb(nil, "no se pudo codificar la peticion")
      return
    end
    encoded = res
  end
  request(path, method, encoded, function(res, forceError)
    if forceError ~= nil then
      cb(nil, forceError)
      return
    end
    if res == nil then
      cb(nil, "sin respuesta del servidor")
      return
    end
    -- `res.ok` significa que la peticion se completo, NO que saliera bien:
    -- un 404 o un 500 tambien llegan con `ok = true`. Lo que dice si fue un
    -- fallo es el codigo de estado (comprobado con una sonda contra el
    -- servidor: un 404 devuelve ok=true, status=404).
    if not res.ok then
      cb(nil, "sin respuesta del servidor")
      return
    end
    local status = tonumber(res.status) or 0
    if status >= 400 then
      cb(nil, "HTTP " .. tostring(status))
      return
    end
    if res.body == nil or res.body == "" then
      cb({}, nil)
      return
    end
    local ok, decoded = pcall(noctalia.json.decode, res.body)
    if not ok or type(decoded) ~= "table" then
      cb(nil, "respuesta ilegible")
      return
    end
    -- El servidor responde los fallos con {"error": "..."}: si aparece esa
    -- clave, es un fallo aunque el codigo no lo delatara.
    if decoded.error ~= nil then
      cb(nil, tostring(decoded.error))
      return
    end
    cb(decoded, nil)
  end, priority)
end

-- ------------------------------------------------- nota abierta (otro plugin)
--
-- `noctalia.state` esta aislado por plugin: las claves que publica
-- `faminec/notes` no se ven desde aqui. El canal entre plugins es el
-- fichero `current.json` que el plugin de notas escribe en su directorio de
-- datos (~/.local/state/noctalia/plugins/data/<autor>/<plugin>/).

local function dataRoot()
  local dir = noctalia.pluginDataDir() or ""
  -- La ruta es absoluta: hay que conservar la barra inicial.
  local absolute = dir:sub(1, 1) == "/"
  local parts = {}
  for part in dir:gmatch("[^/]+") do
    table.insert(parts, part)
  end
  while #parts > 0 and parts[#parts] ~= "data" do
    table.remove(parts)
  end
  if #parts == 0 then
    return ""
  end
  return (absolute and "/" or "") .. table.concat(parts, "/")
end

local function notesCurrentFile()
  local root = dataRoot()
  if root == "" then
    return nil
  end
  return root .. "/" .. notesPluginId() .. "/current.json"
end

-- Devuelve {name, content, open} de la ultima nota con la que se trabajo en
-- el panel de notas, o nil. `open` dice si esa nota esta abierta ahora mismo.
local function readCurrentNote()
  local path = notesCurrentFile()
  if path == nil then
    return nil
  end
  local raw = noctalia.readFile(path)
  if raw == nil or raw == "" then
    return nil
  end
  local ok, decoded = pcall(noctalia.json.decode, raw)
  if not ok or type(decoded) ~= "table" then
    return nil
  end
  if type(decoded.name) ~= "string" or decoded.name == "" then
    return nil
  end
  return {
    name = decoded.name,
    content = decoded.content or "",
    open = decoded.open == true,
  }
end

-- ------------------------------------------------------------------ estado

local snapshot = {
  serverUp = false,
  phoneConnected = false,
  pending = 0,
  notes = 0,
  lastSeen = 0,
  url = "",
  checkedAt = "",
  error = "",
  currentNote = "",
  currentOpen = false,
}

local function publish()
  snapshot.url = serverUrl()
  snapshot.checkedAt = noctalia.formatTime("%H:%M:%S")
  local current = readCurrentNote()
  snapshot.currentNote = current and current.name or ""
  snapshot.currentOpen = current and current.open or false
  noctalia.state.set("notes_sync", snapshot)
end

-- El servidor escribe ~/notes-mobile/state.json: si esta, se lee como
-- respaldo cuando el servidor no responde.
local function readStateFile()
  local path = noctalia.expandPath("~/notes-mobile/state.json")
  local raw = noctalia.readFile(path)
  if raw == nil then
    return nil
  end
  local ok, decoded = pcall(noctalia.json.decode, raw)
  if not ok or type(decoded) ~= "table" then
    return nil
  end
  return decoded
end

local function applyHealth(data)
  snapshot.serverUp = true
  snapshot.error = ""
  snapshot.version = data.version or 0
  local phone = data.phone or {}
  snapshot.phoneConnected = phone.connected == true
  snapshot.lastSeen = tonumber(phone.lastSeen) or 0
  snapshot.pending = tonumber(data.pendingPush) or 0
  snapshot.notes = tonumber(data.notes) or snapshot.notes
end

local function applyStateFile(data)
  if type(data) ~= "table" then
    return
  end
  snapshot.version = tonumber(data.version) or snapshot.version
  local phone = data.phone or {}
  snapshot.phoneConnected = phone.connected == true
  snapshot.lastSeen = tonumber(phone.lastSeen) or snapshot.lastSeen
  local push = data.push
  if type(push) == "table" then
    snapshot.pending = #push
  end
end

local function refresh()
  jsonRequest("/api/health", "GET", nil, function(data, err)
    if data ~= nil then
      applyHealth(data)
    else
      snapshot.serverUp = false
      snapshot.error = err or "sin respuesta"
      local fromFile = readStateFile()
      if fromFile ~= nil then
        applyStateFile(fromFile)
      end
    end
    publish()
  end, PRIO_SONDEO)
end

-- Tambien se mira el estado del servidor para saber cuantas notas hay.
local function refreshState()
  jsonRequest("/api/state", "GET", nil, function(data, err)
    if data ~= nil then
      snapshot.serverUp = true
      snapshot.error = ""
      snapshot.notes = #(data.notes or {})
      if data.phone ~= nil then
        snapshot.phoneConnected = data.phone.connected == true
        snapshot.lastSeen = tonumber(data.phone.lastSeen) or snapshot.lastSeen
      end
      if tonumber(data.version) ~= nil then
        snapshot.version = data.version
      end
    else
      snapshot.serverUp = false
      snapshot.error = err or "sin respuesta"
      local fromFile = readStateFile()
      if fromFile ~= nil then
        applyStateFile(fromFile)
      end
    end
    publish()
  end, PRIO_SONDEO)
end

-- ---------------------------------------------------------------- acciones

local function notifyOk(text)
  noctalia.notify(tr("title"), text)
end

local function notifyErr(text)
  noctalia.notifyError(tr("title"), text or "")
end

-- --------------------------------------------------- comandos de Noctalia
--
-- Los nombres de nota vienen del celular: hay que citarlos bien para el
-- shell. Entre comillas simples, y las comillas simples de dentro se
-- cierran y se reabren ('\'').
local function shellQuote(text)
  local s = tostring(text)
  s = s:gsub("'", "'\\''")
  return "'" .. s .. "'"
end

-- Abre el panel de notas del plugin `faminec/notes`. Se usa `panel-open` (y
-- no `toggle`) para que un panel ya abierto no se cierre.
local function openNotesPanel(noteName)
  if type(noteName) == "string" and noteName ~= "" then
    -- Primero se apunta la nota en el panel abierto y en el servicio (que la
    -- guarda para cuando el panel se abra), y despues se abre.
    noctalia.runAsync(
      "noctalia msg plugin "
        .. shellQuote(notesPanelId())
        .. " all open-note "
        .. shellQuote(noteName)
    )
    noctalia.runAsync(
      "noctalia msg plugin "
        .. shellQuote(notesPluginId() .. ":service")
        .. " all open-note "
        .. shellQuote(noteName)
    )
  end
  noctalia.runAsync("noctalia msg panel-open " .. shellQuote(notesPanelId()))
end

-- Codifica un texto para ponerlo en una URL (los nombres de nota pueden
-- llevar espacios, acentos o comillas).
local function urlEncode(text)
  local s = tostring(text)
  s = s:gsub("([^%w%-%.%_%~])", function(c)
    return string.format("%%%02X", string.byte(c))
  end)
  return s
end

-- ¿Sigue existiendo la nota? Se pregunta al servidor (que es quien ve el
-- disco). El segundo valor es el error cuando no se pudo saber.
local function noteExists(name, cb)
  jsonRequest("/api/note/" .. urlEncode(name), "GET", nil, function(data, err)
    if data ~= nil then
      cb(true, nil)
      return
    end
    -- "HTTP 404" es que no existe; cualquier otra cosa es que no se pudo
    -- preguntar (y no es lo mismo).
    if err ~= nil and err:match("^HTTP ") then
      cb(false, nil)
      return
    end
    cb(false, err or tr("errors.cannot_read"))
  end, PRIO_COMPROBACION)
end

-- Encola un mensaje para el celular.
local function pushToPhone(text, title, cb)
  if type(text) ~= "string" or text == "" then
    notifyErr(tr("errors.empty"))
    if cb then cb(false) end
    return
  end
  jsonRequest("/api/push", "POST", { text = text, title = title or tr("push_title") }, function(data, err)
    if data == nil then
      notifyErr(err or tr("errors.push_failed"))
      if cb then cb(false) end
      return
    end
    snapshot.pending = tonumber(data.pending) or snapshot.pending
    publish()
    notifyOk(tr("push_sent"))
    if cb then cb(true) end
  end, PRIO_MENSAJE)
end

-- Manda al celular la nota que hay abierta en el panel de notas.
local function sendCurrentNote()
  local current = readCurrentNote()
  if current == nil then
    notifyErr(tr("errors.no_note_open"))
    return
  end
  if current.content == "" then
    notifyErr(tr("errors.cannot_read"))
    return
  end
  -- Antes de mandarla se comprueba que la nota sigue existiendo: si se
  -- borro desde el movil mientras el panel de notas estaba cerrado, el canal
  -- sigue publicando su nombre (el panel no vigila si esta cerrado) y se
  -- mandaria una nota que ya no esta.
  noteExists(current.name, function(exists, err)
    if err ~= nil then
      notifyErr(err)
      return
    end
    if not exists then
      notifyErr(tr("errors.note_gone"))
      return
    end
    pushToPhone(current.content, current.name)
  end)
end

-- ------------------------------------------------------------------- IPC

local function handleCommand(cmd)
  if type(cmd) ~= "table" then
    return
  end
  local op = cmd.op
  if op == "status" then
    refreshState()
  elseif op == "open-notes" then
    openNotesPanel(nil)
  elseif op == "open-note" then
    local name = cmd.name
    if type(name) ~= "string" or name == "" then
      notifyErr(tr("errors.bad_name"))
      return
    end
    openNotesPanel(name)
  elseif op == "send-current" then
    sendCurrentNote()
  elseif op == "push" then
    pushToPhone(cmd.text, cmd.title)
  elseif op == "refresh" then
    refreshState()
  else
    noctalia.log("[notes-sync] op desconocida: " .. tostring(op))
  end
end

function onIpc(event, payload)
  if event == "refresh" then
    refreshState()
    return
  end
  if event == "cmd" and payload ~= nil then
    local ok, cmd = pcall(noctalia.json.decode, payload)
    if ok and type(cmd) == "table" then
      handleCommand(cmd)
    else
      noctalia.log("[notes-sync] payload IPC invalido")
    end
  end
end

-- ------------------------------------------------------------------ ciclo

-- Cada cuanto se pide el estado completo (no el resumen): el estado trae la
-- lista de notas, asi que no se pide en cada tic. El resumen (salud) es
-- ligero y se pide siempre.
local fullStateEvery = 6

function update()
  refresh()
  fullStateTick = (fullStateTick or 0) + 1
  if fullStateTick >= fullStateEvery then
    fullStateTick = 0
    refreshState()
  end
end

function onConfigChanged()
  refresh()
end

noctalia.setUpdateInterval(pollIntervalMs())
refreshState()
