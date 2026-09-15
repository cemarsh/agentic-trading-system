"""The weekly scan must price tickers outside regular trading hours.

It runs Monday pre-market (00:00-09:30 ET) and priced each ticker with
get_bars(ticker, "1Min", 1). That is empty before the open, so every ticker was
skipped every week and strategy_analysis never received a row.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests

sys.path.insert(0, str(Path(__file__).parent.parent))

from execution import strategy_advisor as sa
from execution.alpaca_client import AlpacaClient


def _settings(tickers=()):
    cfg = MagicMock()
    cfg.anthropic.api_key = "test-key"
    cfg.wheel.tickers = list(tickers)
    cfg.alpaca.key = "test_key"
    cfg.alpaca.secret = "test_secret"
    cfg.alpaca.base_url = "https://paper-api.alpaca.markets"
    return cfg


def _premarket_alpaca(prices):
    """A client as it looks before the open: no 1-minute bars, last trades available."""
    alpaca = MagicMock()
    alpaca.get_account.return_value = {"equity": "75000"}
    alpaca.get_bars.return_value = []
    alpaca.get_latest_price.side_effect = lambda t: prices.get(t, 0.0)
    return alpaca


# --- the scan -----------------------------------------------------------------

def test_scan_analyzes_tickers_before_the_open():
    alpaca = _premarket_alpaca({"GEO": 30.88, "CCJ": 101.5})
    analysis = {"recommendation": "WATCH", "conviction": 0.6, "primary_strategy": "wheel"}

    with patch.object(sa, "analyze_ticker", return_value=analysis) as analyze:
        sa.run_weekly_scan(alpaca, "NEUTRAL", settings=_settings(["GEO", "CCJ"]))

    assert [c.args[:2] for c in analyze.call_args_list] == [("GEO", 30.88), ("CCJ", 101.5)]


def test_scan_skips_only_tickers_with_no_price():
    alpaca = _premarket_alpaca({"GEO": 30.88})

    with patch.object(sa, "analyze_ticker", return_value={"recommendation": "AVOID"}) as analyze:
        sa.run_weekly_scan(alpaca, "NEUTRAL", settings=_settings(["GEO", "NOPE"]))

    assert [c.args[0] for c in analyze.call_args_list] == ["GEO"]


# --- AlpacaClient.get_latest_price --------------------------------------------

def test_latest_price_uses_the_last_trade():
    client = AlpacaClient(settings=_settings())
    client._get = MagicMock(return_value={"symbol": "GEO", "trade": {"p": 30.88}})
    client.get_bars = MagicMock()

    assert client.get_latest_price("GEO") == 30.88
    client.get_bars.assert_not_called()


def test_latest_price_falls_back_to_the_last_daily_close():
    client = AlpacaClient(settings=_settings())
    client._get = MagicMock(side_effect=requests.HTTPError("404 Not Found"))
    client.get_bars = MagicMock(return_value=[{"c": 30.10}, {"c": 30.85}])

    assert client.get_latest_price("GEO") == 30.85
    assert client.get_bars.call_args.args[1] == "1Day"
    assert client.get_bars.call_args.kwargs.get("start")  # without start, bars cover today only


def test_latest_price_is_zero_when_nothing_is_available():
    client = AlpacaClient(settings=_settings())
    client._get = MagicMock(return_value={"symbol": "GEO", "trade": None})
    client.get_bars = MagicMock(return_value=[])

    assert client.get_latest_price("GEO") == 0.0
