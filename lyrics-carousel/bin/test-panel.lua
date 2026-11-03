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
  language = "auto",
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
-- El panel se redibuja en cada cambio; algunos callbacks llegan tarde.
local renders = 0
-- Fallos simulados: el volcado de overrides y playerctl.
local failMerge = false
local deferPlayerctl = false
local deferredPlayerctl = nil

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
    renders = renders + 1
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
      -- Un playerctl lento: el callback llega despues de cerrar el panel.
      if argv[1] == "playerctl" and deferPlayerctl and callback ~= nil then
        deferredPlayerctl = callback
        return true
      end
      -- El helper de ajustes es el unico que escribe: se registra.
      if argv[1] == "python3" and argv[2] and argv[2]:match("set%-setting%.py$") then
        local modo = argv[3]
        if modo == "override" then
          if argv[4] == "explode" then
            exitCode = 1
          else
            overrides[argv[4]] = parseValue(argv[5], argv[6])
          end
        elseif modo == "merge" and failMerge then
          exitCode = 1
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

-- Busca un fragmento en cualquier argumento de los procesos lanzados.
local function comandoContiene(fragmento)
  for _, argv in ipairs(commands) do
    for _, value in ipairs(argv) do
      if type(value) == "string" and value:find(fragmento, 1, true) then
        return true
      end
    end
  end
  return false
end

-- Entrega el callback de playerctl que se dejo pendiente.
local function dispararPlayerctlDiferido()
  local callback = deferredPlayerctl
  deferredPlayerctl = nil
  if callback ~= nil then
    callback({ exitCode = 0, stdout = "", stderr = "" })
  end
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
-- Pasar el raton por encima no puede cambiar el ancho. El panel no usa
-- manejadores de hover en ningun sitio, asi que el boton no debe tener
-- ninguno: si algun dia lo tuviera, tendria que ser inocuo (y el
-- aserto de abajo lo comprueba).
check(
  minus == nil or minus.props.onHover == nil,
  "el boton de ancho no define un manejador de hover"
)
if minus ~= nil then
  if minus.props.onHover ~= nil then
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

-- 12. El idioma de la ventana se puede cambiar desde el panel ------------------

local langAuto = findByKey("button", "lang-auto")
local langEn = findByKey("button", "lang-en")
local langEs = findByKey("button", "lang-es")
check(
  langAuto ~= nil and langEn ~= nil and langEs ~= nil,
  "el panel tiene botones para el idioma de la ventana"
)
if langEs ~= nil then
  langEs.props.onClick()
  eq(overrides.language, "es", "elegir español guarda el idioma")
  eq(findByKey("button", "lang-es").props.variant, "secondary", "el idioma elegido queda marcado")
end

-- 13. El boton de vaciar la cache lanza el script con --clear-cache ------------

