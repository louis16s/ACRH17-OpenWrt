from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

class TurboAccRuntimeTests(unittest.TestCase):
    def test_offload_guard_retains_bbr_and_avoids_dns_restart(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / 'root/etc/init.d/turboacc'
            path.parent.mkdir(parents=True)
            path.write_text('''inital_conf() {
config_load turboacc
config_get sw_flow config sw_flow 0
config_get hw_flow config hw_flow 0
config_get sfe_flow config sfe_flow 0
config_get bbr_cca config bbr_cca 0
\tconfig_get "fullcone6" "config" "fullcone6" "0"
}
restart() {
: # Other runtime work remains after DNS restart is removed.
\t/etc/init.d/dnsmasq restart >"/dev/null" 2>&1
}
''')
            subprocess.run(['python3', str(ROOT / 'scripts/patch-turboacc-runtime.py'), str(root)], check=True)
            text = path.read_text()
            self.assertNotIn('/etc/init.d/dnsmasq restart', text)
            for enabled, want in ((1, '0 0 0 1'), (0, '1 1 1 1')):
                mock = '''config_load() { :; }
config_get() { eval "$1=1"; }
uci() { echo ENABLED; }
logger() { :; }
'''.replace('ENABLED', str(enabled))
                result = subprocess.run(['sh', '-c', mock + text + '\ninital_conf\nprintf "%s %s %s %s" "$sw_flow" "$hw_flow" "$sfe_flow" "$bbr_cca"'], capture_output=True, text=True, check=True)
                self.assertEqual(result.stdout, want)
