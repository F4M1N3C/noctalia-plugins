--!nonstrict
-- Panel de control de los CMF Buds Pro 2 (implementación compartida).
-- Cada pestaña es un panel propio (panel_sound.luau, panel_controls.luau...)
-- para que la ventana se ajuste al tamaño del contenido.

local C = require("./common.luau")

local M = {}

local statePath = nil
local socketPath = nil
local logPath = nil
local pluginPath = noctalia.pluginDir() or ""

local st = nil
local tab = "sound"
local panelId = "faminec/cmf-buds:panel"
local ctrlGroup = "left"
local lastRaw = nil
local loading = true
local busy = false
local dragging = false
local errorText = ""
local customDirty = false
local localRules = {}
local localLast = {}
local localMods = {}
local localModsOk = false

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

local function tr(key, args)
  return C.tr(key, args)
end

local function truthy(value)
  return value == true or value == "true"
end

local function syncCustom()
  if st == nil or customDirty then
    return
  end
  local c = st.eq and st.eq.custom or {}
  st.eq = st.eq or {}
  st.eq.custom = {
    bass = tonumber(c.bass) or 0,
    mid = tonumber(c.mid) or 0,
    treble = tonumber(c.treble) or 0,
  }
end

local function syncLocal()
  if st == nil then
    return
  end
  local la = st.local_actions
  if la == nil then
    return
  end
  if la.rules ~= nil then
    localRules = la.rules
  end
  if la.last ~= nil then
    localLast = la.last
  end
  if la.modifiers ~= nil then
    localMods = la.modifiers
  end
  if la.modifiers_available ~= nil then
    localModsOk = la.modifiers_available
  end
end

local function readState()
  if statePath == nil then
    ensurePaths()
  end
  if statePath == nil then
    return false
  end
  local raw = noctalia.readFile(statePath)
  if raw == nil or raw == lastRaw then
    return false
  end
  local ok, data = pcall(noctalia.json.decode, raw)
  if not ok or type(data) ~= "table" then
    return false
  end
  lastRaw = raw
  st = data
  syncCustom()
  syncLocal()
  return true
end

local function rpc(req, cb)
  ensurePaths()
  if statePath == nil then
    errorText = tr("error.daemon")
    loading = false
    render()
    return false
  end
  busy = true
  local encoded = noctalia.json.encode(req)
  if encoded == nil then
    noctalia.log("cmf-buds: no se pudo serializar la petición")
    busy = false
    loading = false
    return
  end
  local argv = {
    "python3",
    pluginPath .. "/bin/budsctl.py",
    "rpc",
    encoded,
    "--socket",
    socketPath,
    "--state",
    statePath,
    "--log",
    logPath,
  }
  return noctalia.runAsync(argv, function(result)
    busy = false
    loading = false
    local ok, data = pcall(noctalia.json.decode, result.stdout or "")
    if not ok or type(data) ~= "table" then
      local detail = (result.stderr or ""):gsub("%s+$", "")
      errorText = detail ~= "" and detail or tr("error.generic")
    else
      if data.state ~= nil then
        st = data.state
        lastRaw = nil
        syncCustom()
        syncLocal()
      end
      if data.local_actions ~= nil then
        if data.local_actions.rules ~= nil then
          localRules = data.local_actions.rules
        end
        if data.local_actions.last ~= nil then
          localLast = data.local_actions.last
        end
        if data.local_actions.modifiers ~= nil then
          localMods = data.local_actions.modifiers
        end
        if data.local_actions.modifiers_available ~= nil then
          localModsOk = data.local_actions.modifiers_available
        end
      end
      if data.ok ~= true then
        errorText = data.error or tr("error.generic")
      else
        errorText = ""
      end
    end
    if cb ~= nil then
      cb(data)
    end
    render()
  end)
end

local function refresh()
  loading = st == nil
  render()
  rpc({ cmd = "status" })
end

-- ── piezas de UI ─────────────────────────────────────────────────────────────

local function section(titleKey, glyphName, hint)
  local children = {
    ui.glyph({ name = glyphName or "circle", size = 15, color = "primary" }),
    ui.label({
      text = tr(titleKey),
      fontFamily = dot,
      fontSize = 19,
      color = "on_surface",
      flexGrow = 1,
    }),
  }
  local row = ui.row({ align = "center", gap = 8 }, children)
  if hint ~= nil then
    return ui.column({ gap = 2 }, {
      row,
      ui.label({ text = hint, fontSize = 10, color = "on_surface_variant" }),
    })
  end
  return row
