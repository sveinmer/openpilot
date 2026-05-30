"""Tester for tools.preap_long.rlog_loader.

P3 Fase B: dette er skeleton-tester. Vi laster IKKE faktiske rlogs i denne
fasen — det er Fase C-arbeid. Testene dekker:
  1. PedalTick-dataclass: defaults og field-types.
  2. 0x551 encode→decode roundtrip (Tinkla 0.6.6 formula).
  3. accel_request-ekstraktor: prefererer `accel`, faller tilbake til gas-brake.
  4. load_pedal_tick_stream med ugyldig route (404 / not-found gracefully).
  5. Smoke-test som mock-er _iter_route_msgs slik vi tester pipeline uten nett.
"""
from __future__ import annotations

import math
import struct
import unittest
from dataclasses import fields
from unittest import mock

from openpilot.tools.preap_long import rlog_loader
from openpilot.tools.preap_long.rlog_loader import (
    ADDR_GAS_COMMAND,
    PedalTick,
    TINKLA_PEDAL_D,
    TINKLA_PEDAL_M1,
    decode_pedal_di_from_0x551,
    int_accel_to_pedal_command,
    load_pedal_tick_stream,
)


def _tinkla_pack_0x551(accel_command: float, enable: int = 1, idx: int = 0) -> bytes:
    """Reprodusere Tinkla 0.6.6 sin pakke-logikk for 0x551 (for roundtrip-test).

    Speiler `create_pedal_command_msg` fra Tinkla/selfdrive/car/tesla/teslacan.py
    så testen er uavhengig av om Tinkla-repoet er importerbart.
    """
    m1 = TINKLA_PEDAL_M1
    m2 = 2 * m1  # m2 = 0.101593626 ≈ 2*m1
    d = TINKLA_PEDAL_D
    if enable == 1:
        int_accel = int((accel_command - d) / m1)
        int_accel2 = int((accel_command - d) / m2)
    else:
        int_accel = 0
        int_accel2 = 0
    payload = bytearray(6)
    struct.pack_into(
        "BBBBB",
        payload,
        0,
        (int_accel >> 8) & 0xFF,
        int_accel & 0xFF,
        (int_accel2 >> 8) & 0xFF,
        int_accel2 & 0xFF,
        ((enable << 7) + idx) & 0xFF,
    )
    # checksum er kun for validering — vi setter 0
    return bytes(payload)


class TestPedalTickDataclass(unittest.TestCase):
    """1. PedalTick dataclass defaults None-håndtering."""

    def test_pedaltick_only_ts_required(self):
        tick = PedalTick(ts=1234.5)
        self.assertEqual(tick.ts, 1234.5)
        # Alle andre felter må defaulte til None
        for field in fields(tick):
            if field.name == "ts":
                continue
            self.assertIsNone(
                getattr(tick, field.name),
                f"{field.name} skal default til None",
            )

    def test_pedaltick_accepts_all_fields(self):
        tick = PedalTick(
            ts=1.0,
            accel_request=0.5,
            v_ego=10.0,
            a_ego=0.1,
            gas_pressed=False,
            brake_pressed=False,
            recorded_pedal_di=42,
            long_active=True,
            enabled=True,
            pcm_acc_state=2,
        )
        self.assertEqual(tick.accel_request, 0.5)
        self.assertEqual(tick.recorded_pedal_di, 42)
        self.assertTrue(tick.long_active)


class TestPedalDiEncoding(unittest.TestCase):
    """2. 0x551 encode→decode roundtrip via Tinkla 0.6.6 formula."""

    def test_roundtrip_zero(self):
        payload = _tinkla_pack_0x551(0.0)
        di = decode_pedal_di_from_0x551(payload)
        self.assertIsNotNone(di)
        cmd = int_accel_to_pedal_command(di)
        # accept-tolerance fordi int-konvertering taper presisjon
        self.assertAlmostEqual(cmd, 0.0, delta=TINKLA_PEDAL_M1)

    def test_roundtrip_positive(self):
        for cmd_in in [10.0, 25.0, 100.0, 250.0]:
            payload = _tinkla_pack_0x551(cmd_in)
            di = decode_pedal_di_from_0x551(payload)
            self.assertIsNotNone(di)
            cmd_out = int_accel_to_pedal_command(di)
            self.assertAlmostEqual(
                cmd_out, cmd_in, delta=TINKLA_PEDAL_M1,
                msg=f"roundtrip mismatch for {cmd_in}",
            )

    def test_roundtrip_disabled(self):
        # enable=0 → int_accel=0 → cmd dekoder til d (offset)
        payload = _tinkla_pack_0x551(50.0, enable=0)
        di = decode_pedal_di_from_0x551(payload)
        self.assertEqual(di, 0)
        cmd = int_accel_to_pedal_command(di)
        self.assertAlmostEqual(cmd, TINKLA_PEDAL_D, delta=1e-9)

    def test_decode_short_payload_returns_none(self):
        self.assertIsNone(decode_pedal_di_from_0x551(b""))
        self.assertIsNone(decode_pedal_di_from_0x551(b"\x00\x00"))
        self.assertIsNone(decode_pedal_di_from_0x551(None))

    def test_addr_constant(self):
        self.assertEqual(ADDR_GAS_COMMAND, 0x551)


