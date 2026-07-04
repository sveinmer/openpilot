#!/usr/bin/env python3
"""A/B: Tinkla-aera (mai, IC virket) vs NAP naa (juni/juli, IC stuck).

Samme metrikker begge veier: modell-horisont, sat-frac paa sendt C2,
corr(sendt C2 vs fasit), corr(punkt-kurvatur vs fasit), 0x239-feltinnhold.
Fasit: livePose -> liveLocationKalman -> (fallback) steering.
"""
import sys, glob, json, math, os
import numpy as np
from openpilot.tools.lib.logreader import LogReader

BASE = "/data/media/0/realdata"

def curvature_at(x, y, target_x):
  i = int(np.argmin(np.abs(x - target_x)))
  if i < 1 or i >= len(x) - 1 or x[i + 1] - x[i - 1] < 1.0:
    return np.nan
  d1 = (y[i] - y[i - 1]) / max(x[i] - x[i - 1], 0.1)
  d2 = (y[i + 1] - y[i]) / max(x[i + 1] - x[i], 0.1)
  return 2 * (d2 - d1) / (x[i + 1] - x[i - 1])

def analyze_route(route, seg_limit=25):
  segs = sorted(glob.glob(f"{BASE}/{route}--*"), key=lambda p: int(p.rsplit("--", 1)[1]))[:seg_limit]
  cs_t, cs_v, cs_sa = [], [], []
  im_t, im_yaw = [], []
  md_t, k15, c2f, xmax, yfar = [], [], [], [], []
  tx_t, tx = [], []
  n_md = 0
  sr = None

  for seg in segs:
    rl = seg + "/rlog.zst" if os.path.exists(seg + "/rlog.zst") else seg + "/rlog"
    if not os.path.exists(rl):
      continue
    try:
      lr = LogReader(rl)
    except Exception as e:
      print(f"# skip {seg}: {e}", file=sys.stderr)
      continue
    try:
      for msg in lr:
        w = msg.which()
        if w == "carParams" and sr is None:
          sr = msg.carParams.steerRatio
        elif w == "carState":
          t = msg.logMonoTime * 1e-9
          if cs_t and t - cs_t[-1] < 0.04:
            continue
          cs_t.append(t); cs_v.append(msg.carState.vEgo)
          cs_sa.append(msg.carState.steeringAngleDeg)
        elif w == "livePose":
          im_t.append(msg.logMonoTime * 1e-9)
          im_yaw.append(msg.livePose.angularVelocityDevice.z)
        elif w == "liveLocationKalman" and not im_t or w == "liveLocationKalman":
          try:
            av = msg.liveLocationKalman.angularVelocityCalibrated.value
            if len(av) == 3:
              im_t.append(msg.logMonoTime * 1e-9); im_yaw.append(av[2])
          except Exception:
            pass
        elif w == "modelV2":
          n_md += 1
          if n_md % 4 != 0:
            continue
          md = msg.modelV2
          x = np.array(md.position.x); y = np.array(md.position.y)
          if len(x) < 10 or x[-1] < 25:
            continue
          md_t.append(msg.logMonoTime * 1e-9)
          k15.append(curvature_at(x, y, 15.0))
          c2f.append(np.polyfit(x, y, 3)[1])
          xmax.append(float(x[-1])); yfar.append(float(abs(y[-1])))
        elif w == "sendcan":
          for c in msg.sendcan:
            if c.address == 569:
              d = bytes(c.dat)
              if len(d) >= 8:
                tx_t.append(msg.logMonoTime * 1e-9)
                tx.append((d[1], d[2] * 0.035 - 3.5, d[4] * 2e-05 - 0.0025,
                           d[5] * 2.4e-07 - 3e-05, d[0]))
    except Exception as e:
      print(f"# parse-abort {seg}: {e}", file=sys.stderr)

  res = {"route": route, "segs_used": len(segs), "n_modelV2": n_md,
         "n_tx239": len(tx_t), "n_imu": len(im_t), "steerRatio": sr}
  if len(md_t) < 100 or not cs_t:
    res["error"] = "for lite data"
    return res

  cs_t = np.array(cs_t)
  md_t = np.array(md_t)
  v_md = np.interp(md_t, cs_t, np.array(cs_v))
  mov = v_md > 5.0
  res["v_mean_kmh"] = round(float(v_md[mov].mean() * 3.6), 1)
  res["xmax_mean"] = round(float(np.mean(np.array(xmax)[mov])), 1)
  res["yfar_p90"] = round(float(np.percentile(np.array(yfar)[mov], 90)), 1)

  if im_t:
    yaw_md = np.interp(md_t, np.array(im_t), np.array(im_yaw))
    fasit = np.where(v_md > 3.0, yaw_md / np.maximum(v_md, 3.0), 0.0)
    res["fasit"] = "imu"
  else:
    sa = np.interp(md_t, cs_t, np.array(cs_sa))
    fasit = np.tan(np.radians(sa) / (sr or 15.0)) / 2.96
    res["fasit"] = "steer_raatt_fortegn_ukjent"
  res["kappa_rms"] = round(float(np.sqrt((fasit[mov] ** 2).mean())), 5)

  def cc(a, b, m):
    a = np.asarray(a, dtype=float); b = np.asarray(b, dtype=float)
    ok = m & np.isfinite(a) & np.isfinite(b)
    if ok.sum() < 50 or a[ok].std() < 1e-12 or b[ok].std() < 1e-12:
      return None
    return round(float(np.corrcoef(a[ok], b[ok])[0, 1]), 3)

  dt = float(np.median(np.diff(md_t)))
  def lag_peak(series):
    best = (None, None)
    for lag_s in np.arange(0.0, 6.1, 0.25):
      sh = int(round(lag_s / dt))
      a = np.asarray(series, dtype=float)[:len(series) - sh or None]
      b = fasit[sh:]; m = mov[sh:]
      n = min(len(a), len(b), len(m))
      c = cc(a[:n], b[:n], m[:n])
      if c is not None and (best[1] is None or abs(c) > abs(best[1])):
        best = (round(lag_s, 2), c)
    return {"lag_s": best[0], "corr": best[1]}

  res["peak_k15pt"] = lag_peak(k15)
  res["peak_c2full_x2"] = lag_peak(2 * np.array(c2f))
  sent_equiv = np.clip(np.array(c2f) * 4.0, -0.0025, 0.0025)
  res["fullfit_sat_frac"] = round(float((np.abs(sent_equiv[mov]) >= 0.0025 - 1e-9).mean()), 3)

  if tx_t:
    tx_t = np.array(tx_t)
    vr = np.array([t[0] for t in tx]); c2s = np.array([t[2] for t in tx])
    c3s = np.array([t[3] for t in tx]); b0 = np.array([t[4] for t in tx])
    v_tx = np.interp(tx_t, cs_t, np.array(cs_v))
    mtx = v_tx > 5.0
    res["tx_viewRange_uniq"] = sorted(set(int(v) for v in np.unique(vr)))[:5]
    res["tx_byte0_uniq"] = sorted(set(int(v) for v in np.unique(b0)))[:8]
    res["tx_sat_frac_C2"] = round(float((np.abs(c2s[mtx]) >= 0.0025 - 1e-9).mean()), 3)
    res["tx_sat_frac_C3"] = round(float((np.abs(c3s[mtx]) >= 3e-05 - 1e-9).mean()), 3)
    k_tx = np.interp(tx_t, md_t, fasit)
    dttx = float(np.median(np.diff(tx_t))) or 0.1
    best = (None, None)
    for lag_s in np.arange(0.0, 6.1, 0.25):
      sh = int(round(lag_s / dttx))
      a = c2s[:len(c2s) - sh or None]; b = k_tx[sh:]; m = mtx[sh:]
      n = min(len(a), len(b), len(m))
      c = cc(a[:n], b[:n], m[:n])
      if c is not None and (best[1] is None or abs(c) > abs(best[1])):
        best = (round(lag_s, 2), c)
    res["peak_sentC2"] = {"lag_s": best[0], "corr": best[1]}
  return res

if __name__ == "__main__":
  for route in sys.argv[1:]:
    print(json.dumps(analyze_route(route)))
