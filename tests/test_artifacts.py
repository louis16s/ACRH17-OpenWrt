from pathlib import Path
import hashlib
import io
import subprocess
import tarfile
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/verify-artifacts.py'

class ArtifactTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'configs').mkdir()
        (self.root / 'configs/acrh17.config').write_text('CONFIG_PACKAGE_ua3f=y\n')
        self.image = self.root / 'openwrt-asus_rt-ac42u-squashfs-sysupgrade.bin'
        with tarfile.open(self.image, 'w') as archive:
            for name, body in [('CONTROL', b'BOARD=asus_rt-ac42u\n'), ('kernel', b'kernel'), ('root', b'hsqsROOT')]:
                info = tarfile.TarInfo('sysupgrade-asus_rt-ac42u/' + name)
                info.size = len(body)
                archive.addfile(info, io.BytesIO(body))
        (self.root / 'openwrt-asus_rt-ac42u.manifest').write_text('ua3f - 3.6.0\nlibustream-mbedtls20201210 - 1\n')
        # A repository index is not the list of packages in the image.
        (self.root / 'Packages.manifest').write_text('Package: unrelated\n')
        (self.root / 'sha256sums').write_text(hashlib.sha256(self.image.read_bytes()).hexdigest() + '  ' + self.image.name + '\n')

    def verify(self):
        return subprocess.run(['python3', str(SCRIPT), str(self.root), '--sysupgrade-only'], cwd=self.root, capture_output=True, text=True)

    def test_device_manifest_selected_even_with_package_index(self):
        self.assertEqual(self.verify().returncode, 0)

    def test_corrupt_image_rejected(self):
        with self.image.open('ab') as stream:
            stream.write(b'corruption')
        result = self.verify()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('checksum mismatch', result.stderr)

    def test_conflicting_ssl_providers_rejected(self):
        with (self.root / 'openwrt-asus_rt-ac42u.manifest').open('a') as stream:
            stream.write('libustream-openssl20201210 - 1\n')
        result = self.verify()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('libustream', result.stderr)
