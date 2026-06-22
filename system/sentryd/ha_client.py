"""HTTP-bro til Home Assistant via Nabu Casa. Feiler aldri ut — returnerer
bool/None slik at sentryd-løkka aldri krasjer på nettverksfeil.

Bruker stdlib logging (ikke cloudlog) for å holde modulen importerbar uten
openpilot-build; dette er en bevisst beslutning for en liten daemon."""
import logging

import requests

LOG = logging.getLogger("sentryd")


class HAClient:
    def __init__(self, webhook_url: str, poll_url: str, token: str, timeout: float = 10.0):
        self.webhook_url = webhook_url
        self.poll_url = poll_url
        self.token = token
        self.timeout = timeout

    def report(self, status: dict) -> bool:
        """POST status til HA-webhook. True ved 2xx, ellers False (kaster aldri)."""
        try:
            r = requests.post(self.webhook_url, json=status, timeout=self.timeout)
            return 200 <= r.status_code < 300
        except Exception:
            LOG.exception("sentryd: HA report failed")
            return False

    def poll(self) -> dict | None:
        """GET kommando fra HA. Returnerer {'enabled':..,'mode':..} eller None.

        HA /api/states/<entity> svarer {"state":..,"attributes":{..}}; vi leser
        enabled/mode fra attributes."""
        try:
            headers = {"Authorization": f"Bearer {self.token}"}
            r = requests.get(self.poll_url, headers=headers, timeout=self.timeout)
            if not (200 <= r.status_code < 300):
                return None
            attrs = r.json().get("attributes", {})
            return {"enabled": attrs.get("enabled", False),
                    "mode": attrs.get("mode", "off")}
        except Exception:
            LOG.exception("sentryd: HA poll failed")
            return None
