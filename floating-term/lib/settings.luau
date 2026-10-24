--!nonstrict
-- Sincronización bidireccional del plugin con settings.toml.
--
-- El panel edita la lista de widgets en su propio store.json (para no
-- disparar la recarga de Noctalia mientras el panel está abierto). Al
-- cerrar el panel, o cuando el usuario abre la página de ajustes, se vuelca
-- el resultado a settings.toml con bin/settings-sync.py para que las dos
-- vistas coincidan.

local util = require("./util.luau")

local M = {}

local PLUGIN_ID = "faminec/floating-term"

function M.sync(commands, layouts, callback)
  local dir = util.pluginPath("")
  if dir == nil then
    if callback ~= nil then
      callback(false)
    end
    return false
  end

  local script = util.pluginPath("bin/settings-sync.py")
  if script == nil then
    if callback ~= nil then
      callback(false)
    end
    return false
  end

  local ok1, encodedCommands = pcall(noctalia.json.encode, commands or {}, true)
  local ok2, encodedLayouts = pcall(noctalia.json.encode, layouts or {}, true)
  if not ok1 or not ok2 or encodedCommands == nil or encodedLayouts == nil then
    if callback ~= nil then
      callback(false)
    end
    return false
  end

  local started = noctalia.runAsync({
    "python3",
    script,
    "commands",
    encodedCommands,
    "layouts",
    encodedLayouts,
  }, function(result)
    if result == nil or result.exitCode ~= 0 then
      if callback ~= nil then
        callback(false)
      end
      return
    end
    if callback ~= nil then
      callback(true)
    end
  end)
  if not started then
    if callback ~= nil then
      callback(false)
    end
    return false
  end
  return true
end

return M