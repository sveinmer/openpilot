"""Synthetic-tester for `replay_pedal_paritet`.

Sprintplan-krav (P3 Fase C):
  - synthetic_perfect_parity → GRØNN
  - synthetic_yellow_classification (median delta ≈ 5) → GUL
  - synthetic_red_classification (≥15% > 30 DI) → RØD
  - csv_output_format → headere + struktur stemmer
  - stats_calculation → median/p95/max/bias riktig
  - cli_arg_parsing → argparse honorerer alle flagg

Disse testene MÅ ikke treffe ekte rlogs. Spor 1 og Spor 2 (rlog_loader +
tinkla_pcc_reference) er stubbet/i utvikling; her muskler vi inn synthetic
data via dependency-injection-parametere på :func:`replay`.

Kjør med::

    PYTHONPATH=. .venv/bin/pytest --noconftest -q \
        tools/preap_long/tests/test_replay_pedal_paritet.py
"""
from __future__ import annotations

import csv
import os
import tempfile
from typing import Callable, Iterable, List, Optional

import pytest

from tools.preap_long.replay_pedal_paritet import (
  CLASSIFICATION_GREEN,
  CLASSIFICATION_RED,
  CLASSIFICATION_YELLOW,
  CSV_COLUMNS,
  EXIT_GREEN,
  EXIT_PIPELINE_ERROR,
  EXIT_RED,
  EXIT_YELLOW,
  ParityStats,
  build_arg_parser,
  classify,
  main,
  replay,
  write_csv,
  write_stats,
)
from tools.preap_long.rlog_loader import PedalTick
from tools.preap_long.tinkla_pcc_reference import TinklaLongState


# ---------------------------------------------------------------------------
# Hjelpere: synthetic tick-streams + injectable compute-funksjoner.
# ---------------------------------------------------------------------------


def make_tick_loader(ticks: List[PedalTick]) -> Callable:
  """Returner en `load_ticks`-callable som matcher Spor 1-API."""

  def _loader(route_id: str, max_segments: Optional[int] = None) -> Iterable[PedalTick]:
    return iter(ticks)

  return _loader


def make_tinkla_returning(values: List[int]) -> Callable:
  """Returner en `compute_tinkla`-callable som spiller av faste DI-verdier."""
  counter = {"i": 0}

  def _compute(accel_request, v_ego, prev_pedal_di, prev_tesla_accel, state):
    idx = counter["i"]
    if idx >= len(values):
      # Hvis vi går tom for scriptede verdier, fall tilbake på 0.
      di = 0
    else:
      di = values[idx]
    counter["i"] = idx + 1
    return int(di), state

  return _compute


def make_nap_returning(values: List[int]) -> Callable:
  """Returner en `compute_nap`-callable som spiller av faste DI-verdier.

  Returnerer (voltage_stub, di) tuple for å matche NAP-controller-signatur.
  """
  counter = {"i": 0}

  def _compute(accel_request, v_ego, prev_pedal_di, target_speed_kph=None):
    idx = counter["i"]
    if idx >= len(values):
      di = 0
    else:
      di = values[idx]
    counter["i"] = idx + 1
    return (0.0, float(di))

  return _compute


def synthetic_ticks(n: int) -> List[PedalTick]:
  """100 ticks med jevn accel-rampe fra -1.0 til +1.5 m/s²."""
  ticks: List[PedalTick] = []
  for i in range(n):
    accel = -1.0 + (2.5 * i / max(1, n - 1))
    ticks.append(
      PedalTick(
        ts=0.02 * i,
        accel_request=accel,
        v_ego=10.0,
        recorded_pedal_di=None,
      )
    )
  return ticks


# ---------------------------------------------------------------------------
# Klassifisering
# ---------------------------------------------------------------------------


