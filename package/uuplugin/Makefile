#
# 网易 UU 路由器插件（官方预编译二进制，静态 armv7）
#
# 二进制来自官方 openwrt-arm 通道，是静态链接的 ELF32 ARM，不需要交叉编译工具
# 链，所以这里只做三件事：取包并校验、按固定布局安装、由 procd 拉起。
# 版本号出现在下载路径里（v$(PKG_VERSION)），PKG_HASH 是整包的 sha256：上游发
# 新版只会让这个地址 404 或让校验失败，不会悄悄换掉镜像里的插件。
# （PKG_MD5SUM 在 24.10 已标记为 deprecated，它在下载后只留一条警告。）
#
include $(TOPDIR)/rules.mk

PKG_NAME:=uuplugin
PKG_VERSION:=14.10.6
PKG_RELEASE:=1

PKG_SOURCE:=uu.tar.gz
PKG_SOURCE_URL:=http://uurouter.gdl.netease.com/uuplugin/openwrt-arm/v$(PKG_VERSION) \
	http://uurouter-19.gdl.nieapps.com/uuplugin/openwrt-arm/v$(PKG_VERSION)
PKG_HASH:=755179a23b064e9aec72fdb476ed9929fd9f6c97c16c7bb570e31693832fa0f1

PKG_LICENSE:=Proprietary
PKG_MAINTAINER:=ACRH17-OpenWrt

PKG_BUILD_DIR:=$(BUILD_DIR)/$(PKG_NAME)-$(PKG_VERSION)

include $(INCLUDE_DIR)/package.mk

define Package/uuplugin
  SECTION:=net
  CATEGORY:=Network
  TITLE:=NetEase UU router plugin with LuCI (remote Wake-on-LAN, game acceleration)
  # @arm 是包级依赖：包里的三个可执行文件只有 ELF32 ARM 版本，写成目标依赖后
  # 在别的架构上 menuconfig 根本不会给出这个包，而不是等交叉编译跑完才失败。
  DEPENDS:=@arm +ca-bundle +luci-compat +luci-lib-nixio
endef

define Package/uuplugin/description
 Prebuilt static armv7 binaries from the NetEase UU openwrt-arm channel.
 Provides the UU router plugin (cloud reachable Wake-on-LAN and game
 acceleration) with a LuCI page for service state, device identity and logs.
endef

define Package/uuplugin/conffiles
/etc/config/uuplugin
endef

# 包里的四个文件是固件的一部分，不进 overlay：uuplugin 需要写 uu.conf 和身份
# 文件，运行目录由启动脚本复制到 /tmp/uu，见 files/etc/init.d/uuplugin。
#
# 这里不用 $(call Build/Prepare/Default)：默认解包按「归档里有一层
# pkg-version/」的惯例往 $(PKG_BUILD_DIR)/.. 展开，而这个归档的四个文件就在
# 根部，那样会把它们撒到 build_dir 里。下载仍然是先决条件——download.mk 把
# $(DL_DIR)/$(PKG_SOURCE) 挂在 $(STAMP_PREPARED) 上。
#
# 目录要自己建：$(PKG_BUILD_DIR) 只由 Build/Prepare/Default 创建，覆盖了这个
# 宏就没人建了，tar -C 会直接失败。
#
# 校验不用 shell 循环变量：OpenWrt 会把配方展开两次，`$$f` 第一次变成 `$f`，
# 第二次 `$f` 被当成 make 变量展开成空串，于是 `[ -f $(PKG_BUILD_DIR)/ ]` 恒假，
# 每个包都报「缺文件」。写成串联的 test -f 就与展开次数无关。
define Build/Prepare
	mkdir -p $(PKG_BUILD_DIR)
	$(TAR) -xzf $(DL_DIR)/$(PKG_SOURCE) -C $(PKG_BUILD_DIR)
	@[ -f $(PKG_BUILD_DIR)/uuplugin ] && [ -f $(PKG_BUILD_DIR)/xuplugin-guardian ] && \
		[ -f $(PKG_BUILD_DIR)/xtables-nft-multi ] && [ -f $(PKG_BUILD_DIR)/uu.conf ] || \
		{ echo "uuplugin: $(PKG_SOURCE) must carry uuplugin, xuplugin-guardian, xtables-nft-multi and uu.conf at its root" >&2; exit 1; }
endef

define Build/Compile
endef

define Package/uuplugin/install
	$(INSTALL_DIR) $(1)/usr/lib/uu
	$(INSTALL_BIN) $(PKG_BUILD_DIR)/uuplugin $(1)/usr/lib/uu/
	$(INSTALL_BIN) $(PKG_BUILD_DIR)/xuplugin-guardian $(1)/usr/lib/uu/
	$(INSTALL_BIN) $(PKG_BUILD_DIR)/xtables-nft-multi $(1)/usr/lib/uu/
	$(INSTALL_DATA) $(PKG_BUILD_DIR)/uu.conf $(1)/usr/lib/uu/

	$(INSTALL_DIR) $(1)/etc/init.d
	$(INSTALL_BIN) ./files/etc/init.d/uuplugin $(1)/etc/init.d/uuplugin
	$(INSTALL_DIR) $(1)/etc/config
	$(INSTALL_CONF) ./files/etc/config/uuplugin $(1)/etc/config/uuplugin

	# 身份在 /etc/uu/id。sysupgrade 的保留清单只按 keep.d 走，默认那几项里没有
	# /etc，不装这个文件的话，每次 sysupgrade 都会把绑定关系丢掉。
	$(INSTALL_DIR) $(1)/lib/upgrade/keep.d
	$(INSTALL_DATA) ./files/lib/upgrade/keep.d/uuplugin $(1)/lib/upgrade/keep.d/uuplugin

	$(INSTALL_DIR) $(1)/usr/lib/lua/uuplugin
	$(INSTALL_DATA) ./files/usr/lib/lua/uuplugin/state.lua $(1)/usr/lib/lua/uuplugin/state.lua

	$(INSTALL_DIR) $(1)/usr/lib/lua/luci/controller
	$(INSTALL_DATA) ./files/usr/lib/lua/luci/controller/uuplugin.lua $(1)/usr/lib/lua/luci/controller/uuplugin.lua

	$(INSTALL_DIR) $(1)/usr/lib/lua/luci/model/cbi
	$(INSTALL_DATA) ./files/usr/lib/lua/luci/model/cbi/uuplugin.lua $(1)/usr/lib/lua/luci/model/cbi/uuplugin.lua

	$(INSTALL_DIR) $(1)/usr/lib/lua/luci/view/uuplugin
	$(INSTALL_DATA) ./files/usr/lib/lua/luci/view/uuplugin/dashboard.htm $(1)/usr/lib/lua/luci/view/uuplugin/dashboard.htm
	$(INSTALL_DATA) ./files/usr/lib/lua/luci/view/uuplugin/logs.htm $(1)/usr/lib/lua/luci/view/uuplugin/logs.htm

	$(INSTALL_DIR) $(1)/www/luci-static/resources/uuplugin
	$(INSTALL_DATA) ./files/www/luci-static/resources/uuplugin/dashboard.css $(1)/www/luci-static/resources/uuplugin/dashboard.css
endef

$(eval $(call BuildPackage,uuplugin))
