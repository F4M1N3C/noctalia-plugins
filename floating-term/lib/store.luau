--!nonstrict
-- Almacén propio del plugin.
--
-- Noctalia guarda los ajustes `string_map` como una tabla que *reemplaza* al
-- valor por defecto del manifiesto: al añadir una entrada desde Ajustes, las
-- demás desaparecen. Por eso el plugin no usa esos mapas como única fuente de
-- verdad, sino como una capa más:
--
--   defaults (plugin.toml)  ⊕  config (Ajustes)  ⊕  store (este panel)
--   −  removed (borrados desde el panel)
--
-- Así se puede añadir un widget sin perder los que ya estaban y se pueden
-- borrar también los que vienen por defecto.

local util = require("./util.luau")

local M = {}

local function emptyStore()
  return { commands = {}, layouts = {}, removed = {} }
end

function M.path()
  local dir = noctalia.pluginDataDir()
  if dir == nil then
    return nil
  end
  return dir .. "/store.json"
end

function M.load()
  local store = emptyStore()
  local path = M.path()
  if path == nil then
    return store
  end

  local raw = noctalia.readFile(path)
  if raw == nil or raw == "" then
    return store
  end

  local ok, decoded = pcall(noctalia.json.decode, raw)
  if not ok or type(decoded) ~= "table" then
    noctalia.log("floating-term: store.json ilegible, se empieza de cero")
    return store
  end

  if type(decoded.commands) == "table" then
    for key, value in pairs(decoded.commands) do
      if type(value) == "string" then
        store.commands[key] = value
      end
    end
  end
  if type(decoded.layouts) == "table" then
    for key, value in pairs(decoded.layouts) do
      if type(value) == "string" then
        store.layouts[key] = value
      end
    end
  end
  if type(decoded.removed) == "table" then
    for _, value in ipairs(decoded.removed) do
      if type(value) == "string" then
        table.insert(store.removed, value)
      end
    end
  end

  return store
end

function M.save(store)
  local path = M.path()
  if path == nil then
    return false, "sin directorio de datos"
  end

  local ok, encoded = pcall(noctalia.json.encode, store, true)
  if not ok or encoded == nil then
    return false, "no se pudo serializar"
  end

  local wrote = noctalia.writeFile(path, encoded)
  if wrote ~= true then
    return false, "no se pudo escribir " .. path
  end
  return true
end

-- Fusiona las tres capas y aplica los borrados.
function M.merge(base, configMap, storeMap, removed)
  local out = {}

  for key, value in pairs(base or {}) do
    if type(value) == "string" and value ~= "" then
      out[key] = value
    end
  end
  for key, value in pairs(configMap or {}) do
    if type(value) == "string" and value ~= "" then
      out[key] = value
    end
  end
  for key, value in pairs(storeMap or {}) do
    if type(value) == "string" and value ~= "" then
      out[key] = value
    end
  end
  for _, key in ipairs(removed or {}) do
    out[key] = nil
  end

  return out
end

-- Marca un widget como borrado (tombstone) y lo quita del store.
function M.remove(store, name)
  if not util.contains(store.removed, name) then
    table.insert(store.removed, name)
  end
  store.commands[name] = nil
  store.layouts[name] = nil
end

-- Añade o actualiza un widget.
function M.upsert(store, name, command, layout)
  local index = nil
  for position, value in ipairs(store.removed) do
    if value == name then
      index = position
      break
    end
  end
  if index ~= nil then
    table.remove(store.removed, index)
  end

  if command ~= nil and command ~= "" then
    store.commands[name] = command
  end
  if layout ~= nil and layout ~= "" then
    store.layouts[name] = layout
  end
end

return M
