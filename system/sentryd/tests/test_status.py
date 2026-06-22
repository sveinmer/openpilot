import pytest
from openpilot.system.sentryd.status import build_status, parse_command, VALID_MODES


def test_build_status_shapes_payload():
    s = build_status(dongle_id="abc123", voltage_mv=12340, mode="sensor",
                     enabled=True, offroad=True, camerad_alive=False)
    assert s == {
        "dongle_id": "abc123",
        "voltage_v": 12.34,
        "mode": "sensor",
        "enabled": True,
        "offroad": True,
        "camerad_alive": False,
    }


def test_parse_command_valid():
    assert parse_command({"enabled": True, "mode": "camera"}) == (True, "camera")


def test_parse_command_defaults_to_off_disabled():
    assert parse_command({}) == (False, "off")


def test_parse_command_rejects_bad_mode():
    with pytest.raises(ValueError):
        parse_command({"enabled": True, "mode": "bogus"})


def test_parse_command_rejects_non_dict():
    with pytest.raises(ValueError):
        parse_command(["not", "a", "dict"])


def test_valid_modes():
    assert VALID_MODES == ("off", "sensor", "camera", "continuous")
