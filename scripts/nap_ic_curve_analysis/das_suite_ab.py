#!/usr/bin/env python3
"""Full DAS-suite A/B: alle sendcan-adresser, per-byte verdifordeling.

Sammenligner Tinkla-aera (virket) mot NAP naa (stuck) for aa finne
felt som systematisk avviker og kan gate Buddys lane-rendering.
"""
import sys, glob, json, os
from collections import Counter, defaultdict
import numpy as np
from openpilot.tools.lib.logreader import LogReader

BASE = "/data/media/0/realdata"

def collect(route, seg_limit=12):
  segs = sorted(glob.glob(f"{BASE}/{route}--*"), key=lambda p: int(p.rsplit("--", 1)[1]))[:seg_limit]
  per_addr = defaultdict(lambda: {"n": 0, "bytes": [Counter() for _ in range(8)], "buses": Counter()})
  for seg in segs:
    rl = seg + "/rlog.zst" if os.path.exists(seg + "/rlog.zst") else seg + "/rlog"
    if not os.path.exists(rl):
      continue
    try:
      lr = LogReader(rl)
      for msg in lr:
        if msg.which() != "sendcan":
          continue
        for c in msg.sendcan:
          e = per_addr[c.address]
          e["n"] += 1
          e["buses"][c.src] += 1
          d = bytes(c.dat)
          for i, b in enumerate(d[:8]):
            e["bytes"][i][b] += 1
    except Exception as ex:
      print(f"# skip {seg}: {ex}", file=sys.stderr)
  out = {}
  for addr, e in per_addr.items():
    out[hex(addr)] = {
      "n": e["n"],
      "buses": dict(e["buses"]),
      "bytes": [
        {"uniq": len(cnt), "top": [[v, round(c / max(e['n'], 1), 3)] for v, c in cnt.most_common(3)]}
        for cnt in e["bytes"]
      ],
    }
  return out

if __name__ == "__main__":
  era_a = collect(sys.argv[1])   # Tinkla (virket)
  era_b = collect(sys.argv[2])   # NAP (stuck)
  print(json.dumps({"A_virket": sys.argv[1], "B_stuck": sys.argv[2]}))
  addrs = sorted(set(era_a) | set(era_b), key=lambda h: int(h, 16))
  for a in addrs:
    ea, eb = era_a.get(a), era_b.get(a)
    if ea is None or eb is None:
      print(json.dumps({"addr": a, "KUN_I": "A(virket)" if ea else "B(stuck)",
                        "n": (ea or eb)["n"], "buses": (ea or eb)["buses"]}))
      continue
    diffs = []
    for i in range(8):
      ta = {v for v, _ in ea["bytes"][i]["top"]}
      tb = {v for v, _ in eb["bytes"][i]["top"]}
      # flagg byte hvis dominant verdi-sett er disjunkt eller uniq-klasse skifter
      if ea["bytes"][i]["uniq"] <= 4 and eb["bytes"][i]["uniq"] <= 4 and not (ta & tb):
        diffs.append({"byte": i, "A_top": ea["bytes"][i]["top"], "B_top": eb["bytes"][i]["top"]})
      elif (ea["bytes"][i]["uniq"] <= 2) != (eb["bytes"][i]["uniq"] <= 2):
        diffs.append({"byte": i, "A_uniq": ea["bytes"][i]["uniq"], "B_uniq": eb["bytes"][i]["uniq"],
                      "A_top": ea["bytes"][i]["top"][:2], "B_top": eb["bytes"][i]["top"][:2]})
    print(json.dumps({"addr": a, "nA": ea["n"], "nB": eb["n"],
                      "busA": ea["buses"], "busB": eb["buses"],
                      "byte_diffs": diffs}))
