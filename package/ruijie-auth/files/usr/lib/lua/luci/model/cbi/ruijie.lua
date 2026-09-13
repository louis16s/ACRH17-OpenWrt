local sys = require "luci.sys"
local util = require "luci.util"

local function trim(value)
	return (value or ""):gsub("^%s+", ""):gsub("%s+$", "")
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
dashboard.action_result = ({
	success = translate("成功"),
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
actions = m:section(NamedSection, "main", "main", translate("认证操作"))
actions.description = translate("操作会在后台执行，页面不会等待校园门户的完整响应。")
local function action(name, title, command, style)
	-- The button carries its own label, so the option gets an empty title:
	-- otherwise CBI prints the same text again as a <label> above it.
	local button = actions:option(Button, name, "")
	button.inputtitle = title
	button.inputstyle = style or "apply"
	function button.write()
		sys.call("(umask 077; flock -n 8 || exit 75; printf 'result=running\\n' >/tmp/ruijie-auth.action; " .. command .. " >>/tmp/ruijie-auth.action 2>&1; rc=$?; [ $rc -eq 0 ] && printf 'result=success\\n' >>/tmp/ruijie-auth.action || printf 'result=failed\\n' >>/tmp/ruijie-auth.action; logger -t ruijie-auth 'LuCI action completed') 8>/tmp/ruijie-auth.action.lock </dev/null >/dev/null 2>&1 &")
		m.message = translate("操作已提交。认证请求在后台以短超时执行；刷新页面可查看明确结果。")
	end
end

action("login", translate("立即登录"), "/usr/libexec/ruijie-auth login")
action("logout", translate("注销认证"), "/usr/libexec/ruijie-auth logout", "reset")
action("reauth", translate("重新认证"), "/usr/libexec/ruijie-auth reauth")
action("restart", translate("重启认证服务"), "/etc/init.d/ruijie-auth restart")
action("renew", translate("重新获取 WAN DHCP"), "/usr/libexec/ruijie-auth renew-wan")
action("refresh", translate("重新抓取 queryString"), "/usr/libexec/ruijie-refresh-query capture")
action("clear", translate("清除最近认证结果"), "/usr/libexec/ruijie-auth clear", "reset")

-- Passwords do change out from under a router (campus-wide resets), and the
-- old one is worthless the moment it stops being accepted. Keep the value
-- being replaced in password_prev so the change is always one click back.
local value_write = Value.write or AbstractValue.write
local function remember_password(self, section, value)
	local previous = trim(self.map:get(section, self.option))
	-- Re-saving an unchanged value must not overwrite the rollback point.
	if trim(value) ~= "" and previous ~= "" and trim(value) ~= previous then
		self.map:set(section, "password_prev", previous)
	end
	value_write(self, section, value)
end

action("pw_check", translate("验证当前密码"), "/usr/libexec/ruijie-password check")
action("pw_revert", translate("回退到上一个密码"), "/usr/libexec/ruijie-password revert", "reset")
action("pw_drop", translate("丢弃密码回退点"), "/usr/libexec/ruijie-password drop", "reset")

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
o.description = translate("请填入门户实际请求中的 password 字段值；部分门户不接受明文密码。保存新值时，被替换的旧值会自动存进回退点。")

local rollback = auth:option(DummyValue, "password_rollback", translate("密码回退点"))
function rollback.cfgvalue()
	local previous = trim(cursor:get("ruijie", "main", "password_prev") or "")
	if previous == "" then
		return translate("无。保存新密码时会自动把旧密码存进来。")
	end
	return translate("已保存") .. "：" .. string.format(translate("%d 位，末两位 %s"), #previous, previous:sub(-2))
		.. translate("。上面两个按钮可以换回或丢弃。")
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
