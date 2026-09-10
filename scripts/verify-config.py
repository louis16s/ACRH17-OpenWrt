#!/usr/bin/env python3
"""Kconfig silently drops unknown symbols: fail instead of losing features."""
from pathlib import Path
import sys
requested = Path(sys.argv[1]).read_text().splitlines()
resolved = set(Path(sys.argv[2]).read_text().splitlines())

# Build-host controls such as CONFIG_CCACHE and CONFIG_IB are consumed by
# OpenWrt itself and may be omitted or rewritten by make defconfig.  Only
# firmware-relevant target and package selections must survive defconfig.
required = [
    x for x in requested
    if x.startswith(('CONFIG_TARGET_', 'CONFIG_PACKAGE_'))
    and x.endswith('=y')
    and '_INCLUDE_' not in x
]
missing = [x for x in required if x not in resolved]
if missing:
    raise SystemExit('Required config symbols dropped: ' + ', '.join(missing))

# libustream has one shared soname, so both LuCI SSL collections cannot be
# installed in the same image.  ImmortalWrt profiles can select the OpenSSL
# collection by default even when the project asks for the mbedTLS one.
if 'CONFIG_PACKAGE_luci-ssl=y' in resolved and 'CONFIG_PACKAGE_luci-ssl-openssl=y' in resolved:
    raise SystemExit('Conflicting LuCI SSL providers selected: luci-ssl and luci-ssl-openssl')
print('All requested features survived make defconfig')
