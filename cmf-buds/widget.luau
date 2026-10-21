--!nonstrict
-- Widget de barra para los CMF Buds Pro 2.
-- Click: abre el panel. Rueda: volumen. Click derecho: cicla ANC.

local C = require("./lib/common.luau")

local glyph = noctalia.getConfig("glyph") or "headphones"
local volumeStep = tonumber(noctalia.getConfig("volume_step")) or 5

local statePath = nil
local socketPath = nil
local logPath = nil
local pluginPath = noctalia.pluginDir() or ""
local lastRaw = nil
local lastState = nil

local dot = nil
local grotesk = nil
local render

local function ensurePaths()
  local dir = noctalia.pluginDataDir()
  if dir ~= nil then
    statePath = dir .. "/state.json"
    socketPath = dir .. "/daemon.sock"
    logPath = dir .. "/daemon.log"
  end
end

local function loadFonts()
  if dot == nil then
    dot = noctalia.loadFont("fonts/Doto.ttf")
  end
  if grotesk == nil then
    grotesk = noctalia.loadFont("fonts/SpaceGrotesk.ttf")
  end
end

local function readState()
  if statePath == nil then
    ensurePaths()
  end
  if statePath == nil then
    return nil
  end
  local raw = noctalia.readFile(statePath)
  if raw == nil or raw == lastRaw then
    return lastState
  end
  local ok, data = pcall(noctalia.json.decode, raw)
  if not ok or type(data) ~= "table" then
    return lastState
  end
  lastRaw = raw
  lastState = data
  return data
end

local function rpc(req, cb, silent)
  ensurePaths()
  if statePath == nil then
    return false
  end
  local argv = {
    "python3",
    pluginPath .. "/bin/budsctl.py",
    "rpc",
    noctalia.json.encode(req),
    "--socket",
    socketPath,
    "--state",
    statePath,
    "--log",
    logPath,
  }
  return noctalia.runAsync(argv, function(result)
    local ok, data = pcall(noctalia.json.decode, result.stdout or "")
    if not ok or type(data) ~= "table" then
      if not silent then
        noctalia.notifyError(C.tr("title"), C.tr("error.generic"))
      end
      return
    end
    if data.state ~= nil then
      lastState = data.state
    end
    if data.ok ~= true and not silent then
      noctalia.notifyError(C.tr("title"), data.error or C.tr("error.generic"))
    end
    if cb ~= nil then
      cb(data)
    end
    render()
  end)
end

local function batteryValue(st)
  if st == nil then
    return nil
  end
  local b = st.battery or {}
  if b.left ~= nil then
    return b.left
  end
  if b.right ~= nil then
    return b.right
  end
  return b.bluez
end

render = function()
  local st = lastState
  local connected = st ~= nil and st.connected == true
  local ancMode = st and st.anc and st.anc.mode or "unknown"

  -- Solo el icono: hereda el color de la barra (como el resto de widgets).
  barWidget.render(ui.glyph({ name = glyph, size = 15 }))

  local rows = {
    { C.tr("tooltip.connection"), connected and C.tr("tooltip.connected") or C.tr("tooltip.disconnected") },
    { C.tr("tooltip.anc"), C.anc_label(ancMode, st and st.anc and st.anc.level or nil) },
    { C.tr("tooltip.battery"), C.battery_detail(st) },
    { C.tr("tooltip.eq"), C.eq_label(st and st.eq and st.eq.preset or nil) },
    { C.tr("tooltip.volume"), C.volume_text(st) },
  }
  if st ~= nil and st.error ~= nil and st.error ~= "" then
    table.insert(rows, { C.tr("tooltip.error"), tostring(st.error) })
  end
  barWidget.setTooltip(rows)
end

function update()
  readState()
  render()
end

function onClick()
  noctalia.togglePanel(C.panel_id(C.last_tab()))
end

function onRightClick()
  local st = lastState
  local mode = st and st.anc and st.anc.mode or "off"
  local req
  if mode == "off" then
    req = { cmd = "anc", mode = "transparency" }
  elseif mode == "transparency" then
    req = { cmd = "anc", mode = "anc", level = st and st.anc and st.anc.level or "high" }
  else
    req = { cmd = "anc", mode = "off" }
  end
  if st ~= nil then
    st.anc = st.anc or {}
    st.anc.mode = req.mode
    if req.level ~= nil then
      st.anc.level = req.level
    end
    render()
  end
  rpc(req, nil, false)
end

function onScroll(axis, steps)
  if axis ~= "vertical" then
    return
  end
  local st = lastState
  local current = st and st.volume and st.volume.percent
  if current == nil then
    current = 50
  end
  local delta = -steps * volumeStep
  local target = math.max(0, math.min(100, current + delta))
  if st ~= nil then
    st.volume = st.volume or {}
    st.volume.percent = target
    st.volume.muted = false
    render()
  end
  rpc({ cmd = "volume", percent = target, mute = "off" }, nil, true)
end

function onIpc(event, payload)
  if event == "toggle" then
    noctalia.togglePanel(C.panel_id(C.last_tab()))
  elseif event == "refresh" then
    update()
  elseif event == "anc" then
    if payload == "off" or payload == "transparency" or payload == "anc" then
      rpc({ cmd = "anc", mode = payload, level = lastState and lastState.anc and lastState.anc.level or "high" })
    end
  elseif event == "connect" then
    rpc({ cmd = "connect" })
  end
end

function onConfigChanged()
  glyph = noctalia.getConfig("glyph") or "headphones"
  volumeStep = tonumber(noctalia.getConfig("volume_step")) or 5
  render()
end

ensurePaths()
loadFonts()
C.loadTranslations()
noctalia.setUpdateInterval(5000)
update()
