#!/bin/sh
# acrh17-campus-up.sh -- 刷机后把校园网认证恢复起来（RT-ACRH17 / 本项目镜像）
#
# 刷机重建 rootfs_data，锐捷认证的配置回到出厂默认：没有门户地址、没有学号、
# 没有密码，服务是关的。WAN 照样能从校园网领到 IPv4，但那只是一个校园内网地址，
# 没通过 ePortal 认证就出不了网——「路由器连不上网」就是这个样子。
#
# 这台机器能自己想出来的只有门户地址：未认证时校园网把 HTTP 302 到登录页，那个
# Location 里同时带着门户 origin 和本次链路的 query_string。两者都绑定收到它的
# 地址与 MAC，换台机器抄过来没用、链路一变就失效，所以只能在路由器上现场抓。
# 固件里的 ruijie-refresh-query 已经会从同一个 302 抓 query_string，但没有人把
# origin 存下来，这里补上这一段。
#
# 学号和密码只能由人给，脚本不猜、不打印、也不写进日志。密码请用
# /usr/libexec/ruijie-password set <密码>：它会拿密码做一次真实登录，被门户
# 拒绝时自动回退，而这要求 server 与 username 已经在配置里——所以顺序是
# 先跑本脚本的 fix，再 set 密码，最后再跑一次 fix 把服务打开。
#
# 全程不需要外网：只用到设备上已装的 curl、ubus、jsonfilter、uci。
#
# 用法:
#   ./scripts/acrh17-campus-up.sh --host root@192.168.5.1 --ssh-key ~/.ssh/id_acrh17 \
#       --user 2021xxxx
#   ssh root@192.168.5.1 'sh -s' < scripts/acrh17-campus-up.sh
#
#   check                只读检测（默认）
#   fix                  写入门户地址、query_string 与学号，凭据齐全时打开服务并登录
#   --user 学号          写入 ruijie.main.username（刷机后配置被重置时需要）
#   --server URL         门户地址重定向里推不出来时手工指定，例如 http://172.16.0.1
#   --host [user@]地址   从开发机远程执行；把本脚本经 ssh 送上去运行
#   --ssh-key 路径       远程模式的私钥。ssh 只自动尝试 id_rsa/id_ecdsa/id_ed25519
#                        这几个默认名字，这台路由器的钥匙不在其中，不指定就没法登录
#   -h, --help           显示本帮助
#
# fix 永远不碰密码。缺密码时它会说清楚还差什么，补齐后再跑一次即可。

MODE="${ACRH17_CAMPUS_MODE:-check}"
ROOT="${ACRH17_CAMPUS_ROOT:-}"
HOST=''
SSH_KEY="${ACRH17_SSH_KEY:-}"
USER_ARG="${ACRH17_CAMPUS_USER:-}"
SERVER_ARG="${ACRH17_CAMPUS_SERVER:-}"
# 换行分隔的候选密码。只有配置里还没有密码时才会用到它们。
PW_LIST="${ACRH17_CAMPUS_PASSWORDS:-}"
CFG='ruijie.main'

usage() {
	cat <<'EOF'
用法: acrh17-campus-up.sh [check|fix] [选项]

  check                只读检测（默认）
  fix                  写入门户地址、query_string 与学号，凭据齐全时打开服务并登录
  --user 学号          写入 ruijie.main.username
  --password 密码      可重复。配置里还没有密码时，按给出的顺序逐个交给
                       ruijie-password set 做真实登录验证，第一个被门户接受的留下，
                       被拒绝的自动回退。已经在用的密码不会被重设（那是白白断线）。
  --server URL         手工指定门户地址（重定向里推不出来时用）
  --host [user@]地址   从开发机远程执行
  --ssh-key 路径       远程模式用的私钥；ssh 只会自动尝试 id_rsa/id_ecdsa/id_ed25519
                       这几个默认名字，给这台路由器起的名字不在其中，不指定就是
                       Permission denied (publickey)
  -h, --help           显示本帮助

不给出 --password 时密码不会被本脚本碰，请自己跑 ruijie-password set。
EOF
}

