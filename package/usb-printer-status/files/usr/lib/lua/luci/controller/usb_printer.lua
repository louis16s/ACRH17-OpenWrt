module("luci.controller.usb_printer", package.seeall)

function index()
	entry({"admin", "services", "usb-printer"}, cbi("usb_printer"), _("USB 打印机状态"), 62).dependent = false
end
