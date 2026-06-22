from unittest import mock
from openpilot.system.sentryd.ha_client import HAClient


def make_client():
    return HAClient(webhook_url="https://hooks.nabu.casa/abc",
                    poll_url="https://x.ui.nabu.casa/api/states/sensor.sentry_cmd",
                    token="tok", timeout=5)


def test_report_posts_status_and_returns_true():
    c = make_client()
    with mock.patch("openpilot.system.sentryd.ha_client.requests.post") as post:
        post.return_value = mock.Mock(status_code=200)
        ok = c.report({"voltage_v": 12.3})
    assert ok is True
    post.assert_called_once()
    assert post.call_args.kwargs["json"] == {"voltage_v": 12.3}
    assert post.call_args.kwargs["timeout"] == 5


def test_report_returns_false_on_exception():
    c = make_client()
    with mock.patch("openpilot.system.sentryd.ha_client.requests.post",
                    side_effect=Exception("network down")):
        assert c.report({"voltage_v": 12.3}) is False


def test_poll_parses_ha_state_attributes():
    c = make_client()
    body = {"state": "on", "attributes": {"enabled": True, "mode": "camera"}}
    with mock.patch("openpilot.system.sentryd.ha_client.requests.get") as get:
        get.return_value = mock.Mock(status_code=200, json=mock.Mock(return_value=body))
        cmd = c.poll()
    assert cmd == {"enabled": True, "mode": "camera"}
    assert get.call_args.kwargs["headers"]["Authorization"] == "Bearer tok"


def test_poll_returns_none_on_exception():
    c = make_client()
    with mock.patch("openpilot.system.sentryd.ha_client.requests.get",
                    side_effect=Exception("timeout")):
        assert c.poll() is None


def test_poll_returns_none_on_bad_status():
    c = make_client()
    with mock.patch("openpilot.system.sentryd.ha_client.requests.get") as get:
        get.return_value = mock.Mock(status_code=401, json=mock.Mock(return_value={}))
        assert c.poll() is None