while [ $# -gt 0 ]; do
	arg="$1"
	shift
	case "$arg" in
		check|fix) MODE="$arg" ;;
		--user) USER_ARG="${1:-}"; [ $# -gt 0 ] && shift ;;
		--user=*) USER_ARG="${arg#--user=}" ;;
		# 多次给出就按顺序排队；换行分隔，密码里的空格与 $ 都不会被再展开一次。
		--password) PW_LIST="${PW_LIST}${1:-}
"; [ $# -gt 0 ] && shift ;;
		--password=*) PW_LIST="${PW_LIST}${arg#--password=}
" ;;
		--server) SERVER_ARG="${1:-}"; [ $# -gt 0 ] && shift ;;
		--server=*) SERVER_ARG="${arg#--server=}" ;;
		--host) HOST="${1:-}"; [ $# -gt 0 ] && shift ;;
		--host=*) HOST="${arg#--host=}" ;;
		--ssh-key) SSH_KEY="${1:-}"; [ $# -gt 0 ] && shift ;;
		--ssh-key=*) SSH_KEY="${arg#--ssh-key=}" ;;
		-h|--help) usage; exit 0 ;;
		*) usage >&2; exit 2 ;;
	esac
done

# 这几个值要原样嵌进 ssh 的远程命令串，单引号会破坏引号配对。
case "${USER_ARG}${SERVER_ARG}${PW_LIST}" in
	*"'"*) echo '参数里不能有单引号。' >&2; exit 2;;
esac

if [ -n "$HOST" ]; then
	if [ ! -f "$0" ]; then
		echo '远程模式需要以脚本文件方式运行，例如 ./scripts/acrh17-campus-up.sh --host root@192.168.5.1' >&2
		exit 2
	fi
	# IdentitiesOnly 是跟着 -i 一起来的：不限制的话 agent 会把它持有的每一把钥匙
	# 都递一遍，在路由器那种 MaxAuthTries 很小的地方还没轮到指定这把就断开了。
	set --
	[ -z "$SSH_KEY" ] || set -- -i "$SSH_KEY" -o IdentitiesOnly=yes
	exec ssh -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new "$@" "$HOST" \
		"ACRH17_CAMPUS_MODE=${MODE} ACRH17_CAMPUS_USER='${USER_ARG}' ACRH17_CAMPUS_SERVER='${SERVER_ARG}' ACRH17_CAMPUS_PASSWORDS='${PW_LIST}' sh -s" < "$0"
fi

if [ ! -f "${ROOT}/etc/openwrt_release" ]; then
	echo "这里不是 OpenWrt 设备（缺少 ${ROOT}/etc/openwrt_release）。" >&2
	echo '要在路由器上跑请加 --host root@192.168.5.1，或把本脚本送上去执行。' >&2
	exit 2
fi

CNT_OK=0
CNT_WARN=0
CNT_FAIL=0
CNT_FIXED=0

section() { printf '\n--- %s ---\n' "$1"; }
ok() { CNT_OK=$((CNT_OK + 1)); printf '[ OK ] %s\n' "$1"; }
info() { printf '[INFO] %s\n' "$1"; }
warn() { CNT_WARN=$((CNT_WARN + 1)); printf '[WARN] %s\n' "$1"; }
fail() { CNT_FAIL=$((CNT_FAIL + 1)); printf '[FAIL] %s\n' "$1"; }
fixed() { CNT_FIXED=$((CNT_FIXED + 1)); printf '[FIX ] %s\n' "$1"; }

get() { uci -q get "$CFG.$1" 2>/dev/null; }
auth() { "${ROOT}/usr/libexec/ruijie-auth" "$@"; }

# 与 ruijie-password 同一套掩码：非 ASCII 只报字节数，纯 ASCII 报位数与末两位。
# 这里的值来自 UCI，永不回显明文。
mask() {
	[ -n "$1" ] || { printf '(未设置)'; return; }
	if [ -n "$(printf '%s' "$1" | LC_ALL=C tr -d '\000-\177')" ]; then
		printf '含非 ASCII 字符（%s 字节）' "$(printf '%s' "$1" | wc -c | tr -d '[:space:]')"
		return
	fi
	printf '%s 位，末两位 %s' "${#1}" "$(printf '%s' "$1" | tail -c 2)"
}

