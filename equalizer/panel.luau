--!nonstrict
-- Panel del ecualizador: 10 bandas, preamp, bypass y presets.
--
-- Los valores viven en el preset de EasyEffects y en state.json (para que el
-- servicio los reaplique al arrancar). El socket local de EasyEffects se
-- controla desde bin/eqctl.

local BAND_LABELS = { "31", "62", "125", "250", "500", "1k", "2k", "4k", "8k", "16k" }

local PRESETS = {
  { key = "flat", label = "preset_flat", bands = { 0, 0, 0, 0, 0, 0, 0, 0, 0, 0 }, preamp = 0 },
  { key = "bass", label = "preset_bass", bands = { 6, 5, 4, 2, 0, 0, -1, -2, -3, -4 }, preamp = -3 },
  { key = "vocal", label = "preset_vocal", bands = { -2, -1, 0, 2, 4, 4, 3, 1, 0, -1 }, preamp = -2 },
  { key = "treble", label = "preset_treble", bands = { -3, -2, -1, 0, 0, 1, 2, 4, 5, 6 }, preamp = -2 },
  { key = "loudness", label = "preset_loudness", bands = { 5, 4, 3, 1, 0, -1, 0, 2, 4, 5 }, preamp = -3 },
}

local bands = { 0, 0, 0, 0, 0, 0, 0, 0, 0, 0 }
local preamp = 0.0
local bypass = false
local pipeline = "output"
local preset = "Noctalia EQ"
local ready = false
local loadedPreset = nil
local errorText = ""
local ensuring = false
local startTried = false
local reloadTried = false
local statePath = nil

local render
local refreshStatus

local function tr(key, args)
  return noctalia.tr(key, args)
end

local function loadConfig()
  pipeline = noctalia.getConfig("pipeline") or "output"
  preset = noctalia.getConfig("preset") or "Noctalia EQ"
end

local function ensureStatePath()
  local dir = noctalia.pluginDataDir()
  if dir ~= nil then
    statePath = dir .. "/state.json"
  end
end

local function loadState()
  if statePath == nil then
    return
  end
  local raw = noctalia.readFile(statePath)
  if raw == nil then
    return
  end
  local ok, data = pcall(noctalia.json.decode, raw)
  if not ok or type(data) ~= "table" then
    return
  end
  if type(data.bands) == "table" then
    for i = 1, #BAND_LABELS do
      local value = tonumber(data.bands[i])
      if value ~= nil then
        bands[i] = value
      end
    end
  end
  preamp = tonumber(data.preamp) or preamp
  bypass = data.bypass == true
end

local function saveState()
  if statePath == nil then
    return
  end
  local encoded = noctalia.json.encode({ bands = bands, preamp = preamp, bypass = bypass })
  if encoded ~= nil then
    noctalia.writeFile(statePath, encoded)
  end
end

local function fmt(value)
  return string.format("%+.1f", tonumber(value) or 0)
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

local function errorDetail(result)
  local detail = (result.stderr or ""):gsub("%s+$", "")
  if detail == "" then
    detail = (result.stdout or ""):gsub("%s+$", "")
  end
  return detail
end

local function statusText()
  if not ready then
    return errorText ~= "" and errorText or tr("not_running")
  end
  if loadedPreset ~= preset then
    return tr("wrong_preset", { loaded = tostring(loadedPreset), preset = preset })
  end
  if bypass then
    return tr("bypassed")
  end
  return tr("active", { preset = preset })
end

local function statusColor()
  if not ready then
    return "error"
  end
  if bypass then
    return "on_surface_variant"
  end
  return "primary"
end

local function ensureEq(applyState)
  if ensuring then
    return
  end
  ensuring = true

  local args = { "ensure", "--pipeline", pipeline, "--preset", preset }
  if applyState and statePath ~= nil and noctalia.fileExists(statePath) then
    table.insert(args, "--state")
    table.insert(args, statePath)
  end

  runEqctl(args, function(result)
    ensuring = false
    if result.exitCode ~= 0 then
      ready = false
      errorText = errorDetail(result)
      render()
      return
    end
    refreshStatus()
  end)
