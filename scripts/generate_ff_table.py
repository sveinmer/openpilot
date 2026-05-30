#!/usr/bin/env python3
"""Generate a data-driven feedforward table for VirtualDAS — v2 with proper
interpolation, transient filtering, and sanity clipping.

Reads drive logs and builds a 2D lookup table (speed × accel → pedal_di) by
observing real pedal response. Key improvements over v1:

  - Steady-state filter: only use frames where MPC accel-cmd has been stable
    for ≥0.4s (stdev < 0.05 m/s² over 20-frame window).
  - Per-bin gain ratio: corrected_DI = default_DI × clip(cmd/achieved, 0.5, 2.0).
  - Speed-dimensional smoothing: gain factor averaged with neighbours on
    speed axis to avoid sharp discontinuities (Tesla S85/P85 motor-torque-curve
    is smooth → correction should be smooth).
  - Cross-bin interpolation: bins with <MIN_SAMPLES propagate gain from
    neighbour bins on same speed row, falling back to default (gain=1) only
    at edge cases.

Usage:
  python scripts/generate_ff_table.py /path/to/*.rlog.zst [--output PATH]

Output: /data/vdas_ff_table.json (or --output path)
"""

import argparse
import json
import sys
from collections import defaultdict

import numpy as np

from openpilot.tools.lib.logreader import LogReader


# === Constants ===

MIN_SPEED = 3.0       # m/s — below this, FF-table not used (idle/creep)
ACTUATOR_DELAY = 0.4  # s — shift a_ego earlier by this much to align with cmd
STEADY_WINDOW = 20    # frames (~0.4s at 50Hz) for steady-state detection
STEADY_STDEV = 0.05   # m/s² — max stdev in window to qualify as steady

# Grid (matches ff_table_default)
SPEED_BP = [0.0, 5.0, 12.0, 20.0, 30.0, 40.0]
ACCEL_BP = [-1.5, -1.0, -0.5, 0.0, 0.5, 1.0, 1.5, 2.0, 2.5]

# Default DEFAULT_TABLE (from ff_table_default.py — must match VDAS expects)
DEFAULT_TABLE = [
  [-5.00, -3.33, -1.67,  0.00, 10.00, 20.00, 30.00, 40.00, 50.00],  # 0 m/s
  [-5.00, -3.33, -1.67,  0.00, 11.60, 23.20, 34.80, 46.40, 58.00],  # 5
  [-5.00, -3.33, -1.67,  0.00, 13.20, 26.40, 39.60, 52.80, 66.00],  # 12
  [-5.00, -3.33, -1.67,  0.00, 14.80, 29.60, 44.40, 59.20, 74.00],  # 20
  [-5.00, -3.33, -1.67,  0.00, 16.40, 32.80, 49.20, 65.60, 82.00],  # 30
  [-5.00, -3.33, -1.67,  0.00, 18.00, 36.00, 54.00, 72.00, 90.00],  # 40
]

MIN_SAMPLES = 20      # per-bin
GAIN_CLIP = (0.3, 2.5)  # absolute bounds on gain factor
SMOOTH_WINDOW = 3     # rows for moving-avg smoothing of gain over speed
FALLBACK_GAIN = 1.0   # if bin has no data, fall back to default

FF_TABLE_PATH = "/data/vdas_ff_table.json"


def extract_data(path: str):
  """Yield (t, cmd_accel, a_ego, v_ego, lead_active, long_active, gas_pressed)."""
  lr = LogReader(path)
  last_cs = None
  last_lead = False
  for msg in lr:
    w = msg.which()
    t = msg.logMonoTime / 1e9
    if w == "carState":
      last_cs = msg.carState
    elif w == "radarState":
      try: last_lead = bool(msg.radarState.leadOne.status)
      except: last_lead = False
    elif w == "carControl" and last_cs is not None:
      yield (t, float(msg.carControl.actuators.accel),
             float(last_cs.aEgo), float(last_cs.vEgo),
             last_lead, bool(msg.carControl.longActive),
             bool(last_cs.gasPressed))


