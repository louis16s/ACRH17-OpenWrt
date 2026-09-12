#!/usr/bin/env python3
"""Add the project author's link to Argon's two footer templates."""
from pathlib import Path
import sys

root = Path(sys.argv[1])
marker = 'href="https://530555.xyz"'

# Argon's current Makefile still carries the pre-24.10 conditional
# ``wget-any`` dependency.  That virtual package is not present in the
# pinned 24.10 feeds; the non-APK wget dependency is the portable choice.
# The rewrite is asserted rather than silent: if upstream rewords this line
# the stale ``wget-any`` dependency would otherwise survive unnoticed and
# only surface much later as an unresolved-package failure during ``make``.
OLD_DEPENDS = 'LUCI_DEPENDS:=+USE_APK:wget-any +!USE_APK:wget +jsonfilter'
NEW_DEPENDS = 'LUCI_DEPENDS:=+!USE_APK:wget +jsonfilter'
makefile = root / "Makefile"
make_text = makefile.read_text()
if OLD_DEPENDS in make_text:
    makefile.write_text(make_text.replace(OLD_DEPENDS, NEW_DEPENDS))
elif 'wget-any' in make_text:
    raise SystemExit(f"Argon LUCI_DEPENDS layout changed, still on wget-any: {makefile}")
elif NEW_DEPENDS not in make_text:
    raise SystemExit(f"Argon LUCI_DEPENDS lost its wget dependency: {makefile}")

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
