--!nonstrict
-- Servicio headless: deja EasyEffects en marcha y con el preset cargado.

local pipeline = "output"
local preset = "Noctalia EQ"
local ensuring = false

local function tr(key, args)
  return noctalia.tr(key, args)
end

local function loadConfig()
  pipeline = noctalia.getConfig("pipeline") or "output"
  preset = noctalia.getConfig("preset") or "Noctalia EQ"
end

local function statePath()
  local dir = noctalia.pluginDataDir()
  if dir == nil then
    return nil
  end
  return dir .. "/state.json"
end

local function runEqctl(args, cb)
  local dir = noctalia.pluginDir()
  if dir == nil then
    if cb ~= nil then
      cb({ exitCode = 1, stdout = "", stderr = "plugin dir unavailable" })
    end
    return false
  end
  local argv = { "python3", dir .. "/bin/eqctl" }
  for _, value in ipairs(args) do
    table.insert(argv, tostring(value))
  end
  return noctalia.runAsync(argv, cb)
end

local function ensure()
  if ensuring then
    return
  end
  ensuring = true
  loadConfig()

  local args = { "ensure", "--pipeline", pipeline, "--preset", preset }
  local path = statePath()
  if path ~= nil and noctalia.fileExists(path) then
    table.insert(args, "--state")
    table.insert(args, path)
  end

  runEqctl(args, function(result)
    ensuring = false
    if result.exitCode ~= 0 then
      local detail = (result.stderr or ""):gsub("%s+$", "")
      noctalia.notifyError(tr("title"), detail ~= "" and detail or tr("ensure_failed"))
      noctalia.state.set("eq.ready", false)
    else
      noctalia.state.set("eq.ready", true)
    end
  end)
end

ensure()

function onConfigChanged()
  ensure()
end

function onIpc(event, _payload)
  if event == "ensure" then
    ensure()
  elseif event == "open" then
    runEqctl({ "open" })
  end
end
