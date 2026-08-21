"""Catastrophic equity loss floor — the exit no_auto_manage names never had."""

import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

from execution.protective_logic import ProtectiveLogic


def _cfg(limit=25.0, no_auto=("FJET",)):
    cfg = MagicMock()
    cfg.protection.trailing_stop_pct = 7.0
    cfg.protection.gap_tighten_pct = 3.0
    cfg.protection.ladder_drop_pct = 5.0
    cfg.protection.ladder_buy_shares = 10
    cfg.protection.max_ladder_rungs = 3
    cfg.protection.no_auto_manage = list(no_auto)
    cfg.protection.max_equity_loss_pct = limit
    cfg.protection.catastrophic_exempt = []
    return cfg


def _pos(symbol, qty, entry, price):
    return {
        "symbol": symbol, "qty": str(qty),
        "avg_entry_price": str(entry), "current_price": str(price),
        "unrealized_pl": str((price - entry) * qty),
    }


def test_fires_on_no_auto_manage_ticker():
    """The whole point: FJET is excluded from sync_positions and must still be caught."""
    pl = ProtectiveLogic(settings=_cfg(), alpaca_client=MagicMock())
    positions = [_pos("FJET", 4570, 5.70, 3.90)]  # -31.6%

    pl.sync_positions(positions)
    assert "FJET" not in pl._positions          # excluded from trailing-stop state...

    breached = pl.check_catastrophic_loss(positions)
    assert len(breached) == 1                    # ...but NOT from the loss floor
    assert breached[0]["ticker"] == "FJET"
    assert round(breached[0]["loss_pct"], 1) == 31.6


def test_does_not_fire_above_threshold():
    pl = ProtectiveLogic(settings=_cfg(limit=25.0), alpaca_client=MagicMock())
    assert pl.check_catastrophic_loss([_pos("FJET", 100, 10.0, 8.0)]) == []  # -20%


def test_fires_exactly_at_threshold():
    pl = ProtectiveLogic(settings=_cfg(limit=25.0), alpaca_client=MagicMock())
    assert len(pl.check_catastrophic_loss([_pos("FJET", 100, 10.0, 7.5)])) == 1  # -25%


def test_disabled_when_limit_is_zero():
    pl = ProtectiveLogic(settings=_cfg(limit=0.0), alpaca_client=MagicMock())
    assert pl.check_catastrophic_loss([_pos("FJET", 100, 10.0, 1.0)]) == []


def test_ignores_option_positions():
    pl = ProtectiveLogic(settings=_cfg(), alpaca_client=MagicMock())
    opt = {"symbol": "KTOS260904P00052000", "qty": "-1",
           "avg_entry_price": "2.10", "current_price": "20.00", "unrealized_pl": "-1790"}
    assert pl.check_catastrophic_loss([opt]) == []


def test_ignores_short_equity():
    """A losing short leg needs a buy-to-cover, not this rule's sell."""
    pl = ProtectiveLogic(settings=_cfg(), alpaca_client=MagicMock())
    assert pl.check_catastrophic_loss([_pos("XYZ", -100, 10.0, 5.0)]) == []


def test_is_idempotent_across_cycles_when_state_given():
    """A restart loop must not resubmit the liquidation (guards.acted_once)."""
    pl = ProtectiveLogic(settings=_cfg(), alpaca_client=MagicMock())
    positions = [_pos("FJET", 4570, 5.70, 3.90)]
    state = {}

    assert len(pl.check_catastrophic_loss(positions, state=state)) == 1
    assert pl.check_catastrophic_loss(positions, state=state) == []
    assert pl.check_catastrophic_loss(positions, state=state) == []


def test_without_state_fires_every_call():
    """No state passed = no dedup; the caller owns idempotency in that mode."""
    pl = ProtectiveLogic(settings=_cfg(), alpaca_client=MagicMock())
    positions = [_pos("FJET", 4570, 5.70, 3.90)]
    assert len(pl.check_catastrophic_loss(positions)) == 1
    assert len(pl.check_catastrophic_loss(positions)) == 1


