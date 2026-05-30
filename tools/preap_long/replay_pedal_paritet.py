"""P3 Fase C — `accel → pedal_DI`-paritets-replay: NAP vs Tinkla 0.6.6.

For hver tick i en Tinkla-rlog kjører dette scriptet både Tinkla-reference
(Spor 2) og NAP-controller (`opendbc_repo/opendbc/car/tesla/pedal/controller`)
med identiske inputs og logger delta. Output:

  - CSV-dump per tick til ``output/paritet_<route>.csv``
  - Stat-rapport til stdout + ``output/stats_<route>.txt``
  - Exit code: 0=GRØNN, 1=GUL, 2=RØD, 3=pipeline-feil

Akseptkriterium (P3 sprintplan §4 Fase C):
  GRØNN: median |delta| ≤ 2 AND p95 |delta| ≤ 8 AND bias ∈ [-3, +3]
         AND ingen ticks |delta| > 30
  GUL:   innenfor RØD-grense men utenfor GRØNN
  RØD:   ≥10% av ticks har |delta| > 30

CLI-eksempel::

    python -m tools.preap_long.replay_pedal_paritet \
        --route "<DONGLE_ID>|2025-11-05--05-33-11" \
        --max-segments 5

Hard non-actions:
  * Modifiserer IKKE `opendbc_repo/opendbc/car/tesla/pedal/controller.py`.
  * Modifiserer IKKE `tools/lib/`.
  * Ingen device-touch, ingen SSH.
  * Ingen faktisk replay-kjøring mot ekte route i agent-dispatch — anonymisert i public-mirror
    kjører Fase C interaktivt.
"""
from __future__ import annotations

import argparse
import csv
import math
import os
import sys
from dataclasses import dataclass
from statistics import median
from typing import Callable, Iterable, Iterator, List, Optional

# Importer Spor 1 og Spor 2 lazy via funksjons-handles slik at tester kan
# mocke dem uten å patche modul-attributter etter import.
from tools.preap_long.rlog_loader import (
  PedalTick,
  load_pedal_tick_stream as _default_load_pedal_tick_stream,
)
from tools.preap_long.tinkla_pcc_reference import (
  TinklaLongState,
  compute_tinkla_pedal_di as _default_compute_tinkla_pedal_di,
)


# NAP pedal-controller. Lazy-bind for å la tester mocke compute_pedal_command
# gjennom å patche modulattributtet selv om den ekte modulen krever
# `opendbc.car.tesla.preap.nap_conf` (som finnes i repo).
def _default_compute_pedal_command(
  accel_request: float,
  v_ego: float,
  prev_pedal_di: float,
  target_speed_kph: Optional[float] = None,
):
  from opendbc.car.tesla.pedal.controller import (
    compute_pedal_command as _real_compute,
  )

  return _real_compute(accel_request, v_ego, prev_pedal_di, target_speed_kph)


CSV_COLUMNS = [
  "ts",
  "accel_request",
  "v_ego",
  "prev_pedal_di",
  "tinkla_di",
  "nap_di",
  "recorded_tinkla_di",
  "delta_tinkla_vs_nap",
  "delta_recorded_vs_nap",
]


# ---------------------------------------------------------------------------
# Klassifisering
# ---------------------------------------------------------------------------


CLASSIFICATION_GREEN = "GRØNN"
CLASSIFICATION_YELLOW = "GUL"
CLASSIFICATION_RED = "RØD"

EXIT_GREEN = 0
EXIT_YELLOW = 1
EXIT_RED = 2
EXIT_PIPELINE_ERROR = 3

RED_OUTLIER_FRACTION = 0.10
RED_OUTLIER_THRESHOLD_DI = 30


@dataclass(frozen=True)
class ParityStats:
  """Beregnet statistikk + klassifisering for en replay-kjøring."""

  tick_count: int
  median_abs_delta: float
  p95_abs_delta: float
  max_abs_delta: float
  bias_median: float
  outlier_count: int
  outlier_fraction: float
  classification: str
  exit_code: int

  def as_text_report(self) -> str:
    """Render som lesbar tekst-rapport for stdout og fil."""
    lines = [
      "P3 Fase C — accel → pedal_DI paritets-rapport",
      "=" * 50,
      f"Antall ticks                  : {self.tick_count}",
      f"Median |delta_tinkla_vs_nap|  : {self.median_abs_delta:.2f} DI",
      f"P95    |delta_tinkla_vs_nap|  : {self.p95_abs_delta:.2f} DI",
      f"Max    |delta_tinkla_vs_nap|  : {self.max_abs_delta:.2f} DI",
      f"Bias (median signed delta)    : {self.bias_median:+.2f} DI",
      f"Outliers |delta| > {RED_OUTLIER_THRESHOLD_DI} DI       : "
      f"{self.outlier_count} ({self.outlier_fraction * 100:.2f}%)",
      "",
      f"Klassifisering                : {self.classification}",
      f"Exit code                     : {self.exit_code}",
    ]
    return "\n".join(lines)


