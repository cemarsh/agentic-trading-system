"""Halt classification and startup recovery.

Regression cover for 2026-09-11: Alpaca's paper API returned 500 on /v2/clock for a
few minutes. A 5xx counted against api_retry_limit (3), so the loop halted in ~90s.
On restart the recovery probe exited on the same 500, and after 5 fast restarts
systemd's StartLimitBurst stopped the unit. Nothing retried for three days.
"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

sys.path.insert(0, str(Path(__file__).parent.parent))

from execution import market_loop as ml


def _http_error(status, body=None):
    resp = requests.Response()
    resp.status_code = status
    resp._content = json.dumps(body or {}).encode()
    resp.url = "https://paper-api.alpaca.markets/v2/clock"
    return requests.HTTPError(f"{status} Error for url: {resp.url}", response=resp)


def _halted(reason="api"):
    return {"halted": True, "halt_reason": reason, "api_failures": 3, "network_failures": 0}


# --- classification ---------------------------------------------------------

@pytest.mark.parametrize("status", [500, 502, 503, 504])
def test_broker_5xx_is_transient(status):
    err = _http_error(status)
    assert ml._is_server_error(err)
    assert ml._is_transient_error(err)
    assert not ml._is_auth_error(err)
    assert not ml._is_order_rejection(err)


def test_5xx_message_without_a_response_is_transient():
    err = requests.HTTPError(
        "500 Server Error: Internal Server Error for url: https://paper-api.alpaca.markets/v2/clock"
    )
    assert ml._is_transient_error(err)


def test_connection_reset_is_transient():
    err = requests.ConnectionError(
        "Max retries exceeded with url: /v2/clock (Caused by ProtocolError("
        "'Connection aborted.', ConnectionResetError(104, 'Connection reset by peer')))"
    )
    assert ml._is_transient_error(err)


@pytest.mark.parametrize("status,body", [(401, {}), (403, {}), (404, {}), (422, {"code": 40310000})])
def test_client_4xx_is_not_transient(status, body):
    assert not ml._is_transient_error(_http_error(status, body))


# --- startup recovery ---------------------------------------------------------

@pytest.fixture
def recovery(tmp_path):
    """Patch everything _attempt_halt_recovery touches besides the probe itself."""
    with patch.object(ml, "AlpacaClient") as client_cls, \
         patch.object(ml.time, "sleep") as sleep, \
         patch.object(ml, "save_state"), \
         patch.object(ml, "_send_recovery_slack_alert"), \
         patch.object(ml, "HALT_ALERT_PATH", tmp_path / "halt_pending_alert.json"):
        yield client_cls.return_value.get_clock, sleep


def test_recovery_waits_through_an_outage_instead_of_exiting(recovery):
    get_clock, sleep = recovery
    get_clock.side_effect = [_http_error(500), _http_error(503), {"is_open": False}]
    state = _halted()

    ml._attempt_halt_recovery(state, MagicMock())  # must not raise SystemExit

    assert state["halted"] is False
    assert state["api_failures"] == 0
    assert "halt_reason" not in state
    assert [c.args[0] for c in sleep.call_args_list] == [30, 60]


def test_recovery_backoff_caps_at_five_minutes(recovery):
    get_clock, sleep = recovery
    get_clock.side_effect = [_http_error(500)] * 6 + [{"is_open": True}]
    state = _halted()

    ml._attempt_halt_recovery(state, MagicMock())

    assert [c.args[0] for c in sleep.call_args_list] == [30, 60, 120, 300, 300, 300]
    assert state["halted"] is False


def test_recovery_exits_on_a_non_transient_probe_error(recovery):
    get_clock, sleep = recovery
    get_clock.side_effect = _http_error(404)
    with pytest.raises(SystemExit):
        ml._attempt_halt_recovery(_halted(), MagicMock())
    sleep.assert_not_called()


def test_recovery_exits_when_the_probe_is_unauthorized(recovery):
    get_clock, sleep = recovery
    get_clock.side_effect = _http_error(401)
    with pytest.raises(SystemExit):
        ml._attempt_halt_recovery(_halted(), MagicMock())
    sleep.assert_not_called()


def test_auth_halt_never_probes(recovery):
    get_clock, _ = recovery
    with pytest.raises(SystemExit):
        ml._attempt_halt_recovery(_halted("auth"), MagicMock())
    get_clock.assert_not_called()
