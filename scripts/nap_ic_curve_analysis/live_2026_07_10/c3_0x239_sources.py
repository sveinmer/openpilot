#!/usr/bin/env python3
"""Tell 0x239-kilder (src) + range på CAN, OG rapporter lat/long-engasjement.
Offline rlog-modus. Kjøres i C3-venv med PYTHONPATH=/data/openpilot."""
import sys
sys.path.append("/data/openpilot")
from openpilot.tools.lib.logreader import LogReader

paths = sys.argv[1:]
DAS_LANES = 0x239
per_src = {}          # src -> {payload_hex: count}
eng = {"n":0, "lat":0, "long":0, "cruise":0, "enabled":0}

for p in paths:
    try:
        for msg in LogReader(p):
            w = msg.which()
            if w == "can":
                for c in msg.can:
                    if c.address == DAS_LANES:
                        d = per_src.setdefault(c.src, {})
                        h = bytes(c.dat).hex()
                        d[h] = d.get(h, 0) + 1
            elif w == "carState":
                eng["n"] += 1
                cs = msg.carState
                if getattr(cs, "cruiseState", None) and cs.cruiseState.enabled: eng["cruise"] += 1
            elif w == "controlsState" or w == "selfdriveState":
                pass
            elif w == "carControl":
                cc = msg.carControl
                eng["enabled"] += 1 if cc.enabled else 0
                if getattr(cc, "latActive", False): eng["lat"] += 1
                if getattr(cc, "longActive", False): eng["long"] += 1
    except Exception as e:
        print("  [warn] %s: %s" % (p, e))

def rng(h): return bytes.fromhex(h)[1]

print("\n=== 0x239-kilder på CAN ===")
if not per_src:
    print("  INGEN 0x239 — openpilot sender ikke, eller feil rlog")
for src in sorted(per_src):
    pl = per_src[src]
    ranges = sorted({rng(h) for h in pl})
    tot = sum(pl.values())
    print("  src=%-4d count=%-5d uniq=%-3d ranges=%s" % (src, tot, len(pl), ranges))
    for h,n in sorted(pl.items(), key=lambda x:-x[1])[:3]:
        print("     %-16s x%-5d range=%d" % (h, n, rng(h)))

print("\n=== Engasjement (carControl) ===")
n = max(eng["enabled"],1)
cc_n = eng["lat"] + 0
tot_cc = eng.get("enabled",0)
print("  carControl.enabled frames=%d" % eng["enabled"])
print("  latActive frames =%d" % eng["lat"])
print("  longActive frames=%d" % eng["long"])
print("  cruiseState.enabled (carState) =%d / %d" % (eng["cruise"], eng["n"]))

print("\n=== TOLKNING 0x239 ===")
src_ranges = {s: sorted({rng(h) for h in p}) for s,p in per_src.items()}
has50 = any(50 in r for r in src_ranges.values())
has1  = any(1 in r for r in src_ranges.values())
if has50 and has1:
    print("  TO signaturer: range=50 (openpilot) OG range=1 (fremmed idle) på CAN.")
    print("  => bilens/annen native 0x239 ligger på bussen. IKKE openpilot.")
elif has50:
    print("  KUN range=50 (openpilot) på CAN. Frisk + alene. Overstyring nedstrøms (gw).")
elif has1:
    print("  KUN range=1 og INGEN range=50 → openpilot sender ikke sin egen 0x239.")
else:
    print("  Ingen 50/1 — se payloads.")
