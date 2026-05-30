#!/usr/bin/env python3
"""T5 — UDP inject-test til Buddy port 20101.

Sender 5 sandbox-CAN-frames med arb-ID 0x239 og unique markert payload
til Buddy's EtherCAN-input-port (20101). Capture eth1 før+under+etter
for å se om Buddy:
  (a) forwarder vår sandbox-payload uendret til eth1
  (b) replacerer vår payload med konstant 7001030b80101611
  (c) forkaster vår frame helt

Output: $OUTDIR/t5_inject.json

Tid: ~30s (5s pre-capture + 5s inject + 10s post-capture)

EtherCAN UDP-frame-format (per AGENT_D + Tinkla protocol-doc):
  [4 bytes header: bus(1), 0x00, id_hi(1), id_lo(1)] + [8 bytes CAN-data]
  = 12 bytes UDP payload total
"""

import json
import subprocess
import sys
import time
from pathlib import Path

OUTDIR = Path(sys.argv[1] if len(sys.argv) > 1 else f"/tmp/buddy_sprint_t5_{int(time.time())}")
OUTDIR.mkdir(parents=True, exist_ok=True)
OUTFILE = OUTDIR / "t5_inject.json"
print(f"[T5] Inject-test → {OUTFILE}")

# Sandbox payload — distinctive bytes that can't be confused with normal CAN data
SANDBOX_PAYLOAD = "DEADBEEF11223344"  # 8 bytes hex

# Construct EtherCAN UDP-frame: bus=0, 0x00, id_hi=0x02, id_lo=0x39 = arb 0x239
# Then 8 bytes payload
frame_hex = "00" + "00" + "02" + "39" + SANDBOX_PAYLOAD

# Buddy listens on UDP port 20101 (incoming EtherCAN from softpanda-side).
# We send from dev-box (must be on Buddy WiFi = 10.5.5.x subnet).

REMOTE_SCRIPT = f"""
set -e
# Start capture FIRST so we don't miss the inject
echo pi | sudo -S nohup timeout 25 tcpdump -i eth1 -nn -s 0 -w /tmp/t5_eth1.pcap 'udp port 20101 or udp port 20201' >/dev/null 2>&1 &
TCPPID=$!
trap "echo pi | sudo -S kill $TCPPID 2>/dev/null" EXIT INT TERM HUP
sleep 3

# Inject 5 frames at 100ms interval via Python (Buddy itself has python3)
python3 <<PYEOF
import socket, time
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
frame = bytes.fromhex("{frame_hex}")
# Send to Buddy's own loopback for port 20101 (which is what tinklaBuddy listens on)
for i in range(5):
    s.sendto(frame, ("127.0.0.1", 20101))
    print(f"injected frame {{i+1}}: 0x239 payload {SANDBOX_PAYLOAD}", flush=True)
    time.sleep(0.1)
PYEOF

# Wait remaining capture window
sleep 12

# Kill tcpdump (or let timeout fire)
echo pi | sudo -S kill -INT $TCPPID 2>/dev/null || true
sleep 1

ls -la /tmp/t5_eth1.pcap

# Send pcap home via base64
echo "===PCAP_BEGIN==="
base64 /tmp/t5_eth1.pcap
echo "===PCAP_END==="
echo pi | sudo -S rm /tmp/t5_eth1.pcap
"""

proc = subprocess.run(
    ['python3', '/tmp/buddy_ssh.py', REMOTE_SCRIPT],
    capture_output=True, text=True, timeout=60
)

if proc.returncode != 0:
    print(f"[T5] ERROR: buddy_ssh.py exit {proc.returncode}", file=sys.stderr)
    print(proc.stderr, file=sys.stderr)
    sys.exit(1)

out = proc.stdout
b = out.find("===PCAP_BEGIN===")
e = out.find("===PCAP_END===")
if b == -1 or e == -1:
    print("[T5] ERROR: pcap markers missing", file=sys.stderr)
    sys.exit(1)

import base64
raw = base64.b64decode(out[b + 16:e].strip())
pcap_path = OUTDIR / "t5_eth1.pcap"
pcap_path.write_bytes(raw)
print(f"  ✓ pcap: {len(raw)} bytes")

# Analyze: count 0x239 frames with our DEADBEEF-payload vs constant 7001030b...
import struct as st
sandbox_payload = bytes.fromhex(SANDBOX_PAYLOAD)
constant_payload = bytes.fromhex("7001030b80101611")

sandbox_seen = 0
constant_seen = 0
other_239 = []
all_239_payloads = []

with open(pcap_path, 'rb') as f:
    header = f.read(24)
    magic = st.unpack('<I', header[:4])[0]
    if magic not in (0xa1b2c3d4, 0xd4c3b2a1):
        print(f"[T5] ERROR: bad magic {hex(magic)}", file=sys.stderr)
        sys.exit(1)
    be = magic == 0xd4c3b2a1
    ep = '>' if be else '<'
    while True:
        rec = f.read(16)
        if len(rec) < 16: break
        ts_sec, ts_usec, caplen, origlen = st.unpack(f'{ep}IIII', rec)
        pkt = f.read(caplen)
        if len(pkt) < caplen: break
        if len(pkt) < 14 + 20 + 8: continue
        if st.unpack('!H', pkt[12:14])[0] != 0x0800: continue
        ihl = (pkt[14] & 0xF) * 4
        if pkt[14 + 9] != 17: continue
        uo = 14 + ihl
        ulen = st.unpack('!H', pkt[uo + 4:uo + 6])[0]
        payload = pkt[uo + 8:uo + ulen]
        if len(payload) < 12: continue
        arb = st.unpack('>H', payload[2:4])[0]
        if arb != 0x239: continue
        body = payload[4:12]
        all_239_payloads.append(body.hex())
        if body == sandbox_payload:
            sandbox_seen += 1
        elif body == constant_payload:
            constant_seen += 1
        else:
            other_239.append(body.hex())

result = {
    "test": "t5_inject_sandbox_0x239",
    "injected_count": 5,
    "injected_payload": SANDBOX_PAYLOAD,
    "sandbox_seen_on_eth1": sandbox_seen,
    "constant_seen_on_eth1": constant_seen,
    "other_239_payloads_seen": len(set(other_239)),
    "other_239_samples": list(set(other_239))[:5],
    "total_239_on_eth1": len(all_239_payloads),
    "interpretation": (
        "Buddy forwards our sandbox payload" if sandbox_seen > 0 else
        "Buddy DROPS our sandbox payload entirely (replaces with constant)" if sandbox_seen == 0 and constant_seen > 0 else
        "Buddy drops + nothing else"
    ),
}
OUTFILE.write_text(json.dumps(result, indent=2))

print(f"[T5] Done → {OUTFILE}")
for k, v in result.items():
    if k not in ("other_239_samples",):
        print(f"  {k}: {v}")
