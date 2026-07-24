-- Forward-auth action for HAProxy 3.2.
--
-- The authentication request is deliberately constructed from an allowlist.
-- In particular, Connection, Upgrade, and Sec-WebSocket-* are never copied.

local AUTH_URL = os.getenv("FORWARD_AUTH_URL")
  or (
    "http://127.0.0.1:10080"
      .. "/outpost.goauthentik.io/auth/nginx"
  )
local AUTH_TIMEOUT_MS = 3000
local MAX_HEADER_VALUE_LENGTH = 16384

local IDENTITY_HEADERS = {
  "x-authentik-username",
  "x-authentik-groups",
  "x-authentik-entitlements",
  "x-authentik-email",
  "x-authentik-name",
  "x-authentik-uid",
  "x-authentik-jwt",
  "x-authentik-meta-jwks",
  "x-authentik-meta-outpost",
  "x-authentik-meta-provider",
  "x-authentik-meta-app",
  "x-authentik-meta-version",
}

local function first_header(headers, name)
  local values = headers[name]
  if values == nil then
    return nil
  end

  local value = values[0]
  if value == nil then
    value = values[1]
  end
  if type(value) ~= "string" or #value > MAX_HEADER_VALUE_LENGTH then
    return nil
  end
  return value
end

local function request_header(headers, name)
  local value = first_header(headers, name)
  if value == nil or value == "" then
    return nil
  end
  return { value }
end

local function set_result(txn, result, location, set_cookie)
  txn:set_var("txn.forward_auth_result", result)

  if location ~= nil then
    txn:set_var("txn.forward_auth_location", location)
  else
    txn:unset_var("txn.forward_auth_location")
  end

  if set_cookie ~= nil then
    txn:set_var("txn.forward_auth_set_cookie", set_cookie)
  else
    txn:unset_var("txn.forward_auth_set_cookie")
  end
end

local function percent_encode(value)
  return (value:gsub("[^A-Za-z0-9%-._~]", function(character)
    return string.format("%%%02X", string.byte(character))
  end))
end

local function allowed_redirect(location, protected_host)
  if location == nil then
    return nil
  end
  if location:sub(1, 1) == "/" and location:sub(1, 2) ~= "//" then
    return location
  end

  local origin = "https://" .. protected_host
  if location:sub(1, #origin + 1) == origin .. "/" then
    return location
  end
  return nil
end

local function forward_auth(txn)
  local request_headers = txn.http:req_get_headers()
  local host = first_header(request_headers, "host")
  if host == nil then
    set_result(txn, "error", nil, nil)
    return
  end

  host = string.lower((host:gsub(":%d+$", "")))
  if host == "" or not host:match("^[a-z0-9][a-z0-9.-]*[a-z0-9]$") then
    set_result(txn, "error", nil, nil)
    return
  end

  -- Remove identity supplied by the client before doing any fallible work.
  for _, name in ipairs(IDENTITY_HEADERS) do
    txn.http:req_del_header(name)
  end

  local method = txn.sf:method()
  local request_url = txn.sf:url()
  local client_ip = txn.sf:src()
  local origin = "https://" .. host
  local original_url
  if request_url:sub(1, #origin + 1) == origin .. "/" then
    -- HAProxy can expose an absolute URL for HTTP/2 requests.
    original_url = request_url
  elseif request_url:sub(1, 1) == "/" then
    original_url = origin .. request_url
  else
    set_result(txn, "error", nil, nil)
    return
  end

  local auth_headers = {
    ["host"] = { host },
    ["x-original-url"] = { original_url },
    ["x-real-ip"] = { client_ip },
    ["x-forwarded-for"] = { client_ip },
    ["x-forwarded-host"] = { host },
    ["x-forwarded-method"] = { method },
    ["x-forwarded-proto"] = { "https" },
    ["connection"] = { "close" },
  }

  for _, name in ipairs({ "cookie", "authorization", "user-agent", "accept" }) do
    local value = request_header(request_headers, name)
    if value ~= nil then
      auth_headers[name] = value
    end
  end

  local ok, response = pcall(function()
    local client = core.httpclient()
    return client:head({
      url = AUTH_URL,
      headers = auth_headers,
      timeout = AUTH_TIMEOUT_MS,
    })
  end)

  if not ok or type(response) ~= "table" or type(response.status) ~= "number" then
    txn:Warning("forward-auth result=error reason=invalid-httpclient-response")
    set_result(txn, "error", nil, nil)
    return
  end

  local status = response.status
  local response_headers = response.headers or {}
  local set_cookie = first_header(response_headers, "set-cookie")

  if status >= 200 and status <= 299 then
    for _, name in ipairs(IDENTITY_HEADERS) do
      local value = first_header(response_headers, name)
      if value ~= nil then
        txn.http:req_set_header(name, value)
      end
    end
    set_result(txn, "allow", nil, set_cookie)
    return
  end

  if status == 401 then
    local sign_in =
      "/outpost.goauthentik.io/start?rd=" .. percent_encode(original_url)
    set_result(
      txn,
      "unauthorized",
      sign_in,
      set_cookie
    )
    return
  end

  if status == 403 then
    set_result(txn, "forbidden", nil, set_cookie)
    return
  end

  if status == 301 or status == 302 or status == 303 or status == 307 or status == 308 then
    local response_location =
      allowed_redirect(first_header(response_headers, "location"), host)
    if response_location ~= nil then
      local sign_in =
        "/outpost.goauthentik.io/start?rd=" .. percent_encode(original_url)
      set_result(
        txn,
        "unauthorized",
        sign_in,
        set_cookie
      )
      return
    end
  end

  txn:Warning("forward-auth result=error status=" .. tostring(status))
  set_result(txn, "error", nil, nil)
end

core.register_action("materia-forward-auth", { "http-req" }, function(txn)
  local ok, message = pcall(forward_auth, txn)
  if ok then
    return
  end

  txn:Warning("forward-auth result=error exception=" .. tostring(message))
  set_result(txn, "error", nil, nil)
end)
