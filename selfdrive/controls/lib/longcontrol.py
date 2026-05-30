import numpy as np
from cereal import car
from openpilot.common.realtime import DT_CTRL
from openpilot.selfdrive.controls.lib.drive_helpers import CONTROL_N
from openpilot.common.pid import PIDController
from openpilot.selfdrive.modeld.constants import ModelConstants

CONTROL_N_T_IDX = ModelConstants.T_IDXS[:CONTROL_N]

LongCtrlState = car.CarControl.Actuators.LongControlState


def long_control_state_trans(CP, active, long_control_state, v_ego,
                             should_stop, brake_pressed, cruise_standstill):
  stopping_condition = should_stop
  starting_condition = (not should_stop and
                        not cruise_standstill and
                        not brake_pressed)
  started_condition = v_ego > CP.vEgoStarting

  if not active:
    long_control_state = LongCtrlState.off

  else:
    if long_control_state == LongCtrlState.off:
      if not starting_condition:
        long_control_state = LongCtrlState.stopping
      else:
        if starting_condition and CP.startingState:
          long_control_state = LongCtrlState.starting
        else:
          long_control_state = LongCtrlState.pid

    elif long_control_state == LongCtrlState.stopping:
      if starting_condition and CP.startingState:
        long_control_state = LongCtrlState.starting
      elif starting_condition:
        long_control_state = LongCtrlState.pid

    elif long_control_state in [LongCtrlState.starting, LongCtrlState.pid]:
      if stopping_condition:
        long_control_state = LongCtrlState.stopping
      elif started_condition:
        long_control_state = LongCtrlState.pid
  return long_control_state

# Fase B (2026-05-23) — NAP-fork-spesifikk integral-leak. Tesla preap-stack:
# kp+ki+kd PID med kf=1.0 feedforward kan beholde integral-residual etter
# ramp-up i tens-of-seconds (drive 0000007f win0 viste i_state +0.39 stabil
# under cruise). Multiplikativ leak per tick gir defensiv wash-out uten å
# bryte steady-state-tracking. INTEGRAL_LEAK=1.0 = ingen leak (default for
# andre plattformer); for Tesla preap leses verdi fra preap.constants.
try:
  from opendbc.car.tesla.preap.constants import INTEGRAL_LEAK as _PREAP_INTEGRAL_LEAK
except ImportError:
  _PREAP_INTEGRAL_LEAK = 1.0

# Tune-bridge for outer LongControl (Tier 2.5 2026-05-28). Mirrors VDAS-side
# tune-bridge: refresh Params hvert TUNE_REFRESH_N tick, ramp smooth over
# TUNE_RAMP_S sekunder. Disabled-default via NAPTuneEnable param. Kun aktiv
# for Tesla preap.
try:
  from opendbc.car.tesla.preap.nap_conf import NAPTuneOverrides as _NAPTuneOverrides
except ImportError:
  _NAPTuneOverrides = None

try:
  from openpilot.common.swaglog import cloudlog as _cloudlog
except ImportError:
  _cloudlog = None

# 5s refresh @ 100Hz; 2s ramp
TUNE_REFRESH_N = 500
TUNE_RAMP_S = 2.0


def _resolve_integral_leak(CP):
  """Returner integral-leak per tick basert på platform. Tesla preap bruker
  defensiv 0.998-leak (~1.4s halveringstid); andre plattformer beholder
  1.0 (ingen leak, identisk pre-Fase B-oppførsel)."""
  if getattr(CP, "brand", "") == "tesla" and getattr(CP, "carFingerprint", "") == "TESLA_MODEL_S_PREAP":
    return float(_PREAP_INTEGRAL_LEAK)
  return 1.0


