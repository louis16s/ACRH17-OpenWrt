local fs = require "nixio.fs"
local nixio = require "nixio"
local sys = require "luci.sys"
local uu = require "uuplugin.state"

local BIN_DIR = "/usr/lib/uu"
local ID_DIR = "/etc/uu/id"
local RUN_DIR = "/tmp/uu"
local CLOUD_PORT = 16000
local API_PORT = 16363

local function trim(value)
	return (value or ""):match("^%s*(.-)%s*$")
end

local function readfile(path)
	return trim(fs.readfile(path) or "")
end

-- 运行副本是插件此刻真正在用的值；持久副本是重启后会被回填的那个。两者不同
-- 只会在「刚在 App 里重绑定、还没停过服务」时出现，而重启就会回到旧值，所以
-- 这个差异要显示出来，不能挑一个显示就算了。
local function read_pair(name)
	local live = readfile(RUN_DIR .. "/" .. name)
	local saved = readfile(ID_DIR .. "/" .. name)
	return live, saved
end

-- 云端通道的判据与运维手册里的 netstat | grep :16000 是同一条：连接处于
-- ESTABLISHED，且这条 socket 的 inode 在插件的 fd 里。只看端口，会在别的进程
-- 恰好连上 16000 时报「已连接」——错在更危险的那一侧。
local function connected(pids)
	return uu.cloud_connected(pids, {
		fs.readfile("/proc/net/tcp") or "",
		fs.readfile("/proc/net/tcp6") or "",
	}, CLOUD_PORT, fs.readlink)
end

-- 本地 API 是 App 在局域网里认设备的那一面：连得上就说明进程在服务，返回的 sn
-- 还能用来核对运行实例与页面显示的是不是同一个身份。
local function api_probe()
	local sock = nixio.socket("inet", "stream")
	if not sock then return nil end
	sock:settimeout(1)
	if not sock:connect("127.0.0.1", API_PORT) then
		sock:close()
		return nil
	end
	sock:send("GET /router HTTP/1.0\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n")

	local parts, total = {}, 0
	while total < 8192 do
		local chunk = sock:recv(2048)
		if not chunk or chunk == "" then break end
		parts[#parts + 1] = chunk
		total = total + #chunk
	end
	sock:close()

	local response = table.concat(parts)
	local header = response:find("\r\n\r\n", 1, true)
	return header and response:sub(header + 4) or ""
end

local pids = {}
for pid in (sys.exec("pidof uuplugin 2>/dev/null; pidof xuplugin-guardian 2>/dev/null") or ""):gmatch("%d+") do
	pids[#pids + 1] = pid
end
local running = #pids > 0

local sn_live, sn_saved = read_pair(".sn")
local sn = sn_live ~= "" and sn_live or sn_saved
local activated = select(1, read_pair("activate_status"))
local version = readfile(BIN_DIR .. "/uu.conf"):match("version=([^\r\n%s]+)") or ""

-- 进程没起来时这两项必然是否定的，就别去连本地端口（connect 要等 1 秒超时）、
-- 也别去读两张 /proc/net/tcp*：页面打开的速度不该由「插件没开」决定。
local api_body = running and api_probe() or nil
local api_sn = api_body and api_body:match('"sn"%s*:%s*"([^"]*)"') or nil
local api_model = api_body and api_body:match('"model"%s*:%s*"([^"]*)"') or nil

local cloud = running and connected(pids) or false

local dashboard = Template("uuplugin/dashboard")
dashboard.state = running and (cloud and "online" or "working") or "offline"
dashboard.process = running and translate("运行中") or translate("已停止")
dashboard.process_hint = running and ("pid " .. table.concat(pids, ", "))
	or translate("procd 未持有进程")
dashboard.cloud = cloud and translate("已连接") or translate("未连接")
dashboard.cloud_hint = ("云端 :%d"):format(CLOUD_PORT)
dashboard.api = api_body and translate("有响应") or translate("无响应")
dashboard.api_hint = "127.0.0.1:" .. API_PORT
if api_model and api_model ~= "" then
	dashboard.api_hint = dashboard.api_hint .. " · " .. api_model
end
dashboard.sn = sn ~= "" and sn or translate("未生成")
if sn == "" then
	dashboard.sn_hint = translate("插件首次启动时写入")
elseif sn_live ~= "" and sn_saved ~= "" and sn_live ~= sn_saved then
	dashboard.sn_hint = translate("与持久副本不同，重启会回到旧身份")
else
	dashboard.sn_hint = translate("持久副本 /etc/uu/id/.sn")
end
if api_sn and api_sn ~= "" and sn ~= "" and api_sn ~= sn then
	dashboard.api_hint = translate("运行实例的 sn 与页面身份不同")
end
dashboard.activated = activated ~= "" and activated:sub(1, 60):gsub("\n", " ")
	or translate("未激活")
dashboard.activated_hint = translate("App 端绑定状态，语义由插件自行维护")
dashboard.version = version ~= "" and version or translate("未知")
dashboard.version_hint = translate("随固件冻结，不做运行时自更新")

m = Map("uuplugin", translate("UU 加速器 / 远程开机"),
	translate("网易 UU 路由器插件。它作为单个 procd 服务常驻，用云端通道收发唤醒包；"
		.. "设备身份保存在 /etc/uu/id，重启与 sysupgrade 都不会丢。"))
m:append(dashboard)

-- 按钮必须落在具名 section 里：SimpleSection 不记 section 名，CBI 解析它的子节点
-- 时 section 为 nil，整张表单会在提交时挂掉。
local function action_group(title, description)
	local section = m:section(NamedSection, "main", "main", translate(title))
	if description then section.description = translate(description) end
	return section
end

local function action(section, name, title, command, style)
	-- 按钮自带标题，option 的标题留空，否则 CBI 会在上面再印一遍同样的字。
	local button = section:option(Button, name, "")
	button.inputtitle = translate(title)
	button.inputstyle = style or "apply"
	function button.write()
		local rc = sys.call(command)
		m.message = rc == 0 and translate("已执行，上方状态会随页面刷新更新。")
			or translate("命令返回 %d，请查看下方日志。"):format(rc)
	end
end

local service = action_group("服务控制",
	"启停由 procd 管理；停止时把身份写回 /etc/uu/id，并清掉插件自己建的 nft 表。")
action(service, "start", "启动", "/etc/init.d/uuplugin start")
action(service, "stop", "停止", "/etc/init.d/uuplugin stop", "reset")
action(service, "restart", "重启", "/etc/init.d/uuplugin restart")

local settings = action_group("服务设置",
	"关掉开关后 procd 不再拉起插件；日志级别只改运行副本，包内 uu.conf 保持原样。")

local enabled = settings:option(Flag, "enabled", translate("启用插件"))
enabled.default = "1"
enabled.rmempty = false
enabled.description = translate("立即生效：打开时重启插件，关闭时停止它。")
local write_enabled = enabled.write
function enabled.write(self, section, value)
	write_enabled(self, section, value)
	sys.call("/etc/init.d/uuplugin " .. (value == "1" and "restart" or "stop"))
end

local level = settings:option(ListValue, "log_level", translate("日志级别"))
level:value("info", "info")
level:value("debug", "debug")
level.default = "info"
level.description = translate("日志走 syslog，页面底部可以直接看。保存后重启插件生效。")
local write_level = level.write
function level.write(self, section, value)
	write_level(self, section, value)
	sys.call("/etc/init.d/uuplugin restart")
end

local logs = Template("uuplugin/logs")
logs.lines = trim(sys.exec("logread -e uuplugin 2>/dev/null | tail -n 80"))
m:append(logs)

return m
