#!/bin/bash
# Linux-only isolated integration test; never run against a router's real interfaces.
set -euo pipefail
BIN=$(realpath "$1")
LOG=/tmp/acrh17-routing-logs
mkdir -p "$LOG"
cleanup() {
  for ns in acr-router acr-client acr-wan1 acr-wan2; do
    ip netns pids "$ns" 2>/dev/null | xargs -r kill 2>/dev/null || true
    ip netns del "$ns" 2>/dev/null || true
  done
}
trap cleanup EXIT
for ns in acr-router acr-client acr-wan1 acr-wan2; do
  ip netns add "$ns"
  ip -n "$ns" link set lo up
done
ip link add acr-lan type veth peer name acr-client-link
ip link set acr-lan netns acr-router
ip link set acr-client-link netns acr-client
ip -n acr-router link add br-lan type bridge
ip -n acr-router link set acr-lan master br-lan
ip -n acr-router link set acr-lan up
ip -n acr-router link set br-lan up
ip -n acr-router addr add 192.168.8.1/24 dev br-lan
ip -n acr-client addr add 192.168.8.2/24 dev acr-client-link
ip -n acr-client link set acr-client-link up
ip -n acr-client route add default via 192.168.8.1
for i in 1 2; do
  subnet="203.0.$((112+i))"
  ip link add "acr-u$i" type veth peer name "acr-r$i"
  ip link set "acr-u$i" netns "acr-wan$i"
  ip link set "acr-r$i" netns acr-router
  ip -n "acr-wan$i" addr add "$subnet.1/24" dev "acr-u$i"
  ip -n "acr-wan$i" addr add 192.0.2.10/32 dev lo
  ip -n "acr-wan$i" link set "acr-u$i" up
  ip -n acr-router addr add "$subnet.2/24" dev "acr-r$i"
  ip -n acr-router link set "acr-r$i" up
  ip -n acr-router route add default via "$subnet.1" dev "acr-r$i" table "$i"
  ip -n acr-router rule add priority "$((2000+i))" fwmark "$((i<<24))/0x3f000000" table "$i"
  ip netns exec "acr-wan$i" python3 -u - "$i" >"$LOG/wan$i.log" 2>&1 <<'PY' &
import http.server,sys
wan=sys.argv[1]
class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body=('WAN'+wan+':'+self.headers.get('User-Agent','')).encode()
        self.send_response(200)
        self.send_header('Content-Length',str(len(body)))
        self.end_headers()
        self.wfile.write(body)
http.server.HTTPServer(('192.0.2.10',80),Handler).serve_forever()
PY
done
ip -n acr-router route add default via 203.0.113.1
ip netns exec acr-router sysctl -qw net.ipv4.ip_forward=1 net.ipv4.conf.all.rp_filter=0 net.ipv4.conf.default.rp_filter=0
for device in br-lan acr-lan acr-r1 acr-r2; do
  ip netns exec acr-router sysctl -qw "net.ipv4.conf.$device.rp_filter=0"
done
# Model mwan3's masked packet/connection marks on both hooks.
ipt() { ip netns exec acr-router iptables-legacy -t mangle "$@"; }
ipt -N TEST_MWAN
ipt -A PREROUTING -j TEST_MWAN
ipt -A OUTPUT -j TEST_MWAN
ipt -A TEST_MWAN -j CONNMARK --restore-mark --nfmask 0x3f000000 --ctmask 0x3f000000
ipt -A TEST_MWAN -m mark --mark 0/0x3f000000 -j MARK --set-xmark 0x01000000/0x3f000000
ipt -A TEST_MWAN -j CONNMARK --save-mark --nfmask 0x3f000000 --ctmask 0x3f000000
ip netns exec acr-router "$BIN" -m TPROXY -f ROUTING-TEST -l DEBUG >"$LOG/ua3f.log" 2>&1 &
for attempt in $(seq 1 20); do
  if ip netns exec acr-router nft list table inet UA3F >"$LOG/nft-rules.txt" 2>/dev/null; then break; fi
  sleep 1
done
ip -n acr-router rule show >"$LOG/ip-rules.txt"
for i in 1 2; do
  ipt -R TEST_MWAN 2 -m mark --mark 0/0x3f000000 -j MARK --set-xmark "$((i<<24))/0x3f000000"
  result=$(ip netns exec acr-client curl --noproxy '*' -fsS --http1.0 --max-time 10 -A ORIGINAL-UA http://192.0.2.10/)
  echo "$result" | tee -a "$LOG/results.txt"
  test "$result" = "WAN$i:ROUTING-TEST"
done
