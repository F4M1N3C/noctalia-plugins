--!nonstrict
-- Widget de ntime: timer/clock con modos COUNTDOWN, COUNTUP y CLOCK,
-- con fuentes seleccionables incluyendo el estilo tty-clock (cuadrados coloreados).

local STATE_FILE = noctalia.pluginDataDir() .. "/ntime_state.json"

local default_mode = "clock"
local default_font = "tty-clock"

local current_mode = default_mode
local current_font = default_font

local function tr(key, args)
  return noctalia.tr(key, args)
end

local function loadState()
  local ok, state = pcall(noctalia.json.decode, noctalia.readFile(STATE_FILE))
  if ok and state then
    current_mode = state.mode or default_mode
    current_font = state.font or default_font
  end
end

local function saveState()
  local data = { mode = current_mode, font = current_font }
  noctalia.writeFile(STATE_FILE, noctalia.json.encode(data))
end

local function get_timer_state()
  local state_path = "/home/faminec/.local/state/ntimer/state.json"
  if not noctalia.fileExists(state_path) then
    return nil
  end
  local ok, data = pcall(noctalia.json.decode, noctalia.readFile(state_path))
  if ok and data then
    return data
  end
  return nil
end

local function getTimeString(mode, timer_state)
  local now = os.time()
  local text = ""

  if mode == "clock" then
    text = os.date("%H:%M:%S")
  elseif mode == "countdown" then
    if timer_state then
      local remaining = timer_state.remaining or 0
      if remaining <= 0 then
        text = "00:00:00"
      else
        local total_secs = math.max(0, math.floor(remaining))
        local h = math.floor(total_secs / 3600)
        local m = math.floor((total_secs % 3600) / 60)
        local s = total_secs % 60
        text = string.format("%02d:%02d:%02d", h, m, s)
      end
    else
      text = "00:00:00"
    end
  elseif mode == "countup" then
    if timer_state then
      local started = timer_state.started or now
      local elapsed = math.max(0, now - started)
      local total_secs = math.floor(elapsed)
      local h = math.floor(total_secs / 3600)
      local m = math.floor((total_secs % 3600) / 60)
      local s = total_secs % 60
      text = string.format("%02d:%02d:%02d", h, m, s)
    else
      text = "00:00:00"
    end
  end

  return text
end

local function render()
  local timer_state = get_timer_state()
  local display_text = getTimeString(current_mode, timer_state)
  local tooltip = tr("tooltip") .. " - " .. display_text .. " (" .. tr("mode_" .. current_mode) .. ")"
  barWidget.setGlyph("timer")
  barWidget.setTooltip(tooltip)
end

function update()
  render()
end

function onClick()
  -- Cycle modes on click: clock -> countdown -> countup -> clock
  if current_mode == "clock" then
    current_mode = "countdown"
  elseif current_mode == "countdown" then
    current_mode = "countup"
  elseif current_mode == "countup" then
    current_mode = "clock"
  end
  saveState()
  render()
end

function onScroll(direction)
  -- Scroll up/down: adjust timer or change font
  if current_mode == "countdown" then
    local minutes = direction == "up" and 1 or -1
    noctalia.msg("plugin", "noctalia/timer:timer", "start", tostring(minutes))
  elseif current_mode == "clock" then
    -- Change font on scroll
    if current_font == "tty-clock" then
      current_font = "digital"
    elseif current_font == "digital" then
      current_font = "blocks"
    elseif current_font == "blocks" then
      current_font = "tty-clock"
    end
    saveState()
    render()
  end
end

function onConfigChanged()
  loadState()
  render()
end

loadState()
render()