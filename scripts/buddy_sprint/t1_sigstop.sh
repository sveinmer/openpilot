#!/bin/bash
# T1 — SIGSTOP tinklaBuddy + 15s eth1 capture + SIGCONT.
# Hvis 0x239 fortsetter mens tinklaBuddy stopped → kilden er ekstern.
# Hvis 0x239 stopper → tinklaBuddy er kilden.
#
# Output: $OUTDIR/t1_sigstop_capture.json
#
# Trap-atomic: SIGCONT garantert sendt selv om script blir terminert.
# Tid: ~30s

set -euo pipefail
OUTDIR="${1:?usage: t1_sigstop.sh <outdir>}"
OUTFILE="$OUTDIR/t1_sigstop_capture.json"
echo "[T1] SIGSTOP-test → $OUTFILE"

# Run all in single SSH session to ensure trap fires on Buddy if our SSH dies
python3 /tmp/buddy_ssh.py "$(cat <<'REMOTE_EOF'
set -e
PID=$(pgrep -f tinklaBuddy | head -1)
if [ -z "$PID" ]; then
  echo '{"error": "tinklaBuddy not running"}'
  exit 1
fi
echo "[buddy] tinklaBuddy PID=$PID" >&2

# Trap on Buddy-side: always SIGCONT before exiting, even on signal
trap "echo pi | sudo -S kill -CONT $PID 2>/dev/null; echo '[buddy] TRAP SIGCONT sent' >&2" EXIT INT TERM HUP

echo '[buddy] sending SIGSTOP' >&2
echo pi | sudo -S kill -STOP $PID
sleep 0.5

# 15s capture under sudo (need AF_PACKET on eth1)
echo pi | sudo -S python3 <<PYEOF
import socket, struct, time, json, sys
s = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(0x0003))
s.bind(("eth1", 0))
s.settimeout(0.3)
end = time.time() + 15
from collections import Counter
data_239 = []
data_399 = []
arbs = Counter()
src_macs = Counter()
ts_first = {}
ts_last = {}
while time.time() < end:
    try: pkt, _ = s.recvfrom(2000)
    except: continue
    if struct.unpack("!H", pkt[12:14])[0] != 0x0800: continue
    ihl = (pkt[14] & 0xF) * 4
    if pkt[14 + 9] != 17: continue
    uo = 14 + ihl
    if struct.unpack("!H", pkt[uo + 2:uo + 4])[0] != 20101: continue
    ul = struct.unpack("!H", pkt[uo + 4:uo + 6])[0]
    p = pkt[uo + 8:uo + ul]
    if len(p) < 4: continue
    arb = struct.unpack(">H", p[2:4])[0]
    arbs[arb] += 1
    src = pkt[6:12].hex()
    if arb in (0x239, 0x399):
        src_macs[(arb, src)] += 1
        t = time.time()
        ts_first.setdefault(arb, t)
        ts_last[arb] = t
    if arb == 0x239: data_239.append(p[4:].hex())
    elif arb == 0x399: data_399.append(p[4:].hex())

out = {
    "test": "t1_sigstop_15s_capture_while_stopped",
    "duration_s": 15,
    "cnt_239": len(data_239),
    "unique_239": len(set(data_239)),
    "samples_239": data_239[:6],
    "cnt_399": len(data_399),
    "unique_399": len(set(data_399)),
    "top_arbs": [(f"0x{a:03X}", c) for a, c in arbs.most_common(15)],
    "src_macs": [(f"0x{a:03X}", m, c) for (a, m), c in sorted(src_macs.items())],
    "ts_first_seen": ts_first,
    "ts_last_seen": ts_last,
}
print(json.dumps(out, indent=2))
PYEOF

# trap will SIGCONT here
echo '[buddy] capture done, exiting (trap fires SIGCONT)' >&2
REMOTE_EOF
)" > "$OUTFILE" 2>&1

echo "[T1] Done → $OUTFILE"
echo "[T1] Result preview:"
python3 -c "
import json
try:
  with open('$OUTFILE') as f:
    out = json.load(f)
  print('  cnt_239 while stopped:', out.get('cnt_239', '?'), '  unique:', out.get('unique_239', '?'))
  print('  cnt_399 while stopped:', out.get('cnt_399', '?'), '  unique:', out.get('unique_399', '?'))
except Exception as e:
  print('  ERR:', e)
"
