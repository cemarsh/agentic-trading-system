"""Tests for execution/performance.py — the deterministic report metrics."""

import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from execution.performance import (
    equity_curve,
    capital_snapshot,
    build_needle_section,
    period_bounds_month,
    period_bounds_quarter,
    quarter_label,
    _alpaca_period_for,
)


class FakeAlpaca:
    """Minimal stand-in exposing only what performance.py touches."""

    def __init__(self, history=None, account=None, positions=None, raise_on=None):
        self._history = history or {}
        self._account = account or {}
        self._positions = positions or []
        self._raise_on = raise_on or set()

    def get_portfolio_history(self, period="3M", timeframe="1D"):
        if "history" in self._raise_on:
            raise RuntimeError("boom")
        return self._history

    def get_account(self):
        if "account" in self._raise_on:
            raise RuntimeError("boom")
        return self._account

    def get_positions(self):
        return self._positions


def _ts(y, m, d):
    return int(datetime(y, m, d, tzinfo=timezone.utc).timestamp())


# ---------------------------------------------------------------------------
# Period helpers
# ---------------------------------------------------------------------------

def test_period_bounds_month_handles_december():
    first, last = period_bounds_month(date(2026, 12, 15))
    assert first == date(2026, 12, 1)
    assert last == date(2026, 12, 31)


def test_period_bounds_quarter_q3_and_q4_rollover():
    assert period_bounds_quarter(date(2026, 8, 21)) == (date(2026, 7, 1), date(2026, 9, 30))
    # Q4 must roll the year over when computing the following quarter's start.
    assert period_bounds_quarter(date(2026, 11, 2)) == (date(2026, 10, 1), date(2026, 12, 31))


def test_quarter_label():
    assert quarter_label(date(2026, 8, 21)) == "2026-Q3"
    assert quarter_label(date(2026, 1, 1)) == "2026-Q1"


def test_alpaca_period_ladder_picks_smallest_covering_span():
    assert _alpaca_period_for(20) == "1M"
    assert _alpaca_period_for(92) == "3M"
    assert _alpaca_period_for(180) == "6M"
    assert _alpaca_period_for(370) == "1A"
    assert _alpaca_period_for(400) == "2A"


# ---------------------------------------------------------------------------
# Equity curve
# ---------------------------------------------------------------------------

def test_equity_curve_computes_change_and_drawdown():
    hist = {
        "timestamp": [_ts(2026, 6, 1), _ts(2026, 6, 2), _ts(2026, 6, 3), _ts(2026, 6, 4)],
        "equity": [100000.0, 110000.0, 88000.0, 99000.0],
    }
    out = equity_curve(FakeAlpaca(history=hist), date(2026, 6, 1), date(2026, 6, 30))
    assert out["points"] == 4
    assert out["start_equity"] == 100000.0
    assert out["end_equity"] == 99000.0
    assert out["change"] == -1000.0
    assert round(out["change_pct"], 2) == -1.0
    assert out["peak"] == 110000.0
    assert out["trough"] == 88000.0
    # Deepest decline is 110k -> 88k = 20%, not 100k -> 88k = 12%.
    assert round(out["max_drawdown_pct"], 2) == 20.0


def test_equity_curve_filters_to_requested_window():
    hist = {
        "timestamp": [_ts(2026, 5, 1), _ts(2026, 6, 10), _ts(2026, 7, 20)],
        "equity": [50000.0, 60000.0, 70000.0],
    }
    out = equity_curve(FakeAlpaca(history=hist), date(2026, 6, 1), date(2026, 6, 30))
    assert out["points"] == 1
    assert out["start_equity"] == 60000.0


def test_equity_curve_skips_none_bars():
    """Alpaca returns None-valued bars when the market was closed, not missing keys."""
    hist = {
        "timestamp": [_ts(2026, 6, 1), _ts(2026, 6, 2), _ts(2026, 6, 3)],
        "equity": [100000.0, None, 90000.0],
    }
    out = equity_curve(FakeAlpaca(history=hist), date(2026, 6, 1), date(2026, 6, 30))
    assert out["points"] == 2
    assert out["end_equity"] == 90000.0


def test_equity_curve_degrades_when_broker_unreachable():
    out = equity_curve(FakeAlpaca(raise_on={"history"}), date(2026, 6, 1), date(2026, 6, 30))
    assert out["points"] == 0
    assert out["change"] == 0.0


def test_equity_curve_handles_no_client():
    out = equity_curve(None, date(2026, 6, 1), date(2026, 6, 30))
    assert out["points"] == 0


