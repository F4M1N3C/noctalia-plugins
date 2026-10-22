-- Banco de pruebas del plugin `faminec/floating-term` (módulos `lib/`).
--
-- Se cargan los módulos con un API de Noctalia simulado para comprobar la
-- lógica sin depender del escritorio: fusión de la lista de widgets,
-- tombstones, parser del manifiesto, parser de posiciones, zonas ocupadas y
-- las permutaciones de la rotación.
--
--   lua5.4 test-panel.lua              # prueba la copia de este repo
--   lua5.4 test-panel.lua /ruta/otros  # prueba otra copia (la instalada)
--
-- Sale con código distinto de 0 si algún caso falla.

local function scriptDir()
  local self = arg and arg[0] or ""
  return self:match("^(.*)[/\\][^/\\]+$") or "."
end

local DIR = (arg and arg[1]) or (scriptDir() .. "/")
if DIR:sub(-1) ~= "/" then
  DIR = DIR .. "/"
end

local failures = 0
local checks = 0

local function check(name, got, want)
  checks = checks + 1
  if got ~= want then
    failures = failures + 1
    print(string.format("FAIL  %s\n      esperado: %s\n      obtenido: %s", name, tostring(want), tostring(got)))
  else
    print(string.format("ok    %s", name))
  end
end

local function checkTrue(name, value)
  check(name, value and true or false, true)
end

-- ---------------------------------------------------------------- entorno --

local files = {}
local dirs = {}

local fakeNoctalia = {
  getConfig = function() return nil end,
  pluginDir = function() return DIR end,
  pluginDataDir = function() return "/tmp/opencode/testdata" end,
  readFile = function(path)
    return files[path]
  end,
  writeFile = function(path, content)
    files[path] = content
    return true
  end,
  mkdirAll = function() return true end,
  listDir = function() return {} end,
  removeFile = function(path)
    files[path] = nil
    return true
  end,
  fileExists = function(path)
    return files[path] ~= nil
  end,
  json = {
    encode = function(value)
      -- JSON mínimo: solo nos importa que vuelva algo no vacío.
      return "{\"ok\":true}"
    end,
    decode = function(text)
      return { commands = { prueba = "echo" }, layouts = {}, removed = { "pipes" } }
    end,
  },
  log = function() end,
}

local env = {
  noctalia = fakeNoctalia,
  math = math,
  string = string,
  table = table,
  os = os,
  tonumber = tonumber,
  tostring = tostring,
  type = type,
  pairs = pairs,
  ipairs = ipairs,
  next = next,
  pcall = pcall,
  error = error,
  print = print,
  setmetatable = setmetatable,
  getmetatable = getmetatable,
  rawget = rawget,
  rawset = rawset,
  select = select,
  unpack = table.unpack,
}
-- (se asigna después: dentro del constructor `env` todavía no existe)
env.require = function(path)
  local name = path:match("([^/]+)$")
  local chunk = assert(loadfile(DIR .. "lib/" .. name, "t", env))
  return chunk()
end

local function load(name)
  local chunk = assert(loadfile(DIR .. name, "t", env))
  return chunk()
end

local util = load("lib/util.luau")
local store = load("lib/store.luau")
local layout = load("lib/layout.luau")
local defaults = load("lib/defaults.luau")
local win = load("lib/windows.luau")

print("== utilidades ==")
check("slug", util.slug("Mi Widget!"), "mi-widget")
check("slug vacío", util.slug("!!!"), "app")
check("clase", util.classFor("Cava"), "noctalia-term-cava")
check("trim", util.trim("  hola  "), "hola")

print("\n== fusión de widgets ==")
local base = { a = "a-cmd", b = "b-cmd" }
local config = { b = "b-cmd-editado", c = "c-cmd" }
local storeMap = { d = "d-cmd" }
local removed = { "a" }

local merged = store.merge(base, config, storeMap, removed)
check("default que no está en la config", merged.a, nil)
check("default quitado por tombstone", merged.a, nil)
check("la config pisa al default", merged.b, "b-cmd-editado")
check("entrada nueva de la config", merged.c, "c-cmd")
check("entrada nueva del store", merged.d, "d-cmd")

local merged2 = store.merge({ a = "a", b = "b" }, { c = "c" }, {}, {})
check("sin tombstone se conserva el default", merged2.a, "a")
check("valor vacío se ignora", store.merge({ a = "x" }, { a = "" }, {}, {}).a, "x")
check("valor vacío del store se respeta", store.merge({ a = "x" }, {}, { a = "" }, {}).a, "")
check("el store pisa al default", store.merge({ a = "x" }, {}, { a = "y" }, {}).a, "y")

