#!/usr/bin/env python3
"""Runde 3: er position-dataen frisk, eller odelegger kubikk-fitten den?

- y[0]-distribusjon (banen skal starte i bilen: ~0)
- direkte punkt-kurvatur ved ~30 m (3-punkts andre-differanse, ingen polyfit)
  vs IMU-fasit med lag-sweep
- polyfit-residual naer bilen (hvor mye fitten bommer der IC-en tegner)
"""
import sys, glob, json
import numpy as np
from openpilot.tools.lib.logreader import LogReader

BASE = "/data/media/0/realdata"

def curvature_at(x, y, target_x):
  """3-punkts kurvatur rundt naermeste punkt til target_x."""
  i = int(np.argmin(np.abs(x - target_x)))
  if i < 1 or i >= len(x) - 1:
    return None
  x0, x1, x2 = x[i - 1], x[i], x[i + 1]
  if x2 - x0 < 1.0:
    return None
  # andre-derivert via divided differences
  d1 = (y[i] - y[i - 1]) / (x1 - x0)
  d2 = (y[i + 1] - y[i]) / (x2 - x1)
  ypp = 2 * (d2 - d1) / (x2 - x0)
  yp = (y[i + 1] - y[i - 1]) / (x2 - x0)
  return ypp / (1 + yp * yp) ** 1.5

def analyze_route(route, seg_limit=40):
  segs = sorted(glob.glob(f"{BASE}/{route}--*"), key=lambda p: int(p.rsplit("--", 1)[1]))[:seg_limit]
  cs_t, cs_v = [], []
  lp_t, lp_yaw = [], []
  md_t, y0s, k30, k15, resid20, c2n = [], [], [], [], [], []
  n_md = 0

  for seg in segs:
    try:
      lr = LogReader(seg + "/rlog.zst")
    except Exception:
      continue
    for msg in lr:
      w = msg.which()
      if w == "carState":
        t = msg.logMonoTime * 1e-9
        if cs_t and t - cs_t[-1] < 0.04:
          continue
        cs_t.append(t); cs_v.append(msg.carState.vEgo)
      elif w == "livePose":
        lp_t.append(msg.logMonoTime * 1e-9)
        lp_yaw.append(msg.livePose.angularVelocityDevice.z)
      elif w == "modelV2":
        n_md += 1
        if n_md % 4 != 0:
          continue
        md = msg.modelV2
        x = np.array(md.position.x); y = np.array(md.position.y)
        if len(x) < 10 or x[-1] < 35:
          continue
        md_t.append(msg.logMonoTime * 1e-9)
        y0s.append(float(y[0]))
        k30.append(curvature_at(x, y, 30.0))
        k15.append(curvature_at(x, y, 15.0))
        near = x <= 60.0
        cf = np.polyfit(x, y, 3)
        cn = np.polyfit(x[near], y[near], 3) if near.sum() >= 8 else cf
        c2n.append(cn[1])
        # residual: full-fit-evaluert minus faktisk y ved ~20 m (det IC-en tegner)
        i20 = int(np.argmin(np.abs(x - 20.0)))
        resid20.append(float(np.polyval(cf, x[i20]) - y[i20]))

  res = {"route": route, "n_samples": len(md_t)}
  if len(md_t) < 100:
    res["error"] = "for lite data"
    return res

  md_t = np.array(md_t); cs_t = np.array(cs_t)
  v_md = np.interp(md_t, cs_t, np.array(cs_v))
  mov = v_md > 5.0
  yaw_md = np.interp(md_t, np.array(lp_t), np.array(lp_yaw))
  k_imu = np.where(v_md > 3.0, yaw_md / np.maximum(v_md, 3.0), 0.0)

  y0a = np.array(y0s)[mov]
  res["y0_mean"] = round(float(y0a.mean()), 4)
  res["y0_std"] = round(float(y0a.std()), 4)
  res["y0_p1_p99"] = [round(float(np.percentile(y0a, 1)), 3), round(float(np.percentile(y0a, 99)), 3)]
  r20 = np.array(resid20)[mov]
  res["resid20_rms_m"] = round(float(np.sqrt((r20 ** 2).mean())), 3)
  res["resid20_p99_m"] = round(float(np.percentile(np.abs(r20), 99)), 3)

  def cc(a, b, m):
    a = np.asarray(a, dtype=float); b = np.asarray(b, dtype=float)
    ok = m & np.isfinite(a) & np.isfinite(b)
    if ok.sum() < 50:
      return None
    a = a[ok]; b = b[ok]
    if a.std() < 1e-9 or b.std() < 1e-9:
      return None
    return round(float(np.corrcoef(a, b)[0, 1]), 3)

  dt = float(np.median(np.diff(md_t)))
  for name, series in [("k15pt", k15), ("k30pt", k30), ("c2near_x2", 2 * np.array(c2n))]:
    series = np.array([v if v is not None else np.nan for v in series], dtype=float)
    best = (None, None)
    for lag_s in np.arange(0.0, 6.1, 0.25):
      sh = int(round(lag_s / dt))
      a = series[:len(series) - sh or None]; b = k_imu[sh:]; m = mov[sh:]
      n = min(len(a), len(b), len(m))
      c = cc(a[:n], b[:n], m[:n])
      if c is not None and (best[1] is None or abs(c) > abs(best[1])):
        best = (round(lag_s, 2), c)
    res[f"peak_{name}_vs_imu"] = {"lag_s": best[0], "corr": best[1]}
  return res

if __name__ == "__main__":
  for route in sys.argv[1:]:
    print(json.dumps(analyze_route(route)))
