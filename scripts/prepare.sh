#!/bin/sh
set -eu

echo "[1/2] Adding UA3F..."
rm -rf package/UA3F
git clone --depth=1 https://github.com/SunBK201/UA3F.git package/UA3F

echo "[2/2] Custom packages ready."
