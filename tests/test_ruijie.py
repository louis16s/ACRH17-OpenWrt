"""Exercise real HTTP encoding and captive-portal outcomes without a router."""
import fcntl
import http.server
import json
import os
import re
import shutil
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import unittest
import urllib.parse

SCRIPT = Path(__file__).resolve().parents[1] / 'package/ruijie-auth/files/usr/libexec/ruijie-auth'
PASSWORD_SCRIPT = Path(__file__).resolve().parents[1] / 'package/ruijie-auth/files/usr/libexec/ruijie-password'
REFRESH_SCRIPT = Path(__file__).resolve().parents[1] / 'package/ruijie-auth/files/usr/libexec/ruijie-refresh-query'

class Handler(http.server.BaseHTTPRequestHandler):
    code = 204
    result = 'success'
    # Raw override for the POST body, used to imitate a portal that answers
    # with something that is not the expected JSON at all.
    body = None
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
        payload = type(self).body
        if payload is None:
            payload = json.dumps({'result': type(self).result})
        self.wfile.write(payload.encode())

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
        Handler.code = 204
        Handler.result = 'success'
        Handler.body = None
        Handler.received = None
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
        # A timeout, so a lock regression fails the suite instead of hanging it:
        # flock without -n blocks until the other holder exits, and on CI there is
        # nothing to kill it.
        return subprocess.run(['sh', str(self.script), action], env=self.env,
                              text=True, capture_output=True, timeout=30)
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


    def test_curlrc_cannot_override_portal_request(self):
        (Path(self.temp.name) / '.curlrc').write_text('header = "X-Curlrc: must-not-send"\n')
        self.env['CURL_HOME'] = self.temp.name
        self.assertEqual(self.run_auth('login').returncode, 0)
        self.assertNotIn('X-Curlrc', Handler.received[0])

    def test_portal_rejection_is_named_apart_from_an_unreadable_answer(self):
        # The password logic rolls back only on the exact rejection string, so
        # these two outcomes must not collapse into one message. A 302 or an
        # HTML error page after the WAN address changed is not a rejection.
        Handler.result = 'fail'
        self.assertNotEqual(self.run_auth('login').returncode, 0)
        last = (Path(self.temp.name)/'ruijie-auth.last').read_text()
        self.assertIn('portal rejected request', last)
        self.assertNotIn('unexpected portal response', last)

        Handler.body = '<html><body>login required</body></html>'
        self.assertNotEqual(self.run_auth('login').returncode, 0)
        last = (Path(self.temp.name)/'ruijie-auth.last').read_text()
        self.assertIn('unexpected portal response', last)
        self.assertNotIn('portal rejected request', last)


    def test_renew_and_clear_share_authentication_lock(self):
        state = Path(self.temp.name) / 'ruijie-auth.state'
        state.write_text('auth_state=online\n')
        with open(Path(self.temp.name) / 'ruijie-auth.lock', 'w') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            for action in ('renew-wan', 'clear'):
                result = self.run_auth(action)
                self.assertEqual(result.returncode, 75)
                self.assertIn('already running', result.stdout)
            self.assertTrue(state.exists())


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

    def _run_renew(self, wan_ready_body):
        # ifup returns long before DHCP installs an address. Reporting success
        # on a bare ifup is what left the WAN with no IPv4 while the UI still
        # said the renew had worked.
        definitions = SCRIPT.read_text().rsplit('\ncase "$1" in', 1)[0]
        return subprocess.run(['sh', '-c', definitions + '''
get() { echo wan; }
ifdown() { return 0; }
ifup() { return 0; }
sleep() { :; }
logger() { :; }
save_state() { echo "STATE:$2"; }
wan_ready() { %s; }
renew_wan_request
echo "rc=$?"
''' % wan_ready_body], capture_output=True, text=True, timeout=10)

    def test_renew_wan_needs_a_lease_before_reporting_success(self):
        result = self._run_renew('return 1')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('rc=1', result.stdout)
        self.assertNotIn('STATE:pending', result.stdout)

    def test_renew_wan_reports_success_once_the_lease_is_back(self):
        result = self._run_renew('return 0')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('rc=0', result.stdout)
        self.assertIn('STATE:pending', result.stdout)


