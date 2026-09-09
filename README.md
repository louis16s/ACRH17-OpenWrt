# ASUS RT-ACRH17 · OpenWrt 24.10

面向 OpBoot 的第一版固件构建项目。使用官方 `ipq40xx/generic` →
`asus_rt-ac42u` 定义，OpenWrt 分支为 `openwrt-24.10`。
OpenWrt、packages、LuCI、routing 和 UA3F 的提交固定在 `sources.env`。

## 功能与体积

| 功能 | 包 / 实现 |
| --- | --- |
| LuCI HTTPS、中文、现代主题 | `luci-ssl`、`luci-app-package-manager`、`luci-theme-openwrt-2020`、`LUCI_LANG_zh_Hans` |
| UA3F 图形管理 | UA3F v3.6.0 的 `ua3f` 包自带 Lua LuCI，保留 `luci-compat`；首次启动即启用 |
| 锐捷 ePortal | 自定义 `ruijie-auth`、curl、jsonfilter，LuCI 配置及手动登录/注销 |
| 双 WAN | `mwan3`、`luci-app-mwan3`、legacy iptables/ip6tables、ipset；系统防火墙为 firewall4 |
| Android / USB 网卡 / F50 | RNDIS、CDC Ethernet、CDC NCM 驱动 |
| MBIM 备用支持 | `kmod-usb-net-cdc-mbim`、`umbim`、`luci-proto-mbim`，自动带入 WDM |
| USB 打印 | `kmod-usb-printer`、`p910nd`、`luci-app-p910nd` |
| 内存与 TCP | BBR、FQ（24.10 的 `kmod-sched`）、64 MiB zram 逻辑容量 |
| 时间与 DNS | UTC+8（Asia/Shanghai）、阿里/腾讯/公共 NTP、SmartDNS 与 LuCI 管理页（本地 6053 端口） |

256 MB RAM 是运行预算；128 MB Flash 并非全部可供镜像使用。
官方设备定义的 `IMAGE_SIZE` 为 **20,439,364 bytes（约 19.5 MiB）**。
工作流同时检查镜像存在、大小和完整包清单。

项目不安装 Clash、AdGuard Home、Samba、Docker；不修改设备树或分区布局。
不修改或制作 ART、EEPROM、Factory、calibration、Bootloader 分区内容。

首次启动默认 LAN 为 `192.168.5.1`，管理用户为 `root`，密码为 `password`。
首次登录后应立即更换密码。无线监管域默认设置为中国（CN），不写入超出该
监管域限制的发射功率。

默认主机名为 `DESKTOP-ACRH17`，以 Windows 电脑风格出现在 DHCP、局域网
设备列表和部分上游网络记录中。系统时区为 UTC+8（`Asia/Shanghai`，POSIX
时区字符串为 `CST-8`）。

普通配置使用驱动自动选择的 20/40/80 MHz 频宽。160 MHz 是独立的实验配置，
默认关闭。确认当地法规、终端和信道支持后，可执行：

```sh
uci set acrh17.settings.wifi_160mhz='1'
uci commit acrh17
reboot
```

启用后 5 GHz 无线尝试使用 `VHT160`；DFS、监管域、干扰或驱动能力不足时，
可能自动退回较窄频宽或无法启动。恢复常规配置：

```sh
uci set acrh17.settings.wifi_160mhz='0'
uci commit acrh17
reboot
```

## 构建和验证

推送 `main` / `codex/**` 或手动运行 `Build RT-ACRH17 OpenWrt`：

1. 安装 Ubuntu 24.04 构建工具，运行 HTTP 行为测试和 Lua / shell 语法检查。
2. 获取固定提交，加入自定义包和 UA3F 构建 / 多 WAN 集成补丁。
3. `make defconfig` 后强制检查每个请求的功能；未知包名导致失败。
4. `make download`，从源码编译工具链、内核和软件包。
5. 并行编译失败时原地 `make -j1 V=s`，保存两份完整日志。
6. 检查两种设备镜像和成品 manifest，再上传固件与日志。

Actions 页面：<https://github.com/louis16s/ACRH17-OpenWrt/actions>

固件 artifact 内包含镜像、`sha256sums`、manifest、完整配置、diffconfig、
上游提交锁和本项目 commit。日志在单独的 `build-logs-*` artifact 中。
源码构建结果与真实路由器上的启动、无线、USB 和校园认证测试应分别验收。

