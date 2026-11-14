--!nonstrict
-- Bar widget for the CMF Buds Pro 2.
-- Click: opens the panel. Wheel: volume. Right click: cycles ANC.

local C = require("./lib/common.luau")

local glyph = noctalia.getConfig("glyph") or "headphones-filled"
local volumeStep = tonumber(noctalia.getConfig("volume_step")) or 5

local statePath = nil
local socketPath = nil
local pluginPath = noctalia.pluginDir() or ""

local lastState = nil
local lastReadError = false
local volumeInFlight = false
local pendingVolumeTarget = nil
local lastVolumeSentMs = 0
local wheelBurst = false
local volumeBurstResetTimer = nil

local RPC_TIMEOUT_MS = 60000

local function ensurePaths()
  pluginPath = noctalia.pluginDir() or pluginPath
  local dir = noctalia.pluginDataDir()
  if dir ~= nil and dir ~= "" then
    statePath = dir .. "/state.json"
    socketPath = dir .. "/daemon.sock"
  end
end

local function readState()
  if statePath == nil then
    return nil
  end
  local okRead, text = pcall(noctalia.read, statePath)
  if not okRead or type(text) ~= "string" or text == "" then
    lastReadError = true
    return nil
  end
  local okDecode, obj = pcall(noctalia.jsonDecode, text)
  if not okDecode or type(obj) ~= "table" then
    lastReadError = true
    return nil
  end
  lastReadError = false
  return obj
end

local function ancGlyph(state)
  local lp = state.listening or {}
  local mode = tostring(lp.mode or "off")
  if mode == "anc" then
    return "ear"
  elseif mode == "transparency" then
    return "ear-off"
  end
  return glyph
end

local function tooltipText(state)
  if lastReadError then
    return C.tr("tooltip.unavailable")
  end
  if type(state) ~= "table" then
    return C.tr("tooltip.starting")
  end
  local conn = state.connection or {}
  local bat = state.battery or {}
  local lp = state.listening or {}
  local eq = state.equalizer or {}
  local vol = state.volume or {}

  local lines = {}
  if conn.connected ~= true then
    table.insert(lines, C.tr("tooltip.disconnected"))
  else
    table.insert(lines, C.tr("tooltip.connected"))
    local ancText = C.anc_label(tostring(lp.mode or "off"))
    if lp.mode == "anc" and lp.anc_level ~= nil then
      ancText = ancText .. " (" .. C.anc_level_label(tostring(lp.anc_level)) .. ")"
    end
    table.insert(lines, ancText)
    if bat.left ~= nil then
      table.insert(lines, C.tr("tooltip.left") .. ": " .. tostring(bat.left) .. "%")
    end
    if bat.right ~= nil then
      table.insert(lines, C.tr("tooltip.right") .. ": " .. tostring(bat.right) .. "%")
    end
    if bat.case ~= nil then
      table.insert(lines, C.tr("tooltip.case") .. ": " .. tostring(bat.case) .. "%")
    end
    table.insert(lines, C.eq_label(tostring(eq.preset or "balanced")))
    if vol.percent ~= nil then
      local v = tostring(vol.percent) .. "%"
      if vol.muted == true then
        v = v .. " (" .. C.tr("volume.mute") .. ")"
      end
      table.insert(lines, C.tr("tooltip.volume") .. ": " .. v)
    end
  end
  if state.error ~= nil and tostring(state.error) ~= "" then
    table.insert(lines, C.tr("tooltip.error") .. ": " .. C.error_text(tostring(state.error), state.error_detail))
  end
  return table.concat(lines, "\n")
end

local function render()
  local state = lastState
  local conn = (type(state) == "table" and state.connection) or {}
  local battery = (type(state) == "table" and state.battery) or {}
  local value = C.battery_overall(battery)

  noctalia.setBarWidget({
    icon = ancGlyph(type(state) == "table" and state or {}),
    tooltip = tooltipText(state),
    showIcon = true,
    showPercent = conn.connected == true and value ~= nil,
    percent = value,
    onClick = "openPanel",
    onMiddleClick = "connect",
    onRightClick = "cycleAnc",
  })
end

local function rpc(req, cb, silent)
  ensurePaths()
  if statePath == nil or socketPath == nil then
    if cb ~= nil then cb(nil) end
    return false
  end
  local okEncode, payload = pcall(noctalia.jsonEncode, req)
  if not okEncode then
    if cb ~= nil then cb(nil) end
    return false
  end
  local python = "/usr/bin/python3"
  local script = pluginPath .. "/bin/budsctl.py"
  local args = {
    python, script, "rpc", payload,
    "--state", statePath,
    "--socket", socketPath,
    "--poll", tostring(C.poll_seconds()),
    "--device-mac", tostring(noctalia.getConfig("device_mac") or ""),
    "--device-name", tostring(noctalia.getConfig("device_name") or ""),
  }

  local launched = noctalia.runAsync(args, function(result)
    if type(result) ~= "table" or result.code ~= 0 then
      if not silent then
        local detail = nil
        if type(result) == "table" then
          local stderr = tostring(result.stderr or "")
          local stdout = tostring(result.stdout or "")
          if stderr ~= "" then
            detail = stderr
          elseif stdout ~= "" then
            detail = stdout
          end
        end
        noctalia.notify(C.tr("title"), C.error_text("daemon_failed", detail))
      end
      if cb ~= nil then cb(nil) end
      return
    end

    local stdout = tostring(result.stdout or "")
    local okDecode, data = pcall(noctalia.jsonDecode, stdout)
    if not okDecode or type(data) ~= "table" then
      if not silent then
        noctalia.notify(C.tr("title"), C.tr("error.decode"))
      end
      if cb ~= nil then cb(nil) end
      return
    end

    if data.ok == false then
      if not silent then
        noctalia.notify(C.tr("title"), C.error_text(data.error, data.error_detail))
      end
      if cb ~= nil then cb(data) end
      return
    end

    if data.state ~= nil then
      lastState = data.state
      render()
    end
    if cb ~= nil then cb(data) end
  end, RPC_TIMEOUT_MS)

  if not launched then
    if not silent then
      noctalia.notify(C.tr("title"), C.error_text("daemon_failed"))
    end
    if cb ~= nil then cb(nil) end
  end
  return launched