end

local function card(children, extra)
  local props = {
    gap = 10,
    padding = 14,
    radius = 14,
    fill = "surface_variant/0.35",
    align = "stretch",
  }
  if extra ~= nil then
    for k, v in pairs(extra) do
      props[k] = v
    end
  end
  return ui.column(props, children)
end

local function chip(text, selected, onClick, opts)
  local props = {
    text = text,
    variant = selected and "primary" or "secondary",
    controlSize = "sm",
    selected = selected,
    flexGrow = 1,
    onClick = onClick,
  }
  if opts ~= nil then
    for k, v in pairs(opts) do
      props[k] = v
    end
  end
  return ui.button(props)
end

local function batteryChip(label, value, charging)
  local rowChildren = {
    ui.label({
      text = value ~= nil and (tostring(value) .. "%") or "—",
      fontFamily = dot,
      fontSize = 19,
      color = value ~= nil and "on_surface" or "on_surface_variant",
    }),
  }
  if charging then
    table.insert(rowChildren, ui.glyph({ name = "bolt", size = 11, color = "primary" }))
  end
  return ui.column({
    flexGrow = 1,
    gap = 1,
    padding = 8,
    radius = 10,
    fill = "surface_variant/0.4",
    align = "center",
  }, {
    ui.label({ text = label, fontSize = 9, color = "on_surface_variant" }),
    ui.row({ gap = 3, align = "center" }, rowChildren),
  })
end

local function bigValue(text)
  return ui.label({
    text = text,
    fontFamily = dot,
    fontSize = 38,
    color = "on_surface",
  })
end

-- ── cabecera ─────────────────────────────────────────────────────────────────

local function header()
  local dev = st and st.device or {}
  local connected = st ~= nil and st.connected == true
  local name = (dev.name ~= nil and dev.name ~= "") and dev.name or "CMF Buds Pro 2"
  local statusText = connected and tr("status.connected") or (loading and tr("status.connecting") or tr("status.disconnected"))
  local statusColor = connected and "primary" or (loading and "on_surface_variant" or "error")

  local titleRow = ui.row({ align = "center", gap = 10 }, {
    ui.row({
      width = 42,
      height = 42,
      radius = 21,
      fill = "primary/0.14",
      align = "center",
      justify = "center",
    }, {
      ui.glyph({ name = "headphones", size = 23, color = "primary" }),
    }),
    ui.column({ gap = 0, flexGrow = 1 }, {
      ui.label({
        text = string.upper(name),
        fontFamily = dot,
        fontSize = 21,
        color = "on_surface",
        maxLines = 1,
      }),
      ui.row({ gap = 5, align = "center" }, {
        ui.glyph({ name = "circle-filled", size = 7, color = statusColor }),
        ui.label({ text = statusText, fontSize = 10, color = statusColor }),
        ui.label({ text = "·", fontSize = 10, color = "on_surface_variant" }),
        ui.label({ text = tr("subtitle"), fontSize = 8, color = "on_surface_variant" }),
      }),
    }),
    ui.button({
      glyph = "refresh",
      variant = "ghost",
      controlSize = "sm",
      glyphSize = 16,
      tooltip = tr("button.refresh"),
      onClick = function()
        refresh()
      end,
    }),
    ui.button({
      glyph = "settings",
      variant = "ghost",
      controlSize = "sm",
      glyphSize = 16,
      tooltip = tr("button.settings"),
      onClick = function()
        noctalia.openSettings()
      end,
    }),
    ui.button({
      glyph = "x",
      variant = "ghost",
      controlSize = "sm",
      glyphSize = 16,
      tooltip = tr("button.close"),
      onClick = function()
        panel.close()
      end,
    }),
  })

  local b = st and st.battery or {}
  local ch = b.charging or {}
  local batteryRow = ui.row({ gap = 6 }, {
    batteryChip(tr("battery.left"), b.left, ch.left == true),
    batteryChip(tr("battery.right"), b.right, ch.right == true),
    batteryChip(tr("battery.case"), b.case, ch.case == true),
  })

  return ui.column({ gap = 10 }, { titleRow, batteryRow })
end

