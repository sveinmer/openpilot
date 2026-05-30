"""Pure-Python referanse-port av Tinkla 0.6.6 PCC_module.update_pdl.

Formål: paritets-test mot NAP `opendbc_repo/opendbc/car/tesla/pedal/controller.py`.
Denne porten produserer eksakt samme `pedal_DI`-output som Tinkla 0.6.6 ville gitt
på samme inputs, uten cereal/Params/messaging-avhengigheter.

KILDE-PEKERE (Tinkla 0.6.6, /home/svein/repos/Tinkla/):
- selfdrive/car/tesla/PCC_module.py
    * MAX_PEDAL_VALUE = 112.                                  (linje 26)
    * PEDAL_HYST_GAP = 1.0                                    (linje 27)
    * PEDAL_MAX_UP = MAX_PEDAL_VALUE * _DT / 2                (linje 29)
    * PEDAL_MAX_DOWN = MAX_PEDAL_VALUE * _DT / 0.4            (linje 31)
    * _DT = 0.05                                              (linje 17)
    * MPC_BRAKE_MULTIPLIER = 6.                               (linje 451)
    * PedalForZeroTorque = 18.                                (linje 152, default)
    * TORQUE_LEVEL_ACC = 0., TORQUE_LEVEL_DECEL = -30.        (linje 37-38)
    * tesla_compute_gb(accel, speed) = float(accel) / 3.      (linje 88-89)
    * pedal_zero-switch ved v_ego >= 5 mph                    (linje 456)
    * tesla_brake = clip((1-apply_brake)*pedal_zero, 0, pz)   (linje 458)
    * tesla_accel = clip(apply_accel*(MAX-pz), 0, MAX-pz)     (linje 459)
    * tesla_pedal = tesla_brake + tesla_accel                 (linje 460)
    * hysteresis + rate-limit + clip 0..MAX                   (linje 462-465)
    * pedal_hysteresis()                                      (linje 578-587)
- selfdrive/controls/lib/longcontrol.py
    * STOPPING_EGO_SPEED = 0.5                                (linje 9)
    * MIN_CAN_SPEED = 0.3, STOPPING_TARGET_SPEED = 0.31       (linje 10-11)
    * STARTING_TARGET_SPEED = 0.5                             (linje 12)
    * BRAKE_THRESHOLD_TO_PID = 0.2                            (linje 13)
    * STOPPING_BRAKE_RATE = 0.2, STARTING_BRAKE_RATE = 0.8    (linje 15-16)
    * RATE = 100.0                                            (linje 22)
    * long_control_state_trans()                              (linje 25-57)
- selfdrive/controls/lib/pid_real.py
    * 3-term PID med MovingAverage(3) for D                   (linje 15-108)
    * sat_count_rate=1/rate, i_unwind_rate=0.3/rate           (linje 24-25)
    * i_rate=1/rate, d_rate=7/rate                            (linje 26-28)
- selfdrive/car/tesla/speed_utils/movingaverage.py
    * MovingAverage(length) for D-term smoothing              (alle linjer)
- selfdrive/car/tesla/interface.py
    * longitudinalTuning.kpBP/kpV/kiBP/kiV (Model S, ikke SP) (linje 154-157)
        kpBP=[0., 5., 22., 35.], kpV=[0.4]*4
        kiBP=[0.],               kiV=[0.01]
    * kdBp=[0,5,22,35], kdV=[0.01,0.02,0.04,0.04]             (longcontrol.py:64-65)
    * gasMaxBP=[2.8, 42.], gasMaxV=[0.1, 0.37]                (linje 190-191)
    * brakeMaxBP=[0.], brakeMaxV=[1.]                         (linje 192-193)
    * deadzoneBP=[0.], deadzoneV=[0.]                         (linje 195-196)
    * stoppingControl=True, startAccel=0.5                    (linje 198, 201)

Note om NAP `PEDAL_M1/M2/D` (0.050796813, 0.101593626, -22.85856576):
Disse er CAN-frame scaling-konstanter for `accel_command → int_cmd1/int_cmd2`
felter, IKKE `accel → pedal_DI`-mapping (se NAP teslacan.py:8-50). Tinkla 0.6.6
har dem ikke i PCC_module.py — pedal_DI-verdien produseres direkte av
tesla_brake + tesla_accel-kjeden. Referansen porter Tinkla-kjeden eksakt og
lar M1/M2/D-CAN-encoding være utenfor scope.

API:
    state = TinklaLongState.initial()
    pedal_di, state = compute_tinkla_pedal_di(
        accel_request, v_ego, prev_pedal_di, prev_tesla_accel, state)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

# ---------------------------------------------------------------------------
# Pure helpere (port av common.numpy_fast.clip og interp uten numpy-import)
# ---------------------------------------------------------------------------


def _clip(x: float, lo: float, hi: float) -> float:
    """Identisk semantikk som common.numpy_fast.clip(x, lo, hi)."""
    if x < lo:
        return lo
    if x > hi:
        return hi
    return x


def _interp(x: float, xp: Sequence[float], fp: Sequence[float]) -> float:
    """1-D lineær interpolasjon a la numpy.interp.

    xp må være monotont stigende (samme krav som numpy.interp).
    Returnerer fp[0] for x <= xp[0] og fp[-1] for x >= xp[-1].
    """
    n = len(xp)
    if n == 0:
        raise ValueError("xp empty")
    if n == 1:
        return float(fp[0])
    if x <= xp[0]:
        return float(fp[0])
    if x >= xp[-1]:
        return float(fp[-1])
    for i in range(1, n):
        if x <= xp[i]:
            x0, x1 = xp[i - 1], xp[i]
            y0, y1 = fp[i - 1], fp[i]
            if x1 == x0:
                return float(y1)
            return float(y0 + (y1 - y0) * (x - x0) / (x1 - x0))
    return float(fp[-1])  # unreachable


def _apply_deadzone(error: float, deadzone: float) -> float:
    if error > deadzone:
        return error - deadzone
    if error < -deadzone:
        return error + deadzone
    return 0.0


def _sign(x: float) -> float:
    if x > 0.0:
        return 1.0
    if x < 0.0:
        return -1.0
    return 0.0


# ---------------------------------------------------------------------------
# Tinkla-konstanter (eksakte verdier, verifisert mot kilde — se header)
# ---------------------------------------------------------------------------

_DT = 0.05  # PCC_module._DT (linje 17)
MAX_PEDAL_VALUE = 112.0  # PCC_module:26
PEDAL_HYST_GAP = 1.0  # PCC_module:27
PEDAL_MAX_UP = MAX_PEDAL_VALUE * _DT / 2.0  # = 2.8 per tick (PCC_module:29)
PEDAL_MAX_DOWN = MAX_PEDAL_VALUE * _DT / 0.4  # = 14.0 per tick (PCC_module:31)
MPC_BRAKE_MULTIPLIER = 6.0  # PCC_module:451
DEFAULT_PEDAL_FOR_ZERO_TORQUE = 18.0  # PCC_module:152 startverdi
TORQUE_LEVEL_ACC = 0.0  # PCC_module:37
TORQUE_LEVEL_DECEL = -30.0  # PCC_module:38

# enhetskonverteringer (selfdrive.config.Conversions)
MS_TO_MPH = 2.2369362920544
MPH_TO_MS = 1.0 / MS_TO_MPH

# longcontrol.py-konstanter
STOPPING_EGO_SPEED = 0.5
MIN_CAN_SPEED = 0.3
STOPPING_TARGET_SPEED = MIN_CAN_SPEED + 0.01
STARTING_TARGET_SPEED = 0.5
BRAKE_THRESHOLD_TO_PID = 0.2
STOPPING_BRAKE_RATE = 0.2
STARTING_BRAKE_RATE = 0.8
BRAKE_STOPPING_TARGET = 0.5
RATE = 100.0

# longitudinalTuning (Tesla Model S, ikke SP — interface.py:154-157 + longcontrol.py:64-65)
LONG_KP_BP: Sequence[float] = (0.0, 5.0, 22.0, 35.0)
LONG_KP_V: Sequence[float] = (0.4, 0.4, 0.4, 0.4)
LONG_KI_BP: Sequence[float] = (0.0,)
LONG_KI_V: Sequence[float] = (0.01,)
LONG_KD_BP: Sequence[float] = (0.0, 5.0, 22.0, 35.0)
LONG_KD_V: Sequence[float] = (0.01, 0.02, 0.04, 0.04)
GAS_MAX_BP: Sequence[float] = (2.8, 42.0)
GAS_MAX_V: Sequence[float] = (0.1, 0.37)
BRAKE_MAX_BP: Sequence[float] = (0.0,)
BRAKE_MAX_V: Sequence[float] = (1.0,)
DEADZONE_BP: Sequence[float] = (0.0,)
DEADZONE_V: Sequence[float] = (0.0,)
START_ACCEL = 0.5

# LongCtrlState (enum-paritet med cereal log.ControlsState.LongControlState)
LONG_OFF = 0
LONG_PID = 1
LONG_STOPPING = 2
LONG_STARTING = 3


# ---------------------------------------------------------------------------
# tesla_compute_gb (PCC_module:88-89)
# ---------------------------------------------------------------------------


def tesla_compute_gb(accel: float, speed: float = 0.0) -> float:
    return float(accel) / 3.0


# ---------------------------------------------------------------------------
# MovingAverage (port av speed_utils/movingaverage.py)
# ---------------------------------------------------------------------------


@dataclass
class MovingAverage:
    length: int
    position: int = 0
    sum_: float = 0.0
    no_items: int = 0
    values: List[float] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.values:
            self.values = [0.0] * self.length

    def reset(self) -> None:
        self.position = 0
        self.sum_ = 0.0
        self.no_items = 0
        self.values = [0.0] * self.length

    def add(self, element: float) -> float:
        if self.no_items == self.length:
            self.no_items -= 1
            self.sum_ -= self.values[self.position]
        self.values[self.position] = element
        self.sum_ += self.values[self.position]
        self.no_items += 1
        self.position += 1
        if self.sum_ == 0.0:
            # paritet med kilden: hvis sum_ blir 0, full reset
            self.position = 0
            self.sum_ = 0.0
            self.no_items = 0
            return 0.0
        self.position = self.position % self.length
        return self.sum_ / self.no_items


# ---------------------------------------------------------------------------
# PIController (port av selfdrive/controls/lib/pid_real.py)
# ---------------------------------------------------------------------------


@dataclass
class PIDState:
    k_p_bp: Sequence[float]
    k_p_v: Sequence[float]
    k_i_bp: Sequence[float]
    k_i_v: Sequence[float]
    k_d_bp: Sequence[float]
    k_d_v: Sequence[float]
    pos_limit: float = 0.0
    neg_limit: float = 0.0
    rate: float = RATE
    sat_limit: float = 0.8
    sat_count_rate: float = 1.0 / RATE
    i_unwind_rate: float = 0.3 / RATE
    i_rate: float = 1.0 / RATE
    d_rate: float = 7.0 / RATE
    speed: float = 0.0

    # mutabel state
    p: float = 0.0
    i: float = 0.0
    d: float = 0.0
    sat_count: float = 0.0
    saturated: bool = False
    control: float = 0.0
    past_errors_avg: float = 0.0
    past_errors: MovingAverage = field(default_factory=lambda: MovingAverage(3))

    @classmethod
    def build(
        cls,
        k_p: Tuple[Sequence[float], Sequence[float]],
        k_i: Tuple[Sequence[float], Sequence[float]],
        k_d: Tuple[Sequence[float], Sequence[float]],
        rate: float = RATE,
        sat_limit: float = 0.8,
    ) -> "PIDState":
        return cls(
            k_p_bp=k_p[0],
            k_p_v=k_p[1],
            k_i_bp=k_i[0],
            k_i_v=k_i[1],
            k_d_bp=k_d[0],
            k_d_v=k_d[1],
            rate=rate,
            sat_limit=sat_limit,
            sat_count_rate=1.0 / rate,
            i_unwind_rate=0.3 / rate,
            i_rate=1.0 / rate,
            d_rate=7.0 / rate,
        )

    def reset(self) -> None:
        self.p = 0.0
        self.i = 0.0
        self.d = 0.0
        self.sat_count = 0.0
        self.saturated = False
        self.control = 0.0
        self.past_errors_avg = 0.0
        self.past_errors.reset()

    def _kp(self) -> float:
        return _interp(self.speed, self.k_p_bp, self.k_p_v)

    def _ki(self) -> float:
        return _interp(self.speed, self.k_i_bp, self.k_i_v)

    def _kd(self) -> float:
        return _interp(self.speed, self.k_d_bp, self.k_d_v)

    def _check_saturation(self, control: float, override: bool, error: float) -> bool:
        saturated = (control < self.neg_limit) or (control > self.pos_limit)
        if saturated and not override and abs(error) > 0.1:
            self.sat_count += self.sat_count_rate
        else:
            self.sat_count -= self.sat_count_rate
        self.sat_count = _clip(self.sat_count, 0.0, 1.0)
        return self.sat_count > self.sat_limit

    def update(
        self,
        setpoint: float,
        measurement: float,
        speed: float = 0.0,
        check_saturation: bool = True,
        override: bool = False,
        feedforward: float = 0.0,
        deadzone: float = 0.0,
        freeze_integrator: bool = False,
    ) -> float:
        self.speed = speed
        error = _apply_deadzone(setpoint - measurement, deadzone)
        self.p = error * self._kp()
        self.d = 0.0
        if self.past_errors.no_items == self.past_errors.length:
            self.d = self._kd() * ((error - self.past_errors_avg) / self.d_rate)
        self.past_errors_avg = self.past_errors.add(error)

        if override:
            self.i -= self.i_unwind_rate * _sign(self.i)
            control = self.p + self.i + self.d
            control = tesla_compute_gb(control, speed=self.speed)
        else:
            i = self.i + error * self._ki() * self.i_rate
            control = self.p + i + self.d
            control = tesla_compute_gb(control, speed=self.speed)
            if (
                (error >= 0 and (control <= self.pos_limit or i < 0.0))
                or (error <= 0 and (control >= self.neg_limit or i > 0.0))
            ) and not freeze_integrator:
                self.i = i
            else:
                control = self.p + self.i + self.d
                control = tesla_compute_gb(control, speed=self.speed)

        if check_saturation:
            self.saturated = self._check_saturation(control, override, error)
        else:
            self.saturated = False

        self.control = _clip(control, self.neg_limit, self.pos_limit)
        return self.control


# ---------------------------------------------------------------------------
# LongControl state machine (port av selfdrive/controls/lib/longcontrol.py)
# ---------------------------------------------------------------------------


def _long_control_state_trans(
    active: bool,
    state: int,
    v_ego: float,
    v_target: float,
    v_pid: float,
    output_gb: float,
    brake_pressed: bool,
    cruise_standstill: bool,
) -> int:
    stopping_condition = (v_ego < 2.0 and cruise_standstill) or (
        v_ego < STOPPING_EGO_SPEED
        and (
            (v_pid < STOPPING_TARGET_SPEED and v_target < STOPPING_TARGET_SPEED)
            or brake_pressed
        )
    )
    starting_condition = v_target > STARTING_TARGET_SPEED and not cruise_standstill

    if not active:
        return LONG_OFF

    if state == LONG_OFF:
        return LONG_PID
    if state == LONG_PID:
        if stopping_condition:
            return LONG_STOPPING
    elif state == LONG_STOPPING:
        if starting_condition:
            return LONG_STARTING
    elif state == LONG_STARTING:
        if stopping_condition:
            return LONG_STOPPING
        elif output_gb >= -BRAKE_THRESHOLD_TO_PID:
            return LONG_PID
    return state


@dataclass
class LongControlState:
    pid: PIDState
    long_state: int = LONG_OFF
    v_pid: float = 0.0
    last_output_gb: float = 0.0
    stopping_control: bool = True

    @classmethod
    def build(cls) -> "LongControlState":
        return cls(
            pid=PIDState.build(
                k_p=(LONG_KP_BP, LONG_KP_V),
                k_i=(LONG_KI_BP, LONG_KI_V),
                k_d=(LONG_KD_BP, LONG_KD_V),
            ),
            stopping_control=True,
        )

    def reset(self, v_pid: float) -> None:
        self.pid.reset()
        self.v_pid = v_pid

    def update(
        self,
        active: bool,
        v_ego: float,
        brake_pressed: bool,
        standstill: bool,
        cruise_standstill: bool,
        v_cruise: float,
        v_target: float,
        v_target_future: float,
        a_target: float,
    ) -> Tuple[float, float]:
        gas_max = _interp(v_ego, GAS_MAX_BP, GAS_MAX_V)
        brake_max = _interp(v_ego, BRAKE_MAX_BP, BRAKE_MAX_V)

        output_gb = self.last_output_gb
        self.long_state = _long_control_state_trans(
            active,
            self.long_state,
            v_ego,
            v_target_future,
            self.v_pid,
            output_gb,
            brake_pressed,
            cruise_standstill,
        )

        v_ego_pid = max(v_ego, MIN_CAN_SPEED)

        if self.long_state == LONG_OFF:
            self.v_pid = v_ego_pid
            self.pid.reset()
            output_gb = 0.0

        elif self.long_state == LONG_PID:
            self.v_pid = v_target
            self.pid.pos_limit = gas_max
            self.pid.neg_limit = -brake_max
            prevent_overshoot = (
                not self.stopping_control and v_ego < 1.5 and v_target_future < 0.7
            )
            deadzone = _interp(v_ego_pid, DEADZONE_BP, DEADZONE_V)
            output_gb = self.pid.update(
                self.v_pid,
                v_ego_pid,
                speed=v_ego_pid,
                deadzone=deadzone,
                feedforward=a_target,
                freeze_integrator=prevent_overshoot,
            )
            if prevent_overshoot:
                output_gb = min(output_gb, 0.0)

        elif self.long_state == LONG_STOPPING:
            if (not standstill) or output_gb > -BRAKE_STOPPING_TARGET:
                output_gb -= STOPPING_BRAKE_RATE / RATE
            output_gb = _clip(output_gb, -brake_max, gas_max)
            self.v_pid = v_ego
            self.pid.reset()

        elif self.long_state == LONG_STARTING:
            if output_gb < -0.2:
                output_gb += STARTING_BRAKE_RATE / RATE
            self.v_pid = v_ego
            self.pid.reset()

        self.last_output_gb = output_gb
        final_gas = _clip(output_gb, 0.0, gas_max)
        final_brake = -_clip(output_gb, -brake_max, 0.0)
        return final_gas, final_brake


# ---------------------------------------------------------------------------
# Top-level state-bundle for paritets-test
# ---------------------------------------------------------------------------


@dataclass
class TinklaLongState:
    """Bærer all PCC-FSM-state mellom ticks."""

    long_control: LongControlState
    pedal_steady: float = 0.0  # hysteresis-anker (PCC_module:147)
    prev_tesla_pedal: float = 0.0  # rate-limit-anker (PCC_module:149)
    prev_tesla_accel: float = 0.0  # adaptive zero-torque-anker (PCC_module:148)
    pedal_for_zero_torque: float = DEFAULT_PEDAL_FOR_ZERO_TORQUE  # PCC_module:152
    last_torque_for_pedal_for_zero_torque: float = TORQUE_LEVEL_DECEL  # PCC_module:153
    pedal_idx: int = 0  # CAN rolling counter, 0..15

    @classmethod
    def initial(cls) -> "TinklaLongState":
        return cls(long_control=LongControlState.build())


# ---------------------------------------------------------------------------
# Hovedmapping: accel → pedal_DI (port av PCC_module.update_pdl, OpMode-path)
# ---------------------------------------------------------------------------


def _pedal_hysteresis(state: TinklaLongState, pedal: float, enabled: bool) -> float:
    """Port av PCC_module.pedal_hysteresis (linje 578-587)."""
    if not enabled:
        state.pedal_steady = 0.0
    elif pedal > state.pedal_steady + PEDAL_HYST_GAP:
        state.pedal_steady = pedal - PEDAL_HYST_GAP
    elif pedal < state.pedal_steady - PEDAL_HYST_GAP:
        state.pedal_steady = pedal + PEDAL_HYST_GAP
    return state.pedal_steady


def _update_pedal_for_zero_torque(
    state: TinklaLongState,
    torque_level: float,
    v_ego: float,
) -> None:
    """Port av PCC_module.update_pdl linje 321-330 (adaptive zero-torque)."""
    if (
        torque_level < TORQUE_LEVEL_ACC
        and torque_level > TORQUE_LEVEL_DECEL
        and v_ego >= 10.0 * MPH_TO_MS
        and abs(torque_level) < abs(state.last_torque_for_pedal_for_zero_torque)
        and state.prev_tesla_accel > 0.0
    ):
        state.pedal_for_zero_torque = state.prev_tesla_accel
        state.last_torque_for_pedal_for_zero_torque = torque_level


def compute_tinkla_pedal_di(
    accel_request: float,
    v_ego: float,
    prev_pedal_di: float,
    prev_tesla_accel: float,
    state: Optional[TinklaLongState] = None,
    *,
    enabled: bool = True,
    brake_request: float = 0.0,
    torque_level: float = 0.0,
) -> Tuple[float, TinklaLongState]:
    """Returner (pedal_di, ny_state) per Tinkla 0.6.6 update_pdl OpMode-path.

    OpMode-pathen (PCC_module.py:444-446): `output_gb = actuators.gas - actuators.brake`.
    NAP-pedal-controlleren gir `accel` direkte (uten radar/follow) — vi tolker
    `accel_request` som `actuators.gas` når positiv og som `actuators.brake` når
    negativ. Caller kan også gi `brake_request` eksplisitt (default 0) for å
    matche en konkret NAP-actuator-splitt; ellers regnes output_gb = accel_request.

    Args:
        accel_request: m/s^2. Tolkes som output_gb-input (PCC OpMode).
        v_ego: m/s, kjøretøyhastighet.
        prev_pedal_di: forrige tick sin pedal_DI (rate-limit-anker). Brukes som
            `state.prev_tesla_pedal`-override (PCC_module:464 forventer at denne
            anker-en er live mellom ticks).
        prev_tesla_accel: forrige apply_accel*enable_pedal (adaptive zero-torque-input).
        state: TinklaLongState; bruk `TinklaLongState.initial()` for første tick.
        enabled: tilsvarer `self.enable_pedal_cruise` (PCC_module:465-466). False
            tvinger pedal_DI = 0 og hysteresis-reset.
        brake_request: eksplisitt actuators.brake. Hvis 0 (default), brukes
            negative accel_request som brake.
        torque_level: CS.torqueLevel for adaptive zero-torque-oppdatering.

    Returns:
        (pedal_di, oppdatert_state).
    """
    if state is None:
        state = TinklaLongState.initial()

    # synkroniser anker fra caller — gjør funksjonen idempotent når caller
    # styrer prev_pedal_di / prev_tesla_accel eksplisitt fra utsiden
    state.prev_tesla_pedal = float(prev_pedal_di)
    state.prev_tesla_accel = float(prev_tesla_accel)

    # adaptive PedalForZeroTorque (PCC_module:321-330)
    _update_pedal_for_zero_torque(state, torque_level, v_ego)

    # OpMode-path: output_gb = actuators.gas - actuators.brake (PCC_module:444-446)
    if brake_request == 0.0:
        # tolkning: positiv accel = gas, negativ = brake (NAP-default)
        output_gb = accel_request
    else:
        gas = max(accel_request, 0.0)
        output_gb = gas - brake_request

    # apply_accel/apply_brake-splitt (PCC_module:450-452)
    apply_accel = _clip(output_gb, 0.0, 1.0)
    # _brake_pedal_min er normalt lead/curve-aware; uten radar i OpMode-paritet
    # bruker vi konservativ -1 (full regen tillatt) — Tinkla-default for
    # v_ego <= 7 MPH og generell envelope. NAP-pedal-mapping har ikke radar-aware
    # brake-clipping for sin DI-utregning, så dette gir bedre paritet enn å
    # plugge inn _brake_pedal_min-multi-map.
    apply_brake = -_clip(output_gb * MPC_BRAKE_MULTIPLIER, -1.0, 0.0)

    # pedal_zero-switch (PCC_module:454-457)
    pedal_zero = 0.0
    if v_ego >= 5.0 * MPH_TO_MS:
        pedal_zero = state.pedal_for_zero_torque

    # tesla_brake/tesla_accel-mapping (PCC_module:458-460)
    tesla_brake = _clip((1.0 - apply_brake) * pedal_zero, 0.0, pedal_zero)
    tesla_accel = _clip(
        apply_accel * (MAX_PEDAL_VALUE - pedal_zero),
        0.0,
        MAX_PEDAL_VALUE - pedal_zero,
    )
    tesla_pedal = tesla_brake + tesla_accel

    # hysteresis (PCC_module:462)
    tesla_pedal = _pedal_hysteresis(state, tesla_pedal, enabled)

    # rate-limit (PCC_module:464)
    tesla_pedal = _clip(
        tesla_pedal,
        state.prev_tesla_pedal - PEDAL_MAX_DOWN,
        state.prev_tesla_pedal + PEDAL_MAX_UP,
    )

    # final clip + enable-gate (PCC_module:465-466)
    if enabled:
        tesla_pedal = _clip(tesla_pedal, 0.0, MAX_PEDAL_VALUE)
    else:
        tesla_pedal = 0.0
    enable_pedal = 1.0 if enabled else 0.0

    # state-oppdatering (PCC_module:469-471)
    state.prev_tesla_pedal = tesla_pedal * enable_pedal
    state.prev_tesla_accel = apply_accel * enable_pedal
    state.pedal_idx = (state.pedal_idx + 1) % 16

    return state.prev_tesla_pedal, state


__all__ = [
    "MAX_PEDAL_VALUE",
    "PEDAL_HYST_GAP",
    "PEDAL_MAX_UP",
    "PEDAL_MAX_DOWN",
    "MPC_BRAKE_MULTIPLIER",
    "DEFAULT_PEDAL_FOR_ZERO_TORQUE",
    "TORQUE_LEVEL_ACC",
    "TORQUE_LEVEL_DECEL",
    "MS_TO_MPH",
    "MPH_TO_MS",
    "MovingAverage",
    "PIDState",
    "LongControlState",
    "TinklaLongState",
    "tesla_compute_gb",
    "compute_tinkla_pedal_di",
]
