#!/bin/sh
# acrh17-doctor.sh -- 刷机后的检测与修复（RT-ACRH17 / 本项目 OpenWrt 24.10 镜像）
#
# 用法:
#   ./scripts/acrh17-doctor.sh --host root@192.168.5.1        只读检测（默认 check）
#   ./scripts/acrh17-doctor.sh fix --host root@192.168.5.1    检测并把安全项修回去
#   ssh root@192.168.5.1 'sh -s' < scripts/acrh17-doctor.sh   直接在路由器上跑
#
# --host 模式的私钥用 --ssh-key 指定：ssh 只自动尝试 id_rsa/id_ecdsa/id_ed25519 这几个
# 默认名字，这台路由器的钥匙不在其中，钥匙不叫默认名时就得自己给。
#
# check 只读。fix 只做幂等、非破坏性的改动：把被 sysupgrade 重置的服务开关重新
# 关掉、恢复 UA3F/mwan3 存在时不允许的 TurboACC 卸载、修回文件权限、把锐捷密码
# 状态机里「值丢失」的两种状态补回去。两个默认关闭的开关用于会动到用户可见设置
# 的修复：
#   --fix-wifi   按 2026-09-14 的实测选台重设 2.4G ch6/HT20、5G ch36/VHT80
#   --fix-auth   探测确认离线时执行一次 /usr/libexec/ruijie-auth reauth
#
# 无论哪种模式都不会改动 Wi-Fi 密码、LAN 地址、WAN 协议或 mwan3 自定义规则，
# 也不会打印任何密码明文（掩码规则与 ruijie-password 一致）。
#
# 远程模式把这些环境变量带给路由器：ACRH17_DOCTOR_MODE、_FIX_WIFI、_FIX_AUTH、
# _EXPECT_STAMP。ACRH17_DOCTOR_ROOT 只用于测试，把绝对路径换成临时根目录：
#   ACRH17_DOCTOR_ROOT=/tmp/fixture PATH=/tmp/fakebin:$PATH sh scripts/acrh17-doctor.sh

MODE="${ACRH17_DOCTOR_MODE:-check}"
FIX_WIFI="${ACRH17_DOCTOR_FIX_WIFI:-0}"
FIX_AUTH="${ACRH17_DOCTOR_FIX_AUTH:-0}"
EXPECT_STAMP="${ACRH17_DOCTOR_EXPECT_STAMP:-}"
ROOT="${ACRH17_DOCTOR_ROOT:-}"
HOST=''
SSH_KEY="${ACRH17_SSH_KEY:-}"

usage() {
	cat <<'EOF'
用法: acrh17-doctor.sh [check|fix] [选项]

  check                只读检测（默认）
  fix                  检测并修复安全项（见脚本头部说明）
  --host [user@]地址   从开发机远程执行；把本脚本通过 ssh 送到路由器上运行
  --ssh-key 路径       远程模式用的私钥；ssh 只会自动尝试 id_rsa/id_ecdsa/id_ed25519
  --expect-stamp 值    期望的固件版本戳（YYYYMMDD-HHMM），不匹配时报错
  --fix-wifi           重设 2.4G ch6/HT20 与 5G ch36/VHT80
  --fix-auth           探测确认离线时执行一次 reauth
  -h, --help           显示本帮助
EOF
}

while [ $# -gt 0 ]; do
	arg="$1"
	shift
	case "$arg" in
		check|fix) MODE="$arg" ;;
		--host) HOST="${1:-}"; [ $# -gt 0 ] && shift ;;
		--host=*) HOST="${arg#--host=}" ;;
		--ssh-key) SSH_KEY="${1:-}"; [ $# -gt 0 ] && shift ;;
		--ssh-key=*) SSH_KEY="${arg#--ssh-key=}" ;;
		--expect-stamp) EXPECT_STAMP="${1:-}"; [ $# -gt 0 ] && shift ;;
		--expect-stamp=*) EXPECT_STAMP="${arg#--expect-stamp=}" ;;
		--fix-wifi) FIX_WIFI=1 ;;
		--fix-auth) FIX_AUTH=1 ;;
		-h|--help) usage; exit 0 ;;
		*) usage >&2; exit 2 ;;
	esac
done

# 这个值原样嵌进 ssh 的远程命令串，单引号会破坏引号配对，把剩余部分变成路由器上
# 的又一条命令。MODE/FIX_WIFI/FIX_AUTH 都出自固定取值，只有 --expect-stamp 是自由文本。
case "${EXPECT_STAMP}" in
	*"'"*) echo '参数里不能有单引号。' >&2; exit 2;;
esac

if [ -n "$HOST" ]; then
	if [ ! -f "$0" ]; then
		echo '远程模式需要以脚本文件方式运行，例如 ./scripts/acrh17-doctor.sh --host root@192.168.5.1' >&2
		exit 2
	fi
	# IdentitiesOnly 是跟着 -i 一起来的：不限制的话 agent 会把它持有的每一把钥匙
	# 都递一遍，在路由器那种 MaxAuthTries 很小的地方还没轮到指定这把就断开了。
	set --
	[ -z "$SSH_KEY" ] || set -- -i "$SSH_KEY" -o IdentitiesOnly=yes
	exec ssh -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new "$@" "$HOST" \
		"ACRH17_DOCTOR_MODE=${MODE} ACRH17_DOCTOR_FIX_WIFI=${FIX_WIFI} ACRH17_DOCTOR_FIX_AUTH=${FIX_AUTH} ACRH17_DOCTOR_EXPECT_STAMP='${EXPECT_STAMP}' sh -s" < "$0"
fi

if [ ! -f "${ROOT}/etc/openwrt_release" ]; then
	echo "这里不是 OpenWrt 设备（缺少 ${ROOT}/etc/openwrt_release）。" >&2
	echo '要检测路由器请加 --host root@192.168.5.1，或把本脚本送到路由器上执行。' >&2
	exit 2
fi

CNT_OK=0
CNT_WARN=0
CNT_FAIL=0
CNT_FIXED=0
CHANGES=''

section() { printf '\n--- %s ---\n' "$1"; }
ok() { CNT_OK=$((CNT_OK + 1)); printf '[ OK ] %s\n' "$1"; }
info() { printf '[INFO] %s\n' "$1"; }
skip() { printf '[SKIP] %s\n' "$1"; }
warn() { CNT_WARN=$((CNT_WARN + 1)); printf '[WARN] %s\n' "$1"; }
fail() { CNT_FAIL=$((CNT_FAIL + 1)); printf '[FAIL] %s\n' "$1"; }
fixed() {
	CNT_FIXED=$((CNT_FIXED + 1))
	CHANGES="${CHANGES}  - $1
"
	printf '[FIX ] %s\n' "$1"
}

# trouble <问题> <修复命令>：check 只报告并给出命令，fix 直接执行；执行成功算已修复，
# 失败仍然计为失败，避免「修了但还是坏的」被当成通过。
trouble() {
	if [ "$MODE" = fix ]; then
		if eval "$2" >/dev/null 2>&1; then
			fixed "$1"
		else
			fail "$1（自动修复失败，请手动执行: $2）"
		fi
	else
		fail "$1（修复命令: $2）"
	fi
}