## OpBoot 首次测试与后续升级

| 文件后缀 | 用途 |
| --- | --- |
| `asus_rt-ac42u-initramfs-uImage.itb` | **仅在 OpBoot 明确支持 FIT/initramfs 的 RAM 加载启动时**，用于首次临时启动测试 |
| `asus_rt-ac42u-squashfs-sysupgrade.bin` | 已经正常运行该设备 OpenWrt 之后，用于 LuCI / sysupgrade 标准升级 |

尚未获得这台机器的 OpBoot 版本、镜像接收格式或实际分区布局。
因此不能保证它的网页“固件上传”按钮支持 RAM 测试，也不能把 initramfs
当成可永久安装镜像。若页面没有明确的 RAM 启动功能，应先核实 OpBoot
文档和设备现状，再选择启动方法。

首次测试先使用网线，逐项验证设备型号、LAN/WAN、LuCI、两张无线网卡、
USB 枚举、认证、双 WAN 切换和打印。旧 swconfig 配置不能直接迁移至
24.10 的 DSA；大版本迁移应重新配置网络。

上游升级检查可能因残留的 ASUS `jffs2` UBI 卷而拒绝安装。
本项目不会自动处理该布局；遇到拒绝时停止安装并核实固件存储布局。
不得绕过镜像兼容检查，也不得写入上述受保护分区。

## USB WAN / F50 / Android

插入数据线并在手机或 F50 上启用 USB 网络共享。通过 SSH 只读检查：

```sh
lsusb
ip -br link
dmesg | grep -Ei 'rndis|cdc|ncm|mbim|usb'
```

在 LuCI「网络 → 接口」创建 `usbwan`，选择实际枚举的网卡设备并使用 DHCP
客户端；不要固定假定它一定叫 `usb0`。将它加入已有 WAN 防火墙区域，
确认该区域开启 masquerading，并设置与主 WAN 不同的接口 metric。

若设备枚举为 MBIM 且存在 `/dev/cdc-wdm*`，使用 LuCI MBIM 协议并填写实际
APN / SIM 参数。CDC NCM 网卡共享通常直接使用 DHCP；需要 AT 命令拨号的
其他 NCM 调制解调器不等同于手机/F50 的 USB 网络共享模式。

F50 各固件的 USB 模式、供电和线材会影响识别。本版不发送未知的 USB
mode-switch 指令。路由器只有一个 USB 端口；同时连接 F50 与打印机通常
需要供电充足的 USB Hub。

## mwan3 与 UA3F

先分别验证校园 WAN 与 USB WAN，再在 mwan3 中建立对应的接口、成员和策略。
首版建议主 WAN 优先、USB 备用，测试拔线、恢复和 DNS。mwan3 安装后默认未
启用自启动，完成真实上联配置后再启用服务。

UA3F 在「服务 → UA3F」，保持完整上游 LuCI 界面，默认关闭。
它在本镜像中可使用 nftables TPROXY；对应 tproxy / queue 内核模块已包含。
构建补丁补齐 `luci-base/host` 的 po2lmo 依赖和 Build/Prepare 目录创建。

UA3F 原始 TPROXY 标记 `0x1c9` 与 mwan3 默认 `0x3f00` 掩码有交集。
本项目把 mwan3 掩码设为 `0x3f000000`，并对 UA3F 的 nft TPROXY/REDIRECT
标记比较使用低 16 位；TPROXY 本地交付的策略路由使用优先级 100 与
`0xffff` 掩码，先于 mwan3 的上联路由。补丁保存在
`scripts/patch-ua3f-mwan3.py`，上游升级时必须复审。

该组合需要实机验证。NFQUEUE 模式及高级连接标记重写未经过双 WAN 联合
验证；开启这些功能前应单独验证。透明代理产生的新上游连接来自路由器，
按 LAN 客户端源地址制定的 mwan3 策略不一定继续适用。

## 锐捷 ePortal

进入「服务 → Ruijie ePortal」，填写校园网页成功登录请求中的字段：
server、userId、password、service、queryString、Cookie、Referer 等。
填写的是**解码后的字段值**，脚本统一进行 form URL 编码；不要再次粘贴
百分号编码的整个 POST 请求体。加密 password 必须来自实际协议流程。

先「保存并应用」，再点击 Login now；手动成功后才启用自动认证。
默认检测端点必须返回 HTTP 204，200 登录页与 302 重定向均判为离线。
自定义检测 URL 也必须遵循 204 约定。

