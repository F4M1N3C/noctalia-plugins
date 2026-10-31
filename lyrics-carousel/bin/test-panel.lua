-- Pruebas de regresión de panel.luau, ejecutables con Lua 5.4.
--
-- El panel es Lua/Luau puro: solo habla con el shell a través de los globales
-- `noctalia`, `panel` y `ui`. Aquí se simulan esos globales para cargar la
-- entrada y manejarla como lo haría Noctalia: abrir, pulsar, cambiar un
-- ajuste. Después se mira el árbol que se ha dibujado.
--
-- Los ajustes que el panel cambia se acumulan en `overrides` (la capa que el
-- panel escribe y el script lee), así que las comprobaciones miran lo que
-- de verdad se ha guardado y no solo lo que se ve en pantalla.
--
-- Uso: lua5.4 bin/test-panel.lua panel.luau

local panelPath = arg[1] or "panel.luau"
local pluginDir = panelPath:match("^(.*)/[^/]+$") or "."

local checks = 0
local failures = 0

local function check(condition, message)
  checks = checks + 1
  if not condition then
    failures = failures + 1
    io.stderr:write("FALLO: " .. message .. "\n")
  end
end

local function eq(actual, expected, message)
  check(
    actual == expected,
    string.format("%s (obtenido %s, esperado %s)", message, tostring(actual), tostring(expected))
  )
end

-- Simulación del shell ------------------------------------------------------

-- Configuracion inicial (lo que hay en el settings.toml).
local config = {
  font_family = "Departure Mono",
  font_size = 22,
  render_mode = "text",
  direction = "down",
  marker = false,
  karaoke = true,
  equalizer = false,
  footer = false,
  hints = false,
  header = false,
  spacing = 2,
  animation_ms = 650,
  ghost = true,
  offset_ms = 0,
  width = 1200,
  height = 820,
  anchor = "center",
  custom_x = 100,
  custom_y = 100,
  accent = "primary",
  custom_color = "#e46767",
  active_scale = 1.35,
  visible_above = 6,
  visible_below = 6,
}

-- Capa de overrides: lo que el panel ha escrito.
local overrides = {}
-- Lecturas del fichero de overrides (para comprobar la cache).
local reads = 0
-- Procesos que el panel ha lanzado.
local commands = {}
local tree = nil
local closed = false
local notified = {}

local function parseValue(value, kind)
  if kind == "bool" then
    return value == "true" or value == "1"
  elseif kind == "int" then
    return math.floor(tonumber(value) or 0)
  elseif kind == "float" then
    return tonumber(value) or 0
  end
  return value
end

local function node(kind)
  return function(props, children)
    return { kind = kind, props = props or {}, children = children or {} }
  end
end

ui = {
  column = node("column"),
  row = node("row"),
  scroll = node("scroll"),
  label = node("label"),
  separator = node("separator"),
  spacer = node("spacer"),
  button = node("button"),
  glyph = node("glyph"),
  toggle = node("toggle"),
  select = node("select"),
  input = node("input"),
  slider = node("slider"),
}

panel = {
  close = function()
    closed = true
  end,
  render = function(nextTree)
    tree = nextTree
  end,
  setNeedsFrameTick = function() end,
}

noctalia = {
  tr = function(key)
    return key
  end,
  getenv = function()
    return "/home/tester"
  end,
  getConfig = function(key)
    return config[key]
  end,
  getSetting = function()
    return nil
  end,
  pluginDataDir = function()
    return "/tmp/lyrics-carousel-selftest/data"
  end,
  pluginDir = function()
    return "/tmp/lyrics-carousel-selftest/plugin"
  end,
  readFile = function()
    reads = reads + 1
    return "{}"
  end,
  writeFile = function()
    return true
  end,
  fileExists = function()
    return false
  end,
  mkdirAll = function()
    return true
  end,
  json = {
    encode = function()
      return "{}"
    end,
    decode = function()
      -- El shell devuelve el contenido del overrides.json.
      local copy = {}
      for key, value in pairs(overrides) do
        copy[key] = value
      end
      return copy
    end,
  },
  outputs = function()
    return { { name = "DP-1", width = 1920, height = 1080, focused = true } }
  end,
  openSettings = function() end,
  notify = function(title, body)
    table.insert(notified, { title = title, body = body })
  end,
  notifyError = function(title, body)
    table.insert(notified, { title = title, body = body })
  end,
  log = function() end,
  runAsync = function(argv, callback)
    local exitCode = 0
    if type(argv) == "table" then
      table.insert(commands, argv)
      -- El helper de ajustes es el unico que escribe: se registra.
      if argv[1] == "python3" and argv[2] and argv[2]:match("set%-setting%.py$") then
        local modo = argv[3]
        if modo == "override" then
          if argv[4] == "explode" then
            exitCode = 1
          else
            overrides[argv[4]] = parseValue(argv[5], argv[6])
          end
        end
      end
    end
    if callback then
      callback({ exitCode = exitCode, stdout = "", stderr = exitCode == 0 and "" or "boom" })
    end
    return true
  end,
}

