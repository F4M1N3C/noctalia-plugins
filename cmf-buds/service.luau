--!nonstrict
-- Servicio headless: arranca y mantiene vivo el demonio de los CMF Buds.

local statePath = nil
local socketPath = nil
local logPath = nil
local pluginPath = noctalia.pluginDir() or ""
local started = false

local function ensurePaths()
  local dir = noctalia.pluginDataDir()
  if dir ~= nil then
    statePath = dir .. "/state.json"
    socketPath = dir .. "/daemon.sock"
    logPath = dir .. "/daemon.log"
  end
end

local function daemonArgv(extra)
  local argv = {
    "python3",
    pluginPath .. "/bin/budsctl.py",
    "daemon",
    "--state", statePath,
    "--socket", socketPath,
    "--log", logPath,
    "--poll", tostring(tonumber(noctalia.getConfig("poll_seconds")) or 60),
    "--idle-timeout", "300",
    "--device-mac", noctalia.getConfig("device_mac") or "",
    "--device-name", noctalia.getConfig("device_name") or "",
  }
  if extra ~= nil then
    for _, v in ipairs(extra) do
      table.insert(argv, v)
    end
  end
  return argv
end

local function stopDaemon()
  if statePath == nil then
    return
  end
  noctalia.runAsync({
    "python3", pluginPath .. "/bin/budsctl.py", "stop",
    "--state", statePath,
    "--socket", socketPath,
    "--log", logPath,
  })
end

local function startDaemon()
  ensurePaths()
  if statePath == nil then
    return
  end
  -- El demonio tiene flock: si ya hay uno, este intento sale sin hacer nada.
  noctalia.runAsync(daemonArgv())
  started = true
end

local function ping()
  if statePath == nil then
    ensurePaths()
    if statePath == nil then
      return
    end
  end
  noctalia.runAsync({
    "python3", pluginPath .. "/bin/budsctl.py", "rpc", "{\"cmd\":\"ping\"}",
    "--state", statePath,
    "--socket", socketPath,
    "--log", logPath,
  }, function(result)
    -- Si el demonio murió (por ejemplo tras un crash), hay que relanzarlo.
    local code = result.exitCode or 0
    if code ~= 0 then
      startDaemon()
    end
  end)
end

function update()
  if not started then
    startDaemon()
  end
  ping()
end

function onEnable()
  startDaemon()
end

function onConfigChanged()
  stopDaemon()
  started = false
  startDaemon()
end

function onExit(_signal, _reason)
  stopDaemon()
end

noctalia.setUpdateInterval(20000)
startDaemon()