class LongControl:
  def __init__(self, CP):
    self.CP = CP
    self.long_control_state = LongCtrlState.off
    # Fase B: include kdBP/kdV from longitudinalTuning. Fields are added in
    # capnp schema; default to flat 0 if absent (pre-Fase B builds).
    kd_bp = getattr(CP.longitudinalTuning, 'kdBP', None) or [0.0]
    kd_v  = getattr(CP.longitudinalTuning, 'kdV',  None) or [0.0]
    self.pid = PIDController((CP.longitudinalTuning.kpBP, CP.longitudinalTuning.kpV),
                             (CP.longitudinalTuning.kiBP, CP.longitudinalTuning.kiV),
                             k_d=(list(kd_bp), list(kd_v)),
                             rate=1 / DT_CTRL)
    self.last_output_accel = 0.0
    self.last_error = 0.0
    self.prev_long_control_state = LongCtrlState.off
    self.integral_leak = _resolve_integral_leak(CP)

    # Tune-bridge state (Tier 2.5 2026-05-28). Aktiv kun for Tesla preap.
    self._tune_enabled_platform = (
      getattr(CP, "brand", "") == "tesla"
      and getattr(CP, "carFingerprint", "") == "TESLA_MODEL_S_PREAP"
      and _NAPTuneOverrides is not None
    )
    self._tune_tick = 0
    self._tune_ramp_remaining = 0.0
    # Base = innledende verdier; vi sammenligner target mot base for å
    # bestemme ramp-retning og kunne revert-til-base ved disable.
    self._tune_base_outer_ki_v = list(CP.longitudinalTuning.kiV)
    self._tune_base_leak = self.integral_leak
    # Eff = løpende verdi som faktisk anvendes (etter ramp)
    self._tune_eff_outer_ki_v = list(self._tune_base_outer_ki_v)
    self._tune_eff_leak = self._tune_base_leak
    # Target = der vi skal ende opp etter ramp
    self._tune_target_outer_ki_v = list(self._tune_base_outer_ki_v)
    self._tune_target_leak = self._tune_base_leak
    # Ramp-start verdier for lineær interpolasjon
    self._tune_ramp_start_outer_ki_v = list(self._tune_base_outer_ki_v)
    self._tune_ramp_start_leak = self._tune_base_leak
    self._tune_last_overrides_active = False

  def reset(self):
    self.pid.reset()
    self.last_error = 0.0

  def _tune_tick_step(self):
    """Periodisk refresh av live-tune-overrides + smooth ramp av outer ki + leak.
    Mirror av VirtualDAS-side tune-bridge. Kun aktiv hvis platform = Tesla preap."""
    if not self._tune_enabled_platform:
      return
    self._tune_tick += 1
    if self._tune_tick % TUNE_REFRESH_N == 0:
      self._tune_refresh_params()

    if self._tune_ramp_remaining > 0.0:
      self._tune_ramp_remaining = max(0.0, self._tune_ramp_remaining - DT_CTRL)
      progress = 1.0 - (self._tune_ramp_remaining / TUNE_RAMP_S)
      # Outer ki — element-vis lineær interp
      self._tune_eff_outer_ki_v = [
        a + (b - a) * progress
        for a, b in zip(self._tune_ramp_start_outer_ki_v,
                        self._tune_target_outer_ki_v, strict=True)
      ]
      # Leak — skalar lineær interp
      self._tune_eff_leak = (
        self._tune_ramp_start_leak
        + (self._tune_target_leak - self._tune_ramp_start_leak) * progress
      )
      # Apply: oppdater PID's k_i og self.integral_leak
      try:
        self.pid._k_i = (self.pid._k_i[0], list(self._tune_eff_outer_ki_v))
      except (AttributeError, IndexError):
        pass
      self.integral_leak = float(self._tune_eff_leak)

  def _tune_refresh_params(self):
    """Les Params og start ny ramp hvis target endret."""
    try:
      overrides = _NAPTuneOverrides.read_current()
    except Exception:
      return

    # Beregn nytt target. Hvis ingen aktiv override, target = base.
    if overrides.tune_enabled and overrides.pedal_long_ki_v is not None:
      new_target_outer_ki = list(overrides.pedal_long_ki_v)
      # Lengde-sjekk: må matche base-lengden (4 for Tesla preap)
      if len(new_target_outer_ki) != len(self._tune_base_outer_ki_v):
        new_target_outer_ki = list(self._tune_base_outer_ki_v)
    else:
      new_target_outer_ki = list(self._tune_base_outer_ki_v)

    if overrides.tune_enabled and overrides.integral_leak is not None:
      new_target_leak = float(overrides.integral_leak)
    else:
      new_target_leak = self._tune_base_leak

    target_changed = (
      new_target_outer_ki != self._tune_target_outer_ki_v
      or abs(new_target_leak - self._tune_target_leak) > 1e-6
    )
    if target_changed:
      self._tune_ramp_start_outer_ki_v = list(self._tune_eff_outer_ki_v)
      self._tune_ramp_start_leak = self._tune_eff_leak
      self._tune_target_outer_ki_v = new_target_outer_ki
      self._tune_target_leak = new_target_leak
      self._tune_ramp_remaining = TUNE_RAMP_S
      try:
        msg = ("LongControl tune-bridge: %s → ramping outer_ki=%s leak=%s"
               % (overrides.active_summary(),
                  new_target_outer_ki, new_target_leak))
        if _cloudlog is not None:
          _cloudlog.warning(msg)
      except Exception:
        pass

  def update(self, active, CS, a_target, should_stop, accel_limits):
    """Update longitudinal control. This updates the state machine and runs a PID loop"""
    self._tune_tick_step()
    self.pid.neg_limit = accel_limits[0]
    self.pid.pos_limit = accel_limits[1]

    self.long_control_state = long_control_state_trans(self.CP, active, self.long_control_state, CS.vEgo,
                                                       should_stop, CS.brakePressed,
                                                       CS.cruiseState.standstill)
    if self.long_control_state == LongCtrlState.off:
      self.reset()
      output_accel = 0.

    elif self.long_control_state == LongCtrlState.stopping:
      output_accel = self.last_output_accel
      if output_accel > self.CP.stopAccel:
        output_accel = min(output_accel, 0.0)
        output_accel -= self.CP.stoppingDecelRate * DT_CTRL
      self.reset()

    elif self.long_control_state == LongCtrlState.starting:
      output_accel = self.CP.startAccel
      self.reset()

    else:  # LongCtrlState.pid
      error = a_target - CS.aEgo
      # Fase B: derivative term on error. Suppress derivative-spike on
      # state-transition into pid (last_error was 0 after reset → false
      # rate-of-change).
      first_pid_frame = self.prev_long_control_state != LongCtrlState.pid
      error_rate = 0.0 if first_pid_frame else (error - self.last_error) / DT_CTRL
      output_accel = self.pid.update(error, error_rate=error_rate,
                                     speed=CS.vEgo, feedforward=a_target)
      self.last_error = error
      # Fase B: integral-leak per tick. Multiplikativ; INTEGRAL_LEAK=1.0
      # for andre plattformer (ingen endring), 0.998 for Tesla preap.
      if self.integral_leak < 1.0:
        self.pid.i *= self.integral_leak

    self.last_output_accel = np.clip(output_accel, accel_limits[0], accel_limits[1])
    self.prev_long_control_state = self.long_control_state
    return self.last_output_accel
