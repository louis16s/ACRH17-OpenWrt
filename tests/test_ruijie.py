"""Exercise real HTTP encoding and captive-portal outcomes without a router."""
import http.server
import json
import os
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
        self.env = dict(os.environ, PATH=str(p) + ':' + os.environ['PATH'], TEST_CONFIG=json.dumps(cfg))
        for name, source in {
            'uci': 'import os,json,sys; print(json.loads(os.environ["TEST_CONFIG"]).get(sys.argv[-1].split(".")[-1], ""))',
            'ubus': 'print("{\\"up\\":true,\\"ipv4-address\\":[{\\"address\\":\\"192.0.2.2\\"}]}")',
            'jsonfilter': 'import json,sys; data=json.load(open(sys.argv[sys.argv.index("-i")+1])) if "-i" in sys.argv else json.load(sys.stdin); expr=" ".join(sys.argv); print(data.get("result", "") if "-i" in sys.argv else (1 if "@.up" in expr and data.get("up") else data.get("ipv4-address", [{}])[0].get("address", "")))',
            'logger': 'pass',
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