class PasswordRollbackTests(unittest.TestCase):
    """Repeated changes must never put the original password out of reach, and
    only the portal actually turning a login down may spend the rollback point.

    Runs the real script against stubs for uci/ubus and for the two helpers it
    shells out to, so the state machine is exercised rather than re-implemented
    in the test.
    """

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name)
        self.state_file = self.dir / 'uci-state.json'

        # Point every absolute path the script hardcodes at the sandbox.
        self.script = self.dir / 'pw'
        self.script.write_text(
            PASSWORD_SCRIPT.read_text()
            .replace('/usr/libexec/ruijie-auth', str(self.dir / 'auth'))
            .replace('/etc/init.d/ruijie-auth', str(self.dir / 'initscript'))
            .replace('/tmp/ruijie-auth', str(self.dir / 'ruijie-auth'))
        )

        # The exit status matters as much as the value: `uci -q get` exits 1 for
        # an option that does not exist and 0 for one that exists with an empty
        # value, and the scripts use that difference to tell "never written" from
        # "written empty". A stub that always exits 0 cannot express it. (uci's
        # cli.c: a failed lookup returns 1, CMD_GET on a found option returns 0,
        # and -q only suppresses the error message.)
        state_path = repr(str(self.state_file))
        (self.dir / 'uci').write_text(
            '#!/usr/bin/env python3\n'
            'import json, os, sys\n'
            'path = ' + state_path + '\n'
            'state = json.load(open(path)) if os.path.exists(path) else {}\n'
            'args = [a for a in sys.argv[1:] if a != "-q"]\n'
            'if args and args[0] == "get":\n'
            '    key = args[1].rsplit(".", 1)[-1]\n'
            '    if key not in state:\n'
            '        sys.exit(1)\n'
            '    print(state[key])\n'
            'elif args and args[0] == "set":\n'
            '    key, _, value = args[1].partition("=")\n'
            '    state[key.rsplit(".", 1)[-1]] = value\n'
            '    json.dump(state, open(path, "w"))\n'
        )
        (self.dir / 'ubus').write_text(
            '#!/usr/bin/env python3\n'
            'print(\'{"up":true,"ipv4-address":[{"address":"192.0.2.2"}]}\')\n'
        )
        # wan_ready parses the ubus status through jsonfilter, so without this
        # every set would stop at "no IPv4" and never reach the portal probe.
        (self.dir / 'jsonfilter').write_text(
            '#!/usr/bin/env python3\n'
            'import json, sys\n'
            'with open(sys.argv[sys.argv.index("-i")+1]) if "-i" in sys.argv else sys.stdin as stream:\n'
            '    data = json.load(stream)\n'
            'expr = sys.argv[sys.argv.index("-e")+1]\n'
            'if expr == "@.up":\n'
            '    print(str(data.get("up", False)).lower())\n'
            'elif expr == \'@["ipv4-address"][0].address\':\n'
            '    print(next(iter(data.get("ipv4-address", [])), {}).get("address", ""))\n'
        )
        (self.dir / 'initscript').write_text('#!/bin/sh\nexit 0\n')
        (self.dir / 'logger').write_text('#!/bin/sh\nexit 0\n')
        for name in ('uci', 'ubus', 'jsonfilter', 'initscript', 'logger'):
            (self.dir / name).chmod(0o755)

        self.env = dict(os.environ, PATH=str(self.dir) + ':' + os.environ['PATH'])

    def write_state(self, **values):
        self.state_file.write_text(json.dumps(values))

    def read_state(self):
        if not self.state_file.exists():
            return {}
        return json.loads(self.state_file.read_text())

    def run_pw(self, *args, auth_rc=1, auth_last='', write_last=True):
        """Run ruijie-password with a stub auth that returns auth_rc and leaves
        auth_last where the script reads it.

        write_last=False models the attempts that never reach the portal: the
        real ruijie-auth has several paths that return without writing the file
        at all, which is exactly how a previous run's answer gets read as this
        run's verdict.
        """
        last_path = repr(str(self.dir / 'ruijie-auth.last'))
        write = ('printf "%s\\n" "$AUTH_LAST" > ' + last_path + '\n') if write_last else ''
        (self.dir / 'auth').write_text(
            '#!/bin/sh\n' + write + 'exit "${AUTH_RC:-1}"\n'
        )
        (self.dir / 'auth').chmod(0o755)
        env = dict(self.env, AUTH_RC=str(auth_rc), AUTH_LAST=auth_last)
        # ruijie-password reports in Chinese, so decode as UTF-8 explicitly
        # rather than relying on whatever locale the test runner happens to
        # have; macOS defaults to US-ASCII when LANG is unset.
        return subprocess.run(['sh', str(self.script)] + list(args),
                              env=env, text=True, encoding='utf-8',
                              capture_output=True, timeout=60)

    def test_repeated_changes_never_lose_the_original_password(self):
        # password_prev moves with every set, so after a second change the
        # value the router shipped with is no longer reachable through it --
        # and a set during an outage exits without verifying, which is exactly
        # when someone tries again.
        self.write_state(password_payload='P0-original')
        for value in ('NEW-1', 'NEW-2', 'NEW-3'):
            # 2, not 0: the value was written but --no-test means nothing proved
            # it. The exit status has to keep those apart.
            self.assertEqual(self.run_pw('set', value, '--no-test').returncode, 2)
        state = self.read_state()
        self.assertEqual(state['password_payload'], 'NEW-3')
        self.assertEqual(state['password_prev'], 'NEW-2')
        self.assertEqual(state['password_original'], 'P0-original')

    def test_revert_original_restores_the_first_value_and_keeps_the_anchor(self):
        self.write_state(password_payload='P0-original')
        self.run_pw('set', 'NEW-1', '--no-test')
        self.run_pw('set', 'NEW-2', '--no-test')

        self.assertEqual(self.run_pw('revert', '--original').returncode, 0)
        state = self.read_state()
        self.assertEqual(state['password_payload'], 'P0-original')
        self.assertEqual(state['password_original'], 'P0-original')

        # A plain revert still brings back the value we just left.
        self.run_pw('revert')
        state = self.read_state()
        self.assertEqual(state['password_payload'], 'NEW-2')
        self.assertEqual(state['password_original'], 'P0-original')

    def test_only_a_portal_rejection_spends_the_rollback_point(self):
        for last, expected in [
            ('login: portal rejected request', 'P0-original'),
            ('login: unexpected portal response', 'NEW-1'),
            ('login: HTTP or network error', 'NEW-1'),
            ('logout: portal reported success', 'NEW-1'),
        ]:
            with self.subTest(last=last):
                self.write_state(password_payload='P0-original')
                self.run_pw('set', 'NEW-1', auth_rc=1, auth_last=last)
                self.assertEqual(self.read_state()['password_payload'], expected)

    def test_failure_message_prints_the_whole_path(self):
        # A bare $VAR followed by a non-ASCII byte lets a C-locale shell absorb
        # that byte into the variable name: the expansion goes empty and the
        # trailing bytes come out as invalid UTF-8. run_pw decodes as UTF-8, so
        # this also fails outright if the message is not well formed.
        self.write_state(password_payload='P0-original')
        result = self.run_pw('set', 'NEW-1', auth_rc=1,
                             auth_last='logout: portal reported success')
        self.assertIn(str(self.dir / 'ruijie-auth.last'), result.stdout)

    def test_a_flag_is_never_stored_as_a_password(self):
        # `set --no-test` with the flag first and no password would otherwise
        # pass the non-empty check and store the literal string.
        self.write_state(password_payload='P0-original')
        result = self.run_pw('set', '--no-test')
        self.assertNotEqual(result.returncode, 0)
        state = self.read_state()
        self.assertEqual(state['password_payload'], 'P0-original')

    def test_a_stale_rejection_never_spends_the_rollback_point(self):
        # ruijie-auth has paths that return without writing $LAST at all: no WAN
        # address, a server that is not a URL, an empty userId, no temp file.
        # Reading the file anyway hands the previous attempt's answer to this one,
        # and a stale "portal rejected request" then rolls back a password that
        # was never put to the portal -- while telling the user the portal turned
        # it down.
        self.write_state(password_payload='P0-original')
        (self.dir / 'ruijie-auth.last').write_text('login: portal rejected request\n')
        result = self.run_pw('set', 'NEW-1', auth_rc=1, write_last=False)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn('未能确认登录结果', result.stdout)
        self.assertNotIn('门户拒绝', result.stdout)
        state = self.read_state()
        self.assertEqual(state['password_payload'], 'NEW-1')
        self.assertEqual(state['password_prev'], 'P0-original')

    def test_an_interrupt_still_brings_the_authentication_service_back(self):
        # The verification window stops the daemon and then waits on a portal
        # round trip. procd respawns a process that crashed, not an instance that
        # was stopped on purpose, so an interrupt inside that window used to leave
        # the campus link down until somebody started the service by hand.
        log = self.dir / 'initscript.log'
        (self.dir / 'initscript').write_text(
            '#!/bin/sh\nprintf "%s\\n" "$1" >> ' + repr(str(log)) + '\nexit 0\n')
        (self.dir / 'initscript').chmod(0o755)
        # Long enough that the signal is certain to land inside the window.
        (self.dir / 'auth').write_text('#!/bin/sh\nsleep 5\nexit 1\n')
        (self.dir / 'auth').chmod(0o755)
        self.write_state(password_payload='P0-original')

        process = subprocess.Popen(['sh', str(self.script), 'set', 'NEW-1'],
                                   env=self.env, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, encoding='utf-8',
                                   errors='replace')
        self.addCleanup(process.kill)
        deadline = time.monotonic() + 20
        calls = []
        while 'stop' not in calls and time.monotonic() < deadline:
            time.sleep(0.05)
            calls = log.read_text().split() if log.exists() else []
        self.assertIn('stop', calls, 'the daemon was never stopped')

        process.terminate()
        try:
            process.communicate(timeout=30)
        except subprocess.TimeoutExpired:
            process.kill()
            self.fail('the interrupt left the password script running')
        # The shell defers a trap until the foreground child exits, so the file
        # has to be read after the process is gone rather than when it is written.
        self.assertIn('start', log.read_text().split())

    def test_a_mistyped_flag_never_silently_reverts(self):
        # `revert --orig` used to fall through to the plain revert, swapping in
        # the *previous* password while the user believed they had asked for the
        # original one. Both paths print nothing but a mask, so nothing on screen
        # showed which of the two had happened.
        for flag in ('--orig', '--ORIGINAL', 'garbage'):
            with self.subTest(flag=flag):
                self.write_state(password_payload='P0-original', password_prev='FALLBACK',
                                 password_original='ANCHOR')
                result = self.run_pw('revert', flag)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.read_state()['password_payload'], 'P0-original')

    def test_the_anchor_lands_on_the_first_change_not_the_second(self):
        # The shipped payload is empty, so an emptiness test anchors one change
        # too late -- onto a value that had itself just been replaced, and in the
        # worst case onto one the portal had already turned down.
        self.write_state(password_payload='')
        self.assertEqual(self.run_pw('set', 'NEW-1', '--no-test').returncode, 2)
        state = self.read_state()
        self.assertIn('password_original', state)
        self.assertEqual(state['password_original'], '')
        self.assertEqual(self.run_pw('set', 'NEW-2', '--no-test').returncode, 2)
        self.assertEqual(self.read_state()['password_original'], '')

    def test_a_non_ascii_password_is_described_without_half_a_character(self):
        # tail -c 2 takes two bytes, which is half a character for anything that
        # is not ASCII: the terminal receives a sequence it cannot decode, and the
        # byte count is read as a character count. Both are wrong, about the one
        # value on the page nobody can see.
        self.write_state(password_payload='')
        result = self.run_pw('set', '密码密码', '--no-test')
        self.assertIn('含非 ASCII 字符（12 字节）', result.stdout)

        self.write_state(password_payload='')
        result = self.run_pw('set', 'passAs', '--no-test')
        self.assertIn('6 位，末两位 As', result.stdout)

    def test_written_but_unverified_is_not_reported_as_success(self):
        # 0 has to mean "the portal accepted this value". Reporting a write that
        # nothing proved as success is how a password nobody has verified comes to
        # look verified.
        self.write_state(password_payload='P0-original')
        self.assertEqual(self.run_pw('set', 'NEW-1', '--no-test').returncode, 2)

        # No IPv4 on the WAN: the probe is skipped and the value is still stored.
        online = (self.dir / 'ubus').read_text()
        (self.dir / 'ubus').write_text("#!/usr/bin/env python3\nprint('{\"up\":false}')\n")
        self.write_state(password_payload='P0-original')
        result = self.run_pw('set', 'NEW-1')
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertEqual(self.read_state()['password_payload'], 'NEW-1')

        # A real acceptance is the one case that exits 0.
        (self.dir / 'ubus').write_text(online)
        self.write_state(password_payload='P0-original')
        result = self.run_pw('set', 'NEW-1', auth_rc=0,
                             auth_last='login: portal reported success')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_reverting_onto_an_empty_value_keeps_the_rollback_point(self):
        # The value being replaced is moved into the rollback point so a plain
        # revert can bring it back -- but an empty current value is not a
        # password, and storing it throws away the only password still known to
        # work. The LuCI page can leave the payload empty (clearing the field
        # saves without recording anything), which is exactly the state
        # `revert --original` is for.
        self.write_state(password_payload='', password_prev='FALLBACK',
                         password_original='ANCHOR')
        result = self.run_pw('revert', '--original')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        state = self.read_state()
        self.assertEqual(state['password_payload'], 'ANCHOR')
        self.assertEqual(state['password_prev'], 'FALLBACK')

        self.write_state(password_payload='', password_prev='FALLBACK')
        self.assertEqual(self.run_pw('revert').returncode, 0)
        state = self.read_state()
        self.assertEqual(state['password_payload'], 'FALLBACK')
        self.assertEqual(state['password_prev'], 'FALLBACK')

    def test_the_original_anchor_is_reported_once_it_exists_empty(self):
        # "Never changed" and "changed to nothing" are different states, and the
        # shipped payload is the second one: the option exists with an empty
        # value. revert --original has no value to put back, and must say so
        # rather than swap in the empty one.
        self.write_state(password_payload='', password_original='')
        result = self.run_pw('revert', '--original')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('最初密码是空的', result.stdout)