uget() { uci -q get "$1" 2>/dev/null; }

# rc.d 里没有 /etc/rc.d 的 keep.d 条目，sysupgrade 重建 rootfs_data 后服务会回到
# 启用状态，所以「是否启用」只能看符号链接，不能看 /etc/config 里的选项。
svc_enabled() {
	for link in "${ROOT}/etc/rc.d"/S[0-9][0-9]"$1"; do
		[ -e "$link" ] && return 0
	done
	return 1
}

svc_running() { # 用 init 脚本自己的 running 判断，和 LuCI 页面一致
	"${ROOT}/etc/init.d/$1" running >/dev/null 2>&1
}

# busybox 镜像不保证带 pgrep，所以按 ps 的完整命令行匹配。调用方把模式写成
# [/]usr/bin/xxx 这种形式（首字符加方括号），这样模式本身不会匹配到自己。
# shellcheck disable=SC2009
cmd_running() {
	ps w 2>/dev/null | grep -v grep | grep -q "$1"
}

# 与 ruijie-password 的 mask 保持同一套规则：非 ASCII 值只报字节数，纯 ASCII 值报
# 位数和末两位。字节数用 wc -c，字符数用 ${#1} 在多字节 ctype 下会与实际单位不符。
mask() {
	[ -n "$1" ] || { printf '(未设置)'; return; }
	if [ -n "$(printf '%s' "$1" | LC_ALL=C tr -d '\000-\177')" ]; then
		printf '含非 ASCII 字符（%s 字节）' "$(printf '%s' "$1" | wc -c | tr -d '[:space:]')"
		return
	fi
	printf '%s 位，末两位 %s' "${#1}" "$(printf '%s' "$1" | tail -c 2)"
}

# 列表成员：uci get 对 list 返回空格分隔的值
has_word() {
	case " $1 " in *" $2 "*) return 0 ;; *) return 1 ;; esac
}

PKG_CACHE=''
load_pkgs() {
	if [ -z "$PKG_CACHE" ]; then
		PKG_CACHE="$(opkg list-installed 2>/dev/null | awk '{print $1}')"
	fi
}
pkg_installed() {
	load_pkgs
	[ -n "$PKG_CACHE" ] || return 1
	printf '%s\n' "$PKG_CACHE" | grep -qx "$1"
}

# 权限读数：busybox 不一定把 stat 编进来，而 GNU 的 `stat -c` 与 BSD 的 `stat -f`
# 语法互不兼容，真机上两条都失败——权限检查会整段静默（case 的空分支），看起来像
# 通过了。`ls -l` 在三种实现里第一字段都是同一个符号串，从它换算出八进制。
file_mode() {
	# 这里只读脚本自己写死的几个路径，不枚举目录，SC2012 的顾虑不适用。
	# shellcheck disable=SC2012
	LC_ALL=C ls -ld "$1" 2>/dev/null | awk '{
		p = substr($1, 2)
		if (length(p) < 9) exit
		n = 0
		for (i = 1; i <= 9; i += 3) {
			v = 0
			if (substr(p, i, 1) != "-") v += 4
			if (substr(p, i + 1, 1) != "-") v += 2
			if (substr(p, i + 2, 1) != "-") v += 1
			n = n * 10 + v
		}
		print n
	}'
}

# check_sysctl <key> <expected> <file-under-/etc/sysctl.d>
check_sysctl() {
	# 内核按点分名在 /proc/sys 下分层，net.ipv4.tcp_congestion_control 对应
	# /proc/sys/net/ipv4/tcp_congestion_control。
	path="$(printf '%s' "$1" | tr '.' '/')"
	value="$(cat "${ROOT}/proc/sys/${path}" 2>/dev/null)"
	if [ "$value" = "$2" ]; then
		ok "${1}=${2}"
	else
		trouble "${1} 实际是 ${value:-读不到}，应为 ${2}" \
			"sysctl -p ${ROOT}/etc/sysctl.d/${3} >/dev/null 2>&1 || sysctl -w ${1}=${2}"
	fi
}

LISTEN_CACHE=''
listen_snapshot() {
	if [ -z "$LISTEN_CACHE" ]; then
		LISTEN_CACHE="$(netstat -lntu 2>/dev/null || ss -lntu 2>/dev/null)"
	fi
}

# ---------------------------------------------------------------- 平台与版本

group_platform() {
	section '平台与版本'
	release="${ROOT}/etc/openwrt_release"
	descr="$(sed -n "s/^DISTRIB_DESCRIPTION='\(.*\)'$/\1/p" "$release")"
	[ -n "$descr" ] || descr="$(sed -n 's/^DISTRIB_DESCRIPTION=//p' "$release" | tr -d "'")"
	stamp="$(printf '%s' "$descr" | grep -o '[0-9]\{8\}-[0-9]\{4\}' | head -n 1)"
	if [ -z "$stamp" ]; then
		fail "固件版本里没有构建时间戳: ${descr:-（读不到 DISTRIB_DESCRIPTION）}"
	elif [ -n "$EXPECT_STAMP" ] && [ "$stamp" != "$EXPECT_STAMP" ]; then
		fail "固件戳 ${stamp}，期望 ${EXPECT_STAMP}（刷入的不是这一次构建）"
	else
		ok "固件版本 ${descr}"
	fi
	for key in DISTRIB_RELEASE DISTRIB_REVISION DISTRIB_TARGET DISTRIB_ARCH; do
		value="$(sed -n "s/^${key}='\(.*\)'$/\1/p" "$release")"
		[ -n "$value" ] && info "${key}=${value}"
	done

	board="$(cat "${ROOT}/tmp/sysinfo/board_name" 2>/dev/null)"
	case "$board" in
		asus,rt-ac42u) ok "设备 ${board}" ;;
		'') warn '读不到 /tmp/sysinfo/board_name' ;;
		*) fail "设备是 ${board}，不是 asus,rt-ac42u" ;;
	esac
	model="$(cat "${ROOT}/tmp/sysinfo/model" 2>/dev/null)"
	[ -n "$model" ] && info "型号 ${model}"

	kernel="$(uname -r 2>/dev/null)"
	case "$kernel" in
		6.6.*) ok "内核 ${kernel}" ;;
		'') warn 'uname 不可用' ;;
		*) warn "内核 ${kernel}，镜像锁的是 6.6.x" ;;
	esac

	uptime_secs="$(cut -d' ' -f1 "${ROOT}/proc/uptime" 2>/dev/null)"
	uptime_secs="${uptime_secs%%.*}"   # /proc/uptime 带小数，算术展开只吃整数
	if [ -n "$uptime_secs" ]; then
		if [ "$uptime_secs" -ge 3600 ]; then
			info "运行了 ${uptime_secs} 秒（约 $((uptime_secs / 3600)) 小时）"
		else
			info "运行了 ${uptime_secs} 秒"
		fi
	fi
	load="$(cut -d' ' -f1-3 "${ROOT}/proc/loadavg" 2>/dev/null)"
	[ -n "$load" ] && info "负载 ${load}"
	avail="$(awk '/^MemAvailable:/ {printf "%d", $2 / 1024}' "${ROOT}/proc/meminfo" 2>/dev/null)"
	[ -n "$avail" ] && info "可用内存 ${avail} MiB"

	if [ -d "${ROOT}/overlay" ]; then
		free_kb="$(df -k "${ROOT}/overlay" 2>/dev/null | tail -n 1 | awk '{print $4}')"
		case "$free_kb" in
			''|*[!0-9]*) skip '读不到 overlay 可用空间' ;;
			*)
				if [ "$free_kb" -lt 512 ]; then
					fail "overlay 只剩 ${free_kb} KiB，改配置可能写不进去"
				elif [ "$free_kb" -lt 2048 ]; then
					warn "overlay 可用 ${free_kb} KiB，偏少"
				else
					ok "overlay 可用 $((free_kb / 1024)) MiB"
				fi
				;;
		esac
	else
		skip '没有 /overlay（不是 squashfs + overlay 布局？）'
	fi
}

