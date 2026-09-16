"""Run the on-device doctor (scripts/acrh17-doctor.sh) against a fixture router.

The doctor runs on the router, so the fixture supplies both halves of its
environment: a fake root tree (ACRH17_DOCTOR_ROOT) for every file it looks at,
and a fake PATH for every command it runs. The two modes are held to different
promises: check must leave the tree byte-identical, fix must repair the faults
the fixture carries and leave a second check clean.
"""
import hashlib
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCTOR = ROOT / 'scripts/acrh17-doctor.sh'

OPENWRT_RELEASE = """DISTRIB_ID='OpenWrt'
DISTRIB_RELEASE='24.10.0-20260914-2100'
DISTRIB_REVISION='r0-a1ea57b'
DISTRIB_TARGET='ipq40xx/generic'
DISTRIB_ARCH='arm_cortex-a7_neon-vfpv4'
DISTRIB_DESCRIPTION='OpenWrt 24.10.0-20260914-2100 r0-a1ea57b'
"""

UCI = {
    'acrh17.settings.defaults_applied': '1',
    'acrh17.settings.wifi_country': 'AU',
    'acrh17.settings.usbwan_interface': 'usbwan',
    'acrh17.settings.mwan3_interface': 'wan wanb wan2 usbwan',
    'acrh17.settings.mwan3_probe_ip': '223.5.5.5 119.29.29.29 114.114.114.114',
    'network.lan.ipaddr': '192.168.5.1',
    'network.lan.ip6assign': '0',
    'network.wan6.proto': 'none',
    'network.wan6.auto': '0',
    'firewall.@defaults[0].disable_ipv6': '1',
    'firewall.@defaults[0].flow_offloading': '0',
    'firewall.@defaults[0].flow_offloading_hw': '0',
    'dhcp.@dnsmasq[0].noresolv': '1',
    'dhcp.@dnsmasq[0].strictorder': '1',
    'dhcp.@dnsmasq[0].server': ('127.0.0.1#6053 223.5.5.5 119.29.29.29 '
                                '114.114.114.114 /scau.edu.cn/202.116.160.33'),
    'dhcp.@dnsmasq[0].rebind_domain': 'scau.edu.cn',
    'mwan3.globals.mmx_mask': '0x3f000000',
    'mwan3.wan6.enabled': '0',
    'mwan3.wanb6.enabled': '0',
    'mwan3.wan.family': 'ipv4',
    'mwan3.wan.track_ip': '223.5.5.5 119.29.29.29 114.114.114.114',
    'mwan3.wanb.family': 'ipv4',
    'mwan3.wanb.track_ip': '223.5.5.5 119.29.29.29 114.114.114.114',
    'turboacc.config.sw_flow': '0',
    'turboacc.config.hw_flow': '0',
    'turboacc.config.sfe_flow': '0',
    'turboacc.config.bbr_cca': '1',
    'ua3f.enabled.enabled': '1',
    'ua3f.main.l3_rewrite_ttl': '1',
    'ua3f.main.l3_rewrite_ttl_value': '64',
    'ua3f.main.l3_rewrite_tcpts': '1',
    'p910nd.@p910nd[0].enabled': '0',
    'smartdns.@smartdns[0].enabled': '1',
    'smartdns.@smartdns[0].port': '6053',
    # 真机上 SmartDNS 限的是入口设备（SO_BINDTODEVICE），监听地址仍然是通配的：
    # netstat 里看到 0.0.0.0:6053 不等于局域网能查。
    'smartdns.@smartdns[0].bind_device': '1',
    'smartdns.@smartdns[0].bind_device_name': 'lo',
    'ruijie.main.enabled': '1',
    'ruijie.main.username': '2021123456',
    'ruijie.main.server': 'http://172.16.0.1',
    'ruijie.main.query_string': 'wlanuserip=10.0.0.2&wlanacname=SCAU',
    'ruijie.main.password_payload': 'CURRENT-PW',
    'ruijie.main.password_prev': '',
    'ruijie.main.password_original': 'SHIPPED-PW',
    'ruijie.main.auto_reconnect': '1',
    'ruijie.main.wan_interface': 'wan',
    'wireless.radio0': 'wifi-device',
    'wireless.radio0.band': '2g',
    'wireless.radio0.channel': '6',
    'wireless.radio0.htmode': 'HT20',
    'wireless.radio0.disabled': '0',
    'wireless.radio0.country': 'AU',
    'wireless.radio1': 'wifi-device',
    'wireless.radio1.band': '5g',
    'wireless.radio1.channel': '36',
    'wireless.radio1.htmode': 'VHT80',
    'wireless.radio1.disabled': '0',
    'wireless.radio1.country': 'AU',
    'wireless.default_radio0': 'wifi-iface',
    'wireless.default_radio0.device': 'radio0',
    'wireless.default_radio0.ssid': 'ACRH17-2.4G',
    'wireless.default_radio0.key': 'campus-wifi-key',
    'wireless.default_radio1': 'wifi-iface',
    'wireless.default_radio1.device': 'radio1',
    'wireless.default_radio1.ssid': 'ACRH17-5G',
    'wireless.default_radio1.key': 'campus-wifi-key',
    'system.@system[0].hostname': 'DESKTOP-ACRH17',
    'system.@system[0].timezone': 'CST-8',
    'luci.main.mediaurlbase': '/luci-static/argon',
}
for _index, _name in enumerate(('重新认证锐捷', '刷新锐捷认证参数', '重启 UA3F',
                                '重拨 USB WAN', '重启打印服务', '查看 USB 设备',
                                '查看 USB 网络驱动状态')):
    UCI[f'luci.@command[{_index}].name'] = _name

