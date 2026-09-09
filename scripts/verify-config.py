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
print('All requested features survived make defconfig')