# ---------------------------------------------------------------- 升级保留

group_upgrade() {
	section '升级保留（sysupgrade 之后）'

	if [ "$(uget acrh17.settings.defaults_applied)" = 1 ]; then
		ok '配置保留标记 defaults_applied=1'
	else
		# 标记由 90-acrh17 的守卫自己写；缺失说明初始化脚本没跑到守卫，或者这是
		# 一个被手工改过的配置。补上它是安全的：守卫另一条判据（root 密码非空）也
		# 会拦住工厂默认值，不会因为补标记而重置任何设置。
		trouble '缺少 acrh17.settings.defaults_applied=1（初始化守卫可能没执行）' \
			'uci -q set acrh17.settings.defaults_applied=1 && uci -q commit acrh17'
	fi

	shadow_root="$(awk -F: '$1 == "root" {print $2}' "${ROOT}/etc/shadow" 2>/dev/null)"
	if [ -z "$shadow_root" ]; then
		fail 'root 密码为空（配置可能被重置；先在 LuCI 里改回管理密码）'
	else
		ok 'root 密码非空（保留配置升级的判据之一）'
	fi

	keep="${ROOT}/lib/upgrade/keep.d/acrh17"
	if [ ! -f "$keep" ]; then
		fail '镜像里没有 /lib/upgrade/keep.d/acrh17，打印驱动 blob 会在下次升级丢失'
	elif grep -qx '/opt/p910nd_drivers' "$keep"; then
		ok 'keep.d 保留了 /opt/p910nd_drivers'
	else
		fail '/lib/upgrade/keep.d/acrh17 没有 /opt/p910nd_drivers 条目'
	fi

	if [ -d "${ROOT}/opt/p910nd_drivers" ]; then
		blobs=0
		for blob in "${ROOT}/opt/p910nd_drivers"/*; do
			[ -e "$blob" ] && blobs=$((blobs + 1))
		done
		ok "打印驱动目录存在，${blobs} 个文件"
	elif [ -f "${ROOT}/opt/p910nd_drivers" ]; then
		warn '/opt/p910nd_drivers 是文件而不是目录'
	else
		info '没有 /opt/p910nd_drivers（还没装过打印驱动，属正常）'
	fi
	if [ -f "${ROOT}/etc/sysupgrade.conf" ] &&
	   grep -q '/opt/p910nd_drivers' "${ROOT}/etc/sysupgrade.conf" 2>/dev/null; then
		info '/etc/sysupgrade.conf 也留了这条（该文件自身不被保留，只作参考）'
	fi

	hostname="$(uget system.@system[0].hostname)"
	[ -n "$hostname" ] && info "主机名 ${hostname}"
	timezone="$(uget system.@system[0].timezone)"
	[ -n "$timezone" ] && info "时区 ${timezone}"

	ifaces="$(uci show wireless 2>/dev/null | sed -n 's/^wireless\.\([^.=]*\)=wifi-iface$/\1/p')"
	if [ -z "$ifaces" ]; then
		warn '读不到 wireless 配置（无线设置可能被重置）'
	else
		blank=''
		for iface in $ifaces; do
			ssid="$(uget "wireless.${iface}.ssid")"
			key="$(uget "wireless.${iface}.key")"
			if [ -z "$ssid" ] || [ -z "$key" ]; then
				blank="${blank} ${iface}"
			else
				info "无线 ${iface}: ${ssid} / 密码 $(mask "$key")"
			fi
		done
		if [ -n "$blank" ]; then
			fail "这些无线接口的 SSID 或密码为空:${blank}（配置可能被重置）"
		else
			ok '无线 SSID 与密码都还在'
		fi
	fi
}

# ---------------------------------------------------------------- 服务开关

group_services() {
	section '服务开关'

	# /etc/rc.d 不在任何 keep.d 条目里，每次升级都会复位；watchcat 复活后会按
	# 8.8.8.8 每 6 小时探测并在失败时强制重启，所以这三个必须一直是关的。
	for svc in watchcat ddns mwan3; do
		if svc_enabled "$svc"; then
			trouble "${svc} 被重新启用了（升级会复位 /etc/rc.d）" \
				"[ -x ${ROOT}/etc/init.d/${svc} ] && ${ROOT}/etc/init.d/${svc} disable && ${ROOT}/etc/init.d/${svc} stop"
		elif [ -x "${ROOT}/etc/init.d/$svc" ]; then
			ok "${svc} 未启用"
		fi
	done

	# 项目默认要开的服务。缺符号链接时功能看起来正常（进程可能还在跑），但重启后
	# 就没了，所以这里按「启用」判定。
	for svc in smartdns ua3f irqbalance turboacc; do
		[ -x "${ROOT}/etc/init.d/$svc" ] || { warn "缺少 /etc/init.d/${svc}"; continue; }
		if svc_enabled "$svc"; then
			ok "${svc} 已启用"
		else
			trouble "${svc} 没有开机自启（/etc/rc.d 里没有它的链接）" \
				"${ROOT}/etc/init.d/${svc} enable"
		fi
	done

	# 锐捷认证服务：配置里打开才要求自启；打开了却没跑才算失败。
	if [ "$(uget ruijie.main.enabled)" = 1 ]; then
		if svc_running ruijie-auth || cmd_running '[/]usr/libexec/ruijie-auth daemon'; then
			ok '锐捷认证服务在运行'
		else
			trouble '锐捷认证已在配置里启用，但服务没在运行' \
				"${ROOT}/etc/init.d/ruijie-auth enable && ${ROOT}/etc/init.d/ruijie-auth start"
		fi
		if ! svc_enabled ruijie-auth; then
			trouble '锐捷认证服务不会开机自启' "${ROOT}/etc/init.d/ruijie-auth enable"
		fi
	else
		info '锐捷认证在配置里是关闭的（ruijie.main.enabled=0）'
	fi

	# mwan3 的 service_running() 只看 /var/run/mwan3 目录在不在，重复安装或异常
	# 退出会留下这个过期目录，导致 LuCI 与 mwan3 status 都显示成「在运行」。
	# 这里 09-15 之前用的是 rmdir，而它一次也没成功过：真实的残留目录里必然有
	# iface_state/、iptables_log/、mmx_mask 这些 mwan3 自己写的运行时状态，rmdir
	# 只会报 Directory not empty 然后放弃——等于这个修复是摆设（09-15 在真机上
	# 就是这么失败的）。目录里没有配置，配置在 /etc/config/mwan3；上面那个判断
	# 又已经确认 mwan3 既没开机自启也没在跑，所以整个删掉是安全的。
	if [ -d "${ROOT}/var/run/mwan3" ] && ! svc_enabled mwan3 && ! cmd_running '[/]usr/sbin/mwan3'; then
		if [ "$MODE" = fix ]; then
			if rm -rf "${ROOT}/var/run/mwan3"; then
				fixed '清掉了过期的 /var/run/mwan3 目录（它让 mwan3 看起来像在运行）'
			else
				warn '/var/run/mwan3 删不掉；mwan3 status 会继续显示 tracking down'
			fi
		else
			fail '存在过期的 /var/run/mwan3，mwan3 会被误报成运行中（修复命令: rm -rf /var/run/mwan3）'
		fi
	fi

	if cmd_running '[/]usr/sbin/dnsmasq'; then
		ok 'dnsmasq 在运行'
	else
		trouble 'dnsmasq 没在运行，LAN 客户端无法解析域名' \
			"${ROOT}/etc/init.d/dnsmasq restart"
	fi
	if svc_enabled ua3f && ! cmd_running '[/]usr/bin/ua3f'; then
		trouble 'ua3f 已启用但进程不在' "${ROOT}/etc/init.d/ua3f restart"
	fi

	listen_snapshot
	if printf '%s' "$LISTEN_CACHE" | grep -q '6053'; then
		ok 'SmartDNS 在监听 6053'
	else
		trouble 'SmartDNS 没有监听 6053（dnsmasq 的上游是 127.0.0.1#6053，解析会全断）' \
			"${ROOT}/etc/init.d/smartdns restart"
	fi
	# 限制入口靠的是 SO_BINDTODEVICE（bind_device + bind_device_name），不是监听地址：
	# 开了设备绑定，netstat 里照样是通配地址。按监听地址判会把这份正确配置报成
	# 「没绑回环」——真机上就是这么误报的。
	sd_bind="$(uget smartdns.@smartdns[0].bind_device)"
	sd_dev="$(uget smartdns.@smartdns[0].bind_device_name)"
	if [ "$sd_bind" = 1 ] && [ "$sd_dev" = lo ]; then
		ok 'SmartDNS 只收 lo 的查询（bind_device=1, bind_device_name=lo）'
	elif printf '%s' "$LISTEN_CACHE" | grep -q '127\.0\.0\.1:6053'; then
		ok 'SmartDNS 监听 127.0.0.1:6053'
	else
		trouble "SmartDNS 没绑回环（bind_device=${sd_bind:-未设} name=${sd_dev:-未设}），局域网可直接查 6053" \
			"uci -q set smartdns.@smartdns[0].bind_device=1 && uci -q set smartdns.@smartdns[0].bind_device_name=lo && uci -q commit smartdns && ${ROOT}/etc/init.d/smartdns restart"
	fi

	if [ "$(uget p910nd.@p910nd[0].enabled)" = 1 ]; then
		info 'p910nd 已启用（用户在 LuCI 里打开的，保持不动）'
	else
		info 'p910nd 未启用（默认值）'
	fi
}

# ---------------------------------------------------------------- 网络

group_network() {
	section '网络'

	lan_ip="$(uget network.lan.ipaddr)"
	case "$lan_ip" in
		192.168.5.1) ok 'LAN 地址 192.168.5.1' ;;
		'') warn 'LAN 没有静态地址（配置可能被重置）' ;;
		*) warn "LAN 地址是 ${lan_ip}，项目默认 192.168.5.1（若是自己改的就忽略；改回命令: uci set network.lan.ipaddr=192.168.5.1 && uci commit network && /etc/init.d/network reload）" ;;
	esac
	if command -v ip >/dev/null 2>&1; then
		live="$(ip -4 addr show br-lan 2>/dev/null | sed -n 's/.*inet \([0-9.]*\)\/.*/\1/p' | head -n 1)"
		if [ -n "$live" ]; then
			if [ -n "$lan_ip" ] && [ "$live" != "$lan_ip" ]; then
				warn "br-lan 实际地址 ${live} 与配置 ${lan_ip} 不一致（需要 /etc/init.d/network reload）"
			else
				info "br-lan 实际地址 ${live}"
			fi
		fi
	fi

	case "$(uget network.lan.ip6assign)" in
		0) ok 'LAN 不发 IPv6（ip6assign=0）' ;;
		'') warn 'network.lan.ip6assign 没设置（老配置的默认值会对 LAN 下发 IPv6 前缀）' ;;
		*) trouble "network.lan.ip6assign=$(uget network.lan.ip6assign)，镜像按纯 IPv4 设计" \
			'uci -q set network.lan.ip6assign=0 && uci -q commit network' ;;
	esac
	if uci -q show network.wan6 >/dev/null 2>&1; then
		wan6_proto="$(uget network.wan6.proto)"
		wan6_auto="$(uget network.wan6.auto)"
		if [ "$wan6_proto" = none ] && [ "$wan6_auto" = 0 ]; then
			ok 'wan6 已停用（proto=none, auto=0）'
		else
			trouble "wan6 还在跑（proto=${wan6_proto:-未设}, auto=${wan6_auto:-未设}）" \
				'uci -q set network.wan6.proto=none && uci -q set network.wan6.auto=0 && uci -q commit network'
		fi
	else
		info '配置里没有 wan6 段'
	fi

	fw_disable_v6="$(uget firewall.@defaults[0].disable_ipv6)"
	if [ "$fw_disable_v6" = 1 ]; then
		ok '防火墙禁用 IPv6'
	else
		trouble "firewall.@defaults[0].disable_ipv6=${fw_disable_v6:-未设}" \
			"uci -q set firewall.@defaults[0].disable_ipv6=1 && uci -q commit firewall && ${ROOT}/etc/init.d/firewall reload"
	fi
	for key in flow_offloading flow_offloading_hw; do
		value="$(uget "firewall.@defaults[0].${key}")"
		if [ "$value" = 0 ]; then
			ok "防火墙 ${key}=0"
		else
			trouble "firewall.@defaults[0].${key}=${value:-未设}（与 UA3F/mwan3 冲突）" \
				"uci -q set firewall.@defaults[0].${key}=0 && uci -q commit firewall && ${ROOT}/etc/init.d/firewall reload"
		fi
	done

	# dnsmasq 是 LAN 的 DNS 入口，SmartDNS 在 6053 做后端；直连 IPv4 服务器是
	# SmartDNS 没起来时的回退，校园内网域名必须交给校园 DNS 解析。
	dns_servers="$(uget dhcp.@dnsmasq[0].server)"
	if [ "$(uget dhcp.@dnsmasq[0].noresolv)" = 1 ]; then
		ok 'dnsmasq 不读上游 resolv.conf'
	else
		trouble 'dhcp.@dnsmasq[0].noresolv 不是 1' \
			"uci -q set dhcp.@dnsmasq[0].noresolv=1 && uci -q commit dhcp && ${ROOT}/etc/init.d/dnsmasq restart"
	fi
	missing=''
	for entry in '127.0.0.1#6053' 223.5.5.5 119.29.29.29 114.114.114.114 '/scau.edu.cn/202.116.160.33'; do
		has_word "$dns_servers" "$entry" || missing="${missing} ${entry}"
	done
	if [ -z "$missing" ]; then
		ok 'dnsmasq 服务器列表包含 SmartDNS、三个直连回退和校园 DNS 分流'
	else
		# $s 要在 eval 时才展开，所以这条修复命令必须保持单引号。
		# shellcheck disable=SC2016
		dns_fix='for s in 127.0.0.1#6053 223.5.5.5 119.29.29.29 114.114.114.114 /scau.edu.cn/202.116.160.33; do uci -q add_list dhcp.@dnsmasq[0].server="$s"; done && uci -q commit dhcp && ${ROOT}/etc/init.d/dnsmasq restart'
		trouble "dnsmasq 缺少这些服务器:${missing}" "$dns_fix"
	fi
	if has_word "$(uget dhcp.@dnsmasq[0].rebind_domain)" scau.edu.cn; then
		ok '解析结果豁免名单含 scau.edu.cn'
	else
		trouble 'dnsmasq 的 rebind_domain 里没有 scau.edu.cn（校园域名会被重绑定保护丢掉）' \
			"uci -q add_list dhcp.@dnsmasq[0].rebind_domain=scau.edu.cn && uci -q commit dhcp && ${ROOT}/etc/init.d/dnsmasq restart"
	fi

	# 校园 WAN：能不能上网取决于校园网，这里只报告，不算失败。
	wan="$(uget ruijie.main.wan_interface)"
	[ -n "$wan" ] || wan=wan
	if command -v ubus >/dev/null 2>&1; then
		wan_json="$(ubus call "network.interface.${wan}" status 2>/dev/null)"
		wan_up="$(printf '%s' "$wan_json" | jsonfilter -e '@.up' 2>/dev/null)"
		wan_ip="$(printf '%s' "$wan_json" | jsonfilter -e '@["ipv4-address"][0].address' 2>/dev/null)"
		if [ "$wan_up" = true ] && [ -n "$wan_ip" ]; then
			ok "WAN ${wan} up，地址 ${wan_ip}"
		else
			info "WAN ${wan} 没有 IPv4（校园网未接或未认证，不算故障）"
		fi
	fi

	# mwan3：只在这个变体上检查策略路由的关键项，且服务本身是关的，改配置没有立即影响。
	if [ -f "${ROOT}/etc/config/mwan3" ]; then
		mmx="$(uget mwan3.globals.mmx_mask)"
		if [ "$mmx" = 0x3f000000 ]; then
			ok 'mwan3 mmx_mask=0x3f000000（避开 UA3F 的低 16 位）'
		else
			trouble "mwan3.globals.mmx_mask=${mmx:-未设}" \
				'uci -q set mwan3.globals.mmx_mask=0x3f000000 && uci -q commit mwan3'
		fi
		for sec in wan6 wanb6; do
			uci -q show "mwan3.${sec}" >/dev/null 2>&1 || continue
			if [ "$(uget "mwan3.${sec}.enabled")" = 0 ]; then
				ok "mwan3.${sec} 已停用"
			else
				trouble "mwan3.${sec} 还在启用" \
					"uci -q set mwan3.${sec}.enabled=0 && uci -q commit mwan3"
			fi
		done
		probes="$(uget acrh17.settings.mwan3_probe_ip)"
		for msec in $(uget acrh17.settings.mwan3_interface); do
			uci -q show "mwan3.${msec}" >/dev/null 2>&1 || continue
			[ "$(uget "mwan3.${msec}.family")" = ipv6 ] && continue
			family="$(uget "mwan3.${msec}.family")"
			track="$(uget "mwan3.${msec}.track_ip")"
			[ "$family" = ipv4 ] || warn "mwan3.${msec}.family=${family:-未设}"
			missing=''
			for target in $probes; do
				has_word "$track" "$target" || missing="${missing} ${target}"
			done
			[ -z "$missing" ] || trouble "mwan3.${msec} 缺少探测目标:${missing}" \
				"for ip in ${probes}; do uci -q add_list mwan3.${msec}.track_ip=\"\$ip\"; done && uci -q commit mwan3"
		done
	else
		info '这是单 WAN 变体（没有 /etc/config/mwan3），跳过 mwan3 检查'
	fi

	# TurboACC 的运行时补丁在 UA3F 或 mwan3 启用时强制关掉三种卸载。补丁在镜像里
	# 的标志是这段守卫；缺了它，LuCI 里一开卸载就会绕过 UA3F 的 netfilter 钩子。
	turboacc_init="${ROOT}/etc/init.d/turboacc"
	if [ -f "$turboacc_init" ]; then
		if grep -q 'Flow offload disabled while UA3F or mwan3 is enabled' "$turboacc_init"; then
			ok '镜像带 TurboACC 运行时守卫'
		else
			fail 'TurboACC 初始化脚本里没有卸载守卫（这不是本项目的镜像？）'
		fi
	fi

	for key in sw_flow hw_flow sfe_flow; do
		value="$(uget "turboacc.config.${key}")"
		if [ "$value" = 0 ]; then
			ok "turboacc ${key}=0"
		else
			# 运行时守卫会把它们压成 0，但配置里留着 1 会让 LuCI 与页面显示不一致，
			# 也让「谁在生效」变得要靠猜。
			trouble "turboacc ${key}=${value:-未设}（UA3F/mwan3 存在时不允许）" \
				"uci -q set turboacc.config.${key}=0 && uci -q commit turboacc && ${ROOT}/etc/init.d/turboacc restart"
		fi
	done
	if [ "$(uget turboacc.config.bbr_cca)" = 1 ]; then
		ok 'turboacc bbr_cca=1'
	else
		trouble 'turboacc bbr_cca 不是 1' \
			"uci -q set turboacc.config.bbr_cca=1 && uci -q commit turboacc && ${ROOT}/etc/init.d/turboacc restart"
	fi
	if command -v nft >/dev/null 2>&1; then
		flowtables="$(nft list ruleset 2>/dev/null | grep -c 'flowtable')"
		if [ "$flowtables" = 0 ]; then
			ok '规则集里没有 flowtable（卸载确实没生效）'
		else
			warn "规则集里有 ${flowtables} 处 flowtable，卸载可能仍在生效"
		fi
	fi

	# sysctl 来自 /etc/sysctl.d，重启后由 sysctl 服务重新应用，这里同时核对文件与运行值。
	for file in 90-acrh17-bbr.conf 91-acrh17-ipv6-off.conf; do
		if [ -f "${ROOT}/etc/sysctl.d/$file" ]; then
			ok "sysctl 文件 ${file} 在"
		else
			fail "缺少 /etc/sysctl.d/${file}"
		fi
	done
	check_sysctl net.ipv4.tcp_congestion_control bbr 90-acrh17-bbr.conf
	check_sysctl net.core.default_qdisc fq 90-acrh17-bbr.conf
	check_sysctl net.ipv6.conf.all.disable_ipv6 1 91-acrh17-ipv6-off.conf

	if grep -q '/dev/zram0' "${ROOT}/proc/swaps" 2>/dev/null; then
		zram_kb="$(awk '/\/dev\/zram0/ {print $3}' "${ROOT}/proc/swaps" 2>/dev/null)"
		ok "zram 交换已启用（${zram_kb} KiB）"
	else
		trouble 'zram 交换没在 /proc/swaps 里' \
			"${ROOT}/etc/init.d/zram enable && ${ROOT}/etc/init.d/zram start"
	fi
}

