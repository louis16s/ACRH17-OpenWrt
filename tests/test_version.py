from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts/firmware-version.py'

# The shape include/version.mk has upstream, quoted so a rewording is a failure.
VERSION_MK = """\
VERSION_NUMBER:=$(call qstrip,$(CONFIG_VERSION_NUMBER))
VERSION_NUMBER:=$(if $(VERSION_NUMBER),$(VERSION_NUMBER),24.10-SNAPSHOT)

VERSION_CODE:=$(call qstrip,$(CONFIG_VERSION_CODE))
VERSION_CODE:=$(if $(VERSION_CODE),$(VERSION_CODE),$(REVISION))
"""


class FirmwareVersionTests(unittest.TestCase):
    def run_script(self, body, stamp='20260913-2359'):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'version.mk'
            path.write_text(body, encoding='utf-8')
            return subprocess.run([sys.executable, str(SCRIPT), str(path), stamp],
                                  capture_output=True, text=True)

    def test_appends_the_stamp_to_the_upstream_fallback(self):
        result = self.run_script(VERSION_MK)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual('24.10-SNAPSHOT-20260913-2359', result.stdout.strip())

    def test_rejects_a_rewritten_fallback(self):
        result = self.run_script('VERSION_NUMBER:=$(CONFIG_VERSION_NUMBER)\n')
        self.assertEqual(1, result.returncode)
        self.assertIn('expected one VERSION_NUMBER fallback', result.stderr)

    def test_rejects_two_fallbacks(self):
        result = self.run_script(VERSION_MK + VERSION_MK)
        self.assertEqual(1, result.returncode)
        self.assertIn('found 2', result.stderr)

    def test_rejects_a_stamp_that_is_not_a_build_time(self):
        result = self.run_script(VERSION_MK, stamp='2026-09-13 23:59')
        self.assertEqual(1, result.returncode)
        self.assertIn('YYYYMMDD-HHMM', result.stderr)

    def test_requires_both_arguments(self):
        result = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True)
        self.assertEqual(1, result.returncode)
        self.assertIn('usage:', result.stderr)


if __name__ == '__main__':
    unittest.main()
