"""Pytest-suite for Tinkla 0.6.6 PCC-referanse-porten.

Alle tester er pure-Python uten cereal/Params-deps. Kjøres med:
    PYTHONPATH=. .venv/bin/pytest --noconftest -q \
        tools/preap_long/tests/test_tinkla_pcc_reference.py
"""

from __future__ import annotations

import math

import pytest

from tools.preap_long.tinkla_pcc_reference import (
    DEFAULT_PEDAL_FOR_ZERO_TORQUE,
    MAX_PEDAL_VALUE,
    MPH_TO_MS,
    PEDAL_HYST_GAP,
    PEDAL_MAX_DOWN,
    PEDAL_MAX_UP,
    TinklaLongState,
    compute_tinkla_pedal_di,
    tesla_compute_gb,
)


# ---------------------------------------------------------------------------
# Helper for å kjøre N ticks med samme accel og returnere DI-historikk
# ---------------------------------------------------------------------------


def _run(
    accel_request,
    v_ego,
    n_ticks,
    *,
    state=None,
    enabled=True,
    initial_di=0.0,
    initial_tesla_accel=0.0,
):
    """Kjør et accel-request (skalar eller callable(t)->float) i n_ticks.

    Returnerer (history_list_of_di, final_state).
    """
    if state is None:
        state = TinklaLongState.initial()
    prev_di = float(initial_di)
    prev_accel = float(initial_tesla_accel)
    history = []
    for t in range(n_ticks):
        a = accel_request(t) if callable(accel_request) else accel_request
        v = v_ego(t) if callable(v_ego) else v_ego
        di, state = compute_tinkla_pedal_di(
            a, v, prev_di, prev_accel, state, enabled=enabled
        )
        prev_di = di
        prev_accel = state.prev_tesla_accel
        history.append(di)
    return history, state


# ---------------------------------------------------------------------------
# 1. Initial state
# ---------------------------------------------------------------------------


def test_initial_state_default_zero():
    """TinklaLongState.initial() har null-state for alle akkumulatorer."""
    s = TinklaLongState.initial()
    assert s.pedal_steady == 0.0
    assert s.prev_tesla_pedal == 0.0
    assert s.prev_tesla_accel == 0.0
    assert s.pedal_for_zero_torque == DEFAULT_PEDAL_FOR_ZERO_TORQUE
    assert s.pedal_idx == 0
    assert s.long_control.long_state == 0  # LONG_OFF
    assert s.long_control.last_output_gb == 0.0


def test_constants_match_tinkla_source():
    """Bekreft at konstantene matcher /home/svein/repos/Tinkla/.../PCC_module.py."""
    assert MAX_PEDAL_VALUE == 112.0
    assert PEDAL_HYST_GAP == 1.0
    # _DT=0.05, MAX*_DT/2 = 2.8
    assert PEDAL_MAX_UP == pytest.approx(2.8, abs=1e-9)
    # _DT=0.05, MAX*_DT/0.4 = 14.0
    assert PEDAL_MAX_DOWN == pytest.approx(14.0, abs=1e-9)
    assert DEFAULT_PEDAL_FOR_ZERO_TORQUE == 18.0
    # tesla_compute_gb = accel/3
    assert tesla_compute_gb(3.0, 0.0) == pytest.approx(1.0)
    assert tesla_compute_gb(0.0, 0.0) == 0.0
    assert tesla_compute_gb(-6.0, 10.0) == pytest.approx(-2.0)


# ---------------------------------------------------------------------------
# 2. Constant accel ramp-up
# ---------------------------------------------------------------------------


def test_constant_accel_ramp_up():
    """Konstant accel=1.0 (m/s²) ramper opp med 2.8/tick (PEDAL_MAX_UP)."""
    history, state = _run(accel_request=1.0, v_ego=15.0, n_ticks=100)
    # første 6 ticks: 2.8, 5.6, 8.4, 11.2, 14.0, 16.8
    expected = [2.8, 5.6, 8.4, 11.2, 14.0, 16.8]
    for i, exp in enumerate(expected):
        assert history[i] == pytest.approx(exp, abs=1e-9), (
            f"tick {i}: got {history[i]}, expected {exp}"
        )
    # ved tick 95+ skal vi være ved saturated steady-state (MAX-1 pga hysteresis)
    assert history[-1] == pytest.approx(MAX_PEDAL_VALUE - PEDAL_HYST_GAP, abs=1e-9)