end

refreshStatus = function()
  runEqctl({ "status", "--pipeline", pipeline, "--preset", preset }, function(result)
    if result.exitCode ~= 0 then
      ready = false
      errorText = errorDetail(result)
      render()
      return
    end

    local ok, data = pcall(noctalia.json.decode, result.stdout)
    if not ok or type(data) ~= "table" then
      ready = false
      errorText = tr("bad_status")
      render()
      return
    end

    ready = data.running == true
    errorText = ""
    if type(data.bands) == "table" then
      for i = 1, #BAND_LABELS do
        local value = tonumber(data.bands[i])
        if value ~= nil then
          bands[i] = value
        end
      end
    end
    preamp = tonumber(data.preamp) or preamp
    bypass = data.bypass == true
    loadedPreset = data.loaded_preset or data.preset

    if not ready and not startTried then
      startTried = true
      ensureEq(true)
      return
    end
    if ready and loadedPreset ~= preset and not reloadTried then
      reloadTried = true
      ensureEq(false)
      return
    end
    render()
  end)
end

local function setBand(index)
  saveState()
  runEqctl({
    "set-band",
    tostring(index - 1),
    string.format("%.2f", bands[index]),
    "--pipeline",
    pipeline,
    "--preset",
    preset,
  }, function(result)
    if result.exitCode ~= 0 then
      errorText = errorDetail(result)
      noctalia.notifyError(tr("title"), errorText ~= "" and errorText or tr("apply_failed"))
      render()
    else
      ready = true
      errorText = ""
    end
  end)
end

local function setPreamp()
  saveState()
  runEqctl({
    "set-preamp",
    string.format("%.2f", preamp),
    "--pipeline",
    pipeline,
    "--preset",
    preset,
  }, function(result)
    if result.exitCode ~= 0 then
      errorText = errorDetail(result)
      noctalia.notifyError(tr("title"), errorText ~= "" and errorText or tr("apply_failed"))
      render()
    else
      ready = true
      errorText = ""
    end
  end)
end

local function setBypass()
  saveState()
  runEqctl({
    "bypass",
    bypass and "1" or "0",
    "--pipeline",
    pipeline,
    "--preset",
    preset,
  }, function(result)
    if result.exitCode ~= 0 then
      errorText = errorDetail(result)
      noctalia.notifyError(tr("title"), errorText ~= "" and errorText or tr("apply_failed"))
      render()
    else
      ready = true
      errorText = ""
    end
  end)
end

local function applyAll()
  saveState()
  local values = {}
  for i = 1, #BAND_LABELS do
    values[i] = string.format("%.2f", bands[i])
  end
  local args = {
    "apply",
    "--pipeline",
    pipeline,
    "--preset",
    preset,
    "--bands",
    table.concat(values, ","),
    "--preamp",
    string.format("%.2f", preamp),
  }
  if bypass then
    table.insert(args, "--bypass")
  end

  runEqctl(args, function(result)
    if result.exitCode ~= 0 then
      errorText = errorDetail(result)
      noctalia.notifyError(tr("title"), errorText ~= "" and errorText or tr("apply_failed"))
      render()
      return
    end
    ready = true
    errorText = ""
    refreshStatus()
  end)
end

local function applyPreset(presetData)
  for i = 1, #BAND_LABELS do
    bands[i] = presetData.bands[i] or 0
  end
  preamp = presetData.preamp or 0
  bypass = false
  render()
  applyAll()
end

local function resetAll()
  applyPreset(PRESETS[1])
end

local function bandRow(index)
  return ui.row({ key = "band-" .. index, gap = 8, align = "center" }, {
    ui.label({
      text = BAND_LABELS[index],
      width = 46,
      fontSize = 11,
      color = "on_surface_variant",
    }),
    ui.slider({
      key = "slider-" .. index,
      min = -12,
      max = 12,
      step = 0.5,
      value = bands[index],
      flexGrow = 1,
      onChange = function(value)
        bands[index] = tonumber(value) or bands[index]
      end,
      onDragEnd = function()
        setBand(index)
        render()
      end,
    }),
    ui.label({
      text = fmt(bands[index]),
      width = 42,
      fontSize = 11,
      color = "on_surface",
    }),
  })
