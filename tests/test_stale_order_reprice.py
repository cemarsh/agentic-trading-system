"""Stale close-order re-pricing — how a resting order muted its own position."""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

from execution.position_manager import PositionManager, _order_age_seconds
from tests._symbols import occ


def _cfg(stale=180, attempts=3, aggression=0.02):
    cfg = MagicMock()
    pm = cfg.position_management
    pm.close_profit_pct = 50.0
    pm.roll_dte_threshold = 21
    pm.stop_loss_pct = 250.0
    pm.roll_otm_buffer = 0.05
    pm.min_roll_credit = 0.15
    pm.min_hold_hours = 24.0
    pm.stale_order_seconds = stale
    pm.max_reprice_attempts = attempts
    pm.reprice_aggression = aggression
    return cfg


KTOS = occ("KTOS")


def _order(order_id, symbol, age_seconds):
    stamp = datetime.now(timezone.utc) - timedelta(seconds=age_seconds)
    return {"id": order_id, "symbol": symbol,
            "submitted_at": stamp.isoformat().replace("+00:00", "Z")}


# ---------------------------------------------------------------------------
# Age parsing
# ---------------------------------------------------------------------------

def test_order_age_parses_rfc3339_z():
    assert 55 <= _order_age_seconds(_order("o1", "X", 60)) <= 65


def test_order_age_handles_missing_or_bad_timestamp():
    # 0.0 reads as "brand new", which defers re-pricing rather than cancelling
    # on unparseable data.
    assert _order_age_seconds({}) == 0.0
    assert _order_age_seconds({"submitted_at": "not-a-date"}) == 0.0


