#!/usr/bin/env python3
"""Validate the selected device's images, checksums and installed package list."""
import hashlib
from pathlib import Path
import sys
import tarfile


def require(condition, message):
    if not condition:
        raise SystemExit(message)


p = Path(sys.argv[1])
suffixes = ['squashfs-sysupgrade.bin'] if '--sysupgrade-only' in sys.argv else ['initramfs-uImage.itb', 'squashfs-sysupgrade.bin']
checksums = {}
for line in (p / 'sha256sums').read_text().splitlines():
    digest, name = line.split(maxsplit=1)
    checksums[name.lstrip('*')] = digest
for suffix in suffixes:
    images = list(p.glob('*asus_rt-ac42u-' + suffix))
    require(len(images) == 1 and images[0].stat().st_size > 0, 'Missing or ambiguous image: ' + suffix)
    image = images[0]
    require(hashlib.sha256(image.read_bytes()).hexdigest() == checksums.get(image.name),
            'Image checksum mismatch: ' + image.name)
    print(image.name, image.stat().st_size, 'bytes')
    if suffix == 'squashfs-sysupgrade.bin':
        require(image.stat().st_size <= 20439364, 'Official device image size exceeded')
        with tarfile.open(image) as archive:
            prefix = 'sysupgrade-asus_rt-ac42u/'
            for name in ('CONTROL', 'kernel', 'root'):
                member = archive.getmember(prefix + name)
                require(member.isfile() and member.size > 0, 'Invalid sysupgrade member: ' + name)
            with archive.extractfile(prefix + 'root') as root:
                require(root.read(4) == b'hsqs', 'Expected a SquashFS root filesystem')
    else:
        with image.open('rb') as fit:
            require(fit.read(4) == b'\xd0\x0d\xfe\xed', 'Expected a FIT initramfs image')

# Package indexes can also contain Packages.manifest. Select the device file.
manifests = list(p.glob('*asus_rt-ac42u.manifest'))
require(len(manifests) == 1, 'Expected exactly one RT-AC42U firmware manifest')
packages = {line.split()[0] for line in manifests[0].read_text().splitlines() if line.strip()}
config = Path('configs/acrh17.config').read_text().splitlines()
required = {
    line.split('CONFIG_PACKAGE_', 1)[1].split('=')[0]
    for line in config
    if line.startswith('CONFIG_PACKAGE_') and line.endswith('=y') and '_INCLUDE_' not in line
}
require(not required - packages, 'Missing packages: ' + str(required - packages))
for name in packages:
    require(not any(x in name.lower() for x in ['clash', 'adguard', 'samba', 'docker']),
            'Unexpected package: ' + name)
for line in config:
    if line.startswith('# CONFIG_PACKAGE_') and line.endswith(' is not set') and '_INCLUDE_' not in line:
        name = line.split('CONFIG_PACKAGE_', 1)[1].split()[0]
        require(name not in packages, 'Excluded package installed: ' + name)
providers = {name for name in packages if name.startswith('libustream-')}
require(len(providers) == 1, 'Expected one libustream provider: ' + str(providers))
print('Firmware structure, checksums and package contract verified')
