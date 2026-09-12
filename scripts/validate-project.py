#!/usr/bin/env python3
"""Fail on any syntax error; find -exec alone does not propagate luac failures."""
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
for directory in ('scripts', 'files', 'package'):
    for path in sorted((root / directory).rglob('*')):
        if not path.is_file():
            continue
        if path.suffix == '.lua':
            subprocess.run(['luac', '-p', str(path)], check=True)
        elif path.read_bytes().startswith(b'#!/bin/sh'):
            subprocess.run(['sh', '-n', str(path)], check=True)
subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-v'], cwd=root, check=True)
