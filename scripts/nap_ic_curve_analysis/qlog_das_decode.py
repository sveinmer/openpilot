#!/usr/bin/env python3
"""Dekod DAS-state-felter fra qlogs/rlogs — sammenlign fungerende 06-20 vs naa.

Felter: 0x659 byte0 (op_status+flagg), byte1 (acc_speed_kph), byte2 (adaptive_cruise
+hands_on), byte3 (cc_state<<6|pcc<<5|alca), 0x389 byte0 (cruise_speed),
0x239 C2-saturering, engasjement.
"""
import sys, glob, json
from collections import Counter
import numpy as np
from openpilot.tools.lib.logreader import LogReader

def analyze(paths, label):
  b659 = [Counter() for _ in range(6)]
  b389_0 = Counter()
  c2 = []
  n659 = 0
  en_n = en_y = 0
  v = []
  for p in sorted(paths):
    try:
      lr = LogReader(p)
    except Exception as e:
      print(f"# skip {p}: {e}", file=sys.stderr)
      continue
    try:
      for msg in lr:
        w = msg.which()
        if w == "sendcan":
          for c in msg.sendcan:
            if c.address == 0x659:
              d = bytes(c.dat)
              n659 += 1
              for i in range(min(6, len(d))):
                b659[i][d[i]] += 1
            elif c.address == 0x389:
              d = bytes(c.dat)
              if d:
                b389_0[d[0]] += 1
            elif c.address == 569:
              d = bytes(c.dat)
              if len(d) >= 6:
                c2.append(d[4] * 2e-05 - 0.0025)
        elif w == "selfdriveState":
          en_n += 1; en_y += int(msg.selfdriveState.enabled)
        elif w == "carState":
          v.append(msg.carState.vEgo)
    except Exception as e:
      print(f"# abort {p}: {e}", file=sys.stderr)

  c2 = np.array(c2)
  mov_sat = float((np.abs(c2) >= 0.0025 - 1e-9).mean()) if len(c2) else None
  res = {
    "label": label, "n_659": n659, "n_239": len(c2),
    "enabled_frac": round(en_y / max(en_n, 1), 3),
    "v_mean_kmh": round(float(np.mean(v)) * 3.6, 1) if v else None,
    "sat_frac_C2_alle": round(mov_sat, 3) if mov_sat is not None else None,
    "b659_acc_speed_byte1": [[v_, round(c / max(n659, 1), 3)] for v_, c in b659[1].most_common(6)],
    "b659_byte0": [[v_, round(c / max(n659, 1), 3)] for v_, c in b659[0].most_common(6)],
    "b659_byte2": [[v_, round(c / max(n659, 1), 3)] for v_, c in b659[2].most_common(4)],
    "b659_byte3_ccstate": [[v_, round(c / max(n659, 1), 3)] for v_, c in b659[3].most_common(6)],
    "b389_byte0": [[v_, round(c / max(sum(b389_0.values()), 1), 3)] for v_, c in b389_0.most_common(6)],
  }
  print(json.dumps(res))

if __name__ == "__main__":
  analyze(glob.glob(sys.argv[1]), sys.argv[2])