def test_synthetic_perfect_parity():
  """100 ticks der Tinkla == NAP → GRØNN (alle delta = 0)."""
  ticks = synthetic_ticks(100)
  values = [int(round((-1.0 + 2.5 * i / 99) * 10)) for i in range(100)]

  rows = replay(
    "synthetic|0",
    max_segments=None,
    load_ticks=make_tick_loader(ticks),
    compute_tinkla=make_tinkla_returning(values),
    compute_nap=make_nap_returning(values),
  )
  assert len(rows) == 100
  stats = classify(rows)
  assert stats.classification == CLASSIFICATION_GREEN
  assert stats.exit_code == EXIT_GREEN
  assert stats.median_abs_delta == 0.0
  assert stats.outlier_count == 0
  assert stats.bias_median == 0.0


def test_synthetic_yellow_classification():
  """Median delta ≈ 5 (utenfor GRØNN, innenfor RØD) → GUL."""
  ticks = synthetic_ticks(100)
  tinkla_values = [50] * 100
  nap_values = [45] * 100  # konstant offset 5

  rows = replay(
    "synthetic|0",
    load_ticks=make_tick_loader(ticks),
    compute_tinkla=make_tinkla_returning(tinkla_values),
    compute_nap=make_nap_returning(nap_values),
  )
  stats = classify(rows)
  assert stats.median_abs_delta == 5.0
  assert stats.bias_median == 5.0
  # bias 5 er utenfor [-3, +3] → ikke GRØNN; ingen outliers > 30 → ikke RØD
  assert stats.classification == CLASSIFICATION_YELLOW
  assert stats.exit_code == EXIT_YELLOW


def test_synthetic_red_classification():
  """15% av ticks har |delta| > 30 → RØD."""
  ticks = synthetic_ticks(100)
  # 85 ticks med delta=0, 15 ticks med delta=40
  tinkla_values = [50] * 85 + [90] * 15
  nap_values = [50] * 100

  rows = replay(
    "synthetic|0",
    load_ticks=make_tick_loader(ticks),
    compute_tinkla=make_tinkla_returning(tinkla_values),
    compute_nap=make_nap_returning(nap_values),
  )
  stats = classify(rows)
  assert stats.outlier_count == 15
  assert stats.outlier_fraction >= 0.10
  assert stats.classification == CLASSIFICATION_RED
  assert stats.exit_code == EXIT_RED


def test_red_classification_at_exact_10_percent_threshold():
  """Eksakt 10% outliers triggerer RØD (grense-test)."""
  ticks = synthetic_ticks(100)
  tinkla_values = [0] * 90 + [40] * 10
  nap_values = [0] * 100

  rows = replay(
    "synthetic|0",
    load_ticks=make_tick_loader(ticks),
    compute_tinkla=make_tinkla_returning(tinkla_values),
    compute_nap=make_nap_returning(nap_values),
  )
  stats = classify(rows)
  assert stats.outlier_count == 10
  assert stats.outlier_fraction == pytest.approx(0.10)
  assert stats.classification == CLASSIFICATION_RED


def test_green_requires_no_outliers():
  """En enkelt outlier > 30 DI nedgraderer GRØNN → GUL (ikke RØD)."""
  ticks = synthetic_ticks(100)
  tinkla_values = [50] * 99 + [85]  # én outlier på +35
  nap_values = [50] * 100

  rows = replay(
    "synthetic|0",
    load_ticks=make_tick_loader(ticks),
    compute_tinkla=make_tinkla_returning(tinkla_values),
    compute_nap=make_nap_returning(nap_values),
  )
  stats = classify(rows)
  assert stats.outlier_count == 1
  assert stats.outlier_fraction == pytest.approx(0.01)
  # 1% < 10% RØD-grense; bias=0, median=0 men outlier_count>0 → GUL
  assert stats.classification == CLASSIFICATION_YELLOW


# ---------------------------------------------------------------------------
# CSV-output
# ---------------------------------------------------------------------------


