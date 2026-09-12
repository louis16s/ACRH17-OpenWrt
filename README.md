# ASUS RT-ACRH17 · ImmortalWrt 24.10 试验分支

此分支使用 ImmortalWrt 的 `openwrt-24.10` 源码、`ipq40xx/generic` →
`asus_rt-ac42u` 设备定义，并继承主线功能配置。ImmortalWrt、packages、LuCI、
routing 和 UA3F 的提交固定在 `sources.env`。

## 功能与体积

| 功能 | 包 / 实现 |
| --- | --- |
| LuCI HTTPS、中文、Argon Dark 主题 | `luci-ssl`、`luci-app-package-manager`、`luci-theme-argon`、`LUCI_LANG_zh_Hans` |
| UA3F 图形管理 | UA3F v3.6.0 系列的 `ua3f` 包自带 Lua LuCI，锁定官方最新提交 `7a3869714df6...`；保留 `luci-compat`，首次启动即启用 |
| 锐捷 ePortal | 自定义 `ruijie-auth`、curl、jsonfilter，LuCI 配置及手动登录/注销 |
| 双 WAN | `mwan3`、`luci-app-mwan3`、legacy iptables/ip6tables、ipset；系统防火墙为 firewall4 |
| Android / USB 网卡 / F50 | RNDIS、CDC Ethernet、CDC NCM 驱动 |
| MBIM 备用支持 | `kmod-usb-net-cdc-mbim`、`umbim`、`luci-proto-mbim`，自动带入 WDM |
| USB 打印 | `kmod-usb-printer`、`p910nd`、`luci-app-p910nd` |
| 内存与 TCP | BBR、FQ（24.10 的 `kmod-sched`）、64 MiB zram 逻辑容量 |
| 时间与 DNS | UTC+8（Asia/Shanghai）、阿里/腾讯/公共 NTP、SmartDNS 与 LuCI 管理页（本地 6053 端口） |
| 维护工具 | watchcat、LuCI 命令、irqbalance、DDNS、TurboACC；watchcat 与 DDNS 默认关闭 |

256 MB RAM 是运行预算；128 MB Flash 并非全部可供镜像使用。
官方设备定义的 `IMAGE_SIZE` 为 **20,439,364 bytes（约 19.5 MiB）**。
工作流同时检查镜像存在、大小和完整包清单。

项目不安装 Clash、AdGuard Home、Samba、Docker；不修改设备树或分区布局。
不修改或制作 ART、EEPROM、Factory、calibration、Bootloader 分区内容。

首次启动默认 LAN 为 `192.168.5.1`，管理用户为 `root`，密码直接设为
`password`。无线监管域默认设为澳大利亚（AU）。首次启动会同时启用两个无线
网络，SSID 分别为 `ACRH17-2.4G` 与 `ACRH17-5G`。
两个无线网络默认使用 WPA2-PSK，密码为 `password`。

默认主机名为 `DESKTOP-ACRH17`，以 Windows 电脑风格出现在 DHCP、局域网
设备列表和部分上游网络记录中。系统时区为 UTC+8（`Asia/Shanghai`，POSIX
时区字符串为 `CST-8`）。

无线保持标准 OpenWrt 24.10 配置，不强制 160 MHz，也不修改校准、ART、EEPROM
或其他无线相关受保护分区。

本镜像按 IPv4-only 校园网络使用：LAN 不分配 IPv6 前缀，WAN6 和 LAN 的
DHCPv6/RA/NDP 和 firewall4 的 IPv6 处理已停用，内核也默认关闭 IPv6。这样
不会让自动生成的 WAN6 路由绕过 UA3F 或 mwan3 的 IPv4 策略；需要 IPv6 的用户
应另行构建配置。

