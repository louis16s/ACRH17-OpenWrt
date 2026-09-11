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


if __name__ == "__main__":
    unittest.main()