ENABLED_SERVICES = ('watchcat', 'ddns', 'mwan3', 'smartdns', 'ua3f', 'irqbalance',
                    'turboacc', 'ruijie-auth', 'dnsmasq', 'zram', 'firewall')
# 健康夹具里「已启用」的服务：其余 init 脚本存在但没有 rc.d 链接。
RUNNING_LINKS = {'smartdns', 'ua3f', 'irqbalance', 'turboacc', 'ruijie-auth'}

PACKAGES = """ua3f - 2024.11
luci-app-turboacc - 1.0
smartdns - 1.2024
luci-app-smartdns - 1.0
luci-theme-argon - 2.3
luci-app-commands - 1.0
watchcat - 5
luci-app-watchcat - 5
ddns-scripts - 2.8
luci-app-ddns - 2.4
p910nd - 0.97
luci-app-p910nd - 1.0
kmod-usb-printer - 6.6.151
kmod-usb-net-cdc-mbim - 6.6.151
kmod-usb-net-rndis - 6.6.151
kmod-usb-net-cdc-ncm - 6.6.151
umbim - 2022.08.13
luci-proto-mbim - 1.0
kmod-tcp-bbr - 6.6.151
zram-swap - 34
irqbalance - 1.9
curl - 8.10
jsonfilter - 2024
luci-compat - 1.0
ruijie-auth - 1.1.0
luci-i18n-base-zh-cn - 1.0
kmod-nft-queue - 6.6.151
kmod-nft-tproxy - 6.6.151
kmod-usb-core - 6.6.151
kmod-usb2 - 6.6.151
kmod-usb3 - 6.6.151
kmod-usb-net - 6.6.151
kmod-sched - 6.6.151
ip-full - 6.6.151
tcpdump-mini - 4.99
ca-bundle - 2024
usbutils - 017
mwan3 - 2.11
luci-app-mwan3 - 2.11
iptables-zz-legacy - 1.8.10
ip6tables-zz-legacy - 1.8.10
"""

PROCESSES = """/usr/bin/ua3f /etc/ua3f/config.yaml
/usr/sbin/dnsmasq -C /var/etc/dnsmasq.conf
/usr/libexec/ruijie-auth daemon
"""

# 真机上 SmartDNS 的监听地址是通配的：bind_device 用 SO_BINDTODEVICE 限入口设备，
# 不体现在这个地址上。
NETSTAT = "tcp        0      0 0.0.0.0:6053            0.0.0.0:*               LISTEN\n"
IWINFO_LIST = ('wlan0     ESSID: "ACRH17-5G"\n'
               '          Mode: Master  Channel: 36 (5.180 GHz)\n'
               'wlan1     ESSID: "ACRH17-2.4G"\n'
               '          Mode: Master  Channel: 6 (2.437 GHz)\n')
IWINFO_INFO = ('wlanX     ESSID: "ACRH17-X"\n'
               '          Access Point: 00:11:22:33:44:55\n'
               '          Mode: Master  Channel: %s (2.437 GHz)\n'
               '          Center Channel 1: %s (2.437 GHz)\n')
DF = "Filesystem     1K-blocks    Used Available Use% Mounted on\n/dev/root          10240    2048      8192  20% /overlay\n"
NFT_RULES = "meta mark & 0xffff == 7894 tproxy to :7895\n"
LOGREAD = "Mon Sep 15 09:00:00 2026 user.info ruijie-auth: login rc=0\n"