# query string 的字段：key=value&key=value...
field() { printf '%s' "$1" | tr '&' '\n' | sed -n "s/^$2=//p" | head -1; }

# 门户页判据与 ruijie-refresh-query 一致：校园网对 80 端口的拦截一定落到 index.jsp。
# 别的重定向（透明代理、上级网关）不是门户，拿它的 origin 当 server 会把认证发到
# 一台不认识这台机器的服务器上。
is_portal_page() {
	case "$1" in
		*index.jsp*) return 0 ;;
		*) return 1 ;;
	esac
}

# http://host[:port]/eportal/index.jsp?... -> http://host[:port]
# 门户地址就是重定向的 origin；路径与查询串分别由 login_path 和 query_string 承担。
origin_of() {
	case "$1" in
		http://*|https://*) ;;
		*) return 1 ;;
	esac
	rest="${1#*://}"
	host="${rest%%/*}"
	[ -n "$host" ] || return 1
	printf '%s://%s' "${1%%://*}" "$host"
}

# index.jsp 之后的部分才是门户要的 query string。
query_of() {
	case "$1" in
		*index.jsp\?*) printf '%s' "${1#*index.jsp?}" ;;
		*) return 1 ;;
	esac
}

wan_ready() {
	wan="$(get wan_interface)"
	case "$wan" in ''|*[!A-Za-z0-9_-]*) wan=wan;; esac
	status_json="$(ubus call "network.interface.$wan" status 2>/dev/null)" || return 1
	up="$(printf '%s' "$status_json" | jsonfilter -e '@.up' 2>/dev/null)"
	case "$up" in 1|true) ;; *) return 1;; esac
	ipv4="$(printf '%s' "$status_json" | jsonfilter -e '@["ipv4-address"][0].address' 2>/dev/null)"
	case "$ipv4" in ''|0.0.0.0) return 1;; esac
	l3dev="$(printf '%s' "$status_json" | jsonfilter -e '@.l3_device' 2>/dev/null)"
	return 0
}

# 探针必须从认证将要走的那个设备出去：门户把 query_string 绑在收到请求的地址上，
# 多 WAN 的机器走默认路由会抓回一条属于另一条链路的串，覆盖掉还能用的那条。
# 用 IP 字面量是为了让坏掉的解析器藏不住重定向；故意不带 -L，302 本身就是答案。
# 参数与超时跟 ruijie-refresh-query 的 probe() 保持一致。
probe_location() {
	set -- "$1"
	[ -z "$DEV" ] || set -- --interface "$DEV" "$@"
	curl -q -4 -sS --noproxy '*' --proto '=http' --connect-timeout 5 --max-time 12 \
		-o /dev/null -D - "$@" 2>/dev/null | tr -d '\r' | sed -n 's/^[Ll]ocation: *//p' | head -n 1
}

printf '========== ACRH17 校园网上线（%s）==========\n' "$MODE"
printf '时间 %s\n' "$(date '+%Y-%m-%d %H:%M:%S')"

# ------------------------------------------------------------ 链路
section '链路'
if wan_ready; then
	ok "WAN ${wan} 有 IPv4 ${ipv4}（设备 ${l3dev}）"
else
	fail 'WAN 没有 IPv4：校园网线没接或 DHCP 没拿到地址，认证无从谈起'
	printf '\n========== 汇总 ==========\n'
	printf '通过 %s｜警告 %s｜失败 %s｜已修复 %s\n' "$CNT_OK" "$CNT_WARN" "$CNT_FAIL" "$CNT_FIXED"
	exit 1
fi

# 认证还没过时，门户会把 HTTP 拦下来换成登录页；已经在线就什么都拦不到。
# 设备选择与 ruijie-auth 的 request() 相同：显式覆盖优先，否则用逻辑 WAN 的 l3_device。
DEV="$(get interface)"
[ -n "$DEV" ] || DEV="$l3dev"
case "$DEV" in ''|*[!A-Za-z0-9_.:-]*) DEV='';; esac

LOCATION=''
if [ -n "$SERVER_ARG" ]; then
	info '门户地址用 --server 指定，跳过重定向探测'