def test_csv_output_format():
  """CSV inneholder akkurat de definerte kolonnene + riktig antall rader."""
  ticks = synthetic_ticks(5)
  # Sett recorded_pedal_di på første tick for å verifisere ikke-None-path
  ticks[0] = PedalTick(
    ts=ticks[0].ts,
    accel_request=ticks[0].accel_request,
    v_ego=ticks[0].v_ego,
    recorded_pedal_di=42,
  )

  rows = replay(
    "synthetic|0",
    load_ticks=make_tick_loader(ticks),
    compute_tinkla=make_tinkla_returning([10, 20, 30, 40, 50]),
    compute_nap=make_nap_returning([10, 20, 30, 40, 50]),
  )
  assert len(rows) == 5
  assert rows[0]["recorded_tinkla_di"] == 42
  assert rows[0]["delta_recorded_vs_nap"] == 42 - 10
  assert rows[1]["recorded_tinkla_di"] is None
  assert rows[1]["delta_recorded_vs_nap"] is None

  with tempfile.TemporaryDirectory() as tmp:
    csv_path = os.path.join(tmp, "out.csv")
    write_csv(rows, csv_path)

    with open(csv_path) as fh:
      reader = csv.DictReader(fh)
      assert reader.fieldnames == CSV_COLUMNS
      loaded = list(reader)
    assert len(loaded) == 5
    # None blir tom streng i CSV
    assert loaded[1]["recorded_tinkla_di"] == ""
    assert loaded[1]["delta_recorded_vs_nap"] == ""
    assert loaded[0]["recorded_tinkla_di"] == "42"


def test_csv_skips_ticks_with_none_inputs():
  """Tick med accel_request=None eller v_ego=None skal hoppes over."""
  ticks = [
    PedalTick(ts=0.0, accel_request=None, v_ego=10.0),
    PedalTick(ts=0.02, accel_request=0.5, v_ego=None),
    PedalTick(ts=0.04, accel_request=0.5, v_ego=10.0),
  ]
  rows = replay(
    "synthetic|0",
    load_ticks=make_tick_loader(ticks),
    compute_tinkla=make_tinkla_returning([7]),
    compute_nap=make_nap_returning([5]),
  )
  assert len(rows) == 1
  assert rows[0]["ts"] == 0.04


# ---------------------------------------------------------------------------
# Stats-beregning
# ---------------------------------------------------------------------------


def test_stats_calculation():
  """Verifiser median / p95 / max / bias mot kjente verdier."""
  # Konstruer 10 ticks med deterministiske deltaer:
  # delta = -3, -2, -1, 0, 1, 2, 3, 4, 5, 6
  ticks = synthetic_ticks(10)
  tinkla_values = [t + d for t, d in zip([10] * 10, [-3, -2, -1, 0, 1, 2, 3, 4, 5, 6])]
  nap_values = [10] * 10

  rows = replay(
    "synthetic|0",
    load_ticks=make_tick_loader(ticks),
    compute_tinkla=make_tinkla_returning(tinkla_values),
    compute_nap=make_nap_returning(nap_values),
  )
  stats = classify(rows)
  abs_deltas = [3, 2, 1, 0, 1, 2, 3, 4, 5, 6]
  # median av sortert |delta| = median([0,1,1,2,2,3,3,4,5,6]) = (2+3)/2 = 2.5
  assert stats.median_abs_delta == pytest.approx(2.5)
  assert stats.max_abs_delta == 6.0
  # Signed bias: median av [-3,-2,-1,0,1,2,3,4,5,6] sortert = (1+2)/2 = 1.5
  assert stats.bias_median == pytest.approx(1.5)
  assert stats.outlier_count == 0
  # 95-percentil av sortert abs ([0,1,1,2,2,3,3,4,5,6]) ≈ 5.55 (lineær interp)
  assert stats.p95_abs_delta == pytest.approx(5.55, abs=0.05)


def test_stats_empty_rows_is_pipeline_error():
  """Tomme rows → RØD/pipeline-error exit code 3."""
  stats = classify([])
  assert stats.tick_count == 0
  assert stats.classification == CLASSIFICATION_RED
  assert stats.exit_code == EXIT_PIPELINE_ERROR


