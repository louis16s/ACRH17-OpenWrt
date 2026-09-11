#!/bin/sh
set -eu
# Invoke with the OpenWrt source tree as the working directory.
PROJECT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
. "$PROJECT/sources.env"
[ -f include/toplevel.mk ] || { echo 'Run inside an OpenWrt source tree' >&2; exit 1; }
[ ! -e package/UA3F ] || { echo 'UA3F directory already exists' >&2; exit 1; }
fetch_source() {
 git init "$3"
 git -C "$3" remote add origin "$1"
 git -C "$3" fetch --depth=1 origin "$2"
 git -C "$3" checkout --detach FETCH_HEAD
}
fetch_source https://github.com/SunBK201/UA3F.git "$UA3F_COMMIT" package/UA3F
python3 "$PROJECT/scripts/patch-ua3f.py" package/UA3F/openwrt/Makefile
python3 "$PROJECT/scripts/patch-ua3f-mwan3.py" package/UA3F
fetch_source https://github.com/jerrykuku/luci-theme-argon.git "$ARGON_COMMIT" package/luci-theme-argon
python3 "$PROJECT/scripts/patch-argon-footer.py" package/luci-theme-argon
fetch_source https://github.com/chenmozhijin/luci-app-turboacc.git "$TURBOACC_COMMIT" turboacc-source
cp -R turboacc-source/luci-app-turboacc package/
python3 "$PROJECT/scripts/patch-turboacc.py" package/luci-app-turboacc/Makefile
cp -R "$PROJECT/package/ruijie-auth" package/
cp -R "$PROJECT/files" .