class Fixture:
    """A fake router on disk: root tree plus mocked commands on PATH."""

    def __init__(self, base):
        self.base = Path(base)
        self.root = self.base / 'root'
        self.bin = self.base / 'bin'
        self.uci_state = self.base / 'uci.state'
        self.uci_log = self.base / 'uci.log'
        self.init_log = self.base / 'init.log'
        self.running = self.base / 'running'
        self.status_file = self.base / 'ruijie-status.txt'
        self.uci = dict(UCI)
        self.packages = PACKAGES
        self.processes = PROCESSES
        self.root.mkdir(parents=True)
        self.bin.mkdir()

    # ---- 构造

    def write(self, relative, text, mode=0o644, root=None):
        path = (root or self.root) / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
        path.chmod(mode)
        return path

    def build(self):
        self.write('etc/openwrt_release', OPENWRT_RELEASE)
        self.write('tmp/sysinfo/board_name', 'asus,rt-ac42u\n')
        self.write('tmp/sysinfo/model', 'ASUS RT-ACRH17\n')
        self.write('proc/uptime', '1234.56 4321.00\n')
        self.write('proc/loadavg', '0.01 0.02 0.03 1/100 1234\n')
        self.write('proc/meminfo', 'MemTotal:  262144 kB\nMemAvailable:  51234 kB\n')
        self.write('proc/swaps',
                   'Filename\t\t\t\tType\t\tSize\t\tUsed\t\tPriority\n'
                   '/dev/zram0                              partition\t65532\t\t0\t\t100\n')
        self.write('proc/sys/net/ipv4/tcp_congestion_control', 'bbr\n')
        self.write('proc/sys/net/core/default_qdisc', 'fq\n')
        self.write('proc/sys/net/ipv6/conf/all/disable_ipv6', '1\n')
        self.write('etc/shadow', 'root:$1$abcdefgh$0123456789abcdef:19000:0:99999:7:::\n', 0o600)
        self.write('etc/config/ruijie', 'config main \'main\'\n\toption enabled \'1\'\n', 0o600)
        self.write('etc/config/mwan3', 'config globals \'globals\'\n', 0o644)
        self.write('etc/sysctl.d/90-acrh17-bbr.conf', 'net.ipv4.tcp_congestion_control=bbr\n')
        self.write('etc/sysctl.d/91-acrh17-ipv6-off.conf',
                   'net.ipv6.conf.all.disable_ipv6=1\n')
        keep = (ROOT / 'files/lib/upgrade/keep.d/acrh17').read_text(encoding='utf-8')
        self.write('lib/upgrade/keep.d/acrh17', keep)
        self.write('opt/p910nd_drivers/foo.drv', 'blob\n')
        self.write('opt/p910nd_drivers/bar.drv', 'blob\n')
        self.write('tmp/ruijie-auth.state',
                   'auth_state=online\nlast_result=success\n'
                   'last_time=2026-09-15 09:00:00\nlast_summary=login: portal reported success\n')
        self.write('var/log/ua3f/ua3f.log', 'timeout\n')
        for service in ENABLED_SERVICES:
            self.write(f'etc/init.d/{service}', self.init_script(service), 0o755)
        (self.root / 'etc/rc.d').mkdir()
        for service in sorted(RUNNING_LINKS):
            (self.root / 'etc/rc.d' / f'S95{service}').symlink_to(
                self.root / 'etc/init.d' / service)
        for program in ('ruijie-auth', 'ruijie-password', 'ruijie-refresh-query',
                        'acrh17-usbwan-redial', 'acrh17-usb-net-status'):
            self.write(f'usr/libexec/{program}', self.program_script(program), 0o755)
        self.write('overlay/.keep', '')
        self.running.write_text('ua3f\nsmartdns\nirqbalance\nturboacc\nruijie-auth\n')
        self.status_file.write_text('online\n')
        self.save_uci()
        self.install_commands()

    def init_script(self, service):
        guard = ''
        if service == 'turboacc':
            # 镜像带着 patch-turboacc-runtime.py 的守卫时，初始化脚本里有这一行。
            guard = "logger -t turboacc 'Flow offload disabled while UA3F or mwan3 is enabled'\n"
        return ('#!/bin/sh\n'
                f'name={service}\n'
                f'{guard}'
                f'echo "$name $1" >> {self.init_log}\n'
                'case "$1" in\n'
                f'  running) grep -qx "$name" {self.running} 2>/dev/null && exit 0 || exit 1 ;;\n'
                f'  enable) ln -sf "$0" {self.root}/etc/rc.d/S95$name ;;\n'
                f'  disable) rm -f {self.root}/etc/rc.d/S95$name ;;\n'
                'esac\n'
                'exit 0\n')

    def program_script(self, name):
        if name != 'ruijie-auth':
            return '#!/bin/sh\nexit 0\n'
        return ('#!/bin/sh\n'
                'case "$1" in\n'
                f'  status) cat {self.status_file} ;;\n'
                '  reauth) exit 0 ;;\n'
                'esac\n'
                'exit 0\n')

    def save_uci(self):
        lines = ''.join(f'{key}={value}\n' for key, value in sorted(self.uci.items()))
        self.uci_state.write_text(lines, encoding='utf-8')

    def install_commands(self):
        self.command('opkg', f'#!/bin/sh\ncat <<\'EOF\'\n{self.packages}EOF\n')
        self.command('ps', f'#!/bin/sh\ncat <<\'EOF\'\n{self.processes}EOF\n')
        self.command('netstat', f'#!/bin/sh\nprintf %s "{NETSTAT}"\n')
        self.command('df', f'#!/bin/sh\nprintf %s "{DF}"\n')
        self.command('nft', f'#!/bin/sh\nprintf %s "{NFT_RULES}"\n')
        self.command('uname', '#!/bin/sh\necho 6.6.151\n')
        self.command('logread', f'#!/bin/sh\nprintf %s "{LOGREAD}"\n')
        for name in ('ip', 'sysctl', 'ubus', 'jsonfilter'):
            self.command(name, '#!/bin/sh\nexit 0\n')
        # iwinfo 把信道写在 Mode 行的中间，真机格式是 fixture 必须还原的部分之一：
        # 空 stub 会让「按行首锚定」这种坏正则看起来是好的。
        self.command('iwinfo', (
            '#!/bin/sh\n'
            'case "$1" in\n'
            '  wlan0) channel=36 ;;\n'
            '  wlan1) channel=6 ;;\n'
            f"  *) printf %s '{IWINFO_LIST}'; exit 0 ;;\n"
            'esac\n'
            f"printf '{IWINFO_INFO}' \"$channel\" \"$channel\"\n"))
        self.command('uci', self.uci_mock())

    def command(self, name, text):
        path = self.bin / name
        path.write_text(text, encoding='utf-8')
        path.chmod(0o755)

    def uci_mock(self):
        return f'''#!{sys.executable}
import os, sys

STATE = {str(self.uci_state)!r}
LOG = {str(self.uci_log)!r}


def load():
    data = {{}}
    if os.path.exists(STATE):
        with open(STATE, encoding='utf-8') as handle:
            for line in handle:
                line = line.rstrip('\\n')
                if line:
                    key, _, value = line.partition('=')
                    data[key] = value
    return data


def save(data):
    with open(STATE, 'w', encoding='utf-8') as handle:
        for key, value in sorted(data.items()):
            handle.write('%s=%s\\n' % (key, value))


def log(line):
    with open(LOG, 'a', encoding='utf-8') as handle:
        handle.write(line + '\\n')


args = sys.argv[1:]
if args and args[0] == '-q':
    args = args[1:]
if not args:
    sys.exit(1)
command, rest = args[0], args[1:]
data = load()
if command == 'get':
    if rest[0] not in data:
        sys.exit(1)
    print(data[rest[0]])
    sys.exit(0)
if command == 'show':
    prefix = rest[0]
    hits = [(k, v) for k, v in sorted(data.items())
            if k == prefix or k.startswith(prefix + '.')]
    if not hits:
        sys.exit(1)
    for key, value in hits:
        print('%s=%s' % (key, value))
    sys.exit(0)
if command == 'set':
    key, _, value = rest[0].partition('=')
    data[key] = value
    save(data)
    log('set %s=%s' % (key, value))
    sys.exit(0)
if command == 'add_list':
    key, _, value = rest[0].partition('=')
    parts = data.get(key, '').split()
    if value not in parts:
        parts.append(value)
    data[key] = ' '.join(parts)
    save(data)
    log('add_list %s=%s' % (key, value))
    sys.exit(0)
if command == 'delete':
    for key in [k for k in data if k == rest[0] or k.startswith(rest[0] + '.')]:
        del data[key]
    save(data)
    log('delete %s' % rest[0])
    sys.exit(0)
if command == 'commit':
    log('commit %s' % (rest[0] if rest else ''))
    sys.exit(0)
sys.exit(1)
'''

    # ---- 运行

    def run(self, *args, mode='check'):
        env = dict(os.environ)
        env['PATH'] = str(self.bin) + os.pathsep + env['PATH']
        env['ACRH17_DOCTOR_ROOT'] = str(self.root)
        env['ACRH17_DOCTOR_MODE'] = mode
        return subprocess.run(['sh', str(DOCTOR), *args], env=env, text=True,
                              capture_output=True)

    def snapshot(self):
        entries = {}
        for path in sorted(self.root.rglob('*')):
            key = str(path.relative_to(self.root))
            if path.is_symlink():
                entries[key] = 'link:' + os.readlink(path)
            elif path.is_file():
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                entries[key] = '%s:%s' % (oct(path.stat().st_mode & 0o777), digest)
            else:
                entries[key] = 'dir'
        return entries

    def uci_now(self):
        data = {}
        for line in self.uci_state.read_text(encoding='utf-8').splitlines():
            if line:
                key, _, value = line.partition('=')
                data[key] = value
        return data

    def init_calls(self):
        if not self.init_log.exists():
            return []
        return self.init_log.read_text(encoding='utf-8').splitlines()


class DoctorTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.fixture = Fixture(self._tmp.name)
        self.fixture.build()

    def break_everything_fixable(self):
        f = self.fixture
        for service in ('watchcat', 'ddns'):
            (f.root / 'etc/rc.d' / f'S95{service}').symlink_to(
                f.root / 'etc/init.d' / service)
        # 造出真机上的残留目录：空的 mkdir 是个骗人的夹具，rmdir 能删掉一个
        # 空目录，于是「用 rmdir 清理」这个从来没生效过的修复在测试里一直是绿的。
        # 真机上 mwan3 退出时留下的一定是这些东西（09-15 现场看到的就是）。
        stale = f.root / 'var/run/mwan3'
        (stale / 'iface_state').mkdir(parents=True)
        (stale / 'iptables_log').mkdir()
        (stale / 'mmx_mask').write_text('0x3f000000\n', encoding='utf-8')
        f.uci['turboacc.config.sw_flow'] = '1'
        f.uci['turboacc.config.hw_flow'] = '1'
        f.uci['ua3f.main.l3_rewrite_ttl_value'] = '128'
        f.uci['ruijie.main.password_payload'] = ''
        f.uci['ruijie.main.password_prev'] = 'ROLLBACK-PW'
        f.save_uci()
        (f.root / 'etc/config/ruijie').chmod(0o644)


