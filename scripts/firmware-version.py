#!/usr/bin/env python3
"""Resolve the version string a firmware build is stamped with.

include/version.mk falls back to a hard-coded number when CONFIG_VERSION_NUMBER
is empty. The build start time is appended to that number instead of replacing
it, so the image still says which upstream release it came from. The fallback is
matched with an asserted pattern: an upstream rewording must fail the build
rather than quietly stamp a version that no longer means anything.
"""
from pathlib import Path
import re
import sys

FALLBACK = re.compile(
    r'^VERSION_NUMBER:=\$\(if \$\(VERSION_NUMBER\),\$\(VERSION_NUMBER\),(.+)\)$', re.M)
STAMP = re.compile(r'[0-9]{8}-[0-9]{4}')


def base_version(version_mk):
    matches = FALLBACK.findall(Path(version_mk).read_text(encoding='utf-8'))
    if len(matches) != 1:
        raise SystemExit('%s: expected one VERSION_NUMBER fallback, found %d'
                         % (version_mk, len(matches)))
    return matches[0]


def firmware_version(version_mk, stamp):
    if not STAMP.fullmatch(stamp):
        raise SystemExit('build stamp must look like YYYYMMDD-HHMM, got %r' % stamp)
    return '%s-%s' % (base_version(version_mk), stamp)


if __name__ == '__main__':
    if len(sys.argv) != 3:
        sys.exit('usage: firmware-version.py <include/version.mk> <YYYYMMDD-HHMM>')
    print(firmware_version(sys.argv[1], sys.argv[2]))