# ---------------------------------------------------------------- UA3F

group_ua3f() {
	section 'UA3F'

	if [ "$(uget ua3f.enabled.enabled)" = 1 ]; then
		ok 'UA3F 在配置里启用'
	else
		trouble 'ua3f.enabled.enabled 不是 1（UA 改写与透明代理都不会生效）' \
			"uci -q set ua3f.enabled.enabled=1 && uci -q commit ua3f && ${ROOT}/etc/init.d/ua3f restart"
	fi

	# L3 重写只开 TTL 与 TCP 时间戳：定值 64 让转发流量看起来像一跳之外的 Linux
	# 主机，去掉时间戳是另一处指纹。两者都只作用于 SYN，数据面没有新增开销。
	if [ "$(uget ua3f.main.l3_rewrite_ttl)" = 1 ] &&
	   [ "$(uget ua3f.main.l3_rewrite_ttl_value)" = 64 ] &&
	   [ "$(uget ua3f.main.l3_rewrite_tcpts)" = 1 ]; then
		ok 'L3 重写: TTL 64 + 去 TCP 时间戳'
	else
		trouble "L3 重写不是 TTL 64 + 去时间戳（ttl=$(uget ua3f.main.l3_rewrite_ttl) value=$(uget ua3f.main.l3_rewrite_ttl_value) tcpts=$(uget ua3f.main.l3_rewrite_tcpts)）" \
			"uci -q set ua3f.main.l3_rewrite_ttl=1 && uci -q set ua3f.main.l3_rewrite_ttl_value=64 && uci -q set ua3f.main.l3_rewrite_tcpts=1 && uci -q commit ua3f && ${ROOT}/etc/init.d/ua3f restart"
	fi
	# ipid 在现代 Linux 上是空操作且每包多一次排队；tcpwin 65535 本身就是指纹；
	# block_quic 会打断 HTTP/3；bpf_offload 需要镜像里没有的 kmod-sched-bpf。
	for key in l3_rewrite_ipid l3_rewrite_tcpwin block_quic bpf_offload; do
		if [ "$(uget "ua3f.main.${key}")" = 1 ]; then
			info "ua3f.main.${key}=1（不是默认取舍，确认是有意打开的）"
		fi
	done

	# mwan3 用高位 mark 选路，UA3F 只应比较低 16 位并在写回时保留高位。这条能从
	# 运行中的规则看出来；看不到掩码时不能断定坏了（不同变体的规则形态不同），
	# 所以是警告而不是失败。
	if command -v nft >/dev/null 2>&1; then
		masks="$(nft list ruleset 2>/dev/null | grep -c '0xffff')"
		if [ "$masks" -gt 0 ]; then
			ok "规则里有 ${masks} 处 0xffff 掩码，UA3F 不会覆盖 mwan3 的高位 mark"
		else
			warn '运行中的规则里没有掩码表达式，UA3F 与 mwan3 的 mark 可能互相覆盖'
		fi
	fi

	ua3f_log="${ROOT}/var/log/ua3f/ua3f.log"
	if [ -f "$ua3f_log" ]; then
		size="$(wc -c < "$ua3f_log" | tr -d '[:space:]')"
		info "ua3f.log ${size} 字节"
	fi
}