local function tabBar()
  local function tabBtn(key, label)
    local selected = tab == key
    return ui.button({
      text = label,
      variant = selected and "primary" or "ghost",
      controlSize = "sm",
      selected = selected,
      flexGrow = 1,
      onClick = function()
        M.switchTab(key)
      end,
    })
  end
  return ui.row({ gap = 6 }, {
    tabBtn("sound", tr("tab.sound")),
    tabBtn("controls", tr("tab.controls")),
    tabBtn("actions", tr("tab.actions")),
    tabBtn("system", tr("tab.system")),
  })
end

-- ── pestaña Sonido ───────────────────────────────────────────────────────────

local function ancCard()
  local anc = st and st.anc or {}
  local mode = anc.mode or "unknown"
  local level = anc.level or "high"

  local modes = ui.row({ gap = 6 }, {
    chip(tr("anc.off"), mode == "off", function()
      rpc({ cmd = "anc", mode = "off" })
    end),
    chip(tr("anc.transparency"), mode == "transparency", function()
      rpc({ cmd = "anc", mode = "transparency" })
    end),
    chip(tr("anc.cancel"), mode == "anc", function()
      rpc({ cmd = "anc", mode = "anc", level = level })
    end),
  })

  local children = { modes }
  if mode == "anc" then
    local levels = ui.row({ gap = 6 }, {
      chip(tr("anc.adaptive"), level == "adaptive", function()
        rpc({ cmd = "anc", mode = "anc", level = "adaptive" })
      end),
      chip(tr("anc.high"), level == "high", function()
        rpc({ cmd = "anc", mode = "anc", level = "high" })
      end),
      chip(tr("anc.mid"), level == "mid", function()
        rpc({ cmd = "anc", mode = "anc", level = "mid" })
      end),
      chip(tr("anc.low"), level == "low", function()
        rpc({ cmd = "anc", mode = "anc", level = "low" })
      end),
    })
    table.insert(children, levels)
  end
  table.insert(children, ui.label({
    text = tr("anc.hint"),
    fontSize = 10,
    color = "on_surface_variant",
  }))
  return card(children)
end

local function volumeCard()
  local v = st and st.volume or {}
  local percent = tonumber(v.percent) or 0
  local muted = v.muted == true
  local sink = v.description ~= nil and v.description ~= "" and v.description or v.sink or "—"

  local top = ui.row({ align = "center", gap = 10 }, {
    bigValue(tostring(percent) .. "%"),
    ui.label({
      text = muted and tr("volume.mute") or "",
      fontSize = 10,
      color = "error",
      flexGrow = 1,
    }),
    ui.button({
      glyph = muted and "volume-off" or "volume",
      text = muted and tr("volume.unmute") or tr("volume.mute"),
      variant = "secondary",
      controlSize = "sm",
      onClick = function()
        rpc({ cmd = "volume", mute = "toggle" })
      end,
    }),
  })

  local slider = ui.slider({
    min = 0,
    max = 100,
    step = 1,
    value = percent,
    flexGrow = 1,
    onChange = function(value)
      dragging = true
      if st ~= nil then
        st.volume = st.volume or {}
        st.volume.percent = tonumber(value) or percent
        st.volume.muted = false
      end
    end,
    onDragEnd = function()
      dragging = false
      local target = st and st.volume and st.volume.percent or percent
      rpc({ cmd = "volume", percent = target, mute = "off" })
    end,
  })

  return card({
    top,
    slider,
    ui.label({
      text = tr("volume.system", { sink = sink }),
      fontSize = 9,
      color = "on_surface_variant",
      maxLines = 1,
    }),
  })
end

local function presetRow(names)
  local buttons = {}
  for _, name in ipairs(names) do
    table.insert(buttons, chip(tr("eq.preset." .. name), st ~= nil and st.eq and st.eq.preset == name, function()
      rpc({ cmd = "eq", preset = name })
    end))
  end
  return ui.row({ gap = 6 }, buttons)
end

