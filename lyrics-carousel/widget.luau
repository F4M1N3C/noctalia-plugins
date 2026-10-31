--!nonstrict
-- Widget de barra del carrusel de letras.
--
-- Ademas de abrir el panel, acepta IPC para cambiar ajustes sin abrirlo
-- (util para atajos de teclado):
--   noctalia msg plugin faminec/lyrics-carousel:widget all set visible_above 4 int
--   noctalia msg plugin faminec/lyrics-carousel:widget all toggle karaoke

local settings = require("./lib/settings.luau")

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
  render()
end

function onIpc(event, payload)
  if event == "launch" then
    noctalia.togglePanel("faminec/lyrics-carousel:panel")
  elseif event == "set" then
    local key, value = settings.parse(payload)
    if key ~= nil then
      settings.apply(key, value)
    end
  elseif event == "toggle" then
    -- Solo se alternan los interruptores: alternar un numero no tiene sentido.
    if type(payload) == "string" and settings.BOOL_KEYS[payload] then
      settings.apply(payload, nil)
    end
  elseif event == "refresh" then
    render()
  end
end

render()
