--!nonstrict
-- Botón de barra: abre/cierra el panel del carrusel de letras.

local glyph = noctalia.getConfig("glyph") or "music"

local function render()
  barWidget.setGlyph(glyph)
  barWidget.setTooltip(noctalia.tr("tooltip"))
end

function update()
  glyph = noctalia.getConfig("glyph") or "music"
  render()
end

function onClick()
  noctalia.togglePanel("faminec/lyrics-carousel:panel")
end

function onConfigChanged()
  glyph = noctalia.getConfig("glyph") or "music"
  render()
end

render()
