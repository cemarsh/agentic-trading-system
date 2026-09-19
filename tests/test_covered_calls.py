"""Covered calls on held shares — the path run_cycle never reached (2026-08-21)."""

import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

from execution.wheel_strategy import WheelStrategy
from tests._symbols import occ


def _cfg(tickers=("FJET",), write_ccs=True, underwater_pct=25.0, uw_markup=12.0,
         quarantined=("FJET",)):
    cfg = MagicMock()
    cfg.wheel.tickers = list(tickers)
    cfg.wheel.target_delta = 0.25
    cfg.wheel.expiration_weeks = 2
    cfg.wheel.cc_strike_markup_pct = 2.0
    cfg.wheel.min_premium_pct = 0.0
    cfg.wheel.max_portfolio_pct_per_trade = 15.0
    cfg.wheel.max_wheel_allocation_pct = 65
    cfg.wheel.min_iv_rank = 0.0
    cfg.wheel.iv_gate_fail_open = True
    cfg.wheel.min_credit_per_share = 0.10
    cfg.wheel.earnings_gate = False
    cfg.wheel.max_contracts_per_trade = 1
    cfg.wheel.prioritize_by_iv_rank = False
    cfg.wheel.skip_log_cooldown_minutes = 0
    cfg.wheel.use_signal_candidates = False
    cfg.wheel.max_book_loss_pct = 0.0
    cfg.wheel.skip_losing_underlying = False
    cfg.wheel.min_otm_vol_mult = 0.0
    cfg.wheel.min_credit_vs_expected_move = 0.0
    cfg.wheel.realized_vol_lookback_days = 30
    cfg.wheel.write_covered_calls = write_ccs
    cfg.wheel.underwater_cc_loss_pct = underwater_pct
    cfg.wheel.underwater_cc_markup_pct = uw_markup
    cfg.risk.quarantined_tickers = list(quarantined)
    cfg.protection.no_auto_manage = list(quarantined)
    return cfg


def _fjet(qty=4570, available=309, entry=5.702366, price=3.86):
    return {"symbol": "FJET", "qty": str(qty), "qty_available": str(available),
            "avg_entry_price": str(entry), "current_price": str(price),
            "market_value": str(qty * price), "unrealized_pl": str((price - entry) * qty)}


def _alpaca(call_strikes=(4.5,), bid=0.15):
    a = MagicMock()
    a.get_account.return_value = {"equity": "83907", "initial_margin": "0"}
    a.get_options_contracts.return_value = [
        {"type": "call", "strike_price": str(s), "symbol": occ("FJET", "C", s)}
        for s in call_strikes
    ]
    a.get_option_quote.return_value = {"bid": bid, "ask": bid + 0.05, "mid": bid}
    a.submit_option_order.return_value = {"id": "cc1"}
    return a


# ---------------------------------------------------------------------------
# Sync
# ---------------------------------------------------------------------------

def test_sync_records_available_shares_and_cost_basis():
    ws = WheelStrategy(settings=_cfg(), alpaca_client=MagicMock())
    ws.sync_positions([_fjet()])
    assert ws._positions["FJET"].stage == 2
    assert ws._positions["FJET"].shares_held == 4570
    assert ws._shares_available["FJET"] == 309       # not 4570
    assert round(ws._positions["FJET"].cost_basis, 2) == 5.70   # from broker, not 0.0


def test_sync_detects_existing_short_calls():
    ws = WheelStrategy(settings=_cfg(), alpaca_client=MagicMock())
    ws.sync_positions([
        _fjet(),
        {"symbol": occ("FJET", "C", 4.5), "qty": "-3", "unrealized_pl": "-10",
         "avg_entry_price": "0.15", "current_price": "0.18", "market_value": "-54"},
    ])
    assert ws._open_short_calls == {"FJET": 4.5}


# ---------------------------------------------------------------------------
# Sizing and strike selection
# ---------------------------------------------------------------------------

def test_cc_sized_to_available_not_held_shares():
    """4,570 held but only 309 free -> 3 contracts, not 45."""
    alpaca = _alpaca()
    ws = WheelStrategy(settings=_cfg(), alpaca_client=alpaca)
    ws.sync_positions([_fjet()])

    assert ws.open_cc("FJET") is not None
    assert alpaca.submit_option_order.call_args.kwargs["qty"] == 3


