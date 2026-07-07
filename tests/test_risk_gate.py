"""Tests for the pre-trade risk gate — position cap, IPO quarantine, sector cap."""

import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

from execution.risk_gate import RiskGate, _occ_parts


def _mock_settings():
    cfg = MagicMock()
    cfg.risk.max_position_pct = 5.0
    cfg.risk.quarantine_max_position_pct = 1.0
    cfg.risk.quarantined_tickers = ["FJET"]
    cfg.risk.sector_cap_pct = 20.0
    cfg.risk.sector_map = {
        "defense_aerospace": ["RTX", "PLTR", "FJET"],
        "nuclear_uranium": ["CCJ", "CEG", "VST"],
    }
    cfg.protection.no_auto_manage = ["FJET", "OPTX"]
    return cfg


def _gate(positions=None, equity=90_000.0):
    gate = RiskGate(settings=_mock_settings())
    gate.refresh(positions or [], equity)
    return gate


def test_occ_parser():
    assert _occ_parts("CCJ260717P00098000") == ("CCJ", "P", 98.0)
    assert _occ_parts("AAPL") is None


def test_fails_closed_without_refresh():
    gate = RiskGate(settings=_mock_settings())
    ok, reason = gate.check_equity_order("RTX", 1000)
    assert not ok


def test_fails_closed_on_zero_equity():
    gate = _gate(equity=0)
    ok, _ = gate.check_equity_order("RTX", 1000)
    assert not ok


def test_position_cap_blocks_oversize_buy():
    # 5% of $90k = $4,500 cap — the FJET $26k position would be rejected
    gate = _gate()
    ok, reason = gate.check_equity_order("HD", 26_000)
    assert not ok
    assert "position cap" in reason


def test_position_cap_allows_small_buy():
    gate = _gate()
    ok, _ = gate.check_equity_order("HD", 4_000)
    assert ok


def test_existing_exposure_counts_toward_cap():
    positions = [{"symbol": "HD", "market_value": "4000", "qty": "10"}]
    gate = _gate(positions)
    ok, _ = gate.check_equity_order("HD", 1_000)  # 4000 + 1000 > 4500
    assert not ok


def test_quarantined_ticker_gets_1pct_cap():
    gate = _gate()
    ok, reason = gate.check_equity_order("FJET", 2_000)  # 1% of 90k = $900
    assert not ok
    assert "quarantined" in reason
    ok, _ = gate.check_equity_order("FJET", 800)
    assert ok


def test_no_auto_manage_tickers_auto_quarantined():
    gate = _gate()
    ok, reason = gate.check_equity_order("OPTX", 2_000)  # in no_auto_manage, not risk list
    assert not ok
    assert "quarantined" in reason


def test_sector_cap_counts_csp_collateral():
    # Short put CCJ $98 = $9,800 collateral in nuclear_uranium
    positions = [
        {"symbol": "CCJ260717P00098000", "qty": "-1", "market_value": "-250"},
        {"symbol": "CEG", "market_value": "8000", "qty": "30"},
    ]
    gate = _gate(positions)
    # nuclear sector = 9800 + 8000 = 17,800; cap = 18,000; VST buy of 500 tips it
    ok, reason = gate.check_equity_order("VST", 500)
    assert not ok
    assert "sector" in reason


def test_csp_collateral_check_blocks_sector_breach():
    positions = [{"symbol": "CEG", "market_value": "10000", "qty": "40"}]
    gate = _gate(positions)
    ok, reason = gate.check_option_collateral("VST", 9_000)  # 19k > 18k cap
    assert not ok
    ok, _ = gate.check_option_collateral("VST", 7_000)
    assert ok


def test_csp_on_quarantined_ticker_always_blocked():
    gate = _gate()
    ok, reason = gate.check_option_collateral("FJET", 500)
    assert not ok
    assert "quarantined" in reason


def test_unmapped_ticker_has_no_sector_cap():
    gate = _gate()
    ok, _ = gate.check_equity_order("GLD", 4_000)  # unmapped, under position cap
    assert ok


def test_record_fill_accumulates_within_cycle():
    gate = _gate()
    ok, _ = gate.check_equity_order("HD", 3_000)
    assert ok
    gate.record_fill("HD", 3_000)
    ok, _ = gate.check_equity_order("HD", 3_000)  # would now exceed $4,500
    assert not ok
