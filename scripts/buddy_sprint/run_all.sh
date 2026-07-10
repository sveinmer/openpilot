#!/bin/bash
# Buddy live-sprint orchestrator.
#
# Kjøre-rekkefølge: T2 → T3 → T7 (fast/safe) → T1 → T4 → T5 → T6 (analyse).
#
# Pre-conditions:
#   1. Dev-box må være på Buddy WiFi (10.5.5.x) - du må fysisk koble til
#   2. /tmp/buddy_ssh.py må eksistere (pexpect-wrapper for pi@10.5.5.1, BUDDY_PASS)
#   3. Test connectivity: python3 /tmp/buddy_ssh.py "hostname" → tb-XXXX-Tesla
#   4. C3 onroad (panda emitterer 0x239 vi observerer nedstrøms)
#
# Tid: ~5 min total

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TS=$(date +%Y%m%d_%H%M%S)
OUTDIR="/tmp/buddy_sprint_$TS"
mkdir -p "$OUTDIR"

echo "════════════════════════════════════════════════════════════════════"
echo "Buddy live-sprint $TS"
echo "Output dir: $OUTDIR"
echo "════════════════════════════════════════════════════════════════════"
echo

# Sanity check: Buddy reachable
echo "▸ Connectivity check"
if ! python3 /tmp/buddy_ssh.py "hostname" 2>&1 | grep -qE "tb-|tinkla"; then
  echo "FAIL: Buddy ikke nåbar via /tmp/buddy_ssh.py"
  echo "Pre-condition: dev-box må være på Buddy WiFi (SSID tinklaAP, password ?)"
  echo "Sjekk: ping 10.5.5.1; python3 /tmp/buddy_ssh.py 'hostname'"
  exit 1
fi
echo "  ✓ Buddy reachable"
echo

# T2 — Inventory (basis, snabbt)
echo "▸ T2 Inventory"
bash "$SCRIPT_DIR/t2_inventory.sh" "$OUTDIR"
echo

# T3 — MAC-ID resolution
echo "▸ T3 ARP / MAC-resolusjon"
bash "$SCRIPT_DIR/t3_arp_mac.sh" "$OUTDIR"
echo

# T7 — Web-UI (mens vi har tilkobling)
echo "▸ T7 Web-UI"
bash "$SCRIPT_DIR/t7_web_ui.sh" "$OUTDIR"
echo

# T1 — SIGSTOP-test (kritisk avgjørelse-punkt)
echo "▸ T1 SIGSTOP-test (~30s, Buddy fryses midlertidig)"
read -p "Trykk ENTER for å fortsette (eller Ctrl-C for å abort)" _
bash "$SCRIPT_DIR/t1_sigstop.sh" "$OUTDIR"
echo

# T4 — Dual capture
echo "▸ T4 Dual capture eth0+eth1 (30s)"
python3 "$SCRIPT_DIR/t4_dual_capture.py" "$OUTDIR"
echo

# T5 — UDP inject
echo "▸ T5 Sandbox-UDP-inject (sender 5 fake 0x239 til Buddy port 20101)"
read -p "Trykk ENTER for å fortsette" _
python3 "$SCRIPT_DIR/t5_inject_test.py" "$OUTDIR"
echo

# T6 — Post-analyse av T4
echo "▸ T6 0x399 vs 0x239 analyse (offline, T4 capture)"
python3 "$SCRIPT_DIR/t6_0x399_vs_0x239.py" "$OUTDIR"
echo

# Summary
echo "════════════════════════════════════════════════════════════════════"
echo "Sprint complete. Results:"
echo "  $OUTDIR/"
echo "════════════════════════════════════════════════════════════════════"
ls -la "$OUTDIR/"
echo
echo "Next: les $OUTDIR/t6_analysis.txt + t1_sigstop_capture.json for tolkning."
