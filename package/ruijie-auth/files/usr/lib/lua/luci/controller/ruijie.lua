module("luci.controller.ruijie", package.seeall)

function index()
	if not require("nixio.fs").access("/etc/config/ruijie") then
		return
	end
	entry({"admin", "services", "ruijie"}, cbi("ruijie"), _("锐捷认证"), 61).dependent = false
end