def test_cc_skipped_when_no_free_shares():
    alpaca = _alpaca()
    ws = WheelStrategy(settings=_cfg(), alpaca_client=alpaca)
    ws.sync_positions([_fjet(available=42)])

    assert ws.open_cc("FJET") is None
    alpaca.submit_option_order.assert_not_called()


def test_underwater_position_prices_strike_off_spot():
    """Basis $5.70 x 1.02 = $5.81 is ~50% OTM at a $3.86 spot and bids ~$0.00."""
    alpaca = _alpaca(call_strikes=(4.5, 5.5, 6.0))
    ws = WheelStrategy(settings=_cfg(uw_markup=12.0), alpaca_client=alpaca)
    ws.sync_positions([_fjet()])

    ws.open_cc("FJET")
    # spot 3.86 x 1.12 = 4.32 -> nearest available strike is 4.5, not the 5.5/6.0
    # a basis-derived target would have chosen.
    assert alpaca.submit_option_order.call_args.kwargs["symbol"] == occ("FJET", "C", 4.5)


def test_healthy_position_still_uses_cost_basis_strike():
    alpaca = _alpaca(call_strikes=(10.0, 11.0, 12.0))
    ws = WheelStrategy(settings=_cfg(), alpaca_client=alpaca)
    # 2% below basis — nowhere near the underwater threshold
    ws.sync_positions([{"symbol": "FJET", "qty": "500", "qty_available": "500",
                        "avg_entry_price": "10.0", "current_price": "9.8",
                        "market_value": "4900", "unrealized_pl": "-100"}])
    ws.open_cc("FJET")
    # basis 10.0 x 1.02 = 10.2 -> nearest is 10.0
    assert alpaca.submit_option_order.call_args.kwargs["symbol"] == occ("FJET", "C", 10)


def test_underwater_mode_disabled_at_zero():
    alpaca = _alpaca(call_strikes=(4.5, 5.5, 6.0))
    ws = WheelStrategy(settings=_cfg(underwater_pct=0.0), alpaca_client=alpaca)
    ws.sync_positions([_fjet()])
    ws.open_cc("FJET")
    # falls back to basis 5.70 x 1.02 = 5.81 -> nearest is 6.0... or 5.5
    chosen = alpaca.submit_option_order.call_args.kwargs["symbol"]
    assert chosen in (occ("FJET", "C", 5.5), occ("FJET", "C", 6))


# ---------------------------------------------------------------------------
# Runaway protection
# ---------------------------------------------------------------------------

def test_does_not_stack_a_second_covered_call():
    """stage stays 2 after writing, so without this guard every cycle sells another."""
    alpaca = _alpaca()
    ws = WheelStrategy(settings=_cfg(), alpaca_client=alpaca)
    ws.sync_positions([
        _fjet(),
        {"symbol": occ("FJET", "C", 4.5), "qty": "-3", "unrealized_pl": "-10",
         "avg_entry_price": "0.15", "current_price": "0.18", "market_value": "-54"},
    ])
    assert ws.open_cc("FJET") is None
    alpaca.submit_option_order.assert_not_called()


def test_no_bid_means_no_order():
    alpaca = _alpaca(bid=0.0)
    ws = WheelStrategy(settings=_cfg(), alpaca_client=alpaca)
    ws.sync_positions([_fjet()])
    assert ws.open_cc("FJET") is None


# ---------------------------------------------------------------------------
# run_cycle wiring
# ---------------------------------------------------------------------------

def test_run_cycle_writes_covered_calls_on_quarantined_holdings():
    """Quarantine blocks new RISK; a CC on shares already owned reduces it."""
    alpaca = _alpaca()
    ws = WheelStrategy(settings=_cfg(), alpaca_client=alpaca)
    ws.sync_positions([_fjet()])

    assert ws.run_cycle() == 1
    alpaca.submit_option_order.assert_called_once()


def test_run_cycle_skips_covered_calls_when_disabled():
    alpaca = _alpaca()
    ws = WheelStrategy(settings=_cfg(write_ccs=False), alpaca_client=alpaca)
    ws.sync_positions([_fjet()])

    assert ws.run_cycle() == 0
    alpaca.submit_option_order.assert_not_called()


def test_run_cycle_cc_failure_does_not_abort_the_cycle():
    alpaca = _alpaca()
    alpaca.get_options_contracts.side_effect = RuntimeError("chain down")
    ws = WheelStrategy(settings=_cfg(), alpaca_client=alpaca)
    ws.sync_positions([_fjet()])
    assert ws.run_cycle() == 0        # swallowed, not raised
