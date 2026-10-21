--!nonstrict
-- Icono de barra: abre/cierra el panel del ecualizador.

local glyph = noctalia.getConfig("glyph") or "adjustments-horizontal"

local function render()
  barWidget.setGlyph(glyph)
  barWidget.setTooltip(noctalia.tr("tooltip"))
end

function update()
  glyph = noctalia.getConfig("glyph") or "adjustments-horizontal"
  render()
end

function onClick()
  noctalia.togglePanel("faminec/equalizer:panel")
end

function onConfigChanged()
  update()
end
