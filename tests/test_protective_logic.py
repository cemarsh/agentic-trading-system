"""Tests for ProtectiveLogic — trailing stops, gap tighten, ladder."""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from execution.protective_logic import ProtectiveLogic


def _mock_settings(trailing=7.0, gap=3.0, ladder_drop=5.0, ladder_shares=10):
    cfg = MagicMock()
    cfg.protection.trailing_stop_pct = trailing
    cfg.protection.gap_tighten_pct = gap
    cfg.protection.ladder_drop_pct = ladder_drop
    cfg.protection.ladder_buy_shares = ladder_shares
    return cfg


def _make_position(ticker="AAPL", entry=100.0, qty=100):
    return {
        "symbol": ticker,
        "qty": str(qty),
        "avg_entry_price": str(entry),
        "current_price": str(entry),
        "unrealized_pl": "0.0",
    }


def test_stop_price_set_on_sync():
    pl = ProtectiveLogic(settings=_mock_settings())
    pl.sync_positions([_make_position("AAPL", 100.0)])
    pos = pl._positions["AAPL"]
    assert abs(pos.stop_price - 93.0) < 0.01  # 100 * (1 - 0.07)


def test_stop_not_triggered_above_stop():
    pl = ProtectiveLogic(settings=_mock_settings())
    pl.sync_positions([_make_position("AAPL", 100.0)])
    triggered = pl.check_stops({"AAPL": 95.0})
    assert "AAPL" not in triggered


def test_stop_triggered_below_stop():
    pl = ProtectiveLogic(settings=_mock_settings())
    pl.sync_positions([_make_position("AAPL", 100.0)])
    triggered = pl.check_stops({"AAPL": 92.0})
    assert "AAPL" in triggered


def test_high_water_mark_ratchets_stop():
    pl = ProtectiveLogic(settings=_mock_settings())
    pl.sync_positions([_make_position("AAPL", 100.0)])

    # Price rises to 120
    pl.sync_positions([{
        "symbol": "AAPL",
        "qty": "100",
        "avg_entry_price": "100.0",
        "current_price": "120.0",
        "unrealized_pl": "2000.0",
    }])
    pos = pl._positions["AAPL"]
    assert pos.high_water_mark == 120.0
    assert abs(pos.stop_price - 111.6) < 0.1  # 120 * 0.93


def test_gap_tighten():
    pl = ProtectiveLogic(settings=_mock_settings(trailing=7.0, gap=3.0))
    pl.sync_positions([_make_position("AAPL", 100.0)])
    pl.apply_gap_tighten(["AAPL"])
    pos = pl._positions["AAPL"]
    # stop = 100 * (1 - 0.07 - 0.03) = 90.0
    assert abs(pos.stop_price - 90.0) < 0.01


def test_ladder_triggers_at_threshold():
    pl = ProtectiveLogic(settings=_mock_settings(ladder_drop=5.0))
    pl.sync_positions([_make_position("AAPL", 100.0)])
    assert pl.check_ladder("AAPL", 94.0)   # 6% drop > 5% threshold
    assert not pl.check_ladder("AAPL", 96.0)  # 4% drop < 5% threshold