def test_execute_submits_full_size_sell_and_clears_stop_state():
    alpaca = MagicMock()
    alpaca.submit_order.return_value = {"id": "o1"}
    pl = ProtectiveLogic(settings=_cfg(no_auto=()), alpaca_client=alpaca)

    positions = [_pos("FJET", 4570, 5.70, 3.90)]
    pl.sync_positions(positions)                 # not excluded here, so state exists
    assert "FJET" in pl._positions

    breach = pl.check_catastrophic_loss(positions)[0]
    assert pl.execute_catastrophic_exit(breach) == {"id": "o1"}

    alpaca.submit_order.assert_called_once()
    kwargs = alpaca.submit_order.call_args.kwargs
    assert kwargs["ticker"] == "FJET"
    assert kwargs["qty"] == 4570
    assert kwargs["side"] == "sell"
    # Trailing-stop state must be dropped so check_stops can't fire a second sell.
    assert "FJET" not in pl._positions


def test_execute_returns_none_when_broker_rejects():
    alpaca = MagicMock()
    alpaca.submit_order.side_effect = RuntimeError("rejected")
    pl = ProtectiveLogic(settings=_cfg(), alpaca_client=alpaca)
    breach = pl.check_catastrophic_loss([_pos("FJET", 100, 10.0, 5.0)])[0]
    assert pl.execute_catastrophic_exit(breach) is None


def test_skips_positions_with_unusable_prices():
    pl = ProtectiveLogic(settings=_cfg(), alpaca_client=MagicMock())
    bad = {"symbol": "FJET", "qty": "100", "avg_entry_price": "0",
           "current_price": "0", "unrealized_pl": "0"}
    assert pl.check_catastrophic_loss([bad]) == []


def test_execute_cancels_resting_sells_before_liquidating():
    """Shares locked by a working sell are not available to a new order — the
    liquidation would be rejected and appear to have fired. FJET is the live case:
    4,261 of 4,570 shares locked by a GTC breakeven sell."""
    alpaca = MagicMock()
    alpaca.get_open_orders.return_value = [
        {"id": "gtc1", "symbol": "FJET", "side": "sell", "qty": "4261", "limit_price": "5.71"},
        {"id": "other", "symbol": "CCJ", "side": "sell", "qty": "100", "limit_price": "99"},
    ]
    alpaca.cancel_order.return_value = True
    alpaca.submit_order.return_value = {"id": "o1"}
    pl = ProtectiveLogic(settings=_cfg(), alpaca_client=alpaca)

    breach = pl.check_catastrophic_loss([_pos("FJET", 4570, 5.70, 3.86)])[0]
    pl.execute_catastrophic_exit(breach)

    alpaca.cancel_order.assert_called_once_with("gtc1")   # only FJET's, not CCJ's
    assert alpaca.submit_order.call_args.kwargs["qty"] == 4570


def test_execute_still_sells_when_order_cleanup_fails():
    alpaca = MagicMock()
    alpaca.get_open_orders.side_effect = RuntimeError("api down")
    alpaca.submit_order.return_value = {"id": "o1"}
    pl = ProtectiveLogic(settings=_cfg(), alpaca_client=alpaca)

    breach = pl.check_catastrophic_loss([_pos("FJET", 100, 10.0, 5.0)])[0]
    assert pl.execute_catastrophic_exit(breach) == {"id": "o1"}


def test_exempt_ticker_is_not_liquidated():
    """FJET is held under an explicit plan (breakeven order + covered calls), so the
    floor must not fire on it — decision recorded in strategy_params.yaml."""
    cfg = _cfg()
    cfg.protection.catastrophic_exempt = ["FJET"]
    pl = ProtectiveLogic(settings=cfg, alpaca_client=MagicMock())
    assert pl.check_catastrophic_loss([_pos("FJET", 4570, 5.70, 3.86)]) == []


def test_exemption_does_not_leak_to_other_tickers():
    cfg = _cfg()
    cfg.protection.catastrophic_exempt = ["FJET"]
    pl = ProtectiveLogic(settings=cfg, alpaca_client=MagicMock())
    breached = pl.check_catastrophic_loss([
        _pos("FJET", 4570, 5.70, 3.86),
        _pos("OPTX", 100, 10.0, 6.0),
    ])
    assert [b["ticker"] for b in breached] == ["OPTX"]