local function customSlider(labelKey, key)
  local custom = st and st.eq and st.eq.custom or {}
  local value = tonumber(custom[key]) or 0
  return ui.row({ gap = 8, align = "center" }, {
    ui.label({ text = tr(labelKey), width = 52, fontSize = 11, color = "on_surface_variant" }),
    ui.slider({
      min = -6,
      max = 6,
      step = 1,
      value = value,
      flexGrow = 1,
      onChange = function(newValue)
        dragging = true
        customDirty = true
        if st ~= nil then
          st.eq = st.eq or {}
          st.eq.custom = st.eq.custom or { bass = 0, mid = 0, treble = 0 }
          st.eq.custom[key] = tonumber(newValue) or value
        end
      end,
      onDragEnd = function()
        dragging = false
        local c = st and st.eq and st.eq.custom or {}
        rpc({
          cmd = "custom_eq",
          bass = tonumber(c.bass) or 0,
          mid = tonumber(c.mid) or 0,
          treble = tonumber(c.treble) or 0,
        })
        customDirty = false
      end,
    }),
    ui.label({
      text = string.format("%+d", math.floor(value + 0.5)),
      width = 34,
      fontSize = 11,
      color = "on_surface",
      textAlign = "end",
    }),
  })
end

local function eqCard()
  local bass = st and st.bass or {}
  local level = tonumber(bass.level) or 1
  local enabled = bass.enabled == true

  local levelChips = {}
  for i = 1, 5 do
    table.insert(levelChips, chip(tostring(i), enabled and level == i, function()
      rpc({ cmd = "bass", enabled = true, level = i })
    end, { flexGrow = 1 }))
  end

  return card({
    presetRow({ "balanced", "rock", "electronic", "pop" }),
    presetRow({ "vocal", "classical", "custom" }),
    ui.separator({ thickness = 1, color = "outline/0.25", spacing = 6 }),
    ui.row({ align = "center", gap = 8 }, {
      ui.glyph({ name = "wave-sine", size = 14, color = "primary" }),
      ui.label({
        text = tr("eq.ultra"),
        fontSize = 11,
        color = "on_surface",
        flexGrow = 1,
      }),
      ui.toggle({
        checked = enabled,
        onChange = function(value)
          rpc({ cmd = "bass", enabled = truthy(value), level = level })
        end,
      }),
    }),
    ui.row({ gap = 6 }, levelChips),
    ui.separator({ thickness = 1, color = "outline/0.25", spacing = 6 }),
    ui.label({
      text = tr("eq.custom"),
      fontFamily = dot,
      fontSize = 16,
      color = "on_surface",
    }),
    customSlider("eq.bass", "bass"),
    customSlider("eq.mid", "mid"),
    customSlider("eq.treble", "treble"),
    ui.label({
      text = tr("eq.hint"),
      fontSize = 9,
      color = "on_surface_variant",
    }),
  })
end

local function soundTab()
  return {
    section("anc.title", "wave-sine"),
    ancCard(),
    section("volume.title", "volume"),
    volumeCard(),
    section("eq.title", "adjustments"),
    eqCard(),
  }
end

-- ── pestaña Controles ────────────────────────────────────────────────────────

local function controlsTab()
  local rows = {
    section("controls." .. ctrlGroup, ctrlGroup == "case" and "dialpad" or "hand-click"),
  }

  local groupRow = ui.row({ gap = 6 }, {
    chip(tr("controls.left"), ctrlGroup == "left", function()
      ctrlGroup = "left"
      render()
    end),
    chip(tr("controls.right"), ctrlGroup == "right", function()
      ctrlGroup = "right"
      render()
    end),
    chip(tr("controls.case"), ctrlGroup == "case", function()
      ctrlGroup = "case"
      render()
    end),
  })
  table.insert(rows, groupRow)

  if ctrlGroup == "case" then
    table.insert(rows, ui.label({
      text = tr("controls.case_hint"),
      fontSize = 10,
      color = "on_surface_variant",
    }))
  end

  local items = {}
  for _, gesture in ipairs(C.gesture_types(ctrlGroup)) do
    local keys = C.action_keys(ctrlGroup, gesture)
    local current = st and st.gestures and st.gestures[ctrlGroup .. "." .. gesture] or "no_action"
    local selected = 0
    for i, key in ipairs(keys) do
      if key == current then
        selected = i - 1
        break
      end
    end
    table.insert(items, ui.row({ gap = 8, align = "center" }, {
      ui.label({
        text = C.gesture_label(gesture),
        width = 136,
        fontSize = 11,
        color = "on_surface_variant",
      }),
      ui.select({
        options = C.action_labels(keys),
        selectedIndex = selected,
        flexGrow = 1,
        controlSize = "sm",
        onChange = function(value)
          local idx = (tonumber(value) or 0) + 1
          local action = keys[idx] or "no_action"
          rpc({ cmd = "gesture", group = ctrlGroup, gesture = gesture, action = action })
        end,
      }),
    }))
  end
  table.insert(rows, card(items))

  local ring = st and st.ring or {}
  table.insert(rows, section("ring.title", "bell"))
  table.insert(rows, card({
    ui.row({ gap = 8 }, {
      ui.button({
        text = ring.left and tr("ring.stop") or tr("ring.left"),
        glyph = ring.left and "player-stop" or "volume",
        variant = ring.left and "destructive" or "secondary",
        controlSize = "sm",
        flexGrow = 1,
        onClick = function()
          rpc({ cmd = "ring", side = "left", on = not (ring.left == true) })
        end,
      }),
      ui.button({
        text = ring.right and tr("ring.stop") or tr("ring.right"),
        glyph = ring.right and "player-stop" or "volume",
        variant = ring.right and "destructive" or "secondary",
        controlSize = "sm",
        flexGrow = 1,
        onClick = function()
          rpc({ cmd = "ring", side = "right", on = not (ring.right == true) })
        end,
      }),
    }),
  }))
  return rows
