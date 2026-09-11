# 兼容性审查（2026-09-11）

审查范围：全部项目维护的 package、files、configs、sources.env、scripts、测试和 Actions。
上游大型源码仅审查与本项目直接相关的设备定义、包配方、初始化与路由规则。

| 组合 / 路径 | 结论与处理 |
| --- | --- |
| LuCI SSL / libustream | 每个镜像只允许一种 libustream 提供者；配置及 manifest 检查明确排除项，避免上游默认重新选入 |
| UA3F / mwan3 | 保留低 16 位 UA3F 标记、高位 mwan3 掩码和优先级 100 路由补丁；双 WAN 实机验证仍待完成 |
| mwan3 默认探测 | 修复 `uci show` 无法正确逐项展开 list 的问题；只配置已存在接口；缺少 mwan3 时跳过整个区块 |
| 锐捷 / 备用出口 | 未指定物理设备时从已配置的逻辑 WAN 获取 l3_device 并绑定 curl；WAN 未 up / 无 IPv4 时不请求 |
| 锐捷开机 / 自动恢复 | 开机登录并入循环，保留 DHCP 等待；失败按 30/45/60/60 秒退避；重启自身用 exec 保留 procd 管理 PID，避免反复触发崩溃重启上限 |
| 锐捷手工 / 后台操作 | 使用 flock 串行化门户登录、注销和重新认证；增加明确的 flock 包依赖；操作结果按 0600 创建 |
| LuCI 兼容 | 保留 luci-compat；网关查询改用校园 WAN 的 ubus 路由数据；修复折叠隐藏与校验错误展开行为；Lua 5.1 编译语法检查 |
| USB WAN / 校园 WAN | 重拨前检查逻辑接口存在，并拒绝校园接口名，避免误断主 WAN |
| SmartDNS / dnsmasq | 保留 6053 / 53 端口分工与直连 DNS 回退；监听和双栈选择明确设为 IPv4-only；实际超时回退延迟取决于上游和 dnsmasq，不能保证即时切换 |
| TurboACC / UA3F | 保留软件、硬件、SFE、FullCone 默认关闭；BBR、irqbalance、zram 使用原有实现 |
| TurboACC 可选依赖 | 构建前移除 24.10 feed 中不存在的 Shortcut-FE / NFT FullCone 依赖和菜单项；修复 Makefile 续行，避免把 `=all` 误解析成依赖；保留可用的 flow offload 与 BBR CCA |
| feeds / 构建缓存 | 跳过缺少 `rpcd-mod-rad3-enc` 的未使用 `luci-app-radicale3` feed 链接；下载目录和 ccache 使用稳定键，后续矩阵构建可直接复用 |
| 打印 / USB 网络 | 保留驱动和 p910nd；服务默认关闭，无新打印 daemon；多 USB 设备需要合适供电及 Hub |
| 构建并发 | 独立 run ID 并发组，保留已有任务；明确系统与 mwan3 / 单上联版本名 |

测试包括真实本机 HTTP 请求、URL 编码、凭据隔离、门户拒绝响应、无 IPv4、并发锁、
开机 DHCP 等待、完整退避序列、UCI 多接口探测列表和包排除校验。
测试不能替代实际 RT-ACRH17 上的驱动、无线、USB、电源、认证和故障切换验证。

固定源码中的设备树给出 124 MiB UBI 区域，标准 sysupgrade 使用 UBI 卷；
这不等同于未知 OpBoot 机器的实际可用空间。当前常规构建保持原体积检查，未修改
设备树、分区或任何校准内容。40MB 镜像需要结合实机 UBI 可用容量和升级路径验证。