end

local function presetRow()
  local buttons = {}
  for _, presetData in ipairs(PRESETS) do
    table.insert(buttons, ui.button({
      key = "preset-" .. presetData.key,
      text = tr(presetData.label),
      variant = "secondary",
      controlSize = "sm",
      flexGrow = 1,
      onClick = function()
        applyPreset(presetData)
      end,
    }))
  end
  return ui.row({ gap = 6, align = "center" }, buttons)
end

render = function()
  local rows = {}
  for i = 1, #BAND_LABELS do
    table.insert(rows, bandRow(i))
  end

  panel.render(ui.column({ flexGrow = 1, gap = 10, align = "stretch" }, {
    ui.row({ align = "center", gap = 8 }, {
      ui.glyph({ name = "adjustments-horizontal", size = 18, color = "primary" }),
      ui.label({ text = tr("title"), fontSize = 16, fontWeight = "bold", color = "on_surface", flexGrow = 1 }),
      ui.button({
        key = "open-settings",
        glyph = "settings",
        variant = "ghost",
        tooltip = tr("open_settings"),
        onClick = function()
          noctalia.openSettings()
        end,
      }),
      ui.button({
        key = "close-panel",
        glyph = "close",
        variant = "ghost",
        tooltip = tr("close"),
        onClick = function()
          panel.close()
        end,
      }),
    }),
    ui.row({ align = "center", gap = 8 }, {
      ui.glyph({ name = "circle-filled", size = 10, color = statusColor() }),
      ui.label({
        text = statusText(),
        fontSize = 11,
        color = statusColor(),
        flexGrow = 1,
        maxLines = 2,
      }),
      ui.toggle({
        key = "eq-enabled",
        checked = not bypass,
        onChange = function(value)
          local enabled = value == true or value == "true"
          bypass = not enabled
          saveState()
          setBypass()
          render()
        end,
      }),
    }),
    ui.scroll({ flexGrow = 1, gap = 4 }, rows),
    ui.row({ gap = 8, align = "center" }, {
      ui.label({
        text = tr("preamp"),
        width = 46,
        fontSize = 11,
        color = "on_surface_variant",
      }),
      ui.slider({
        key = "preamp",
        min = -12,
        max = 12,
        step = 0.5,
        value = preamp,
        flexGrow = 1,
        onChange = function(value)
          preamp = tonumber(value) or preamp
        end,
        onDragEnd = function()
          setPreamp()
          render()
        end,
      }),
      ui.label({
        text = fmt(preamp),
        width = 42,
        fontSize = 11,
        color = "on_surface",
      }),
    }),
    presetRow(),
    ui.row({ gap = 8, align = "center" }, {
      ui.button({
        key = "open-easyeffects",
        text = tr("open_easyeffects"),
        glyph = "external-link",
        variant = "ghost",
        controlSize = "sm",
        onClick = function()
          runEqctl({ "open" })
        end,
      }),
      ui.button({
        key = "reset-eq",
        text = tr("reset"),
        glyph = "rotate",
        variant = "ghost",
        controlSize = "sm",
        onClick = resetAll,
      }),
      ui.label({
        text = tr("preset_label", { preset = preset }),
        fontSize = 10,
        color = "on_surface_variant",
        flexGrow = 1,
      }),
    }),
  }))
end

function onOpen(_context)
  ensureStatePath()
  loadConfig()
  loadState()
  ready = false
  loadedPreset = nil
  errorText = ""
  startTried = false
  reloadTried = false
  render()
  refreshStatus()
end

function onClose()
end

function onConfigChanged()
  ensureStatePath()
  loadConfig()
  loadState()
  ready = false
  loadedPreset = nil
  errorText = ""
  startTried = false
  reloadTried = false
  render()
  refreshStatus()
end

function onIpc(event, _payload)
  if event == "refresh" then
    refreshStatus()
  elseif event == "ensure" then
    ensureEq(true)
  elseif event == "reset" then
    resetAll()
  elseif event == "open" then
    runEqctl({ "open" })
  end
end
