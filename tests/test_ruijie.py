"""Exercise real HTTP encoding and captive-portal outcomes without a router."""
import fcntl
import http.server
import json
import os
import shutil
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
import urllib.parse

SCRIPT = Path(__file__).resolve().parents[1] / 'package/ruijie-auth/files/usr/libexec/ruijie-auth'

class Handler(http.server.BaseHTTPRequestHandler):
    code = 204
    result = 'success'
    received = None
    def log_message(self, *args):
        pass
    def do_GET(self):
        type(self).probe_headers = dict(self.headers)
        self.send_response(type(self).code)
        self.end_headers()
    def do_POST(self):
        type(self).received = (dict(self.headers), urllib.parse.parse_qs(self.rfile.read(int(self.headers['Content-Length'])).decode(), keep_blank_values=True))
        self.send_response(200)
        self.end_headers()
        self.wfile.write(json.dumps({'result': type(self).result}).encode())

class PortalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        p = Path(self.temp.name)
        self.script = p / 'auth'
        self.script.write_text(SCRIPT.read_text().replace('/tmp/ruijie-auth', str(p / 'ruijie-auth')))
        cfg = {'server': 'http://127.0.0.1:' + str(self.server.server_port), 'login_path': '/login', 'logout_path': '/logout', 'username': 'user & test', 'password_payload': '+/= encrypted payload', 'cookie': 'SESSION=a; other=b c', 'referer': 'http://example.test/a?b=c', 'query_string': 'a=b&c=d%20e'}
        cfg['check_url'] = cfg['server'] + '/probe'
        cfg['interface'] = 'lo0' if os.uname().sysname == 'Darwin' else 'lo'
        self.env = dict(os.environ, PATH=str(p) + ':' + os.environ['PATH'], TEST_CONFIG=json.dumps(cfg))
        for name, source in {
            'uci': 'import os,json,sys; print(json.loads(os.environ["TEST_CONFIG"]).get(sys.argv[-1].split(".")[-1], ""))',
            'ubus': 'import os; print(os.environ.get("TEST_WAN", \'{"up":true,"ipv4-address":[{"address":"192.0.2.2"}]}\'))',
            'jsonfilter': '''import json,sys
with open(sys.argv[sys.argv.index("-i")+1]) if "-i" in sys.argv else sys.stdin as stream:
    data=json.load(stream)
expr=sys.argv[sys.argv.index("-e")+1]
if expr == "@.result": print(data.get("result", ""))
elif expr == "@.up": print(str(data.get("up", False)).lower())
elif expr == '@["ipv4-address"][0].address': print(next(iter(data.get("ipv4-address", [])), {}).get("address", ""))
elif expr == "@.l3_device": print(data.get("l3_device", ""))
''',
            'logger': 'pass',
            **({'flock': 'import fcntl,sys; fcntl.flock(int(sys.argv[-1]), fcntl.LOCK_EX | fcntl.LOCK_NB)'} if not shutil.which('flock') else {}),
        }.items():
            f = p/name
            f.write_text('#!/usr/bin/env python3\n' + source + '\n')
            f.chmod(0o755)
    def run_auth(self, action):
        return subprocess.run(['sh', str(self.script), action], env=self.env, text=True, capture_output=True)
    def test_captive_portal_is_offline(self):
        for code in [200, 302, 403, 500]:
            Handler.code = code
            result = self.run_auth('status')
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout.strip(), 'offline')
        Handler.code = 204
        self.assertEqual(self.run_auth('status').returncode, 0)
    def test_login_encoding_headers_and_private_status(self):
        Handler.result = 'success'
        Handler.code = 204
        self.assertEqual(self.run_auth('login').returncode, 0)
        headers, data = Handler.received
        self.assertEqual(headers['Cookie'], 'SESSION=a; other=b c')
        self.assertEqual(data['password'], ['+/= encrypted payload'])
        self.assertEqual(data['queryString'], ['a=b&c=d%20e'])
        self.assertEqual(data['userId'], ['user & test'])
        last = Path(self.temp.name)/'ruijie-auth.last'
        self.assertEqual(last.stat().st_mode & 0o777, 0o600)
        self.assertNotIn('encrypted', last.read_text())
    def test_rejected_login_and_logout(self):
        Handler.result = 'fail'
        self.assertNotEqual(self.run_auth('login').returncode, 0)
        Handler.result = 'success'
        self.assertEqual(self.run_auth('logout').returncode, 0)
        self.assertNotIn('password', Handler.received[1])
    def test_successful_logout_is_offline(self):
        Handler.result = 'success'
        self.assertEqual(self.run_auth('logout').returncode, 0)
        state = (Path(self.temp.name)/'ruijie-auth.state').read_text()
        self.assertIn('auth_state=offline', state)

    def test_login_acceptance_does_not_prove_internet(self):
        Handler.result = 'success'
        Handler.code = 302
        self.assertEqual(self.run_auth('login').returncode, 0)
        state = (Path(self.temp.name)/'ruijie-auth.state').read_text()
        self.assertIn('auth_state=offline', state)
        self.assertNotIn('Cookie', Handler.probe_headers)
        self.assertNotIn('Origin', Handler.probe_headers)
        Handler.code = 204

    def test_invalid_server(self):
        cfg = json.loads(self.env['TEST_CONFIG'])
        cfg['server'] = 'file:///etc/passwd'
        self.env['TEST_CONFIG'] = json.dumps(cfg)
        self.assertNotEqual(self.run_auth('login').returncode, 0)

    def test_wan_precheck_skips_portal_request(self):
        (Path(self.temp.name) / 'ubus').write_text(
            '#!/usr/bin/env python3\nprint("{\\"up\\":false,\\"ipv4-address\\":[]}")\n'
        )
        (Path(self.temp.name) / 'ubus').chmod(0o755)
        Handler.received = None
        result = self.run_auth('login')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('no IPv4', result.stdout)
        self.assertIsNone(Handler.received)

    def test_up_without_ipv4_skips_http(self):
        self.env['TEST_WAN'] = '{"up":true,"ipv4-address":[]}'
        Handler.received = None
        self.assertNotEqual(self.run_auth('login').returncode, 0)
        self.assertIsNone(Handler.received)
        self.assertEqual(self.run_auth('status').stdout.strip(), 'offline')


    def test_parallel_authentication_is_rejected(self):
        with open(Path(self.temp.name) / 'ruijie-auth.lock', 'w') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            Handler.received = None
            result = self.run_auth('login')
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('already running', result.stdout)
            self.assertIsNone(Handler.received)


