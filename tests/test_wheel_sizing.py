"""Tests for wheel CSP sizing, IV-rank prioritization, and broker-derived stage.

Context: the wheel submitted qty=1 unconditionally, so a name whose caps authorized
four contracts still sold one. Sizing now fills the authorized capacity — these tests
pin the property that matters: the SMALLEST cap always binds, and no cap is ever
exceeded by the sized order.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

from execution.risk_gate import RiskGate
from execution.wheel_strategy import WheelStrategy


def _settings(tickers=("CCJ",), max_contracts=4, per_trade_pct=15.0,
              alloc_pct=65, prioritize=False):
    cfg = MagicMock()
    cfg.wheel.tickers = list(tickers)
    cfg.wheel.target_delta = 0.25
    cfg.wheel.expiration_weeks = 2
    cfg.wheel.cc_strike_markup_pct = 2.0
    cfg.wheel.min_premium_pct = 0.0          # credit floor off for sizing tests
    cfg.wheel.max_portfolio_pct_per_trade = per_trade_pct
    cfg.wheel.max_wheel_allocation_pct = alloc_pct
    cfg.wheel.min_iv_rank = 0.0              # IV gate off unless a test enables it
    cfg.wheel.iv_gate_fail_open = True
    cfg.wheel.min_credit_per_share = 0.10
    cfg.wheel.earnings_gate = False
    cfg.wheel.max_contracts_per_trade = max_contracts
    cfg.wheel.prioritize_by_iv_rank = prioritize
    cfg.wheel.skip_log_cooldown_minutes = 240
    cfg.database.url = ""
    return cfg


def _alpaca(price=100.0, strike=20.0, bid=0.50, equity="90000", initial_margin="0"):
    a = MagicMock()
    a.get_account.return_value = {"equity": equity, "initial_margin": initial_margin}
    a.get_bars.return_value = [{"c": price}]
    a.get_options_contracts.return_value = [
        {"type": "put", "strike_price": str(strike),
         "symbol": f"CCJ260821P{int(strike * 1000):08d}"},
    ]
    a.get_option_quote.return_value = {"bid": bid, "ask": bid + 0.05, "mid": bid + 0.02}
    a.submit_option_order.return_value = {"id": "order-1"}
    return a


def _submitted_qty(alpaca):
    return alpaca.submit_option_order.call_args.kwargs["qty"]


# ---------------------------------------------------------------- sizing

def test_sizes_up_to_the_hard_contract_ceiling():
    # $90k equity, 15% per-trade = $13,500. Strike $20 => $2,000/contract => 6 fit,
    # but max_contracts_per_trade caps it at 4.
    a = _alpaca(price=21.0, strike=20.0)
    ws = WheelStrategy(settings=_settings(max_contracts=4), alpaca_client=a)
    assert ws.open_csp("CCJ") is not None
    assert _submitted_qty(a) == 4


def test_per_trade_cap_binds_before_the_ceiling():
    # 15% of $90k = $13,500; strike $50 => $5,000/contract => only 2 fit.
    a = _alpaca(price=53.0, strike=50.0)
    ws = WheelStrategy(settings=_settings(max_contracts=4), alpaca_client=a)
    assert ws.open_csp("CCJ") is not None
    assert _submitted_qty(a) == 2


def test_allocation_headroom_binds():
    # 65% of $90k = $58,500 budget; $56,000 already used => $2,500 left => 1 contract
    # at $2,000, even though the per-trade cap would allow 6.
    a = _alpaca(price=21.0, strike=20.0, initial_margin="56000")
    ws = WheelStrategy(settings=_settings(max_contracts=4), alpaca_client=a)
    assert ws.open_csp("CCJ") is not None
    assert _submitted_qty(a) == 1


def test_sector_headroom_binds():
    # Real gate: CCJ is nuclear_uranium; CEG already holds $14,000 of a $18,000
    # sector cap (20% of $90k) => $4,000 left => 2 contracts at $2,000.
    cfg = _settings(max_contracts=4)
    cfg.risk.max_position_pct = 5.0
    cfg.risk.quarantine_max_position_pct = 1.0
    cfg.risk.quarantined_tickers = []
    cfg.risk.sector_cap_pct = 20.0
    cfg.risk.sector_map = {"nuclear_uranium": ["CCJ", "CEG"]}
    cfg.protection.no_auto_manage = []
    gate = RiskGate(settings=cfg)
    gate.refresh([{"symbol": "CEG", "qty": "50", "market_value": "14000"}], 90_000.0)

    a = _alpaca(price=21.0, strike=20.0)
    ws = WheelStrategy(settings=cfg, alpaca_client=a, risk_gate=gate)
    assert ws.open_csp("CCJ") is not None
    assert _submitted_qty(a) == 2


def test_no_headroom_skips_entirely():
    # Sector budget fully consumed => not even one contract => no order at all.
    cfg = _settings(max_contracts=4)
    cfg.risk.max_position_pct = 5.0
    cfg.risk.quarantine_max_position_pct = 1.0
    cfg.risk.quarantined_tickers = []
    cfg.risk.sector_cap_pct = 20.0
    cfg.risk.sector_map = {"nuclear_uranium": ["CCJ", "CEG"]}
    cfg.protection.no_auto_manage = []
    gate = RiskGate(settings=cfg)
    gate.refresh([{"symbol": "CEG", "qty": "80", "market_value": "18000"}], 90_000.0)

    a = _alpaca(price=21.0, strike=20.0)
    ws = WheelStrategy(settings=cfg, alpaca_client=a, risk_gate=gate)
    assert ws.open_csp("CCJ") is None
    a.submit_option_order.assert_not_called()


def test_expensive_underlying_still_rejected_by_per_trade_cap():
    # One CAT-sized contract ($80,550) exceeds 15% of $90k — must not trade at qty 1.
    a = _alpaca(price=859.0, strike=805.5)
    ws = WheelStrategy(settings=_settings(max_contracts=4), alpaca_client=a)
    assert ws.open_csp("CCJ") is None
    a.submit_option_order.assert_not_called()


def test_sized_order_is_rechecked_against_the_gate():
    # The gate must see the SIZED collateral, not one contract's worth.
    cfg = _settings(max_contracts=4)
    cfg.risk.max_position_pct = 5.0
    cfg.risk.quarantine_max_position_pct = 1.0
    cfg.risk.quarantined_tickers = []
    cfg.risk.sector_cap_pct = 20.0
    cfg.risk.sector_map = {"nuclear_uranium": ["CCJ"]}
    cfg.protection.no_auto_manage = []
    gate = RiskGate(settings=cfg)
    gate.refresh([], 90_000.0)

    a = _alpaca(price=21.0, strike=20.0)
    ws = WheelStrategy(settings=cfg, alpaca_client=a, risk_gate=gate)
    ws.open_csp("CCJ")
    qty = _submitted_qty(a)
    # Whatever was sized must fit inside the 20% sector cap ($18,000).
    assert 20.0 * 100 * qty <= 18_000


# ------------------------------------------------------- prioritization

def test_run_cycle_evaluates_richest_iv_first(monkeypatch):
    cfg = _settings(tickers=("AAA", "BBB", "CCC"), prioritize=True)
    cfg.risk.quarantined_tickers = []
    cfg.protection.no_auto_manage = []
    ws = WheelStrategy(settings=cfg, alpaca_client=MagicMock())

    ranks = {"AAA": 0.20, "BBB": 0.95, "CCC": 0.55}
    monkeypatch.setattr(ws, "_iv_rank", lambda t: ranks[t])

    seen = []
    monkeypatch.setattr(ws, "open_csp", lambda t, ivr=None: seen.append(t) or None)
    ws.run_cycle()
    assert seen == ["BBB", "CCC", "AAA"]


def test_unknown_iv_rank_sorts_last(monkeypatch):
    cfg = _settings(tickers=("AAA", "BBB"), prioritize=True)
    cfg.risk.quarantined_tickers = []
    cfg.protection.no_auto_manage = []
    ws = WheelStrategy(settings=cfg, alpaca_client=MagicMock())

    monkeypatch.setattr(ws, "_iv_rank", lambda t: None if t == "AAA" else 0.10)
    seen = []
    monkeypatch.setattr(ws, "open_csp", lambda t, ivr=None: seen.append(t) or None)
    ws.run_cycle()
    assert seen == ["BBB", "AAA"]


# --------------------------------------------------- broker-derived stage

def test_sync_positions_marks_short_put_as_stage_1():
    cfg = _settings(tickers=("CCJ", "MP"))
    cfg.risk.quarantined_tickers = []
    cfg.protection.no_auto_manage = []
    ws = WheelStrategy(settings=cfg, alpaca_client=MagicMock())
    ws.sync_positions([{"symbol": "CCJ260821P00098000", "qty": "-1"}])
    assert ws._positions["CCJ"].stage == 1
    assert ws._positions["CCJ"].csp_strike == 98.0
    assert ws._positions["MP"].stage == 0


def test_sync_positions_marks_assigned_shares_as_stage_2():
    cfg = _settings(tickers=("MP",))
    cfg.risk.quarantined_tickers = []
    cfg.protection.no_auto_manage = []
    ws = WheelStrategy(settings=cfg, alpaca_client=MagicMock())
    ws.sync_positions([{"symbol": "MP", "qty": "300", "market_value": "14000"}])
    assert ws._positions["MP"].stage == 2
    assert ws._positions["MP"].shares_held == 300


def test_sync_positions_clears_stage_when_flat():
    cfg = _settings(tickers=("CCJ",))
    cfg.risk.quarantined_tickers = []
    cfg.protection.no_auto_manage = []
    ws = WheelStrategy(settings=cfg, alpaca_client=MagicMock())
    ws._positions["CCJ"].stage = 1
    ws.sync_positions([])
    assert ws._positions["CCJ"].stage == 0


def test_open_csp_refuses_when_already_short_a_put():
    # The restart bug: stage reset to 0 in memory while the broker still held the put.
    a = _alpaca(price=21.0, strike=20.0)
    cfg = _settings()
    cfg.risk.quarantined_tickers = []
    cfg.protection.no_auto_manage = []
    ws = WheelStrategy(settings=cfg, alpaca_client=a)
    ws.sync_positions([{"symbol": "CCJ260821P00020000", "qty": "-1"}])
    assert ws.open_csp("CCJ") is None
    a.submit_option_order.assert_not_called()
