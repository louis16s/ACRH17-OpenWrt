local sys = require "luci.sys"

m = Map("ruijie", translate("Ruijie ePortal Authentication"),
	translate("Configure the Ruijie/ePortal HTTP authentication parameters captured from your school's login request."))

s = m:section(NamedSection, "main", "main", translate("Authentication"))

o = s:option(Flag, "enabled", translate("Enable automatic authentication"))
o.default = 0

o = s:option(Value, "server", translate("Server"))
o.placeholder = "http://172.31.0.3"

o = s:option(Value, "login_path", translate("Login path"))
o.default = "/eportal/InterFace.do?method=login"

o = s:option(Value, "logout_path", translate("Logout path"))
o.default = "/eportal/InterFace.do?method=logout"

o = s:option(Value, "username", translate("userId / account"))

o = s:option(Value, "password_payload", translate("Password payload"))
o.password = true
o.description = translate("Paste the password value exactly as captured. Some portals do not accept the plaintext password.")

o = s:option(Value, "service", translate("Service"))

o = s:option(Value, "query_string", translate("queryString"))

o = s:option(Value, "cookie", translate("Cookie"))

o = s:option(Value, "referer", translate("Referer"))

o = s:option(Value, "operator_pwd", translate("operatorPwd"))
o.optional = true

o = s:option(Value, "operator_user_id", translate("operatorUserId"))
o.optional = true

o = s:option(Value, "validcode", translate("validcode"))
o.optional = true

o = s:option(ListValue, "password_encrypt", translate("passwordEncrypt"))
o:value("true", "true")
o:value("false", "false")
o.default = "true"

o = s:option(Value, "check_url", translate("Internet check URL"))
o.default = "http://connect.rom.miui.com/generate_204"

o = s:option(Value, "check_interval", translate("Reconnect check interval (seconds)"))
o.datatype = "uinteger"
o.default = "60"

st = m:section(TypedSection, "_status", translate("Actions"))
st.anonymous = true
st.addremove = false

online = st:option(DummyValue, "_online", translate("Current connectivity"))
function online.cfgvalue()
	return sys.exec("/usr/libexec/ruijie-auth status 2>/dev/null"):gsub("%s+$","")
end

last = st:option(DummyValue, "_last", translate("Last portal response"))
function last.cfgvalue()
	return sys.exec("cat /tmp/ruijie-auth.last 2>/dev/null | head -c 600"):gsub("%s+$","")
end

login = st:option(Button, "_login", translate("Login now"))
login.inputstyle = "apply"
function login.write()
	sys.call("/usr/libexec/ruijie-auth login >/tmp/ruijie-auth.last 2>&1")
end

logout = st:option(Button, "_logout", translate("Logout now"))
logout.inputstyle = "reset"
function logout.write()
	sys.call("/usr/libexec/ruijie-auth logout >/tmp/ruijie-auth.last 2>&1")
end

return m
