"""Correlation-aware universe screening (2026-08-21)."""

import math
import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

from execution.universe_screen import (
    correlation,
    max_correlation_to_book,
    screen_ticker,
    build_book_returns,
    run_screen,
)


def _cfg(max_corr=0.60, max_spread=25.0, seed=("BAC",), enabled=True):
    cfg = MagicMock()
    cfg.universe.enabled = enabled
    cfg.universe.max_correlation = max_corr
    cfg.universe.correlation_lookback_days = 60
    cfg.universe.max_spread_pct = max_spread
    cfg.universe.max_new_per_run = 4
    cfg.universe.max_promoted = 12
    cfg.universe.seed_pool = list(seed)
    cfg.wheel.tickers = ["KTOS"]
    cfg.wheel.target_delta = 0.25
    cfg.wheel.expiration_weeks = 2
    cfg.wheel.max_portfolio_pct_per_trade = 15.0
    return cfg


def _series(n=60, seed=1.0, flip=False):
    """Deterministic pseudo-returns; flip inverts for a negative correlation."""
    out = []
    for i in range(n):
        v = math.sin(i * seed) * 0.01
        out.append(-v if flip else v)
    return out


# ---------------------------------------------------------------------------
# Correlation
# ---------------------------------------------------------------------------

def test_identical_series_correlate_at_one():
    s = _series()
    assert abs(correlation(s, s) - 1.0) < 1e-9


def test_inverted_series_correlate_at_minus_one():
    s = _series()
    assert abs(correlation(s, _series(flip=True)) + 1.0) < 1e-9


def test_correlation_none_when_series_too_short():
    assert correlation([0.1, 0.2], [0.1, 0.2]) is None


def test_correlation_none_on_flat_series():
    assert correlation([0.0] * 40, _series(40)) is None


def test_max_correlation_uses_worst_not_average():
    """Uncorrelated to nine holdings and 0.9 to the tenth is a concentration risk."""
    cand = _series()
    book = {
        "AAA": _series(seed=2.7),      # something else
        "BBB": _series(seed=1.0),      # identical -> 1.0
    }
    worst, with_t = max_correlation_to_book(cand, book)
    assert with_t == "BBB"
    assert worst > 0.99


def test_max_correlation_keeps_sign_so_hedges_are_not_rejected():
    """A strongly NEGATIVE correlation is a diversifier, not a concentration."""
    worst, _ = max_correlation_to_book(_series(), {"AAA": _series(flip=True)})
    assert worst < 0


def test_max_correlation_empty_book():
    worst, with_t = max_correlation_to_book(_series(), {})
    assert worst is None and with_t is None


# ---------------------------------------------------------------------------
# Book construction
# ---------------------------------------------------------------------------

def test_book_returns_maps_options_to_underlying():
    alpaca = MagicMock()
    alpaca.get_bars.return_value = [{"c": 100 + i} for i in range(70)]
    cfg = _cfg()
    positions = [
        {"symbol": "KTOS260904P00052000"},
        {"symbol": "FJET"},
    ]
    book = build_book_returns(alpaca, cfg, positions)
    assert set(book) == {"KTOS", "FJET"}      # the option resolved to its underlying


# ---------------------------------------------------------------------------
# Screening
# ---------------------------------------------------------------------------

def _alpaca(price=45.0, bid=0.50, ask=0.55, puts=True, bars=70):
    a = MagicMock()

    def _bars(ticker, tf, limit, start=None):
        if tf == "1Min":
            return [{"c": price}]
        return [{"c": 100 * (1 + 0.001 * ((i * 7) % 11 - 5))} for i in range(bars)]

    a.get_bars.side_effect = _bars
    a.get_options_contracts.return_value = (
        [{"type": "put", "strike_price": "42.0", "symbol": "X260904P00042000"}] if puts else []
    )
    a.get_option_quote.return_value = {"bid": bid, "ask": ask}
    return a


def test_rejects_when_one_contract_exceeds_the_cap():
    v = screen_ticker(_alpaca(price=200.0), "MU", _cfg(), {}, per_trade_cap=12_559)
    assert not v["ok"] and "collateral" in v["reason"]


def test_rejects_a_candidate_correlated_to_the_book():
    cand_book = {"KTOS": _series(seed=1.0)}
    a = _alpaca()
    # Force the candidate's series to match the book's exactly.
    import execution.universe_screen as us
    orig = us.daily_log_returns
    us.daily_log_returns = lambda c, t, d: _series(seed=1.0)
    try:
        v = screen_ticker(a, "RKLB", _cfg(max_corr=0.60), cand_book, per_trade_cap=99_999)
    finally:
        us.daily_log_returns = orig
    assert not v["ok"] and "corr" in v["reason"]


def test_accepts_an_uncorrelated_candidate():
    import execution.universe_screen as us
    orig = us.daily_log_returns
    us.daily_log_returns = lambda c, t, d: _series(flip=True)
    try:
        v = screen_ticker(_alpaca(), "KO", _cfg(), {"KTOS": _series()}, per_trade_cap=99_999)
    finally:
        us.daily_log_returns = orig
    assert v["ok"], v["reason"]
    assert v["corr"] < 0


def test_rejects_a_wide_spread():
    v = screen_ticker(_alpaca(bid=0.10, ask=0.90), "T", _cfg(max_spread=25.0), {},
                      per_trade_cap=99_999)
    assert not v["ok"] and "spread" in v["reason"]


def test_rejects_when_no_puts_at_the_expiry():
    v = screen_ticker(_alpaca(puts=False), "O", _cfg(), {}, per_trade_cap=99_999)
    assert not v["ok"] and "no puts" in v["reason"]


def test_rejects_one_sided_market():
    v = screen_ticker(_alpaca(bid=0.0, ask=0.9), "WBD", _cfg(), {}, per_trade_cap=99_999)
    assert not v["ok"] and "two-sided" in v["reason"]


def test_rejects_short_price_history():
    v = screen_ticker(_alpaca(bars=5), "NEWCO", _cfg(), {}, per_trade_cap=99_999)
    assert not v["ok"] and "history" in v["reason"]


# ---------------------------------------------------------------------------
# Market-hours guard
# ---------------------------------------------------------------------------

def test_refuses_to_run_when_the_market_is_closed():
    """Stale after-hours quotes made the screen reject KO, T and SBUX as illiquid."""
    a = MagicMock()
    a.get_clock.return_value = {"is_open": False}
    result = run_screen(alpaca_client=a, settings=_cfg())
    assert result["passed"] == [] and result.get("skipped") == "market closed"
    a.get_account.assert_not_called()


def test_allow_closed_overrides_the_guard():
    a = _alpaca()
    a.get_clock.return_value = {"is_open": False}
    a.get_account.return_value = {"equity": "83724"}
    a.get_positions.return_value = []
    result = run_screen(alpaca_client=a, settings=_cfg(seed=()), allow_closed=True)
    assert "skipped" not in result


def test_disabled_screen_is_a_noop():
    a = MagicMock()
    result = run_screen(alpaca_client=a, settings=_cfg(enabled=False))
    assert result == {"passed": [], "rejected": []}
    a.get_clock.assert_not_called()
