module("luci.controller.uuplugin", package.seeall)

function index()
	-- 页面就是这套配置的入口：/etc/config/uuplugin 不在，说明包没装或已被移除。
	if not require("nixio.fs").access("/etc/config/uuplugin") then
		return
	end
	entry({"admin", "services", "uuplugin"}, cbi("uuplugin"), _("UU 加速器"), 62).dependent = false
end
