--!nonstrict
-- Pestaña "controls" del panel de control de los CMF Buds Pro 2.
-- Cada pestaña es un panel propio para que la ventana se ajuste al contenido.

local P = require("./lib/panel_ui.luau")

local TAB = "controls"
local PANEL = "faminec/cmf-buds:panel-controls"

function onOpen(context)
  P.setup(TAB, PANEL)
  P.onOpen(context)
end

function onClose()
  P.onClose()
end

function update()
  P.update()
end

function onConfigChanged()
  P.onConfigChanged()
end

function onIpc(event, payload)
  P.onIpc(event, payload)
end
