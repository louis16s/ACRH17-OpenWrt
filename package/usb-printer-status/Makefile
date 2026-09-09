include $(TOPDIR)/rules.mk

PKG_NAME:=usb-printer-status
PKG_VERSION:=1.0.0
PKG_RELEASE:=1
PKGARCH:=all

include $(INCLUDE_DIR)/package.mk

define Package/usb-printer-status
  SECTION:=net
  CATEGORY:=Network
  TITLE:=Lightweight USB printer status page for LuCI
  DEPENDS:=+jsonfilter +luci-compat +p910nd +usbutils
endef

define Package/usb-printer-status/description
 Lightweight status and service controls for USB printers shared by p910nd.
endef

define Build/Prepare
	$(INSTALL_DIR) $(PKG_BUILD_DIR)
endef

define Build/Compile
endef

define Package/usb-printer-status/install
	$(INSTALL_DIR) $(1)/usr/lib/lua/luci/controller
	$(INSTALL_DATA) ./files/usr/lib/lua/luci/controller/usb_printer.lua $(1)/usr/lib/lua/luci/controller/usb_printer.lua
	$(INSTALL_DIR) $(1)/usr/lib/lua/luci/model/cbi
	$(INSTALL_DATA) ./files/usr/lib/lua/luci/model/cbi/usb_printer.lua $(1)/usr/lib/lua/luci/model/cbi/usb_printer.lua
endef

$(eval $(call BuildPackage,usb-printer-status))
