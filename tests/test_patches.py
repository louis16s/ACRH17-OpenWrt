import subprocess
import tempfile
import unittest
from pathlib import Path


class TurboAccPatchTests(unittest.TestCase):
    def test_removes_unavailable_modules_but_keeps_supported_options(self):
        source = """PKG_CONFIG_DEPENDS:= \\
\tCONFIG_PACKAGE_$(PKG_NAME)_INCLUDE_BBR_CCA \\
\tCONFIG_PACKAGE_$(PKG_NAME)_INCLUDE_OFFLOADING \\
\tCONFIG_PACKAGE_$(PKG_NAME)_INCLUDE_SHORTCUT_FE \\
\tCONFIG_PACKAGE_$(PKG_NAME)_INCLUDE_SHORTCUT_FE_CM \\
\tCONFIG_PACKAGE_$(PKG_NAME)_INCLUDE_SHORTCUT_FE_DRV \\
\tCONFIG_PACKAGE_$(PKG_NAME)_INCLUDE_NFT_FULLCONE
LUCI_DEPENDS:= \\
\t+PACKAGE_$(PKG_NAME)_INCLUDE_BBR_CCA:kmod-tcp-bbr \\
\t+PACKAGE_$(PKG_NAME)_INCLUDE_OFFLOADING:kmod-nft-offload \\
\t+PACKAGE_$(PKG_NAME)_INCLUDE_SHORTCUT_FE:kmod-fast-classifier \\
\t+PACKAGE_$(PKG_NAME)_INCLUDE_SHORTCUT_FE_CM:kmod-shortcut-fe-cm \\
\t+PACKAGE_$(PKG_NAME)_INCLUDE_SHORTCUT_FE_DRV:kmod-shortcut-fe-drv \\
\t+PACKAGE_$(PKG_NAME)_INCLUDE_NFT_FULLCONE:kmod-nft-fullcone
define Package/x/config
config PACKAGE_$(PKG_NAME)_INCLUDE_OFFLOADING
\tbool \"Include Flow Offload\"
config PACKAGE_$(PKG_NAME)_INCLUDE_SHORTCUT_FE
\tbool \"Include Shortcut-FE\"
config PACKAGE_$(PKG_NAME)_INCLUDE_SHORTCUT_FE_CM
\tbool \"Include Shortcut-FE CM\"
config PACKAGE_$(PKG_NAME)_INCLUDE_SHORTCUT_FE_DRV
\tbool \"Include Shortcut-FE ECM\"
config PACKAGE_$(PKG_NAME)_INCLUDE_NFT_FULLCONE
\tbool \"Include NFT FULLCONE\"
config PACKAGE_$(PKG_NAME)_INCLUDE_BBR_CCA
\tbool \"Include BBR CCA\"
endef
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "Makefile"
            path.write_text(source)
            subprocess.run(["python3", "scripts/patch-turboacc.py", str(path)], check=True)
            result = path.read_text()
        self.assertNotIn("SHORTCUT_FE", result)
        self.assertNotIn("NFT_FULLCONE", result)
        self.assertIn("INCLUDE_OFFLOADING", result)
        self.assertIn("INCLUDE_BBR_CCA", result)
        self.assertIn("kmod-nft-offload", result)
        self.assertRegex(result, r"(?m)^\t\+PACKAGE_\$\(PKG_NAME\)_INCLUDE_OFFLOADING:kmod-nft-offload$")
        self.assertNotIn("kmod-nft-offload \\\nLUCI_PKGARCH", result)


class Ua3fMwan3PatchTests(unittest.TestCase):
    RULE = 'cmd := exec.Command("ip", "rule", "add", "fwmark", fwmark, "table", routeTable)\n'
    INJECT_RULE = 'fmt.Sprintf("mark %d", base.SO_INJECT_MARK),\n'

    def _root(self, directory):
        root = Path(directory) / "UA3F"
        (root / "internal/netfilter").mkdir(parents=True)
        (root / "internal/server/tproxy").mkdir(parents=True)
        (root / "internal/server/redirect").mkdir(parents=True)
        (root / "internal/netfilter/firewall.go").write_text(self.RULE * 4)
        for rel in ("internal/server/tproxy/nftables.go", "internal/server/redirect/nftables.go"):
            (root / rel).write_text(
                '\t\t\tfmt.Sprintf("mark %d", s.so_mark),\n'
                '\t\t\tfmt.Sprintf("mark {%s}", mark),\n'
                '\t\t\t"mark", s.tproxyFwMark,\n'
                '\t\t\t"mark set", s.tproxyFwMark,\n'
                + (self.INJECT_RULE if rel.endswith("tproxy/nftables.go") else "")
            )
        for mode in ('nfqueue', 'desync', 'netlink'):
            directory = root / 'internal/server' / mode
            directory.mkdir(parents=True)
            (directory / 'nftables.go').write_text(self.INJECT_RULE)
        for mode in ('nfqueue', 'desync', 'netlink', 'tproxy', 'redirect'):
            (root / 'internal/server' / mode / 'iptables.go').write_text(
                '"--mark", strconv.Itoa(base.SO_INJECT_MARK),\n')
        (root / 'internal/server/nfqueue/nfqueue_linux.go').write_text(
            'func (s *Server) getNextMark(packet *common.Packet, result *common.RewriteDecision) (setMark bool, mark uint32) {\n'
            '\tmark, found := packet.GetCtMark()\n}\n')
        return root

    def test_confines_ua3f_marks_to_the_low_16_bits(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self._root(directory)
            subprocess.run(["python3", "scripts/patch-ua3f-mwan3.py", str(root)], check=True)
            rule = (root / "internal/netfilter/firewall.go").read_text()
            tproxy = (root / "internal/server/tproxy/nftables.go").read_text()
            redirect = (root / "internal/server/redirect/nftables.go").read_text()

        # mwan3 keeps its id bits in 0x3f000000; every UA3F ip-rule lookup must
        # compare only the low half, and the rule needs an explicit priority so
        # that TPROXY delivery precedes mwan3's 1001+ uplink policies.
        self.assertNotIn('"fwmark", fwmark,', rule)
        self.assertEqual(rule.count('"priority", "100", "fwmark", fwmark+"/0xffff", "table", routeTable'), 4)
        for source in (tproxy, redirect):
            # matches must be masked...
            self.assertIn('fmt.Sprintf("mark & 0xffff == %d", s.so_mark)', source)
            self.assertIn('fmt.Sprintf("mark & 0xffff == {%s}", mark)', source)
            self.assertIn('"mark & 0xffff ==", s.tproxyFwMark', source)
            # ...and assignments must preserve whatever mwan3 already set.
            self.assertIn('"mark set (mark & 0xffff0000) |", s.tproxyFwMark', source)
            self.assertNotIn('fmt.Sprintf("mark %d", s.so_mark)', source)
            self.assertNotIn('"mark set", s.tproxyFwMark', source)
        self.assertIn('fmt.Sprintf("mark & 0xffff == %d", base.SO_INJECT_MARK)', tproxy)

    def test_refuses_source_that_lost_the_expected_constructs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self._root(directory)
            (root / "internal/server/tproxy/nftables.go").write_text("package tproxy\n")
            result = subprocess.run(["python3", "scripts/patch-ua3f-mwan3.py", str(root)],
                                    capture_output=True)
        self.assertNotEqual(result.returncode, 0)


class ArgonPatchTests(unittest.TestCase):
    WGET_ANY_DEPENDS = "LUCI_DEPENDS:=+USE_APK:wget-any +!USE_APK:wget +jsonfilter\n"
    NEEDLE = ('<a href="https://github.com/jerrykuku/luci-theme-argon" target="_blank">'
              'ArgonTheme {# vPKG_VERSION #}</a>')

    def _root(self, directory, makefile=None):
        root = Path(directory) / "luci-theme-argon"
        (root / "ucode/template/themes/argon").mkdir(parents=True)
        (root / "Makefile").write_text(self.WGET_ANY_DEPENDS if makefile is None else makefile)
        for name in ("footer.ut", "footer_login.ut"):
            (root / "ucode/template/themes/argon" / name).write_text(self.NEEDLE + "\n")
        return root

    def _run(self, root):
        return subprocess.run(["python3", "scripts/patch-argon-footer.py", str(root)],
                              capture_output=True)

    def test_drops_wget_any_and_injects_the_author_link(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self._root(directory)
            self.assertEqual(self._run(root).returncode, 0)
            makefile = (root / "Makefile").read_text()
            footers = [(root / "ucode/template/themes/argon" / name).read_text()
                       for name in ("footer.ut", "footer_login.ut")]
        self.assertNotIn("wget-any", makefile)
        self.assertIn("LUCI_DEPENDS:=+!USE_APK:wget +jsonfilter", makefile)
        for footer in footers:
            self.assertEqual(footer.count("https://530555.xyz"), 1)

    def test_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self._root(directory)
            self._run(root)
            self.assertEqual(self._run(root).returncode, 0)
            footer = (root / "ucode/template/themes/argon/footer.ut").read_text()
        self.assertEqual(footer.count("https://530555.xyz"), 1)

    def test_rejects_a_reworded_wget_any_dependency(self):
        # Silently leaving wget-any behind would only surface much later as an
        # unresolvable package during the build.
        with tempfile.TemporaryDirectory() as directory:
            root = self._root(directory, "LUCI_DEPENDS:=+USE_APK:wget-any:x +!USE_APK:wget +jsonfilter\n")
            result = self._run(root)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("wget-any", result.stderr.decode())

    def test_rejects_a_makefile_without_the_wget_dependency(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self._root(directory, "LUCI_DEPENDS:=+jsonfilter\n")
            result = self._run(root)
        self.assertNotEqual(result.returncode, 0)

    def test_rejects_a_footer_whose_layout_changed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self._root(directory)
            (root / "ucode/template/themes/argon/footer.ut").write_text("<a>nothing useful</a>\n")
            result = self._run(root)
        self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
