from cereal import car
from openpilot.selfdrive.controls.lib.longcontrol import LongCtrlState, LongControl, long_control_state_trans




class TestLongControlStateTransition:

  def test_stay_stopped(self):
    CP = car.CarParams.new_message()
    active = True
    current_state = LongCtrlState.stopping
    next_state = long_control_state_trans(CP, active, current_state, v_ego=0.1,
                             should_stop=True, brake_pressed=False, cruise_standstill=False)
    assert next_state == LongCtrlState.stopping
    next_state = long_control_state_trans(CP, active, current_state, v_ego=0.1,
                             should_stop=False, brake_pressed=True, cruise_standstill=False)
    assert next_state == LongCtrlState.stopping
    next_state = long_control_state_trans(CP, active, current_state, v_ego=0.1,
                             should_stop=False, brake_pressed=False, cruise_standstill=True)
    assert next_state == LongCtrlState.stopping
    next_state = long_control_state_trans(CP, active, current_state, v_ego=1.0,
                             should_stop=False, brake_pressed=False, cruise_standstill=False)
    assert next_state == LongCtrlState.pid
    active = False
    next_state = long_control_state_trans(CP, active, current_state, v_ego=1.0,
                             should_stop=False, brake_pressed=False, cruise_standstill=False)
    assert next_state == LongCtrlState.off

def test_engage():
  CP = car.CarParams.new_message()
  active = True
  current_state = LongCtrlState.off
  next_state = long_control_state_trans(CP, active, current_state, v_ego=0.1,
                             should_stop=True, brake_pressed=False, cruise_standstill=False)
  assert next_state == LongCtrlState.stopping
  next_state = long_control_state_trans(CP, active, current_state, v_ego=0.1,
                             should_stop=False, brake_pressed=True, cruise_standstill=False)
  assert next_state == LongCtrlState.stopping
  next_state = long_control_state_trans(CP, active, current_state, v_ego=0.1,
                             should_stop=False, brake_pressed=False, cruise_standstill=True)
  assert next_state == LongCtrlState.stopping
  next_state = long_control_state_trans(CP, active, current_state, v_ego=0.1,
                             should_stop=False, brake_pressed=False, cruise_standstill=False)
  assert next_state == LongCtrlState.pid

def test_starting():
  CP = car.CarParams.new_message(startingState=True, vEgoStarting=0.5)
  active = True
  current_state = LongCtrlState.starting
  next_state = long_control_state_trans(CP, active, current_state, v_ego=0.1,
                             should_stop=False, brake_pressed=False, cruise_standstill=False)
  assert next_state == LongCtrlState.starting
  next_state = long_control_state_trans(CP, active, current_state, v_ego=1.0,
                             should_stop=False, brake_pressed=False, cruise_standstill=False)
  assert next_state == LongCtrlState.pid


# --- Fase B (2026-05-23): D-term + integral-leak + plant-delay verifikasjon ---

def _build_preap_cp():
  """Tesla preap-mock CarParams med Fase B-tuning."""
  CP = car.CarParams.new_message()
  CP.brand = 'tesla'
  CP.carFingerprint = 'TESLA_MODEL_S_PREAP'
  CP.longitudinalTuning.kpBP = [0.0, 3.0, 6.0, 35.0]
  CP.longitudinalTuning.kpV = [0.20, 0.20, 0.20, 0.20]
  CP.longitudinalTuning.kiBP = [0.0, 3.0, 6.0, 35.0]
  CP.longitudinalTuning.kiV = [0.04, 0.06, 0.08, 0.12]
  CP.longitudinalTuning.kdBP = [0.0, 3.0, 6.0, 35.0]
  CP.longitudinalTuning.kdV = [0.02, 0.04, 0.05, 0.05]
  CP.longitudinalTuning.kf = 1.0
  CP.stoppingDecelRate = 0.3
  CP.startAccel = 0.0
  CP.stopAccel = -0.5
  CP.vEgoStarting = 0.1
  CP.longitudinalActuatorDelay = 0.55
  return CP


class TestLongControlFaseB:

  def test_d_term_passed_to_pid(self):
    """LongControl skal initialisere PIDController med k_d fra kdBP/kdV."""
    CP = _build_preap_cp()
    lc = LongControl(CP)
    # k_d-property er speed-interpolert; sjekk underliggende values
    # (Float32 i capnp gir ~1e-7 presisjon-tap)
    expected = [0.02, 0.04, 0.05, 0.05]
    for got, exp in zip(lc.pid._k_d[1], expected):
      assert abs(got - exp) < 1e-5, f"k_d mismatch: {got} vs {exp}"

  def test_last_error_initialized_zero(self):
    CP = _build_preap_cp()
    lc = LongControl(CP)
    assert lc.last_error == 0.0

  def test_last_error_reset_on_reset(self):
    CP = _build_preap_cp()
    lc = LongControl(CP)
    lc.last_error = 0.5  # simulate mid-update state
    lc.reset()
    assert lc.last_error == 0.0

  def test_actuator_delay_055(self):
    """Plant-delay korreksjon: 0.4 → 0.55 (drive 0000007f mean)."""
    CP = _build_preap_cp()
    assert abs(CP.longitudinalActuatorDelay - 0.55) < 1e-6

  def test_integral_leak_tesla_preap(self):
    """Tesla preap fingerprint → integral_leak = 0.998 (Fase B default)."""
    CP = _build_preap_cp()
    lc = LongControl(CP)
    assert lc.integral_leak == 0.998

  def test_integral_leak_disabled_for_other_brand(self):
    """Non-Tesla brand → integral_leak = 1.0 (ingen endring fra pre-Fase B)."""
    CP = _build_preap_cp()
    CP.brand = 'honda'
    CP.carFingerprint = 'HONDA_CIVIC'
    lc = LongControl(CP)
    assert lc.integral_leak == 1.0

  def test_pid_state_initial_off(self):
    """LongControl skal starte i 'off' state, prev_long_control_state = off."""
    CP = _build_preap_cp()
    lc = LongControl(CP)
    assert lc.long_control_state == LongCtrlState.off
    assert lc.prev_long_control_state == LongCtrlState.off

  def test_kd_default_when_capnp_missing(self):
    """Hvis kdBP/kdV mangler (pre-Fase B build), default til flat 0."""
    # Construct CP without kdBP — capnp returnerer empty list by default
    CP = car.CarParams.new_message()
    CP.longitudinalTuning.kpBP = [0.0]
    CP.longitudinalTuning.kpV = [0.0]
    CP.longitudinalTuning.kiBP = [0.0]
    CP.longitudinalTuning.kiV = [0.0]
    # kdBP/kdV NOT set
    CP.stoppingDecelRate = 0.3
    CP.startAccel = 0.0
    CP.stopAccel = -0.5
    CP.vEgoStarting = 0.1
    lc = LongControl(CP)
    # Empty list → fallback to [0.0]
    assert list(lc.pid._k_d[1]) == [0.0]
