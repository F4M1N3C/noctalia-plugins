--!nonstrict
local layoutLib = require("./layout.luau")
local M = {}

-- Edad máxima (ms) de un rectángulo impuesto para seguir suprimiéndolo.
M.IMPOSED_TTL_MS = 5000

local function thirdMargin(size)
  return size / 3
end

-- Ancla deducida del cuadrante del CENTRO de la ventana.
function M.anchorFromRect(rect, screen, margin)
  local centerX = rect.x + rect.w / 2
  local centerY = rect.y + rect.h / 2
  local column
  if centerX < screen.x + thirdMargin(screen.width) then
    column = "left"
  elseif centerX > screen.x + screen.width * 2 / 3 then
    column = "right"
  else
    column = "center"
  end
  local row
  if centerY < screen.y + thirdMargin(screen.height) then
    row = "top"
  elseif centerY > screen.y + screen.height * 2 / 3 then
    row = "bottom"
  else
    row = "center"
  end
  local anchor
  if row == "center" then
    if column == "center" then anchor = "center"
    elseif column == "left" then anchor = "left-center"
    else anchor = "right-center" end
  else
    anchor = row .. "-" .. column
  end
  local baseX, baseY = layoutLib.anchorPosition(anchor, rect.w, rect.h, screen.width, screen.height, margin)
  -- x/y relativos a la caja del output, igual que resolveGeometry().
  return {
    anchor = anchor,
    dx = math.floor((rect.x - screen.x) - baseX),
    dy = math.floor((rect.y - screen.y) - baseY),
    width = rect.w,
    height = rect.h,
  }
end

function M.layoutString(rect, screen, margin)
  local memory = M.anchorFromRect(rect, screen, margin)
  return string.format("%s, %dx%d, %d, %d", memory.anchor, memory.width, memory.height, memory.dx, memory.dy)
end

function M.geometryFromMemory(value, screenWidth, screenHeight, margin)
  local parsed = layoutLib.parseLayout(value)
  if parsed == nil or parsed.valid ~= true then return nil end
  if parsed.anchor == nil or parsed.auto == true or parsed.custom == true then return nil end
  local width = parsed.width
  local height = parsed.height
  if width == nil or height == nil then return nil end
  local baseX, baseY = layoutLib.anchorPosition(parsed.anchor, width, height, screenWidth, screenHeight, margin)
  return {
    x = baseX + (parsed.dx or 0),
    y = baseY + (parsed.dy or 0),
    width = width,
    height = height,
  }
end

return M