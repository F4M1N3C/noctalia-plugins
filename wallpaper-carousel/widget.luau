--!nonstrict
-- Botón de barra: abre/cierra el carrusel de fondos.

local glyph = noctalia.getConfig("glyph") or "wallpaper"
local isOpen = false

-- El manifiesto declara dos entradas con el mismo panel: `panel` pegada a la
-- barra y `panel_floating` como ventana suelta. El ajuste decide cual se abre.
local function panelId()
  local mode = noctalia.getConfig("panel_mode") or "attached"
  if mode == "floating" then
    return "faminec/wallpaper-carousel:panel_floating"
  end
  return "faminec/wallpaper-carousel:panel"
end

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
  noctalia.togglePanel(panelId())
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