def test_parity_stats_text_report_contains_key_fields():
  """Tekst-rapporten skal nevne klassifisering + median + p95 + bias."""
  stats = ParityStats(
    tick_count=42,
    median_abs_delta=1.5,
    p95_abs_delta=4.2,
    max_abs_delta=11.0,
    bias_median=0.5,
    outlier_count=0,
    outlier_fraction=0.0,
    classification=CLASSIFICATION_GREEN,
    exit_code=EXIT_GREEN,
  )
  report = stats.as_text_report()
  assert "Antall ticks" in report
  assert "1.50" in report
  assert "4.20" in report
  assert "+0.50" in report
  assert CLASSIFICATION_GREEN in report


# ---------------------------------------------------------------------------
# CLI argparse
# ---------------------------------------------------------------------------


def test_cli_arg_parsing_required_route():
  """--route er required."""
  parser = build_arg_parser()
  with pytest.raises(SystemExit):
    parser.parse_args([])


def test_cli_arg_parsing_defaults():
  """Default-verdier matcher spec."""
  parser = build_arg_parser()
  ns = parser.parse_args(["--route", "abc|2025-11-05--05-33-11"])
  assert ns.route == "abc|2025-11-05--05-33-11"
  assert ns.max_segments is None
  assert ns.output_dir == "tools/preap_long/output/"
  assert ns.tolerance_di == 5


def test_cli_arg_parsing_all_flags():
  """Alle flagg honoreres."""
  parser = build_arg_parser()
  ns = parser.parse_args(
    [
      "--route",
      "abc|2025-11-05--05-33-11",
      "--max-segments",
      "3",
      "--output-dir",
      "/tmp/parity",
      "--tolerance-di",
      "7",
    ]
  )
  assert ns.max_segments == 3
  assert ns.output_dir == "/tmp/parity"
  assert ns.tolerance_di == 7


def test_main_pipeline_error_returns_exit_3(monkeypatch, tmp_path):
  """Hvis replay raiser, returnerer main exit 3."""
  from tools.preap_long import replay_pedal_paritet as rpp

  def _boom(*a, **kw):
    raise RuntimeError("rlog-load feilet")

  monkeypatch.setattr(rpp, "replay", _boom)
  exit_code = main(
    [
      "--route",
      "abc|2025-11-05--05-33-11",
      "--output-dir",
      str(tmp_path),
    ]
  )
  assert exit_code == EXIT_PIPELINE_ERROR


def test_main_writes_csv_and_stats(monkeypatch, tmp_path):
  """Sjekk at main skriver CSV og stats-fil + returnerer riktig exit."""
  from tools.preap_long import replay_pedal_paritet as rpp

  fake_rows = [
    {
      "ts": 0.0,
      "accel_request": 0.5,
      "v_ego": 10.0,
      "prev_pedal_di": 0,
      "tinkla_di": 20,
      "nap_di": 20,
      "recorded_tinkla_di": None,
      "delta_tinkla_vs_nap": 0,
      "delta_recorded_vs_nap": None,
    }
  ] * 50

  monkeypatch.setattr(rpp, "replay", lambda *a, **kw: fake_rows)

  exit_code = main(
    [
      "--route",
      "synth|2025-11-05--05-33-11",
      "--output-dir",
      str(tmp_path),
    ]
  )
  assert exit_code == EXIT_GREEN
  files = sorted(os.listdir(tmp_path))
  assert any(f.startswith("paritet_") and f.endswith(".csv") for f in files)
  assert any(f.startswith("stats_") and f.endswith(".txt") for f in files)


# ---------------------------------------------------------------------------
# Write-stats helper
# ---------------------------------------------------------------------------


def test_write_stats_round_trip(tmp_path):
  stats = ParityStats(
    tick_count=10,
    median_abs_delta=2.0,
    p95_abs_delta=7.0,
    max_abs_delta=10.0,
    bias_median=1.0,
    outlier_count=0,
    outlier_fraction=0.0,
    classification=CLASSIFICATION_YELLOW,
    exit_code=EXIT_YELLOW,
  )
  out = tmp_path / "stats.txt"
  write_stats(stats, str(out))
  text = out.read_text()
  assert CLASSIFICATION_YELLOW in text
  assert "Antall ticks" in text
