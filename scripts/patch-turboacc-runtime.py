#!/usr/bin/env python3
"""Guard flow offload when packet inspection or policy routing is configured."""
from pathlib import Path
import sys

path = Path(sys.argv[1]) / 'root/etc/init.d/turboacc'
text = path.read_text()
marker = '\tconfig_get "fullcone6" "config" "fullcone6" "0"\n'
assert text.count(marker) == 1, 'TurboACC runtime changed'
text = text.replace(marker, marker + '''
	# Flow offload skips later netfilter hooks needed by UA3F and mwan3.
	if [ "$(uci -q get ua3f.enabled.enabled)" = "1" ] ||
	   { [ -x /etc/init.d/mwan3 ] && /etc/init.d/mwan3 enabled; }; then
		if [ "$sw_flow" = "1" ] || [ "$hw_flow" = "1" ] || [ "$sfe_flow" = "1" ]; then
			logger -t turboacc 'Flow offload disabled while UA3F or mwan3 is enabled'
		fi
		sw_flow=0
		hw_flow=0
		sfe_flow=0
	fi
''')
# This service changes firewall/sysctl/module state only, never DNS settings.
text = text.replace('\t\t/etc/init.d/dnsmasq restart >"/dev/null" 2>&1\n', '')
text = text.replace('\t/etc/init.d/dnsmasq restart >"/dev/null" 2>&1\n', '')
text = text.replace('DNSMASQ change', 'Firewall change').replace('DNSMASQ revert', 'Firewall revert').replace('DNSMASQ restart', 'Firewall restart')
path.write_text(text)
