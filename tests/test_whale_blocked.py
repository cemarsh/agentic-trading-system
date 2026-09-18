"""CapitolTrades' 429 is Vercel's bot checkpoint, not a rate limit.

Every whale fetch since at least 2026-06-02 failed: first on ~60s polling, then every
30 minutes after the August cooldown. The page answers any HTTP client with a
JavaScript challenge (x-vercel-mitigated: challenge), so retrying on the poll interval
only produced errors. The fetch now raises SourceBlocked, and the loop marks the source
blocked, alerts once, and retries it once per day.
"""

import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

sys.path.insert(0, str(Path(__file__).parent.parent))

from execution import market_loop as ml
from execution.guards import Cooldown
from execution.whale_watch import SourceBlocked, WhaleWatcher

CHECKPOINT = ("<!DOCTYPE html><html><head><title>Vercel Security Checkpoint</title></head>"
              "<body>Please enable JavaScript</body></html>")


def _response(status, text="", headers=None):
    resp = requests.Response()
    resp.status_code = status
    resp._content = text.encode()
    resp.headers.update(headers or {})
    resp.url = "https://www.capitoltrades.com/trades"
    return resp


def _watcher():
    cfg = MagicMock()
    cfg.whale_watch.politician_names = ["Rich McCormick"]
    cfg.whale_watch.whale_trade_min_value = 15000
    return WhaleWatcher(settings=cfg)


class _Due:
    """Stand-in for the loop's feed gate: the normal poll interval has elapsed."""
    @staticmethod
    def ready(source):
        return True


class _NotDue:
    @staticmethod
    def ready(source):
        return False


# --- detection in the fetch ---------------------------------------------------

def test_vercel_challenge_raises_source_blocked():
    resp = _response(429, CHECKPOINT, {"server": "Vercel", "x-vercel-mitigated": "challenge"})
    with patch("requests.get", return_value=resp):
        with pytest.raises(SourceBlocked, match="bot checkpoint"):
            _watcher().fetch_recent_trades()


def test_checkpoint_page_without_the_header_is_still_blocked():
    with patch("requests.get", return_value=_response(429, CHECKPOINT, {"server": "Vercel"})):
        with pytest.raises(SourceBlocked):
            _watcher().fetch_recent_trades()


def test_vercel_firewall_403_is_blocked():
    with patch("requests.get", return_value=_response(403, "Forbidden", {"server": "Vercel"})):
        with pytest.raises(SourceBlocked, match="403"):
            _watcher().fetch_recent_trades()


def test_a_plain_429_is_still_an_ordinary_http_error():
    resp = _response(429, "Too Many Requests", {"retry-after": "60"})
    with patch("requests.get", return_value=resp):
        with pytest.raises(requests.HTTPError):
            _watcher().fetch_recent_trades()


def test_a_normal_page_still_parses():
    row = ("<tr><td>Rich McCormickRepublicanHouseGA</td><td>Abbott LaboratoriesABT:US</td>"
           "<td></td><td></td><td></td><td></td><td>buy</td><td>15K–50K</td></tr>")
    html = f"<table><tbody>{row}</tbody></table>"
    with patch("requests.get", return_value=_response(200, html)):
        trades = _watcher().fetch_recent_trades()
    assert [(t.ticker, t.trade_type, t.trade_value) for t in trades] == [("ABT", "buy", 32500.0)]


# --- backoff in the loop --------------------------------------------------------

def test_blocked_source_alerts_once_and_stops_polling():
    state = {}
    blocked_cd = Cooldown(24 * 3600, store=state.setdefault("_feed_blocked_retries", {}))
    whale = MagicMock()
    whale.get_actionable_trades.side_effect = SourceBlocked("checkpoint")
    notifier = MagicMock()

    with patch.object(ml, "save_state"):
        for _ in range(6):  # six polls inside the retry window
            assert ml._poll_whale(state, whale, _Due, Cooldown(3600), blocked_cd, notifier=notifier) == []

    assert state["whale_source_blocked"] is True
    assert whale.get_actionable_trades.call_count == 1
    notifier.send.assert_called_once()


def test_still_blocked_on_the_daily_retry_does_not_alert_again():
    state = {"whale_source_blocked": True}
    store = state.setdefault("_feed_blocked_retries", {})
    store["whale"] = time.time() - 25 * 3600  # last verdict was 25h ago
    blocked_cd = Cooldown(24 * 3600, store=store)
    whale = MagicMock()
    whale.get_actionable_trades.side_effect = SourceBlocked("checkpoint")
    notifier = MagicMock()

    with patch.object(ml, "save_state"):
        ml._poll_whale(state, whale, _Due, Cooldown(3600), blocked_cd, notifier=notifier)
        ml._poll_whale(state, whale, _Due, Cooldown(3600), blocked_cd, notifier=notifier)

    assert whale.get_actionable_trades.call_count == 1  # retried once, then back off
    notifier.send.assert_not_called()


def test_a_successful_retry_clears_the_block():
    state = {"whale_source_blocked": True}
    store = state.setdefault("_feed_blocked_retries", {})
    store["whale"] = time.time() - 25 * 3600
    blocked_cd = Cooldown(24 * 3600, store=store)
    trade = MagicMock()
    whale = MagicMock()
    whale.get_actionable_trades.return_value = [trade]

    with patch.object(ml, "save_state"):
        assert ml._poll_whale(state, whale, _Due, Cooldown(3600), blocked_cd) == [trade]

    assert "whale_source_blocked" not in state


def test_other_fetch_errors_keep_the_normal_cadence():
    state = {}
    whale = MagicMock()
    whale.get_actionable_trades.side_effect = requests.ConnectionError("Connection reset by peer")
    blocked_cd = Cooldown(24 * 3600, store={})

    with patch.object(ml, "save_state"):
        ml._poll_whale(state, whale, _Due, Cooldown(3600), blocked_cd)
        ml._poll_whale(state, whale, _Due, Cooldown(3600), blocked_cd)

    assert whale.get_actionable_trades.call_count == 2
    assert "whale_source_blocked" not in state


def test_the_normal_poll_interval_still_gates_the_fetch():
    whale = MagicMock()
    assert ml._poll_whale({}, whale, _NotDue, Cooldown(3600), Cooldown(86400, store={})) == []
    whale.get_actionable_trades.assert_not_called()