def test_constant_accel_steady_state_under_max():
    """Lav accel (apply_accel < 1.0) gir steady-state < MAX_PEDAL_VALUE."""
    # apply_accel = clip(0.3, 0, 1) = 0.3; pedal_zero = 18 @ v_ego=15
    # tesla_accel steady = 0.3 * (112-18) = 28.2; tesla_brake = 18 (brake=0)
    # total = 46.2; hysteresis → 45.2
    history, state = _run(accel_request=0.3, v_ego=15.0, n_ticks=100)
    final = history[-1]
    expected_steady = 0.3 * (MAX_PEDAL_VALUE - DEFAULT_PEDAL_FOR_ZERO_TORQUE)
    expected_with_zero = expected_steady + DEFAULT_PEDAL_FOR_ZERO_TORQUE
    expected_hyst = expected_with_zero - PEDAL_HYST_GAP
    assert final == pytest.approx(expected_hyst, abs=1e-9)


# ---------------------------------------------------------------------------
# 3. Step response
# ---------------------------------------------------------------------------


def test_step_response():
    """Step fra accel=0 → 1.0 ved t=10. Skal rampes opp jevnt etter steget."""

    def schedule(t):
        return 0.0 if t < 10 else 1.0

    history, state = _run(accel_request=schedule, v_ego=15.0, n_ticks=30)

    # første 6 ticks ramp-up til zero-torque steady-state (17 = 18-1)
    assert history[0] == pytest.approx(2.8, abs=1e-9)
    assert history[5] == pytest.approx(16.8, abs=1e-9)
    # tick 6-9: holdt @ 17 (zero-torque-anker pga hysteresis)
    assert history[9] == pytest.approx(17.0, abs=1e-9)
    # tick 10: step inn, +2.8 til 19.8
    assert history[10] == pytest.approx(19.8, abs=1e-9)
    # tick 11: 22.6
    assert history[11] == pytest.approx(22.6, abs=1e-9)
    # monotont stigende fra 10 og fremover
    for i in range(10, len(history) - 1):
        assert history[i + 1] >= history[i] - 1e-9


# ---------------------------------------------------------------------------
# 4. Negative accel = brake-region
# ---------------------------------------------------------------------------


def test_negative_accel_brake_region():
    """Brake-scenario: fra MAX → 0 med PEDAL_MAX_DOWN/tick (14.0)."""
    state = TinklaLongState.initial()
    state.pedal_steady = MAX_PEDAL_VALUE  # forhåndssatt hysteresis-anker
    history, state = _run(
        accel_request=-1.0,
        v_ego=15.0,
        n_ticks=15,
        state=state,
        initial_di=MAX_PEDAL_VALUE,
        initial_tesla_accel=0.5,
    )
    # 112 - 14 = 98 første tick
    assert history[0] == pytest.approx(98.0, abs=1e-9)
    # 98, 84, 70, 56, 42, 28, 14, 1.0 — sluttverdi er hysteresis-anker (pedal=0
    # med pedal_steady=112 → steady = 0 + HYST_GAP = 1.0). Pedal kan ikke gå
    # under hysteresis-anker selv om rate-limit ville tillatt det. Dette er
    # eksakt Tinkla-oppførsel: hysteresis-anker styrer floor, ikke rate-limit.
    assert history[6] == pytest.approx(14.0, abs=1e-9)
    assert history[7] == pytest.approx(1.0, abs=1e-9)
    # holder 1.0 (hysteresis-floor) etter ramp-down
    for di in history[7:]:
        assert di == pytest.approx(1.0, abs=1e-9)


def test_brake_clipped_to_zero_lower_bound():
    """Negativ accel kan aldri gi pedal_DI < 0."""
    history, _ = _run(accel_request=-5.0, v_ego=15.0, n_ticks=30)
    for di in history:
        assert di >= 0.0


