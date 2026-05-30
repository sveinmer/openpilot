#!/usr/bin/env python3
"""T4 — Parallell capture eth0 OG eth1 på Buddy, 30s.

Beviser hva som kommer INN (eth0 fra chassis-side) vs OUT (eth1 til IC-side).

Output: $OUTDIR/t4_dual_capture/{eth0.pcap, eth1.pcap, summary.json}

Tid: ~35s (30s capture + 5s setup/teardown)
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

OUTDIR = Path(sys.argv[1] if len(sys.argv) > 1 else f"/tmp/buddy_sprint_t4_{int(time.time())}")
OUTDIR = OUTDIR / "t4_dual_capture"
OUTDIR.mkdir(parents=True, exist_ok=True)
print(f"[T4] Dual capture → {OUTDIR}/")

# We use a single SSH session that backgrounds tcpdump on both interfaces in parallel,
# waits 30s, kills tcpdump, then rsyncs pcaps back via base64 (avoids requiring rsync
# on Buddy). Simpler: capture, then scp.

REMOTE_SCRIPT = r"""
set -e
OUTBASE=/tmp/buddy_dual_$$
mkdir -p $OUTBASE

# Run tcpdump in background on both interfaces. Capture UDP port 20101 (CAN-frames over EtherCAN).
# -i any would mix, so we run two separately. -B 4096 buffer, -s 0 full packet.
echo pi | sudo -S nohup tcpdump -i eth0 -nn -s 0 -B 4096 -w $OUTBASE/eth0.pcap 'udp port 20101 or udp port 20201 or udp port 31415 or udp port 31515' >/dev/null 2>&1 &
PID0=$!
echo pi | sudo -S nohup tcpdump -i eth1 -nn -s 0 -B 4096 -w $OUTBASE/eth1.pcap 'udp port 20101 or udp port 20201 or udp port 31415 or udp port 31515' >/dev/null 2>&1 &
PID1=$!
sleep 0.5
echo "[buddy] tcpdump started (eth0=$PID0, eth1=$PID1)" >&2

# Trap to clean up if SSH dies
trap "echo pi | sudo -S kill $PID0 $PID1 2>/dev/null; echo '[buddy] TRAP killed tcpdump' >&2" EXIT INT TERM HUP

# 30s capture
sleep 30

# Stop tcpdump
echo pi | sudo -S kill -INT $PID0 $PID1 2>/dev/null
sleep 1

# Show sizes
ls -la $OUTBASE/

# Base64 both pcaps to stdout for retrieval
echo "===PCAP_ETH0_BEGIN==="
base64 $OUTBASE/eth0.pcap
echo "===PCAP_ETH0_END==="
echo "===PCAP_ETH1_BEGIN==="
base64 $OUTBASE/eth1.pcap
echo "===PCAP_ETH1_END==="

