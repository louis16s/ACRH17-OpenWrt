local sys = require "luci.sys"
local util = require "luci.util"

local function trim(value)
	return (value or ""):gsub("^%s+", ""):gsub("%s+$", "")
end

-- Lua 5.1 has no UTF-8 library and # counts bytes. Passwords from this portal
-- are ASCII, but the panel is Chinese and a password may not be, and taking the
-- last two bytes of "密码" returns half a character -- an invalid sequence the
-- browser draws as a replacement box, which tells the user nothing about which
-- password is stored. Count characters, and take whole ones.
local function utf8_length(value)
	local count = 0
	for _ in value:gmatch("[^\128-\191]") do count = count + 1 end
	return count
end

local function utf8_tail(value, wanted)
	local start = #value
	local found = 0
	while start > 0 and found < wanted do
		local byte = value:byte(start)
		start = start - 1
		-- Anything that is not a continuation byte begins a character.
		if byte < 128 or byte >= 192 then found = found + 1 end
	end
	return value:sub(start + 1)
end

-- Read one snapshot per page instead of forking sed/head/uci for each field.
local fs = require "nixio.fs"
local cursor = require("luci.model.uci").cursor()
local state_values = {}
for line in (fs.readfile("/tmp/ruijie-auth.state") or ""):gmatch("[^\n]+") do
	local key, value = line:match("^([^=]+)=(.*)$")
	if key then state_values[key] = value end
end
local function state(key)
	return trim(state_values[key])
end

local function action_result()
	local result = ""
	for line in (fs.readfile("/tmp/ruijie-auth.action") or ""):gmatch("[^\n]+") do
		result = line:match("^result=(.*)$") or result
	end
	return result
end

local function wan_name()
	local name = cursor:get("ruijie", "main", "wan_interface") or "wan"
	return name:match("^[%w_%-]+$") and name or "wan"
end
local wan = wan_name()
local wan_status = util.ubus("network.interface." .. wan, "status") or {}
local function wan_ipv4()
	return ((wan_status["ipv4-address"] or {})[1] or {}).address or ""
end
local function wan_gateway()
	for _, route in ipairs(wan_status.route or {}) do
		if route.target == "0.0.0.0" and route.mask == 0 then
			return route.nexthop or ""
		end
	end
	return ""
end

-- Everything the panel shows is gathered here, once, and handed to the template
-- as plain values: the page must not fork a command per displayed field.
local service_running = sys.call("/etc/init.d/ruijie-auth running >/dev/null 2>&1") == 0
local auth_state = state("auth_state")
local dashboard = Template("ruijie/dashboard")
dashboard.wan = wan
dashboard.ip = wan_ipv4()
dashboard.gateway = wan_gateway()
dashboard.auth = auth_state
dashboard.service = service_running
dashboard.last_result = state("last_result")
dashboard.last_time = state("last_time")
dashboard.last_summary = state("last_summary")
dashboard.reconnect = cursor:get("ruijie", "main", "auto_reconnect") == "1"
-- Four outcomes, not two. "The password was written but nothing proved it" and
-- "another action held the lock, so this one never ran" both used to be shown as
-- 失败, which reads as "the login failed" -- and sends the user to retry a
-- password that may be perfectly good. A single outcome for both also hid the
-- case where the action did not run at all and the panel showed the previous
-- run's success.
dashboard.action_result = ({
	success = translate("成功"),
	unverified = translate("已写入，但未能验证"),
	busy = translate("另一个操作正在运行，本次未执行"),
	failed = translate("失败"),
	running = translate("正在执行"),
})[action_result()]
-- Section titles the page script keeps folded on load, "|" separated.
dashboard.collapse = translate("认证参数")

m = Map("ruijie", translate("Ruijie ePortal / 锐捷认证"),
	translate("校园网认证中心。认证请求以短超时在后台运行，刷新页面即可查看执行结果。"))
m:append(dashboard)

-- Buttons must live in a named section. A SimpleSection keeps no section name,
-- and CBI parses its children through Node.parse with no section argument, so
-- every Button lands in AbstractValue.parse with a nil section and the whole
-- form POST dies on the resulting cbid() concatenation.
local function action_group(title, description)
	local section = m:section(NamedSection, "main", "main", translate(title))
	if description then section.description = translate(description) end
	return section
end