else
	for url in http://1.1.1.1/ http://connect.rom.miui.com/generate_204 http://223.5.5.5/; do
		LOCATION="$(probe_location "$url")"
		[ -n "$LOCATION" ] && break
	done
fi

ALREADY_ONLINE=0
auth status >/dev/null 2>&1 && ALREADY_ONLINE=1

if [ -n "$LOCATION" ] && is_portal_page "$LOCATION"; then
	ok "门户重定向: ${LOCATION}"
elif [ -n "$LOCATION" ]; then
	warn "看到了重定向，但不是门户登录页，忽略：${LOCATION}"
elif [ "$ALREADY_ONLINE" = 1 ]; then
	ok '校园链路已经在线，没有重定向可抓'
else
	warn '没看到门户重定向（可能校园网不劫持 HTTP，或这条链路没接校园网）'
fi

# ------------------------------------------------------------ 门户地址
section '门户地址'
CUR_SERVER="$(get server)"
NEW_SERVER=''
if [ -n "$SERVER_ARG" ]; then
	NEW_SERVER="$SERVER_ARG"
elif [ -n "$LOCATION" ] && is_portal_page "$LOCATION"; then
	NEW_SERVER="$(origin_of "$LOCATION")" || NEW_SERVER=''
fi

if [ -z "$NEW_SERVER" ]; then
	if [ -n "$CUR_SERVER" ]; then
		info "配置里已有门户地址 ${CUR_SERVER}，探测没给出新的"
	else
		fail '推不出门户地址：用 --server http://<门户IP> 手工指定'
	fi
elif [ "$NEW_SERVER" = "$CUR_SERVER" ]; then
	ok "门户地址 ${NEW_SERVER}"
elif [ "$MODE" = fix ]; then
	if uci set "$CFG.server=$NEW_SERVER" && uci commit ruijie; then
		fixed "写入门户地址 ${NEW_SERVER}（原有：${CUR_SERVER:-空}）"
	else
		fail '写入门户地址失败'
	fi
else
	warn "门户地址应为 ${NEW_SERVER}，配置里${CUR_SERVER:+是 ${CUR_SERVER}}${CUR_SERVER:-没有}（修复加 fix）"
fi

# ------------------------------------------------------------ query_string
section 'query_string'
CUR_QUERY="$(get query_string)"
NEW_QUERY=''
if [ -n "$LOCATION" ] && is_portal_page "$LOCATION"; then
	NEW_QUERY="$(query_of "$LOCATION")" || NEW_QUERY=''
fi

if [ -n "$NEW_QUERY" ]; then
	# 真串一定带客户端地址与 MAC（两者都加密）。注意不能用 case 模式表达这个
	# 判断：`?` 是通配符、`|` 是分支，`*wlanuserip=?*|*mac=?*` 会变成只要有一个。
	if [ -z "$(field "$NEW_QUERY" wlanuserip)" ] || [ -z "$(field "$NEW_QUERY" mac)" ]; then
		fail '抓到的 query 缺 wlanuserip 或 mac，不写入'
		NEW_QUERY=''
	fi
fi

if [ -n "$NEW_QUERY" ]; then
	if [ "$NEW_QUERY" = "$CUR_QUERY" ]; then
		ok '抓到的 query 与配置里的一致'
	elif [ "$MODE" = fix ]; then
		if uci set "$CFG.query_string=$NEW_QUERY" && uci commit ruijie; then
			fixed "写入 query_string（${#NEW_QUERY} 字节，含 wlanuserip 与 mac）"
		else
			fail '写入 query_string 失败'
		fi
	else
		warn "抓到了新的 query_string（配置里${CUR_QUERY:+是旧的}${CUR_QUERY:-是空的}，修复加 fix）"
	fi
elif [ -n "$CUR_QUERY" ]; then
	if [ -n "$(field "$CUR_QUERY" wlanuserip)" ] && [ -n "$(field "$CUR_QUERY" mac)" ]; then
		info '沿用配置里已有的 query_string'
	else
		fail '配置里的 query_string 缺 wlanuserip 或 mac，且这次没抓到新的'
	fi
else
	fail '没有可用的 query_string：链路必须先处于「有 IPv4、未认证」才能抓到'
