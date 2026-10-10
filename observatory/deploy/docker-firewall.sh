#!/usr/bin/env bash
# docker-firewall.sh — let only Cloudflare reach the published web ports.
#
# ufw does not see traffic to Docker-published ports: Docker writes its own
# iptables rules, which run before ufw's. Found 2026-10-10: with ufw allowing
# 80/443 only from Cloudflare, anyone could still connect to Caddy directly.
# So the same rule goes into DOCKER-USER, the chain Docker leaves to the
# administrator and checks first. Run at boot after Docker
# (plover-docker-firewall.service) and safe to re-run.
#
# Cloudflare's ranges are fetched fresh; the last good list is kept and used
# when the fetch fails, and with neither the script refuses to run rather
# than open or close the site blindly.
set -euo pipefail
CACHE=/opt/plover/cloudflare-ips
mkdir -p "$CACHE"
for v in 4 6; do
  if list=$(curl -fsS -m 20 "https://www.cloudflare.com/ips-v$v/") && [ -n "$list" ]; then
    echo "$list" > "$CACHE/v$v"
  fi
  [ -s "$CACHE/v$v" ] || { echo "no Cloudflare v$v ranges, fetched or cached"; exit 1; }
done
WAN=$(ip route show default | awk '{print $5; exit}')

apply() {  # apply <iptables|ip6tables> <ranges file>
  local ipt=$1 ranges=$2
  $ipt -L DOCKER-USER -n >/dev/null 2>&1 || return 0
  $ipt -N PLOVER-CF 2>/dev/null || $ipt -F PLOVER-CF
  while read -r r; do
    [ -n "$r" ] && $ipt -A PLOVER-CF -s "$r" -j RETURN
  done < "$ranges"
  $ipt -A PLOVER-CF -j DROP
  # one jump, first in the chain: new traffic arriving on the public
  # interface for the web ports goes through the Cloudflare list
  while $ipt -D DOCKER-USER -i "$WAN" -p tcp -m multiport --dports 80,443 -j PLOVER-CF 2>/dev/null; do :; done
  $ipt -I DOCKER-USER 1 -i "$WAN" -p tcp -m multiport --dports 80,443 -j PLOVER-CF
}
apply iptables "$CACHE/v4"
apply ip6tables "$CACHE/v6"
echo "web ports open to Cloudflare only on $WAN ($(wc -l < "$CACHE/v4") v4 + $(wc -l < "$CACHE/v6") v6 ranges)"
