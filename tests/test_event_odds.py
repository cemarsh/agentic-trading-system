"""Macro-event overlay (2026-09-29): Kalshi odds → shadow/enforce gate on new CSPs.

The property that matters: a CSP whose expiry spans a CONTESTED scheduled event is
refused in enforce mode, merely recorded in shadow mode, and the overlay never blocks
anything when it has no fresh data (it fails open — it is an overlay, not a core input).
"""

import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

import execution.wheel_strategy as wheel_mod
from execution.event_odds import (
    WatchSpec,
    big_moves,
    market_prob,
    summarize_event,
    verdict,
)
from execution.wheel_strategy import WheelStrategy

NOW = datetime(2026, 10, 14, 15, 0, tzinfo=timezone.utc)


def _mkt(label, bid, ask, last=None, prev=None, status="active"):
    return {"ticker": f"T-{label}", "yes_sub_title": label, "status": status,
            "yes_bid_dollars": f"{bid:.4f}", "yes_ask_dollars": f"{ask:.4f}",
            "last_price_dollars": f"{(last if last is not None else ask):.4f}",
            "previous_price_dollars": None if prev is None else f"{prev:.4f}",
            "close_time": "2026-10-28T17:59:00Z"}


def _fomc(hold=0.55, hike=0.45):
    return {"event_ticker": "KXFEDDECISION-26OCT", "title": "Fed decision in Oct 2026?",
            "strike_date": "2026-10-28T18:00:00Z",
            "markets": [_mkt("Fed maintains rate", hold - 0.005, hold + 0.005, prev=0.30),
                        _mkt("Hike 25bps", hike - 0.005, hike + 0.005, prev=0.70),
                        _mkt("Cut 25bps", 0.0, 0.01)]}


def _snap(events, fetched=NOW):
    return {"fetched_at": fetched.isoformat(), "events": events, "errors": {}}


FOMC_SPEC = WatchSpec("FOMC decision", "KXFEDDECISION", "window", 0.30)
RECESSION_SPEC = WatchSpec("US recession", "KXRECSSNBER", "level", 0.40)


# ------------------------------------------------------------- pricing

def test_market_prob_uses_mid_when_tight():
    assert market_prob(_mkt("x", 0.54, 0.55)) == 0.545


def test_market_prob_falls_back_to_last_when_book_is_wide():
    # A 0.01/0.99 book has a "mid" of 0.50 that nobody would trade at.
    assert market_prob(_mkt("x", 0.01, 0.99, last=0.12)) == 0.12


def test_window_event_normalises_and_measures_surprise():
    s = summarize_event(_fomc(0.55, 0.45), FOMC_SPEC)
    assert s["outcomes"][0]["label"] == "Fed maintains rate"
    # 0.55 / (0.55 + 0.45 + 0.005) → modal ≈ 0.547 → surprise ≈ 0.45
    assert 0.44 < s["risk"] < 0.46


def test_level_event_risk_is_yes_probability():
    ev = {"event_ticker": "KXRECSSNBER-27", "markets": [_mkt("Yes", 0.23, 0.24)]}
    assert summarize_event(ev, RECESSION_SPEC)["risk"] == 0.235


# ------------------------------------------------------------- verdict

def test_contested_event_inside_expiry_window_blocks():
    snap = _snap([summarize_event(_fomc(), FOMC_SPEC)])
    ok, reason, triggers = verdict(snap, date(2026, 10, 30), now=NOW)
    assert not ok and "FOMC decision" in reason and len(triggers) == 1


def test_event_after_expiry_does_not_block():
    snap = _snap([summarize_event(_fomc(), FOMC_SPEC)])
    ok, _, _ = verdict(snap, date(2026, 10, 23), now=NOW)
    assert ok


def test_event_on_expiry_day_counts():
    # FOMC 18:00 UTC on expiry day is before the 16:00 ET close.
    ev = _fomc()
    ev["strike_date"] = "2026-10-30T18:00:00Z"
    ok, _, _ = verdict(_snap([summarize_event(ev, FOMC_SPEC)]), date(2026, 10, 30), now=NOW)
    assert not ok