fi

# ------------------------------------------------------------ 凭据
section '凭据'
USERNAME="$(get username)"
# --user 是给刚刷完机、配置被重置回默认值的情况用的。学号不是秘密，密码是。
if [ -n "$USER_ARG" ] && [ "$USER_ARG" != "$USERNAME" ]; then
	if [ "$MODE" = fix ]; then
		if uci set "$CFG.username=$USER_ARG" && uci commit ruijie; then
			fixed "写入学号 ${USER_ARG}（原有：${USERNAME:-空}）"
			USERNAME="$USER_ARG"
		else
			fail '写入学号失败'
		fi
	else
		warn "学号应是 ${USER_ARG}，配置里是 ${USERNAME:-空}（修复加 fix）"
	fi
fi

CREDS=1

if [ -n "$USERNAME" ]; then
	ok "学号 userId 已配置（${USERNAME}）"
else
	fail 'ruijie.main.username 是空的：用 --user <学号> 或到 LuCI「服务 → Ruijie ePortal」填'
	CREDS=0
fi

PASSWORD="$(get password_payload)"

# 候选密码走 ruijie-password set，而不是直接写 UCI：它自己会拿这个密码做一次
# 真实登录，被门户拒绝就把上一个值放回去。猜错一个候选不会留下一个坏密码，
# 也不会让「密码对不对」变成没人验证过的假设。已经在用的密码不动——重设一次
# 等于白白断一次线，而那个密码本来就没被投诉过。
if [ -n "$PW_LIST" ] && [ -z "$PASSWORD" ] && [ "$MODE" = fix ]; then
	index=0
	while IFS= read -r pw; do
		[ -n "$pw" ] || continue
		index=$((index + 1))
		PW_OUT="${ROOT}/tmp/ruijie-pw.$$"
		PW_RC=0
		"${ROOT}/usr/libexec/ruijie-password" set "$pw" > "$PW_OUT" 2>&1 || PW_RC=$?
		# 该命令的输出只含掩码，但明文没必要在任何地方多留一份。
		rm -f "$PW_OUT"
		case "$PW_RC" in
		0)
			fixed "第 ${index} 个候选密码通过门户验证"
			PASSWORD="$(get password_payload)"
			break ;;
		1)
			warn "第 ${index} 个候选密码被门户拒绝，已自动回退" ;;
		75)
			warn '另一个认证动作正持锁，候选密码没能验证'; break ;;
		*)
			warn "第 ${index} 个候选密码已写入但没能验证（请求没送达门户，或答复读不懂）"
			break ;;
		esac
	done <<EOF
$PW_LIST
EOF
	PASSWORD="$(get password_payload)"
fi

if [ -n "$PASSWORD" ]; then
	ok "密码已配置（$(mask "$PASSWORD")）"
else
	fail '还没有校园网密码：用 --password 给一个，或自己跑 /usr/libexec/ruijie-password set <密码>'
	CREDS=0
fi

# 这里只拦「写了但不是 URL」的情况：空的门户地址上面那节已经报过，再 FAIL 一次
# 是把同一个事实说两遍。两种都要挡住开服务。
SERVER_NOW="$(get server)"
case "$SERVER_NOW" in
	'') CREDS=0 ;;
	http://?*|https://?*) ;;
	*) fail "门户地址不是 http(s) URL：${SERVER_NOW}"; CREDS=0 ;;
esac

# ------------------------------------------------------------ 认证服务
section '认证服务'
if [ "$(get enabled)" = 1 ]; then
	ok 'ruijie.main.enabled=1'
elif [ "$MODE" = fix ] && [ "$CREDS" = 1 ]; then
	if uci set "$CFG.enabled=1" && uci commit ruijie; then
		fixed '打开 ruijie.main.enabled'
	else
		fail '打开 ruijie.main.enabled 失败'
	fi
elif [ "$MODE" = fix ]; then
	info '凭据没配齐，先不开服务（一个登录不成的守护进程只会反复打扰门户）'
else
	fail '认证服务是关的（ruijie.main.enabled≠1）'
fi

if [ ! -x "${ROOT}/etc/init.d/ruijie-auth" ]; then
	fail '缺少 /etc/init.d/ruijie-auth'