class RefreshQueryTests(unittest.TestCase):
    """ruijie-refresh-query 抓到 query 时必须把同一个 Location 的 origin 一起写成 server。

    刷机重建 rootfs_data 之后 server 和 query_string 一起回到空值，而 ruijie-auth
    没有 server 就连请求都不发；两者又都是门户按收到请求的地址加密的，只能在路由器
    上现抓——所以它们是同一份 302 的两半，写入与回滚都得成对。这里用桩件替掉
    uci/ubus/curl/logger 和它调用的 ruijie-auth，真在跑的是脚本自己的分支：探测、
    门户判据、写 UCI、失败回滚。
    """

    QUERY = 'wlanuserip=8A3F21&wlanacname=SCAU&mac=77C1E0&t=1757890000'
    # 旧值刻意非空且与抓到的不同：这样「server 被改写成门户地址」才是被证明的，
    # 而不是撞上一个原本就空着的字段。
    OLD_QUERY = 'wlanuserip=OLD&mac=OLD'
    OLD_SERVER = 'http://10.0.0.9'

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name)
        self.state_file = self.dir / 'uci-state.json'
        self.seen_file = self.dir / 'seen-by-auth.json'
        self.location = self.dir / 'location'
        self.auth_rc = self.dir / 'auth-rc'

        # 设备上的绝对路径在沙箱里都要有对应物：state 文件、以及 reauth 调的那个
        # ruijie-auth。
        self.script = self.dir / 'refresh'
        self.script.write_text(
            REFRESH_SCRIPT.read_text(encoding='utf-8')
            .replace('/usr/libexec/ruijie-auth', str(self.dir / 'auth'))
            .replace('/tmp/ruijie-auth', str(self.dir / 'ruijie-auth'))
        )

        # 状态型的 uci 桩：get 对不存在的选项退出 1（真 uci 就是这样，脚本靠这个
        # 区分「没写过」和「写成空」），set 落盘，commit 无所谓——回滚是否真的把值
        # 写回去了，要看得到才行。
        (self.dir / 'uci').write_text(
            '#!/usr/bin/env python3\n'
            'import json, os, sys\n'
            'path = ' + repr(str(self.state_file)) + '\n'
            'state = json.load(open(path)) if os.path.exists(path) else {}\n'
            'args = [a for a in sys.argv[1:] if a != "-q"]\n'
            'if args and args[0] == "get":\n'
            '    key = args[1].rsplit(".", 1)[-1]\n'
            '    if key not in state:\n'
            '        sys.exit(1)\n'
            '    print(state[key])\n'
            'elif args and args[0] == "set":\n'
            '    key, _, value = args[1].partition("=")\n'
            '    state[key.rsplit(".", 1)[-1]] = value\n'
            '    json.dump(state, open(path, "w"))\n'
        )
        (self.dir / 'ubus').write_text(
            '#!/usr/bin/env python3\n'
            'import json\n'
            'print(json.dumps({"up": True, "l3_device": "eth0.2",\n'
            '                  "ipv4-address": [{"address": "172.16.67.126"}]}))\n'
        )
        (self.dir / 'jsonfilter').write_text(
            '#!/usr/bin/env python3\n'
            'import json,sys\n'
            'with open(sys.argv[sys.argv.index("-i")+1]) if "-i" in sys.argv else sys.stdin as stream:\n'
            '    data=json.load(stream)\n'
            'expr=sys.argv[sys.argv.index("-e")+1]\n'
            'if expr == "@.up": print(str(data.get("up", False)).lower())\n'
            'elif expr == \'@["ipv4-address"][0].address\': print(next(iter(data.get("ipv4-address", [])), {}).get("address", ""))\n'
            'elif expr == "@.l3_device": print(data.get("l3_device", ""))\n'
            'elif expr == "@.result": print(data.get("result", ""))\n'
        )
        (self.dir / 'logger').write_text('#!/bin/sh\nexit 0\n')
        # 探针打的三个地址在夹具里不重要，重要的是 Location 这个头——没有它就是
        # 「没被拦」，脚本应当拒绝往下走。
        (self.dir / 'curl').write_text(
            '#!/usr/bin/env python3\n'
            'import pathlib, sys\n'
            'spec = pathlib.Path(' + repr(str(self.location)) + ')\n'
            'if not spec.exists():\n'
            '    sys.exit(7)\n'
            'print("HTTP/1.1 302 Found")\n'
            'print("Location: " + spec.read_text())\n'
        )
        # reauth 一进来就把当时的 UCI 抄一份：回滚之后旧值回来了，光看结果分不出
        # 「写过又回滚」和「根本没写」，那一份在认证发起时刻的配置才是证据。
        (self.dir / 'auth').write_text(
            '#!/usr/bin/env python3\n'
            'import pathlib, shutil, sys\n'
            'shutil.copyfile(' + repr(str(self.state_file)) + ', ' + repr(str(self.seen_file)) + ')\n'
            'sys.exit(int(pathlib.Path(' + repr(str(self.auth_rc)) + ').read_text().strip()))\n'
        )
        for name in ('uci', 'ubus', 'jsonfilter', 'logger', 'curl', 'auth'):
            (self.dir / name).chmod(0o755)

        self.env = dict(os.environ, PATH=str(self.dir) + os.pathsep + os.environ['PATH'])
        self.write_state(wan_interface='wan', interface='',
                         server=self.OLD_SERVER, query_string=self.OLD_QUERY)
        self.set_auth_rc(0)

    # ---- 夹具

    def write_state(self, **values):
        self.state_file.write_text(json.dumps(values), encoding='utf-8')

    def read_state(self):
        return json.loads(self.state_file.read_text(encoding='utf-8'))

    def seen_by_auth(self):
        return json.loads(self.seen_file.read_text(encoding='utf-8'))

    def set_redirect(self, location):
        self.location.write_text(location, encoding='utf-8')

    def set_auth_rc(self, rc):
        self.auth_rc.write_text(str(rc), encoding='utf-8')

    def run_refresh(self, *args):
        # 脚本打印中文（旧 query / 门户地址），解码按 UTF-8 显式指定，不靠
        # runner 恰好是什么 locale。
        return subprocess.run(['sh', str(self.script)] + list(args), env=self.env,
                              text=True, encoding='utf-8', capture_output=True, timeout=30)

    # ---- 用例

    def test_the_portal_origin_is_written_as_the_server(self):
        self.set_redirect('http://172.16.0.1/eportal/index.jsp?' + self.QUERY)
        result = self.run_refresh()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        state = self.read_state()
        self.assertEqual(state['query_string'], self.QUERY)
        self.assertEqual(state['server'], 'http://172.16.0.1')
        # 门户地址不是秘密，抓到就该看得见（query 照旧只打值）。
        self.assertIn('http://172.16.0.1', result.stdout)

    def test_an_explicit_port_survives_in_the_origin(self):
        self.set_redirect('http://172.16.0.1:8080/eportal/index.jsp?' + self.QUERY)
        self.assertEqual(self.run_refresh().returncode, 0)
        self.assertEqual(self.read_state()['server'], 'http://172.16.0.1:8080')

    def test_an_https_origin_keeps_its_scheme(self):
        self.set_redirect('https://portal.scau.edu.cn/eportal/index.jsp?' + self.QUERY)
        self.assertEqual(self.run_refresh().returncode, 0)
        self.assertEqual(self.read_state()['server'], 'https://portal.scau.edu.cn')

    def test_a_redirect_that_is_not_a_portal_page_leaves_the_server_alone(self):
        # 透明代理和上级网关也会 302，拿它们的 origin 当 server 会把认证发到一台
        # 不认识这台机器的服务器上。判据只认 index.jsp，这里顺带钉住旧值不动。
        self.set_redirect('http://192.168.1.1/login.html')
        result = self.run_refresh()
        self.assertNotEqual(result.returncode, 0)
        state = self.read_state()
        self.assertEqual(state['server'], self.OLD_SERVER)
        self.assertEqual(state['query_string'], self.OLD_QUERY)

    def test_capture_only_stores_the_origin_too(self):
        # capture 不登录，但门户地址是「抓」的一部分：不然抓完还要人再填一次，
        # 而那正是刷机后认证发不出去的原因。
        self.set_redirect('http://172.16.0.1/eportal/index.jsp?' + self.QUERY)
        result = self.run_refresh('capture')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.read_state()['server'], 'http://172.16.0.1')

    def test_a_failed_reauth_rolls_the_server_back_with_the_query(self):
        self.set_redirect('http://172.16.0.1:8080/eportal/index.jsp?' + self.QUERY)
        self.set_auth_rc(1)
        result = self.run_refresh()
        self.assertNotEqual(result.returncode, 0)
        # 发出去认证的必须是这一对：新串配新门户。
        self.assertEqual(self.seen_by_auth()['query_string'], self.QUERY)
        self.assertEqual(self.seen_by_auth()['server'], 'http://172.16.0.1:8080')
        # 被门户拒了之后两个字段一起回到旧值，不能只回滚一半。
        state = self.read_state()
        self.assertEqual(state['query_string'], self.OLD_QUERY)
        self.assertEqual(state['server'], self.OLD_SERVER)

    def test_the_rollback_puts_back_a_server_that_was_empty(self):
        # 刚刷完机就是这样：server 空着。回滚只把 query 放回去的话，留下的是
        # 「旧串 + 只认新串的门户」，比什么都不做更糟。
        self.write_state(wan_interface='wan', interface='',
                         server='', query_string=self.OLD_QUERY)
        self.set_redirect('http://172.16.0.1/eportal/index.jsp?' + self.QUERY)
        self.set_auth_rc(1)
        self.assertNotEqual(self.run_refresh().returncode, 0)
        self.assertEqual(self.seen_by_auth()['server'], 'http://172.16.0.1')
        self.assertEqual(self.read_state()['server'], '')


