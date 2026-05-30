"""rlog_loader — pure-helper for å ekstraktere pedal-relevante tick-data fra Tinkla 0.6.6-rlogs.

Brukt i P3 Fase B for å validere `accel → pedal_DI`-paritet mellom NAP
`pedal/controller.py` og Tinkla 0.6.6 `PCC_module.py` på samme inputs.

Designprinsipper:
  * Pure helper: ingen device-touch, ingen nettverks-IO utenfor LogReader,
    ingen Params/cereal-publishing.
  * Defensiv mot Tinkla 0.6.6's gamle capnp-schema: hvis LogReader krasjer
    eller mangler felter, skip route gracefully (logg `RuntimeError` med
    detalj-msg, ikke krasj kall-site).
  * Tick-synkronisering: `controlsState` (~50 Hz) er master. For hver
    controlsState-msg, hent siste `carControl` + `carState` fra running
    state-buffer. `sendcan`-0x551 attaches kun hvis TX skjedde i tick'en.
  * 0x551 pedal-DI invers-formula henter fra `Tinkla/selfdrive/car/tesla/
    teslacan.py::create_pedal_command_msg` (m1=0.050796813, d=-22.85856576).

Bruk:
    from openpilot.tools.preap_long.rlog_loader import load_pedal_tick_stream
    for tick in load_pedal_tick_stream("2f...|2025-11-05--05-33-11", max_segments=2):
        print(tick.ts, tick.accel_request, tick.v_ego, tick.recorded_pedal_di)
"""
from __future__ import annotations

import logging
import struct
from collections.abc import Iterable, Iterator
from dataclasses import dataclass

LOG = logging.getLogger(__name__)


def _resolve_capnp_exception() -> type[BaseException]:
    """Lazy import av capnp's exception slik at modul-import ikke krever capnp.

    Returnerer en exception-klasse som er trygg å bruke i `except`-tuples.
    Hvis capnp ikke er installert, returneres en stub-klasse som aldri matcher.
    """
    try:
        import capnp  # type: ignore[import-not-found]
        return capnp.KjException
    except Exception:
        return type("_NoCapnpException", (Exception,), {})


CAPNP_EXC: type[BaseException] = _resolve_capnp_exception()


# Tinkla 0.6.6 pedal-encoding-konstanter (fra teslacan.py::create_pedal_command_msg)
# int_accel = (accelCommand - d) / m1  →  accelCommand = (int_accel * m1) + d
TINKLA_PEDAL_M1 = 0.050796813
TINKLA_PEDAL_M2 = 0.101593626
TINKLA_PEDAL_D = -22.85856576

# CAN-adresser
ADDR_GAS_COMMAND = 0x551


@dataclass
class PedalTick:
    """Én tick av pedal-relevante data, synkronisert til en controlsState-event.

    Alle felter er Optional fordi:
      * Tinkla 0.6.6 capnp-schema kan mangle nye felter (`longActive`, etc.).
      * carControl/carState er ikke garantert å ha kommet før første
        controlsState — vi bruker last-seen running buffer.
      * recorded_pedal_di er kun satt hvis 0x551 TX faktisk skjedde i tick'en.
    """

    ts: float
    accel_request: float | None = None
    v_ego: float | None = None
    a_ego: float | None = None
    gas_pressed: bool | None = None
    brake_pressed: bool | None = None
    recorded_pedal_di: int | None = None
    long_active: bool | None = None
    enabled: bool | None = None
    pcm_acc_state: int | None = None


# ---- 0x551 sendcan-parsing ---------------------------------------------------


def decode_pedal_di_from_0x551(dat: bytes) -> int | None:
    """Decode pedal-DI (m1-skala accelCommand) fra en 0x551 6-byte CAN-payload.

    Tinkla 0.6.6 pakker bytes (se teslacan.py::create_pedal_command_msg):
        byte 0: (int_accel >> 8) & 0xFF      # high byte int_accel (m1-skala)
        byte 1: int_accel & 0xFF             # low byte int_accel  (m1-skala)
        byte 2: (int_accel2 >> 8) & 0xFF     # high byte int_accel2 (m2-skala)
        byte 3: int_accel2 & 0xFF            # low byte int_accel2 (m2-skala)
        byte 4: ((enable << 7) + idx) & 0xFF # enable + counter
        byte 5: checksum

    Returnerer rå int_accel (m1-skala), eller None hvis payload er ugyldig.
    Kaller-site multiplisere med TINKLA_PEDAL_M1 + TINKLA_PEDAL_D for å få
    accelCommand i samme enhet som ble sendt inn til create_pedal_command_msg.
    """
    if dat is None or len(dat) < 5:
        return None
    try:
        b0, b1, _b2, _b3, _b4 = struct.unpack_from("BBBBB", dat, 0)
    except struct.error:
        return None
    int_accel = (b0 << 8) | b1
    # int_accel er signed-konseptuelt (accelCommand kan være negativ via d-offset)
    # men `create_pedal_command_msg` skriver det som unsigned via `& 0xFF`.
    # Hvis MSB er satt, behandler vi det som 16-bit signed.
    if int_accel >= 0x8000:
        int_accel -= 0x10000
    return int_accel