end

-- ── pestaña Atajos locales ───────────────────────────────────────────────────

local function infoRow(labelKey, value)
  return ui.row({ gap = 8, align = "center" }, {
    ui.label({ text = tr(labelKey), width = 78, fontSize = 10, color = "on_surface_variant" }),
    ui.label({
      text = (value ~= nil and tostring(value) ~= "") and tostring(value) or "—",
      fontSize = 10,
      color = "on_surface",
      flexGrow = 1,
      maxLines = 2,
    }),
  })
end

local TRIGGERS = { "volume_up", "volume_down" }
local TRIGGER_NAMES = { volume_up = "dial_up", volume_down = "dial_down" }

local function triggerName(trigger)
  return TRIGGER_NAMES[tostring(trigger)] or tostring(trigger)
end
local MODIFIERS = { "none", "super", "ctrl", "alt", "shift", "no_super" }

local function modifierRequire(mod)
  if mod == "super" or mod == "ctrl" or mod == "alt" or mod == "shift" then
    return { mod }
  end
  return {}
end

local function modifierForbid(mod)
  if mod == "no_super" then
    return { "super" }
  end
  return {}
end

local function ruleIndexById(id)
  for i, rule in ipairs(localRules) do
    if tostring(rule.id) == tostring(id) then
      return i
    end
  end
  return nil
end

local ruleCounter = 0

local function saveRule(rule)
  rule.require = modifierRequire(rule.modifier)
  rule.forbid = modifierForbid(rule.modifier)
  rpc({ cmd = "local_rule_set", rule = rule })
end

local function removeRule(id)
  local idx = ruleIndexById(id)
  if idx ~= nil then
    table.remove(localRules, idx)
  end
  rpc({ cmd = "local_rule_delete", id = id })
end

local function newRule()
  ruleCounter = ruleCounter + 1
  return {
    id = "r" .. tostring(ruleCounter) .. "-" .. tostring(math.floor(math.random(100000))),
    trigger = "volume_up",
    presses = 0,
    modifier = "super",
    command = "",
    enabled = true,
    notify = true,
    restore_volume = false,
    require = {},
    forbid = {},
  }
end

local function selectRow(label, options, selected, onChange)
  return ui.row({ gap = 8, align = "center" }, {
    ui.label({ text = label, width = 92, fontSize = 11, color = "on_surface_variant" }),
    ui.select({
      options = options,
      selectedIndex = selected,
      flexGrow = 1,
      controlSize = "sm",
      onChange = onChange,
    }),
  })
end

