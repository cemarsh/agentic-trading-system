"""
Earnings calendar gate — kills the "CSP expiring on earnings day" failure class
(the CCJ expiry-on-earnings collision). One API call per ticker per day.

Data source: Finnhub /calendar/earnings (free tier is plenty at our volume).
Set FINNHUB_API_KEY in .env. Without a key the module returns None (unknown) and
callers fail OPEN with a logged warning — the gate can't block on data we don't
have, but it should be loud that it isn't protecting us.

Results are cached per ticker per day in logs/earnings_cache.json so the wheel's
per-cycle scans don't hammer the API.

Usage:
    from execution.earnings_calendar import has_earnings_before
    verdict = has_earnings_before("CCJ", "2026-07-24")   # True / False / None
"""

import json
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import List, Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

import requests

CACHE_PATH = Path("logs/earnings_cache.json")
FINNHUB_URL = "https://finnhub.io/api/v1/calendar/earnings"
LOOKAHEAD_DAYS = 60  # how far out to fetch earnings dates

_warned_no_key = False


def _api_key() -> str:
    return os.environ.get("FINNHUB_API_KEY", "")


def _load_cache() -> dict:
    try:
        if CACHE_PATH.exists():
            return json.loads(CACHE_PATH.read_text())
    except Exception:
        pass
    return {}


def _save_cache(cache: dict) -> None:
    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(json.dumps(cache, indent=2))
    except Exception:
        pass


def upcoming_earnings(ticker: str) -> Optional[List[str]]:
    """ISO dates of earnings events in the next LOOKAHEAD_DAYS for `ticker`.
    Returns None when the calendar is unavailable (no key / API error)."""
    global _warned_no_key
    key = _api_key()
    if not key:
        if not _warned_no_key:
            print("[EARNINGS] FINNHUB_API_KEY not set — earnings gate is NOT protecting trades (fail-open)")
            _warned_no_key = True
        return None

    today = date.today().isoformat()
    cache = _load_cache()
    entry = cache.get(ticker)
    if entry and entry.get("fetched") == today:
        return entry.get("dates", [])

    try:
        resp = requests.get(
            FINNHUB_URL,
            params={
                "from": today,
                "to": (date.today() + timedelta(days=LOOKAHEAD_DAYS)).isoformat(),
                "symbol": ticker,
                "token": key,
            },
            timeout=15,
        )
        resp.raise_for_status()
        events = resp.json().get("earningsCalendar") or []
        dates = sorted({e.get("date") for e in events if e.get("date")})
    except Exception as e:
        print(f"[EARNINGS] fetch failed for {ticker}: {e}")
        return None

    cache[ticker] = {"fetched": today, "dates": dates}
    _save_cache(cache)
    return dates


def has_earnings_before(ticker: str, expiry_iso: str) -> Optional[bool]:
    """True if `ticker` reports earnings on/before `expiry_iso` (a short option
    spanning that date carries binary event risk). False if clear. None if unknown."""
    dates = upcoming_earnings(ticker)
    if dates is None:
        return None
    try:
        expiry = date.fromisoformat(expiry_iso)
    except ValueError:
        return None
    today = date.today()
    for d in dates:
        try:
            ed = date.fromisoformat(d)
        except ValueError:
            continue
        if today <= ed <= expiry:
            return True
    return False


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("ticker")
    p.add_argument("--before", default=(date.today() + timedelta(days=21)).isoformat())
    args = p.parse_args()
    print(f"upcoming: {upcoming_earnings(args.ticker)}")
    print(f"earnings before {args.before}: {has_earnings_before(args.ticker, args.before)}")