def int_accel_to_pedal_command(int_accel: int) -> float:
    """Konverter rå int_accel (m1-skala) tilbake til accelCommand-verdien
    som ble sendt inn til Tinkla `create_pedal_command_msg`.

    Invers av: int_accel = (accelCommand - d) / m1
    →         accelCommand = int_accel * m1 + d
    """
    return int_accel * TINKLA_PEDAL_M1 + TINKLA_PEDAL_D


# ---- accel-request-ekstrahering fra carControl --------------------------------


def _extract_accel_request(cc_actuators) -> float | None:
    """Hent accel-request fra carControl.actuators.

    Tinkla 0.6.6 kan ha forskjellige felt-navn:
      * Nyere: `accel` (m/s²)
      * Eldre: `gas` + `brake` (0..1), evt. som proxy gas - brake
    Vi prøver `accel` først (foretrukket); faller tilbake til gas - brake.
    Returnerer None hvis ingen er tilgjengelig.
    """
    if cc_actuators is None:
        return None
    # Foretrekk eksplisitt accel-feltet
    try:
        accel = getattr(cc_actuators, "accel", None)
        if accel is not None:
            return float(accel)
    except (AttributeError, CAPNP_EXC):
        pass
    # Fallback: gas - brake proxy
    try:
        gas = float(getattr(cc_actuators, "gas", 0.0) or 0.0)
        brake = float(getattr(cc_actuators, "brake", 0.0) or 0.0)
        return gas - brake
    except (AttributeError, TypeError, CAPNP_EXC):
        return None


# ---- Hovedstrøm ----------------------------------------------------------------


def _iter_route_msgs(route_id: str, max_segments: int | None) -> Iterable:
    """Wrapper rundt LogReader som håndterer Tinkla-format-feil gracefully.

    Lazy-importerer LogReader/Route slik at modulen kan importeres uten at
    cereal/openpilot er fullt på plass (for ren unit-test).
    """
    try:
        from openpilot.tools.lib.logreader import LogReader
    except Exception as exc:
        raise RuntimeError(f"kunne ikke importere LogReader: {exc!r}") from exc

    identifier = route_id
    if max_segments is not None and max_segments > 0:
        # SegmentRange-syntaks: "<route>/<start>:<end>"
        # max_segments=2 → "<route>/0:2"  (segments 0 og 1)
        if "/" not in route_id.split("|", 1)[-1]:
            identifier = f"{route_id}/0:{max_segments}"

    try:
        lr = LogReader(identifier)
    except Exception as exc:
        raise RuntimeError(
            f"LogReader-konstruksjon feilet for {identifier!r}: {exc!r}"
        ) from exc

    try:
        yield from lr
    except Exception as exc:
        # Tinkla 0.6.6 capnp-format kan trigge schema-mismatch midt i iterasjon.
        raise RuntimeError(
            f"LogReader-iterasjon feilet for {identifier!r}: {exc!r}"
        ) from exc


