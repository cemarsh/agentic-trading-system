"""Tests for the wheel selection gates — hard IV gate, credit floor, earnings
gate, limit-order entry."""

import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

from execution.wheel_strategy import WheelStrategy


def _settings(min_iv_rank=0.0, iv_fail_open=False):
    cfg = MagicMock()
    cfg.wheel.tickers = ["CCJ"]
    cfg.wheel.target_delta = 0.25
    cfg.wheel.expiration_weeks = 2
    cfg.wheel.cc_strike_markup_pct = 2.0
    cfg.wheel.min_premium_pct = 0.8
    cfg.wheel.max_portfolio_pct_per_trade = 15.0
    cfg.wheel.max_wheel_allocation_pct = 65
    cfg.wheel.min_iv_rank = min_iv_rank
    cfg.wheel.iv_gate_fail_open = iv_fail_open
    cfg.wheel.min_credit_per_share = 0.15
    cfg.wheel.earnings_gate = False  # off by default in tests; enabled per-test
    cfg.database.url = ""            # no IV history available
    return cfg


def _alpaca(bid=1.50, strike=95.0):
    a = MagicMock()
    a.get_account.return_value = {"equity": "90000", "initial_margin": "0"}
    a.get_bars.return_value = [{"c": 100.0}]
    a.get_options_contracts.return_value = [
        {"type": "put", "strike_price": str(strike), "symbol": f"CCJ260717P{int(strike*1000):08d}"},
    ]
    a.get_option_quote.return_value = {"bid": bid, "ask": bid + 0.10, "mid": bid + 0.05}
    a.submit_option_order.return_value = {"id": "order-1"}
    return a


def test_hard_iv_gate_blocks_without_history():
    ws = WheelStrategy(settings=_settings(min_iv_rank=0.30), alpaca_client=_alpaca())
    assert ws.open_csp("CCJ") is None
    ws._alpaca.submit_option_order.assert_not_called()


def test_iv_gate_fail_open_allows_without_history():
    ws = WheelStrategy(settings=_settings(min_iv_rank=0.30, iv_fail_open=True),
                       alpaca_client=_alpaca())
    assert ws.open_csp("CCJ") is not None


def test_credit_floor_blocks_thin_bid():
    # $0.10 bid < max($0.15 abs floor, 0.8% of $95 = $0.76)
    ws = WheelStrategy(settings=_settings(), alpaca_client=_alpaca(bid=0.10))
    assert ws.open_csp("CCJ") is None
    ws._alpaca.submit_option_order.assert_not_called()


def test_credit_floor_uses_premium_pct_of_strike():
    # $0.50 bid clears the $0.15 abs floor but not 0.8% of strike ($0.76)
    ws = WheelStrategy(settings=_settings(), alpaca_client=_alpaca(bid=0.50))
    assert ws.open_csp("CCJ") is None


def test_good_credit_places_limit_order_at_bid():
    ws = WheelStrategy(settings=_settings(), alpaca_client=_alpaca(bid=1.50))
    order = ws.open_csp("CCJ")
    assert order is not None
    kwargs = ws._alpaca.submit_option_order.call_args.kwargs
    assert kwargs["order_type"] == "limit"
    assert kwargs["limit_price"] == 1.50
    assert kwargs["side"] == "sell"


def test_earnings_gate_blocks(monkeypatch):
    import execution.earnings_calendar as ec
    monkeypatch.setattr(ec, "has_earnings_before", lambda t, e: True)
    cfg = _settings()
    cfg.wheel.earnings_gate = True
    ws = WheelStrategy(settings=cfg, alpaca_client=_alpaca())
    assert ws.open_csp("CCJ") is None


def test_earnings_gate_fail_open_when_unknown(monkeypatch):
    import execution.earnings_calendar as ec
    monkeypatch.setattr(ec, "has_earnings_before", lambda t, e: None)
    cfg = _settings()
    cfg.wheel.earnings_gate = True
    ws = WheelStrategy(settings=cfg, alpaca_client=_alpaca())
    assert ws.open_csp("CCJ") is not None


def test_risk_gate_blocks_csp():
    gate = MagicMock()
    gate.check_option_collateral.return_value = (False, "sector cap")
    ws = WheelStrategy(settings=_settings(), alpaca_client=_alpaca(), risk_gate=gate)
    assert ws.open_csp("CCJ") is None
    ws._alpaca.submit_option_order.assert_not_called()


def test_ledger_records_open():
    ledger = MagicMock()
    ws = WheelStrategy(settings=_settings(), alpaca_client=_alpaca(), ledger=ledger)
    assert ws.open_csp("CCJ") is not None
    ledger.record_open.assert_called_once()
    assert ledger.record_open.call_args.kwargs.get("owner") == "wheel"
