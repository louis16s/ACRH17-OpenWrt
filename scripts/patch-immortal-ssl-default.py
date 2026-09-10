#!/usr/bin/env python3
"""Align ImmortalWrt's default ustream provider with the LuCI SSL bundle."""
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text()
needle = "\tlibustream-openssl \\\n"
replacement = "\tlibustream-mbedtls \\\n"
if needle not in text:
    if replacement in text:
        print("ImmortalWrt default SSL provider already uses mbedTLS")
        raise SystemExit(0)
    raise SystemExit(f"Unexpected ImmortalWrt target defaults: {path}")
path.write_text(text.replace(needle, replacement, 1))
print("Patched ImmortalWrt default SSL provider to mbedTLS")