双 WAN 环境应把 Physical WAN device 设置为实际校园出口设备，使检测和
认证绑定校园上联，否则 USB 上网可能掩盖校园掉线。物理设备绑定限制出口，
仍需验证校园路由和 DNS 可达。

配置文件权限为 0600，升级时保留；结果文件放在 tmpfs，权限同为 0600。
不把门户返回内容或认证字段写入 syslog。HTTP 成功但门户返回认证失败时，
脚本会返回失败状态。界面操作区绑定真实的 UCI section。

这不是通用校园协议自动发现器：若门户要求动态 RSA、验证码、每次更新的
queryString/Cookie 或会话令牌，需要根据该校园的成功请求进一步适配。

## USB 打印

在「服务 → p910nd」选择 `/dev/usb/lp0`（以实际设备为准），端口 `0`
对应 TCP 9100。默认保持关闭，连接并配置打印机后启用。
建议把监听地址设置为实际 LAN IP；WAN 区域保持默认拒绝入站，
不要添加公网 9100 放行规则。

客户端使用 RAW / AppSocket 9100 并安装该打印机的厂商驱动。
p910nd 不提供渲染驱动，也不保证所有仅支持专有协议的打印机可用。
若双向模式导致异常，可在 LuCI 切换该选项后重新测试。

## BBR 与 zram

```sh
sysctl net.ipv4.tcp_congestion_control net.core.default_qdisc
cat /proc/swaps
/etc/init.d/zram status
```

BBR 调节路由器自身终止或发起的 TCP（包括代理连接），不会替换纯转发
客户端的拥塞控制算法。64 MiB zram 是压缩交换设备的逻辑容量，实际压缩
页仍消耗 RAM；它不写 Flash。UA3F 的实际内存占用需在并发负载下测量。

## 默认网络、NTP 和 SmartDNS

LAN 地址为 `192.168.5.1`。SmartDNS 监听本机 `6053`，dnsmasq 已配置为将 DNS
请求转发到该端口；上游服务器和监听端口可通过 LuCI「服务 → SmartDNS」或
`/etc/config/smartdns` 调整。该 LuCI 应用来自固定的 OpenWrt 24.10 LuCI
提交，不依赖额外第三方 feed。
默认 SmartDNS 上游为腾讯 DNSPod（`119.29.29.29`、`119.28.28.28`）和阿里
DNS（`223.5.5.5`、`223.6.6.6`）；SmartDNS 会在可用上游中选择响应更快的
结果。默认 NTP 为阿里云、腾讯云和 `pool.ntp.org`。

## 默认启用的 UA3F

UA3F 在首次启动时已启用并设为开机启动，默认使用上游 `TPROXY` 与 `FFF`
User-Agent 重写规则。若校园认证、银行、流媒体或某个站点出现异常，可先在
LuCI「服务 → UA3F」关闭验证，再按目标域名细化规则。

## 无线性能分支审查

RT-ACRH17 的 5 GHz 使用 QCA9984，官方 OpenWrt 24.10 设备定义使用
`ath10k-ct` 与该型号专用 BDF。未发现能在此设备上复现、同时保留 OpenWrt
24.10、UA3F 和 mwan3 的更高性能维护分支。部分 QSDK/NSS fork 面向 IPQ807x
和 IPQ6018，不适用于本机的 IPQ4019；以其他设备的 `ath10k` 非 CT 固件
替换本机固件可能失去 RT-AC42U 专用 BDF，不能作为默认镜像方案。

## 审查依据

- [OpenWrt 官方设备定义](https://github.com/openwrt/openwrt/blob/a1ea57bd050c172fdc2b851824ebd9782aafb055/target/linux/ipq40xx/image/generic.mk)
- [OpenWrt 24.10 USB 模块定义](https://github.com/openwrt/openwrt/blob/a1ea57bd050c172fdc2b851824ebd9782aafb055/package/kernel/linux/modules/usb.mk)
- [mwan3 包和源代码](https://github.com/openwrt/packages/tree/4b4b1f5af9d7aec892ec9148aaccd88590d83982/net/mwan3)
- [p910nd 包和默认配置](https://github.com/openwrt/packages/tree/4b4b1f5af9d7aec892ec9148aaccd88590d83982/net/p910nd)
- [UA3F v3.6.0](https://github.com/SunBK201/UA3F/releases/tag/v3.6.0)
