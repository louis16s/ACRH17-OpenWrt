module("luci.controller.ruijie", package.seeall)

function index()
	if not nixio.fs.access("/etc/config/ruijie") then
		return
	end
	entry({"admin", "services", "ruijie"}, cbi("ruijie"), _("Ruijie ePortal"), 61).dependent = false
end