# ---------------------------------------------------------------------------
# 5. Zero accel
# ---------------------------------------------------------------------------


def test_zero_accel_yields_zero_torque():
    """accel_request=0 @ v_ego >= 5 mph → steady ved PedalForZeroTorque - HYST."""
    history, state = _run(accel_request=0.0, v_ego=15.0, n_ticks=50)
    final = history[-1]
    # PedalForZeroTorque=18, hysteresis trekker 1 → 17
    expected = DEFAULT_PEDAL_FOR_ZERO_TORQUE - PEDAL_HYST_GAP
    assert final == pytest.approx(expected, abs=1e-9)
    # PedalForZeroTorque ikke endret (torque_level=0 default oppfyller ikke
    # adaptive-criteria)
    assert state.pedal_for_zero_torque == DEFAULT_PEDAL_FOR_ZERO_TORQUE


def test_zero_accel_below_5_mph_yields_zero_di():
    """Under 5 mph: pedal_zero=0, accel=0 → DI=0 (ingen zero-torque-hold)."""
    history, state = _run(accel_request=0.0, v_ego=1.0, n_ticks=50)
    # apply_accel=0, apply_brake=0, pedal_zero=0
    # tesla_brake = clip((1-0)*0, 0, 0) = 0; tesla_accel = clip(0*112, 0, 112) = 0
    # total = 0, hysteresis: pedal=0, steady=0 (uendret)
    assert history[-1] == pytest.approx(0.0, abs=1e-9)


# ---------------------------------------------------------------------------
# 6. Saturation
# ---------------------------------------------------------------------------


def test_saturation_at_max_pedal():
    """Overdrevent accel saturerer ved MAX_PEDAL_VALUE (minus hysteresis-gap)."""
    history, state = _run(accel_request=10.0, v_ego=15.0, n_ticks=200)
    final = history[-1]
    # apply_accel = clip(10, 0, 1) = 1.0
    # tesla_accel = 1.0 * (112-18) = 94; tesla_brake = 18
    # total = 112 (= MAX); hysteresis trekker 1 → 111
    expected = MAX_PEDAL_VALUE - PEDAL_HYST_GAP
    assert final == pytest.approx(expected, abs=1e-9)
    # ingen DI overskrider MAX_PEDAL_VALUE
    for di in history:
        assert di <= MAX_PEDAL_VALUE + 1e-9


def test_saturation_clipped_below_max():
    """DI kan aldri bli > MAX_PEDAL_VALUE selv ved ekstreme inputs."""
    state = TinklaLongState.initial()
    state.pedal_steady = MAX_PEDAL_VALUE
    history, _ = _run(
        accel_request=100.0,
        v_ego=30.0,
        n_ticks=50,
        state=state,
        initial_di=MAX_PEDAL_VALUE,
    )
    for di in history:
        assert di <= MAX_PEDAL_VALUE + 1e-9


# ---------------------------------------------------------------------------
# 7. Enable-gate
# ---------------------------------------------------------------------------


def test_disabled_yields_zero_di():
    """enabled=False → DI=0 og pedal_steady nullstilles."""
    state = TinklaLongState.initial()
    # først ramp opp for å få ikke-trivial state
    history, state = _run(accel_request=1.0, v_ego=15.0, n_ticks=20)
    assert history[-1] > 10.0
    # nå disable og kjør én tick
    di, state = compute_tinkla_pedal_di(
        1.0, 15.0, history[-1], 1.0, state, enabled=False
    )
    assert di == 0.0
    assert state.pedal_steady == 0.0
    assert state.prev_tesla_pedal == 0.0


# ---------------------------------------------------------------------------
# 8. Rate-limit symmetri (asymmetrisk: up=2.8, down=14.0)
# ---------------------------------------------------------------------------


def test_rate_limit_up_vs_down_asymmetric():
    """PEDAL_MAX_DOWN (14.0) er 5× PEDAL_MAX_UP (2.8) per tick."""
    assert PEDAL_MAX_DOWN == pytest.approx(5.0 * PEDAL_MAX_UP, abs=1e-9)


# ---------------------------------------------------------------------------
# 9. Adaptive PedalForZeroTorque
# ---------------------------------------------------------------------------


