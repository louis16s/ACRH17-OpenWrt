#!/usr/bin/env python3
"""Minimal build-only fixes for the pinned upstream UA3F v3.6.0 recipe."""
from pathlib import Path
import sys
p = Path(sys.argv[1])
s = p.read_text()
for old, new in [
    ('PKG_BUILD_DEPENDS:=golang/host', 'PKG_BUILD_DEPENDS:=golang/host luci-base/host'),
    ('define Build/Prepare\n', 'define Build/Prepare\n\t$(INSTALL_DIR) $(PKG_BUILD_DIR)\n'),
]:
    if s.count(old) != 1:
        raise SystemExit('UA3F recipe changed; review patch before updating')
    s = s.replace(old, new)
p.write_text(s)