class DetectionTests(DoctorTestCase):
    def test_healthy_device_passes(self):
        result = self.fixture.run()
        self.assertNotIn('[FAIL]', result.stdout, result.stdout)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn('固件版本 OpenWrt 24.10.0-20260914-2100', result.stdout)
        self.assertIn('L3 重写: TTL 64 + 去 TCP 时间戳', result.stdout)
        self.assertIn('全部通过。', result.stdout)

    def test_check_mode_changes_nothing(self):
        # check 是只读的：跑完之后整棵树必须逐字节相同，包括权限与符号链接。
        self.break_everything_fixable()
        before = self.fixture.snapshot()
        result = self.fixture.run()
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertEqual(self.fixture.snapshot(), before)

    def test_faults_are_named_with_their_fix(self):
        self.break_everything_fixable()
        out = self.fixture.run().stdout
        for fragment in ('watchcat 被重新启用了', 'ddns 被重新启用了',
                         '过期的 /var/run/mwan3', 'turboacc sw_flow=1',
                         'L3 重写不是 TTL 64', '/etc/config/ruijie 权限是 644',
                         'password_payload 是空的，但回退点还在'):
            self.assertIn(fragment, out)

    def test_expected_stamp_mismatch_fails(self):
        result = self.fixture.run('--expect-stamp', '20260101-0000')
        self.assertEqual(result.returncode, 1)
        self.assertIn('期望 20260101-0000', result.stdout)

    def test_lan_address_is_reported_not_rewritten(self):
        self.fixture.uci['network.lan.ipaddr'] = '10.0.0.1'
        self.fixture.save_uci()
        out = self.fixture.run().stdout
        self.assertIn('LAN 地址是 10.0.0.1', out)
        self.assertEqual(self.fixture.uci_now()['network.lan.ipaddr'], '10.0.0.1')

    def test_wireless_mode_is_only_rewritten_with_the_flag(self):
        self.fixture.uci['wireless.radio0.htmode'] = 'NOHT'
        self.fixture.save_uci()
        out = self.fixture.run().stdout
        self.assertIn('模式是 NOHT，应为 HT20', out)
        self.assertEqual(self.fixture.uci_now()['wireless.radio0.htmode'], 'NOHT')

        out = self.fixture.run('--fix-wifi').stdout
        self.assertIn('模式改回 HT20', out)
        self.assertEqual(self.fixture.uci_now()['wireless.radio0.htmode'], 'HT20')

    def test_the_channel_is_never_rewritten_not_even_by_the_flag(self):
        # 09-14 把 2.4G 定成 ch6，09-15 三次复扫证明 ch1 好 20 dB。信道随射频
        # 环境变，写死的值在环境变了以后只会帮倒忙，所以 --fix-wifi 也不碰它。
        self.fixture.uci['wireless.radio0.channel'] = '11'
        self.fixture.save_uci()
        for args in ((), ('--fix-wifi',), ()):
            out = self.fixture.run(*args).stdout
            self.assertEqual(self.fixture.uci_now()['wireless.radio0.channel'], '11')
            self.assertEqual(self.fixture.uci_now()['wireless.radio1.channel'], '36')
            self.assertNotIn('实测选台', out)

    def test_stale_auth_state_is_reported_not_forced(self):
        # 门户探测说 online，状态文件说 failed：页面显示是旧的，不该因此重新认证。
        self.fixture.write('tmp/ruijie-auth.state', 'auth_state=failed\nlast_result=failure\n')
        out = self.fixture.run().stdout
        self.assertIn('门户探测: 已联网，但状态文件写的是 failed', out)
        self.assertNotIn('[FIX ]', out)

    def test_loopback_binding_comes_from_uci_not_the_listen_address(self):
        # 真机上端口听在通配地址上而配置是对的（SO_BINDTODEVICE 不体现在地址里），
        # 按监听地址判会把这份正确的配置报成「没绑回环」。
        out = self.fixture.run().stdout
        self.assertIn('SmartDNS 只收 lo 的查询', out)
        self.assertNotIn('没绑回环', out)

        self.fixture.uci['smartdns.@smartdns[0].bind_device'] = '0'
        self.fixture.save_uci()
        out = self.fixture.run().stdout
        self.assertIn('SmartDNS 没绑回环', out)

    def test_permissions_are_read_when_stat_is_unusable(self):
        # busybox 不一定编进 stat，GNU 的 -c 与 BSD 的 -f 又互不兼容；真机上两条都
        # 失败，权限检查整段静默地「通过」了。读数不能靠 stat。
        self.fixture.command('stat', '#!/bin/sh\nexit 1\n')
        out = self.fixture.run().stdout
        self.assertIn('/etc/config/ruijie 权限 0600', out)
        self.assertIn('ruijie-auth 权限 0755', out)

    def test_running_channel_is_parsed_from_iwinfo(self):
        # 信道在 Mode 行的中间，不是行首；iwinfo 的续行也不该被当成网卡名。
        out = self.fixture.run().stdout
        self.assertIn('运行态 wlan0 信道 36', out)
        self.assertIn('运行态 wlan1 信道 6', out)
        self.assertNotIn('运行态 Mode:', out)

    def test_unconfigured_ruijie_is_reported_without_noise(self):
        # 没配置不是故障：三个空字段不该各报一条 WARN 把真故障淹掉。
        for key in ('username', 'server', 'query_string', 'password_payload',
                    'password_original'):
            self.fixture.uci[f'ruijie.main.{key}'] = ''
        self.fixture.save_uci()
        out = self.fixture.run().stdout
        self.assertIn('锐捷认证还没配置', out)
        self.assertIn('还没有锐捷密码（服务尚未配置，属正常）', out)
        for key in ('username', 'server', 'query_string'):
            self.assertNotIn(f'ruijie.main.{key} 是空的', out)
        self.assertNotIn('还没有可用的锐捷密码', out)


