#!/usr/bin/env python3
"""Add the project author's link to Argon's two footer templates."""
from pathlib import Path
import sys

root = Path(sys.argv[1])
marker = 'href="https://530555.xyz"'
for name in ("footer.ut", "footer_login.ut"):
    path = root / "ucode/template/themes/argon" / name
    text = path.read_text()
    if marker in text:
        continue
    needle = '<a href="https://github.com/jerrykuku/luci-theme-argon" target="_blank">ArgonTheme {# vPKG_VERSION #}</a>'
    replacement = needle + '\n\t\t\t\t<a href="https://530555.xyz" target="_blank">番鼠大王</a>'
    if needle not in text:
        raise SystemExit(f"Argon footer layout changed: {path}")
    path.write_text(text.replace(needle, replacement, 1))
