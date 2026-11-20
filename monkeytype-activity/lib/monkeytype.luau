--!nonstrict

-- The MonkeyType API as this plugin sees it: request shapes, error mapping and
-- the one place that has to know how the responses are wrapped.
--
-- Authentication is an Ape Key (`Authorization: ApeKey <key>`), generated in
-- MonkeyType under Settings -> Ape Keys. Requests go through `noctalia.http`,
-- so the key never reaches a process command line.

local Monkeytype = {}

Monkeytype.BASE_URL = "https://api.monkeytype.com"

-- Shared status vocabulary published to the widget and the panel.
Monkeytype.STATUS = {
  AUTH = "auth_error",
  INVALID_KEY = "invalid_key",
  RATE_LIMITED = "rate_limited",
  REQUEST = "request_error",
  RESPONSE = "invalid_response",
  NO_ACTIVITY = "no_activity",
}

function Monkeytype.request(path, key)
  return {
    url = Monkeytype.BASE_URL .. path,
    method = "GET",
    headers = {
      "Accept: application/json",
      "Authorization: ApeKey " .. key,
    },
  }
end

-- The API answers 470/471/472 for unusable Ape keys and 429/479 for rate
-- limits; anything else is a plain failure.
function Monkeytype.statusFor(httpStatus)
  if httpStatus == 401 then
    return Monkeytype.STATUS.AUTH
  end
  if httpStatus == 470 or httpStatus == 471 or httpStatus == 472 then
    return Monkeytype.STATUS.INVALID_KEY
  end
  if httpStatus == 429 or httpStatus == 479 then
    return Monkeytype.STATUS.RATE_LIMITED
  end
  return Monkeytype.STATUS.REQUEST
end

-- Decode one `{ ok, status, body }` response into its `data` payload.
-- `no_activity` means the account has nothing saved yet, which is a normal
-- state, not an error.
--
-- The host reports `ok = true` for any completed transfer, including a 4xx
-- answer, so the HTTP status decides whether the payload is usable.
function Monkeytype.payload(response, decodeJson)
  if type(response) ~= "table" then
    return nil, Monkeytype.STATUS.REQUEST
  end

  local status = response.status
  if type(status) ~= "number" or status < 200 or status > 299 then
    return nil, Monkeytype.statusFor(status)
  end
  if response.ok ~= true then
    return nil, Monkeytype.STATUS.REQUEST
  end

  local envelope = type(decodeJson) == "function" and decodeJson(response.body or "") or nil
  if type(envelope) ~= "table" then
    return nil, Monkeytype.STATUS.RESPONSE
  end

  local data = envelope.data
  if data == nil then
    return nil, Monkeytype.STATUS.NO_ACTIVITY
  end
  if type(data) ~= "table" then
    return nil, Monkeytype.STATUS.RESPONSE
  end

  return data
end

-- Length of a flat numeric array as it appears in the response body.
--
-- The JSON decoder maps `null` to `nil`, and `#table` stops at the first hole,
-- so a `testsByDays` window that ends with test-free days would look shorter
-- than it is. Counting the separators in the body keeps the real window length
-- (and with it the day alignment) intact.
function Monkeytype.arrayLength(body, field)
  if type(body) ~= "string" or type(field) ~= "string" then
    return nil
  end

  local start = string.find(body, '"' .. field .. '"%s*:%s*%[')
  if start == nil then
    return nil
  end

  local open = string.find(body, "[", start, true)
  if open == nil then
    return nil
  end

  local depth = 0
  local separatorCount = 0
  local valueCount = 0
  for index = open, #body do
    local char = string.sub(body, index, index)
    if char == "[" then
      depth = depth + 1
    elseif char == "]" then
      depth = depth - 1
      if depth == 0 then
        return separatorCount + valueCount
      end
    elseif depth == 1 then
      if char == "," then
        separatorCount = separatorCount + 1
      elseif char ~= " " and char ~= "\t" and char ~= "\n" and char ~= "\r" then
        valueCount = 1
      end
    end
  end

  return separatorCount + valueCount
end

-- Profile URL for the optional username setting, or nil when unset.
function Monkeytype.profileUrl(username)
  if type(username) ~= "string" then
    return nil
  end

  local name = string.gsub(username, "[^%w_%-]", "")
  if name == "" then
    return nil
  end

  return "https://monkeytype.com/profile/" .. name
end

return Monkeytype
