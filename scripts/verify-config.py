#!/usr/bin/env python3
"""Kconfig silently drops unknown symbols: fail instead of losing features."""
from pathlib import Path
import sys
requested = Path(sys.argv[1]).read_text().splitlines()
resolved = set(Path(sys.argv[2]).read_text().splitlines())
missing = [x for x in requested if x.startswith('CONFIG_') and x.endswith('=y') and x not in resolved]
if missing:
    raise SystemExit('Required config symbols dropped: ' + ', '.join(missing))
print('All requested features survived make defconfig')