local function ruleCard(rule)
  local triggerIdx = 1
  for i, name in ipairs(TRIGGERS) do
    if name == rule.trigger then
      triggerIdx = i - 1
      break
    end
  end
  local modIdx = 1
  for i, name in ipairs(MODIFIERS) do
    if name == rule.modifier then
      modIdx = i - 1
      break
    end
  end

  local header = ui.row({ gap = 8, align = "center" }, {
    ui.glyph({ name = "command", size = 15, color = "primary" }),
    ui.label({
      text = tr("shortcut.rule_title", {
        trigger = tr("shortcut.gesture." .. triggerName(rule.trigger)),
        modifier = tr("shortcut.modifier." .. tostring(rule.modifier or "none")),
      }),
      fontSize = 12,
      color = "on_surface",
      flexGrow = 1,
    }),
    ui.toggle({
      checked = rule.enabled ~= false,
      onChange = function(value)
        rule.enabled = truthy(value)
        saveRule(rule)
      end,
    }),
    ui.button({
      glyph = "trash",
      variant = "ghost",
      controlSize = "sm",
      glyphSize = 15,
      tooltip = tr("shortcut.delete"),
      onClick = function()
        removeRule(rule.id)
      end,
    }),
  })

  local children = {
    header,
    selectRow(tr("shortcut.gesture_label"), {
      tr("shortcut.gesture.dial_up"),
      tr("shortcut.gesture.dial_down"),
    }, triggerIdx, function(value)
      rule.trigger = TRIGGERS[(tonumber(value) or 0) + 1] or "volume_up"
      saveRule(rule)
    end),
    selectRow(tr("shortcut.presses_label"), {
      tr("shortcut.presses.any"),
      "1",
      "2",
      "3",
      "4",
      "5",
    }, tonumber(rule.presses) or 0, function(value)
      rule.presses = tonumber(value) or 0
      saveRule(rule)
    end),
    selectRow(tr("shortcut.modifier_label"), {
      tr("shortcut.modifier.none"),
      tr("shortcut.modifier.super"),
      tr("shortcut.modifier.ctrl"),
      tr("shortcut.modifier.alt"),
      tr("shortcut.modifier.shift"),
      tr("shortcut.modifier.no_super"),
    }, modIdx, function(value)
      rule.modifier = MODIFIERS[(tonumber(value) or 0) + 1] or "none"
      rule.require = modifierRequire(rule.modifier)
      rule.forbid = modifierForbid(rule.modifier)
      saveRule(rule)
    end),
    ui.row({ gap = 8, align = "center" }, {
      ui.label({ text = tr("shortcut.command_label"), width = 92, fontSize = 11, color = "on_surface_variant" }),
      ui.input({
        key = "cmd-" .. tostring(rule.id),
        value = rule.command or "",
        placeholder = tr("shortcut.command_placeholder"),
        flexGrow = 1,
        onChange = function(value)
          rule.command = value
        end,
        onSubmit = function(value)
          rule.command = value
          saveRule(rule)
        end,
      }),
    }),
    ui.row({ gap = 10, align = "center" }, {
      ui.toggle({
        checked = rule.notify ~= false,
        onChange = function(value)
          rule.notify = truthy(value)
          saveRule(rule)
        end,
      }),
      ui.label({ text = tr("shortcut.notify"), fontSize = 10, color = "on_surface_variant" }),
      ui.toggle({
        checked = rule.restore_volume == true,
        onChange = function(value)
          rule.restore_volume = truthy(value)
          saveRule(rule)
        end,
      }),
      ui.label({ text = tr("shortcut.restore"), fontSize = 10, color = "on_surface_variant" }),
      ui.button({
        text = tr("shortcut.test"),
        glyph = "player-play",
        variant = "secondary",
        controlSize = "sm",
        flexGrow = 1,
        onClick = function()
          if (rule.command or "") ~= "" then
            rpc({ cmd = "local_test", command = rule.command })
          end
        end,
      }),
    }),
  }
  return card(children)
end

