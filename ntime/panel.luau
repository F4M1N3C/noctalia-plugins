--!nonstrict
-- Panel de ntime: panel completo con timer/clock, seleccion de modo y fuente,
-- y controles para COUNTDOWN, COUNTUP y CLOCK.

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

local function getColor(mode, timer_state)
  local color = "on_surface"
  if mode == "countdown" and timer_state then
    local remaining = timer_state.remaining or 0
    if remaining <= 10 then
      color = "on_error"
    end
  end
  return color
end

local function getFontGlyph(font)
  if font == "tty-clock" then
    return "tty-clock"
  elseif font == "digital" then
    return "digital"
  elseif font == "blocks" then
    return "blocks"
  end
  return nil
end

local render

local function doRender()
  local timer_state = get_timer_state()
  local display_text = getTimeString(current_mode, timer_state)
  local color = getColor(current_mode, timer_state)
  local glyph_name = getFontGlyph(current_font)

  local rows = {}

  -- Mode selector row
  table.insert(rows, ui.label({
    text = tr("mode_" .. current_mode),
    fontSize = 10,
    color = "on_surface_variant",
    width = 80,
  }))

  -- Time display area
  if glyph_name then
    table.insert(rows, ui.glyph({
      name = glyph_name,
      size = 48,
      color = color,
    }))
    table.insert(rows, ui.label({
      text = display_text,
      fontSize = 20,
      color = color,
      width = 120,
    }))
  else
    table.insert(rows, ui.label({
      text = display_text,
      fontSize = 24,
      color = color,
      flexGrow = 1,
    }))
  end

  -- Mode info
  table.insert(rows, ui.button({
    text = tr("mode_" .. current_mode),
    variant = "ghost",
    onClick = function()
      -- Cycle modes
      if current_mode == "clock" then
        current_mode = "countdown"
      elseif current_mode == "countdown" then
        current_mode = "countup"
      elseif current_mode == "countup" then
        current_mode = "clock"
      end
      saveState()
      render()
    end,
  }))

  -- Font selector
  table.insert(rows, ui.row({ gap = 8, align = "center" }, {
    ui.button({
      text = tr("font_tty_clock"),
      variant = current_font == "tty-clock" and "primary" or "ghost",
      onClick = function()
        current_font = "tty-clock"
        saveState()
        render()
      end,
    }),
    ui.button({
      text = tr("font_digital"),
      variant = current_font == "digital" and "primary" or "ghost",
      onClick = function()
        current_font = "digital"
        saveState()
        render()
      end,
    }),
    ui.button({
      text = tr("font_blocks"),
      variant = current_font == "blocks" and "primary" or "ghost",
      onClick = function()
        current_font = "blocks"
        saveState()
        render()
      end,
    }),
  }))

  -- Duration setting (only for countdown mode)
  if current_mode == "countdown" then
    table.insert(rows, ui.row({ gap = 8, align = "center" }, {
      ui.label({
        text = tr("duration") .. ":",
        fontSize = 10,
        color = "on_surface_variant",
        width = 60,
      }),
      ui.label({
        text = tostring(noctalia.getConfig("duration") or 25) .. " min",
        fontSize = 10,
        color = "on_surface",
      }),
    }))
  end

  panel.render(ui.column({ flexGrow = 1, gap = 12, align = "stretch" }, rows))
end

render = function()
  doRender()
end

local function onClick()
  -- Cycle modes on panel click
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

local function onConfigChanged()
  loadState()
  render()
end

loadState()

function onOpen(context)
  loadState()
  render()
end

function onIpc(event, payload)
  if event == "set_mode" then
    if payload == "clock" then
      current_mode = "clock"
    elseif payload == "countdown" then
      current_mode = "countdown"
    elseif payload == "countup" then
      current_mode = "countup"
    end
    saveState()
    render()
  elseif event == "set_font" then
    if payload == "tty-clock" then
      current_font = "tty-clock"
    elseif payload == "digital" then
      current_font = "digital"
    elseif payload == "blocks" then
      current_font = "blocks"
    end
    saveState()
    render()
  elseif event == "adjust_timer" then
    -- Adjust timer by minutes from payload
    local minutes = tonumber(payload) or 0
    if current_mode == "countdown" and minutes ~= 0 then
      noctalia.msg("plugin", "noctalia/timer:timer", "start", tostring(minutes))
    end
  end
end