# ---------------------------------------------------------------- 无线

group_wireless() {
	section '无线'
	country_default="$(uget acrh17.settings.wifi_country)"
	[ -n "$country_default" ] || country_default=AU

	radios="$(uci show wireless 2>/dev/null | sed -n 's/^wireless\.\([^.=]*\)=wifi-device$/\1/p')"
	if [ -z "$radios" ]; then
		warn '读不到无线设备配置'
		return
	fi
	for radio in $radios; do
		band="$(uget "wireless.${radio}.band")"
		disabled="$(uget "wireless.${radio}.disabled")"
		country="$(uget "wireless.${radio}.country")"
		channel="$(uget "wireless.${radio}.channel")"
		htmode="$(uget "wireless.${radio}.htmode")"
		if [ "$disabled" = 0 ]; then
			ok "${radio}(${band}) 未禁用"
		else
			trouble "${radio}(${band}) 是禁用的" \
				"uci -q set wireless.${radio}.disabled=0 && uci -q commit wireless && wifi reload"
		fi
		if [ "$country" = "$country_default" ]; then
			ok "${radio} 国家码 ${country}"
		else
			trouble "${radio} 国家码 ${country:-未设}，应为 ${country_default}" \
				"uci -q set wireless.${radio}.country=${country_default} && uci -q commit wireless && wifi reload"
		fi
		info "${radio} 信道 ${channel:-auto} / 模式 ${htmode:-默认}"

		# 2026-09-15 起这里只管 htmode，信道一个字都不写。09-14 曾按一次扫描把
		# 2.4G 定成 ch6（理由「同频干扰比 ch1 低 6 倍」），09-15 三次复扫得到相反
		# 结论：ch5 上一台 -45 dBm 的 SCAUNET_1x 把 ch6 压到 -44 dBm，ch1 有
		# -66 dBm，差 20 dB。射频环境会变，而写死的信道在环境变了以后不会自己
		# 纠正，只会把用户从好信道推到坏信道上——「优选信道」必须是现场扫描的
		# 结论，不能是别人昨天量出来的常量。htmode 不是同一类东西：HT20/VHT80
		# 是网卡能力问题，跟邻居无关，所以照旧强制。
		case "$band" in
			2g) want_htmode=HT20 ;;
			5g) want_htmode=VHT80 ;;
			*) continue ;;
		esac
		if [ "$htmode" = "$want_htmode" ]; then
			ok "${radio} 无线模式 ${want_htmode}"
		elif [ "$FIX_WIFI" = 1 ]; then
			uci -q set "wireless.${radio}.htmode=${want_htmode}"
			if uci -q commit wireless >/dev/null 2>&1; then
				fixed "${radio} 模式改回 ${want_htmode}（需 wifi reload 才生效）"
			else
				fail "${radio} 模式改回 ${want_htmode} 失败"
			fi
		else
			warn "${radio} 模式是 ${htmode:-默认}，应为 ${want_htmode}（要改加 --fix-wifi）"
		fi
	done

	if command -v iwinfo >/dev/null 2>&1; then
		# 首字符必须是非空格：iwinfo 的续行（`          Access Point: ...`）也以「一个
		# 单词加空格」开头，按 ^[^ ]* 取会把 Access、Mode: 当成网卡名去调用。
		for netdev in $(iwinfo 2>/dev/null | sed -n 's/^\([^ ][^ ]*\) .*/\1/p'); do
			# iwinfo 把信道写在 Mode 行的中间（`Mode: Master  Channel: 36 (5.180 GHz)`），
			# 不是行首，按 `^Channel:` 锚定的正则永远匹配不到。
			line="$(iwinfo "$netdev" info 2>/dev/null | sed -n 's/.*Channel: \([0-9][0-9]*\).*/\1/p' | head -n 1)"
			[ -n "$line" ] && info "运行态 ${netdev} 信道 ${line}"
		done
		clients="$(iwinfo 2>/dev/null | grep -c 'ESSID:')"
		[ -n "$clients" ] && info "iwinfo 报告 ${clients} 个无线接口在广播"
	else
		skip '没有 iwinfo，跳过运行态无线检查'
	fi
}