local function action(section, name, title, command, style)
	-- The button carries its own label, so the option gets an empty title:
	-- otherwise CBI prints the same text again as a <label> above it.
	local button = section:option(Button, name, "")
	button.inputtitle = translate(title)
	button.inputstyle = style or "apply"
	function button.write()
		-- The action file is the only thing the panel reads, so every outcome has
		-- to be written to it -- including "this never ran". The lock test used
		-- to come first and leave without touching the file, which left the
		-- previous run's answer on screen: the panel reported 成功 for an action
		-- that was dropped before it started. Exit codes are mapped apart rather
		-- than collapsed, so a lock collision and an unverified write stop
		-- looking like a failed login.
		local shell = "(umask 077; "
			.. "flock -n 8 || { printf 'result=busy\\n' >/tmp/ruijie-auth.action; exit 75; }; "
			.. "printf 'result=running\\n' >/tmp/ruijie-auth.action; "
			.. command .. " >>/tmp/ruijie-auth.action 2>&1; rc=$?; "
			.. "case $rc in "
			.. "0) printf 'result=success\\n' >>/tmp/ruijie-auth.action;; "
			.. "2) printf 'result=unverified\\n' >>/tmp/ruijie-auth.action;; "
			.. "75) printf 'result=busy\\n' >>/tmp/ruijie-auth.action;; "
			.. "*) printf 'result=failed\\n' >>/tmp/ruijie-auth.action;; esac; "
			.. "logger -t ruijie-auth 'LuCI action completed') "
			.. "8>/tmp/ruijie-auth.action.lock </dev/null >/dev/null 2>&1 &"
		sys.call(shell)
		m.message = translate("操作已提交。认证请求在后台以短超时执行；刷新页面可查看明确结果。")
	end
end

-- One section per group. CBI stacks every option of a section in a single
-- column, so ten buttons in one section is a ten-row list; splitting them puts
-- the buttons that belong to the same job on the same row.
local session = action_group("认证操作",
	"操作会在后台执行，页面不会等待校园门户的完整响应。")
action(session, "login", "立即登录", "/usr/libexec/ruijie-auth login")
action(session, "logout", "注销认证", "/usr/libexec/ruijie-auth logout", "reset")
action(session, "reauth", "重新认证", "/usr/libexec/ruijie-auth reauth")

local network = action_group("服务与网络",
	"门户换了地址、或者本地状态已经过期时，按 WAN 地址、queryString、认证服务的顺序重来一遍。")
action(network, "renew", "重新获取 WAN DHCP", "/usr/libexec/ruijie-auth renew-wan")
action(network, "refresh", "重新抓取 queryString", "/usr/libexec/ruijie-refresh-query capture")
action(network, "restart", "重启认证服务", "/etc/init.d/ruijie-auth restart")
action(network, "clear", "清除最近认证结果", "/usr/libexec/ruijie-auth clear", "reset")

-- Passwords do change out from under a router (campus-wide resets), and the
-- old one is worthless the moment it stops being accepted. Keep the value
-- being replaced in password_prev so the change is always one click back.
local value_write = Value.write or AbstractValue.write
local function remember_password(self, section, value)
	local current = self.map:get(section, self.option)
	local previous = trim(current)
	-- Re-saving an unchanged value must not overwrite the rollback point. The
	-- comparison is on the raw values -- the same ones CBI compared to decide
	-- whether to call this at all. Trimming here would let a value that differs
	-- only in surrounding whitespace be saved without recording what it
	-- replaced, and the value it replaced is then the only password still known
	-- to work. The command line compares raw values too, so this is also what
	-- keeps the two paths from disagreeing.
	if trim(value) ~= "" and previous ~= "" and value ~= current then
		-- password_prev moves with every save, so saving the page twice pushes
		-- the value the router shipped with out of reach. Anchor it once in
		-- password_original and never move it again. The test is whether the
		-- option has ever been written, not whether its value is non-empty: the
		-- shipped payload is empty, so an emptiness test anchors one save too
		-- late -- onto a value that had itself just been replaced, and in the
		-- worst case onto one the portal had already turned down.
		if self.map:get(section, "password_original") == nil then
			self.map:set(section, "password_original", previous)
		end
		self.map:set(section, "password_prev", previous)
	end
	value_write(self, section, value)
end

local passwords = action_group("密码管理",
	"保存新密码时旧值会自动存进回退点，这里可以验证当前密码、换回上一个或最初密码、丢弃回退点。")
action(passwords, "pw_check", "验证当前密码", "/usr/libexec/ruijie-password check")
action(passwords, "pw_revert", "回退到上一个密码", "/usr/libexec/ruijie-password revert", "reset")
action(passwords, "pw_original", "回退到最初密码", "/usr/libexec/ruijie-password revert --original", "reset")
action(passwords, "pw_drop", "丢弃密码回退点", "/usr/libexec/ruijie-password drop", "reset")

