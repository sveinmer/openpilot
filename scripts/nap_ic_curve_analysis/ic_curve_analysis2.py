#!/usr/bin/env python3
"""Runde 2: lag-sweep + uavhengige fasiter (IMU-yawrate, desiredCurvature).

Avgjor om negativ korrelasjon fra runde 1 er preview-lag eller fortegnsfeil,
og hvor i kjeden fortegnet ev. flippes.
"""
import sys, glob, json, math
import numpy as np
from openpilot.tools.lib.logreader import LogReader

BASE = "/data/media/0/realdata"

def analyze_route(route, seg_limit=40):
  segs = sorted(glob.glob(f"{BASE}/{route}--*"), key=lambda p: int(p.rsplit("--", 1)[1]))[:seg_limit]
  steer_ratio = wheelbase = None
  cs_t, cs_kappa, cs_v = [], [], []
  lp_t, lp_yaw = [], []
  md_t, md_c2n, md_c2f, md_desired = [], [], [], []
  n_md = 0

  for seg in segs:
    try:
      lr = LogReader(seg + "/rlog.zst")
    except Exception as e:
      print(f"# skip {seg}: {e}", file=sys.stderr)
      continue
    for msg in lr:
      w = msg.which()
      if w == "carParams" and steer_ratio is None:
        steer_ratio = msg.carParams.steerRatio
        wheelbase = msg.carParams.wheelbase
      elif w == "carState":
        t = msg.logMonoTime * 1e-9
        if cs_t and t - cs_t[-1] < 0.04:
          continue
        cs = msg.carState
        sr = steer_ratio or 15.0
        wb = wheelbase or 2.96
        cs_t.append(t)
        cs_kappa.append(math.tan(math.radians(cs.steeringAngleDeg) / sr) / wb)
        cs_v.append(cs.vEgo)
      elif w == "livePose":
        lp = msg.livePose
        lp_t.append(msg.logMonoTime * 1e-9)
        lp_yaw.append(lp.angularVelocityDevice.z)
      elif w == "modelV2":
        n_md += 1
        if n_md % 4 != 0:
          continue
        md = msg.modelV2
        x = np.array(md.position.x); y = np.array(md.position.y)
        if len(x) < 10:
          continue
        cf = np.polyfit(x, y, 3)
        near = x <= 60.0
        cn = np.polyfit(x[near], y[near], 3) if near.sum() >= 8 else cf
        md_t.append(msg.logMonoTime * 1e-9)
        md_c2f.append(cf[1]); md_c2n.append(cn[1])
        try:
          md_desired.append(md.action.desiredCurvature)
        except Exception:
          md_desired.append(0.0)

  res = {"route": route, "segs_used": len(segs), "n_modelV2": n_md, "n_livePose": len(lp_t)}
  if not md_t or not cs_t:
    res["error"] = "mangler data"
    return res

  cs_t = np.array(cs_t); cs_kappa = np.array(cs_kappa); cs_v = np.array(cs_v)
  md_t = np.array(md_t)
  v_md = np.interp(md_t, cs_t, cs_v)
  mov = v_md > 5.0
  res["frac_moving"] = float(mov.mean())

  k_steer = np.interp(md_t, cs_t, cs_kappa)
  fasit = {"steer": k_steer}
  if lp_t:
    yaw_md = np.interp(md_t, np.array(lp_t), np.array(lp_yaw))
    k_imu = np.where(v_md > 3.0, yaw_md / np.maximum(v_md, 3.0), 0.0)
    fasit["imu"] = k_imu

  def cc(a, b, m):
    a = np.asarray(a)[m]; b = np.asarray(b)[m]
    if len(a) < 50 or a.std() < 1e-9 or b.std() < 1e-9:
      return None
    return round(float(np.corrcoef(a, b)[0, 1]), 3)

  # fasit-kryssjekk: IMU vs steering (begge "naa-kurvatur" -> corr her viser
  # om steering-fortegn/SR er til aa stole paa)
  if "imu" in fasit:
    res["corr_imu_vs_steer"] = cc(fasit["imu"], fasit["steer"], mov)

  # desiredCurvature vs fasit (validerer fasit-fortegn: control virker)
  for fname, fv in fasit.items():
    res[f"corr_desired_vs_{fname}"] = cc(md_desired, fv, mov)

  # lag-sweep: model-kurvatur (2*c2) vs fasit; positiv lag = modellen leder
  dt = float(np.median(np.diff(md_t)))
  sweeps = {}
  for series_name, series in [("nearfit", 2 * np.array(md_c2n)), ("fullfit", 2 * np.array(md_c2f)),
                              ("desired", np.array(md_desired))]:
    best = {}
    for fname, fv in fasit.items():
      curve = []
      for lag_s in np.arange(-2.0, 10.1, 0.5):
        sh = int(round(lag_s / dt))
        if sh >= 0:
          a = series[:len(series) - sh or None]; b = fv[sh:]; m = mov[sh:]
        else:
          a = series[-sh:]; b = fv[:sh]; m = mov[:sh]
        n = min(len(a), len(b), len(m))
        c = cc(a[:n], b[:n], m[:n])
        if c is not None:
          curve.append((round(lag_s, 1), c))
      if curve:
        peak = max(curve, key=lambda p: abs(p[1]))
        best[fname] = {"peak_lag_s": peak[0], "peak_corr": peak[1],
                       "lag0": dict(curve).get(0.0)}
    sweeps[series_name] = best
  res["lag_sweeps"] = sweeps
  return res

if __name__ == "__main__":
  for route in sys.argv[1:]:
    print(json.dumps(analyze_route(route)))