# ---------------------------------------------------------------- 锐捷认证

group_ruijie() {
	section '锐捷认证'

	cfg="${ROOT}/etc/config/ruijie"
	if [ ! -f "$cfg" ]; then
		fail '没有 /etc/config/ruijie（锐捷认证没有安装或配置被重置）'
		return
	fi
	mode="$(file_mode "$cfg")"
	case "$mode" in
		600) ok '/etc/config/ruijie 权限 0600' ;;
		'') warn '读不到 /etc/config/ruijie 的权限' ;;
		*) trouble "/etc/config/ruijie 权限是 ${mode}，凭据文件应为 0600" "chmod 600 ${cfg}" ;;
	esac
	for prog in ruijie-auth ruijie-password ruijie-refresh-query; do
		path="${ROOT}/usr/libexec/$prog"
		[ -f "$path" ] || { fail "缺少 /usr/libexec/${prog}"; continue; }
		pmode="$(file_mode "$path")"
		case "$pmode" in
			755) ok "${prog} 权限 0755" ;;
			'') ;;
			*) trouble "/usr/libexec/${prog} 权限是 ${pmode}，应为 0755" "chmod 755 ${path}" ;;
		esac
	done

	# 没配置不等于配置错了。三个空字段各报一条 WARN 会把真正的故障淹掉，所以
	# 合并成一条，并且下面跟密码、门户有关的判断都按「尚未配置」处理。
	unset_keys=''
	for key in username server query_string; do
		[ -n "$(uget "ruijie.main.${key}")" ] || unset_keys="${unset_keys} ${key}"
	done
	if [ -n "$unset_keys" ]; then
		info "锐捷认证还没配置（缺${unset_keys}），下面按「尚未配置」处理"
	else
		ok 'ruijie.main 的 username/server/query_string 都已配置'
	fi
	if [ "$(uget ruijie.main.auto_reconnect)" = 1 ]; then
		ok '断线自动重连已打开'
	else
		info '断线自动重连是关的（auto_reconnect≠1）'
	fi

	# 密码状态机：payload 是当前密码，prev 是上一次的，original 是第一次改密码前
	# 存下的锚点。payload 空而锚点/回退点还在，说明「值丢失」——回退点和锚点是这个
	# 状态机唯一还记得的凭据，补回去不会覆盖任何还能用的密码。
	payload="$(uget ruijie.main.password_payload)"
	prev="$(uget ruijie.main.password_prev)"
	if uci -q get ruijie.main.password_original >/dev/null 2>&1; then
		original="$(uget ruijie.main.password_original)"
		has_original=1
	else
		original=''
		has_original=0
	fi
	info "当前密码 $(mask "$payload")｜回退点 $(mask "$prev")｜锚点 $(mask "$original")"
	# 找回顺序：先用回退点（它是最近一次被成功用过、又被换下来的值），没有回退点
	# 才用最初的锚点。两个值都留在各自的选项里，选错了可以再换回去。
	# $(uci -q get ...) 要在 eval 时才展开，所以这两条修复命令保持单引号。
	# shellcheck disable=SC2016
	restore_from_prev='uci -q set ruijie.main.password_payload="$(uci -q get ruijie.main.password_prev)" && uci -q commit ruijie'
	# shellcheck disable=SC2016
	restore_from_original='uci -q set ruijie.main.password_payload="$(uci -q get ruijie.main.password_original)" && uci -q commit ruijie'
	if [ -z "$payload" ] && [ -n "$prev" ]; then
		trouble 'password_payload 是空的，但回退点还在（设置被写丢了，用回退点补回）' "$restore_from_prev"
	elif [ -z "$payload" ] && [ "$has_original" = 1 ] && [ -n "$original" ]; then
		trouble 'password_payload 是空的，但最初的密码锚点还在（设置被写丢了，用锚点补回）' "$restore_from_original"
	elif [ -z "$payload" ] && [ -n "$unset_keys" ]; then
		info '还没有锐捷密码（服务尚未配置，属正常）'
	elif [ -z "$payload" ]; then
		warn '还没有可用的锐捷密码（payload 与回退点都是空的）'
	elif [ -n "$prev" ]; then
		ok '当前密码可用，且有一个回退点'
	else
		ok '当前密码可用（没有回退点）'
	fi

	state="${ROOT}/tmp/ruijie-auth.state"
	if [ -f "$state" ]; then
		info "最近状态: $(tr '\n' ' ' < "$state")"
	else
		info '没有 /tmp/ruijie-auth.state（服务还没写过结果）'
	fi
	last="${ROOT}/tmp/ruijie-auth.last"
	if [ -f "$last" ]; then
		# 这是「上一次请求」的结论，不是当前密码的判定：没送到门户的尝试也会写进来。
		info "最近一次请求: $(tr '\n' ' ' < "$last" | cut -c1-160)"
	fi

	# 门户探测：只读，最多等十几秒。探测结果与状态文件不一致时，说明页面上的状态
	# 是旧的，不是网络真的掉了。
	if [ -x "${ROOT}/usr/libexec/ruijie-auth" ]; then
		probe="$( "${ROOT}/usr/libexec/ruijie-auth" status 2>/dev/null )"
		state_value="$(sed -n 's/^auth_state=//p' "$state" 2>/dev/null)"
		case "$probe" in
			online)
				if [ "$state_value" = online ] || [ -z "$state_value" ]; then
					ok '门户探测: 已联网'
				else
					warn "门户探测: 已联网，但状态文件写的是 ${state_value}（页面状态是旧的，链路本身可用）"
				fi
				;;
			offline)
				if [ "$FIX_AUTH" = 1 ] && [ "$(uget ruijie.main.enabled)" = 1 ]; then
					info '探测不可达，按 --fix-auth 执行一次重新认证'
					if "${ROOT}/usr/libexec/ruijie-auth" reauth >/dev/null 2>&1; then
						fixed '已执行一次重新认证'
					else
						warn '重新认证没有成功（门户拒绝或网络不通，见 /tmp/ruijie-auth.last）'
					fi
				else
					warn '门户探测: 不可达（校园网可能没接或已下线；要自动重认证加 --fix-auth）'
				fi
				;;
			*) info "门户探测没有明确结论: ${probe:-无输出}" ;;
		esac
	fi
}

