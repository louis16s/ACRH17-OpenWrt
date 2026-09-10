#!/usr/bin/env python3
from pathlib import Path
import sys
p = Path(sys.argv[1])
suffixes = ['squashfs-sysupgrade.bin'] if '--sysupgrade-only' in sys.argv else ['initramfs-uImage.itb', 'squashfs-sysupgrade.bin']
for suffix in suffixes:
    images = list(p.glob('*asus_rt-ac42u-' + suffix))
    assert len(images) == 1 and images[0].stat().st_size > 0, suffix
    print(images[0].name, images[0].stat().st_size, 'bytes')
    if suffix == 'squashfs-sysupgrade.bin':
        assert images[0].stat().st_size <= 20439364, 'Official device image size exceeded'
manifest = next(p.glob('*.manifest')).read_text()
packages = {line.split()[0] for line in manifest.splitlines() if line.strip()}
required = {
    line.split('CONFIG_PACKAGE_', 1)[1].split('=')[0]
    for line in Path('configs/acrh17.config').read_text().splitlines()
    if line.startswith('CONFIG_PACKAGE_')
    and line.endswith('=y')
    and '_INCLUDE_' not in line
}
assert not required - packages, 'Missing packages: ' + str(required - packages)
for name in packages:
    assert not any(x in name.lower() for x in ['clash', 'adguard', 'samba', 'docker']), name
print('Firmware manifest contains every required package')

for line in Path('configs/acrh17.config').read_text().splitlines():
    if line.startswith('# CONFIG_PACKAGE_') and line.endswith(' is not set') and '_INCLUDE_' not in line:
        name = line.split('CONFIG_PACKAGE_', 1)[1].split()[0]
        assert name not in packages, 'Excluded package installed: ' + name
