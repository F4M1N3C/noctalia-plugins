--!nonstrict
-- Botón de barra: abre/cierra el carrusel de fondos.

local glyph = noctalia.getConfig("glyph") or "wallpaper"
local isOpen = false

local function render()
  barWidget.setGlyph(glyph)
  barWidget.setTooltip(noctalia.tr(isOpen and "tooltip_close" or "tooltip"))
end

function update()
  local nextGlyph = noctalia.getConfig("glyph") or "wallpaper"
  if nextGlyph ~= glyph then
    glyph = nextGlyph
    render()
  end
end

function onClick()
  noctalia.togglePanel("faminec/wallpaper-carousel:panel")
end

function onConfigChanged()
  glyph = noctalia.getConfig("glyph") or "wallpaper"
  render()
end

noctalia.state.watch("carousel.open", function(value)
  isOpen = value == true
  render()
end)

render()