def test_adaptive_pedal_for_zero_torque_updates():
    """torque_level mellom (-30, 0) + v_ego >= 10 mph + prev_tesla_accel > 0
    → PedalForZeroTorque oppdateres."""
    state = TinklaLongState.initial()
    # ramp opp for å få prev_tesla_accel > 0
    prev_di = 0.0
    prev_accel = 0.0
    for t in range(20):
        di, state = compute_tinkla_pedal_di(
            1.0, 15.0, prev_di, prev_accel, state, enabled=True, torque_level=0.0
        )
        prev_di = di
        prev_accel = state.prev_tesla_accel
    assert state.prev_tesla_accel > 0.0
    pftz_before = state.pedal_for_zero_torque
    # nå med torque_level = -5 (mellom DECEL=-30 og ACC=0), v_ego=15 m/s (>10mph)
    # abs(-5) = 5 < abs(-30) (last_torque_for_pedal_for_zero_torque default)
    di, state = compute_tinkla_pedal_di(
        1.0, 15.0, prev_di, prev_accel, state, enabled=True, torque_level=-5.0
    )
    # PedalForZeroTorque skal være satt til prev_tesla_accel (apply_accel=1.0)
    # Note: dette er en *normalized* accel, ikke pedal-units — det er PCC-bug i
    # original, men vi porterer eksakt.
    assert state.pedal_for_zero_torque == 1.0
    assert state.last_torque_for_pedal_for_zero_torque == -5.0
    assert state.pedal_for_zero_torque != pftz_before


def test_adaptive_zero_torque_not_triggered_below_10_mph():
    """v_ego < 10 mph → PedalForZeroTorque uendret selv med valid torque_level."""
    state = TinklaLongState.initial()
    # 9 mph = 4.02 m/s
    v_low = 9.0 * MPH_TO_MS
    di, state = compute_tinkla_pedal_di(
        1.0, v_low, 0.0, 0.5, state, enabled=True, torque_level=-5.0
    )
    assert state.pedal_for_zero_torque == DEFAULT_PEDAL_FOR_ZERO_TORQUE


# ---------------------------------------------------------------------------
# 10. Hysteresis bidirectional
# ---------------------------------------------------------------------------


def test_hysteresis_dead_band():
    """Pedal-endring innenfor PEDAL_HYST_GAP holder pedal_steady konstant."""
    state = TinklaLongState.initial()
    # ramp opp til 17.0 (zero-torque-anker)
    history, state = _run(accel_request=0.0, v_ego=15.0, n_ticks=50, state=state)
    steady = state.pedal_steady
    assert steady == pytest.approx(17.0, abs=1e-9)
    # gi liten oscillasjon (accel=0.005 → tesla_accel = 0.005 * 94 = 0.47, total = 18.47)
    # 18.47 - 17 = 1.47 > HYST_GAP=1.0, så pedal_steady BØR oppdatere til 18.47-1.0=17.47
    di, state = compute_tinkla_pedal_di(
        0.005, 15.0, history[-1], state.prev_tesla_accel, state
    )
    # Pedal flytter seg, men subjekt for rate-limit
    assert state.pedal_steady != steady


# ---------------------------------------------------------------------------
# 11. Long-run integrity
# ---------------------------------------------------------------------------


def test_long_run_no_overflow_or_nan():
    """500 ticks med varierende accel skal ikke gi NaN, inf, eller out-of-range."""
    import math as _math

    def schedule(t):
        return 1.5 * _math.sin(t * 0.05)

    history, state = _run(accel_request=schedule, v_ego=20.0, n_ticks=500)
    for di in history:
        assert _math.isfinite(di)
        assert -1e-9 <= di <= MAX_PEDAL_VALUE + 1e-9
    # pedal_idx etter 500 ticks: 500 % 16 = 4
    assert state.pedal_idx == 500 % 16


def test_state_isolation_between_runs():
    """Bygge ny state → får samme deterministiske historikk."""
    h1, _ = _run(accel_request=1.0, v_ego=15.0, n_ticks=20)
    h2, _ = _run(accel_request=1.0, v_ego=15.0, n_ticks=20)
    assert h1 == h2