local function shortcutsTab()
  local rows = {
    section("shortcut.title", "command"),
    ui.label({
      text = tr("shortcut.hint"),
      fontSize = 10,
      color = "on_surface_variant",
      maxLines = 3,
    }),
  }

  for _, rule in ipairs(localRules) do
    table.insert(rows, ruleCard(rule))
  end

  table.insert(rows, ui.button({
    text = tr("shortcut.add"),
    glyph = "plus",
    variant = "secondary",
    controlSize = "sm",
    onClick = function()
      local rule = newRule()
      table.insert(localRules, rule)
      saveRule(rule)
    end,
  }))

  local lastText = tr("shortcut.none")
  if localLast ~= nil and localLast.trigger ~= nil then
    local mods = ""
    if localLast.modifiers ~= nil and #localLast.modifiers > 0 then
      local names = {}
      for _, m in ipairs(localLast.modifiers) do
        table.insert(names, m:upper())
      end
      mods = " + " .. table.concat(names, "+")
    end
    lastText = tr("shortcut.last", {
      trigger = tostring(localLast.trigger),
      presses = tostring(localLast.presses or 1),
      modifiers = mods,
      command = localLast.command or tr("shortcut.none"),
    })
  end

  local modsText = localModsOk and (tr("shortcut.mods_held", { mods = (#localMods > 0) and table.concat(localMods, "+") or "—" })) or tr("shortcut.mods_unavailable")

  table.insert(rows, card({
    infoRow("shortcut.last_label", lastText),
    infoRow("shortcut.mods_label", modsText),
    ui.label({
      text = tr("shortcut.note"),
      fontSize = 9,
      color = "on_surface_variant",
      maxLines = 3,
    }),
  }))

  return rows
end

-- ── pestaña Sistema ──────────────────────────────────────────────────────────

local function toggleRow(glyphName, titleKey, descKey, key, current)
  return ui.row({ align = "center", gap = 10 }, {
    ui.row({
      width = 34,
      height = 34,
      radius = 10,
      fill = "primary/0.10",
      align = "center",
      justify = "center",
    }, {
      ui.glyph({ name = glyphName, size = 16, color = "primary" }),
    }),
    ui.column({ gap = 1, flexGrow = 1 }, {
      ui.label({ text = tr(titleKey), fontSize = 12, color = "on_surface" }),
      ui.label({ text = tr(descKey), fontSize = 9, color = "on_surface_variant", maxLines = 1 }),
    }),
    ui.toggle({
      checked = current == true,
      onChange = function(value)
        rpc({ cmd = "toggle", key = key, value = truthy(value) })
      end,
    }),
  })
end

local function fitCard()
  local fit = st and st.fit_test or {}
  local running = fit.running == true
  local children = {
    ui.row({ align = "center", gap = 8 }, {
      ui.label({
        text = tr("fit.title"),
        fontFamily = dot,
        fontSize = 18,
        color = "on_surface",
        flexGrow = 1,
      }),
      ui.button({
        text = running and tr("fit.stop") or tr("fit.start"),
        glyph = running and "player-stop" or "ear",
        variant = running and "destructive" or "secondary",
        controlSize = "sm",
        onClick = function()
          rpc({ cmd = "fit_test", start = not running })
        end,
      }),
    }),
  }

  if running then
    table.insert(children, ui.row({ gap = 6, align = "center" }, {
      ui.glyph({ name = "loader", size = 13, color = "primary" }),
      ui.label({ text = tr("fit.running"), fontSize = 10, color = "on_surface_variant" }),
    }))
  else
    local function resultChip(labelKey, value)
      return ui.column({
        flexGrow = 1,
        gap = 2,
        padding = 8,
        radius = 10,
        fill = "surface_variant/0.4",
        align = "center",
      }, {
        ui.label({ text = tr(labelKey), fontSize = 9, color = "on_surface_variant" }),
        ui.label({
          text = C.fit_label(value),
          fontSize = 11,
          color = value == 0 and "primary" or (value == 1 and "error" or "on_surface_variant"),
        }),
      })
    end
    table.insert(children, ui.row({ gap = 6 }, {
      resultChip("fit.left", fit.left),
      resultChip("fit.right", fit.right),
    }))
  end

  table.insert(children, ui.label({
    text = tr("fit.hint"),
    fontSize = 9,
    color = "on_surface_variant",
  }))
  return card(children)
end

local function infoCard()
  local dev = st and st.device or {}
  return card({
    infoRow("info.model", dev.model),
    infoRow("info.firmware", dev.firmware),
    infoRow("info.serial", dev.serial),
    infoRow("info.address", dev.mac),
    infoRow("info.battery", C.battery_detail(st)),
  })
end

local function connectionCard()
  local connected = st ~= nil and st.connected == true
  local children = {
    ui.row({ align = "center", gap = 8 }, {
      ui.glyph({ name = connected and "bluetooth" or "bluetooth-off", size = 16, color = connected and "primary" or "error" }),
      ui.label({
        text = connected and tr("status.connected") or tr("status.disconnected"),
        fontSize = 12,
        color = connected and "primary" or "error",
        flexGrow = 1,
      }),
      ui.button({
        text = connected and tr("button.reconnect") or tr("button.connect"),
        variant = "secondary",
        controlSize = "sm",
        onClick = function()
          rpc({ cmd = "connect" })
        end,
      }),
    }),
  }
  if errorText ~= "" then
    table.insert(children, ui.row({
      gap = 6,
      padding = 8,
      radius = 8,
      fill = "error/0.12",
      align = "center",
    }, {
      ui.glyph({ name = "alert-triangle", size = 13, color = "error" }),
      ui.label({ text = errorText, fontSize = 9, color = "error", flexGrow = 1, maxLines = 3 }),
    }))
  end
  table.insert(children, ui.label({
    text = tr("hint.phone"),
    fontSize = 9,
    color = "on_surface_variant",
    maxLines = 2,
  }))
  return card(children)
end

local function systemTab()
  return {
    section("system.title", "adjustments"),
    card({
      toggleRow("sparkles", "system.spatial", "system.spatial_desc", "spatial", st and st.spatial),
      ui.separator({ thickness = 1, color = "outline/0.25", spacing = 6 }),
      toggleRow("ear", "system.in_ear", "system.in_ear_desc", "in_ear", st and st.in_ear),
      ui.separator({ thickness = 1, color = "outline/0.25", spacing = 6 }),
      toggleRow("bolt", "system.low_latency", "system.low_latency_desc", "low_latency", st and st.low_latency),
      ui.separator({ thickness = 1, color = "outline/0.25", spacing = 6 }),
      toggleRow("devices", "system.dual", "system.dual_desc", "dual_connection", st and st.dual_connection),
    }),
    fitCard(),
    section("info.title", "info-circle"),
    infoCard(),
    connectionCard(),
    ui.row({ gap = 8, align = "center" }, {
      ui.button({
        text = tr("button.settings"),
        glyph = "settings",
        variant = "ghost",
        controlSize = "sm",
        onClick = function()
          noctalia.openSettings()
        end,
      }),
      ui.label({
        text = "CMF Buds · Nothing X para Linux",
        fontSize = 9,
        color = "on_surface_variant",
        flexGrow = 1,
        textAlign = "end",
      }),
    }),
  }
end

-- ── API del módulo ───────────────────────────────────────────────────────────

function M.setup(defaultTab, ownPanelId)
  tab = defaultTab or "sound"
  panelId = ownPanelId or panelId
  C.set_last_tab(tab)
end

function M.switchTab(key)
  local target = C.panel_id(key)
  if target == nil then
    return
  end
  if target == panelId then
    return
  end
  noctalia.togglePanel(target)
end

-- ── render ───────────────────────────────────────────────────────────────────

render = function()
  if statePath == nil then
    ensurePaths()
  end

  local body
  if st == nil then
    body = ui.column({ gap = 10, align = "center", justify = "center" }, {
      ui.glyph({ name = "headphones", size = 34, color = "primary" }),
      ui.label({ text = tr("loading"), fontFamily = dot, fontSize = 18, color = "on_surface" }),
      ui.label({ text = tr("hint.phone"), fontSize = 9, color = "on_surface_variant", maxLines = 2 }),
    })
  else
    local rows
    if tab == "controls" then
      rows = controlsTab()
    elseif tab == "actions" then
      rows = shortcutsTab()
    elseif tab == "system" then
      rows = systemTab()
    else
      rows = soundTab()
    end
    body = ui.column({ gap = 12, align = "stretch" }, rows)
  end

  panel.render(ui.column({ gap = 10, padding = 14, align = "stretch" }, {
    header(),
    tabBar(),
    body,
  }))
end

-- ── ciclo de vida ────────────────────────────────────────────────────────────

function M.onOpen(_context)
  M.setup(tab, panelId)
  ensurePaths()
  loadFonts()
  noctalia.setUpdateInterval(3000)
  panel.setWantsSecondTicks(false)
  loading = true
  errorText = ""
  readState()
  render()
  refresh()
end

function M.onClose()
end

function M.update()
  if dragging then
    return
  end
  if readState() then
    render()
  end
end

function M.onConfigChanged()
  ensurePaths()
  loadFonts()
  C.loadTranslations()
  readState()
  render()
  refresh()
end

function M.onIpc(event, payload)
  if event == "refresh" then
    refresh()
  elseif event == "tab" then
    if payload == "sound" or payload == "controls" or payload == "actions" or payload == "system" then
      M.switchTab(payload)
    end
  end
end

ensurePaths()
loadFonts()
C.loadTranslations()

return M
