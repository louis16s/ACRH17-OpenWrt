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
        block = text.split('if [ -x /etc/init.d/mwan3 ]; then\n', 1)[1].split('\nfi\n', 1)[0]
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

    def test_ntp_servers_replace_the_generated_pool(self):
        # config_generate seeds four openwrt.pool.ntp.org entries before
        # uci-defaults runs, so the list has to be cleared first; appending
        # would leave seven servers with the unreachable pool tried first.
        text = (ROOT / 'files/etc/uci-defaults/90-acrh17').read_text()
        lines = [line for line in text.splitlines() if 'system.ntp.server' in line]
        self.assertTrue(lines, 'no system.ntp.server configuration found')
        mock = '''uci() {
shift
case "$1:$2" in
delete:*) echo "DELETE $2";;
add_list:*) echo "$2";;
esac
}
'''
        result = subprocess.run(['sh', '-c', mock + '\n'.join(lines)],
                                text=True, capture_output=True, check=True)
        self.assertEqual(result.stdout.splitlines(), [
            'DELETE system.ntp.server',
            'system.ntp.server=ntp.aliyun.com',
            'system.ntp.server=ntp.tencent.com',
            'system.ntp.server=pool.ntp.org',
        ])

    def test_unused_services_are_disabled_ahead_of_the_guard(self):
        # /etc/rc.d appears in no keep.d entry and nand_do_upgrade deletes and
        # recreates the rootfs_data volume, so a disable done here is lost on
        # every upgrade while the guard below returns early. watchcat would then
        # ping 8.8.8.8 every 6h and force a reboot, so the disables must sit
        # ahead of the guard to be re-applied whenever this script reappears.
        text = (ROOT / 'files/etc/uci-defaults/90-acrh17').read_text()
        before_guard = text.split("uci -q set network.lan.ipaddr=", 1)[0]
        with tempfile.TemporaryDirectory() as d:
            Path(d, 'init.d').mkdir()
            for service in ('watchcat', 'ddns', 'mwan3', 'smartdns', 'ua3f'):
                script = Path(d, 'init.d', service)
                script.write_text(f'echo "{service} $1"\n')
                script.chmod(0o755)
            mock = 'chmod() { :; }\nuci() { :; }\nawk() { return 0; }\n'
            body = '\n'.join(before_guard.replace('/etc/init.d/', './init.d/').splitlines()[1:])
            result = subprocess.run(['sh', '-c', mock + body], cwd=d,
                                    text=True, capture_output=True, check=True)
        disabled = {line.split()[0] for line in result.stdout.splitlines()
                    if line.endswith(' disable')}
        self.assertEqual(disabled, {'watchcat', 'ddns', 'mwan3'})

    def test_p910nd_driver_blobs_survive_upgrade(self):
        # The p910nd hotplug script appends /opt/p910nd_drivers to
        # /etc/sysupgrade.conf, but that file is itself in no keep.d entry, so
        # the entry is cleared by the first upgrade and the blobs are dropped by
        # the next one. Keep the directory directly.
        keep = (ROOT / 'files/lib/upgrade/keep.d/acrh17').read_text()
        # sysupgrade strips comments and blank lines before calling find, so the
        # path has to survive that filter.
        listed = {line for line in keep.splitlines()
                  if line.strip() and not line.startswith('#')}
        self.assertIn('/opt/p910nd_drivers', listed)

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