def _percentile(sorted_values: List[float], pct: float) -> float:
  """Lineær-interpolert percentil. ``pct`` i [0, 100]."""
  if not sorted_values:
    return 0.0
  if len(sorted_values) == 1:
    return float(sorted_values[0])
  k = (len(sorted_values) - 1) * (pct / 100.0)
  f = math.floor(k)
  c = math.ceil(k)
  if f == c:
    return float(sorted_values[int(k)])
  lo = sorted_values[int(f)] * (c - k)
  hi = sorted_values[int(c)] * (k - f)
  return float(lo + hi)


def classify(rows: List[dict]) -> ParityStats:
  """Beregn stat-rapport og klassifisering fra replay-rows.

  ``rows`` er dict-listen produsert av :func:`replay`.
  """
  if not rows:
    return ParityStats(
      tick_count=0,
      median_abs_delta=0.0,
      p95_abs_delta=0.0,
      max_abs_delta=0.0,
      bias_median=0.0,
      outlier_count=0,
      outlier_fraction=0.0,
      classification=CLASSIFICATION_RED,
      exit_code=EXIT_PIPELINE_ERROR,
    )

  signed_deltas = [int(r["delta_tinkla_vs_nap"]) for r in rows]
  abs_deltas = [abs(d) for d in signed_deltas]
  sorted_abs = sorted(abs_deltas)

  med_abs = float(median(sorted_abs))
  p95_abs = _percentile(sorted_abs, 95.0)
  max_abs = float(sorted_abs[-1])
  bias = float(median(signed_deltas))
  outlier_count = sum(1 for d in abs_deltas if d > RED_OUTLIER_THRESHOLD_DI)
  outlier_fraction = outlier_count / len(rows)

  # RØD-grense går først — strengeste vinner.
  if outlier_fraction >= RED_OUTLIER_FRACTION:
    classification = CLASSIFICATION_RED
    exit_code = EXIT_RED
  elif (
    med_abs <= 2.0
    and p95_abs <= 8.0
    and -3.0 <= bias <= 3.0
    and outlier_count == 0
  ):
    classification = CLASSIFICATION_GREEN
    exit_code = EXIT_GREEN
  else:
    classification = CLASSIFICATION_YELLOW
    exit_code = EXIT_YELLOW

  return ParityStats(
    tick_count=len(rows),
    median_abs_delta=med_abs,
    p95_abs_delta=p95_abs,
    max_abs_delta=max_abs,
    bias_median=bias,
    outlier_count=outlier_count,
    outlier_fraction=outlier_fraction,
    classification=classification,
    exit_code=exit_code,
  )


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


def replay(
  route_id: str,
  max_segments: Optional[int] = None,
  *,
  load_ticks: Callable[..., Iterable[PedalTick]] = _default_load_pedal_tick_stream,
  compute_tinkla: Callable = _default_compute_tinkla_pedal_di,
  compute_nap: Callable = _default_compute_pedal_command,
) -> List[dict]:
  """Kjør paritets-replay og returner per-tick rows (in-memory).

  Args:
    route_id: Tinkla-route i ``<dongle>|<date>``-format.
    max_segments: Begrens segmenter (None = alle).
    load_ticks: Injectable tick-loader (default Spor 1).
    compute_tinkla: Injectable Tinkla-reference (default Spor 2).
    compute_nap: Injectable NAP-controller (default
      :func:`opendbc.car.tesla.pedal.controller.compute_pedal_command`).

  Returns:
    Liste av dict med CSV-kolonnene fra :data:`CSV_COLUMNS`.

  Raises:
    Lar exception fra ``load_ticks``/``compute_*`` propagere — kall-site
    håndterer pipeline-feil og setter exit code 3.
  """
  tinkla_state = TinklaLongState.initial()
  prev_tinkla_di = 0
  prev_nap_di: float = 0.0
  prev_tesla_accel = 0.0

  rows: List[dict] = []

  for tick in load_ticks(route_id, max_segments=max_segments):
    if tick.accel_request is None or tick.v_ego is None:
      continue

    accel_request = float(tick.accel_request)
    v_ego = float(tick.v_ego)

    # Tinkla-reference
    tinkla_di_raw, tinkla_state = compute_tinkla(
      accel_request, v_ego, prev_tinkla_di, prev_tesla_accel, tinkla_state
    )
    tinkla_di = int(tinkla_di_raw)

    # NAP-controller. Den ekte versjonen returnerer (voltage, di) tuple;
    # tester kan returnere bare int. Vi håndterer begge.
    nap_result = compute_nap(accel_request, v_ego, prev_nap_di)
    if isinstance(nap_result, tuple):
      nap_di_raw = nap_result[1]
    else:
      nap_di_raw = nap_result
    nap_di = int(round(float(nap_di_raw)))

    delta_t_n = tinkla_di - nap_di
    delta_r_n: Optional[int]
    if tick.recorded_pedal_di is not None:
      delta_r_n = int(tick.recorded_pedal_di) - nap_di
    else:
      delta_r_n = None

    rows.append(
      {
        "ts": float(tick.ts),
        "accel_request": accel_request,
        "v_ego": v_ego,
        "prev_pedal_di": int(round(prev_nap_di)),
        "tinkla_di": tinkla_di,
        "nap_di": nap_di,
        "recorded_tinkla_di": (
          int(tick.recorded_pedal_di) if tick.recorded_pedal_di is not None else None
        ),
        "delta_tinkla_vs_nap": delta_t_n,
        "delta_recorded_vs_nap": delta_r_n,
      }
    )

    prev_tinkla_di = tinkla_di
    prev_nap_di = float(nap_di_raw)
    prev_tesla_accel = accel_request

  return rows