elif [ -e "${ROOT}/etc/rc.d/S95ruijie-auth" ]; then
	ok '开机自启已启用'
elif [ "$MODE" = fix ]; then
	if "${ROOT}/etc/init.d/ruijie-auth" enable >/dev/null 2>&1; then
		fixed '设置 ruijie-auth 开机自启'
	else
		fail '设置开机自启失败'
	fi
else
	warn 'ruijie-auth 不会开机自启（修复加 fix）'
fi

# ------------------------------------------------------------ 上线
section '上线'
if [ "$MODE" = check ]; then
	if [ "$ALREADY_ONLINE" = 1 ]; then
		ok '校园链路已在线，无需登录'
	else
		info 'check 不发起登录；凭据齐全时用 fix 登录并验证'
	fi
elif [ "$CREDS" != 1 ]; then
	warn '凭据还差东西，这一步跳过。补齐后重跑 fix 即可'
else
	# 守护进程自己也会登录（boot_login=1），但那条路把结果留在 /tmp 里；先同步
	# 登录一次，好拿到一句能直接给用户看的失败原因。此处的顺序是先登录后起
	# 服务：守护进程只在真正发请求时才拿认证锁，先起服务会和这次登录抢锁。
	LOGIN_RC=0
	auth login >/dev/null 2>&1 || LOGIN_RC=$?
	if [ "$LOGIN_RC" -eq 0 ]; then
		fixed '门户接受了登录'
	elif [ "$LOGIN_RC" -eq 75 ]; then
		info '另一个认证动作正持锁，跳过主动登录，直接看结果'
	else
		LAST="${ROOT}/tmp/ruijie-auth.last"
		if [ -f "$LAST" ]; then
			warn "登录未成功：$(tr '\n' ' ' < "$LAST" | cut -c1-160)"
		else
			warn '登录未成功，且 /tmp/ruijie-auth.last 没留下原因'
		fi
	fi
	# 起守护进程接管保活；登录失败也起，让它按自己的退避重试（auto_refresh_query
	# 会重抓 query_string，那正是链路变化后需要的那一步）。
	"${ROOT}/etc/init.d/ruijie-auth" restart >/dev/null 2>&1 || true
	# 门户放行到真正能出网之间还隔着一次收敛，给它一点时间再判定。
	ONLINE=0
	attempt=0
	while [ "$attempt" -lt 6 ]; do
		if auth status >/dev/null 2>&1; then
			ONLINE=1
			break
		fi
		sleep 5
		attempt=$((attempt + 1))
	done
	if [ "$ONLINE" = 1 ]; then
		ok '连通性探测通过：路由器能出网了'
	else
		fail '连通性探测仍失败，见 /tmp/ruijie-auth.state 与 /tmp/ruijie-auth.last'
	fi
fi

printf '\n========== 汇总 ==========\n'
printf '通过 %s｜警告 %s｜失败 %s｜已修复 %s\n' "$CNT_OK" "$CNT_WARN" "$CNT_FAIL" "$CNT_FIXED"

if [ "$CREDS" != 1 ] && [ "$MODE" = fix ]; then
	cat <<EOF

还差凭据。一次跑完：
  acrh17-campus-up.sh fix --user <学号> --password <密码>
候选密码按给出的顺序逐个验证，被门户拒绝的自动回退，第一个通过验证的留下。

也可以分三步手动来：
  1. 本脚本的 fix（已把 server / query_string / 学号 配好）
  2. /usr/libexec/ruijie-password set '<密码>'   真实登录验证，被拒自动回退
  3. 再跑一次本脚本的 fix                         打开认证服务并登录
不管走哪条路，server 与 username 都得先就位：ruijie-password 是靠一次真实登录
验证密码的，请求发不出去时它只把密码写进配置，没有任何东西验证过它。
EOF
fi

if [ "$CNT_FAIL" -gt 0 ]; then
	echo '有失败项，见上文。'
	exit 1
fi
if [ "$CNT_WARN" -gt 0 ]; then
	printf '没有失败项，%s 个警告见上文。\n' "$CNT_WARN"
	exit 0
fi
echo '全部通过。'
exit 0
