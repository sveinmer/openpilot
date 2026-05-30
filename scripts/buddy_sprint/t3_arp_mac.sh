#!/bin/bash
# T3 — MAC-eier-identifikasjon: hvem eier 0000a7010203 på Buddy eth1?
# Output: $OUTDIR/t3_arp_mac.txt
#
# Tid: ~2 min (arp-scan over 254 IPs på 192.168.90.0/24)

set -euo pipefail
OUTDIR="${1:?usage: t3_arp_mac.sh <outdir>}"
OUTFILE="$OUTDIR/t3_arp_mac.txt"
echo "[T3] MAC-ID resolution → $OUTFILE"

python3 /tmp/buddy_ssh.py "
echo '=== eth1 status ==='
ip -s a show eth1 2>/dev/null || echo 'eth1 not found'
ip a show eth1 | grep ether 2>/dev/null

echo
echo '=== eth1 own MAC (for comparison) ==='
cat /sys/class/net/eth1/address 2>/dev/null

echo
echo '=== current ARP cache (eth1) ==='
ip neigh show dev eth1 2>/dev/null

echo
echo '=== arp-scan style discovery (192.168.90.0/24) ==='
echo pi | sudo -S sh -c '
for i in \$(seq 100 110); do
  (ping -c 1 -W 1 -I eth1 192.168.90.\$i > /dev/null 2>&1; arp -an | grep 192.168.90.\$i) &
done
wait
'

echo
echo '=== final ARP cache after probe ==='
ip neigh show dev eth1 2>/dev/null
arp -an 2>/dev/null | grep -E 'eth1|192.168.90'

echo
echo '=== look for MAC 00:00:a7:01:02:03 in any cache ==='
ip neigh 2>/dev/null | grep -i 'a7:01:02:03'
arp -an 2>/dev/null | grep -i 'a7:01:02:03'

echo
echo '=== tcpdump 3s on eth1 to see who is actively sending ==='
echo pi | sudo -S timeout 3 tcpdump -i eth1 -nn -e -c 30 2>/dev/null | head -40
" > "$OUTFILE" 2>&1

echo "[T3] Done → $OUTFILE"
echo "[T3] Key finding lines:"
grep -E '(ether|a7:|192.168.90)' "$OUTFILE" | head -10