# ---------------------------------------------------------------------------
# CSV + stats output
# ---------------------------------------------------------------------------


def _route_basename(route_id: str) -> str:
  """Konverter route-id (``dongle|date`` evt med ``/segrange``) til
  filsystem-trygg basename."""
  safe = route_id.replace("|", "_").replace("/", "_").replace(":", "-")
  return safe


def write_csv(rows: List[dict], csv_path: str) -> None:
  """Skriv rows til CSV med deterministisk kolonne-rekkefølge."""
  with open(csv_path, "w", newline="") as fh:
    writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
    writer.writeheader()
    for row in rows:
      out_row = {k: ("" if row.get(k) is None else row.get(k)) for k in CSV_COLUMNS}
      writer.writerow(out_row)


def write_stats(stats: ParityStats, stats_path: str) -> None:
  """Skriv tekst-rapport til disk."""
  with open(stats_path, "w") as fh:
    fh.write(stats.as_text_report())
    fh.write("\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_arg_parser() -> argparse.ArgumentParser:
  """Standalone for å la test-suiten dekke argparse-konfigurasjonen."""
  parser = argparse.ArgumentParser(
    prog="replay_pedal_paritet",
    description=(
      "P3 Fase C: replay Tinkla-rlog og sammenlign accel→pedal_DI fra "
      "NAP-controller mot Tinkla 0.6.6-reference."
    ),
  )
  parser.add_argument(
    "--route",
    required=True,
    help="Tinkla-route i <dongle>|<dato>-format.",
  )
  parser.add_argument(
    "--max-segments",
    type=int,
    default=None,
    help="Begrens antall segments (default: alle).",
  )
  parser.add_argument(
    "--output-dir",
    default="tools/preap_long/output/",
    help="Hvor CSV + stats skrives.",
  )
  parser.add_argument(
    "--tolerance-di",
    type=int,
    default=5,
    help=(
      "Reservert for fremtidig finjustering av classify-thresholds. "
      "Brukes ikke i nåværende implementasjon — sprintplan §4 Fase C-"
      "akseptkriterium er hardkodet."
    ),
  )
  return parser


def main(argv: Optional[List[str]] = None) -> int:
  """CLI entry. Returnerer exit code (0/1/2/3)."""
  parser = build_arg_parser()
  args = parser.parse_args(argv)

  os.makedirs(args.output_dir, exist_ok=True)
  basename = _route_basename(args.route)
  csv_path = os.path.join(args.output_dir, f"paritet_{basename}.csv")
  stats_path = os.path.join(args.output_dir, f"stats_{basename}.txt")

  try:
    rows = replay(args.route, max_segments=args.max_segments)
  except Exception as exc:
    print(f"[paritet] PIPELINE-FEIL: {exc!r}", file=sys.stderr)
    return EXIT_PIPELINE_ERROR

  write_csv(rows, csv_path)
  stats = classify(rows)
  write_stats(stats, stats_path)
  print(stats.as_text_report())
  print(f"\nCSV skrevet: {csv_path}")
  print(f"Stats skrevet: {stats_path}")
  return stats.exit_code


if __name__ == "__main__":
  sys.exit(main())