-- `require` relativo: Noctalia lo resuelve desde el directorio de la entrada.
local settingsModule = nil
require = function(name)
  local relative = name:gsub("^%./", ""):gsub("%.luau$", "")
  local module = dofile(pluginDir .. "/" .. relative .. ".luau")
  if relative:match("settings") then
    settingsModule = module
  end
  return module
end

dofile(panelPath)

-- Ayudas sobre el árbol -----------------------------------------------------

local function collect(current, kind, result)
  result = result or {}
  if type(current) ~= "table" then
    return result
  end
  if current.kind == kind then
    table.insert(result, current)
  end
  for _, child in ipairs(current.children or {}) do
    collect(child, kind, result)
  end
  return result
end

local function findByKey(kind, key)
  for _, node in ipairs(collect(tree, kind)) do
    if node.props.key == key then
      return node
    end
  end
  return nil
end

-- El interruptor cuyo texto de etiqueta es `label`.
local function toggleFor(label)
  for _, row in ipairs(collect(tree, "row")) do
    for _, child in ipairs(row.children or {}) do
      if child.kind == "label" and child.props.text == label then
        for _, sibling in ipairs(row.children or {}) do
          if sibling.kind == "toggle" then
            return sibling
          end
        end
      end
    end
  end
  return nil
end

-- El numero que se ve junto a un boton de tamano.
local function stepperValue(buttonKey)
  for _, row in ipairs(collect(tree, "row")) do
    local hasButton = false
    for _, child in ipairs(row.children or {}) do
      if child.kind == "button" and child.props.key == buttonKey then
        hasButton = true
      end
    end
    if hasButton then
      for _, child in ipairs(row.children or {}) do
        if child.kind == "label" then
          return tonumber(child.props.text)
        end
      end
    end
  end
  return nil
end

local function firstSelect()
  return collect(tree, "select")[1]
end

onOpen()

-- 1. Los interruptores se encienden y se apagan -----------------------------

local TOGGLES = {
  "karaoke",
  "marker",
  "header",
  "footer",
  "hints",
  "equalizer",
  "ghost",
}

for _, name in ipairs(TOGGLES) do
  local toggle = toggleFor(name)
  check(toggle ~= nil, "el panel tiene un interruptor para " .. name)
  if toggle ~= nil then
    -- Noctalia entrega el valor como cadena: "true" / "false".
    toggle.props.onChange("true")
    eq(toggleFor(name).props.checked, true, "el interruptor " .. name .. " se enciende")
    eq(overrides[name], true, "el interruptor " .. name .. " guarda el valor")
    toggleFor(name).props.onChange("false")
    eq(toggleFor(name).props.checked, false, "el interruptor " .. name .. " se apaga")
    eq(overrides[name], false, "el interruptor " .. name .. " guarda el apagado")
  end
end

-- 2. El desplegable de posicion usa indices de base 0 ------------------------