class ShellHygieneTests(unittest.TestCase):
    """The shell scripts here must not contain a bare $VAR whose very next byte
    is non-ASCII.

    A shell with a multibyte ctype -- bash or dash under a UTF-8 locale -- reads
    the bytes after a variable name as part of it, so

        echo "详情见 $LAST；网络恢复后..."

    expands $LAST followed by a character nobody asked for and the variable comes
    out empty. The router never sees it (musl's isalpha is ASCII-only whatever the
    locale says), which is why this needs a scan rather than a test run: it is
    only reachable on a development machine. ${VAR} is safe everywhere, and this
    repository is full of Chinese output next to variables.
    """

    VAR_BEFORE_NON_ASCII = re.compile(rb'\$[A-Za-z_][A-Za-z0-9_]*(?=[\x80-\xff])')

    def test_no_expansion_is_followed_by_a_non_ascii_byte(self):
        root = Path(__file__).resolve().parents[1]
        offenders = []
        checked = 0
        for path in sorted(root.rglob('*')):
            if not path.is_file() or any(part.startswith('.') for part in path.parts):
                continue
            data = path.read_bytes()
            shebang = data.split(b'\n', 1)[0]
            if not shebang.startswith(b'#!') or b'sh' not in shebang:
                continue
            checked += 1
            for number, line in enumerate(data.split(b'\n'), 1):
                for match in self.VAR_BEFORE_NON_ASCII.finditer(line):
                    offenders.append('%s:%d: %s' % (path.relative_to(root), number,
                                                    match.group().decode('ascii')))
        # A scan that stops matching anything passes for the wrong reason.
        self.assertGreater(checked, 5, 'no shell scripts were scanned')
        self.assertEqual(offenders, [])
