-- Pruebas del panel de `faminec/notes-plus` con el API de Noctalia simulado.
--
-- Se comprueba sobre todo el CANAL con el otro plugin: el fichero
-- .current.json (nota abierta, contenido y si esta abierta ahora mismo).
-- Es lo que lee `faminec/notes-plus` para mandar la nota al celular, y se
-- rompio mas de una vez al renombrar o al borrar sin republicar.
--
--     lua5.4 test-panel.lua

local FALLOS = 0
local PASADOS = 0

local function check(nombre, esperado, obtenido)
  if esperado == obtenido then
    PASADOS = PASADOS + 1
    print(string.format("  ok   %-58s %s", nombre, tostring(obtenido)))
  else
    FALLOS = FALLOS + 1
    print(string.format("  FALLA %-58s esperado=%s obtenido=%s", nombre, tostring(esperado), tostring(obtenido)))
  end
end

local function scriptDir()
  local src = debug.getinfo(1, "S").source
  if src:sub(1, 1) == "@" then
    return src:sub(2):match("^(.*)[/\\][^/\\]*$") or "."
  end
  return "."
end

local M = dofile(scriptDir() .. "/test-mock.luau")
local mock = M.mock
local state = M.state
local botones = M.botones
local bitacora = M.bitacora
local erroresNotificados = M.erroresNotificados
local pins = M.pins
local DIR = M.DIR
local DATA_DIR = M.DATA_DIR
local limpia = M.limpia
local escribir = M.escribir
local leer = M.leer
local existe = M.existe
local listar = M.listar
local json_encode = M.json_encode
local json_decode = M.json_decode
local ui_button = M.ui_button
local normaliza = M.normaliza
local PANEL_PATH = M.PANEL_PATH

_G.noctalia = mock

-- ------------------------------------------------------------- pruebas


-- ¿Se publico de forma atomica? Es decir: se escribio a un temporal y ese
-- temporal se renombro al fichero final. Un lector que llegue en medio nunca
-- ve un JSON a medias.
local function publicacionAtomica()
  local tmp, renombrado = nil, false
  for _, op in ipairs(bitacora) do
    if op.op == "write" and op.path:match("%.tmp$") then
      tmp = op.path
    elseif op.op == "rename" and op.to:match("/%.current%.json$") then
      if tmp ~= nil and op.from == tmp then
        renombrado = true
      end
    end
  end
  return renombrado
end

local function current()
  local raw = mock.readFile(DIR .. "/.current.json")
  if raw == nil then
    return nil
  end
  return json_decode(raw)
end

print("== el canal con el otro plugin ==")

limpia()
escribir(DIR .. "/nota.md", "contenido de la nota")

-- onOpen: el panel se abre con la nota indicada
state.open_note = "nota.md"
pcall(onOpen, {})

local c = current()
check(".current.json existe tras abrir", true, c ~= nil)
check("apunta a la nota abierta", "nota.md", c and c.name or nil)
check("lleva el contenido", "contenido de la nota", c and c.content or nil)
check("marca que esta abierta", true, c and c.open == true or false)
check("se publica de forma atomica (temporal + renombrado)", true, publicacionAtomica())
check("no queda ningun temporal suelto", true, not existe(DIR .. "/.current.json.tmp"))
check("el canal esta en la carpeta de notas", true, existe(DIR .. "/.current.json"))

-- Renombrar: el nombre cambia y se vuelve a publicar
local okR, errR = pcall(onRename, "renombrada")
if not okR then print("  [debug] onRename fallo:", tostring(errR)) end
c = current()
check("tras renombrar apunta al nombre nuevo", "renombrada.md", c and c.name or nil)
check("el fichero tambien se renombro", true, existe(DIR .. "/renombrada.md"))
check("el nombre viejo ya no esta", true, not existe(DIR .. "/nota.md"))

-- Cambios externos: se vuelve a publicar
escribir(DIR .. "/renombrada.md", "contenido nuevo")
pcall(update)
-- (sin trazas)
c = current()
check("un cambio externo se publica", "contenido nuevo", c and c.content or nil)