class TestAccelRequestExtractor(unittest.TestCase):
    """3. _extract_accel_request: prefererer accel, faller tilbake til gas-brake."""

    def test_returns_none_for_none_input(self):
        self.assertIsNone(rlog_loader._extract_accel_request(None))

    def test_prefers_accel_field(self):
        actuators = mock.Mock()
        actuators.accel = 1.5
        actuators.gas = 0.7
        actuators.brake = 0.0
        self.assertAlmostEqual(
            rlog_loader._extract_accel_request(actuators), 1.5,
        )

    def test_fallback_to_gas_minus_brake(self):
        # Bygg objekt der `accel` mangler (getattr returnerer None)
        class FakeActuators:
            gas = 0.4
            brake = 0.1
            # ingen accel-attr
        result = rlog_loader._extract_accel_request(FakeActuators())
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result, 0.3, places=6)


class TestLoadWithInvalidRoute(unittest.TestCase):
    """4. load_pedal_tick_stream håndterer ugyldig route gracefully."""

    def test_invalid_route_raises_runtime_error(self):
        # Mock LogReader til å kaste — vi sjekker at vi får RuntimeError ut,
        # ikke arbitrær underliggende exception.
        fake_logreader_module = mock.MagicMock()
        fake_logreader_module.LogReader.side_effect = ValueError(
            "fake: route not found"
        )

        with mock.patch.dict(
            "sys.modules",
            {"openpilot.tools.lib.logreader": fake_logreader_module},
        ):
            with self.assertRaises(RuntimeError) as ctx:
                list(load_pedal_tick_stream("bogus|2099-01-01--00-00-00"))
            self.assertIn("LogReader-konstruksjon feilet", str(ctx.exception))

    def test_import_failure_raises_runtime_error(self):
        # Simuler at openpilot.tools.lib.logreader ikke kan importeres.
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "openpilot.tools.lib.logreader":
                raise ImportError("fake: no logreader")
            return real_import(name, *args, **kwargs)

        with mock.patch("builtins.__import__", side_effect=fake_import):
            with self.assertRaises(RuntimeError) as ctx:
                list(load_pedal_tick_stream("bogus|2099-01-01--00-00-00"))
            self.assertIn("kunne ikke importere LogReader", str(ctx.exception))


class TestLoadMinimalSegmentsSmoke(unittest.TestCase):
    """5. Smoke-test: mock _iter_route_msgs slik vi tester pipeline uten nett.

    Bygger 4 mock-msgs: carState → carControl → sendcan(0x551) → controlsState
    og verifiserer at vi får én PedalTick med alle synkroniserte felter.
    """

    def test_pipeline_produces_synced_tick(self):
        # Bygg fake msg-objekter med .which() og rette attributter.
        cs_msg = mock.MagicMock()
        cs_msg.which.return_value = "carState"
        cs_msg.carState.vEgo = 12.3
        cs_msg.carState.aEgo = 0.4
        cs_msg.carState.gasPressed = False
        cs_msg.carState.brakePressed = False
        cs_msg.carState.cruiseState = mock.MagicMock(speed=25.0, speedCluster=None)

        cc_msg = mock.MagicMock()
        cc_msg.which.return_value = "carControl"
        cc_msg.carControl.actuators.accel = 1.25
        cc_msg.carControl.actuators.gas = 0.0
        cc_msg.carControl.actuators.brake = 0.0

        # sendcan-msg med 0x551 frame
        accel_test = 50.0
        payload = _tinkla_pack_0x551(accel_test)
        frame = mock.MagicMock()
        frame.address = 0x551
        frame.dat = payload

        sendcan_msg = mock.MagicMock()
        sendcan_msg.which.return_value = "sendcan"
        sendcan_msg.sendcan = [frame]

        controls_msg = mock.MagicMock()
        controls_msg.which.return_value = "controlsState"
        controls_msg.logMonoTime = int(1.5 * 1e9)
        controls_msg.controlsState.enabled = True
        controls_msg.controlsState.longActive = True

        fake_msgs = [cs_msg, cc_msg, sendcan_msg, controls_msg]

        with mock.patch.object(
            rlog_loader, "_iter_route_msgs", return_value=iter(fake_msgs)
        ):
            ticks = list(load_pedal_tick_stream("fake|route"))

        self.assertEqual(len(ticks), 1)
        tick = ticks[0]
        self.assertAlmostEqual(tick.ts, 1.5, places=6)
        self.assertAlmostEqual(tick.accel_request, 1.25)
        self.assertAlmostEqual(tick.v_ego, 12.3)
        self.assertAlmostEqual(tick.a_ego, 0.4)
        self.assertFalse(tick.gas_pressed)
        self.assertFalse(tick.brake_pressed)
        self.assertTrue(tick.enabled)
        self.assertTrue(tick.long_active)
        self.assertIsNotNone(tick.recorded_pedal_di)
        # Roundtrip-sanity
        cmd_out = int_accel_to_pedal_command(tick.recorded_pedal_di)
        self.assertAlmostEqual(cmd_out, accel_test, delta=TINKLA_PEDAL_M1)

    def test_tick_without_sendcan_has_none_pedal_di(self):
        # controlsState uten foregående sendcan → recorded_pedal_di = None
        controls_msg = mock.MagicMock()
        controls_msg.which.return_value = "controlsState"
        controls_msg.logMonoTime = int(2.0 * 1e9)
        controls_msg.controlsState.enabled = False
        controls_msg.controlsState.longActive = False

        with mock.patch.object(
            rlog_loader, "_iter_route_msgs", return_value=iter([controls_msg])
        ):
            ticks = list(load_pedal_tick_stream("fake|route"))
        self.assertEqual(len(ticks), 1)
        self.assertIsNone(ticks[0].recorded_pedal_di)
        self.assertFalse(ticks[0].enabled)


if __name__ == "__main__":
    unittest.main()
