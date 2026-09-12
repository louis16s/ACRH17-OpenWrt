#!/usr/bin/env python3
"""Kconfig silently drops unknown symbols: fail instead of losing features."""
from pathlib import Path
import sys
requested = Path(sys.argv[1]).read_text().splitlines()
resolved = set(Path(sys.argv[2]).read_text().splitlines())

# Every explicit enable is part of the build contract, including ImageBuilder,
# languages and package feature toggles. Kconfig must not silently drop these.
required = [x for x in requested if x.startswith('CONFIG_') and x.endswith('=y')]
missing = [x for x in required if x not in resolved]
if missing:
    raise SystemExit('Required config symbols dropped: ' + ', '.join(missing))

# libustream has one shared soname, so both LuCI SSL collections cannot be
# installed in the same image.  ImmortalWrt profiles can select the OpenSSL
# collection by default even when the project asks for the mbedTLS one.
if 'CONFIG_PACKAGE_luci-ssl=y' in resolved and 'CONFIG_PACKAGE_luci-ssl-openssl=y' in resolved:
    raise SystemExit('Conflicting LuCI SSL providers selected: luci-ssl and luci-ssl-openssl')

excluded = [x.split("CONFIG_PACKAGE_", 1)[1].split()[0]
            for x in requested if x.startswith("# CONFIG_PACKAGE_")
            and x.endswith(" is not set")]
for name in excluded:
    if "CONFIG_PACKAGE_" + name + "=y" in resolved:
        raise SystemExit("Excluded package selected: " + name)
providers = [x for x in resolved if x.startswith("CONFIG_PACKAGE_libustream-") and x.endswith("=y")]
if len(providers) > 1:
    raise SystemExit("Conflicting libustream providers: " + ", ".join(providers))

print('All requested features and exclusions survived make defconfig')