end

local function flushVolumeQueue()
  if pendingVolumeTarget == nil then
    volumeInFlight = false
    wheelBurst = false
    return
  end
  local target = pendingVolumeTarget
  pendingVolumeTarget = nil
  local now = (noctalia.epochMs and noctalia.epochMs()) or 0
  if now > 0 then
    lastVolumeSentMs = now
  end
  volumeInFlight = true
  local launched = rpc({ cmd = "volume", percent = target, mute = "off" }, function()
    volumeInFlight = false
    flushVolumeQueue()
  end, true)
  if not launched then
    volumeInFlight = false
    pendingVolumeTarget = nil
    wheelBurst = false
  end
end

local function applyVolume(delta)
  local state = lastState or {}
  local vol = state.volume or {}
  local current = tonumber(vol.percent) or 0
  local target = C.clamp(current + delta, 0, 100)
  pendingVolumeTarget = target
  if not volumeInFlight then
    local now = (noctalia.epochMs and noctalia.epochMs()) or 0
    local wait = 0
    if wheelBurst and lastVolumeSentMs > 0 and now > 0 then
      local elapsed = now - lastVolumeSentMs
      if elapsed < 160 then
        wait = 160 - elapsed
      end
    end
    if wait > 0 then
      noctalia.setTimeout(function()
        if not volumeInFlight then
          flushVolumeQueue()
        end
      end, wait)
    else
      flushVolumeQueue()
    end
  end
end

local function resetWheelBurst()
  wheelBurst = false
  volumeBurstResetTimer = nil
end

local function onClick()
  noctalia.openPanel(C.panel_id())
end

local function onConnect()
  rpc({ cmd = "connect" }, function(data)
    if data ~= nil and data.ok == true then
      noctalia.notify(C.tr("title"), C.tr("toast.connected"))
    end
  end)
end

local function onDisconnect()
  rpc({ cmd = "disconnect" }, function(data)
    if data ~= nil and data.ok == true then
      noctalia.notify(C.tr("title"), C.tr("toast.disconnected"))
    end
  end)
end

local function cycleAnc()
  local state = lastState or {}
  local lp = state.listening or {}
  local nextMode = C.next_anc_mode(tostring(lp.mode or "off"))
  local level = tostring(lp.anc_level or "high")
  rpc({ cmd = "anc", mode = nextMode, level = level }, function(data)
    if data ~= nil and data.ok == true then
      noctalia.notify(C.tr("title"), C.anc_label(nextMode))
    end
  end)
end

local function onScroll(steps)
  local conn = (lastState or {}).connection or {}
  if conn.connected ~= true then
    return false
  end
  wheelBurst = true
  if volumeBurstResetTimer ~= nil then
    noctalia.clearTimeout(volumeBurstResetTimer)
  end
  volumeBurstResetTimer = noctalia.setTimeout(resetWheelBurst, 220)
  local delta = -(tonumber(steps) or 0) * volumeStep
  applyVolume(delta)
  return true
end

function update()
  ensurePaths()
  local state = readState()
  if state ~= nil then
    lastState = state
  end
  render()
end

function onBarWidgetEvent(event, _payload)
  if event == "openPanel" then
    onClick()
  elseif event == "connect" then
    onConnect()
  elseif event == "cycleAnc" then
    cycleAnc()
  elseif event == "wheelUp" then
    onScroll(1)
  elseif event == "wheelDown" then
    onScroll(-1)
  end
end

function onIpc(event, payload)
  if event == "toggle" or event == "togglePanel" then
    noctalia.togglePanel(C.panel_id())
  elseif event == "connect" then
    onConnect()
  elseif event == "disconnect" then
    onDisconnect()
  elseif event == "refresh" then
    update()
  elseif event == "anc" then
    local mode = tostring((type(payload) == "table" and payload.mode) or "anc")
    local level = tostring((type(payload) == "table" and payload.level) or ((lastState or {}).listening or {}).anc_level or "high")
    rpc({ cmd = "anc", mode = mode, level = level })
  end
end

function onConfigChanged()
  glyph = noctalia.getConfig("glyph") or "headphones-filled"
  volumeStep = tonumber(noctalia.getConfig("volume_step")) or 5
  ensurePaths()
  C.loadTranslations()
  update()
end

ensurePaths()
C.loadTranslations()
-- The panel polls the state every 500 ms and the daemon publishes external
-- changes (phone volume, ANC, battery) as soon as it sees them: with a 1 s
-- interval the bar tooltip stays live.
noctalia.setUpdateInterval(1000)
update()
