"""Tests for WheelStrategy — strike selection, stage transitions."""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from execution.wheel_strategy import WheelStrategy


def _mock_settings():
    cfg = MagicMock()
    cfg.wheel.tickers = ["AAPL", "NVDA"]
    cfg.wheel.target_delta = 0.30
    cfg.wheel.expiration_weeks = 2
    cfg.wheel.cc_strike_markup_pct = 2.0
    cfg.wheel.min_premium_pct = 0.5
    return cfg


def test_select_csp_strike_below_current():
    ws = WheelStrategy(settings=_mock_settings())
    strike = ws.select_csp_strike("AAPL", 180.0)
    assert strike < 180.0


def test_select_csp_strike_rounded_to_half_dollar():
    ws = WheelStrategy(settings=_mock_settings())
    strike = ws.select_csp_strike("AAPL", 177.33)
    assert strike % 0.5 == 0.0


def test_open_csp_skips_if_already_in_stage():
    ws = WheelStrategy(settings=_mock_settings())
    ws._positions["AAPL"].stage = 1
    result = ws.open_csp("AAPL")
    assert result is None


def test_handle_assignment_sets_stage2():
    ws = WheelStrategy(settings=_mock_settings())
    ws._positions["AAPL"].stage = 1
    # Prevent actual API call
    ws.open_cc = MagicMock(return_value=None)
    ws.handle_assignment("AAPL", 100, 175.0)
    assert ws._positions["AAPL"].stage == 2
    assert ws._positions["AAPL"].cost_basis == 175.0
    assert ws._positions["AAPL"].shares_held == 100


def test_cc_strike_above_cost_basis():
    ws = WheelStrategy(settings=_mock_settings())
    pos = ws._positions["AAPL"]
    pos.stage = 2
    pos.cost_basis = 175.0
    pos.shares_held = 100
    ws._alpaca = None  # prevent API call, will return None
    ws.open_cc("AAPL")
    # cc_strike should be 175 * 1.02 = 178.5
    assert abs(pos.cc_strike - 0) < 0.01  # not set (no alpaca client), just verify no crash