# Cleanup remote
echo pi | sudo -S rm -rf $OUTBASE
"""

# Execute via buddy_ssh.py
import tempfile
proc = subprocess.run(
    ['python3', '/tmp/buddy_ssh.py', REMOTE_SCRIPT],
    capture_output=True, text=True, timeout=60
)

if proc.returncode != 0:
    print(f"[T4] ERROR: buddy_ssh.py exit {proc.returncode}", file=sys.stderr)
    print(proc.stderr, file=sys.stderr)
    sys.exit(1)

# Parse output to extract base64-encoded pcaps
out = proc.stdout

def extract(blob, tag):
    begin = blob.find(f"==={tag}_BEGIN===")
    end = blob.find(f"==={tag}_END===")
    if begin == -1 or end == -1:
        return None
    return blob[begin + len(f"==={tag}_BEGIN==="):end].strip()

import base64

for tag, fname in [("PCAP_ETH0", "eth0.pcap"), ("PCAP_ETH1", "eth1.pcap")]:
    b64 = extract(out, tag)
    if b64 is None:
        print(f"[T4] WARN: {tag} not found in output", file=sys.stderr)
        continue
    raw = base64.b64decode(b64)
    (OUTDIR / fname).write_bytes(raw)
    print(f"  ✓ {fname}: {len(raw)} bytes")

# Analyze with scapy or dpkt if available; fallback to raw parsing.
print(f"[T4] Analyzing pcaps...")

def analyze_pcap(path):
    """Parse pcap directly for UDP-EtherCAN-frame summary."""
    import struct as st
    from collections import Counter
    arbs = Counter()
    data_per_arb = {}
    src_macs_per_arb = {}
    dst_macs_per_arb = {}
    with open(path, 'rb') as f:
        header = f.read(24)
        # Validate magic
        magic = st.unpack('<I', header[:4])[0]
        if magic != 0xa1b2c3d4 and magic != 0xd4c3b2a1:
            return {"error": f"bad magic {hex(magic)}"}
        be = magic == 0xd4c3b2a1
        ep = '>' if be else '<'
        while True:
            rec = f.read(16)
            if len(rec) < 16:
                break
            ts_sec, ts_usec, caplen, origlen = st.unpack(f'{ep}IIII', rec)
            pkt = f.read(caplen)
            if len(pkt) < caplen:
                break
            # Ethernet header: 14 bytes
            if len(pkt) < 14 + 20 + 8: continue
            if st.unpack('!H', pkt[12:14])[0] != 0x0800: continue  # IPv4
            ihl = (pkt[14] & 0x0F) * 4
            proto = pkt[14 + 9]
            if proto != 17: continue  # UDP
            uo = 14 + ihl
            dport = st.unpack('!H', pkt[uo + 2:uo + 4])[0]
            ulen = st.unpack('!H', pkt[uo + 4:uo + 6])[0]
            payload = pkt[uo + 8:uo + ulen]
            if len(payload) < 4: continue
            arb = st.unpack('>H', payload[2:4])[0]
            arbs[arb] += 1
            src = pkt[6:12].hex()
            dst = pkt[0:6].hex()
            data_per_arb.setdefault(arb, set()).add(payload[4:].hex())
            src_macs_per_arb.setdefault(arb, Counter())[src] += 1
            dst_macs_per_arb.setdefault(arb, Counter())[dst] += 1
    summary = {
        "total_frames": sum(arbs.values()),
        "unique_arbs": len(arbs),
        "arb_breakdown": [
            {
                "arb": f"0x{a:03X}",
                "count": c,
                "unique_payloads": len(data_per_arb.get(a, set())),
                "src_macs": [(m, n) for m, n in src_macs_per_arb[a].most_common(3)],
                "dst_macs": [(m, n) for m, n in dst_macs_per_arb[a].most_common(3)],
                "sample_payloads": list(data_per_arb.get(a, set()))[:3],
            }
            for a, c in arbs.most_common(20)
        ],
    }
    return summary

summary = {
    "test": "t4_dual_capture_eth0_and_eth1",
    "duration_s": 30,
    "eth0": analyze_pcap(OUTDIR / "eth0.pcap"),
    "eth1": analyze_pcap(OUTDIR / "eth1.pcap"),
}
(OUTDIR / "summary.json").write_text(json.dumps(summary, indent=2))

print(f"[T4] Done → {OUTDIR}/summary.json")
print(f"[T4] eth0 frames: {summary['eth0'].get('total_frames', 'ERR')}")
print(f"[T4] eth1 frames: {summary['eth1'].get('total_frames', 'ERR')}")
print(f"[T4] eth0 0x239 unique: {next((b['unique_payloads'] for b in summary['eth0'].get('arb_breakdown', []) if b['arb'] == '0x239'), 'absent')}")
print(f"[T4] eth1 0x239 unique: {next((b['unique_payloads'] for b in summary['eth1'].get('arb_breakdown', []) if b['arb'] == '0x239'), 'absent')}")
