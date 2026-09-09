#!/usr/bin/env python3
"""Bind a standalone ImageBuilder to the exact source, package and build recipe."""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

def signature():
    files = [Path('sources.env'), Path('configs/acrh17.config')]
    files += sorted(Path('scripts').glob('patch-*.py'))
    files += [Path('scripts/prepare.sh'), Path('package/ruijie-auth/Makefile')]
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}

if __name__ == '__main__':
    mode, directory = sys.argv[1:3]
    path = Path(directory) / 'compatibility.json'
    if mode == 'stamp':
        path.write_text(json.dumps(signature(), indent=2))
        overlays = [str(p) for root in ('files', 'package/ruijie-auth/files') for p in Path(root).rglob('*') if p.is_file()]
        (Path(directory) / 'overlay-paths.json').write_text(json.dumps(overlays))
        (Path(directory) / 'project-commit.txt').write_text(subprocess.check_output(['git','rev-parse','HEAD'], text=True))
    else:
        if json.loads(path.read_text()) != signature():
            raise SystemExit('Source/package/build recipe changed: run the full build first')
        removed = [p for p in json.loads((Path(directory) / 'overlay-paths.json').read_text()) if not Path(p).is_file()]
        if removed:
            raise SystemExit('Overlay files removed: run full build first: ' + ', '.join(removed))
        print('ImageBuilder source and package compatibility verified')