class RepairTests(DoctorTestCase):
    def test_fix_repairs_and_leaves_a_clean_second_run(self):
        self.break_everything_fixable()
        result = self.fixture.run(mode='fix')
        self.assertEqual(result.returncode, 0, result.stdout)
        state = self.fixture.uci_now()
        self.assertEqual(state['turboacc.config.sw_flow'], '0')
        self.assertEqual(state['turboacc.config.hw_flow'], '0')
        self.assertEqual(state['ua3f.main.l3_rewrite_ttl_value'], '64')
        self.assertEqual(state['ruijie.main.password_payload'], 'ROLLBACK-PW')
        self.assertEqual(stat.S_IMODE((self.fixture.root / 'etc/config/ruijie').stat().st_mode),
                         0o600)
        self.assertFalse((self.fixture.root / 'var/run/mwan3').exists())
        calls = self.fixture.init_calls()
        self.assertIn('watchcat disable', calls)
        self.assertIn('watchcat stop', calls)
        self.assertIn('ddns disable', calls)
        self.assertIn('turboacc restart', calls)
        self.assertIn('ua3f restart', calls)

        # 修完再检查一次：既证明修复真的落到了设备状态上，也证明脚本可重复运行。
        second = self.fixture.run()
        self.assertEqual(second.returncode, 0, second.stdout)
        self.assertNotIn('[FAIL]', second.stdout, second.stdout)

    def test_missing_rc_d_links_are_reenabled(self):
        for service in ('smartdns', 'ua3f', 'irqbalance', 'turboacc'):
            (self.fixture.root / 'etc/rc.d' / f'S95{service}').unlink()
        result = self.fixture.run(mode='fix')
        self.assertIn('[FIX ]', result.stdout)
        for service in ('smartdns', 'ua3f', 'irqbalance', 'turboacc'):
            self.assertTrue((self.fixture.root / 'etc/rc.d' / f'S95{service}').exists(),
                            service)
        self.assertEqual(self.fixture.run().returncode, 0)

    def test_original_anchor_is_used_when_there_is_no_rollback_point(self):
        self.fixture.uci['ruijie.main.password_payload'] = ''
        self.fixture.uci['ruijie.main.password_prev'] = ''
        self.fixture.save_uci()
        result = self.fixture.run(mode='fix')
        self.assertIn('用锚点补回', result.stdout)
        self.assertEqual(self.fixture.uci_now()['ruijie.main.password_payload'],
                         'SHIPPED-PW')

    def test_secrets_are_never_printed(self):
        for mode in ('check', 'fix'):
            out = self.fixture.run(mode=mode).stdout
            self.assertNotIn('CURRENT-PW', out)
            self.assertNotIn('SHIPPED-PW', out)
            self.assertNotIn('ROLLBACK-PW', out)
            self.assertNotIn('campus-wifi-key', out)

    def test_offline_portal_reauths_only_with_the_flag(self):
        self.fixture.status_file.write_text('offline\n')
        out = self.fixture.run().stdout
        self.assertIn('门户探测: 不可达', out)
        self.assertNotIn('[FIX ]', out)
        out = self.fixture.run('--fix-auth').stdout
        self.assertIn('已执行一次重新认证', out)


