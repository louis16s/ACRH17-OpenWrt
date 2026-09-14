# 代码与固件审查（2026-09-12）

范围：四个变体分支的项目代码、配置、补丁、工作流和测试；固定上游中与设备、
UA3F、mwan3、SmartDNS、TurboACC 直接相关的实现。并非逐行审查整个 Linux/OpenWrt。
远端新增的 `63167e2`（Argon 补丁断言及测试）已合并，保留四个发行版/单双 WAN 差异。

## 已完成产物核对

检查对象：[完整构建 34676435773](https://github.com/louis16s/ACRH17-OpenWrt/actions/runs/34676435773)，
[Release](https://github.com/louis16s/ACRH17-OpenWrt/releases/tag/build-34676435773)。
这是此次新修复之前的成功产物，不能用它证明新修复已进入固件。

| 变体 | sysupgrade 字节数 | 包数量 | 项目提交 |
| --- | ---: | ---: | --- |
| immortalwrt-campus | 18,146,362 | 304 | `9edb0d9e52ba` |
| immortalwrt-singlewan | 18,136,122 | 298 | `2e518e9f1c01` |
| openwrt-campus | 16,159,798 | 258 | `63167e273685` |
| openwrt-singlewan | 16,129,078 | 252 | `62d95491ed4c` |

- 四个 `.bin` 的实际 SHA-256 同时匹配 Release 的 digest 和 artifact 的 `sha256sums`。
- 四个 initramfs 的哈希通过，FIT 文件头正确；sysupgrade 的设备目录、CONTROL、kernel、root 成员正常，root 为 SquashFS。
- 镜像均小于设备定义的 20,439,364 字节上限。
- 包清单包含全部请求包；每个镜像仅有 mbedTLS 的 libustream 提供者。
- 双 WAN 为 mwan3 + legacy iptables/ip6tables；单 WAN 无 mwan3 和 legacy 前端，UA3F 的依赖带入 iptables-nft。
- 从根文件系统提取的认证程序和初始化脚本与各自项目提交逐字节一致；锐捷配置权限为 0600，程序为 0755。
- 在四个实际 rootfs 中确认 SmartDNS 支持此次使用的绑定设备和缓存选项。

完整哈希记录见 [artifact-audit-34676435773.json](artifact-audit-34676435773.json)。

## 修复的问题

| 严重度 | 问题与影响 | 修复 |
| --- | --- | --- |
| 高 | sysupgrade 重新安装 uci-defaults，原逻辑重设 root 密码、LAN/Wi-Fi 并禁用服务 | 持久初始化标记；旧安装通过已配置 root 密码识别，保留已有设置 |
| 高 | 上一条的持久标记把「禁用服务」一并跳过：`/etc/rc.d` 不在任何 keep.d 条目中，且 `nand_do_upgrade` 会删除并重建 rootfs_data，因此 `disable` 在每次升级后失效，watchcat 复活后以 8.8.8.8 每 6 小时探测、失败即强制重启 | 将 watchcat、ddns、mwan3 的 `disable` 移到幂等守卫之前，使其在每次升级后重新生效，并加回归测试锁定位置 |
| 高 | UA3F NFQUEUE 读取完整 ct mark，并在 verdict 中覆盖 mwan3 高位，导致分类/选路失效 | UA3F 只比较低 16 位，所有更新保留高位；覆盖 skip/cache/modified 等返回路径 |
| 高 | 辅助 NFQUEUE、desync、netlink、sidecar 和 iptables 回退规则未完整遵守 mark 掩码 | 同步修复比较及赋值；TPROXY 路由优先级 100 和掩码保持一致 |
| 高 | UI 可重新启用 TurboACC 流卸载，与 UA3F/策略路由冲突 | UA3F 或已启用 mwan3 存在时，TurboACC 有效配置关闭软件/硬件/SFE 卸载 |
| 中 | 手动重拨、清结果与后台认证可并行；锁忙计为失败可导致无谓重拨 | 共享认证锁；锁忙使用独立退出码，后台跳过失败累计 |
| 中 | 重认证调用 ifup 后立即登录，DHCP 通常尚未完成 | 最多等待 30 秒的 IPv4 就绪检查，重拨失败或超时停止该次登录 |
| 中 | 网络自行恢复后页面仍显示旧失败状态 | 成功探测刷新联网状态；探测固定 IPv4，curl 禁用隐式 curlrc 配置 |
| 中 | LuCI 多次点击共同改写 action 文件，后台继承请求描述符 | 独立操作锁及标准输入输出脱离请求；状态页按页读取一次文件/UCI/WAN 状态，减少 fork |
| 中 | 快速构建不按输入变体检出，且用 workflow 名称比较实际 run-name，错误拒绝成功基线 | 按变体检出；用 workflow 路径、成功状态及源码/包/补丁指纹检查基线 |
| 中 | Kconfig 校验忽略 ImageBuilder、ccache、语言及 INCLUDE 开关 | 所有显式 `=y` 和包排除项均必须成立 |
| 中 | 构建用 find -exec luac，单文件语法失败未必传递为 find 失败 | 统一 Python 校验器，逐文件检查退出码并运行回归测试 |
| 中 | 镜像验证只查存在和体积、manifest 用不明确 glob | 增加哈希、FIT/tar/SquashFS 结构；明确选设备 manifest，检查 SSL 提供者冲突 |
| 中 | 四个 job 分别检出移动分支，Release tag 未固定触发提交 | 启动时一次解析四个 SHA；按 SHA 检出；Release 固定 target 并附带 SHA-256 文件 |
| 低 | TurboACC 启停无 DNS 配置改动却多次重启 dnsmasq | 移除多余 DNS 重启，保留防火墙更新；并针对上游两处缩进形态（双 tab ×2、单 tab ×1）与三个 `DNSMASQ` 词串加断言，pin 升级后不再匹配时立即失败而非静默失效 |
| 低 | SmartDNS 缺少明确的设备监听和内存预算 | 新安装只绑定回环设备，1024 条缓存且不持久写盘；保留 dnsmasq 53 / SmartDNS 6053 分工 |
| 低 | p910nd 热插拔脚本把 `/opt/p910nd_drivers` 追加到 `/etc/sysupgrade.conf`，但该文件本身不在任何 keep.d 条目中，首次升级即被清空，打印机驱动 blob 会在第二次升级时丢失 | 在 `files/lib/upgrade/keep.d/acrh17` 中直接保留该目录，并加回归测试锁定 |
| 中 | `fast-image.yml` 的 `make image \| tee` 未启用 `pipefail`，`tee` 的 0 掩盖编译失败，验证步骤对上一次的完整产物照常通过，任务错误变绿，失败只留在日志里 | 该步骤补 `set -o pipefail`，与 `build.yml` 四处管道步骤保持一致 |
| 低 | Release 由 `gh release create` 先建记录再逐条上传资产，上传失败或被新提交取消会留下可见的残缺 release，同一 run 重跑还会撞上上次留下的 tag | 上传前清理同名残留，改为 draft 创建、资产齐备后再 publish |
| 低 | ShellCheck 有两处残留告警：`prepare.sh` 的 `CDPATH= cd` 被误判为赋值笔误（SC1007），`routing-netns.sh` 的重试变量由 `seq` 展开、既被判未使用（SC2034）又在 zsh 下只迭代一次 | 前者加定向 disable 注释并说明空格用途，后者改为算术 `for` 循环，bash 与 zsh 下都迭代 20 次 |

保留当前源码锁、无线驱动、设备树和分区布局。BBR 主要影响路由器自身终结的 TCP，
不能据此承诺转发速度提升；此次没有缺乏实测依据的频率、缓冲区或硬件卸载调整。

## 第二轮审查：密码状态机（2026-09-14）

范围：`ruijie-password`、`ruijie-auth` 的门户请求路径、密码相关的 LuCI 模型与页面。
方法是逐个状态转场做反事实实验：把修复改回原样，对应测试必须变红；变不红的测试视为没有覆盖。

| 严重度 | 问题与影响 | 修复 |
| --- | --- | --- |
| 高 | 验证窗口内被中断会永久停掉认证服务：`set`/`check` 先 stop 守护进程再做最长 1 分钟的门户往返，而 procd 只 respawn 崩溃的进程，被 stop 的实例不会自己回来，校园链路会断到有人手工 start 为止 | 三个信号 trap 把中断变成一次正常退出，EXIT trap 统一走 `resume_daemon`；该函数幂等，正常返回与中断走同一条恢复路径 |
| 高 | `last_reason` 判断的是文件而不是本次尝试。`ruijie-auth` 有 5 条未发出请求的提前返回（WAN 无地址、server 非 URL、portal path 不以 / 开头、userId 为空、建不了响应临时文件）不写 `$LAST`，上一次的「门户拒绝」会被读成这一次的结论：一个从未送到门户的密码被自动回退，并告诉用户「门户拒绝了这次登录」 | `portal_request` 每条未发出请求的路径都写自己的原因；`set`/`check` 在调用前删掉 `$LAST`；只有门户以自身格式明确拒绝才回退，其余一律按「没有证据」处理 |
| 中 | `revert` 只看第一个参数是否等于 `--original`：`--orig`、`--ORIGINAL` 静默落到普通 revert，换回的是「上一个」而用户以为是最初那个；两条路径都只打印掩码，屏幕上没有区别 | 严格解析：只接受 `--original`，其余一律报错退出 |
| 中 | LuCI 按钮先测锁再写结果文件，锁冲突时直接离开：页面上留着上一次的「成功」，而这次操作根本没执行；锁忙与未验证又都被折叠成「失败」 | 锁冲突先写 `result=busy`；0、2、75 分别映射为成功、已写入但未能验证、另一个操作正在运行 |
| 中 | `set --no-test`、WAN 无 IPv4、锁忙三条路径都返回 0，把「已写入但没人验证过」显示成成功 | 退出码 2 表示已写入未验证；`check` 只有门户拒绝才返回 1，其余返回 2 |
| 中 | 网页保存用 trim 之后的值比较，只差首尾空白的值会被保存而不记录被替换的旧值，而那个旧值当时是唯一还能登录的密码 | 与命令行一致，按裸值比较 |
| 低 | `check` 先重启守护进程再读判决，而守护进程自己写这个文件，读到的可能是它刚发起的请求的结论 | 先读判决，再恢复守护进程 |
| 低 | `revert --original` 在当前值为空时把空值写进回退点，唯一还能登录的密码被丢掉 | 空值不写入回退点，并把回退点读回来显示 |
| 低 | 掩码与页面描述按字节截断：非 ASCII 值的末两位是半个字符，字节数又被当成位数报出 | shell 侧改用 `wc -c` 报字节并明确说明「含非 ASCII 字符」；Lua 侧按字符计数与截取 |
| 低 | 「最初密码」锚点用「值非空」判断，而出厂 payload 就是空值，锚点晚落一次并落在刚被替换的值上 | 改用「选项是否已写入」：`uci -q get` 对不存在的选项返回 1、对空值返回 0，正是需要的区分 |
| 低 | 中文输出旁的裸 `$VAR`（`$LAST；`）在多字节 ctype 的 shell 下会把后面的字节并进变量名，展开为空 | 改为 `${LAST}`；新增静态扫描测试，任何 shell 脚本里变量名后紧跟非 ASCII 字节即判失败 |

多字节 ctype 只在开发机的 bash/dash + UTF-8 locale 下成立，路由器上的 musl `isalpha`
只认 ASCII，所以最后一条靠静态扫描而不是运行测试发现。

## 验证与边界

本地验证包括 shell/Lua 语法、actionlint、ShellCheck、真实 HTTP 编码与响应、
凭据文件权限、curlrc 隔离、认证锁、重拨等待/超时、退避、升级保护、包开关、镜像损坏、
SSL 冲突及上游补丁回归测试；第二轮补充了密码回退状态机、陈旧判决、中断恢复、
退出码分级、非 ASCII 掩码和 shell 变量名扫描。固定 UA3F 已完成 ARMv7 交叉编译。
Linux 集成测试包含 Go 层连接标记测试和两个 network namespace WAN 的实际透明 HTTP 重写。
最终代码的 [Linux 验证 34683557944](https://github.com/louis16s/ACRH17-OpenWrt/actions/runs/34683557944)
已成功：35 项项目回归测试、Go NFQUEUE 标记测试、UA3F Linux 编译和双 WAN 透明重写均通过。
矩阵构建现在以此集成测试成功作为编译前置条件。

- 源码与离线镜像验证不能保证未知 OpBoot 版本的首次刷入兼容性；不绕过设备检查，不修改校准/引导分区。
- 尚无实体 RT-ACRH17 的启动、无线吞吐、USB/F50 供电、打印、校园门户和断线恢复证据。
- TPROXY 建立新的上游连接；这里验证的是两个出口的默认策略切换，未验证所有按 LAN 客户端源地址配置的 mwan3 规则都会传递到代理连接。
- 全新安装保留仓库既有的 `password` 管理/无线默认密码；部署时须修改，保留配置升级不再重置密码。
- 升级保护保留已有配置，因此新增 SmartDNS 默认值等只用于新安装；现有安装可在 LuCI 中按需调整。