def collect_samples(paths):
  """Collect (cmd, achieved, v_ego) from steady-state, long-active, non-gas frames."""
  samples = []
  for path in paths:
    print(f"Reading: {path}", file=sys.stderr)
    rows = list(extract_data(path))
    if not rows:
      continue
    # Apply actuator delay: shift achieved (a_ego) forward in time
    # We compare cmd[i] with a_ego[i + delay_frames]
    if len(rows) < 2:
      continue
    dt_avg = (rows[-1][0] - rows[0][0]) / max(len(rows) - 1, 1)
    delay_frames = max(1, int(round(ACTUATOR_DELAY / dt_avg)))

    for i in range(len(rows) - delay_frames - STEADY_WINDOW):
      r = rows[i]
      if not r[5]:  # longActive
        continue
      if r[6]:  # gasPressed (driver override)
        continue
      v_ego = r[3]
      if v_ego < MIN_SPEED:
        continue
      # Steady-state: stdev of cmd over the next STEADY_WINDOW frames
      cmds = [rows[i + k][1] for k in range(STEADY_WINDOW)]
      cmd_mean = sum(cmds) / len(cmds)
      cmd_var = sum((c - cmd_mean) ** 2 for c in cmds) / len(cmds)
      if cmd_var ** 0.5 > STEADY_STDEV:
        continue
      # Achieved (a_ego) at i + delay_frames
      achieved = rows[i + delay_frames][2]
      samples.append((cmd_mean, achieved, v_ego))

    print(f"  rows={len(rows)}  delay_frames={delay_frames}  samples so far: {len(samples)}", file=sys.stderr)
  return samples


def bin_index(value, breakpoints):
  """Return the nearest bin index for a value (snap to grid)."""
  best_i = 0
  best_d = abs(value - breakpoints[0])
  for i, bp in enumerate(breakpoints[1:], start=1):
    d = abs(value - bp)
    if d < best_d:
      best_d, best_i = d, i
  return best_i


def build_gain_grid(samples):
  """Build a per-bin gain factor grid: gain[si][ai] = cmd_median / achieved_median."""
  # Bucketize by snapping to nearest bin
  bins = defaultdict(list)  # (si, ai) -> [(cmd, achieved), ...]
  for cmd, achieved, v_ego in samples:
    si = bin_index(v_ego, SPEED_BP)
    ai = bin_index(cmd, ACCEL_BP)
    bins[(si, ai)].append((cmd, achieved))

  gain_grid = np.full((len(SPEED_BP), len(ACCEL_BP)), np.nan)
  count_grid = np.zeros((len(SPEED_BP), len(ACCEL_BP)), dtype=int)

  for (si, ai), data in bins.items():
    count_grid[si][ai] = len(data)
    if len(data) < MIN_SAMPLES:
      continue
    cmds = [d[0] for d in data]
    achieveds = [d[1] for d in data]
    # Use medians for robustness
    cmd_med = float(np.median(cmds))
    ach_med = float(np.median(achieveds))
    # Skip near-zero achieved (division blowup)
    if abs(ach_med) < 0.05 or abs(cmd_med) < 0.05:
      continue
    gain = cmd_med / ach_med
    # Only keep if same sign — opposite signs mean noise dominated
    if gain < 0:
      continue
    gain_clipped = max(GAIN_CLIP[0], min(GAIN_CLIP[1], gain))
    gain_grid[si][ai] = gain_clipped

  return gain_grid, count_grid


