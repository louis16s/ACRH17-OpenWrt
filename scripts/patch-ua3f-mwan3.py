#!/usr/bin/env python3
"""Separate UA3F's low 16 packet-mark bits from mwan3's high 6 bits.

The firmware uses UA3F's nft backend and mwan3's legacy iptables backend.
TPROXY's local delivery rule must precede mwan3 uplink policy rules.
"""
from pathlib import Path
import sys
root = Path(sys.argv[1])
f = root / 'internal/netfilter/firewall.go'
s = f.read_text()
assert s.count('"fwmark", fwmark, "table", routeTable') == 4
s = s.replace('"fwmark", fwmark, "table", routeTable', '"priority", "100", "fwmark", fwmark+"/0xffff", "table", routeTable')
f.write_text(s)
for rel in ['internal/server/tproxy/nftables.go', 'internal/server/redirect/nftables.go']:
    f = root / rel
    s = f.read_text()
    assert 'fmt.Sprintf("mark %d", s.so_mark)' in s
    s = s.replace('fmt.Sprintf("mark %d",', 'fmt.Sprintf("mark & 0xffff == %d",')
    s = s.replace('fmt.Sprintf("mark {%s}",', 'fmt.Sprintf("mark & 0xffff == {%s}",')
    s = s.replace('"mark", s.tproxyFwMark', '"mark & 0xffff ==", s.tproxyFwMark')
    s = s.replace('"mark set", s.tproxyFwMark', '"mark set (mark & 0xffff0000) |", s.tproxyFwMark')
    f.write_text(s)
