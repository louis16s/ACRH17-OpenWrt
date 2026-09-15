"""Run the campus recovery script (scripts/acrh17-campus-up.sh) against a fixture router.

The script exists for the state a reflash leaves behind: rootfs_data is rebuilt,
so the Ruijie config is back to its shipped defaults -- no portal address, no
student id, no password, service off -- while the WAN still holds a campus IPv4
lease. The one thing the router can work out by itself is the portal address,
and it comes from the same 302 that ruijie-refresh-query reads the query string
from, so the fixture has to model that redirect honestly.

Like the doctor's fixture, both halves of the environment are supplied: a fake
root tree for every file the script looks at, and a fake PATH for every command
it runs. Every stub logs to one file *outside* the root tree, so a check run can
be held to leaving the tree byte-identical and the ordering of a fix run can be
asserted from the same log.
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts/acrh17-campus-up.sh'
REFRESH = ROOT / 'package/ruijie-auth/files/usr/libexec/ruijie-refresh-query'

OPENWRT_RELEASE = """DISTRIB_ID='ImmortalWrt'
DISTRIB_RELEASE='24.10-SNAPSHOT'
DISTRIB_REVISION='r0-946a25f'
DISTRIB_TARGET='ipq40xx/generic'
DISTRIB_ARCH='arm_cortex-a7_neon-vfpv4'
DISTRIB_DESCRIPTION='ImmortalWrt 24.10-SNAPSHOT r0-946a25f'
"""

WAN_IP = '172.16.67.126'
WAN_DEVICE = 'eth0.2'

# 门户对 80 端口的拦截：Location 同时带着门户 origin 和本次链路的 query。
# 两个字段都是门户按客户端加密的，所以值本身没有可读性，只要非空即可。
QUERY = ('wlanuserip=8A3F21&wlanacname=SCAU&mac=77C1E0&t=1757890000')
PORTAL = 'http://172.16.0.1/eportal/index.jsp?' + QUERY

# 一台刚刷完机的路由器：配置全空、服务关着、rc.d 里没有自启链接。
FLASHED = {
    'ruijie.main.enabled': '0',
    'ruijie.main.server': '',
    'ruijie.main.username': '',
    'ruijie.main.password_payload': '',
    'ruijie.main.query_string': '',
    'ruijie.main.wan_interface': 'wan',
    'ruijie.main.interface': '',
    'ruijie.main.auto_reconnect': '1',
    'ruijie.main.boot_login': '1',
    'ruijie.main.check_url': 'http://connect.rom.miui.com/generate_204',
}


class Fixture:
    """A fake router on disk: root tree plus mocked commands on PATH."""

    def __init__(self, base):
        self.base = Path(base)
        self.root = self.base / 'root'
        self.bin = self.base / 'bin'
        # 全部桩状态都在 root 之外：它们每次调用都会写，落在 root 里的话
        # 「check 不动任何东西」这条断言就变成了在检查自己的日志。
        self.calls = self.base / 'calls.log'
        self.uci_state = self.base / 'uci.state'
        self.wan_json = self.base / 'wan.json'
        self.curl_spec = self.base / 'curl.json'
        self.auth_status = self.base / 'auth-status'
        self.login_rc = self.base / 'login-rc'
        self.pw_accept = self.base / 'pw-accept'
        self.pw_mode = self.base / 'pw-mode'
        self.uci = dict(FLASHED)
        self.rc_d_link = False
        self.root.mkdir(parents=True)
        self.bin.mkdir()

    # ---- 构造

    def write(self, relative, text, mode=0o644):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
        path.chmod(mode)
        return path

    def command(self, name, text):
        path = self.bin / name
        path.write_text(text, encoding='utf-8')
        path.chmod(0o755)

    def build(self):
        self.write('etc/openwrt_release', OPENWRT_RELEASE)
        self.write('etc/config/ruijie', "config main 'main'\n\toption enabled '0'\n", 0o600)
        self.write('tmp/.keep', '')
        self.set_wan(up=True, address=WAN_IP, device=WAN_DEVICE)
        self.set_redirect(PORTAL)
        self.set_auth(online=False)
        self.set_login_rc(0)
        self.set_accepted_password('')
        self.set_password_mode('reject')
        self.write_stubs()
        self.write_services()
        self.save_uci()

    def write_services(self):
        """设备上的可执行文件：认证程序、改密码的程序，以及 init 脚本。"""
        # ruijie-password 的桩：只认 pw-accept 里那一个密码，其余按 pw-mode 表态。
        # 它照真实行为更新 UCI——被拒绝时什么都不留，就像真脚本回退到上一个值。
        self.write('usr/libexec/ruijie-password', (
            '#!/bin/sh\n'
            f'echo "ruijie-password $*" >> {self.calls}\n'
            '[ "$1" = set ] || exit 0\n'
            'pw="$2"\n'
            f'if [ -n "$(cat {self.pw_accept} 2>/dev/null)" ] && '
            f'[ "$pw" = "$(cat {self.pw_accept})" ]; then\n'
            f'  uci set "ruijie.main.password_payload=$pw"\n'
            '  uci commit ruijie\n'
            '  exit 0\n'
            'fi\n'
            f'case "$(cat {self.pw_mode} 2>/dev/null)" in\n'
            '  unverified) exit 2 ;;\n'
            '  locked) exit 75 ;;\n'
            'esac\n'
            'exit 1\n'), 0o755)
        self.write('usr/libexec/ruijie-auth', (
            '#!/bin/sh\n'
            f'echo "ruijie-auth $*" >> {self.calls}\n'
            'case "$1" in\n'
            f'  status) [ "$(cat {self.auth_status})" = online ] && exit 0 || exit 1 ;;\n'
            '  login)\n'
            f'    rc="$(cat {self.login_rc})"\n'
            '    if [ "$rc" != 0 ]; then\n'
            f'      mkdir -p {self.root}/tmp\n'
            f'      printf "login: portal rejected request\\n" > {self.root}/tmp/ruijie-auth.last\n'
            '    fi\n'
            '    exit "$rc" ;;\n'
            'esac\n'
            'exit 0\n'), 0o755)
        self.write('etc/init.d/ruijie-auth', (
            '#!/bin/sh\n'
            f'echo "init $*" >> {self.calls}\n'
            'case "$1" in\n'
            f'  enable) ln -sf "$0" {self.root}/etc/rc.d/S95ruijie-auth ;;\n'
            'esac\n'
            'exit 0\n'), 0o755)
        (self.root / 'etc/rc.d').mkdir(exist_ok=True)

    def write_stubs(self):
        self.command('uci', UCI_MOCK.replace('@STATE@', str(self.uci_state)).replace('@PYTHON@', sys.executable))
        self.command('ubus', (
            '#!/bin/sh\n'
            f'echo "ubus $*" >> {self.calls}\n'
            '[ "$1" = call ] || exit 1\n'
            f'[ -s {self.wan_json} ] || exit 1\n'
            f'cat {self.wan_json}\n'))
        self.command('jsonfilter', JSONFILTER.replace('@PYTHON@', sys.executable))
        # 上线那段会 sleep 等收敛（真机上是 6 次 5 秒）。夹具把等待去掉，好让
        # 「重试到放弃」这条路径也能被跑完——被换掉的是等待，不是重试本身。
        self.command('sleep', f'#!/bin/sh\necho "sleep $*" >> {self.calls}\nexit 0\n')
        self.command('curl', CURL_MOCK.replace('@PYTHON@', sys.executable)
                     .replace('@CALLS@', str(self.calls))
                     .replace('@SPEC@', str(self.curl_spec)))

    # ---- 状态

    def save_uci(self):
        self.uci_state.write_text(
            ''.join(f'{key}={value}\n' for key, value in sorted(self.uci.items())),
            encoding='utf-8')

    def set_wan(self, up=True, address=WAN_IP, device=WAN_DEVICE):
        if not up:
            self.wan_json.write_text(json.dumps({'up': False}), encoding='utf-8')
            return
        self.wan_json.write_text(json.dumps({
            'up': True,
            'ipv4-address': [{'address': address}],
            'l3_device': device,
        }), encoding='utf-8')

    def set_wan_absent(self):
        self.wan_json.write_text('', encoding='utf-8')

    def set_redirect(self, location=None, code=302):
        """location=None 表示没有重定向（已经在线，或者根本没被拦）。"""
        self.curl_spec.write_text(json.dumps({'location': location, 'code': code}),
                                  encoding='utf-8')

    def set_curl_error(self):
        self.curl_spec.write_text(json.dumps({'error': True}), encoding='utf-8')

    def set_auth(self, online=True):
        self.auth_status.write_text('online\n' if online else 'offline\n', encoding='utf-8')

    def set_login_rc(self, rc):
        self.login_rc.write_text(str(rc), encoding='utf-8')

    def set_accepted_password(self, password):
        """哪个候选密码会被门户接受；空字符串表示全都拒绝。"""
        self.pw_accept.write_text(password, encoding='utf-8')

    def set_password_mode(self, mode):
        """候选密码被打回时 ruijie-password 的退出码：unverified=2，locked=75。"""
        self.pw_mode.write_text(mode, encoding='utf-8')

    def add_rc_d_link(self):
        (self.root / 'etc/rc.d').mkdir(exist_ok=True)
        link = self.root / 'etc/rc.d/S95ruijie-auth'
        if not link.exists():
            link.symlink_to(self.root / 'etc/init.d/ruijie-auth')

    # ---- 运行

    def run(self, *args, mode='check'):
        self.calls.write_text('', encoding='utf-8')
        env = dict(os.environ)
        env['PATH'] = str(self.bin) + os.pathsep + env['PATH']
        env['ACRH17_CAMPUS_ROOT'] = str(self.root)
        env['ACRH17_CAMPUS_MODE'] = mode
        return subprocess.run(['sh', str(SCRIPT), *args], env=env, text=True,
                              capture_output=True)

    def log(self):
        return self.calls.read_text(encoding='utf-8').splitlines()

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


JSONFILTER = '''#!@PYTHON@
"""Enough of jsonfilter to keep the script honest about its expressions.

