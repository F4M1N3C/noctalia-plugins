-- Pruebas de los modulos base de `faminec/notes-plus`: dirs, merge, channel.
-- No dependen del panel ni del servidor: solo del mock de noctalia.
--
--     lua5.4 test-units.lua

local function scriptDir()
  local src = debug.getinfo(1, "S").source
  if src:sub(1, 1) == "@" then
    return src:sub(2):match("^(.*)[/\\][^/\\]*$") or "."
  end
  return "."
end

local FALLOS = 0
local PASADOS = 0
local function check(nombre, esperado, obtenido)
  if esperado == obtenido then
    PASADOS = PASADOS + 1
    print(string.format("  ok   %-60s %s", nombre, tostring(obtenido)))
  else
    FALLOS = FALLOS + 1
    print(string.format("  FALLA %-60s esperado=%s obtenido=%s", nombre, tostring(esperado), tostring(obtenido)))
  end
end

-- Mock minimo de noctalia para los modulos.
local HOME = "/tmp/notes-units-home"
local NOTES_DIR = "/tmp/notes-units-notes"
local XDG_CONFIG = HOME .. "/.config"
local USER_DIRS = XDG_CONFIG .. "/user-dirs.dirs"
local files = {}
local function writeFile(p, c) files[p] = c; return true end
local function readFile(p) return files[p] end
local function removeFile(p) files[p] = nil; return true end
local function renameFile(a, b) if files[a] == nil then return false end; files[b] = files[a]; files[a] = nil; return true end
-- fileInfo: in-memory files win; real directories are detected on disk
-- (dirs.luau asks whether a folder exists to apply the legacy fallback).
local function fileInfo(p)
  if files[p] ~= nil then
    return { size = #files[p], mtime = 1, isDir = false }
  end
  local probe = io.popen('test -d "' .. p .. '" && echo yes || echo no')
  local r = probe:read("*a")
  probe:close()
  if r:match("yes") then
    return { size = 0, mtime = 1, isDir = true }
  end
  return nil
end
local function mkdirAll() return true end
local function expandPath(p)
  if p == "~" then return HOME end
  if p:sub(1, 2) == "~/" then return HOME .. p:sub(2) end
  return p
end
local function getenv(k)
  if k == "XDG_CONFIG_HOME" then return XDG_CONFIG end
  return nil
end
local function getConfig(k)
  if k == "notes_dir" then return (rawget(_G, "_nds") or "") end
  if k == "extension" then return "md" end
  return ""
end
local function json_encode(v)
  if type(v) ~= "table" then return tostring(v) end
  local partes = {}
  for k, val in pairs(v) do
    if type(val) == "string" then
      partes[#partes + 1] = string.format('"%s":"%s"', tostring(k), val)
    elseif type(val) == "boolean" then
      partes[#partes + 1] = string.format('"%s":%s', tostring(k), tostring(val))
    else
      partes[#partes + 1] = string.format('"%s":%s', tostring(k), tostring(val))
    end
  end
  return "{" .. table.concat(partes, ",") .. "}"
end
local function json_decode(s)
  local out = {}
  for k, v in s:gmatch('"([^"]*)":"([^"]*)"') do out[k] = v end
  for k, v in s:gmatch('"([^"]*)":([^,}]+)') do
    if out[k] == nil then
      local t = v:gsub("^%s+", ""):gsub("%s+$", "")
      if t == "true" then out[k] = true elseif t == "false" then out[k] = false else out[k] = t end
    end
  end
  return out
end
local function tr(k) return k end
local function formatTime(f) return "2026-01-01 00.00.00" end
local function string_trim(s) return (s:gsub("^%s+", ""):gsub("%s+$", "")) end

local mock = {
  getConfig = getConfig, getSetting = function() return 1 end,
  expandPath = expandPath, setUpdateInterval = function() end, tr = tr, log = function() end,
  notifyError = function() end, formatTime = formatTime, pluginDataDir = function() return "/tmp/notes-units-data" end,
  mkdirAll = mkdirAll, readFile = readFile, writeFile = writeFile, renameFile = renameFile,
  removeFile = removeFile, fileExists = function(p) return files[p] ~= nil end,
  fileInfo = fileInfo, listDir = function() return {} end,
  json = { encode = json_encode, decode = json_decode },
  string = { trim = string_trim },
  state = { get = function() return nil end, set = function() end, watch = function() end },
  getenv = getenv,
}
_G.noctalia = mock

-- Prepare the filesystem for dirs tests.
os.execute("rm -rf " .. HOME .. " " .. NOTES_DIR)
os.execute("mkdir -p " .. XDG_CONFIG)
-- user-dirs.dirs with a localized Documents folder
files[USER_DIRS] = 'XDG_DOCUMENTS_DIR="$HOME/Documentos"\n'
-- El directorio resuelto (localizado) existe y el legacy no: se usa el
-- resuelto. El caso legacy se prueba despues, quitando este.
os.execute("mkdir -p " .. HOME .. "/Documentos/Notes")
os.execute("mkdir -p " .. HOME .. "/Documentos")

-- ============================================================ dirs.luau
local dirs = dofile(scriptDir() .. "/dirs.luau")

-- Default resolves to the localized Documents/Notes.
check("dirs: default -> Documents/Notes localizado", HOME .. "/Documentos/Notes", dirs.resolveNotesDir())

-- Legacy fallback: if resolved default does not exist but ~/Documents/Notes does.
os.execute("rm -rf " .. HOME .. "/Documentos/Notes")
os.execute("mkdir -p " .. HOME .. "/Documents/Notes")
-- resolved = ~/Documentos/Notes (no existe), legacy = ~/Documents/Notes (existe) -> legacy
check("dirs: fallback legacy", HOME .. "/Documents/Notes", dirs.resolveNotesDir())

-- Restore and test an absolute configured path.
os.execute("mkdir -p " .. HOME .. "/Documentos/Notes")
_G._nds = "/tmp/absoluto/notas"
check("dirs: ruta absoluta configurada", "/tmp/absoluto/notas", dirs.resolveNotesDir())
_G._nds = ""

-- $XDG_DOCUMENTS_DIR prefix.
_G._nds = "$XDG_DOCUMENTS_DIR/sub"
check("dirs: prefijo $XDG_DOCUMENTS_DIR", HOME .. "/Documentos/sub", dirs.resolveNotesDir())
_G._nds = ""

-- ============================================================ merge.luau
local merge = dofile(scriptDir() .. "/merge.luau")

check("merge: same", "same", merge.resolve("a", "b", "b").status)
check("merge: same content", "b", merge.resolve("a", "b", "b").content)
check("merge: local (remote==base)", "local", merge.resolve("a", "b", "a").status)
check("merge: local content", "b", merge.resolve("a", "b", "a").content)
check("merge: remote (local==base)", "remote", merge.resolve("a", "a", "c").status)
check("merge: remote content", "c", merge.resolve("a", "a", "c").content)
check("merge: merged (one prefix)", "merged", merge.resolve("a", "ab", "abc").status)
check("merge: merged content", "abc", merge.resolve("a", "ab", "abc").content)
check("merge: merged (distinct appends)", "merged", merge.resolve("a", "ab", "ac").status)
check("merge: merged distinct content", "a" .. "b" .. "c", merge.resolve("a", "ab", "ac").content)
check("merge: conflict (middle edit)", "conflict", merge.resolve("ab", "aXb", "ayb").status)
check("merge: conflict keeps local", "aXb", merge.resolve("ab", "aXb", "ayb").content)
check("merge: conflict (base empty)", "conflict", merge.resolve("", "x", "y").status)

-- ============================================================ channel.luau
local channel = dofile(scriptDir() .. "/channel.luau")

local cdir = "/tmp/notes-units-chan"
os.execute("rm -rf " .. cdir); os.execute("mkdir -p " .. cdir)
files = {}  -- reset for channel (uses readFile/writeFile/renameFile)
-- re-bind files table references (already captured by closure? readFile closure captures `files` upvalue by name via the table; ok because files is upvalue)
check("channel: path", cdir .. "/.current.json", channel.currentPath(cdir))
local okw = channel.write(cdir, { name = "nota.md", content = "hola", open = true, at = "t" })
check("channel: write ok", true, okw)
check("channel: file exists", true, files[cdir .. "/.current.json"] ~= nil)
check("channel: no temp left", true, files[cdir .. "/.current.json.tmp"] == nil)
local r = channel.read(cdir)
check("channel: read name", "nota.md", r and r.name or nil)
check("channel: read content", "hola", r and r.content or nil)
check("channel: read open", true, r and r.open == true or false)
-- atomicity: a rename was recorded
check("channel: read of missing -> nil", nil, channel.read("/tmp/notes-units-nope"))

-- corrupt file
files[cdir .. "/.current.json"] = "{not json"
check("channel: corrupt -> nil", nil, channel.read(cdir))

-- empty name clears the channel
local ok2 = channel.write(cdir, { name = "", content = "", open = false, at = "t" })
check("channel: clear write ok", true, ok2)
local r2 = channel.read(cdir)
check("channel: cleared name", "", r2 and r2.name or "X")

print()
print(string.format("Resultado: %d correctos, %d fallos", PASADOS, FALLOS))
os.exit(FALLOS == 0 and 0 or 1)

