-- Mirakurun forward-auth PoC for HAProxy 3.2.
--
-- The authentication request is deliberately constructed from an allowlist.
-- In particular, Connection, Upgrade, and Sec-WebSocket-* are never copied.

local AUTH_URL = os.getenv("MATERIA_FORWARD_AUTH_URL")
  or (
    "http://127.0.0.1:10080"
      .. "/outpost.goauthentik.io/auth/nginx"
  )
local AUTH_TIMEOUT_MS = 3000
local PROTECTED_HOST = "mirakurun.ggrel.net"
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

local function elapsed_ms(started_at)
  local finished_at = core.now()
  return (finished_at.sec - started_at.sec) * 1000
    + math.floor((finished_at.usec - started_at.usec) / 1000)
end

local function set_result(txn, result, status, location, set_cookie, duration_ms)
  txn:set_var("txn.materia_auth_result", result)
  txn:set_var("txn.materia_auth_status", status)
  txn:set_var("txn.materia_auth_duration_ms", duration_ms)

  if location ~= nil then
    txn:set_var("txn.materia_auth_location", location)
  else
    txn:unset_var("txn.materia_auth_location")
  end

  if set_cookie ~= nil then
    txn:set_var("txn.materia_auth_set_cookie", set_cookie)
  else
    txn:unset_var("txn.materia_auth_set_cookie")
  end
end

local function percent_encode(value)
  return (value:gsub("[^A-Za-z0-9%-._~]", function(character)
    return string.format("%%%02X", string.byte(character))
  end))
end

local function allowed_redirect(location)
  if location == nil then
    return nil
  end
  if location:sub(1, 1) == "/" and location:sub(1, 2) ~= "//" then
    return location
  end

  local origin = "https://" .. PROTECTED_HOST
  if location:sub(1, #origin + 1) == origin .. "/" then
    return location
  end
  return nil
end

local function forward_auth(txn)
  local started_at = core.now()
  local request_headers = txn.http:req_get_headers()
  local host = first_header(request_headers, "host")
  if host == nil then
    set_result(txn, "error", 0, nil, nil, elapsed_ms(started_at))
    return
  end

  host = string.lower((host:gsub(":%d+$", "")))
  if host ~= PROTECTED_HOST then
    set_result(txn, "error", 0, nil, nil, elapsed_ms(started_at))
    return
  end

  -- Remove identity supplied by the client before doing any fallible work.
  for _, name in ipairs(IDENTITY_HEADERS) do
    txn.http:req_del_header(name)
  end

  local method = txn.sf:method()
  local request_url = txn.sf:url()
  if request_url:sub(-5) == "//rpc" then
    txn.http:req_set_path("/rpc")
    request_url = request_url:sub(1, -6) .. "/rpc"
  end
  local client_ip = txn.sf:src()
  local origin = "https://" .. PROTECTED_HOST
  local original_url
  if request_url:sub(1, #origin + 1) == origin .. "/" then
    -- HAProxy can expose an absolute URL for HTTP/2 requests.
    original_url = request_url
  elseif request_url:sub(1, 1) == "/" then
    original_url = origin .. request_url
  else
    set_result(txn, "error", 0, nil, nil, elapsed_ms(started_at))
    return
  end
  txn:set_var("txn.materia_original_url", original_url)

  local auth_headers = {
    ["host"] = { PROTECTED_HOST },
    ["x-original-url"] = { original_url },
    ["x-real-ip"] = { client_ip },
    ["x-forwarded-for"] = { client_ip },
    ["x-forwarded-host"] = { PROTECTED_HOST },
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
    txn:Warning("materia-forward-auth result=error status=0")
    txn:set_var("txn.materia_auth_reason", "invalid-httpclient-response")
    set_result(txn, "error", 0, nil, nil, elapsed_ms(started_at))
    return
  end

  local status = response.status
  local reason = response.reason or ""
  local response_headers = response.headers or {}
  local set_cookie = first_header(response_headers, "set-cookie")
  txn:set_var("txn.materia_auth_reason", tostring(reason):sub(1, 128))
  txn:Warning(
    "materia-forward-auth result=response status="
      .. tostring(status)
      .. " reason="
      .. tostring(reason):sub(1, 128)
  )

  if status >= 200 and status <= 299 then
    for _, name in ipairs(IDENTITY_HEADERS) do
      local value = first_header(response_headers, name)
      if value ~= nil then
        txn.http:req_set_header(name, value)
      end
    end
    set_result(txn, "allow", status, nil, set_cookie, elapsed_ms(started_at))
    return
  end

  if status == 401 then
    local sign_in =
      "/outpost.goauthentik.io/start?rd=" .. percent_encode(original_url)
    set_result(
      txn,
      "unauthorized",
      status,
      sign_in,
      set_cookie,
      elapsed_ms(started_at)
    )
    return
  end

  if status == 403 then
    set_result(txn, "forbidden", status, nil, set_cookie, elapsed_ms(started_at))
    return
  end

  if status == 301 or status == 302 or status == 303 or status == 307 or status == 308 then
    local response_location =
      allowed_redirect(first_header(response_headers, "location"))
    if response_location ~= nil then
      local sign_in =
        "/outpost.goauthentik.io/start?rd=" .. percent_encode(original_url)
      set_result(
        txn,
        "unauthorized",
        status,
        sign_in,
        set_cookie,
        elapsed_ms(started_at)
      )
      return
    end
  end

  txn:Warning("materia-forward-auth result=error status=" .. tostring(status))
  set_result(txn, "error", status, nil, nil, elapsed_ms(started_at))
end

core.register_action("materia-forward-auth", { "http-req" }, function(txn)
  local ok, message = pcall(forward_auth, txn)
  if ok then
    return
  end

  txn:Warning("materia-forward-auth result=error exception=" .. tostring(message))
  txn:set_var(
    "txn.materia_auth_reason",
    ("lua-exception-" .. tostring(message)):sub(1, 128)
  )
  set_result(txn, "error", 0, nil, nil, 0)
end)