# ---------------------------------------------------------------- 软件包与 USB

group_packages() {
	section '软件包与 USB'

	if ! command -v opkg >/dev/null 2>&1; then
		skip '没有 opkg，跳过软件包检查（apk 的镜像改到这里）'
		return
	fi
	load_pkgs
	if [ -z "$PKG_CACHE" ]; then
		skip 'opkg list-installed 没有输出，跳过软件包检查'
		return
	fi
	core='ua3f luci-app-turboacc smartdns luci-app-smartdns luci-theme-argon luci-app-commands
watchcat luci-app-watchcat ddns-scripts luci-app-ddns p910nd luci-app-p910nd
kmod-usb-printer kmod-usb-net-cdc-mbim kmod-usb-net-rndis kmod-usb-net-cdc-ncm umbim
luci-proto-mbim kmod-tcp-bbr zram-swap irqbalance curl jsonfilter luci-compat
ruijie-auth luci-i18n-base-zh-cn kmod-nft-queue kmod-nft-tproxy'
	missing=''
	for pkg in $core; do
		pkg_installed "$pkg" || missing="${missing} ${pkg}"
	done
	if [ -z "$missing" ]; then
		ok '核心软件包齐全'
	else
		fail "缺少核心软件包:${missing}"
	fi
	warn_missing=''
	for pkg in kmod-usb-core kmod-usb2 kmod-usb3 kmod-usb-net kmod-sched ip-full tcpdump-mini ca-bundle usbutils; do
		pkg_installed "$pkg" || warn_missing="${warn_missing} ${pkg}"
	done
	if [ -z "$warn_missing" ]; then
		ok '辅助软件包齐全'
	else
		warn "缺少辅助软件包（不影响主线功能）:${warn_missing}"
	fi
	if [ -f "${ROOT}/etc/config/mwan3" ]; then
		missing=''
		for pkg in mwan3 luci-app-mwan3 iptables-zz-legacy ip6tables-zz-legacy; do
			pkg_installed "$pkg" || missing="${missing} ${pkg}"
		done
		if [ -z "$missing" ]; then
			ok '双 WAN 变体的 mwan3/legacy 前端齐全'
		else
			fail "双 WAN 变体缺少:${missing}"
		fi
	fi

	if command -v lsusb >/dev/null 2>&1; then
		devices="$(lsusb 2>/dev/null | wc -l | tr -d '[:space:]')"
		info "USB 上枚举到 ${devices} 个设备"
	else
		skip '没有 lsusb'
	fi
	usbwan="$(uget acrh17.settings.usbwan_interface)"
	[ -n "$usbwan" ] || usbwan=usbwan
	if uci -q show "network.${usbwan}" >/dev/null 2>&1; then
		info "USB WAN 逻辑接口 ${usbwan} 已在 network 配置里"
	else
		info "USB WAN 逻辑接口 ${usbwan} 还没建立（插上 F50/手机后在 LuCI 里加）"
	fi
	for helper in acrh17-usbwan-redial acrh17-usb-net-status; do
		if [ -x "${ROOT}/usr/libexec/$helper" ]; then
			ok "维护脚本 ${helper} 可执行"
		else
			fail "缺少可执行的 /usr/libexec/${helper}"
		fi
	done

	cmds="$(uci show luci 2>/dev/null | grep -c '^luci\.@command\[')"
	if [ "$cmds" -ge 7 ]; then
		ok "自定义命令 ${cmds} 条"
	else
		# 90-acrh17 只在全新安装时写这些命令；保留配置升级后它们可能不存在。
		warn "自定义命令只有 ${cmds} 条（全新安装是 7 条；升级保留的配置不会补）"
	fi
	media="$(uget luci.main.mediaurlbase)"
	[ -n "$media" ] && info "LuCI 主题 ${media}"
}

