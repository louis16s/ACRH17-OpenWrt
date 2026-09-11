#!/usr/bin/env python3
"""Remove TurboACC options whose kernel packages are absent from 24.10 feeds."""
from pathlib import Path
import re
import sys

path = Path(sys.argv[1])
text = path.read_text()

unsupported = {
    "SHORTCUT_FE": "kmod-fast-classifier",
    "SHORTCUT_FE_CM": "kmod-shortcut-fe-cm",
    "SHORTCUT_FE_DRV": "kmod-shortcut-fe-drv",
    "NFT_FULLCONE": "kmod-nft-fullcone",
}

# Keep the recipe honest: an unavailable package must not remain in
# LUCI_DEPENDS, even when its corresponding config option defaults to n.
for symbol, package in unsupported.items():
    marker = f"+PACKAGE_$(PKG_NAME)_INCLUDE_{symbol}:{package}"
    matches = [line for line in text.splitlines(keepends=True) if marker in line]
    if len(matches) != 1:
        raise SystemExit(f"TurboACC recipe changed; expected one dependency for {marker}")
    text = "".join(line for line in text.splitlines(keepends=True) if marker not in line)

# The dependency entries above are part of make's backslash-continued
# variable assignments.  Removing the last entry must also remove the
# continuation marker from the new last entry; otherwise the following
# ``LUCI_PKGARCH:=all`` assignment is parsed as a bogus dependency named
# ``=all``.  Keep this generic so a harmless ordering change in the recipe
# does not reintroduce the warning.
def close_dependency_block(source, variable):
    lines = source.splitlines(keepends=True)
    index = 0
    prefix = f"{variable}:="
    while index < len(lines):
        if not lines[index].startswith(prefix):
            index += 1
            continue

        end = index + 1
        while end < len(lines):
            current = lines[end]
            if current.strip() == "" or current.startswith((" ", "\t")):
                end += 1
                continue
            break

        for candidate in range(end - 1, index, -1):
            if lines[candidate].strip():
                content = lines[candidate].rstrip("\r\n")
                if content.endswith("\\"):
                    # Preserve the line ending when the final entry already
                    # is a complete assignment (for example, a Kconfig
                    # block whose last unsupported entry was removed later).
                    lines[candidate] = content[:-1].rstrip() + "\n"
                break
        index = end
    return "".join(lines)

# Drop the matching Kconfig dependency declarations as well.
text = "".join(
    line for line in text.splitlines(keepends=True)
    if not any(f"CONFIG_PACKAGE_$(PKG_NAME)_INCLUDE_{symbol}" in line
               for symbol in unsupported)
)

# Hide the same unsupported features from menuconfig.  Leaving a visible
# toggle that cannot install its kernel module would be misleading.
lines = text.splitlines(keepends=True)
out = []
skip = False
for line in lines:
    match = re.match(r"config PACKAGE_\$\(PKG_NAME\)_INCLUDE_([A-Z_]+)\s*$", line.rstrip("\n"))
    if match:
        symbol = match.group(1)
        if symbol in unsupported:
            skip = True
            continue
    if skip and line.startswith("config "):
        skip = False
    if skip and line.startswith("endef"):
        skip = False
    if not skip:
        out.append(line)
text = "".join(out)

# Run this after both dependency and Kconfig entries have been pruned so the
# remaining last entry in each make variable is the one whose continuation
# marker must be closed.
for dependency_variable in ("PKG_CONFIG_DEPENDS", "LUCI_DEPENDS"):
    text = close_dependency_block(text, dependency_variable)

for symbol in unsupported:
    if f"INCLUDE_{symbol}" in text:
        raise SystemExit(f"TurboACC unsupported option survived patch: {symbol}")
path.write_text(text)
