#!/bin/sh
set -eu
# Invoke with the OpenWrt source tree as the working directory.
PROJECT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
. "$PROJECT/sources.env"
[ -f include/toplevel.mk ] || { echo 'Run inside an OpenWrt source tree' >&2; exit 1; }
[ ! -e package/UA3F ] || { echo 'UA3F directory already exists' >&2; exit 1; }
git clone https://github.com/SunBK201/UA3F.git package/UA3F
git -C package/UA3F checkout --detach "$UA3F_COMMIT"
python3 "$PROJECT/scripts/patch-ua3f.py" package/UA3F/openwrt/Makefile
python3 "$PROJECT/scripts/patch-ua3f-mwan3.py" package/UA3F
cp -R "$PROJECT/package/ruijie-auth" package/
cp -R "$PROJECT/files" .
