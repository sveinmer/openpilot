#!/usr/bin/env python3
"""Offline decisive-test for IC-curves (handover 2026-07-02 §3, uten kjøring).

Per rute:
  - modelV2.position -> full-array polyfit (eksakt hud_module-replika) og
    near-field polyfit (x<=60 m)
  - sendcan 0x239 -> faktisk transmittert DAS_virtualLaneC0/C2
  - carState.steeringAngleDeg/vEgo -> faktisk kjort kurvatur (fasit)
Sammenligner tidsserier -> hvor i kjeden kurve-informasjonen dor.
"""
import sys, glob, json, math
import numpy as np
from openpilot.tools.lib.logreader import LogReader

BASE = "/data/media/0/realdata"

def analyze_route(route):
  segs = sorted(glob.glob(f"{BASE}/{route}--*"), key=lambda p: int(p.rsplit("--", 1)[1]))
  steer_ratio = None
  wheelbase = None
  cs_t, cs_kappa, cs_v = [], [], []
  md_t, md_c2f, md_c2n, md_c0f, md_c0n, md_xmax, md_ymax = [], [], [], [], [], [], []
  tx_t, tx_c0, tx_c2 = [], [], []
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
        sr = steer_ratio or 11.5
        wb = wheelbase or 2.96
        kappa = math.tan(math.radians(cs.steeringAngleDeg) / sr) / wb
        cs_t.append(t); cs_kappa.append(kappa); cs_v.append(cs.vEgo)
      elif w == "modelV2":
        n_md += 1
        if n_md % 4 != 0:  # 5 Hz holder
          continue
        md = msg.modelV2
        x = np.array(md.position.x); y = np.array(md.position.y)
        if len(x) < 10:
          continue
        # eksakt hud_module-replika: get_path_length_idx(y, 100) == full array
        max_idx = sum(1 for v in y if v < 100.0)
        if max_idx == 0 or len(x) < max_idx:
          continue
        cf = np.polyfit(x[:max_idx], y[:max_idx], 3)
        near = x <= 60.0
        cn = np.polyfit(x[near], y[near], 3) if near.sum() >= 8 else cf
        md_t.append(msg.logMonoTime * 1e-9)
        md_c2f.append(cf[1]); md_c2n.append(cn[1])
        md_c0f.append(cf[3]); md_c0n.append(cn[3])
        md_xmax.append(float(x[max_idx - 1])); md_ymax.append(float(np.abs(y).max()))
      elif w == "sendcan":
        for c in msg.sendcan:
          if c.address == 569:
            d = bytes(c.dat)
            if len(d) >= 6:
              tx_t.append(msg.logMonoTime * 1e-9)
              tx_c0.append(d[2] * 0.035 - 3.5)
              tx_c2.append(d[4] * 2e-05 - 0.0025)

  res = {"route": route, "segs": len(segs), "n_modelV2": n_md,
         "n_tx239": len(tx_t), "steerRatio": steer_ratio, "wheelbase": wheelbase}
  if not md_t or not cs_t:
    res["error"] = "mangler modelV2/carState"
    return res

  cs_t = np.array(cs_t); cs_kappa = np.array(cs_kappa); cs_v = np.array(cs_v)
  md_t = np.array(md_t)
  k_at_md = np.interp(md_t, cs_t, cs_kappa)
  v_at_md = np.interp(md_t, cs_t, cs_v)
  moving = v_at_md > 5.0
  res["frac_moving"] = float(moving.mean())
  res["v_mean_kmh"] = float(v_at_md[moving].mean() * 3.6) if moving.any() else 0.0
  res["kappa_rms_1perm"] = float(np.sqrt((k_at_md[moving] ** 2).mean()))
  res["xmax_mean"] = float(np.mean(md_xmax))

  def cc(a, b, m):
    a = np.asarray(a)[m]; b = np.asarray(b)[m]
    if len(a) < 20 or a.std() < 1e-9 or b.std() < 1e-9:
      return None
    return float(np.corrcoef(a, b)[0, 1])

  # modellens plan-kurvatur ved x=0 er 2*c2 (fortegnskonvensjon: y venstre+)
  res["corr_kappa_fullfit"] = cc(2 * np.array(md_c2f), k_at_md, moving)
  res["corr_kappa_nearfit"] = cc(2 * np.array(md_c2n), k_at_md, moving)
  sent_equiv = np.clip(np.array(md_c2f) * 4.0, -0.0025, 0.0025)
  res["fullfit_sat_frac"] = float((np.abs(sent_equiv[moving]) >= 0.0025 - 1e-9).mean())
  res["c0_full_minmax"] = [float(np.min(md_c0f)), float(np.max(md_c0f))]
  res["c0_near_minmax"] = [float(np.min(md_c0n)), float(np.max(md_c0n))]

  if tx_t:
    tx_t = np.array(tx_t); tx_c2 = np.array(tx_c2)
    k_at_tx = np.interp(tx_t, cs_t, cs_kappa)
    v_at_tx = np.interp(tx_t, cs_t, cs_v)
    mtx = v_at_tx > 5.0
    res["corr_kappa_sentC2"] = cc(tx_c2 / 2.0, k_at_tx, mtx)
    res["sent_sat_frac"] = float((np.abs(tx_c2[mtx]) >= 0.0025 - 1e-9).mean()) if mtx.any() else None
    # integritet: sendt vs rekonstruert (naermeste modelV2-sample)
    idx = np.searchsorted(md_t, tx_t).clip(1, len(md_t) - 1)
    recon = sent_equiv[idx]
    res["corr_sent_vs_recon"] = cc(tx_c2, recon, mtx)
    res["tx_c2_uniq"] = int(len(np.unique(np.round(tx_c2, 6))))
  return res

if __name__ == "__main__":
  for route in sys.argv[1:]:
    print(json.dumps(analyze_route(route)))
