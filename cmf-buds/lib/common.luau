--!nonstrict
-- Etiquetas y listas compartidas por el widget y el panel.

local M = {}

-- El plugin muestra siempre su propia traducción (español) y usa noctalia.tr
-- como respaldo si falta alguna clave.
M.t = {}

function M.loadTranslations()
  local dir = noctalia.pluginDir()
  if dir == nil then
    return M.t
  end
  for _, lang in ipairs({ "es", "en" }) do
    local raw = noctalia.readFile(dir .. "/translations/" .. lang .. ".json")
    if raw ~= nil then
      local ok, data = pcall(noctalia.json.decode, raw)
      if ok and type(data) == "table" then
        M.t = data
        return M.t
      end
    end
  end
  return M.t
end

M.lastTab = "sound"

local PANEL_IDS = {
  sound = "faminec/cmf-buds:panel-sound",
  controls = "faminec/cmf-buds:panel-controls",
  actions = "faminec/cmf-buds:panel-actions",
  system = "faminec/cmf-buds:panel-system",
}

function M.panel_id(tab)
  return PANEL_IDS[tab or "sound"] or PANEL_IDS.sound
end

-- Las entradas (widget, panel, servicio) viven en VMs distintas: el estado
-- compartido se pasa por noctalia.state.
function M.last_tab()
  local value = noctalia.state.get("last_tab")
  if type(value) == "string" and PANEL_IDS[value] ~= nil then
    return value
  end
  return "sound"
end

function M.set_last_tab(tab)
  if PANEL_IDS[tab] ~= nil then
    noctalia.state.set("last_tab", tab)
  end
end

function M.tr(key, args)
  local out = M.t and M.t[key]
  if out == nil then
    out = noctalia.tr(key, args)
  end
  if out == nil then
    out = key
  end
  if args ~= nil then
    out = (string.gsub(tostring(out), "{(%w+)}", function(name)
      local value = args[name]
      if value == nil then
        return "{" .. name .. "}"
      end
      return tostring(value)
    end))
  end
  return tostring(out)
end

function M.anc_label(mode, level)
  if mode == "off" then
    return M.tr("anc.off")
  elseif mode == "transparency" then
    return M.tr("anc.transparency")
  elseif mode == "anc" then
    local lvl = M.tr("anc." .. (level or "high"))
    return M.tr("anc.cancel") .. " · " .. lvl
  end
  return "—"
end

function M.anc_short(mode)
  if mode == "anc" then
    return "ANC"
  elseif mode == "transparency" then
    return "TR"
  elseif mode == "off" then
    return "OFF"
  end
  return ""
end

function M.eq_label(preset)
  local key = "eq.preset." .. tostring(preset or "balanced")
  local out = M.tr(key)
  if out == nil or out == key then
    return tostring(preset or "—")
  end
  return out
end

function M.battery_short(st)
  if st == nil then
    return "—"
  end
  local b = st.battery or {}
  local left = b.left
  local right = b.right
  local case = b.case
  if left == nil and right == nil then
    if b.bluez ~= nil then
      return tostring(b.bluez) .. "%"
    end
    return "—"
  end
  return string.format("%s%% / %s%%", left ~= nil and tostring(left) or "—", right ~= nil and tostring(right) or "—")
end

function M.battery_detail(st)
  if st == nil then
    return "—"
  end
  local b = st.battery or {}
  local function part(label, value)
    if value == nil then
      return label .. " —"
    end
    return label .. " " .. tostring(value) .. "%"
  end
  return part("L", b.left) .. " · " .. part("R", b.right) .. " · " .. part("C", b.case)
end

function M.volume_text(st)
  local v = st and st.volume or {}
  if v.percent == nil then
    return "—"
  end
  if v.muted then
    return M.tr("volume.mute")
  end
  return tostring(v.percent) .. "%"
end

local ACTION_ALLOWED = {
  left = {
    double = { "play_pause", "skip_back", "skip_forward", "voice_assistant", "no_action" },
    triple = { "skip_back", "skip_forward", "voice_assistant", "no_action" },
    hold = { "noise_control", "voice_assistant", "no_action" },
    double_hold = { "volume_up", "volume_down", "voice_assistant", "no_action" },
  },
  right = {
    double = { "play_pause", "skip_back", "skip_forward", "voice_assistant", "no_action" },
    triple = { "skip_back", "skip_forward", "voice_assistant", "no_action" },
    hold = { "noise_control", "voice_assistant", "no_action" },
    double_hold = { "volume_up", "volume_down", "voice_assistant", "no_action" },
  },
  case = {
    single = { "play_pause", "skip_back", "skip_forward", "voice_assistant", "game_mode", "no_action" },
    double = { "play_pause", "skip_back", "skip_forward", "voice_assistant", "game_mode", "no_action" },
    triple = { "play_pause", "skip_back", "skip_forward", "voice_assistant", "game_mode", "no_action" },
    hold = { "noise_control", "voice_assistant", "game_mode", "no_action" },
    rotate = { "volume_control", "no_action" },
  },
}

local GROUPS = {
  left = { "double", "triple", "hold", "double_hold" },
  right = { "double", "triple", "hold", "double_hold" },
  case = { "single", "double", "triple", "hold", "rotate" },
}

function M.gesture_types(group)
  return GROUPS[group] or GROUPS.left
end

function M.action_keys(group, gesture)
  local g = ACTION_ALLOWED[group] or ACTION_ALLOWED.left
  return g[gesture] or g.double or { "no_action" }
end

function M.action_labels(keys)
  local out = {}
  for _, key in ipairs(keys) do
    table.insert(out, M.tr("action." .. key))
  end
  return out
end

function M.action_label(key)
  local out = M.tr("action." .. tostring(key or "no_action"))
  if out == nil then
    return tostring(key or "—")
  end
  return out
end

function M.gesture_label(key)
  return M.tr("gesture." .. tostring(key or ""))
end

function M.fit_label(result)
  if result == 0 then
    return M.tr("fit.good")
  elseif result == 1 then
    return M.tr("fit.bad")
  end
  return M.tr("fit.error")
end

return M