默认 LuCI 使用 Argon Dark，页脚包含作者链接：[番鼠大王](https://530555.xyz)。

## 构建和验证

推送默认分支 `codex/openwrt-24.10` 或手动运行 `RT-ACRH17 Firmware Matrix`：

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

首次启动会把 `wan`、`wanb` 映射到 `mwan3` 中已经存在的逻辑接口，并使用
`223.5.5.5`、`119.29.29.29`、`114.114.114.114` 作为 IPv4 探测目标，要求
至少两个目标成功、连续失败 3 次才判定掉线。校园网若屏蔽公共 DNS，应把
在 LuCI 的对应 mwan3 接口中填写学校网关或可访问的校内 DNS 与公共 DNS。
`/etc/config/acrh17` 的 `mwan3_probe_ip` 列表仅作为首次启动模板，修改它再重启 mwan3
不会自动同步；运行期间应直接修改 mwan3 的 `track_ip`。`wan2`、`usbwan` 只作为可配置映射
保留，不会凭空创建上联；在 LuCI 中建立实际接口后，再将它加入 mwan3 的成员
和策略。`wan6` / `wanb6` 默认关闭。

UA3F 在「服务 → UA3F」，保持完整上游 LuCI 界面，首次启动默认启用。
`sources.env` 锁定官方最新未发布提交 `7a3869714df6b46af7b1a52287e6560d4bfbd6ba`。
该提交修正 Desync 参数含义并增加可配置 TTL 值；本项目仍保持重排和 TTL 默认关闭，
因此升级提交不会改变现有默认行为。正式 Release 仍为 v3.6.0。
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

## 校园认证、维护命令和自动恢复

「服务 → Ruijie ePortal / 锐捷认证」显示 procd 服务状态、最近认证状态、
校园 WAN 逻辑接口及 IPv4 地址、默认网关、最近认证时间/结果/摘要和自动重连
状态。登录、注销、重新认证、按需 DHCP 更新、清除结果和服务重启均在后台
执行，避免 LuCI 因门户超时而卡住；最近日志仅从 RAM 中的 `logread` 读取 80 行。

自动恢复支持开机认证、断线重认证、检测及失败重试起始间隔、最大失败次数，以及仅重试、
重启 WAN 逻辑接口或重启认证服务三种失败动作。默认不会重启整台路由器。
认证请求前会先检查 WAN 逻辑接口是否 up 且已获得 IPv4；DHCP 未就绪时仅等待，
不会先执行联网探测再执行门户请求。认证失败采用有限退避：默认从 30 秒开始，
依次为 45 秒、60 秒，之后保持 60 秒；达到配置的最大连续失败次数后，只有重启
WAN 或重启服务动作会清零退避，选择“仅继续重试”会保持封顶间隔。

「系统 → 自定义命令」预置重新认证锐捷、重启 UA3F、重拨 UCI 中配置的 USB
WAN、重启 p910nd、查看 USB 设备及查看 USB 网络驱动状态。USB WAN 默认逻辑
接口名为 `usbwan`，可通过 `acrh17.settings.usbwan_interface` 调整；命令不会
重启校园 WAN。

watchcat 已编译但默认关闭，也没有预置实例。建议仅为校园主 WAN 建立一个
检测实例，并将断线动作设置为重启该网络接口。检测目标使用学校可访问的稳定
IP 或 URL；不要把 Google、Cloudflare 等作为校园网络唯一检测目标。需要监测
F50 时另建 USB WAN 实例，不要默认同时运行多个实例。

DDNS 页面和脚本已编译但默认关闭，不包含服务商、域名或账号。irqbalance 已
启用并使用包自带的 procd/init 服务，适合 IPQ4019 的四核 CPU，不额外创建
守护脚本。TurboACC 默认启用 BBR，软件和硬件 flow offloading、Shortcut-FE
与 FullCone 均关闭。校园认证 / UA3F / mwan3 模式保持这个设置；只有在纯 NAT
高吞吐场景下，才建议临时在 LuCI 中单独开启软件卸载并逐项验证，硬件卸载不作为
默认方案。

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

LAN 地址为 `192.168.5.1`。SmartDNS 监听本机 `6053`，dnsmasq 优先将 DNS
请求转发到该端口，同时保留腾讯 DNSPod 和阿里 DNS 的直连 IPv4 回退；SmartDNS
停止、尚未启动或上游全部失败时，dnsmasq 仍可直接解析。上游服务器和监听端口
可通过 LuCI「服务 → SmartDNS」或 `/etc/config/smartdns` 调整。该 LuCI 应用
来自固定的 OpenWrt 24.10 LuCI 提交，不依赖额外第三方 feed。`prefetch` 与
`serve_expired` 保持可选，建议先观察校园 DNS 对过期缓存的接受情况，再按需启用，
不默认增大缓存。
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
- [UA3F v3.6.0 最新正式 Release](https://github.com/SunBK201/UA3F/releases/tag/v3.6.0)
- [UA3F 锁定提交 7a386971](https://github.com/SunBK201/UA3F/commit/7a3869714df6b46af7b1a52287e6560d4bfbd6ba)

## 构建提速与稳定性

完整构建使用一个矩阵 run，在同一次 Actions 中并行编译 OpenWrt / ImmortalWrt
的 Campus（mwan3）和 Single WAN 四个变体；默认分支的提交会取消旧的矩阵 run，
避免批量同步变体分支时重复占用 runner。每个变体的固件和日志使用
`RT-ACRH17-<variant>-<run_id>` 命名。其他变体分支仍可在 Actions 中手动触发同一矩阵。
纯 Markdown 修改不触发完整编译。下载目录与 ccache 分开缓存；ccache 通过
`CONFIG_DEVEL=y`/`CONFIG_CCACHE=y` 真正接入编译器，并按变体、源码锁和配置隔离，
容量限制为 2 GiB。第三方源码按固定提交浅拉取。

完整构建会生成 `fast-base-<commit>`，包含专用 standalone ImageBuilder。
只修改 `files/` 默认配置或锐捷包的脚本、Lua、CSS 时，可以在同分支手动运行
`Fast RT-ACRH17 image`，输入成功的完整矩阵 run ID 和 `variant`。它按所选变体
下载对应的 ImageBuilder，检查源码、包配置与构建
补丁是否匹配，再覆盖当前配置文件和锐捷脚本生成标准 sysupgrade。改变内核、
feeds、软件包清单、主题上游或包 Makefile 时必须重新完整构建。

快速构建只交付 sysupgrade；首次内存启动测试使用对应完整构建的 initramfs。
快速构建不会重新编译内核或重新编译上游主题。固件保留 BBR、irqbalance、UA3F、
SmartDNS；启用 mwan3 或代理重写时应先验证正常路径，再在实机比较软件卸载开关
对吞吐、重写和故障切换的影响，不把加速开关全部打开作为默认优化。

完整矩阵构建成功后，Actions 会自动创建一个以 `build-<run_id>` 命名的 GitHub
Release。Release 只附加四个变体的 `sysupgrade.bin`；对应的 initramfs、构建配置和
完整日志仍保留在同一次 Actions 的 artifacts 中。首次测试请先确认 OpBoot 版本是否
支持 RAM/临时启动，并使用同一变体的 initramfs；确认设备可正常启动后再刷对应的
sysupgrade.bin。Release 流程不会生成或写入 ART、EEPROM、Factory、校准或 Bootloader
分区内容。

Argon 通过 UCI `mode=dark` 强制暗色，64 MiB zram 配置持久化。锐捷页面将门户
返回的认证结果与联网检查分开；HTTP 204 探测成功才记录已联网，注销记录为离线。

## 版本命名与兼容性审查

- `codex/openwrt-24.10`：OpenWrt Campus，原 main 分支，UA3F + mwan3 校园版。
- `codex/immortalwrt-24.10`：ImmortalWrt Campus，UA3F + mwan3 校园版。
- `codex/openwrt-24.10-singlewan`：OpenWrt Single WAN，UA3F 单上联版。
- `codex/immortalwrt-24.10-singlewan`：ImmortalWrt Single WAN，UA3F 单上联版。

本轮修复 UCI 多值列表读取、锐捷重复开机请求、接口绑定、认证操作互斥、
LuCI 网关字段转义和折叠区域校验提示。包配置与成品 manifest 同时检查明确排除的包，
并检查 libustream 提供者冲突。恢复重试通过行为测试验证。

单上联版保留 UA3F、锐捷、SmartDNS、USB 网络、打印和原有维护工具，省去 mwan3
及其 LuCI 页面。USB 上联仍可在网络接口页面配置；多出口的自动策略切换由校园版提供。
所有版本的软件和硬件转发卸载默认关闭，实际吞吐和联合运行仍需实机验证。


## 2026-09-12 审查更新

最新已完成产物 `build-34676435773` 的四种镜像已通过 SHA-256、设备 tar/FIT
结构、SquashFS、包清单、脚本来源及权限核对；详情见 [审查记录](docs/CODE_AUDIT.md)。
后续矩阵构建先通过 Linux 双 WAN 路由和 NFQUEUE 标记测试，再编译固件。
构建启动时固定四个变体的提交，Release 附带四个 `.bin` 的 `sha256sums`。

保留配置升级时，初始化脚本保留已有密码、网络、Wi-Fi 和服务选择；全新安装
继续使用上文的默认配置。旧版本通过已配置的 root 密码识别已安装系统。
首次安装后应修改默认管理密码和无线密码。

TurboACC 在 UA3F 或已启用的 mwan3 存在时关闭不兼容的流量卸载。
SmartDNS 的新安装配置将监听限制到回环设备，缓存上限设为 1024 条且不落盘。
锐捷重认证等待 DHCP 恢复，手动重拨和后台登录共用锁；锁忙不会触发 WAN 故障恢复。

快速打包按所选变体检出源码，只有源码、包配置和补丁指纹与完整构建一致时才复用
ImageBuilder。此次补丁和包版本已变化，必须先完成一次新的完整构建。
