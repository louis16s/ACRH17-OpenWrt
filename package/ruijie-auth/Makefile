include $(TOPDIR)/rules.mk

PKG_NAME:=ruijie-auth
PKG_VERSION:=1.1.0
PKG_RELEASE:=2

PKGARCH:=all

include $(INCLUDE_DIR)/package.mk

define Package/ruijie-auth
  SECTION:=net
  CATEGORY:=Network
  TITLE:=Ruijie ePortal authentication helper with LuCI
  DEPENDS:=+curl +ca-bundle +jsonfilter +flock +luci-compat
endef

define Package/ruijie-auth/description
 Lightweight Ruijie ePortal authentication helper using UCI and LuCI.
endef

define Package/ruijie-auth/conffiles
/etc/config/ruijie
endef

define Build/Prepare
	$(INSTALL_DIR) $(PKG_BUILD_DIR)
endef

define Build/Compile
endef

define Package/ruijie-auth/install
	$(INSTALL_DIR) $(1)/etc/config
	$(INSTALL_CONF) ./files/etc/config/ruijie $(1)/etc/config/ruijie
	chmod 600 $(1)/etc/config/ruijie

	$(INSTALL_DIR) $(1)/etc/init.d
	$(INSTALL_BIN) ./files/etc/init.d/ruijie-auth $(1)/etc/init.d/ruijie-auth

	$(INSTALL_DIR) $(1)/usr/libexec
	$(INSTALL_BIN) ./files/usr/libexec/ruijie-auth $(1)/usr/libexec/ruijie-auth

	$(INSTALL_DIR) $(1)/usr/lib/lua/luci/controller
	$(INSTALL_DATA) ./files/usr/lib/lua/luci/controller/ruijie.lua $(1)/usr/lib/lua/luci/controller/ruijie.lua

	$(INSTALL_DIR) $(1)/usr/lib/lua/luci/model/cbi
	$(INSTALL_DATA) ./files/usr/lib/lua/luci/model/cbi/ruijie.lua $(1)/usr/lib/lua/luci/model/cbi/ruijie.lua

	$(INSTALL_DIR) $(1)/usr/lib/lua/luci/view/ruijie
	$(INSTALL_DATA) ./files/usr/lib/lua/luci/view/ruijie/dashboard.htm $(1)/usr/lib/lua/luci/view/ruijie/dashboard.htm

	$(INSTALL_DIR) $(1)/www/luci-static/resources/ruijie
	$(INSTALL_DATA) ./files/www/luci-static/resources/ruijie/dashboard.css $(1)/www/luci-static/resources/ruijie/dashboard.css
	$(INSTALL_DATA) ./files/www/luci-static/resources/ruijie/dashboard.js $(1)/www/luci-static/resources/ruijie/dashboard.js
endef

$(eval $(call BuildPackage,ruijie-auth))
