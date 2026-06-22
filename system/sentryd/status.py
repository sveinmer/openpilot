"""Rene funksjoner for sentry-status og kommando-parsing (ingen I/O, ingen openpilot-imports)."""

VALID_MODES = ("off", "sensor", "camera", "continuous")


def build_status(dongle_id: str, voltage_mv: int, mode: str, enabled: bool,
                 offroad: bool, camerad_alive: bool) -> dict:
    """Bygg status-payload som POSTes til HA-webhook."""
    return {
        "dongle_id": dongle_id,
        "voltage_v": round(voltage_mv / 1000.0, 2),
        "mode": mode,
        "enabled": enabled,
        "offroad": offroad,
        "camerad_alive": camerad_alive,
    }


def parse_command(resp) -> tuple[bool, str]:
    """Valider HA-poll-respons. Returnerer (enabled, mode) eller kaster ValueError."""
    if not isinstance(resp, dict):
        raise ValueError(f"command not a dict: {type(resp)}")
    enabled = bool(resp.get("enabled", False))
    mode = resp.get("mode", "off")
    if mode not in VALID_MODES:
        raise ValueError(f"invalid mode: {mode!r}")
    return enabled, mode
