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

    def test_build_cache_is_enabled(self):
        config = (ROOT / 'configs/acrh17.config').read_text()
        self.assertIn('CONFIG_DEVEL=y', config)
        self.assertIn('CONFIG_CCACHE=y', config)

    def test_required_build_and_feature_symbols_cannot_disappear(self):
        for symbol in ('CONFIG_IB', 'CONFIG_IB_STANDALONE', 'CONFIG_CCACHE',
                       'CONFIG_LUCI_LANG_zh_Hans',
                       'CONFIG_PACKAGE_luci-app-turboacc_INCLUDE_OFFLOADING'):
            with self.subTest(symbol=symbol), tempfile.TemporaryDirectory() as d:
                requested, resolved = Path(d) / 'requested', Path(d) / 'resolved'
                requested.write_text(symbol + '=y\n')
                resolved.write_text('')
                result = subprocess.run(['python3', str(ROOT / 'scripts/verify-config.py'), str(requested), str(resolved)], capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(symbol, result.stderr)

    def test_retained_installation_skips_factory_defaults(self):
        text = (ROOT / 'files/etc/uci-defaults/90-acrh17').read_text()
        guard = text.split("uci -q set network.lan.ipaddr=", 1)[0]
        for marker, password in ((1, 0), (0, 1), (0, 0)):
            mock = """chmod() { :; }
uci() { case "$1:$2:$3" in -q:get:acrh17.settings.defaults_applied) echo MARKER;; esac; }
awk() { return PASSWORD; }
""".replace('MARKER', str(marker)).replace('PASSWORD', '0' if password else '1')
            result = subprocess.run(['sh', '-c', mock + guard + '\necho APPLY_FACTORY_DEFAULTS'], capture_output=True, text=True, check=True)
            self.assertEqual('APPLY_FACTORY_DEFAULTS' in result.stdout, not (marker or password))