Only the two shapes the script uses are understood, and an expression that
drifts to a wrong path resolves to nothing -- which is what jsonfilter does --
so a typo fails the test instead of silently reading something else.
"""
import json
import re
import sys

def resolve(data, expr):
    if not expr.startswith('@'):
        return None
    current = data
    pattern = r'\\.([A-Za-z0-9_-]+)|\\[(\\d+)\\]|\\["([^"]+)"\\]'
    for name, index, quoted in re.findall(pattern, expr[1:]):
        key = name or quoted
        try:
            current = current[key] if key else current[int(index)]
        except (KeyError, IndexError, TypeError):
            return None
    return current

args = sys.argv[1:]
expr = args[args.index('-e') + 1] if '-e' in args else ''
try:
    payload = json.load(sys.stdin)
except ValueError:
    sys.exit(1)
value = resolve(payload, expr)
if value is None:
    sys.exit(1)
if isinstance(value, bool):
    print('true' if value else 'false')
elif isinstance(value, (dict, list)):
    print(json.dumps(value))
else:
    print(value)
'''

CURL_MOCK = '''#!@PYTHON@
import json
import sys

with open('@CALLS@', 'a', encoding='utf-8') as handle:
    handle.write('curl ' + ' '.join(sys.argv[1:]) + '\\n')

with open('@SPEC@', encoding='utf-8') as handle:
    spec = json.load(handle)

if spec.get('error'):
    sys.stderr.write('curl: (7) Failed to connect to 1.1.1.1 port 80\\n')
    sys.exit(7)

sys.stdout.write('HTTP/1.1 %s \\r\\n' % spec.get('code', 302))
if spec.get('location'):
    sys.stdout.write('Location: %s\\r\\n' % spec['location'])
sys.stdout.write('\\r\\n')
'''

UCI_MOCK = '''#!@PYTHON@
import os
import sys

STATE = '@STATE@'

def load():
    data = {}
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
if command == 'set':
    key, _, value = rest[0].partition('=')
    data[key] = value
    save(data)
    sys.exit(0)
if command == 'commit':
    sys.exit(0)
sys.exit(1)
'''


class CampusTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.fixture = Fixture(self._tmp.name)
        self.fixture.build()

    def flashed_with_credentials(self, username='2021123456', password='CAMPUS-PW'):
        """刚刷完机但学号密码已经补上：fix 应该能一路走到上线。"""
        f = self.fixture
        f.uci['ruijie.main.username'] = username
        f.uci['ruijie.main.password_payload'] = password
        f.save_uci()
        return f


class DetectionTests(CampusTestCase):
    def test_flashed_device_names_everything_that_is_missing(self):
        result = self.fixture.run(mode='check')
        self.assertEqual(result.returncode, 1, result.stdout)
        # 探针抓到了门户地址和 query，但 check 不写；凭据和服务是缺的。
        self.assertIn('门户地址应为 http://172.16.0.1', result.stdout)
        self.assertIn('抓到了新的 query_string', result.stdout)
        self.assertIn('ruijie.main.username 是空的', result.stdout)
        self.assertIn('还没有校园网密码', result.stdout)
        self.assertIn('认证服务是关的', result.stdout)
        self.assertNotIn('Traceback', result.stdout + result.stderr)

    def test_check_mode_changes_nothing(self):
        before_tree = self.fixture.snapshot()
        before_uci = dict(self.fixture.uci_now())
        result = self.fixture.run(mode='check')
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.fixture.snapshot(), before_tree)
        self.assertEqual(self.fixture.uci_now(), before_uci)

    def test_check_mode_never_logs_in(self):
        self.fixture.run(mode='check')
        self.assertEqual([line for line in self.fixture.log()
                          if line.startswith('ruijie-auth login')], [])
        self.assertEqual([line for line in self.fixture.log()
                          if line.startswith('init restart')], [])

    def test_online_link_needs_no_redirect(self):
        f = self.flashed_with_credentials()
        f.uci['ruijie.main.server'] = 'http://172.16.0.1'
        f.uci['ruijie.main.query_string'] = QUERY
        f.uci['ruijie.main.enabled'] = '1'
        f.save_uci()
        f.add_rc_d_link()
        f.set_auth(online=True)
        f.set_redirect(None, code=204)
        result = f.run(mode='check')
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn('校园链路已经在线', result.stdout)
        self.assertIn('全部通过', result.stdout)

    def test_link_without_ipv4_stops_before_probing(self):
        self.fixture.set_wan(up=False)
        result = self.fixture.run(mode='check')
        self.assertEqual(result.returncode, 1)
        self.assertIn('WAN 没有 IPv4', result.stdout)
        # 没有地址就没有可认证的链路，探针不该发出去。
        self.assertEqual([line for line in self.fixture.log()
                          if line.startswith('curl ')], [])

    def test_missing_wan_interface_is_reported_not_crashed(self):
        self.fixture.set_wan_absent()
        result = self.fixture.run(mode='check')
        self.assertEqual(result.returncode, 1)
        self.assertIn('WAN 没有 IPv4', result.stdout)

    def test_password_is_masked_and_never_printed(self):
        f = self.flashed_with_credentials(password='SUPER-SECRET-VALUE')
        result = f.run(mode='check')
        self.assertNotIn('SUPER-SECRET-VALUE', result.stdout)
        self.assertNotIn('SUPER-SECRET-VALUE', result.stderr)
        # 掩码本身要能看出配过：位数与末两位，与 ruijie-password 同一套。
        self.assertIn('18 位，末两位 UE', result.stdout)


class PortalAddressTests(CampusTestCase):
    def test_redirect_origin_becomes_the_server(self):
        f = self.flashed_with_credentials()
        result = f.run(mode='fix')
        self.assertIn('写入门户地址 http://172.16.0.1', result.stdout)
        self.assertEqual(f.uci_now()['ruijie.main.server'], 'http://172.16.0.1')

    def test_query_string_is_written_with_the_server(self):
        f = self.flashed_with_credentials()
        f.run(mode='fix')
        self.assertEqual(f.uci_now()['ruijie.main.query_string'], QUERY)

    def test_probe_uses_the_wan_device_not_the_default_route(self):
        f = self.flashed_with_credentials()
        f.run(mode='fix')
        curls = [line for line in f.log() if line.startswith('curl ')]
        self.assertTrue(curls, 'fix 应该探测过一次重定向')
        # 门户把 query 绑在收到请求的地址上，探针必须从认证要走的设备出去。
        for line in curls:
            self.assertIn('--interface ' + WAN_DEVICE, line)

    def test_explicit_interface_overrides_the_l3_device(self):
        f = self.flashed_with_credentials()
        f.uci['ruijie.main.interface'] = 'br-wan'
        f.save_uci()
        f.run(mode='fix')
        curls = [line for line in f.log() if line.startswith('curl ')]
        self.assertTrue(curls)
        for line in curls:
            self.assertIn('--interface br-wan', line)
            self.assertNotIn('--interface ' + WAN_DEVICE, line)

    def test_redirect_that_is_not_a_portal_page_is_ignored(self):
        f = self.flashed_with_credentials()
        # 透明代理或上级网关也会重定向，但它的 origin 不是门户。
        f.set_redirect('http://192.168.1.1/login.html', code=302)
        result = f.run(mode='fix')
        self.assertIn('但不是门户登录页', result.stdout)
        self.assertEqual(f.uci_now()['ruijie.main.server'], '')
        self.assertEqual(f.uci_now()['ruijie.main.query_string'], '')

    def test_query_missing_mac_is_refused(self):
        f = self.flashed_with_credentials()
        f.set_redirect('http://172.16.0.1/eportal/index.jsp?wlanuserip=8A3F21')
        result = f.run(mode='fix')
        self.assertIn('缺 wlanuserip 或 mac', result.stdout)
        self.assertEqual(f.uci_now()['ruijie.main.query_string'], '')
        # 门户地址仍然可用：缺的是查询串，不是 origin。
        self.assertEqual(f.uci_now()['ruijie.main.server'], 'http://172.16.0.1')

    def test_portal_page_without_a_query_still_yields_the_server(self):
        f = self.flashed_with_credentials()
        f.set_redirect('http://172.16.0.1/eportal/index.jsp')
        f.run(mode='fix')
        self.assertEqual(f.uci_now()['ruijie.main.server'], 'http://172.16.0.1')

    def test_server_argument_skips_the_probe(self):
        f = self.flashed_with_credentials()
        f.uci['ruijie.main.query_string'] = QUERY
        f.uci['ruijie.main.server'] = 'http://172.16.0.9'
        f.save_uci()
        f.set_curl_error()
        result = f.run('--server', 'http://172.16.0.9', mode='fix')
        self.assertEqual([line for line in f.log() if line.startswith('curl ')], [])
        self.assertIn('跳过重定向探测', result.stdout)
        self.assertIn('门户地址 http://172.16.0.9', result.stdout)

    def test_http_and_https_origins_are_both_kept(self):
        f = self.flashed_with_credentials()
        f.set_redirect('https://portal.scau.edu.cn/eportal/index.jsp?' + QUERY)
        f.run(mode='fix')
        self.assertEqual(f.uci_now()['ruijie.main.server'], 'https://portal.scau.edu.cn')

    def test_origin_keeps_an_explicit_port(self):
        f = self.flashed_with_credentials()
        f.set_redirect('http://172.16.0.1:8080/eportal/index.jsp?' + QUERY)
        f.run(mode='fix')
        self.assertEqual(f.uci_now()['ruijie.main.server'], 'http://172.16.0.1:8080')


class CredentialTests(CampusTestCase):
    def test_student_id_is_written_from_the_argument(self):
        f = self.flashed_with_credentials(username='')
        result = f.run('--user', '2021999999', mode='fix')
        self.assertIn('写入学号 2021999999', result.stdout)
        self.assertEqual(f.uci_now()['ruijie.main.username'], '2021999999')

    def test_service_stays_closed_without_a_password(self):
        f = self.flashed_with_credentials(password='')
        result = f.run('--user', '2021999999', mode='fix')
        self.assertEqual(f.uci_now()['ruijie.main.enabled'], '0')
        self.assertEqual([line for line in f.log() if line.startswith('init restart')], [])
        self.assertIn('先不开服务', result.stdout)
        # 缺什么要说清楚，并且说清补齐的顺序。
        self.assertIn('ruijie-password set', result.stdout)
        self.assertIn('2. /usr/libexec/ruijie-password set', result.stdout)

    def test_autostart_link_is_restored_even_without_credentials(self):
        """sysupgrade 会重建 /etc/rc.d，链接本身要补回来；enabled=0 时它不会启动任何东西。"""
        f = self.flashed_with_credentials(password='')
        f.run('--user', '2021999999', mode='fix')
        self.assertTrue((f.root / 'etc/rc.d/S95ruijie-auth').exists())
        self.assertEqual(f.uci_now()['ruijie.main.enabled'], '0')

    def test_missing_student_id_is_named(self):
        f = self.flashed_with_credentials(username='')
        result = f.run(mode='check')
        self.assertIn('--user <学号>', result.stdout)

    def test_portal_address_is_required_for_the_service(self):
        f = self.flashed_with_credentials()
        f.set_redirect('http://192.168.1.1/login.html')  # 不是门户，server 仍是空的
        result = f.run(mode='fix')
        self.assertEqual(f.uci_now()['ruijie.main.enabled'], '0')
        self.assertIn('先不开服务', result.stdout)
        # 缺门户地址只报一次，而且报在门户地址那节（可操作的那句），
        # 不在凭据节再用 FAIL 说一遍同一个事实。
        fails = [line for line in result.stdout.splitlines()
                 if line.startswith('[FAIL]') and '门户地址' in line]
        self.assertEqual(len(fails), 1, result.stdout)
        self.assertIn('推不出门户地址', fails[0])

    def test_portal_address_without_a_scheme_is_named(self):
        f = self.flashed_with_credentials()
        f.uci['ruijie.main.server'] = '172.16.0.1/eportal'
        f.save_uci()
        result = f.run(mode='check')
        self.assertIn('门户地址不是 http(s) URL：172.16.0.1/eportal', result.stdout)
        self.assertEqual(f.uci_now()['ruijie.main.enabled'], '0')


class RepairTests(CampusTestCase):
    def test_fix_brings_the_link_up(self):
        f = self.flashed_with_credentials()
        f.set_auth(online=True)
        result = f.run(mode='fix')
        self.assertEqual(f.uci_now()['ruijie.main.enabled'], '1')
        self.assertTrue((f.root / 'etc/rc.d/S95ruijie-auth').exists())
        self.assertIn('门户接受了登录', result.stdout)
        self.assertIn('连通性探测通过', result.stdout)
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_login_happens_before_the_daemon_starts(self):
        """先起服务会和这次登录抢认证锁，把一次好登录变成 75。"""
        f = self.flashed_with_credentials()
        f.set_auth(online=True)
        f.run(mode='fix')
        lines = f.log()
        login = next(i for i, line in enumerate(lines) if line.startswith('ruijie-auth login'))
        restart = next(i for i, line in enumerate(lines) if line.startswith('init restart'))
        self.assertLess(login, restart, lines)

    def test_busy_lock_is_not_reported_as_a_login_failure(self):
        f = self.flashed_with_credentials()
        f.set_login_rc(75)
        f.set_auth(online=False)
        result = f.run(mode='fix')
        self.assertIn('另一个认证动作正持锁', result.stdout)
        self.assertNotIn('登录未成功', result.stdout)

    def test_rejected_login_surfaces_the_reason(self):
        f = self.flashed_with_credentials()
        f.set_login_rc(1)
        f.set_auth(online=False)
        result = f.run(mode='fix')
        self.assertIn('登录未成功：login: portal rejected request', result.stdout)

    def test_daemon_is_restarted_even_when_the_login_failed(self):
        f = self.flashed_with_credentials()
        f.set_login_rc(1)
        f.set_auth(online=False)
        f.run(mode='fix')
        # auto_refresh_query 会在守护进程里重抓 query 再试，这正是链路变化后需要的。
        self.assertIn('init restart', f.log())

    def test_fix_repairs_and_leaves_a_clean_second_run(self):
        f = self.flashed_with_credentials()
        f.set_auth(online=True)
        fixed = f.run('--user', '2021123456', mode='fix')
        self.assertEqual(fixed.returncode, 0, fixed.stdout)
        second = f.run(mode='check')
        self.assertEqual(second.returncode, 0, second.stdout)
        self.assertIn('全部通过', second.stdout)

    def test_second_fix_is_idempotent(self):
        f = self.flashed_with_credentials()
        f.set_auth(online=True)
        f.run('--user', '2021123456', mode='fix')
        before_tree = f.snapshot()
        before_uci = dict(f.uci_now())
        again = f.run('--user', '2021123456', mode='fix')
        self.assertEqual(again.returncode, 0, again.stdout)
        self.assertEqual(f.snapshot(), before_tree)
        self.assertEqual(f.uci_now(), before_uci)

    def test_service_is_started_but_not_enabled_twice(self):
        f = self.flashed_with_credentials()
        f.set_auth(online=True)
        f.run(mode='fix')
        self.assertEqual(f.log().count('init enable'), 1)


class PasswordCandidateTests(CampusTestCase):
    """--password 让 fix 一次走完；每个候选都要经过真实登录验证才留下。"""

    def attempts(self):
        return [line for line in self.fixture.log()
                if line.startswith('ruijie-password set')]

    def test_first_candidate_wins_and_nothing_else_is_tried(self):
        f = self.flashed_with_credentials(password='')
        f.set_accepted_password('FIRST-OK')
        result = f.run('--user', '20262159017', '--password', 'FIRST-OK',
                       '--password', 'SECOND', mode='fix')
        self.assertEqual(f.uci_now()['ruijie.main.password_payload'], 'FIRST-OK')
        self.assertEqual(len(self.attempts()), 1, result.stdout)
        self.assertIn('第 1 个候选密码通过门户验证', result.stdout)

    def test_a_rejected_candidate_falls_through_to_the_next(self):
        f = self.flashed_with_credentials(password='')
        f.set_accepted_password('SECOND-OK')
        result = f.run('--user', '20262159017', '--password', 'WRONG',
                       '--password', 'SECOND-OK', mode='fix')
        self.assertEqual(f.uci_now()['ruijie.main.password_payload'], 'SECOND-OK')
        self.assertEqual(len(self.attempts()), 2, result.stdout)
        self.assertIn('第 1 个候选密码被门户拒绝，已自动回退', result.stdout)
        self.assertIn('第 2 个候选密码通过门户验证', result.stdout)

    def test_the_candidate_that_worked_is_the_one_that_goes_online(self):
        f = self.flashed_with_credentials(password='')
        f.set_accepted_password('SECOND-OK')
        f.set_auth(online=True)
        result = f.run('--user', '20262159017', '--password', 'WRONG',
                       '--password', 'SECOND-OK', mode='fix')
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(f.uci_now()['ruijie.main.enabled'], '1')
        self.assertIn('连通性探测通过', result.stdout)

    def test_every_candidate_rejected_leaves_no_password_and_no_service(self):
        f = self.flashed_with_credentials(password='')
        f.set_accepted_password('')
        result = f.run('--user', '20262159017', '--password', 'A', '--password', 'B',
                       mode='fix')
        self.assertEqual(f.uci_now()['ruijie.main.password_payload'], '')
        self.assertEqual(f.uci_now()['ruijie.main.enabled'], '0')
        self.assertEqual(result.returncode, 1)
        self.assertIn('还没有校园网密码', result.stdout)

    def test_an_existing_password_is_left_alone(self):
        """重设一个没被投诉过的密码就是白白断一次线。"""
        f = self.flashed_with_credentials(password='ALREADY-SET')
        result = f.run('--password', 'SOMETHING-ELSE', mode='fix')
        self.assertEqual(self.attempts(), [], result.stdout)
        self.assertEqual(f.uci_now()['ruijie.main.password_payload'], 'ALREADY-SET')

    def test_unverified_candidate_stops_instead_of_guessing_again(self):
        """退出码 2 意味着这次尝试没有产生任何关于密码的证据，不该拿它当拒绝。"""
        f = self.flashed_with_credentials(password='')
        f.set_accepted_password('NEVER')
        f.set_password_mode('unverified')
        result = f.run('--user', '20262159017', '--password', 'A', '--password', 'B',
                       mode='fix')
        self.assertEqual(len(self.attempts()), 1, result.stdout)
        self.assertIn('没能验证', result.stdout)

    def test_busy_lock_stops_the_sequence(self):
        f = self.flashed_with_credentials(password='')
        f.set_accepted_password('NEVER')
        f.set_password_mode('locked')
        result = f.run('--user', '20262159017', '--password', 'A', '--password', 'B',
                       mode='fix')
        self.assertEqual(len(self.attempts()), 1, result.stdout)
        self.assertIn('正持锁', result.stdout)

    def test_candidates_are_not_tried_in_check_mode(self):
        f = self.flashed_with_credentials(password='')
        f.set_accepted_password('FIRST-OK')
        before = dict(f.uci_now())
        result = f.run('--user', '20262159017', '--password', 'FIRST-OK', mode='check')
        self.assertEqual(self.attempts(), [], result.stdout)
        self.assertEqual(f.uci_now(), before)

    def test_the_password_never_reaches_the_output(self):
        f = self.flashed_with_credentials(password='')
        f.set_accepted_password('S3CRET-CANDIDATE')
        f.set_auth(online=True)
        result = f.run('--user', '20262159017', '--password', 'S3CRET-CANDIDATE',
                       mode='fix')
        for stream in (result.stdout, result.stderr):
            self.assertNotIn('S3CRET-CANDIDATE', stream)
        # 但配置里确实写进去了，掩码能看出是哪一个。
        self.assertEqual(f.uci_now()['ruijie.main.password_payload'], 'S3CRET-CANDIDATE')
        self.assertIn('16 位，末两位 TE', result.stdout)

    def test_one_command_takes_a_flashed_router_online(self):
        """用户唯一要做的动作是切到路由器的网络上。"""
        f = self.fixture
        f.uci['ruijie.main.username'] = ''
        f.uci['ruijie.main.password_payload'] = ''
        f.save_uci()
        f.set_accepted_password('443988As')
        f.set_auth(online=True)
        result = f.run('--user', '20262159017', '--password', '20262159017',
                       '--password', '443988As', mode='fix')
        self.assertEqual(result.returncode, 0, result.stdout)
        uci = f.uci_now()
        self.assertEqual(uci['ruijie.main.server'], 'http://172.16.0.1')
        self.assertEqual(uci['ruijie.main.query_string'], QUERY)
        self.assertEqual(uci['ruijie.main.username'], '20262159017')
        self.assertEqual(uci['ruijie.main.password_payload'], '443988As')
        self.assertEqual(uci['ruijie.main.enabled'], '1')
        self.assertTrue((f.root / 'etc/rc.d/S95ruijie-auth').exists())
        self.assertIn('连通性探测通过', result.stdout)
        # 跑完再查一次应当是干净的。
        second = f.run(mode='check')
        self.assertEqual(second.returncode, 0, second.stdout)


class RemoteModeTests(CampusTestCase):
    """--host 把脚本经 ssh 送过去跑；这条路径不走假根目录，走的是 ssh 本身。"""

    def setUp(self):
        super().setUp()
        # 一个只记账的 ssh：它必须把 stdin 上的脚本读掉，否则上游会看到 EPIPE。
        self.fixture.command('ssh', (
            '#!/bin/sh\n'
            f'echo "ssh $*" >> {self.fixture.calls}\n'
            'cat > /dev/null\n'
            'exit 0\n'))
        self.fixture.calls.write_text('', encoding='utf-8')

    def ssh_call(self):
        # 一次运行只有一条 ssh 记录，而它总是最后写的。整段读取而不是按行读：
        # 候选密码里带着换行，按行切会把同一条命令行拆成好几行。
        text = self.fixture.calls.read_text(encoding='utf-8')
        self.assertTrue(text.startswith('ssh '), text)
        return text.rstrip('\n')

    def run_remote(self, *args):
        env = dict(os.environ)
        env['PATH'] = str(self.fixture.bin) + os.pathsep + env['PATH']
        return subprocess.run(['sh', str(SCRIPT), '--host', 'root@192.168.5.1', *args],
                              env=env, text=True, capture_output=True)

    def test_key_is_passed_with_identities_only(self):
        self.run_remote('--ssh-key', '/keys/id_acrh17')
        call = self.ssh_call()
        self.assertIn('-i /keys/id_acrh17', call)
        # 不限制身份的话 agent 会挨个试手里的钥匙，可能在轮到这个之前就断开。
        self.assertIn('-o IdentitiesOnly=yes', call)
        self.assertIn('root@192.168.5.1', call)

    def test_without_a_key_the_argument_is_absent(self):
        self.run_remote()
        call = self.ssh_call()
        self.assertNotIn('-i ', call)
        self.assertNotIn('IdentitiesOnly', call)

    def test_arguments_are_carried_into_the_remote_command(self):
        self.run_remote('--user', '2021999999', '--server', 'http://172.16.0.9',
                        '--ssh-key', '/keys/k')
        call = self.ssh_call()
        self.assertIn("ACRH17_CAMPUS_USER='2021999999'", call)
        self.assertIn("ACRH17_CAMPUS_SERVER='http://172.16.0.9'", call)
        self.assertIn('sh -s', call)

    def test_candidates_are_carried_into_the_remote_command(self):
        self.run_remote('--password', 'FIRST', '--password', 'SECOND', '--ssh-key', '/k')
        call = self.ssh_call()
        # 两个候选都要到场，顺序不能丢：第一个被拒时才有第二个可试。
        self.assertIn("ACRH17_CAMPUS_PASSWORDS='FIRST\nSECOND\n'", call)

    def test_a_quote_in_an_argument_is_refused(self):
        result = self.run_remote('--user', "2021'; rm -rf /")
        self.assertEqual(result.returncode, 2)
        self.assertIn('单引号', result.stderr)
        self.assertEqual([line for line in self.fixture.log()
                          if line.startswith('ssh ')], [])


class SyncTests(unittest.TestCase):
    """脚本与固件里的 ruijie-refresh-query 探测同一条链路，判据不能各说各话。"""

    def setUp(self):
        self.source = SCRIPT.read_text(encoding='utf-8')
        self.refresh = REFRESH.read_text(encoding='utf-8')

    def test_probe_targets_match_the_firmware_script(self):
        pattern = re.compile(r'(http://[^\s]+)')
        ours = pattern.findall(self.source)
        theirs = pattern.findall(self.refresh)
        shared = [url for url in ('http://1.1.1.1/', 'http://223.5.5.5/')
                  if url in theirs]
        for url in shared:
            self.assertIn(url, ours, f'{url} 应该和 ruijie-refresh-query 一起探')

    def test_portal_page_predicate_matches_the_firmware_script(self):
        self.assertIn('index.jsp', self.refresh)
        self.assertIn('is_portal_page', self.source)
        self.assertIn('*index.jsp*', self.source)

    def test_field_parser_matches_the_firmware_script(self):
        # 两边都必须按 & 切分再取前缀，否则同一个 query 会被读成不同的值。
        for text in (self.source, self.refresh):
            self.assertIn("tr '&' '\\n'", text)
            self.assertIn('s/^$2=//p', text)

    def test_query_validation_matches_the_firmware_script(self):
        for text in (self.source, self.refresh):
            self.assertIn('wlanuserip', text)
            self.assertIn('mac', text)

    def test_probe_timeouts_match_the_firmware_script(self):
        for text in (self.source, self.refresh):
            self.assertIn('--connect-timeout 5', text)
            self.assertIn('--max-time 12', text)

    def test_script_is_executable_and_parses(self):
        self.assertTrue(os.access(SCRIPT, os.X_OK), 'scripts/acrh17-campus-up.sh 需要可执行位')
        subprocess.run(['sh', '-n', str(SCRIPT)], check=True)


if __name__ == '__main__':
    unittest.main()
