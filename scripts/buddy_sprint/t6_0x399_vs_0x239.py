#!/usr/bin/env python3
"""T6 — Post-analyse av T4 dual-capture: 0x399 vs 0x239 paritets-sjekk.

T4 har capture av begge eth0 (chassis-side input) og eth1 (IC-side output).
Vi vet at:
  - 0x399 viser 32 unique payloads på eth1 (passerer fritt)
  - 0x239 viser 1 unique payload på eth1 (konstant)

Spørsmål: hva er forskjellen i Buddy's behandling?

Hypoteser:
  H1: 0x399 kommer fra eth0 og forwardes; 0x239 kommer ikke fra eth0
  H2: Begge kommer fra eth0 men Buddy MITM-replacer 0x239
  H3: 0x399 kommer fra et annet sted (lokal generering) ikke eth0

Output: $OUTDIR/t6_analysis.txt

Tid: <10s (offline analyse av T4 pcaps)
"""

import json
import struct as st
import sys
from collections import Counter
from pathlib import Path

OUTDIR = Path(sys.argv[1] if len(sys.argv) > 1 else sys.exit("usage: t6_0x399_vs_0x239.py <outdir>"))
T4_DIR = OUTDIR / "t4_dual_capture"
if not T4_DIR.exists():
    sys.exit(f"T4 output missing: {T4_DIR}")

OUTFILE = OUTDIR / "t6_analysis.txt"
print(f"[T6] Analyzing T4 captures for 0x399 vs 0x239 → {OUTFILE}")


def parse_pcap_for_arbs(path, target_arbs):
    """Returns {arb_id: [(timestamp_us, src_mac_hex, dst_mac_hex, payload_hex), ...]}"""
    out = {a: [] for a in target_arbs}
    with open(path, 'rb') as f:
        header = f.read(24)
        magic = st.unpack('<I', header[:4])[0]
        if magic not in (0xa1b2c3d4, 0xd4c3b2a1):
            return out
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
            if len(payload) < 4: continue
            arb = st.unpack('>H', payload[2:4])[0]
            if arb not in target_arbs: continue
            body = payload[4:].hex() if len(payload) > 4 else ""
            src = pkt[6:12].hex()
            dst = pkt[0:6].hex()
            ts = ts_sec * 1_000_000 + ts_usec
            out[arb].append((ts, src, dst, body))
    return out


eth0 = parse_pcap_for_arbs(T4_DIR / "eth0.pcap", {0x239, 0x399, 0x348, 0x488})
eth1 = parse_pcap_for_arbs(T4_DIR / "eth1.pcap", {0x239, 0x399, 0x348, 0x488})


def summarize(frames):
    if not frames:
        return {"count": 0, "unique_payloads": 0, "src_macs": [], "dst_macs": [], "samples": []}
    payloads = [f[3] for f in frames]
    src_macs = Counter(f[1] for f in frames)
    dst_macs = Counter(f[2] for f in frames)
    return {
        "count": len(frames),
        "unique_payloads": len(set(payloads)),
        "src_macs": [(m, n) for m, n in src_macs.most_common(3)],
        "dst_macs": [(m, n) for m, n in dst_macs.most_common(3)],
        "samples": list(set(payloads))[:4],
    }


lines = []
lines.append("=" * 70)
lines.append("T6 — 0x399 vs 0x239 paritets-analyse (T4 capture-data)")
lines.append("=" * 70)
lines.append("")
for arb in [0x239, 0x399, 0x348, 0x488]:
    lines.append(f"### 0x{arb:03X}")
    lines.append(f"  eth0 (chassis-side input):  {json.dumps(summarize(eth0[arb]), indent=4)}")
    lines.append(f"  eth1 (IC-side output):      {json.dumps(summarize(eth1[arb]), indent=4)}")
    lines.append("")

# Crossover-analyse: hvis 0x399-payload på eth1 = payload som ankom eth0, så er det forward
# Hvis ikke, så er det MITM-replace eller separat generert
def crossover_match(in_frames, out_frames, label):
    in_set = set(f[3] for f in in_frames)
    out_set = set(f[3] for f in out_frames)
    forwarded = in_set & out_set
    only_in = in_set - out_set
    only_out = out_set - in_set
    lines.append(f"### {label} payload-overlap eth0 → eth1")
    lines.append(f"  unique on eth0: {len(in_set)}")
    lines.append(f"  unique on eth1: {len(out_set)}")
    lines.append(f"  forwarded (eth0 ∩ eth1): {len(forwarded)}")
    lines.append(f"  only on eth0 (filtered): {len(only_in)}")
    lines.append(f"  only on eth1 (locally generated or MITM): {len(only_out)}")
    if only_out:
        lines.append(f"  Sample only-on-eth1: {list(only_out)[:3]}")
    lines.append("")

crossover_match(eth0[0x239], eth1[0x239], "0x239")
crossover_match(eth0[0x399], eth1[0x399], "0x399")
crossover_match(eth0[0x348], eth1[0x348], "0x348")

# Final conclusion
lines.append("=" * 70)
lines.append("FORTOLKNING")
lines.append("=" * 70)
e0_239 = len(eth0[0x239])
e1_239 = len(eth1[0x239])
e0_399 = len(eth0[0x399])
e1_399 = len(eth1[0x399])
e1_239_unique = len(set(f[3] for f in eth1[0x239]))
e1_399_unique = len(set(f[3] for f in eth1[0x399]))

if e0_239 == 0 and e1_239 > 0:
    lines.append("• 0x239 kommer IKKE inn på eth0, men kommer ut på eth1.")
    lines.append("  → Kilden er LOKAL GENERERING på Buddy (eller annen ECU på eth1-segmentet)")
    lines.append("  → NAP/Tinkla-stack innspiller IKKE 0x239 til Buddy via eth0")
elif e0_239 > 0 and e1_239 > 0 and e1_239_unique == 1:
    lines.append("• 0x239 kommer inn på eth0 (variabel) men ut på eth1 (konstant)")
    lines.append("  → Buddy MITM-REPLACER 0x239 med konstant payload")
elif e0_239 > 0 and e1_239 > 0:
    lines.append("• 0x239 forwardes uendret eth0 → eth1")

if e0_399 == 0 and e1_399 > 0:
    lines.append("• 0x399 kommer IKKE inn på eth0, men ut på eth1.")
    lines.append("  → Kilden er LOKAL GENERERING")
elif e0_399 > 0 and e1_399 > 0:
    lines.append("• 0x399 kommer inn på eth0 og ut på eth1 (forward eller MITM)")

OUTFILE.write_text("\n".join(lines))
print(OUTFILE.read_text())