local clearCache = findByKey("button", "clear-cache")
check(clearCache ~= nil, "el panel tiene un boton para vaciar la cache")
if clearCache ~= nil then
  clearCache.props.onClick()
  local lanzado = false
  for _, argv in ipairs(commands) do
    if argv[#argv] == "--clear-cache" then
      lanzado = true
    end
  end
  check(lanzado, "el boton lanza el script con --clear-cache")
end

-- 14. Un interruptor lee bien un valor que llega como cadena ---------------------
--
-- Noctalia entrega el valor de un interruptor como la cadena "true". Si el
-- panel lo leyera con `== true`, el interruptor se dibujaria apagado aunque
-- el ajuste estuviera encendido.

config.karaoke = "true"
overrides.karaoke = nil
onConfigChanged()
eq(toggleFor("karaoke").props.checked, true, "un \"true\" en la config enciende el interruptor")

config.karaoke = "false"
overrides.karaoke = nil
onConfigChanged()
eq(toggleFor("karaoke").props.checked, false, "un \"false\" en la config apaga el interruptor")

config.karaoke = true
overrides.karaoke = nil
onConfigChanged()
eq(toggleFor("karaoke").props.checked, true, "un booleano true enciende el interruptor")

-- 15. El IPC "toggle" alterna un valor que llega como cadena --------------------
--
-- El widget usa settings.apply para alternar. Si el valor guardado llega como
-- la cadena "true", alternarlo tiene que apagar el interruptor, no dejarlo
-- como estaba.

overrides.footer = nil
config.footer = "true"
settingsModule.refresh()
local alternado = settingsModule.apply("footer", nil)
eq(alternado, false, "alternar un \"true\" lo apaga")
eq(overrides.footer, false, "alternar un \"true\" guarda el apagado")

overrides.footer = nil
config.footer = "false"
settingsModule.refresh()
alternado = settingsModule.apply("footer", nil)
eq(alternado, true, "alternar un \"false\" lo enciende")

-- El panel y el widget tienen que entender los mismos valores: si el panel
-- acepta "1" y el widget no, el IPC "toggle" no haria nada.
overrides.footer = nil
config.footer = "1"
settingsModule.refresh()
alternado = settingsModule.apply("footer", nil)
eq(alternado, false, "alternar un \"1\" lo apaga")
eq(overrides.footer, false, "alternar un \"1\" guarda el apagado")

-- Un ajuste que no es un interruptor no se alterna: no tiene sentido escribir
-- un booleano donde va un numero.
overrides.width = nil
config.width = 1200
settingsModule.refresh()
eq(settingsModule.apply("width", nil), nil, "un numero no se alterna")
eq(overrides.width, nil, "alternar un numero no escribe nada")

config.footer = false
overrides.footer = nil
settingsModule.refresh()

-- 16. Los cinco ajustes que faltaban estan en el panel ----------------------
--
-- El panel tiene que ser un espejo del manifiesto: si un ajuste solo se
-- puede cambiar desde la pagina de ajustes de Noctalia, el usuario cree que
-- el panel esta completo y no lo esta.

overrides = {}
config.anchor = "center"
onConfigChanged()

local function sliderFor(key)
  return findByKey("slider", key)
end

check(sliderFor("spacing") ~= nil, "el panel tiene el control de spacing")
check(sliderFor("animation_ms") ~= nil, "el panel tiene el control de animation_ms")
check(sliderFor("offset_ms") ~= nil, "el panel tiene el control de offset_ms")
check(findByKey("input", "custom_color") ~= nil, "el panel tiene el campo del color")
check(findByKey("input", "glyph") ~= nil, "el panel tiene el campo del glifo")

if sliderFor("spacing") ~= nil then
  sliderFor("spacing").props.onChange("4")
  eq(overrides.spacing, 4, "el control de spacing guarda un entero")
  sliderFor("spacing").props.onChange("2.9")
  eq(overrides.spacing, 2, "el control de spacing trunca a entero")
end

if sliderFor("animation_ms") ~= nil then
  sliderFor("animation_ms").props.onChange("900")
  eq(overrides.animation_ms, 900, "el control de animacion guarda milisegundos")
end

if sliderFor("offset_ms") ~= nil then
  sliderFor("offset_ms").props.onChange("-250")
  eq(overrides.offset_ms, -250, "el control de desfase guarda un negativo")
end

-- Un valor fuera de rango (escrito a mano en el settings.toml, por
-- ejemplo) tiene que verse recortado en el deslizador: si el panel
-- muestra 500 y el script usa 96, los dos no cuentan la misma historia.
config.font_size = 500
overrides.font_size = nil
settingsModule.refresh()
onConfigChanged()
if sliderFor("font_size") ~= nil then
  eq(sliderFor("font_size").props.value, 96, "el deslizador muestra el valor recortado")
end
config.font_size = 22
overrides.font_size = nil
settingsModule.refresh()
onConfigChanged()

local colorInput = findByKey("input", "custom_color")
if colorInput ~= nil then
  colorInput.props.onChange("#12ab34")
  eq(overrides.custom_color, "#12ab34", "un hex valido se guarda")
  colorInput.props.onChange("rojo")
  eq(overrides.custom_color, "#12ab34", "un color invalido no se guarda")
  colorInput.props.onChange("#12AB3")
  eq(overrides.custom_color, "#12ab34", "un hex corto no se guarda")
end

local glyphInput = findByKey("input", "glyph")
if glyphInput ~= nil then
  glyphInput.props.onChange("headphones")
  eq(overrides.glyph, "headphones", "el glifo se guarda")
  glyphInput.props.onChange("Music!")
  eq(overrides.glyph, "headphones", "un glifo invalido no se guarda")
end

-- 17. Los controles numericos respetan el rango del manifiesto --------------
--
-- Un valor fuera de rango deja la ventana fuera de la pantalla o la fuente
-- vacia. Los limites del panel tienen que ser los mismos que los del
-- manifiesto y del script.

check(sliderFor("font_size") ~= nil, "font_size se ajusta con un deslizador")
if sliderFor("font_size") ~= nil then
  eq(sliderFor("font_size").props.min, 6, "font_size empieza en 6")
  eq(sliderFor("font_size").props.max, 96, "font_size acaba en 96")
end
check(sliderFor("visible_above") ~= nil, "visible_above se ajusta con un deslizador")
if sliderFor("visible_above") ~= nil then
  eq(sliderFor("visible_above").props.max, 20, "visible_above acaba en 20")
end
check(sliderFor("active_scale") ~= nil, "active_scale se ajusta con un deslizador")
if sliderFor("active_scale") ~= nil then
  eq(sliderFor("active_scale").props.min, 1.0, "active_scale empieza en 1.0")
  eq(sliderFor("active_scale").props.max, 2.5, "active_scale acaba en 2.5")
end

config.anchor = "custom"
overrides.anchor = nil
overrides.custom_x = nil
onConfigChanged()
local inputX2 = findByKey("input", "custom_x")
check(inputX2 ~= nil, "con posicion personalizada hay campo X para el limite")
if inputX2 ~= nil then
  inputX2.props.onChange("-500")
  check(overrides.custom_x ~= -500, "X no acepta negativos")
  eq(overrides.custom_x, 0, "X recorta el negativo al minimo")
  inputX2.props.onChange("999999")
  check(
    overrides.custom_x == nil or overrides.custom_x <= 10000,
    "X no supera el maximo"
  )
  eq(overrides.custom_x, 10000, "X recorta al maximo")
end
config.anchor = "center"
overrides.anchor = nil
onConfigChanged()

overrides.width = nil
onIpc("set", "width 99999 int")
check(overrides.width == nil or overrides.width <= 3840, "el IPC recorta el ancho al maximo")
eq(overrides.width, 3840, "el IPC recorta el ancho a 3840")

overrides.font_size = nil
onIpc("set", "font_size 999 int")
eq(overrides.font_size, 96, "el IPC recorta el tamano de fuente a 96")

overrides.active_scale = nil
onIpc("set", "active_scale 9.5 float")
eq(overrides.active_scale, 2.5, "el IPC recorta la escala activa a 2.5")

-- 18. La ventana no puede ser mayor que la pantalla -------------------------
--
-- Hyprland acepta un tamano mayor que el monitor, pero la ventana queda
-- cortada y el usuario no puede moverla. El panel recorta antes de lanzar.

config.width = 3840
config.height = 2160
overrides.width = nil
overrides.height = nil
onConfigChanged()
commands = {}
local launchButton = findByKey("button", "launch")
check(launchButton ~= nil, "el panel tiene el boton de lanzar")
if launchButton ~= nil then
  launchButton.props.onClick()
  check(
    comandoContiene("size = { 1920, 1080 }"),
    "el tamano se recorta a la pantalla"
  )
end

-- 19. Cambiar el tamano por IPC mueve la ventana ----------------------------
--
-- Si el IPC solo guarda el ajuste, la ventana abierta mantiene el tamano
-- viejo hasta que se vuelve a lanzar.

config.width = 1200
config.height = 820
overrides.width = nil
overrides.height = nil
onConfigChanged()
commands = {}
onIpc("set", "width 1600 int")
check(comandoContiene("hl.dsp.window"), "el IPC de tamano aplica la geometria")

-- 20. Un fallo del volcado avisa al usuario ---------------------------------
--
-- Si el helper no puede escribir el settings.toml, el usuario tiene que
-- enterarse: el cambio se queda solo en la capa de overrides.

failMerge = true
notified = {}
onClose()
check(#notified > 0, "si el volcado falla, el panel avisa")

-- 21. Un callback tras cerrar no vuelve a dibujar ---------------------------
--
-- playerctl puede tardar mas que el panel. Al llegar su callback, el panel
-- ya esta cerrado y dibujar sobre el arbol muerto da error en Noctalia.

deferPlayerctl = true
onOpen()
local rendersAntes = renders
onClose()
dispararPlayerctlDiferido()
eq(renders, rendersAntes, "no se redibuja un panel cerrado")

-- 22. El widget lee la capa de overrides ---------------------------------
--
-- El panel escribe el glifo en los overrides y los vuelca al cerrarse; si
-- el widget solo mirara la configuracion, el icono de la barra no cambiaria
-- hasta entonces (y el panel dice que se aplica en el acto).

local glyphUsado = nil
barWidget = {
  setGlyph = function(name) glyphUsado = name end,
  setTooltip = function(text) end,
}
config.glyph = "music"
overrides = {}
settingsModule.refresh()
dofile(pluginDir .. "/widget.luau")
eq(glyphUsado, "music", "el widget usa el glifo de la configuracion")

overrides.glyph = "volume"
settingsModule.refresh()
update()
eq(glyphUsado, "volume", "el widget usa el glifo de los overrides")

-- 23. Todo el texto visible pasa por las traducciones ----------------------
--
-- Un placeholder es texto visible: si va escrito a mano, el panel enseña
-- "music" o "#rrggbb" en cualquier idioma y el revisor de la tienda lo
-- marca como texto sin traducir. El mock de tr devuelve la clave, asi que
-- se comprueba que el placeholder es una clave y no un literal.

local glyphInput = findByKey("input", "glyph")
if glyphInput ~= nil then
  eq(glyphInput.props.placeholder, "glyph_placeholder", "el placeholder del glifo pasa por la traduccion")
end

local colorInput = findByKey("input", "custom_color")
if colorInput ~= nil then
  eq(colorInput.props.placeholder, "color_placeholder", "el placeholder del color pasa por la traduccion")
end

-- 24. La fuente se puede escribir ------------------------------------------
--
-- El manifiesto declara la fuente como texto libre: los chips son solo
-- atajos y, sin un campo, no se podria elegir una fuente que no este en
-- la lista.

local familyInput = findByKey("input", "font_family")
check(familyInput ~= nil, "font_family se puede escribir")
if familyInput ~= nil then
  familyInput.props.onChange("Iosevka")
  eq(overrides.font_family, "Iosevka", "el campo de font_family guarda la familia escrita")
end

-- 25. El panel ofrece los rangos del manifiesto -----------------------------
--
-- El manifiesto es la fuente de verdad. Si el panel ofrece un deslizador
-- de 6 a 120 y el manifiesto dice 6 a 96, el usuario puede elegir un valor
-- que el script va a descartar. Este test lee los limites del manifiesto y
-- los compara con los controles que el panel dibuja de verdad (no con el
-- codigo fuente).

local function manifestLimits(path)
  local limites = {}
  local file = io.open(path, "r")
  if file == nil then
    return nil
  end
  local clave, minimo, maximo
  local function cerrar()
    if clave and minimo and maximo then
      limites[clave] = { min = tonumber(minimo), max = tonumber(maximo) }
    end
    clave, minimo, maximo = nil, nil, nil
  end
  for linea in file:lines() do
    local texto = linea:match("^%s*(.-)%s*$")
    if texto == "[[setting]]" then
      cerrar()
    else
      local k = texto:match('^key%s*=%s*"([^"]+)"')
      if k then
        clave = k
      end
      local mn = texto:match("^min%s*=%s*(%-?%d+%.?%d*)")
      if mn then
        minimo = mn
      end
      local mx = texto:match("^max%s*=%s*(%-?%d+%.?%d*)")
      if mx then
        maximo = mx
      end
    end
  end
  cerrar()
  file:close()
  return limites
end

-- Con la posicion personalizada se ven tambien los campos X e Y. El panel
-- se abre otra vez porque en el apartado 21 se cerro (y un panel cerrado
-- no vuelve a dibujar). La posicion se cambia por su desplegable (la via
-- real del usuario) para que la tabla interna del panel quede coherente.
onOpen()
local anchorSelect = findByKey("select", "anchor-select")
check(anchorSelect ~= nil, "el panel tiene el desplegable de posicion")
if anchorSelect ~= nil then
  anchorSelect.props.onChange("9")
end
eq(overrides.anchor, "custom", "la posicion personalizada queda elegida")
settingsModule.refresh()
onConfigChanged()

local limites = manifestLimits(pluginDir .. "/plugin.toml")
check(limites ~= nil and next(limites) ~= nil, "el manifiesto declara limites")
if limites ~= nil then
  for clave, limite in pairs(limites) do
    local control = findByKey("slider", clave)
    if control ~= nil then
      eq(
        control.props.min,
        limite.min,
        "el deslizador de " .. clave .. " empieza en el minimo del manifiesto"
      )
      eq(
        control.props.max,
        limite.max,
        "el deslizador de " .. clave .. " acaba en el maximo del manifiesto"
      )
      check(
        control.props.step ~= nil and control.props.step > 0,
        "el deslizador de " .. clave .. " tiene paso"
      )
    elseif findByKey("input", clave) ~= nil then
      -- Los campos de texto (las coordenadas) no llevan rango visible: el
      -- recorte lo hace la libreria al escribir.
    elseif findByKey("button", clave .. "-dec") ~= nil then
      -- Los contadores +/- no llevan rango en sus props: se comprueba que
      -- no bajan del minimo que declara el manifiesto.
      config[clave] = limite.min
      overrides[clave] = nil
      settingsModule.refresh()
      onConfigChanged()
      local boton = findByKey("button", clave .. "-dec")
      if boton ~= nil then
        boton.props.onClick()
      end
      check(
        overrides[clave] == nil or overrides[clave] >= limite.min,
        "el contador de " .. clave .. " no baja del minimo del manifiesto"
      )
    else
      check(false, "el panel no tiene ningun control para " .. clave)
    end
  end
end

-- Resultado ------------------------------------------------------------------

if failures > 0 then
  io.stderr:write(string.format("%d de %d comprobaciones fallaron\n", failures, checks))
  os.exit(1)
end
print(string.format("%d comprobaciones correctas", checks))