local select = firstSelect()
check(select ~= nil, "el panel tiene un desplegable de posicion")
if select ~= nil then
  eq(#select.props.options, 10, "el desplegable tiene las 10 posiciones")
  -- El valor por defecto es "center", la quinta opcion (indice 4).
  eq(select.props.selectedIndex, 4, "el desplegable marca la posicion actual")

  select.props.onChange("0")
  eq(overrides.anchor, "top-left", "elegir la primera opcion guarda top-left")
  eq(firstSelect().props.selectedIndex, 0, "el desplegable marca la primera opcion")

  select.props.onChange("9")
  eq(overrides.anchor, "custom", "elegir la ultima opcion guarda custom")
end

-- 3. Un valor escrito a mano se normaliza -----------------------------------

config.anchor = "centro"
overrides.anchor = nil
onConfigChanged()
eq(firstSelect().props.selectedIndex, 4, "un ancla en Castellano se marca como center")
config.anchor = "center"
onConfigChanged()

-- 4. Pasar el raton por los botones de tamano no cambia nada ----------------

config.width = 1200
overrides.width = nil
onConfigChanged()
local minus = findByKey("button", "width-dec")
check(minus ~= nil, "el panel tiene un boton para restar ancho")
if minus ~= nil then
  if minus.props.onHover then
    minus.props.onHover("true")
    minus.props.onHover("false")
  end
  eq(overrides.width, nil, "hover no cambia el ancho")
  eq(stepperValue("width-dec"), 1200, "hover no cambia el ancho que se ve")
  minus.props.onClick()
  eq(overrides.width, 1100, "un clic resta 100 al ancho")
  eq(stepperValue("width-dec"), 1100, "se ve el ancho nuevo")
  local plus = findByKey("button", "width-inc")
  plus.props.onClick()
  eq(overrides.width, 1200, "un clic suma 100 al ancho")
end

-- 5. Los campos X/Y solo aparecen con la posicion personalizada --------------

config.anchor = "center"
overrides.anchor = nil
onConfigChanged()
check(findByKey("input", "custom_x") == nil, "sin posicion personalizada no hay campo X")
check(findByKey("input", "custom_y") == nil, "sin posicion personalizada no hay campo Y")

config.anchor = "custom"
onConfigChanged()
local inputX = findByKey("input", "custom_x")
local inputY = findByKey("input", "custom_y")
check(inputX ~= nil, "con posicion personalizada hay campo X")
check(inputY ~= nil, "con posicion personalizada hay campo Y")
if inputX ~= nil then
  inputX.props.onChange("250")
  eq(overrides.custom_x, 250, "el campo X guarda la coordenada")
  -- Un valor que no es un numero no cambia nada.
  inputX.props.onChange("abc")
  eq(overrides.custom_x, 250, "el campo X ignora lo que no es un numero")
end
config.anchor = "center"
overrides.anchor = nil
onConfigChanged()

-- 6. Los campos de texto tienen clave estable --------------------------------

for _, node in ipairs(collect(tree, "input")) do
  check(type(node.props.key) == "string", "todo campo de texto tiene clave estable")
end

-- 7. Un IPC sin token de tipo deduce el tipo de la clave ---------------------

overrides.karaoke = nil
onIpc("set", "karaoke true")
eq(overrides.karaoke, true, "un IPC sin tipo guarda un booleano")
eq(toggleFor("karaoke").props.checked, true, "el interruptor refleja el IPC")

overrides.marker = nil
onIpc("set", "marker true bool")
eq(overrides.marker, true, "un IPC con tipo guarda un booleano")

overrides.visible_above = nil
onIpc("set", "visible_above 4")
eq(overrides.visible_above, 4, "un IPC sin tipo guarda un numero")

-- 8. El IPC "toggle" alterna un interruptor ---------------------------------

overrides.footer = nil
onIpc("toggle", "footer")
eq(overrides.footer, true, "toggle enciende un interruptor apagado")
onIpc("toggle", "footer")
eq(overrides.footer, false, "toggle apaga un interruptor encendido")

-- 9. La escritura avisa de si ha ido bien ------------------------------------

local resultado = nil
settingsModule.write("marker", true, function(ok)
  resultado = ok
end)
eq(resultado, true, "una escritura correcta avisa del resultado")

resultado = nil
settingsModule.write("explode", true, function(ok)
  resultado = ok
end)
eq(resultado, false, "una escritura que falla avisa del fallo")

-- 10. Un valor que parece un tipo no se consume como token -------------------

overrides.font_family = nil
onIpc("set", "font_family string")
eq(overrides.font_family, "string", "un valor con nombre de tipo se guarda entero")

-- 11. Los overrides se cachean -----------------------------------------------

settingsModule.refresh()
reads = 0
settingsModule.value("karaoke")
local lecturas = reads
check(lecturas > 0, "la primera lectura lee el fichero de overrides")
settingsModule.value("marker")
settingsModule.value("footer")
settingsModule.value("width")
eq(reads, lecturas, "las siguientes lecturas usan la cache")

-- Resultado ------------------------------------------------------------------

if failures > 0 then
  io.stderr:write(string.format("%d de %d comprobaciones fallaron\n", failures, checks))
  os.exit(1)
end
print(string.format("%d comprobaciones correctas", checks))
