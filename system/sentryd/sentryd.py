#!/usr/bin/env python3
"""sentryd — c3-agent: rapporter status til HA, anvend modus-kommandoer.

Arming/tier-logikken bor i HA; sentryd er utfører + rapportør. Kamera/encoder-
styring (Plan 3) settes via SentryMode-param som denne løkka skriver.

cereal.messaging + Params importeres lazy i main() slik at run_once kan
enhetstestes uten kompilerte openpilot-moduler."""
import logging
import time

from openpilot.system.sentryd.status import build_status, parse_command
from openpilot.system.sentryd.ha_client import HAClient

LOG = logging.getLogger("sentryd")
REPORT_INTERVAL_S = 30.0


def _as_str(v) -> str:
    return v.decode() if isinstance(v, (bytes, bytearray)) else (v or "")


def run_once(params, sm, client, camerad_alive: bool) -> None:
    """Én iterasjon: rapporter status, poll kommando, anvend hvis ikke override."""
    dongle = _as_str(params.get("DongleId"))
    voltage_mv = sm["peripheralState"].voltage
    offroad = not params.get_bool("IsOnroad")
    mode = _as_str(params.get("SentryMode")) or "off"
    enabled = params.get_bool("SentryEnabled")

    status = build_status(dongle, voltage_mv, mode, enabled, offroad, camerad_alive)
    client.report(status)

    cmd = client.poll()
    if cmd is not None and not params.get_bool("SentryManualOverride"):
        try:
            new_enabled, new_mode = parse_command(cmd)
            params.put_bool("SentryEnabled", new_enabled)
            params.put("SentryMode", new_mode)
        except ValueError:
            LOG.exception("sentryd: bad HA command %r", cmd)


def _camerad_alive(sm) -> bool:
    return bool(sm.alive.get("roadCameraState", False))


def main():
    import cereal.messaging as messaging
    from openpilot.common.params import Params

    params = Params()
    client = HAClient(
        webhook_url=_as_str(params.get("SentryHAWebhookUrl")),
        poll_url=_as_str(params.get("SentryHAPollUrl")),
        token=_as_str(params.get("SentryHAToken")),
    )
    sm = messaging.SubMaster(["peripheralState", "roadCameraState"])
    while True:
        sm.update(1000)
        run_once(params, sm, client, camerad_alive=_camerad_alive(sm))
        time.sleep(REPORT_INTERVAL_S)


if __name__ == "__main__":
    main()