class RemoteModeTests(unittest.TestCase):
    """--host 把脚本经 ssh 送过去跑；这条路径不走假根目录，走的是 ssh 本身。"""

    def setUp(self):
        self.base = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        self.bin = self.base / 'bin'
        self.bin.mkdir()
        self.calls = self.base / 'calls.log'
        self.calls.write_text('', encoding='utf-8')
        # 一个只记账的 ssh：它必须把 stdin 上的脚本读掉，否则上游会看到 EPIPE。
        ssh = self.bin / 'ssh'
        ssh.write_text('#!/bin/sh\n'
                       f'echo "ssh $*" >> {self.calls}\n'
                       'cat > /dev/null\n'
                       'exit 0\n', encoding='utf-8')
        ssh.chmod(0o755)

    def ssh_call(self):
        # 一次运行只有一条 ssh 记录，整段读取而不是按行读。
        text = self.calls.read_text(encoding='utf-8')
        self.assertTrue(text.startswith('ssh '), text)
        return text.rstrip('\n')

    def run_remote(self, *args, root=None):
        env = dict(os.environ)
        env['PATH'] = str(self.bin) + os.pathsep + env['PATH']
        # 远程模式在看见假根目录之前就 exec 掉了，这里默认不给 ROOT。
        env.pop('ACRH17_DOCTOR_ROOT', None)
        if root is not None:
            env['ACRH17_DOCTOR_ROOT'] = str(root)
        return subprocess.run(['sh', str(DOCTOR), '--host', 'root@192.168.5.1', *args],
                              env=env, text=True, capture_output=True)

    def test_key_is_passed_with_identities_only(self):
        self.run_remote('--ssh-key', '/keys/id_acrh17')
        call = self.ssh_call()
        self.assertIn('-i /keys/id_acrh17', call)
        # 不限制身份的话 agent 会挨个试手里的钥匙，可能在轮到这个之前就断开。
        self.assertIn('-o IdentitiesOnly=yes', call)
        self.assertIn('root@192.168.5.1', call)

    def test_key_also_accepts_the_equals_form(self):
        self.run_remote('--ssh-key=/keys/other')
        self.assertIn('-i /keys/other', self.ssh_call())

    def test_without_a_key_the_argument_is_absent(self):
        self.run_remote()
        call = self.ssh_call()
        self.assertNotIn('-i ', call)
        self.assertNotIn('IdentitiesOnly', call)

    def test_mode_and_flags_are_carried_into_the_remote_command(self):
        self.run_remote('fix', '--fix-wifi', '--fix-auth',
                        '--expect-stamp', '20260915-2227', '--ssh-key', '/keys/k')
        call = self.ssh_call()
        self.assertIn('ACRH17_DOCTOR_MODE=fix', call)
        self.assertIn('ACRH17_DOCTOR_FIX_WIFI=1', call)
        self.assertIn('ACRH17_DOCTOR_FIX_AUTH=1', call)
        self.assertIn("ACRH17_DOCTOR_EXPECT_STAMP='20260915-2227'", call)
        self.assertIn('sh -s', call)

    def test_remote_mode_wins_over_a_fake_root(self):
        # --host 分支排在假根目录检查之前，两者同时给定时不该去看那个目录。
        self.run_remote(root=self.base / 'does-not-exist')
        self.assertIn('root@192.168.5.1', self.ssh_call())