# ---------------------------------------------------------------- 日志

group_logs() {
	section '最近日志'
	if ! command -v logread >/dev/null 2>&1; then
		skip '没有 logread'
		return
	fi
	logs="$(logread 2>/dev/null | tail -n 200)"
	for tag in ruijie-auth ruijie-password turboacc; do
		lines="$(printf '%s' "$logs" | grep "$tag" | tail -n 3)"
		if [ -n "$lines" ]; then
			printf '%s\n' "$lines" | while IFS= read -r line; do info "${line}"; done
		else
			info "日志里没有 ${tag} 的记录"
		fi
	done
	ua3f_log="${ROOT}/var/log/ua3f/ua3f.log"
	if [ -f "$ua3f_log" ]; then
		# 被校园网屏蔽的 Google/Facebook 连接超时属预期，不是故障。
		blocked="$(grep -c 'SO_MARK' "$ua3f_log" 2>/dev/null)"
		info "ua3f.log 里 SO_MARK 超时 ${blocked} 条（校园网屏蔽的目标，属预期）"
	fi
}

# ---------------------------------------------------------------- 主流程

printf '========== ACRH17 刷机后检测（%s）==========\n' "$MODE"
printf '时间 %s' "$(date '+%Y-%m-%d %H:%M:%S')"
[ -n "$EXPECT_STAMP" ] && printf '｜期望固件戳 %s' "$EXPECT_STAMP"
printf '\n'
[ "$FIX_WIFI" = 1 ] && printf '（本次会重设无线信道）\n'
[ "$FIX_AUTH" = 1 ] && printf '（本次会在探测不可达时重新认证）\n'

group_platform
group_upgrade
group_services
group_network
group_ua3f
group_wireless
group_ruijie
group_packages
group_logs

printf '\n========== 汇总 ==========\n'
printf '通过 %s｜警告 %s｜失败 %s｜已修复 %s\n' "$CNT_OK" "$CNT_WARN" "$CNT_FAIL" "$CNT_FIXED"
if [ -n "$CHANGES" ]; then
	printf '本次改动:\n%s' "$CHANGES"
fi
if [ "$CNT_FAIL" -gt 0 ]; then
	if [ "$MODE" = check ]; then
		printf '还有 %s 项失败；加 fix 参数重跑可以自动处理其中标了修复命令的部分。\n' "$CNT_FAIL"
	else
		printf 'fix 之后仍有 %s 项失败，需要人工处理。\n' "$CNT_FAIL"
	fi
	exit 1
fi
[ "$CNT_WARN" -gt 0 ] && printf '没有失败项，%s 个警告见上文。\n' "$CNT_WARN" ||
	printf '全部通过。\n'
exit 0
