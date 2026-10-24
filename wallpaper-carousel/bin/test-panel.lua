-- Regression tests for panel.luau, runnable with plain Lua 5.1.
--
-- The panel is pure Lua/Luau: it only talks to the host through the
-- `noctalia`, `panel` and `ui` globals. This harness stubs those globals so the
-- entry can be loaded and driven like the shell would: open, frame ticks,
-- clicks, config changes. It then inspects the rendered tree.
--
-- Usage: lua5.1 bin/test-panel.lua panel.luau

local panelPath = arg[1] or "panel.luau"

local checks = 0
local failures = 0

local function check(condition, message)
  checks = checks + 1
  if not condition then
    failures = failures + 1
    io.stderr:write("FAIL: " .. message .. "\n")
  end
end

local function eq(actual, expected, message)
  check(actual == expected, string.format("%s (got %s, want %s)", message, tostring(actual), tostring(expected)))
end

-- Host stubs -----------------------------------------------------------------

local FILES = {}
for index = 1, 20 do
  FILES[index] = string.format("wp-%02d.jpg", index)
end

local settings = {
  directory = "/wallpapers",
  glyph = "wallpaper",
  card_width = 300,
  card_height = 400,
  card_shape = "skew",
  skew = 0.35,
  parallax = 1.0,
  selected_scale = 1.08,
  base_scale = 0.88,
  hover_boost = 0.2,
  scrim = 0,
  close_on_apply = true,
  apply_all = true,
  show_filenames = true,
  chrome = false,
  wheel = false,
  open_random = true,
}

local applied = {}
local closed = false
local tree = nil
local encoded = nil
local clockMs = 1000

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
  image = node("image"),
  box = node("box"),
  spacer = node("spacer"),
  button = node("button"),
  glyph = node("glyph"),
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
    return settings[key]
  end,
  getSetting = function()
    return 1.0
  end,
  pluginDataDir = function()
    return "/tmp/wc-selftest/data"
  end,
  pluginDir = function()
    return "/tmp/wc-selftest/plugin"
  end,
  mkdirAll = function() end,
  fileExists = function(path)
    return true
  end,
  fileInfo = function()
    return { mtime = 1, size = 2 }
  end,
  listDir = function()
    return FILES
  end,
  wallpaperDirectory = function()
    return "/wallpapers"
  end,
  wallpaperPath = function()
    return "/wallpapers/wp-03.jpg"
  end,
  focusedOutputName = function()
    return "DP-1"
  end,
  outputs = function()
    return { { name = "DP-1", width = 1920, height = 1080 } }
  end,
  setWallpaper = function(first, second)
    table.insert(applied, second or first)
  end,
  notify = function() end,
  notifyError = function() end,
  log = function() end,
  nowMs = function()
    return clockMs
  end,
  state = { set = function() end },
  json = {
    encode = function(value)
      encoded = value
      return "[]"
    end,
    decode = function()
      return {}
    end,
  },
  writeFile = function()
    return true
  end,
  runAsync = function(_, callback)
    if callback then
      callback({ exitCode = 0, stderr = "" })
    end
    return true
  end,
}

dofile(panelPath)

-- Tree helpers ---------------------------------------------------------------

local function childrenOf(current)
  return current and current.children or {}
end

local function collect(current, kind, result)
  result = result or {}
  if type(current) ~= "table" then
    return result
  end
  if current.kind == kind then
    table.insert(result, current)
  end
  for _, child in ipairs(childrenOf(current)) do
    collect(child, kind, result)
  end
  return result
end

local function cards()
  local result = {}
  for _, column in ipairs(collect(tree, "column")) do
    local key = column.props.key
    if type(key) == "string" and key:match("^card%-%-?%d+$") then
      table.insert(result, column)
    end
  end
  return result
end

local function cardAt(slot)
  for _, column in ipairs(cards()) do
    if column.props.key == "card-" .. tostring(slot) then
      return column
    end
  end
  return nil
end

local function tick(times)
  for _ = 1, times do
    onFrameTick(16)
  end
end

-- 1. Open + chunked load -----------------------------------------------------

