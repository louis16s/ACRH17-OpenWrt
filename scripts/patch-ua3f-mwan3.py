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

# Helper/desync packet marks and NFQUEUE connection marks also share mwan3's
# namespace. Preserve the upper bits for every NFQUEUE verdict, including
# early NeedSkip/NeedCache returns, and compare only UA3F's lower bits.
for rel in ['internal/server/nfqueue/nftables.go',
            'internal/server/desync/nftables.go',
            'internal/server/netlink/nftables.go']:
    f = root / rel
    s = f.read_text()
    assert 'fmt.Sprintf("mark %d",' in s, rel
    s = s.replace('fmt.Sprintf("mark %d",', 'fmt.Sprintf("mark & 0xffff == %d",')
    s = s.replace('fmt.Sprintf("ct mark %d",', 'fmt.Sprintf("ct mark & 0xffff == %d",')
    f.write_text(s)
f = root / 'internal/server/tproxy/nftables.go'
s = f.read_text().replace('"mark set 7894"', '"mark set (mark & 0xffff0000) | 7894"')
f.write_text(s)
f = root / 'internal/server/nfqueue/nfqueue_linux.go'
s = f.read_text()
marker = 'func (s *Server) getNextMark(packet *common.Packet, result *common.RewriteDecision) (setMark bool, mark uint32) {\n'
assert s.count(marker) == 1
assert s.count('mark, found := packet.GetCtMark()') == 1
s = s.replace('mark, found := packet.GetCtMark()', 'mark = originalMark & 0xffff')
s = s.replace(marker, marker + """	originalMark, found := packet.GetCtMark()
	defer func() {
		if setMark {
			mark = (originalMark & 0xffff0000) | (mark & 0xffff)
		}
	}()
""")
f.write_text(s)

# Keep the same ownership contract if UA3F falls back to its iptables backend.
for rel in ['tproxy', 'redirect', 'nfqueue', 'desync', 'netlink']:
    f = root / ('internal/server/' + rel + '/iptables.go')
    s = f.read_text()
    for expr in ('strconv.Itoa(s.so_mark)', 'strconv.Itoa(base.SO_INJECT_MARK)',
                 'strconv.Itoa(s.InjectMark)', 'strconv.Itoa(int(s.NotHTTPCtMark))',
                 's.tproxyFwMark', 'imark'):
        s = s.replace('"--mark", ' + expr + ',', '"--mark", ' + expr + '+"/0xffff",')
    s = s.replace('"--tproxy-mark", s.tproxyFwMark,', '"--tproxy-mark", s.tproxyFwMark+"/0xffff",')
    s = s.replace('"--tproxy-mark", "7894",', '"--tproxy-mark", "7894/0xffff",')
    s = s.replace('"--set-mark", s.tproxyFwMark,', '"--set-xmark", s.tproxyFwMark+"/0xffff",')
    f.write_text(s)
