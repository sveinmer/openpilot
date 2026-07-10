#!/bin/bash
# T2 — Buddy live-inventory: prosesser, sockets, nett-topologi.
# Output: $OUTDIR/t2_inventory/*.txt
#
# Krav: Buddy nåbar via /tmp/buddy_ssh.py (pi@10.5.5.1 (passord: BUDDY_PASS, lokal memory))
# Tid: <1 min

set -euo pipefail
OUTDIR="${1:?usage: t2_inventory.sh <outdir>}"
mkdir -p "$OUTDIR/t2_inventory"
echo "[T2] Inventory → $OUTDIR/t2_inventory/"

run() {
  local label="$1" cmd="$2"
  echo "  • $label"
  python3 /tmp/buddy_ssh.py "$cmd" > "$OUTDIR/t2_inventory/${label}.txt" 2>&1 || true
}

run ps_auxf            "ps auxf"
run ps_e_o_pid_comm    "ps -e -o pid,ppid,user,etimes,comm"
run netstat_anup       "netstat -anup 2>/dev/null || ss -anup"
run lsof_udp           "ls -la /proc/*/fd/* 2>/dev/null | grep socket: | head -50; echo ---; (which lsof && lsof -i UDP) || echo lsof not available"
run ip_a               "ip a"
run ip_route           "ip route"
run arp_an             "arp -an 2>/dev/null || ip neigh"
run uname              "uname -a; cat /etc/os-release; cat /etc/hostname"
run uptime             "uptime; date"
run tinklabuddy_fds    "ls -la /proc/\$(pgrep -f tinklaBuddy | head -1)/fd 2>/dev/null"
run tinklabuddy_args   "cat /proc/\$(pgrep -f tinklaBuddy | head -1)/cmdline 2>/dev/null | tr '\\0' ' '; echo"
run tinklabuddy_status "cat /proc/\$(pgrep -f tinklaBuddy | head -1)/status 2>/dev/null | head -30"
run can_interfaces     "ip link show; ls /sys/class/net/"
run firmware_version   "cat /opt/tinkla/version* 2>/dev/null; ls /opt/tinkla/ 2>/dev/null"
run buddy_settings     "cat /home/pi/.tinklaBuddy 2>/dev/null | head -50; ls /home/pi/ 2>/dev/null"

echo "[T2] Done"