onOpen()
tick(200)
check(tree ~= nil, "the panel renders after the chunked load")
check(#cards() >= 5, "the ribbon renders several cards, got " .. #cards())

-- 2. Circular ribbon: cards on both sides, even with the first wallpaper -----

settings.open_random = false -- opens on wp-03, near the start of the folder
onOpen()
tick(200)
check(cardAt(-2) ~= nil and cardAt(2) ~= nil, "the ribbon has cards at both sides of the selection")
check(cardAt(-2).children[1].props.tooltip ~= cardAt(2).children[1].props.tooltip,
  "the cards at both sides are different wallpapers")
check(cardAt(-2).children[1].props.tooltip == "wp-20.jpg" or cardAt(-2).children[1].props.tooltip == "wp-01.jpg",
  "the ribbon wraps around the end of the folder, got " .. tostring(cardAt(-2).children[1].props.tooltip))

-- 3. Tighter cards: the slot is smaller than the selected card ---------------

local slot = cards()[1].props.width
eq(slot, 264, "side cards fill their 300*0.88 slot")
local selectedImage = nil
for _, card in ipairs(cards()) do
  local image = card.children[1]
  if image and image.props.width == math.floor(300 * 1.08 + 0.5) then
    selectedImage = image
  end
end
check(selectedImage ~= nil, "the selected card is wider than the base size")
check(selectedImage.props.width > slot, "the selected card overlaps its neighbours (continuous ribbon)")

-- 4. Filenames are independent from the footer -------------------------------

local labels = collect(tree, "label")
local hasName = false
for _, label in ipairs(labels) do
  if tostring(label.props.text):match("%.jpg$") then
    hasName = true
  end
end
check(hasName, "show_filenames shows the file name without the footer")

settings.show_filenames = false
onConfigChanged()
tick(200)
for _, label in ipairs(collect(tree, "label")) do
  check(not tostring(label.props.text):match("%.jpg$"), "hiding filenames removes the name")
end

settings.show_filenames = true
onConfigChanged()
tick(200)

-- 5. Double click applies; a single click only selects -----------------------

settings.close_on_apply = true
onConfigChanged()
tick(200)
applied = {}
closed = false
local target = cardAt(2)
check(target ~= nil, "there is a neighbour card to click")
local targetName = target.children[1].props.tooltip
onCardClick("2")
eq(#applied, 0, "a single click does not apply")
check(not closed, "a single click does not close the panel")
clockMs = clockMs + 100
onCardClick("2")
eq(#applied, 1, "the second click within the double-click window applies")
eq(applied[1], "/wallpapers/" .. targetName, "the applied wallpaper is the clicked card")
check(closed, "close_on_apply still closes after the double click")

-- 6. A slow second click is not a double click -------------------------------

settings.close_on_apply = false
settings.open_random = false
onConfigChanged()
tick(200)
applied = {}
closed = false
onCardClick("1") -- selects wp-04
clockMs = clockMs + 900
onCardClick("1") -- too late: only records a new first click
eq(#applied, 0, "two slow clicks do not apply")
clockMs = clockMs + 100
onCardClick("1")
eq(#applied, 1, "a quick click after that one counts as its pair")

-- 7. Card shape reaches the thumbnail helper ---------------------------------

for _, shape in ipairs({ "skew", "rect", "square", "triangle", "ellipse" }) do
  settings.card_shape = shape
  onConfigChanged()
  tick(200)
  check(type(encoded) == "table" and encoded[1] ~= nil, "thumbnails are requested for " .. shape)
  if type(encoded) == "table" and encoded[1] then
    eq(encoded[1].shape, shape, "the helper receives the " .. shape .. " shape")
  end
end

-- 8. Unknown shape falls back to the skewed ribbon ---------------------------

settings.card_shape = "banana"
onConfigChanged()
tick(200)
eq(encoded[1].shape, "skew", "an unknown shape falls back to skew")

-- 9. Random opening stays inside the folder ----------------------------------

settings.card_shape = "skew"
settings.open_random = true
onOpen()
tick(200)
local seenSlots = {}
for _, card in ipairs(cards()) do
  local tooltip = tostring(card.children[1].props.tooltip)
  check(tooltip:match("^wp%-%d%d%.jpg$") ~= nil, "the opened card belongs to the folder, got " .. tooltip)
  seenSlots[tooltip] = true
end
local distinct = 0
for _ in pairs(seenSlots) do
  distinct = distinct + 1
end
check(distinct >= 5, "the random opening shows a full ribbon")

-- Result ---------------------------------------------------------------------

if failures > 0 then
  io.stderr:write(string.format("%d/%d checks failed\n", failures, checks))
  os.exit(1)
end
print(string.format("%d checks passed", checks))
