--!nonstrict
-- Driver de pruebas del panel de notas.
--
-- Abre una nota por el MISMO camino que el panel de verdad (el estado
-- "open_note" y onOpen), edita el buffer y guarda con onFlushNow, que es
-- donde vive la logica de fusion (merge.luau). Despues comprueba que el
-- fichero en disco quedo como se pidio y dice que nota toco.
--
--   lua5.4 test-driver.lua --note nota.md --text "hola"
--
-- Opciones:
--   --dir <carpeta>     Carpeta de notas (equivale a NOTES_TEST_DIR).
--   --note <nombre>     Nota a abrir, con su extension ("nota.md").
--   --text <texto>      Texto nuevo que se guarda (reemplaza).
--   --text-file <fich>  Texto nuevo leido de un fichero.
--   --append            Anade el texto al final en vez de reemplazarlo.
--   --new               Crea una nota nueva desde el panel (onNewNote).
--   --print             Escribe en stdout el contenido final de la nota.
--
-- Salida: "OK <ruta>" y codigo 0, o "ERROR <motivo>" y codigo 1.

local function scriptDir()
  local src = debug.getinfo(1, "S").source
  if src:sub(1, 1) == "@" then
    return src:sub(2):match("^(.*)[/\\][^/\\]*$") or "."
  end
  return "."
end

local function fallar(motivo)
  io.stderr:write("ERROR " .. tostring(motivo) .. "\n")
  os.exit(1)
end

local function shq(s)
  return "'" .. tostring(s):gsub("'", "'\\''") .. "'"
end

-- ---------------------------------------------------------- argumentos

local argv = arg or {}
local args = {}
do
  local i = 1
  while i <= #argv do
    local a = argv[i]
    if a == "--dir" or a == "--note" or a == "--text" or a == "--text-file" or a == "--externo" then
      if argv[i + 1] == nil then
        fallar("falta el valor de " .. a)
      end
      args[a] = argv[i + 1]
      i = i + 2
    else
      args[a] = true
      i = i + 1
    end
  end
end

-- El mock lee NOTES_TEST_DIR al cargarse, y en Lua no hay forma de cambiar
-- el entorno del proceso: si la carpeta llega por --dir, el driver se
-- relanza a si mismo con la variable ya puesta.
if args["--dir"] ~= nil then
  local dir = args["--dir"]
  if os.getenv("NOTES_TEST_DIR") ~= dir then
    if os.getenv("NOTES_DRIVER_REEXEC") == "1" then
      fallar("no se pudo fijar NOTES_TEST_DIR")
    end
    local lua = (arg and arg[-1]) or "lua5.4"
    local partes = {}
    for i = 1, #argv do
      partes[#partes + 1] = shq(argv[i])
    end
    local cmd = "NOTES_TEST_DIR=" .. shq(dir) .. " NOTES_DRIVER_REEXEC=1 "
      .. shq(lua) .. " " .. shq(scriptDir() .. "/test-driver.lua")
      .. " " .. table.concat(partes, " ")
    local ok, how, code = os.execute(cmd)
    if how == "exit" then
      os.exit(code)
    end
    os.exit(ok and 0 or 1)
  end
end

-- test-mock.luau devuelve una tabla con el simulador (mock) y los
-- ayudantes de disco (leer, listar...). El panel solo ve la parte "mock".
local env = dofile(scriptDir() .. "/test-mock.luau")
local mock = env.mock
local DIR = env.DIR

-- ---------------------------------------------------------- contenido

local texto = nil
if args["--text-file"] ~= nil then
  local f = io.open(args["--text-file"], "r")
  if f == nil then
    fallar("no se pudo leer " .. tostring(args["--text-file"]))
  end
  texto = f:read("*a")
  f:close()
elseif args["--text"] ~= nil then
  texto = tostring(args["--text"])
end

-- ---------------------------------------------------------- preparar

local function listaFicheros()
  local out = {}
  for _, name in ipairs(env.listar(DIR)) do
    out[name] = true
  end
  return out
end

-- El panel se abre primero: es lo que resuelve la carpeta, la extension y
-- la lista de notas. Sin esto, onNewNote() no sabe el nombre que dar.
_G.onOpen({})

local nombre = nil
if args["--new"] == true then
  -- El panel publica la nota que acaba de abrir en "notes_current": es el
  -- nombre sin adivinar. Si no estuviera, se busca por diferencias en la
  -- carpeta (ignorando los ficheros auxiliares ".something").
  local antes = listaFicheros()
  _G.onNewNote()
  nombre = mock.state.get("notes_current")
  if type(nombre) ~= "string" or nombre == "" then
    local despues = listaFicheros()
    for name in pairs(despues) do
      if not antes[name] and name:sub(1, 1) ~= "." then
        nombre = name
        break
      end
    end
  end
  if type(nombre) ~= "string" or nombre == "" then
    fallar("el panel no creo ninguna nota")
  end
elseif args["--note"] ~= nil then
  nombre = tostring(args["--note"])
  mock.state.set("open_note", nombre)
  _G.onOpen({})
else
  fallar("falta --note o --new")
end

-- ---------------------------------------------------------- editar

-- Con --externo se simula que la nota cambio fuera del panel (el movil, una
-- sincronizacion) DESPUES de abrirla: el panel ya tiene la base en memoria
-- y al guardar tiene que detectarlo.
if args["--externo"] ~= nil then
  local f = io.open(DIR .. "/" .. nombre, "w")
  if f == nil then
    fallar("no se pudo escribir el cambio externo en " .. DIR .. "/" .. nombre)
  end
  f:write(tostring(args["--externo"]))
  f:close()
end

if texto ~= nil then
  if args["--append"] == true then
    local f = io.open(DIR .. "/" .. nombre, "r")
    local actual = ""
    if f ~= nil then
      actual = f:read("*a")
      f:close()
    end
    texto = actual .. texto
  end
  -- onFlushNow es el boton de guardar del panel: pasa por flush(), que
  -- decide con merge.luau si escribe, adopta lo de fuera o avisa de
  -- conflicto.
  _G.onFlushNow(texto)
end

-- ---------------------------------------------------------- comprobar

-- Con NOTES_DRIVER_DEBUG=1 se vuelca la bitacora de operaciones de ficheros:
-- sirve para ver que escribio el panel cuando algo va mal.
if os.getenv("NOTES_DRIVER_DEBUG") == "1" then
  for _, op in ipairs(env.bitacora) do
    io.stdout:write("DEBUG " .. tostring(op.op) .. " " .. tostring(op.path) .. "\n")
  end
end

local ruta = DIR .. "/" .. nombre
local guardado = env.leer(ruta)
if guardado == nil then
  fallar("no existe el fichero " .. ruta)
end

-- Un conflicto deja el texto de fuera intacto y ademas deja una copia del
-- texto del panel: se avisa con "CONFLICTO" y codigo 3 para que las
-- pruebas puedan distinguirlo de un fallo.
local huboConflicto = false
for _, aviso in ipairs(env.erroresNotificados) do
  if tostring(aviso):find("errors.conflict", 1, true) ~= nil then
    huboConflicto = true
    break
  end
end
if huboConflicto then
  io.stdout:write("CONFLICTO " .. ruta .. "\n")
  os.exit(3)
end

if texto ~= nil and guardado ~= texto then
  fallar("el contenido guardado no es el pedido")
end

if args["--print"] == true then
  io.write(guardado)
end

io.stdout:write("OK " .. ruta .. "\n")
os.exit(0)
