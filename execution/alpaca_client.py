"""
Alpaca Markets REST client wrapper.
All credential access goes through config/settings.py.
Usage:
    python execution/alpaca_client.py --verify
"""

import argparse
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config import settings as cfg_module


def _build_retry_session() -> requests.Session:
    """Session that transparently retries transient transport failures with
    exponential backoff, so a brief blip (the ConnectionReset(104) bursts that
    caused the Jun-2026 halt loop) never surfaces as an exception to count toward
    the halt threshold.

    Retries are scoped to GET/HEAD/OPTIONS only — order POSTs are NOT read-retried
    (a reset mid-submit could double-fill). Connection-*establishment* failures are
    still retried for all methods (the request never reached the server, so it's safe).
    """
    retry = Retry(
        total=4,
        connect=4,
        read=3,
        status=3,
        backoff_factor=1.0,  # sleeps ~0, 1, 2, 4s between attempts
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET", "HEAD", "OPTIONS"]),
        raise_on_status=False,
        respect_retry_after_header=True,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session = requests.Session()
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


class AlpacaClient:
    def __init__(self, settings=None):
        self.cfg = settings or cfg_module.load()
        self._headers = {
            "APCA-API-KEY-ID": self.cfg.alpaca.key,
            "APCA-API-SECRET-KEY": self.cfg.alpaca.secret,
        }
        self.base_url = self.cfg.alpaca.base_url
        self.data_url = "https://data.alpaca.markets"
        self._session = _build_retry_session()

    def _get(self, path: str, params: dict = None, data_api: bool = False) -> dict:
        base = self.data_url if data_api else self.base_url
        resp = self._session.get(f"{base}{path}", headers=self._headers, params=params, timeout=20)
        resp.raise_for_status()
        return resp.json()

    def _post(self, path: str, body: dict) -> dict:
        resp = self._session.post(
            f"{self.base_url}{path}",
            headers={**self._headers, "Content-Type": "application/json"},
            json=body,
            timeout=20,
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
        return data.get("bars") or []

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

    def get_clock(self) -> dict:
        """Returns market clock: is_open, next_open, next_close (ISO strings)."""
        return self._get("/v2/clock")

    def get_open_orders(self) -> list:
        """All currently open/working orders (used to avoid double-submitting)."""
        return self._get("/v2/orders", params={"status": "open", "limit": 500})

    def get_option_quote(self, symbol: str) -> Optional[dict]:
        """Latest NBBO for an option contract. Returns {'bid','ask','mid'} or None.
        Used to price rolls/closes off the *real* market instead of an estimate."""
        try:
            data = self._get(
                "/v1beta1/options/quotes/latest",
                params={"symbols": symbol},
                data_api=True,
            )
            q = (data.get("quotes") or {}).get(symbol)
            if not q:
                return None
            bid = float(q.get("bp", 0) or 0)
            ask = float(q.get("ap", 0) or 0)
            mid = (bid + ask) / 2 if (bid and ask) else (ask or bid)
            return {"bid": bid, "ask": ask, "mid": mid}
        except Exception:
            return None

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