class DoctorSyncTests(unittest.TestCase):
    """The doctor's expectations must be the shipped defaults, not a copy that
    drifts away from them."""

    def setUp(self):
        self.doctor = DOCTOR.read_text(encoding='utf-8')
        self.defaults = (ROOT / 'files/etc/uci-defaults/90-acrh17').read_text(encoding='utf-8')

    def test_service_list_matches_the_uci_defaults(self):
        expected = re.search(r'for svc in ([^;]*); do', self.doctor).group(1).split()
        shipped = re.search(r'for service in ([^;]*); do', self.defaults).group(1).split()
        self.assertEqual(sorted(expected), sorted(shipped))

    def test_turboacc_keys_match_the_runtime_patch(self):
        keys = re.search(r'for key in (sw_flow[^;]*); do', self.doctor).group(1).split()
        patch = (ROOT / 'scripts/patch-turboacc-runtime.py').read_text(encoding='utf-8')
        forced = re.findall(r'^\t+(\w+)=0$', patch, re.M)
        self.assertEqual(sorted(keys), sorted(forced))
        self.assertIn('sw_flow', keys)

    def test_guard_string_matches_the_runtime_patch(self):
        guard = re.search(r"grep -q '([^']*Flow offload[^']*)'", self.doctor).group(1)
        patch = (ROOT / 'scripts/patch-turboacc-runtime.py').read_text(encoding='utf-8')
        self.assertIn(guard, patch)

    def test_dnsmasq_expectations_match_the_uci_defaults(self):
        fix = re.search(r"for s in ([^;]*); do uci -q add_list dhcp", self.doctor).group(1)
        entries = fix.split()
        self.assertIn('/scau.edu.cn/202.116.160.33', self.defaults)
        for entry in entries:
            self.assertIn(entry, self.defaults, entry)
        self.assertIn("uci -q add_list dhcp.@dnsmasq[0].rebind_domain='scau.edu.cn'",
                      self.defaults)

    def test_mwan3_mask_and_probe_targets_match_the_shipped_configs(self):
        self.assertIn("uci -q set mwan3.globals.mmx_mask='0x3f000000'", self.defaults)
        self.assertIn("mwan3.globals.mmx_mask=0x3f000000", self.doctor)
        config = (ROOT / 'files/etc/config/acrh17').read_text(encoding='utf-8')
        for target in ('223.5.5.5', '119.29.29.29', '114.114.114.114'):
            self.assertIn(f"list mwan3_probe_ip '{target}'", config)
        self.assertIn('223.5.5.5 119.29.29.29 114.114.114.114', self.doctor)

    def test_keep_entry_the_doctor_checks_is_the_shipped_one(self):
        keep = (ROOT / 'files/lib/upgrade/keep.d/acrh17').read_text(encoding='utf-8')
        self.assertIn("grep -qx '/opt/p910nd_drivers'", self.doctor)
        self.assertIn('/opt/p910nd_drivers', keep)


if __name__ == '__main__':
    unittest.main()
