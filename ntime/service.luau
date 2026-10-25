--!nonstrict
-- Servicio headless para ntime: asegura que el estado esté disponible
-- y expone comandos IPC para controlar el timer/clock.

local function loadConfig()
  -- Cargar configuración del plugin
  -- No config fija necesaria para ntime, pero aquí por coherencia
end

loadConfig()

function onConfigChanged()
  -- Recargar estado cuando cambian las configuraciones
end

function onIpc(event, payload)
  if event == "set_mode" then
    -- Pasar modo al widget
    noctalia.log("ntime: set_mode=" .. tostring(payload))
  elseif event == "set_font" then
    noctalia.log("ntime: set_font=" .. tostring(payload))
  elseif event == "adjust_timer" then
    -- Ajustar timer
    noctalia.msg("plugin", "noctalia/timer:timer", "start", tostring(payload or 0))
  end
end