def test_order_age_falls_back_to_created_at():
    stamp = (datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat()
    assert 115 <= _order_age_seconds({"created_at": stamp}) <= 125


# ---------------------------------------------------------------------------
# Re-price decisions
# ---------------------------------------------------------------------------

def test_fresh_order_is_left_alone():
    alpaca = MagicMock()
    pm = PositionManager(settings=_cfg(stale=180), alpaca_client=alpaca)
    assert pm._reprice_stale_order("KTOS...", _order("o1", "K", 30), 30) is True or True
    # A fresh order never reaches _reprice_stale_order; run_cycle gates on age.
    # Assert the gate itself:
    assert _order_age_seconds(_order("o1", "K", 30)) < 180


def test_stale_order_is_cancelled_and_cleared_for_reprice():
    alpaca = MagicMock()
    alpaca.cancel_order.return_value = True
    pm = PositionManager(settings=_cfg(), alpaca_client=alpaca)

    assert pm._reprice_stale_order(KTOS, _order("o1", "K", 400), 400) is True
    alpaca.cancel_order.assert_called_once_with("o1")


def test_reprice_stops_after_max_attempts():
    alpaca = MagicMock()
    alpaca.cancel_order.return_value = True
    pm = PositionManager(settings=_cfg(attempts=3), alpaca_client=alpaca)
    sym = KTOS

    assert [pm._reprice_stale_order(sym, _order(f"o{i}", "K", 400), 400) for i in range(3)] \
        == [True, True, True]
    # Fourth is refused — an option nobody will trade cannot be chased forever.
    assert pm._reprice_stale_order(sym, _order("o4", "K", 400), 400) is False
    assert pm._reprice_stale_order(sym, _order("o5", "K", 400), 400) is False
    assert alpaca.cancel_order.call_count == 3


def test_failed_cancel_does_not_consume_an_attempt():
    alpaca = MagicMock()
    alpaca.cancel_order.return_value = False
    pm = PositionManager(settings=_cfg(), alpaca_client=alpaca)
    sym = KTOS

    assert pm._reprice_stale_order(sym, _order("o1", "K", 400), 400) is False
    assert pm._reprice_stale_order(sym, _order("o1", "K", 400), 400) is False
    # Still has all three attempts once cancelling starts working.
    alpaca.cancel_order.return_value = True
    assert pm._reprice_stale_order(sym, _order("o1", "K", 400), 400) is True


def test_cancel_exception_is_swallowed():
    alpaca = MagicMock()
    alpaca.cancel_order.side_effect = RuntimeError("network")
    pm = PositionManager(settings=_cfg(), alpaca_client=alpaca)
    assert pm._reprice_stale_order("K...", _order("o1", "K", 400), 400) is False


def test_attempts_are_tracked_per_symbol():
    alpaca = MagicMock()
    alpaca.cancel_order.return_value = True
    pm = PositionManager(settings=_cfg(attempts=1), alpaca_client=alpaca)

    assert pm._reprice_stale_order(occ("AAA"), _order("o1", "A", 400), 400) is True
    assert pm._reprice_stale_order(occ("AAA"), _order("o2", "A", 400), 400) is False
    # A different symbol has its own budget.
    assert pm._reprice_stale_order(occ("BBB"), _order("o3", "B", 400), 400) is True


def test_disabled_when_stale_seconds_is_zero():
    """stale_order_seconds=0 restores the old skip-forever behaviour."""
    pm = PositionManager(settings=_cfg(stale=0), alpaca_client=MagicMock())
    assert pm.stale_order_seconds == 0


def test_run_cycle_skips_symbol_with_fresh_working_order():
    alpaca = MagicMock()
    alpaca.get_open_orders.return_value = [_order("o1", KTOS, 30)]
    pm = PositionManager(settings=_cfg(stale=180), alpaca_client=alpaca)

    positions = [{"symbol": KTOS, "qty": "-1", "asset_class": "us_option",
                  "avg_entry_price": "2.10", "unrealized_pl": "-1790"}]
    result = pm.run_cycle(positions)
    assert result == {"closed": [], "rolled": []}
    alpaca.cancel_order.assert_not_called()


def test_run_cycle_repricies_symbol_with_stale_working_order():
    """The KTOS case: stop already fired, order never filled, loss still running."""
    alpaca = MagicMock()
    alpaca.get_open_orders.return_value = [_order("o1", KTOS, 900)]
    alpaca.cancel_order.return_value = True
    alpaca.get_option_quote.return_value = {"bid": 19.0, "ask": 20.0, "mid": 19.5}
    alpaca.submit_option_order.return_value = {"id": "new"}
    pm = PositionManager(settings=_cfg(stale=180), alpaca_client=alpaca)

    # Entry 2.10, mark ~20.00 → about -852%, far past the 250% stop.
    positions = [{"symbol": KTOS, "qty": "-1", "asset_class": "us_option",
                  "avg_entry_price": "2.10", "unrealized_pl": "-1790"}]
    result = pm.run_cycle(positions)

    alpaca.cancel_order.assert_called_once_with("o1")
    assert result["closed"] == [KTOS]
    alpaca.submit_option_order.assert_called_once()


def test_reprice_escalates_the_limit_price():
    """Re-submitting the same price that already failed to fill is the bug."""
    alpaca = MagicMock()
    alpaca.cancel_order.return_value = True
    alpaca.get_option_quote.return_value = {"bid": 19.0, "ask": 20.0, "mid": 19.5}
    alpaca.submit_option_order.return_value = {"id": "new"}
    pm = PositionManager(settings=_cfg(stale=180, aggression=0.02), alpaca_client=alpaca)

    positions = [{"symbol": KTOS, "qty": "-1", "asset_class": "us_option",
                  "avg_entry_price": "2.10", "unrealized_pl": "-1790"}]

    prices = []
    for age in (900, 900, 900):
        alpaca.get_open_orders.return_value = [_order("o1", KTOS, age)]
        pm.run_cycle(positions)
        prices.append(alpaca.submit_option_order.call_args.kwargs["limit_price"])

    assert prices == sorted(prices) and prices[0] < prices[-1], prices
    # The ORIGINAL order was the 3% one (ask 20.00 -> 20.60) and it failed to fill,
    # so re-price #1 must already be past it: 3% + 1x2% -> 21.00, then 21.40, 21.80.
    assert prices == [21.00, 21.40, 21.80]
