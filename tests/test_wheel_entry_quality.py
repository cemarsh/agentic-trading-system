"""Wheel book-health and expected-value entry gates (2026-08-21)."""

import math
import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

from execution.wheel_strategy import WheelStrategy
from tests._symbols import occ


def _cfg(tickers=("CCJ",), book_loss=0.0, skip_losing=False,
         otm_mult=0.0, credit_mult=0.0):
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
    cfg.wheel.max_book_loss_pct = book_loss
    cfg.wheel.skip_losing_underlying = skip_losing
    cfg.wheel.min_otm_vol_mult = otm_mult
    cfg.wheel.min_credit_vs_expected_move = credit_mult
    cfg.wheel.realized_vol_lookback_days = 30
    cfg.risk.quarantined_tickers = []
    cfg.protection.no_auto_manage = []
    return cfg


def _equity_pos(symbol, qty, unrealized):
    return {"symbol": symbol, "qty": str(qty), "unrealized_pl": str(unrealized),
            "market_value": "1000", "avg_entry_price": "10", "current_price": "9"}


def _short_put(symbol, unrealized):
    return {"symbol": symbol, "qty": "-1", "unrealized_pl": str(unrealized),
            "market_value": "-100", "avg_entry_price": "2.00", "current_price": "3.00"}


# ---------------------------------------------------------------------------
# Book health
# ---------------------------------------------------------------------------

def test_book_health_allows_a_clean_book():
    ws = WheelStrategy(settings=_cfg(book_loss=15.0), alpaca_client=MagicMock())
    ws.sync_positions([_equity_pos("CCJ", 100, +500)])
    ok, reason = ws.book_health(100_000)
    assert ok and reason == ""


def test_book_health_blocks_when_loss_exceeds_limit():
    ws = WheelStrategy(settings=_cfg(book_loss=15.0), alpaca_client=MagicMock())
    ws.sync_positions([_equity_pos("FJET", 4570, -8637), _short_put(occ("KTOS", "P", 52), -400)])
    ok, reason = ws.book_health(50_000)          # -9037 / 50k = 18.1%
    assert not ok
    assert "18.1%" in reason


def test_book_health_allows_loss_under_limit():
    ws = WheelStrategy(settings=_cfg(book_loss=15.0), alpaca_client=MagicMock())
    ws.sync_positions([_equity_pos("FJET", 4570, -8637)])
    ok, _ = ws.book_health(83_907)               # 10.3%
    assert ok


def test_book_health_disabled_at_zero():
    ws = WheelStrategy(settings=_cfg(book_loss=0.0), alpaca_client=MagicMock())
    ws.sync_positions([_equity_pos("FJET", 100, -99_000)])
    assert ws.book_health(100_000)[0] is True


def test_book_health_safe_without_equity():
    ws = WheelStrategy(settings=_cfg(book_loss=15.0), alpaca_client=MagicMock())
    ws.sync_positions([_equity_pos("FJET", 100, -5000)])
    assert ws.book_health(0)[0] is True          # unknown equity must not block


def test_run_cycle_returns_zero_when_book_is_stressed():
    alpaca = MagicMock()
    alpaca.get_account.return_value = {"equity": "50000"}
    ws = WheelStrategy(settings=_cfg(book_loss=15.0), alpaca_client=alpaca)
    ws.sync_positions([_equity_pos("FJET", 4570, -8637), _short_put(occ("KTOS", "P", 52), -400)])

    assert ws.run_cycle() == 0
    alpaca.get_options_contracts.assert_not_called()   # never even priced a chain


# ---------------------------------------------------------------------------
# Losing-underlying gate
# ---------------------------------------------------------------------------

def test_sync_records_losing_underlyings_from_equity_and_options():
    ws = WheelStrategy(settings=_cfg(tickers=("CCJ", "KTOS")), alpaca_client=MagicMock())
    ws.sync_positions([
        _equity_pos("CCJ", 100, -250),
        _short_put(occ("KTOS", "P", 52), -400),
        _equity_pos("MP", 100, +80),
    ])
    assert ws._losing_underlyings == {"CCJ", "KTOS"}
    assert ws._book_unrealized == -570.0


def test_open_csp_skips_underlying_already_at_a_loss():
    alpaca = MagicMock()
    alpaca.get_account.return_value = {"equity": "100000", "initial_margin": "0"}
    ws = WheelStrategy(settings=_cfg(skip_losing=True), alpaca_client=alpaca)
    ws.sync_positions([_equity_pos("CCJ", 100, -250)])
    ws._positions["CCJ"].stage = 0               # flat on options, long the shares

    assert ws.open_csp("CCJ") is None
    alpaca.get_options_contracts.assert_not_called()