recovery = m:section(NamedSection, "main", "main", translate("自动恢复"))
o = recovery:option(Flag, "enabled", translate("启用锐捷认证服务")); o.default = 0
o = recovery:option(Flag, "boot_login", translate("开机自动认证")); o.default = 1
o = recovery:option(Flag, "auto_reconnect", translate("断线自动重新认证")); o.default = 1
o = recovery:option(Value, "check_interval", translate("检测间隔（秒）")); o.datatype = "range(15,3600)"; o.default = "60"
o = recovery:option(Value, "retry_interval", translate("失败重试起始间隔（秒）")); o.datatype = "range(10,60)"; o.default = "30"
o.description = translate("连续失败时按起始值、1.5 倍、2 倍退避并封顶 60 秒；默认序列为 30、45、60、60 秒。")
o = recovery:option(Value, "max_failures", translate("最大连续失败次数")); o.datatype = "range(1,99)"; o.default = "3"
o = recovery:option(ListValue, "failure_action", translate("连续失败后的动作"))
o:value("retry", translate("仅继续重试")); o:value("restart_wan", translate("重启 WAN 接口")); o:value("restart_service", translate("重启锐捷认证服务")); o.default = "retry"
o = recovery:option(Value, "wan_interface", translate("WAN 逻辑接口")); o.default = "wan"
o.description = translate("用于 ubus 状态和按需 DHCP 重拨；填写逻辑接口名，例如 wan。")
o = recovery:option(Flag, "renew_dhcp_on_reauth", translate("重新认证时更新 WAN DHCP")); o.default = 0
o = recovery:option(Flag, "auto_refresh_query", translate("登录失败时重新抓取 queryString")); o.default = 1
o.description = translate("queryString 与 WAN 当时的 IP、MAC 绑定。换了地址后旧串永远登录不上，开启后守护进程会从校园门户的跳转里重抓一份再试一次，而不是无限重试同一个废串。")

auth = m:section(NamedSection, "main", "main", translate("认证参数"))
o = auth:option(Value, "server", translate("Server")); o.placeholder = "http://172.31.0.3"
o = auth:option(Value, "login_path", translate("Login path")); o.default = "/eportal/InterFace.do?method=login"
o = auth:option(Value, "logout_path", translate("Logout path")); o.default = "/eportal/InterFace.do?method=logout"
o = auth:option(Value, "username", translate("userId / account"))
o = auth:option(Value, "password_payload", translate("Password payload")); o.password = true
o.write = remember_password
o.description = translate("请填入门户实际请求中的 password 字段值；部分门户不接受明文密码。保存新值时，被替换的旧值会自动存进回退点，最初那个值单独留一份，反复保存也不会被挤掉。网页保存不做在线验证，要确认新密码能不能登录请用下面的「验证当前密码」。")

local rollback = auth:option(DummyValue, "password_rollback", translate("密码回退点"))
function rollback.cfgvalue()
	local function describe(value)
		return string.format(translate("%d 位，末两位 %s"), utf8_length(value), utf8_tail(value, 2))
	end
	local previous = trim(cursor:get("ruijie", "main", "password_prev") or "")
	local original = trim(cursor:get("ruijie", "main", "password_original") or "")
	local text
	if previous == "" then
		text = translate("无。保存新密码时会自动把旧密码存进来。")
	else
		text = translate("已保存") .. "：" .. describe(previous)
			.. translate("。上面的按钮可以换回或丢弃。")
	end
	if original ~= "" then
		text = text .. " " .. translate("最初密码") .. "：" .. describe(original)
			.. translate("，多位保存过也不会丢。")
	end
	return text
end
o = auth:option(Value, "service", translate("Service"))
o = auth:option(Value, "query_string", translate("queryString"))
o = auth:option(Value, "cookie", translate("Cookie")); o.password = true
o = auth:option(Value, "referer", translate("Referer"))
o = auth:option(Value, "operator_pwd", translate("operatorPwd")); o.password = true; o.optional = true
o = auth:option(Value, "operator_user_id", translate("operatorUserId")); o.optional = true
o = auth:option(Value, "validcode", translate("validcode")); o.optional = true
o = auth:option(ListValue, "password_encrypt", translate("passwordEncrypt"))
o:value("true", "true"); o:value("false", "false"); o.default = "true"
o = auth:option(Value, "check_url", translate("联网检测 URL")); o.default = "http://connect.rom.miui.com/generate_204"
o = auth:option(Value, "interface", translate("校园网物理 WAN 设备"))
o.description = translate("可选，例如 eth0.2。认证请求绑定校园出口，避免 USB 备用网络掩盖校园认证掉线。")

-- A Template node, not a SimpleSection: the log is one preformatted block and
-- needs no form field of its own.
logs = Template("ruijie/logs")
logs.lines = trim(sys.exec("logread -e ruijie-auth 2>/dev/null | tail -n 80"))
m:append(logs)

return m