-- Volver atras: deja de estar abierta, pero se recuerda la ultima nota
pcall(onBack)
c = current()
check("tras volver atras no esta abierta", false, c and c.open == true or false)
check("pero se recuerda la ultima nota", "renombrada.md", c and c.name or nil)

-- Borrar la nota abierta: se publica para no mandar una nota inexistente.
-- `deleteNote` es local, asi que se pulsa el boton de confirmar que crea el
-- panel (es lo que haria el usuario).
escribir(DIR .. "/renombrada.md", "contenido")
state.open_note = "renombrada.md"
pcall(onOpen, {})
for i in pairs(botones) do botones[i] = nil end
pcall(onEditorDelete)
local confirm = nil
for _, b in ipairs(botones) do
  if b.glyph == "check" and type(b.onClick) == "function" then
    confirm = b
  end
end
check("el panel ofrece un boton para confirmar el borrado", true, confirm ~= nil)
if confirm then
  pcall(confirm.onClick)
end
c = current()
check("tras borrar no queda ninguna nota", "", c and c.name or nil)
check("y el contenido tampoco", "", c and c.content or nil)
check("el fichero ya no esta", true, not existe(DIR .. "/renombrada.md"))

-- Renombrar a un nombre que ya existe: se avisa y no se toca nada.
escribir(DIR .. "/nota.md", "contenido")
escribir(DIR .. "/ocupada.md", "otra nota")
state.open_note = "nota.md"
pcall(onOpen, {})
for i in pairs(erroresNotificados) do erroresNotificados[i] = nil end
pcall(onRename, "ocupada")
check("renombrar a un nombre existente avisa", 1, #erroresNotificados)
local trasError = current()
check("y no cambia el nombre", "nota.md", trasError and trasError.name or "SIN current.json")
check("la nota original sigue ahi", true, existe(DIR .. "/nota.md"))
check("la otra nota no se toco", "otra nota", leer(DIR .. "/ocupada.md"))

-- Un nombre con "/" se limpia (no se puede meter una carpeta).
for i in pairs(erroresNotificados) do erroresNotificados[i] = nil end
pcall(onRename, "carpeta/sub")
check("un nombre con barra se limpia", true, existe(DIR .. "/carpetasub.md"))
check("y no se crea ninguna carpeta", true, not existe(DIR .. "/carpeta"))

-- Si la nota se renombra o se borra desde fuera (el movil), el panel no puede
-- quedarse con un fantasma: un nombre que ya no existe y un editor vacio.
escribir(DIR .. "/renombrada.md", "contenido")
state.open_note = "renombrada.md"
pcall(onOpen, {})
os.remove(DIR .. "/renombrada.md") -- como si se borrase desde fuera
pcall(update)
c = current()
check("si la nota desaparece, no queda ninguna nota publicada", "", c and c.name or nil)
check("ni se queda el contenido viejo", "", c and c.content or nil)
check("y el estado publico tambien se vacia", "", tostring(state.notes_current or ""))

print()
print("== el autoguardado no pisa cambios externos ==")

-- El movil escribe mientras se esta editando en el PC: el autoguardado no
-- puede pisar la version del movil.
limpia()
escribir(DIR .. "/nota.md", "contenido")
state.open_note = "nota.md"
pcall(onOpen, {})
pcall(onEdited, "mi version local")
escribir(DIR .. "/nota.md", "version del movil")
for i in pairs(erroresNotificados) do erroresNotificados[i] = nil end
-- Tres ticks: el watcher nota el cambio externo y el autoguardado intenta
-- guardar despues (el umbral de autoguardado son 2 ticks sin escribir).
pcall(update)
pcall(update)
pcall(update)
check("el autoguardado no pisa un cambio externo", "version del movil", leer(DIR .. "/nota.md"))
check("con cambios incompatibles se avisa", true, #erroresNotificados >= 1)
local copias = listar(DIR .. "/.conflicts")
check("se guarda una copia del texto local", true, #copias >= 1)
if #copias > 0 then
  check("la copia tiene el texto local", "mi version local", leer(DIR .. "/.conflicts/" .. copias[1]) or "")
end

-- Sin cambios externos, el autoguardado sigue guardando.
limpia()
escribir(DIR .. "/nota2.md", "base")
state.open_note = "nota2.md"
pcall(onOpen, {})
pcall(onEdited, "base editada")
pcall(update)
pcall(update)
pcall(update)
check("sin cambios externos, el autoguardado guarda", "base editada", leer(DIR .. "/nota2.md"))

-- Un anadido externo se combina con el texto local: no se pierde nada.
limpia()
escribir(DIR .. "/nota3.md", "hola")
state.open_note = "nota3.md"
pcall(onOpen, {})
pcall(onEdited, "hola mundo")
escribir(DIR .. "/nota3.md", "hola!")
pcall(update)
pcall(update)
pcall(update)
check("un anadido externo se combina", "hola mundo!", leer(DIR .. "/nota3.md"))

-- Una edicion en medio no se puede combinar: el movil gana (no se pisa) y el
-- texto local queda a salvo en la copia.
limpia()
escribir(DIR .. "/nota4.md", "base")
state.open_note = "nota4.md"
pcall(onOpen, {})
pcall(onEdited, "mi texto")
escribir(DIR .. "/nota4.md", "otro texto")
pcall(update)
pcall(update)
pcall(update)
check("una edicion incompatible no se pisa", "otro texto", leer(DIR .. "/nota4.md"))

print()
print("== el test detecta una regresion ==")
-- Un test que nunca falla no demuestra nada: se rompe el panel a proposito
-- (se quita la republicacion al renombrar) y se comprueba que el test lo
-- detecta. Si este bloque falla, el test ya no vigila nada.
local function prueba_mutacion()
  local fuente2 = normaliza(assert(io.open(PANEL_PATH, "r")):read("*a"))
  local mutado = fuente2:gsub("(%s*)publishCurrent%(%)%s*%-%- La nota ya no se llama igual",
    "%1-- publicacion quitada a proposito")
  if mutado == fuente2 then
    -- Si el texto ha cambiado, se quitan TODAS las llamadas a publishCurrent
    -- dentro de onRename y onExternalChange.
    mutado = fuente2:gsub("  publishCurrent%(%)", "  -- quitada a proposito")
  end
  if mutado == fuente2 then
    print("  FALLA no se ha podido mutar el panel: revisa el texto")
    return false
  end
  local tmp = os.tmpname() .. ".luau"
  local f = io.open(tmp, "w")
  f:write(mutado)
  f:close()
  local okMut, errMut = pcall(function()
    local chunkMut = load(mutado, tmp)
    chunkMut()
  end)
  os.remove(tmp)
  if not okMut then
    print("  FALLA el panel mutado no se pudo cargar: " .. tostring(errMut))
    return false
  end
  -- Con el panel roto, renombrar NO debe actualizar current.json.
  limpia()
  escribir(DIR .. "/nota.md", "contenido")
  state.open_note = "nota.md"
  pcall(onOpen, {})
  local antes = current()
  pcall(onRename, "renombrada")
  local despues = current()
  local detecto = (antes and antes.name) == "nota.md" and (despues and despues.name) == "nota.md"
  return detecto
end

local detecta = pcall(prueba_mutacion)
check("el test detecta el fallo si se rompe el panel", true, detecta and true or false)

-- Fallo forzado a proposito: lo usa tools/test-codigos.sh para comprobar
-- que este test sale con codigo de error cuando algo falla (si no, un test
-- puede imprimir "1 fallos" y salir con codigo 0 y nadie se entera).
if os.getenv("FORCE_TEST_FAILURE") == "1" then
  check("fallo forzado (comprobacion del codigo de salida)", 1, 2)
end

print()
print(string.format("Resultado: %d correctos, %d fallos", PASADOS, FALLOS))

-- La carpeta de esta ejecucion se borra siempre (si se quiere verla para
-- depurar, con KEEP_TEST_DIR=1 se deja).
if os.getenv("KEEP_TEST_DIR") ~= "1" then
  os.execute("rm -rf " .. DIR)
end
os.exit(FALLOS == 0 and 0 or 1)
