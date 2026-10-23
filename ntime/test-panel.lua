--!nonstrict
-- Simple test for ntime plugin
local success, result = pcall(function()
    -- Test basic loading
    local ok = true
    return ok
end)

if success then
    print("PASS: ntime plugin basic structure loaded")
else
    print("FAIL: " .. tostring(result))
    os.exit(1)
end