class RecoveryTests(unittest.TestCase):
    def run_loop(self, overrides):
        definitions = SCRIPT.read_text().rsplit('\ncase "$1" in', 1)[0]
        return subprocess.run(['sh', '-c', definitions + '\n' + overrides + '\ndaemon'],
                              capture_output=True, text=True, timeout=5)

    def test_boot_failure_obeys_backoff(self):
        result = self.run_loop('''get() {
case "$1" in
boot_login|auto_reconnect) echo 1;; retry_interval) echo 30;;
check_interval) echo 60;; max_failures) echo 3;; failure_action) echo retry;;
esac
}
wan_ready() { return 0; }
status() { return 1; }
portal() { return 1; }
save_state() { :; }
COUNT=0
sleep() { echo "$1"; COUNT=$((COUNT+1)); [ "$COUNT" -lt 4 ] || exit 0; }
''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.split(), ['30', '45', '60', '60'])

    def test_boot_auth_waits_for_dhcp_without_auto_reconnect(self):
        result = self.run_loop('''get() {
case "$1" in boot_login) echo 1;; auto_reconnect) echo 0;; esac
}
READY=0
wan_ready() { [ "$READY" = 1 ]; }
status() { return 1; }
portal() { echo LOGIN >/dev/fd/3; return 0; }
save_state() { :; }
COUNT=0
sleep() { echo "$1"; READY=1; COUNT=$((COUNT+1)); [ "$COUNT" -lt 2 ] || exit 0; }
exec 3>&1
''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.split(), ['30', 'LOGIN', '60'])

class RecoveryRegressionTests(unittest.TestCase):
    run_loop = RecoveryTests.run_loop
    def test_lock_contention_never_renews_wan(self):
        result = self.run_loop('''get() {
case "$1" in boot_login|auto_reconnect) echo 1;; max_failures) echo 1;; failure_action) echo restart_wan;; esac
}
wan_ready() { return 0; }
status() { return 1; }
portal() { return 75; }
renew_wan() { echo UNEXPECTED_RENEW; }
save_state() { :; }
COUNT=0
sleep() { COUNT=$((COUNT+1)); [ "$COUNT" -lt 3 ] || exit 0; }
''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('UNEXPECTED_RENEW', result.stdout)

    def test_online_probe_refreshes_state(self):
        result = self.run_loop('''get() { echo 1; }
wan_ready() { return 0; }
status() { return 0; }
save_state() { echo "$1"; }
sleep() { exit 0; }
''')
        self.assertEqual(result.stdout.strip(), 'online')

    def test_reauth_waits_for_dhcp(self):
        definitions = SCRIPT.read_text().rsplit('\ncase "$1" in', 1)[0]
        result = subprocess.run(['sh', '-c', definitions + '''
get() { echo 1; }
save_state() { :; }
portal_request() { echo "$1"; }
READY=0
renew_wan_request() { echo renew; READY=0; }
wan_ready() { [ "$READY" -ge 2 ]; }
sleep() { READY=$((READY+1)); }
reauth_request
'''], capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.split(), ['renew', 'login'])

    def test_reauth_dhcp_timeout_stops_login(self):
        definitions = SCRIPT.read_text().rsplit('\ncase "$1" in', 1)[0]
        result = subprocess.run(['sh', '-c', definitions + '''
get() { echo 1; }
save_state() { :; }
portal_request() { echo "$1"; }
renew_wan_request() { return 0; }
wan_ready() { return 1; }
sleep() { :; }
reauth_request
'''], capture_output=True, text=True, timeout=5)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('login', result.stdout)
