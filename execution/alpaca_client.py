"""
Alpaca Markets REST client wrapper.
All credential access goes through config/settings.py.
Usage:
    python execution/alpaca_client.py --verify
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import requests
from config import settings as cfg_module


class AlpacaClient:
    def __init__(self, settings=None):
        self.cfg = settings or cfg_module.load()
        self._headers = {
            "APCA-API-KEY-ID": self.cfg.alpaca.key,
            "APCA-API-SECRET-KEY": self.cfg.alpaca.secret,
        }
        self.base_url = self.cfg.alpaca.base_url
        self.data_url = "https://data.alpaca.markets"

    def _get(self, path: str, params: dict = None, data_api: bool = False) -> dict:
        base = self.data_url if data_api else self.base_url
        resp = requests.get(f"{base}{path}", headers=self._headers, params=params, timeout=10)
        resp.raise_for_status()
        return resp.json()

    def _post(self, path: str, body: dict) -> dict:
        resp = requests.post(
            f"{self.base_url}{path}",
            headers={**self._headers, "Content-Type": "application/json"},
            json=body,
            timeout=10,
        )
        if not resp.ok:
            try:
                detail = resp.json()
            except Exception:
                detail = resp.text
            raise requests.HTTPError(
                f"{resp.status_code} {resp.reason} — {detail} — url: {resp.url}",
                response=resp,
            )
        return resp.json()

    def get_account(self) -> dict:
        return self._get("/v2/account")

    def get_positions(self) -> list:
        return self._get("/v2/positions")

    def get_bars(self, ticker: str, timeframe: str = "1Min", limit: int = 10) -> list:
        data = self._get(
            f"/v2/stocks/{ticker}/bars",
            params={"timeframe": timeframe, "limit": limit},
            data_api=True,
        )
        return data.get("bars", [])

    def submit_order(
        self,
        ticker: str,
        qty: int,
        side: str,
        order_type: str = "market",
        time_in_force: str = "day",
        limit_price: float = None,
    ) -> dict:
        body = {
            "symbol": ticker,
            "qty": qty,
            "side": side,
            "type": order_type,
            "time_in_force": time_in_force,
        }
        if limit_price:
            body["limit_price"] = str(limit_price)
        return self._post("/v2/orders", body)

    def get_options_contracts(self, underlying: str, expiration_date: str = None) -> list:
        params = {"underlying_symbols": underlying}
        if expiration_date:
            params["expiration_date"] = expiration_date
        data = self._get("/v2/options/contracts", params=params)
        return data.get("option_contracts", [])

    def submit_option_order(
        self,
        symbol: str,
        qty: int,
        side: str,
        order_type: str = "market",
        limit_price: float = None,
    ) -> dict:
        body = {
            "symbol": symbol,
            "qty": qty,
            "side": side,
            "type": order_type,
            "time_in_force": "day",
        }
        if limit_price:
            body["limit_price"] = str(limit_price)
        return self._post("/v2/orders", body)

    def compute_roc(self, ticker: str, lookback_minutes: int = 5) -> float:
        """Rate of Change over lookback_minutes 1-min bars."""
        bars = self.get_bars(ticker, "1Min", lookback_minutes + 1)
        if len(bars) < 2:
            return 0.0
        oldest_close = bars[0]["c"]
        newest_close = bars[-1]["c"]
        if oldest_close == 0:
            return 0.0
        return (newest_close - oldest_close) / oldest_close * 100


def verify():
    """Standalone verify — reads ALPACA_* env vars directly, no full settings required."""
    import os
    from types import SimpleNamespace

    key = os.environ.get("ALPACA_KEY")
    secret = os.environ.get("ALPACA_SECRET")
    base_url = os.environ.get("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")

    if not key or not secret:
        print("[FAIL] Alpaca API — ALPACA_KEY and ALPACA_SECRET not set in environment")
        return False

    stub = SimpleNamespace(
        alpaca=SimpleNamespace(key=key, secret=secret, base_url=base_url, paper_mode="paper" in base_url)
    )

    try:
        client = AlpacaClient(settings=stub)
        account = client.get_account()
        mode = "PAPER" if stub.alpaca.paper_mode else "LIVE"
        print(f"[OK] Alpaca API — connected ({mode})")
        print(f"     Account ID:    {account.get('id', '?')}")
        print(f"     Equity:        ${float(account.get('equity', 0)):,.2f}")
        print(f"     Buying Power:  ${float(account.get('buying_power', 0)):,.2f}")
        print(f"     Status:        {account.get('status', '?')}")
        return True
    except Exception as e:
        print(f"[FAIL] Alpaca API — {e}")
        return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    if args.verify:
        ok = verify()
        sys.exit(0 if ok else 1)
