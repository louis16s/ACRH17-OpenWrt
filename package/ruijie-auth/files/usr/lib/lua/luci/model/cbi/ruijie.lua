local sys = require "luci.sys"

local function trim(value)
	return (value or ""):gsub("^%s+", ""):gsub("%s+$", "")
end

local function state(key)
	return trim(sys.exec("sed -n 's/^" .. key .. "=//p' /tmp/ruijie-auth.state 2>/dev/null | head -n 1"))
end

local function action_result()
	return trim(sys.exec("sed -n 's/^result=//p' /tmp/ruijie-auth.action 2>/dev/null | tail -n 1"))
end

local function wan_name()
	local name = trim(sys.exec("uci -q get ruijie.main.wan_interface"))
	return name:match("^[%w_%-]+$") and name or "wan"
end

local function wan_ipv4()
	return trim(sys.exec("ubus call network.interface." .. wan_name() .. " status 2>/dev/null | jsonfilter -e '@[\"ipv4-address\"][0].address'"))
end

m = Map("ruijie", translate("Ruijie ePortal / 锐捷认证"),
	translate("校园网认证中心。认证请求以短超时在后台运行，刷新页面即可查看执行结果。"))
m:append(Template("ruijie/dashboard"))

status_section = m:section(SimpleSection, translate("当前状态"))
local function display(name, label, value)
	local field = status_section:option(DummyValue, name, label)
	function field.cfgvalue()
		local result = value()
		return result ~= "" and result or "-"
	end
end

display("service", translate("服务状态"), function() return sys.call("/etc/init.d/ruijie-auth running >/dev/null 2>&1") == 0 and translate("Running") or translate("Stopped") end)
display("auth", translate("当前认证状态"), function() return ({ online = translate("已联网"), authenticating = translate("正在认证"), failed = translate("认证失败") })[state("auth_state")] or translate("未联网") end)
display("wan", translate("WAN 接口"), wan_name)
display("ipv4", translate("WAN IPv4 地址"), wan_ipv4)
display("gateway", translate("默认网关"), function() return trim(sys.exec("ip -4 route show default 2>/dev/null | sed -n '1s/.* via \([^ ]*\).*/\1/p'")) end)
display("last_time", translate("最近认证时间"), function() return state("last_time") end)
display("last_result", translate("最近一次认证结果"), function() return state("last_result") end)
display("last_summary", translate("最近认证返回内容摘要"), function() return state("last_summary") end)
display("reconnect", translate("自动重连"), function() return trim(sys.exec("uci -q get ruijie.main.auto_reconnect")) == "1" and translate("已启用") or translate("未启用") end)
display("action_result", translate("最近快捷操作"), function()
	local result = action_result()
	return ({ success = translate("成功"), failed = translate("失败"), running = translate("正在执行") })[result] or "-"
end)

actions = m:section(SimpleSection, translate("认证操作"))
actions.description = translate("操作会在后台执行，页面不会等待校园门户的完整响应。")
local function action(name, title, command, style)
	local button = actions:option(Button, name, title)
	button.inputstyle = style or "apply"
	function button.write()
		sys.call("(printf 'result=running\\n' >/tmp/ruijie-auth.action; " .. command .. " >>/tmp/ruijie-auth.action 2>&1; rc=$?; [ $rc -eq 0 ] && printf 'result=success\\n' >>/tmp/ruijie-auth.action || printf 'result=failed\\n' >>/tmp/ruijie-auth.action; logger -t ruijie-auth 'LuCI action completed') &")
		m.message = translate("操作已提交。认证请求在后台以短超时执行；刷新页面可查看明确结果。")
	end
end

action("login", translate("立即登录"), "/usr/libexec/ruijie-auth login")
action("logout", translate("注销认证"), "/usr/libexec/ruijie-auth logout", "reset")
action("reauth", translate("重新认证"), "/usr/libexec/ruijie-auth reauth")
action("restart", translate("重启认证服务"), "/etc/init.d/ruijie-auth restart")
action("renew", translate("重新获取 WAN DHCP"), "/usr/libexec/ruijie-auth renew-wan")
action("clear", translate("清除最近认证结果"), "/usr/libexec/ruijie-auth clear", "reset")

recovery = m:section(NamedSection, "main", "main", translate("自动恢复"))
o = recovery:option(Flag, "enabled", translate("启用锐捷认证服务")); o.default = 0
o = recovery:option(Flag, "boot_login", translate("开机自动认证")); o.default = 1
o = recovery:option(Flag, "auto_reconnect", translate("断线自动重新认证")); o.default = 1
o = recovery:option(Value, "check_interval", translate("检测间隔（秒）")); o.datatype = "range(15,3600)"; o.default = "60"
o = recovery:option(Value, "retry_interval", translate("失败重试起始间隔（秒）")); o.datatype = "range(10,3600)"; o.default = "30"
o.description = translate("连续失败时按起始值、1.5 倍、2 倍退避并封顶 60 秒；默认序列为 30、45、60、60 秒。")
o = recovery:option(Value, "max_failures", translate("最大连续失败次数")); o.datatype = "range(1,99)"; o.default = "3"
o = recovery:option(ListValue, "failure_action", translate("连续失败后的动作"))
o:value("retry", translate("仅继续重试")); o:value("restart_wan", translate("重启 WAN 接口")); o:value("restart_service", translate("重启锐捷认证服务")); o.default = "retry"
o = recovery:option(Value, "wan_interface", translate("WAN 逻辑接口")); o.default = "wan"
o.description = translate("用于 ubus 状态和按需 DHCP 重拨；填写逻辑接口名，例如 wan。")
o = recovery:option(Flag, "renew_dhcp_on_reauth", translate("重新认证时更新 WAN DHCP")); o.default = 0

auth = m:section(NamedSection, "main", "main", translate("认证参数"))
o = auth:option(Value, "server", translate("Server")); o.placeholder = "http://172.31.0.3"
o = auth:option(Value, "login_path", translate("Login path")); o.default = "/eportal/InterFace.do?method=login"
o = auth:option(Value, "logout_path", translate("Logout path")); o.default = "/eportal/InterFace.do?method=logout"
o = auth:option(Value, "username", translate("userId / account"))
o = auth:option(Value, "password_payload", translate("Password payload")); o.password = true
o.description = translate("请填入门户实际请求中的 password 字段值；部分门户不接受明文密码。")
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

logs = m:section(SimpleSection, translate("最近认证日志"))
recent_log = logs:option(DummyValue, "recent_log", translate("最近 80 行"))
function recent_log.cfgvalue()
	local output = trim(sys.exec("logread -e ruijie-auth 2>/dev/null | tail -n 80"))
	return output ~= "" and output or "-"
end

return m