def test_open_csp_allows_losing_underlying_when_gate_off():
    alpaca = MagicMock()
    alpaca.get_account.return_value = {"equity": "100000", "initial_margin": "0"}
    alpaca.get_bars.return_value = [{"c": 100.0}]
    alpaca.get_options_contracts.return_value = []
    ws = WheelStrategy(settings=_cfg(skip_losing=False), alpaca_client=alpaca)
    ws.sync_positions([_equity_pos("CCJ", 100, -250)])
    ws._positions["CCJ"].stage = 0

    ws.open_csp("CCJ")
    alpaca.get_options_contracts.assert_called_once()   # got past the gate


# ---------------------------------------------------------------------------
# Realized vol / expected move
# ---------------------------------------------------------------------------

def test_realized_vol_computed_from_daily_bars():
    alpaca = MagicMock()
    closes = [100 * (1.01 ** i) for i in range(31)]     # constant +1%/day
    alpaca.get_bars.return_value = [{"c": c} for c in closes]
    ws = WheelStrategy(settings=_cfg(), alpaca_client=alpaca)
    vol = ws._realized_vol("CCJ")
    assert vol is not None
    assert vol < 1e-6                                   # zero variance in log returns


def test_realized_vol_none_with_too_few_bars():
    alpaca = MagicMock()
    alpaca.get_bars.return_value = [{"c": 100.0}, {"c": 101.0}]
    ws = WheelStrategy(settings=_cfg(), alpaca_client=alpaca)
    assert ws._realized_vol("CCJ") is None


def test_realized_vol_is_cached_per_process():
    alpaca = MagicMock()
    alpaca.get_bars.return_value = [{"c": 100.0 + i} for i in range(31)]
    ws = WheelStrategy(settings=_cfg(), alpaca_client=alpaca)
    ws._realized_vol("CCJ")
    ws._realized_vol("CCJ")
    assert alpaca.get_bars.call_count == 1


def test_realized_vol_survives_broker_error():
    alpaca = MagicMock()
    alpaca.get_bars.side_effect = RuntimeError("no data")
    ws = WheelStrategy(settings=_cfg(), alpaca_client=alpaca)
    assert ws._realized_vol("CCJ") is None


def test_expected_move_scales_with_sqrt_of_time():
    alpaca = MagicMock()
    ws = WheelStrategy(settings=_cfg(), alpaca_client=alpaca)
    ws._vol_cache["CCJ"] = 0.02                          # 2% daily
    one = ws._expected_move("CCJ", 100.0, 1)
    four = ws._expected_move("CCJ", 100.0, 4)
    assert abs(one - 2.0) < 1e-9
    assert abs(four - 4.0) < 1e-9                        # 2 * sqrt(4)


def test_expected_move_none_without_vol():
    ws = WheelStrategy(settings=_cfg(), alpaca_client=MagicMock())
    ws._vol_cache["CCJ"] = None
    assert ws._expected_move("CCJ", 100.0, 14) is None


# ---------------------------------------------------------------------------
# Expected-value entry gates
# ---------------------------------------------------------------------------

def _alpaca_for_entry(spot=100.0, strike=94.0, bid=1.00):
    alpaca = MagicMock()
    alpaca.get_account.return_value = {"equity": "100000", "initial_margin": "0"}
    alpaca.get_bars.return_value = [{"c": spot}]
    alpaca.get_options_contracts.return_value = [
        {"type": "put", "strike_price": str(strike), "symbol": occ("CCJ", "P", 94)}
    ]
    alpaca.get_option_quote.return_value = {"bid": bid, "ask": bid + 0.05, "mid": bid}
    alpaca.submit_option_order.return_value = {"id": "o1"}
    return alpaca


def test_strike_inside_one_sigma_is_rejected():
    """~6% OTM is far on a quiet name and inside a normal week on a volatile one."""
    alpaca = _alpaca_for_entry(spot=100.0, strike=94.0, bid=1.00)
    ws = WheelStrategy(settings=_cfg(otm_mult=1.0), alpaca_client=alpaca)
    ws._vol_cache["CCJ"] = 0.05          # 5% daily -> 14d sigma ~ $18.7, strike only $6 OTM

    assert ws.open_csp("CCJ") is None
    alpaca.submit_option_order.assert_not_called()


def test_strike_outside_one_sigma_is_allowed():
    alpaca = _alpaca_for_entry(spot=100.0, strike=94.0, bid=1.00)
    ws = WheelStrategy(settings=_cfg(otm_mult=1.0), alpaca_client=alpaca)
    ws._vol_cache["CCJ"] = 0.004         # 14d sigma ~ $1.50, strike $6 OTM

    assert ws.open_csp("CCJ") is not None
    alpaca.submit_option_order.assert_called_once()


