--!nonstrict
-- Utilidades compartidas por los módulos del plugin.

local M = {}

function M.trim(value)
  if value == nil then
    return ""
  end
  return (tostring(value):gsub("^%s+", ""):gsub("%s+$", ""))
end

-- "My Widget!" -> "my-widget". Es la base de la clase de la ventana.
function M.slug(name)
  local result = tostring(name):lower():gsub("[^%w]+", "-")
  result = result:gsub("^%-+", ""):gsub("%-+$", "")
  if result == "" then
    return "app"
  end
  return result
end

function M.classFor(name)
  return "noctalia-term-" .. M.slug(name)
end

function M.shellQuote(value)
  return "'" .. tostring(value):gsub("'", "'\\''") .. "'"
end

-- Cadena Lua entre comillas dobles, para incrustarla en la expresión que
-- recibe `hyprctl dispatch`.
function M.luaQuote(value)
  local escaped = tostring(value)
  escaped = escaped:gsub("\\", "\\\\")
  escaped = escaped:gsub('"', '\\"')
  escaped = escaped:gsub("\r", "\\r")
  escaped = escaped:gsub("\n", "\\n")
  return '"' .. escaped .. '"'
end

function M.clamp(value, low, high)
  if value < low then
    return low
  elseif value > high then
    return high
  end
  return value
end

function M.sortedKeys(map)
  local keys = {}
  for key in pairs(map or {}) do
    table.insert(keys, key)
  end
  table.sort(keys, function(a, b)
    local left = tostring(a):lower()
    local right = tostring(b):lower()
    if left == right then
      return tostring(a) < tostring(b)
    end
    return left < right
  end)
  return keys
end

function M.copyMap(map)
  local out = {}
  for key, value in pairs(map or {}) do
    out[key] = value
  end
  return out
end

function M.contains(list, value)
  for _, item in ipairs(list or {}) do
    if item == value then
      return true
    end
  end
  return false
end

return M
