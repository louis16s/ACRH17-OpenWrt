local sys = require "luci.sys"

local function trim(value)
	return (value or ""):gsub("^%s+", ""):gsub("%s+$", "")
end

local function command(command)
	return trim(sys.exec(command .. " 2>/dev/null"))
end

local function printer_nodes()
	local nodes = command("ls /dev/usb/lp* 2>/dev/null")
	return nodes ~= "" and nodes or translate("No USB Printer detected")
end

local function lan_ip()
	local ip = command("ubus call network.interface.lan status | jsonfilter -e '@[\"ipv4-address\"][0].address'")
	return ip ~= "" and ip or "-"
end

local function p910_port()
	local offset = tonumber(command("uci -q get p910nd.@p910nd[0].port")) or 0
	return tostring(9100 + offset)
end

m = SimpleForm("usb_printer", translate("USB 打印机状态"),
	translate("通过 p910nd 提供轻量 RAW TCP 打印共享。本页不安装 CUPS、驱动或打印队列。"))

s = m:section(SimpleSection)
local function display(name, label, value)
	local field = s:option(DummyValue, name, label)
	function field.cfgvalue()
		local result = value()
		return result ~= "" and result or "-"
	end
end

display("printer", translate("USB printer devices"), printer_nodes)
display("usb", translate("USB vendor / product / name"), function() return command("lsusb | head -n 32") end)
display("service", translate("p910nd service"), function() return sys.call("/etc/init.d/p910nd running >/dev/null 2>&1") == 0 and translate("Running") or translate("Stopped") end)
display("configured", translate("Configured p910nd device"), function() return command("uci -q get p910nd.@p910nd[0].device") end)
display("port", translate("RAW TCP port"), p910_port)
display("lan", translate("LAN address"), lan_ip)
display("hint", translate("Client setup hint"), function() return translate("Windows/macOS: add a RAW/AppSocket printer at ") .. lan_ip() .. ":" .. p910_port() end)

local function service_button(name, title, action, style)
	local button = s:option(Button, name, title)
	button.inputstyle = style
	function button.write()
		local rc = sys.call("/etc/init.d/p910nd " .. action .. " >/dev/null 2>&1")
		m.message = rc == 0 and translate("p910nd command completed") or translate("p910nd command failed")
	end
end

service_button("start", translate("Start p910nd"), "start", "apply")
service_button("stop", translate("Stop p910nd"), "stop", "reset")
service_button("restart", translate("Restart p910nd"), "restart", "apply")

return m
