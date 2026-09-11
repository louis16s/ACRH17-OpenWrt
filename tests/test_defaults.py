"""Exercise UCI list expansion and package exclusion checks."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

class DefaultsTests(unittest.TestCase):
    def test_smartdns_is_enabled_on_ipv4_only_listener(self):
        text = (ROOT / 'files/etc/uci-defaults/90-acrh17').read_text()
        self.assertIn("uci -q set smartdns.@smartdns[0].enabled='1'", text)
        self.assertIn("uci -q set smartdns.@smartdns[0].port='6053'", text)
        self.assertIn("uci -q set smartdns.@smartdns[0].ipv6_server='0'", text)

    def test_each_existing_uplink_receives_all_probe_targets(self):
        text = (ROOT / 'files/etc/uci-defaults/90-acrh17').read_text()
        block = text.split('if [ -x /etc/init.d/mwan3 ]; then\n', 1)[1].split('/etc/init.d/mwan3 disable', 1)[0]
        mock = '''uci() {
shift
case "$1:$2" in
get:acrh17.settings.mwan3_interface) echo 'wan wanb usbwan';;
get:acrh17.settings.mwan3_probe_ip) echo '223.5.5.5 119.29.29.29 114.114.114.114';;
show:mwan3.usbwan) return 1;;
get:*.family) echo ipv4;;
add_list:*) echo "$2";;
esac
}
'''
        result = subprocess.run(['sh', '-c', mock + block], text=True, capture_output=True, check=True)
        self.assertEqual(set(result.stdout.splitlines()), {
            f'mwan3.{interface}.track_ip={ip}' for interface in ('wan', 'wanb')
            for ip in ('223.5.5.5', '119.29.29.29', '114.114.114.114')})

    def test_excluded_package_cannot_reappear(self):
        with tempfile.TemporaryDirectory() as d:
            requested, resolved = Path(d) / 'requested', Path(d) / 'resolved'
            requested.write_text('# CONFIG_PACKAGE_mwan3 is not set\n')
            resolved.write_text('CONFIG_PACKAGE_mwan3=y\n')
            result = subprocess.run(['python3', str(ROOT / 'scripts/verify-config.py'), str(requested), str(resolved)], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Excluded package selected: mwan3', result.stderr)