def load_pedal_tick_stream(
    route_id: str,
    max_segments: int | None = None,
) -> Iterator[PedalTick]:
    """Iterer pedal-relevante ticks fra en Tinkla-rlog.

    Args:
        route_id: Route-ID i comma-format `<dongle>|<date>` eller med
            segment-range `<dongle>|<date>/<start>:<end>`.
        max_segments: Hvis satt, begrens til de første N segments
            (ignorert hvis route_id allerede inneholder segment-range).

    Yields:
        PedalTick per controlsState-tick (~50 Hz), synkronisert med
        siste sett carControl + carState og evt. 0x551 sendcan-frame.

    Raises:
        RuntimeError ved LogReader-feil (med detalj-msg fra wrapper).
    """
    # Running state-buffer (last-seen per msg-type).
    last_cc_actuators = None
    last_cs_v_ego: float | None = None
    last_cs_a_ego: float | None = None
    last_cs_gas_pressed: bool | None = None
    last_cs_brake_pressed: bool | None = None
    last_cs_pcm_acc_state: int | None = None

    # 0x551-frames per logMonoTime-bucket (slik vi kan attache pedal-DI til
    # nærmeste controlsState-tick). Vi tømmer bucket etter forbruk.
    pending_pedal_di: int | None = None

    for msg in _iter_route_msgs(route_id, max_segments):
        try:
            which = msg.which()
        except (AttributeError, CAPNP_EXC):
            continue

        if which == "carControl":
            try:
                last_cc_actuators = msg.carControl.actuators
            except (AttributeError, CAPNP_EXC):
                last_cc_actuators = None

        elif which == "carState":
            cs = msg.carState
            try:
                last_cs_v_ego = float(getattr(cs, "vEgo", None)) if getattr(cs, "vEgo", None) is not None else None
            except (AttributeError, TypeError, CAPNP_EXC):
                last_cs_v_ego = None
            try:
                last_cs_a_ego = float(getattr(cs, "aEgo", None)) if getattr(cs, "aEgo", None) is not None else None
            except (AttributeError, TypeError, CAPNP_EXC):
                last_cs_a_ego = None
            try:
                last_cs_gas_pressed = bool(getattr(cs, "gasPressed", None)) if getattr(cs, "gasPressed", None) is not None else None
            except (AttributeError, TypeError, CAPNP_EXC):
                last_cs_gas_pressed = None
            try:
                last_cs_brake_pressed = bool(getattr(cs, "brakePressed", None)) if getattr(cs, "brakePressed", None) is not None else None
            except (AttributeError, TypeError, CAPNP_EXC):
                last_cs_brake_pressed = None
            try:
                cruise = getattr(cs, "cruiseState", None)
                if cruise is not None:
                    # pcmAccState eksisterer ikke i alle schemas — bruk standin
                    pcm = getattr(cruise, "speedCluster", None)
                    if pcm is None:
                        pcm = getattr(cruise, "speed", None)
                    last_cs_pcm_acc_state = int(pcm) if pcm is not None else None
            except (AttributeError, TypeError, CAPNP_EXC):
                last_cs_pcm_acc_state = None

        elif which == "sendcan":
            # Søk gjennom alle CAN-frames i denne sendcan-msgen etter 0x551.
            try:
                frames = msg.sendcan
            except (AttributeError, CAPNP_EXC):
                frames = []
            for frame in frames:
                try:
                    if int(frame.address) == ADDR_GAS_COMMAND:
                        di = decode_pedal_di_from_0x551(bytes(frame.dat))
                        if di is not None:
                            pending_pedal_di = di
                            # Behold til neste controlsState-tick.
                except (AttributeError, CAPNP_EXC):
                    continue

        elif which == "controlsState":
            try:
                ts = msg.logMonoTime / 1e9
            except (AttributeError, TypeError, CAPNP_EXC):
                continue

            cs_inner = msg.controlsState
            try:
                enabled = bool(getattr(cs_inner, "enabled", None)) if getattr(cs_inner, "enabled", None) is not None else None
            except (AttributeError, TypeError, CAPNP_EXC):
                enabled = None

            # `longActive` ligger i carControl i moderne schemas;
            # eldre Tinkla har den på controlsState eller mangler den helt.
            long_active: bool | None = None
            try:
                la = getattr(cs_inner, "longActive", None)
                if la is not None:
                    long_active = bool(la)
            except (AttributeError, TypeError, CAPNP_EXC):
                long_active = None

            tick = PedalTick(
                ts=ts,
                accel_request=_extract_accel_request(last_cc_actuators),
                v_ego=last_cs_v_ego,
                a_ego=last_cs_a_ego,
                gas_pressed=last_cs_gas_pressed,
                brake_pressed=last_cs_brake_pressed,
                recorded_pedal_di=pending_pedal_di,
                long_active=long_active,
                enabled=enabled,
                pcm_acc_state=last_cs_pcm_acc_state,
            )
            # Tøm pending_pedal_di slik at neste tick uten TX får None.
            pending_pedal_di = None

            yield tick