print("\n== store: añadir y borrar ==")
local st = { commands = {}, layouts = {}, removed = {} }
store.upsert(st, "nuevo", "echo hola", "center, 800x400")
check("widget añadido", st.commands.nuevo, "echo hola")
check("posición añadida", st.layouts.nuevo, "center, 800x400")
store.remove(st, "nuevo")
check("widget borrado", st.commands.nuevo, nil)
check("tombstone creado", st.removed[1], "nuevo")
store.upsert(st, "nuevo", "echo hola")
check("tombstone limpiado al volver a añadir", #st.removed, 0)

print("\n== posiciones ==")
local spec = layout.parseLayout("bottom-center, 1610x584")
check("ancla", spec.anchor, "bottom-center")
check("ancho", spec.width, 1610)
check("alto", spec.height, 584)

spec = layout.parseLayout("right-center 869x1424")
check("ancla sin coma", spec.anchor, "right-center")
check("ancho sin coma", spec.width, 869)

spec = layout.parseLayout("bottom-left, 802x582, 0, -24")
check("desplazamiento x", spec.dx, 0)
check("desplazamiento y", spec.dy, -24)

spec = layout.parseLayout("custom, 900x520, 120, 140")
check("absoluta", spec.custom, true)
check("absoluta x", spec.dx, 120)
check("absoluta y", spec.dy, 140)

spec = layout.parseLayout("x=120 y=140 w=900 h=520")
check("clave=valor x", spec.dx, 120)
check("clave=valor ancho", spec.width, 900)

spec = layout.parseLayout("auto, 900x520")
check("auto", spec.auto, true)

spec = layout.parseLayout("abajo-izquierda, 100x100")
check("alias en español", spec.anchor, "bottom-left")

check("inválido", layout.parseLayout("no es una posición").valid, false)
check("vacío", layout.parseLayout(""), nil)
check("solo ancla", layout.parseLayout("center").anchor, "center")
check("espacios de más", layout.parseLayout("bottom-center , 1610x584").anchor, "bottom-center")
check("tamaño con espacios", layout.parseLayout("bottom-center , 1610x584").width, 1610)
check("custom sin coordenadas", layout.parseLayout("custom, 900x520").valid, false)
check("auto sin tamaño", layout.parseLayout("auto").auto, true)
check("ancla con guion bajo", layout.parseLayout("bottom_center").anchor, "bottom-center")
check("tamaño negativo", layout.parseLayout("bottom-center, -10x-10").width, nil)

local x, y = layout.anchorPosition("bottom-right", 900, 520, 3440, 1440, 16)
check("ancla abajo-derecha x", x, 3440 - 900 - 16)
check("ancla abajo-derecha y", y, 1440 - 520 - 16)

print("\n== manifiesto ==")
defaults.reset()
files[DIR .. "plugin.toml"] = [==[
[[setting]]
key = "commands"
type = "string_map"
label_key = "settings.commands.label"
default = { cava = "cava", cbonsai = "cbonsai -l -p", unimatrix = "unimatrix -s 96 -l o" }

[[setting]]
key = "layouts"
type = "string_map"
label_key = "settings.layouts.label"
default = { cava = "bottom-center, 1610x584", cbonsai = "top-center, 801x582" }
]==]
local base2 = defaults.load()
check("comandos del manifiesto", base2.commands.cava, "cava")
check("comando con espacios", base2.commands.cbonsai, "cbonsai -l -p")
check("comando con guiones", base2.commands.unimatrix, "unimatrix -s 96 -l o")
check("posición del manifiesto", base2.layouts.cava, "bottom-center, 1610x584")
check("posición con comas", base2.layouts.cbonsai, "top-center, 801x582")

defaults.reset()
files[DIR .. "plugin.toml"] = "[[setting]]\nkey = \"commands\"\ndefault = { a = \"x\" }\n"
local base3 = defaults.load()
check("manifiesto mínimo", base3.commands.a, "x")
check("respaldo de posiciones", base3.layouts.cava, "bottom-center, 1610x584")

defaults.reset()
files[DIR .. "plugin.toml"] = nil
local base4 = defaults.load()
check("sin manifiesto: respaldo", base4.commands.cava, "cava")
check("sin manifiesto: respaldo de posiciones", base4.layouts.unimatrix, "right-center, 869x1424")

print("\n== zonas ocupadas ==")
local clients = {
  { address = "0xa", class = "noctalia-term-cava", x = 915, y = 840, w = 1610, h = 584, monitor = "1" },
  { address = "0xb", class = "noctalia-term-btop", x = 16, y = 16, w = 928, h = 800, monitor = "1" },
  { address = "0xc", class = "kitty", x = 0, y = 0, w = 800, h = 600, monitor = "1" },
}
local monitors = {
  ["1"] = { id = "1", name = "DP-1", x = 0, y = 0, width = 3440, height = 1440 },
}
local occupied = win.occupiedRects(clients, monitors, "DP-1", nil)
check("solo cuenta las ventanas del plugin", #occupied, 2)
check("la primera zona", occupied[1].x, 915)
check("la segunda zona", occupied[2].y, 16)
local without = win.occupiedRects(clients, monitors, "DP-1", "0xa")
check("excluye la ventana que se recoloca", #without, 1)
check("la que queda", without[1].address, nil)
check("la que queda es la otra", without[1].x, 16)

print("\n== miniaturas ==")
local preview = load("lib/preview.luau")
-- Sistema de ficheros simulado para la limpieza.
local fs = {
  ["btop-aaa.png"] = true,
  ["btop-bbb.png"] = true,
  ["cava-ccc.png"] = true,
  ["batch-1.json"] = true,
}
fakeNoctalia.listDir = function()
  local names = {}
  for name in pairs(fs) do
    names[#names + 1] = name
  end
  return names
end
fakeNoctalia.removeFile = function(path)
  local name = path:match("([^/]+)$")
  fs[name] = nil
  return true
end
fakeNoctalia.fileExists = function(path)
  local name = path:match("([^/]+)$")
  return fs[name] == true
end
fakeNoctalia.mkdirAll = function() return true end
-- Los ficheros de prueba son "viejos": así la limpieza los borra.
fakeNoctalia.fileInfo = function()
  return { size = 10, mtime = os.time() - 7200, isDir = false }
end
fakeNoctalia.pluginDataDir = function() return "/tmp/opencode/testdata" end

local used = preview.currentPaths({
  { name = "btop", x = 10, y = 20, w = 300, h = 200 },
})
local usedCount = 0
for _ in pairs(used) do
  usedCount = usedCount + 1
end
check("currentPaths devuelve una ruta por ventana", usedCount, 1)
local usedPath = nil
for path in pairs(used) do
  usedPath = path
end
check("la ruta lleva el nombre y la firma", usedPath:match("btop%-[0-9a-f]+%.png$") ~= nil, true)

-- Con un mapa de ventanas también vale.
local fromMap = preview.currentPaths({ btop = { name = "btop", x = 10, y = 20, w = 300, h = 200 } })
local mapCount = 0
for _ in pairs(fromMap) do
  mapCount = mapCount + 1
end
check("currentPaths acepta un mapa", mapCount, 1)

-- La limpieza borra lo que no se usa y respeta lo que se usa.
local keep = { ["/tmp/opencode/testdata/thumbs/btop-aaa.png"] = true }
preview.pruneUnused(keep)
check("conserva la miniatura en uso", fs["btop-aaa.png"], true)
check("borra la que no se usa", fs["btop-bbb.png"], nil)
check("borra la de otro widget", fs["cava-ccc.png"], nil)
check("borra los lotes viejos", fs["batch-1.json"], nil)
-- Un fichero sin usar pero reciente se conserva: el host puede volver a
-- aplicar un árbol guardado y pedir esa imagen.
local fresh = { ["/tmp/opencode/testdata/thumbs/btop-bbb.png"] = true }
fs["btop-bbb.png"] = true
fs["btop-ccc.png"] = true
fakeNoctalia.fileInfo = function(path)
  local name = path:match("([^/]+)$")
  if name == "btop-ccc.png" then
    return { size = 10, mtime = os.time() - 7200, isDir = false }
  end
  return { size = 10, mtime = os.time(), isDir = false }
end
preview.pruneUnused(fresh, 1800)
check("conserva la miniatura en uso", fs["btop-aaa.png"], true)
check("conserva la reciente aunque no se use", fs["btop-bbb.png"], true)
check("borra la antigua que no se usa", fs["btop-ccc.png"], nil)

print("\n== rotación: permutaciones ==")
local function fakeWindow(name, x, y, w, h)
  return {
    address = "0x" .. name,
    class = "noctalia-term-" .. name,
    name = name,
    x = x,
    y = y,
    w = w,
    h = h,
    monitor = { id = "1", name = "DP-1", x = 0, y = 0, width = 3440, height = 1440 },
  }
end
local group = {
  fakeWindow("arriba-izq", 16, 16, 900, 800),
  fakeWindow("arriba-der", 2524, 16, 900, 800),
  fakeWindow("abajo-izq", 16, 624, 900, 800),
  fakeWindow("abajo-der", 2524, 624, 900, 800),
}

-- Se capturan las expresiones de movimiento para comprobar la permutación.
local dispatched = {}
fakeNoctalia.runAsync = function(argv, callback)
  local command = table.concat(argv, " ")
  if command:find("hyprctl dispatch") then
    table.insert(dispatched, argv[3])
  end
  if callback ~= nil then
    callback({ exitCode = 0, stdout = "", stderr = "" })
  end
  return true
end

-- En el monitor los cuatro widgets quedan en las esquinas:
--   arriba-izq (10h)  arriba-der (2h)
--   abajo-izq  (8h)   abajo-der  (4h)
-- El orden horario es: arriba-izq -> arriba-der -> abajo-der -> abajo-izq.
win.rotate(group, "clockwise", false, function() end)
local function movedTo(address)
  for _, expression in ipairs(dispatched) do
    if expression:find('address:' .. address, 1, true) then
      local mx, my = expression:match("x = (%-?%d+), y = (%-?%d+)")
      return tonumber(mx), tonumber(my)
    end
  end
  return nil, nil
end
local mx, my = movedTo("0xarriba-izq")
check("horario: arriba-izq toma arriba-der", mx, 2524)
check("horario: arriba-izq toma arriba-der (y)", my, 16)
mx, my = movedTo("0xabajo-der")
check("horario: abajo-der toma abajo-izq", mx, 16)
check("horario: abajo-der toma abajo-izq (y)", my, 624)

dispatched = {}
win.rotate(group, "counterclockwise", false, function() end)
mx, my = movedTo("0xarriba-izq")
check("antihorario: arriba-izq toma abajo-izq", mx, 16)
check("antihorario: arriba-izq toma abajo-izq (y)", my, 624)

dispatched = {}
win.rotate(group, "pairs", false, function() end)
mx, my = movedTo("0xarriba-izq")
check("parejas: arriba-izq toma arriba-der", mx,  2524)
check("parejas: arriba-izq toma arriba-der (y)", my, 16)

dispatched = {}
win.rotate(group, "opposite", false, function() end)
mx, my = movedTo("0xarriba-izq")
check("opuesto: arriba-izq toma abajo-der", mx, 2524)
check("opuesto: arriba-izq toma abajo-der (y)", my, 624)

dispatched = {}
win.rotate(group, "clockwise", true, function() end)
local resized = false
for _, expression in ipairs(dispatched) do
  if expression:find("resize", 1, true) then
    resized = true
  end
end
checkTrue("con tamaños se redimensiona", resized)

dispatched = {}
win.rotate(group, "clockwise", false, function() end)
resized = false
for _, expression in ipairs(dispatched) do
  if expression:find("resize", 1, true) then
    resized = true
  end
end
check("sin tamaños no se redimensiona", resized, false)

-- Con un número impar de ventanas, el que sobra se queda en su sitio.
local odd = {
  fakeWindow("arriba-izq", 16, 16, 900, 800),
  fakeWindow("arriba-der", 2524, 16, 900, 800),
  fakeWindow("abajo-izq", 16, 624, 900, 800),
}
dispatched = {}
win.rotate(odd, "pairs", false, function() end)
mx, my = movedTo("0xarriba-izq")
check("parejas impar: arriba-izq toma arriba-der", mx, 2524)
mx, my = movedTo("0xabajo-izq")
check("parejas impar: el que sobra se queda", mx, 16)
check("parejas impar: el que sobra no se mueve (y)", my, 624)

-- La rotación tiene que ser una biyección: ningún destino se repite.
dispatched = {}
win.rotate(group, "shuffle", false, function() end)
local targets = {}
for _, expression in ipairs(dispatched) do
  local tx, ty = expression:match("x = (%-?%d+), y = (%-?%d+)")
  if tx ~= nil then
    targets[tx .. "," .. ty] = (targets[tx .. "," .. ty] or 0) + 1
  end
end
local unique = 0
for _, count in pairs(targets) do
  if count == 1 then
    unique = unique + 1
  end
end
check("aleatorio: cada destino se usa una vez", unique, #group)

-- Con una sola ventana no hay nada que rotar.
dispatched = {}
win.rotate({ fakeWindow("solo", 16, 16, 900, 800) }, "clockwise", false, function() end)
check("una ventana no se mueve", #dispatched, 0)

print(string.format("\n%d comprobaciones, %d fallos", checks, failures))
os.exit(failures == 0 and 0 or 1)
