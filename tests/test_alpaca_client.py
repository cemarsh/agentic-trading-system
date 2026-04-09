"""Tests for AlpacaClient — uses mocked HTTP responses."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))


def _mock_settings():
    cfg = MagicMock()
    cfg.alpaca.key = "test_key"
    cfg.alpaca.secret = "test_secret"
    cfg.alpaca.base_url = "https://paper-api.alpaca.markets"
    cfg.alpaca.paper_mode = True
    cfg.whale_watch.roc_lookback_minutes = 5
    return cfg


def test_compute_roc_positive():
    from execution.alpaca_client import AlpacaClient

    client = AlpacaClient(settings=_mock_settings())
    client.get_bars = MagicMock(
        return_value=[
            {"c": 100.0},
            {"c": 101.0},
            {"c": 102.0},
            {"c": 103.0},
            {"c": 105.0},
        ]
    )
    roc = client.compute_roc("AAPL", 5)
    assert roc == pytest.approx(5.0, rel=0.01)


def test_compute_roc_empty_bars():
    from execution.alpaca_client import AlpacaClient

    client = AlpacaClient(settings=_mock_settings())
    client.get_bars = MagicMock(return_value=[])
    roc = client.compute_roc("AAPL", 5)
    assert roc == 0.0


def test_compute_roc_zero_division():
    from execution.alpaca_client import AlpacaClient

    client = AlpacaClient(settings=_mock_settings())
    client.get_bars = MagicMock(return_value=[{"c": 0.0}, {"c": 100.0}])
    roc = client.compute_roc("AAPL", 1)
    assert roc == 0.0


import pytest