def test_thin_credit_versus_expected_move_is_rejected():
    alpaca = _alpaca_for_entry(spot=100.0, strike=94.0, bid=0.23)   # the GEO case
    ws = WheelStrategy(settings=_cfg(credit_mult=0.15), alpaca_client=alpaca)
    ws._vol_cache["CCJ"] = 0.01          # 14d sigma ~ $3.74; 15% of that is $0.56

    assert ws.open_csp("CCJ") is None
    alpaca.submit_option_order.assert_not_called()


def test_sufficient_credit_versus_expected_move_is_allowed():
    alpaca = _alpaca_for_entry(spot=100.0, strike=94.0, bid=1.20)
    ws = WheelStrategy(settings=_cfg(credit_mult=0.15), alpaca_client=alpaca)
    ws._vol_cache["CCJ"] = 0.01          # need >= $0.56, have $1.20

    assert ws.open_csp("CCJ") is not None


def test_ev_gates_fail_open_when_vol_unavailable():
    """An unmeasurable vol must not become a silent second IV gate."""
    alpaca = _alpaca_for_entry(spot=100.0, strike=94.0, bid=0.20)
    ws = WheelStrategy(settings=_cfg(otm_mult=1.0, credit_mult=0.15), alpaca_client=alpaca)
    ws._vol_cache["CCJ"] = None

    assert ws.open_csp("CCJ") is not None
    alpaca.submit_option_order.assert_called_once()


def test_ev_gates_disabled_at_zero():
    alpaca = _alpaca_for_entry(spot=100.0, strike=94.0, bid=0.20)
    ws = WheelStrategy(settings=_cfg(otm_mult=0.0, credit_mult=0.0), alpaca_client=alpaca)
    ws._vol_cache["CCJ"] = 0.05          # would fail both gates if they were on

    assert ws.open_csp("CCJ") is not None


# ---------------------------------------------------------------------------
# Vol-aware strike selection — the selector must agree with the gate
# ---------------------------------------------------------------------------

def test_strike_selector_widens_for_a_volatile_name():
    """Without this the gate rejects what the selector proposes and nothing trades."""
    ws = WheelStrategy(settings=_cfg(otm_mult=1.0), alpaca_client=MagicMock())
    ws._vol_cache["RKLB"] = 0.0617                    # 14d 1-sigma on $73.39 ~ $16.94

    fixed_only = ws.select_csp_strike("RKLB", 73.39)             # no dte -> old behaviour
    vol_aware = ws.select_csp_strike("RKLB", 73.39, dte=14)
    assert fixed_only > vol_aware                                # vol pushed it further out
    assert vol_aware <= 73.39 - 16.94                            # at least 1 sigma OTM


def test_strike_selector_unchanged_for_a_quiet_name():
    """GEO already cleared 1 sigma at the fixed distance; don't move it."""
    ws = WheelStrategy(settings=_cfg(otm_mult=1.0), alpaca_client=MagicMock())
    ws._vol_cache["GEO"] = 0.0162                     # 14d 1-sigma on $31.94 ~ $1.93
    assert ws.select_csp_strike("GEO", 31.94, dte=14) == ws.select_csp_strike("GEO", 31.94)


def test_strike_selector_rounds_down_not_nearest():
    """Rounding up moves the strike toward spot — toward the risk the floor avoids."""
    ws = WheelStrategy(settings=_cfg(otm_mult=0.0), alpaca_client=MagicMock())
    strike = ws.select_csp_strike("X", 100.0)         # 100 * 0.9375 = 93.75
    assert strike == 93.5


def test_strike_selector_ignores_vol_when_unavailable():
    ws = WheelStrategy(settings=_cfg(otm_mult=1.0), alpaca_client=MagicMock())
    ws._vol_cache["X"] = None
    assert ws.select_csp_strike("X", 100.0, dte=14) == ws.select_csp_strike("X", 100.0)


def test_selector_output_clears_its_own_gate():
    """End-to-end: the strike the selector picks must survive gate 5b."""
    ws = WheelStrategy(settings=_cfg(otm_mult=1.0), alpaca_client=MagicMock())
    for ticker, spot, vol in [("KTOS", 56.24, 0.0376), ("RKLB", 73.39, 0.0617),
                              ("CCJ", 95.93, 0.0252), ("ABT", 113.98, 0.0251)]:
        ws._vol_cache[ticker] = vol
        strike = ws.select_csp_strike(ticker, spot, dte=14)
        exp_move = ws._expected_move(ticker, spot, 14)
        assert (spot - strike) >= 1.0 * exp_move, (ticker, spot, strike, exp_move)
