--!nonstrict
-- Widget de la barra: estado del puente entre el computador y el celular.
--
--   * verde  : el celular esta conectado al servidor
--   * ambar  : hay mensajes en cola para el celular
--   * gris   : el celular no esta conectado
--   * rojo   : el servidor de notas no responde

local PANEL_ID = "faminec/notes-sync:panel"

local function tr(key, params)
  if params ~= nil then
    return noctalia.tr(key, params)
  end
  return noctalia.tr(key)
end

local function render()
  local glyph = noctalia.getConfig("glyph") or "notes"
  barWidget.setGlyph(glyph)

  local sync = noctalia.state.get("notes_sync") or {}
  local serverUp = sync.serverUp == true
  local connected = sync.phoneConnected == true
  local pending = tonumber(sync.pending) or 0

  local color = "on_surface_variant"
  if not serverUp then
    color = "error"
  elseif pending > 0 then
    color = "warning"
  elseif connected then
    color = "primary"
  end

  barWidget.setGlyphColor(color)
  if type(barWidget.setColor) == "function" then
    barWidget.setColor(if color == "error" or color == "primary" then color else "")
  end

  local showText = noctalia.getConfig("show_text") == true
  if showText then
    if not serverUp then
      barWidget.setText("!")
    elseif pending > 0 then
      barWidget.setText(tostring(pending))
    elseif connected then
      barWidget.setText("on")
    else
      barWidget.setText("off")
    end
  else
    barWidget.setText("")
  end

  local tip
  if not serverUp then
    tip = tr("tooltip_offline")
  elseif pending > 0 then
    tip = tr("tooltip_pending", { count = pending })
  elseif connected then
    tip = tr("tooltip_online")
  else
    tip = tr("tooltip_disconnected")
  end
  barWidget.setTooltip(tip)
end

function update()
  render()
end

function onClick()
  noctalia.togglePanel(PANEL_ID)
end

-- Se redibuja cuando cambia el estado publicado por el servicio.
noctalia.state.watch("notes_sync", function()
  render()
end)

render()
