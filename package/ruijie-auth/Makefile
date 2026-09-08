include $(TOPDIR)/rules.mk

PKG_NAME:=ruijie-auth
PKG_VERSION:=1.0.0
PKG_RELEASE:=1

include $(INCLUDE_DIR)/package.mk

define Package/ruijie-auth
  SECTION:=net
  CATEGORY:=Network
  TITLE:=Ruijie ePortal authentication helper with LuCI
  DEPENDS:=+curl +ca-bundle +luci-compat
endef

define Package/ruijie-auth/description
 Lightweight Ruijie ePortal authentication helper using UCI and LuCI.
endef

define Build/Compile
endef

define Package/ruijie-auth/install
	$(INSTALL_DIR) $(1)/etc/config
	$(INSTALL_CONF) ./files/etc/config/ruijie $(1)/etc/config/ruijie

	$(INSTALL_DIR) $(1)/etc/init.d
	$(INSTALL_BIN) ./files/etc/init.d/ruijie-auth $(1)/etc/init.d/ruijie-auth

	$(INSTALL_DIR) $(1)/usr/libexec
	$(INSTALL_BIN) ./files/usr/libexec/ruijie-auth $(1)/usr/libexec/ruijie-auth

	$(INSTALL_DIR) $(1)/usr/lib/lua/luci/controller
	$(INSTALL_DATA) ./files/usr/lib/lua/luci/controller/ruijie.lua $(1)/usr/lib/lua/luci/controller/ruijie.lua

	$(INSTALL_DIR) $(1)/usr/lib/lua/luci/model/cbi
	$(INSTALL_DATA) ./files/usr/lib/lua/luci/model/cbi/ruijie.lua $(1)/usr/lib/lua/luci/model/cbi/ruijie.lua
endef

$(eval $(call BuildPackage,ruijie-auth))