# ---------------------------------------------------------------------------
# Capital snapshot
# ---------------------------------------------------------------------------

def test_capital_snapshot_counts_short_put_collateral():
    """A short put has no market value but ties up strike x 100 x qty in collateral."""
    positions = [
        {"symbol": "FJET", "qty": "4570", "market_value": "17823", "unrealized_pl": "-8236"},
        {"symbol": "KTOS260904P00052000", "qty": "-1", "market_value": "-130",
         "unrealized_pl": "-65"},
    ]
    out = capital_snapshot(FakeAlpaca(
        account={"equity": "83907.10", "cash": "66924.10"}, positions=positions
    ))
    assert out["available"] is True
    assert out["equity_positions"] == 1
    assert out["option_positions"] == 1
    assert out["long_value"] == 17823.0
    assert out["short_put_collateral"] == 5200.0  # 52.00 x 100 x 1
    assert out["deployed"] == 17823.0 + 5200.0
    assert round(out["deployed_pct"], 1) == round(23023.0 / 83907.10 * 100, 1)
    assert out["unrealized_pl"] == -8301.0


def test_capital_snapshot_ignores_long_puts_for_collateral():
    positions = [
        {"symbol": "SPY260904P00500000", "qty": "1", "market_value": "300",
         "unrealized_pl": "0"},
    ]
    out = capital_snapshot(FakeAlpaca(account={"equity": "10000", "cash": "9700"},
                                      positions=positions))
    assert out["short_put_collateral"] == 0.0


def test_capital_snapshot_degrades_when_account_unreachable():
    out = capital_snapshot(FakeAlpaca(raise_on={"account"}))
    assert out["available"] is False


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def _metrics(equity=None, trades=None, capital=None):
    return {
        "start": date(2026, 6, 1), "end": date(2026, 6, 30),
        "equity": equity or {"points": 0},
        "trades": trades or {"total_trades": 0, "available": False},
        "capital": capital or {"available": False},
    }


def test_needle_section_renders_headline_numbers():
    metrics = _metrics(
        equity={
            "points": 4, "start_equity": 100000.0, "end_equity": 84000.0,
            "change": -16000.0, "change_pct": -16.0, "peak": 100100.0,
            "trough": 83300.0, "max_drawdown_pct": 16.78,
            "start_date": "2026-06-01", "end_date": "2026-06-30", "series": [],
        },
        trades={
            "total_trades": 10, "wins": 3, "losses": 7, "win_rate": 30.0,
            "total_pnl": -2000.0, "gross_win": 500.0, "gross_loss": 2500.0,
            "profit_factor": 0.2, "avg_win": 166.67, "avg_loss": -357.14,
            "expectancy": -200.0, "available": True,
            "by_ticker": {"KTOS": {"trades": 5, "pnl": -1500.0, "wins": 1},
                          "MP": {"trades": 5, "pnl": -500.0, "wins": 2}},
            "by_strategy": {},
        },
    )
    out = build_needle_section(metrics, "June 2026")
    assert "## Needle Movement — June 2026" in out
    assert "-16,000.00" in out and "-16.00%" in out
    assert "16.78%" in out
    assert "| Profit factor | 0.20 |" in out
    assert "KTOS" in out


def test_needle_section_reports_undefined_profit_factor():
    metrics = _metrics(trades={
        "total_trades": 2, "wins": 2, "losses": 0, "win_rate": 100.0,
        "total_pnl": 300.0, "gross_win": 300.0, "gross_loss": 0.0,
        "profit_factor": 0.0, "avg_win": 150.0, "avg_loss": 0.0,
        "expectancy": 150.0, "available": True, "by_ticker": {}, "by_strategy": {},
    })
    out = build_needle_section(metrics, "June 2026")
    # No losses means the ratio is undefined, and must not render as 0.00.
    assert "n/a (no losing trades)" in out


def test_needle_section_distinguishes_no_trades_from_no_ledger():
    with_ledger = build_needle_section(
        _metrics(trades={"total_trades": 0, "available": True}), "June 2026")
    assert "No closed trades logged" in with_ledger

    without_ledger = build_needle_section(
        _metrics(trades={"total_trades": 0, "available": False}), "June 2026")
    assert "Trade ledger unavailable" in without_ledger


def test_needle_section_survives_all_sources_down():
    out = build_needle_section(_metrics(), "June 2026")
    assert "Equity curve unavailable" in out
    assert out.startswith("## Needle Movement")