def fill_missing_from_neighbours(grid):
  """For nan cells, fill from horizontally-nearest non-nan cell in same row."""
  filled = grid.copy()
  n_rows, n_cols = grid.shape
  for si in range(n_rows):
    row = filled[si]
    if np.all(np.isnan(row)):
      continue
    # Forward fill then backward fill
    last_valid = np.nan
    for ai in range(n_cols):
      if not np.isnan(row[ai]):
        last_valid = row[ai]
      elif not np.isnan(last_valid):
        row[ai] = last_valid
    last_valid = np.nan
    for ai in range(n_cols - 1, -1, -1):
      if not np.isnan(row[ai]):
        last_valid = row[ai]
      elif not np.isnan(last_valid):
        row[ai] = last_valid
  # Vertical fill: rows entirely nan inherit from nearest non-nan row
  for si in range(n_rows):
    if np.all(np.isnan(filled[si])):
      # Find nearest non-nan row
      for offset in range(1, n_rows):
        for direction in (-1, 1):
          target = si + direction * offset
          if 0 <= target < n_rows and not np.all(np.isnan(filled[target])):
            filled[si] = filled[target]
            break
        else:
          continue
        break
  # Any remaining nan: fallback gain 1.0
  filled[np.isnan(filled)] = FALLBACK_GAIN
  return filled


def smooth_speed_axis(grid, window=SMOOTH_WINDOW):
  """Moving-average smoothing of gain along speed axis only."""
  smoothed = grid.copy()
  n_rows, n_cols = grid.shape
  half = window // 2
  for ai in range(n_cols):
    for si in range(n_rows):
      lo = max(0, si - half)
      hi = min(n_rows, si + half + 1)
      smoothed[si][ai] = np.mean(grid[lo:hi, ai])
  return smoothed


def apply_gain_to_default(gain_grid):
  """Apply gain factor to DEFAULT_TABLE: corrected = default * gain."""
  table = []
  for si in range(len(SPEED_BP)):
    row = []
    for ai in range(len(ACCEL_BP)):
      default_di = DEFAULT_TABLE[si][ai]
      gain = gain_grid[si][ai]
      corrected = default_di * gain
      row.append(round(float(corrected), 2))
    table.append(row)
  return table


def main():
  parser = argparse.ArgumentParser(description=__doc__,
                                   formatter_class=argparse.RawDescriptionHelpFormatter)
  parser.add_argument('logs', nargs='+', help='rlog files')
  parser.add_argument('--output', default=FF_TABLE_PATH)
  parser.add_argument('--verbose', action='store_true')
  args = parser.parse_args()

  samples = collect_samples(args.logs)
  print(f"\nTotal steady-state samples: {len(samples)}")
  if not samples:
    print("No samples — drive longer in NAP-engaged mode with steady accel/cruise.")
    return 1

  gain_grid, count_grid = build_gain_grid(samples)

  print("\n=== Per-bin gain grid (raw, before fill/smooth) ===")
  print(f"speed↓ accel→:  " + "  ".join(f"{a:+.1f}" for a in ACCEL_BP))
  for si, sp in enumerate(SPEED_BP):
    cells = [f"{gain_grid[si][ai]:5.2f}" if not np.isnan(gain_grid[si][ai]) else "  —  " for ai in range(len(ACCEL_BP))]
    counts = [count_grid[si][ai] for ai in range(len(ACCEL_BP))]
    print(f"  {sp:4.0f} m/s  ({sp*3.6:5.1f} km/h):  " + "  ".join(cells) + f"  (n: {counts})")

  filled = fill_missing_from_neighbours(gain_grid)
  smoothed = smooth_speed_axis(filled)

  print("\n=== Gain grid after fill + speed-smooth ===")
  for si, sp in enumerate(SPEED_BP):
    cells = [f"{smoothed[si][ai]:5.2f}" for ai in range(len(ACCEL_BP))]
    print(f"  {sp:4.0f} m/s:  " + "  ".join(cells))

  table = apply_gain_to_default(smoothed)
  print("\n=== Final corrected FF-table (default × gain) ===")
  for si, sp in enumerate(SPEED_BP):
    print(f"  {sp:4.0f} m/s:  {table[si]}")

  with open(args.output, 'w') as f:
    json.dump({'speed_bp': SPEED_BP, 'accel_bp': ACCEL_BP, 'table': table}, f, indent=2)
  print(f"\nWritten: {args.output}")
  return 0


if __name__ == '__main__':
  sys.exit(main())
