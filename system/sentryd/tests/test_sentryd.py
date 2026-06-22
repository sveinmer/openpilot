from unittest import mock
from openpilot.system.sentryd import sentryd


def make_ctx(voltage_mv=12500, onroad=False, manual_override=False):
    params = mock.Mock()
    params.get_bool.side_effect = lambda k: {
        "IsOnroad": onroad, "SentryManualOverride": manual_override,
        "SentryEnabled": False,
    }.get(k, False)
    params.get.side_effect = lambda k: {"DongleId": b"dongle1", "SentryMode": b"off"}.get(k)
    sm = {"peripheralState": mock.Mock(voltage=voltage_mv)}
    client = mock.Mock()
    return params, sm, client


def test_iteration_reports_status_offroad():
    params, sm, client = make_ctx(voltage_mv=12500, onroad=False)
    client.poll.return_value = None
    sentryd.run_once(params, sm, client, camerad_alive=True)
    status = client.report.call_args.args[0]
    assert status["voltage_v"] == 12.5
    assert status["offroad"] is True
    assert status["camerad_alive"] is True
    assert status["dongle_id"] == "dongle1"


def test_iteration_applies_command_when_not_overridden():
    params, sm, client = make_ctx(manual_override=False)
    client.poll.return_value = {"enabled": True, "mode": "camera"}
    sentryd.run_once(params, sm, client, camerad_alive=False)
    params.put_bool.assert_any_call("SentryEnabled", True)
    params.put.assert_any_call("SentryMode", "camera")


def test_iteration_ignores_command_when_manual_override():
    params, sm, client = make_ctx(manual_override=True)
    client.poll.return_value = {"enabled": True, "mode": "camera"}
    sentryd.run_once(params, sm, client, camerad_alive=False)
    params.put_bool.assert_not_called()
    params.put.assert_not_called()


def test_iteration_ignores_invalid_command():
    params, sm, client = make_ctx(manual_override=False)
    client.poll.return_value = {"enabled": True, "mode": "bogus"}
    sentryd.run_once(params, sm, client, camerad_alive=False)
    params.put_bool.assert_not_called()
