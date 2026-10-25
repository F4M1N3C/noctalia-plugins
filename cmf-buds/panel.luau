--!nonstrict
-- Panel unico de control de los CMF Buds Pro 2. Las secciones son pestañas
-- internas, asi la posicion del panel se mantiene al cambiar de seccion y hay
-- una sola opcion global de posicion/capa.

local C = require("./lib/common.luau")
local P = require("./lib/panel_ui.luau")

local PANEL = "faminec/cmf-buds:panel"

function onOpen(context)
  P.setup(C.last_tab(), PANEL, 1000)
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

function onFrameTick(deltaMs)
  P.onFrameTick(deltaMs)
end