def test_well_priced_event_does_not_block():
    snap = _snap([summarize_event(_fomc(0.92, 0.07), FOMC_SPEC)])
    ok, _, _ = verdict(snap, date(2026, 10, 30), now=NOW)
    assert ok


def test_level_condition_blocks_regardless_of_expiry():
    ev = {"event_ticker": "KXRECSSNBER-27", "markets": [_mkt("Yes", 0.45, 0.46)]}
    ok, reason, _ = verdict(_snap([summarize_event(ev, RECESSION_SPEC)]),
                            date(2026, 10, 16), now=NOW)
    assert not ok and "recession" in reason


def test_stale_or_missing_snapshot_fails_open_with_reason():
    stale = _snap([summarize_event(_fomc(), FOMC_SPEC)], fetched=NOW - timedelta(hours=7))
    ok, reason, _ = verdict(stale, date(2026, 10, 30), max_age_hours=6, now=NOW)
    assert ok and "old" in reason
    ok, reason, _ = verdict(None, date(2026, 10, 30), now=NOW)
    assert ok and "no event-odds" in reason


def test_big_moves_reports_repricing():
    snap = _snap([summarize_event(_fomc(), FOMC_SPEC)])
    moves = {m["outcome"]: m for m in big_moves(snap, 0.10)}
    assert moves["Fed maintains rate"]["from"] == 0.30
    assert "Cut 25bps" not in moves


# ------------------------------------------------------------- wheel wiring

def _wheel(monkeypatch):
    cfg = MagicMock()
    cfg.wheel.tickers = ["CCJ"]
    cfg.wheel.expiration_weeks = 2
    cfg.wheel.use_signal_candidates = False   # MagicMock is truthy — see test_wheel_sizing
    cfg.wheel.prioritize_by_iv_rank = False
    cfg.wheel.write_covered_calls = False
    cfg.wheel.max_book_loss_pct = 0.0
    cfg.wheel.skip_log_cooldown_minutes = 240
    cfg.risk.quarantined_tickers = []
    cfg.protection.no_auto_manage = []
    ws = WheelStrategy(settings=cfg, alpaca_client=MagicMock())
    monkeypatch.setattr(ws, "target_expiry", lambda: "2026-10-30")
    monkeypatch.setattr(ws, "open_csp", lambda t, ivr=None: {"id": "o-1"})
    journal = []
    monkeypatch.setattr(wheel_mod, "log_insight", lambda **kw: journal.append(kw))
    return ws, journal


def _fresh_contested():
    return _snap([summarize_event(_fomc(), FOMC_SPEC)])


def _pin_now(monkeypatch):
    # verdict() compares the event date with wall-clock "now"; pin it to NOW so this
    # test doesn't silently change meaning once the real Oct 28 date has passed.
    import execution.event_odds as eo
    real = eo.verdict
    monkeypatch.setattr(eo, "verdict", lambda s, e, max_age_hours=6.0, now=None:
                        real(s, e, max_age_hours=max_age_hours, now=NOW))


def test_no_snapshot_leaves_wheel_unchanged(monkeypatch):
    ws, journal = _wheel(monkeypatch)
    assert ws.run_cycle() == 1
    assert not any(j.get("source") == "event_odds" for j in journal)


def test_enforce_mode_blocks_new_csps(monkeypatch):
    ws, journal = _wheel(monkeypatch)
    _pin_now(monkeypatch)
    ws.set_event_odds(_fresh_contested(), mode="enforce")
    assert ws.run_cycle() == 0
    assert any("[EVENT] no new CSPs" in j["insight"] for j in journal)


def test_shadow_mode_trades_and_records_what_it_would_block(monkeypatch):
    ws, journal = _wheel(monkeypatch)
    _pin_now(monkeypatch)
    ws.set_event_odds(_fresh_contested(), mode="shadow")
    assert ws.run_cycle() == 1
    shadow = [j for j in journal if j.get("source") == "event_odds"]
    assert shadow and shadow[0]["metadata"]["tickers"] == ["CCJ"]
    assert shadow[0]["metadata"]["shadow"] is True
