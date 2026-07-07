"""
IV Tracker — Accumulates daily IV snapshots per ticker and computes IVR / IVP.

Runs once per day DURING MARKET HOURS (~10 AM ET) to snapshot current IV for
each ticker in the wheel + derivatives universe. The window matters: Alpaca's
indicative options feed is RTH-only, so a pre-market snapshot returns
"unavailable" for most names and silently stores nothing (the cause of the
sparse-history period Jun-Jul 2026). After MIN_HISTORY_DAYS of history, IVR
and IVP are usable as strategy gates; accuracy keeps improving toward a full
52-week window.

IVR (IV Rank)       = (current_IV - 52wk_low) / (52wk_high - 52wk_low)
IVP (IV Percentile) = % of trading days in past year where IV < today's IV

Falls back to Tradier API when Alpaca indicative feed is unavailable.

Usage:
    python execution/iv_tracker.py --snapshot       # record today's IV for all tickers
    python execution/iv_tracker.py --rank PLTR      # print IVR + IVP for a ticker
    python execution/iv_tracker.py --rank-all       # print IVR/IVP for all tickers
"""

import argparse
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import settings as cfg_module
from execution.daily_journal import log_insight

TRADIER_BASE = "https://api.tradier.com/v1"
ALPACA_DATA_BASE = "https://data.alpaca.markets"

# Minimum snapshots before IVR/IVP are considered usable. 15 ≈ three weeks of
# trading days — coarse but workable while history builds; the alternative (30)
# left the hard IV gate blocking every ticker for weeks on end.
MIN_HISTORY_DAYS = 15

# IV regime thresholds (used by strategy selector)
IVR_HIGH = 50      # ≥ this → sell premium aggressively
IVR_MID = 30       # 30–49 → sell premium conservatively
IVR_LOW = 25       # < this → buy premium / LEAPS
IVP_HIGH = 75      # ≥ this → confirms high IVR signal
IVP_LOW = 25       # < this → confirms low IVR signal


def _get_iv_from_alpaca(ticker: str, headers: dict) -> Optional[float]:
    """Fetch ATM IV from Alpaca options snapshot for the nearest expiry."""
    import requests
    try:
        # limit must be generous: contracts come back sorted by symbol (nearest
        # expiry, ascending strike), so a small limit returns only deep-ITM calls,
        # which carry no greeks/IV on the indicative feed. limit=10 yielded ZERO
        # usable contracts for RTX; limit=100 yields ~50.
        resp = requests.get(
            f"{ALPACA_DATA_BASE}/v1beta1/options/snapshots/{ticker}",
            headers=headers,
            params={"feed": "indicative", "limit": 100, "type": "call"},
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
        snapshots = data.get("snapshots", {})
        if not snapshots:
            return None
        # Pick the contract with delta closest to 0.50 (ATM proxy)
        best = None
        best_dist = float("inf")
        for symbol, snap in snapshots.items():
            greeks = snap.get("greeks") or {}
            delta = greeks.get("delta")
            iv = snap.get("impliedVolatility") or snap.get("implied_volatility")
            if delta is None or iv is None:
                continue
            dist = abs(abs(delta) - 0.50)
            if dist < best_dist:
                best_dist = dist
                best = iv
        return best
    except Exception as e:
        print(f"[IV] Alpaca snapshot failed for {ticker}: {e}")
        return None


def _get_iv_from_tradier(ticker: str, tradier_token: str) -> Optional[float]:
    """Fetch ATM IV from Tradier (ORATS-powered). Falls back when Alpaca unavailable."""
    import requests
    try:
        # Get nearest expiry
        exp_resp = requests.get(
            f"{TRADIER_BASE}/markets/options/expirations",
            headers={"Authorization": f"Bearer {tradier_token}", "Accept": "application/json"},
            params={"symbol": ticker, "includeAllRoots": "true", "strikes": "false"},
            timeout=10,
        )
        exp_resp.raise_for_status()
        expirations = exp_resp.json().get("expirations", {}).get("date", [])
        if not expirations:
            return None
        # Use first expiry that's 20+ DTE
        today = date.today()
        chosen_exp = None
        for exp in (expirations if isinstance(expirations, list) else [expirations]):
            exp_date = date.fromisoformat(str(exp))
            if (exp_date - today).days >= 20:
                chosen_exp = str(exp)
                break
        if not chosen_exp:
            return None

        chain_resp = requests.get(
            f"{TRADIER_BASE}/markets/options/chains",
            headers={"Authorization": f"Bearer {tradier_token}", "Accept": "application/json"},
            params={"symbol": ticker, "expiration": chosen_exp, "greeks": "true"},
            timeout=10,
        )
        chain_resp.raise_for_status()
        options = chain_resp.json().get("options", {}).get("option", [])
        if not options:
            return None
        # Pick ATM by delta closest to 0.50
        best_iv = None
        best_dist = float("inf")
        for opt in options:
            if opt.get("option_type") != "call":
                continue
            greeks = opt.get("greeks") or {}
            delta = greeks.get("delta")
            mid_iv = greeks.get("mid_iv") or opt.get("mid_iv")
            if delta is None or mid_iv is None:
                continue
            dist = abs(abs(float(delta)) - 0.50)
            if dist < best_dist:
                best_dist = dist
                best_iv = float(mid_iv)
        return best_iv
    except Exception as e:
        print(f"[IV] Tradier fallback failed for {ticker}: {e}")
        return None


def snapshot_all_tickers(settings=None, alpaca_headers: dict = None) -> dict:
    """
    Fetch current IV for all tickers in wheel + derivatives universe.
    Stores results in the iv_history Postgres table.
    Returns dict of {ticker: iv_value}.
    """
    cfg = settings or cfg_module.load()
    tickers = list(set(cfg.wheel.tickers))

    if alpaca_headers is None:
        alpaca_headers = {
            "APCA-API-KEY-ID": cfg.alpaca.key,
            "APCA-API-SECRET-KEY": cfg.alpaca.secret,
        }

    tradier_token = os.environ.get("TRADIER_API_TOKEN", "")
    today = date.today()
    results = {}

    for ticker in tickers:
        iv = _get_iv_from_alpaca(ticker, alpaca_headers)
        if iv is None and tradier_token:
            iv = _get_iv_from_tradier(ticker, tradier_token)
        if iv is not None:
            results[ticker] = round(float(iv), 6)
            print(f"[IV] {ticker:6s}  IV={iv:.4f}")
        else:
            print(f"[IV] {ticker:6s}  IV=unavailable")

    # Persist to Postgres
    if cfg.database.url and results:
        _store_snapshots(cfg.database.url, today, results)

    return results


def _store_snapshots(db_url: str, snapshot_date: date, iv_map: dict):
    """Upsert IV snapshots into the iv_history table."""
    import psycopg2
    try:
        with psycopg2.connect(db_url) as conn:
            with conn.cursor() as cur:
                for ticker, iv in iv_map.items():
                    cur.execute(
                        """
                        INSERT INTO iv_history (ticker, snapshot_date, iv_value)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (ticker, snapshot_date) DO UPDATE SET iv_value = EXCLUDED.iv_value
                        """,
                        (ticker, snapshot_date, iv),
                    )
            conn.commit()
        print(f"[IV] Stored {len(iv_map)} snapshots for {snapshot_date}")
    except Exception as e:
        print(f"[IV] DB store failed: {e}")


def get_iv_rank(ticker: str, db_url: str) -> dict:
    """
    Compute IVR and IVP for a ticker from stored history.

    Returns:
        {
            "ticker": str,
            "current_iv": float | None,
            "iv_rank": float | None,       # 0.0–1.0 (multiply by 100 for %)
            "iv_percentile": float | None,  # 0.0–1.0
            "history_days": int,
            "regime": str,  # "HIGH_IV" | "MID_IV" | "LOW_IV" | "TRANSITION" | "INSUFFICIENT_DATA"
        }
    """
    import psycopg2
    import psycopg2.extras
    result = {
        "ticker": ticker,
        "current_iv": None,
        "iv_rank": None,
        "iv_percentile": None,
        "history_days": 0,
        "regime": "INSUFFICIENT_DATA",
    }
    try:
        with psycopg2.connect(db_url) as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cutoff = date.today() - timedelta(days=365)
                cur.execute(
                    """
                    SELECT snapshot_date, iv_value
                    FROM iv_history
                    WHERE ticker = %s AND snapshot_date >= %s
                    ORDER BY snapshot_date DESC
                    """,
                    (ticker, cutoff),
                )
                rows = cur.fetchall()

        if not rows:
            return result

        ivs = [float(r["iv_value"]) for r in rows]
        current_iv = ivs[0]  # most recent
        result["current_iv"] = round(current_iv, 6)
        result["history_days"] = len(ivs)

        if len(ivs) < MIN_HISTORY_DAYS:
            result["regime"] = "INSUFFICIENT_DATA"
            return result

        iv_52w_high = max(ivs)
        iv_52w_low = min(ivs)
        denominator = iv_52w_high - iv_52w_low

        if denominator > 0:
            ivr = (current_iv - iv_52w_low) / denominator
            result["iv_rank"] = round(ivr, 4)
        else:
            result["iv_rank"] = 0.5  # flat IV environment

        ivp = sum(1 for iv in ivs if iv < current_iv) / len(ivs)
        result["iv_percentile"] = round(ivp, 4)

        ivr_pct = (result["iv_rank"] or 0) * 100
        ivp_pct = (result["iv_percentile"] or 0) * 100

        if ivr_pct >= IVR_HIGH and ivp_pct >= IVP_HIGH:
            result["regime"] = "HIGH_IV"
        elif ivr_pct < IVR_LOW and ivp_pct < IVP_LOW:
            result["regime"] = "LOW_IV"
        elif IVR_MID <= ivr_pct < IVR_HIGH:
            result["regime"] = "MID_IV"
        elif abs(ivr_pct - ivp_pct) > 20:
            result["regime"] = "TRANSITION"
        else:
            result["regime"] = "LOW_IV"

        return result

    except Exception as e:
        print(f"[IV] get_iv_rank failed for {ticker}: {e}")
        return result


def get_strategy_gate(ticker: str, db_url: str) -> str:
    """
    Returns a concise strategy recommendation based on IV rank.
    One of: 'SELL_AGGRESSIVE' | 'SELL_CONSERVATIVE' | 'SPREAD_ONLY' | 'BUY_PREMIUM' | 'SKIP'
    """
    iv_data = get_iv_rank(ticker, db_url)
    regime = iv_data.get("regime", "INSUFFICIENT_DATA")
    mapping = {
        "HIGH_IV": "SELL_AGGRESSIVE",
        "MID_IV": "SELL_CONSERVATIVE",
        "TRANSITION": "SPREAD_ONLY",
        "LOW_IV": "BUY_PREMIUM",
        "INSUFFICIENT_DATA": "SKIP",
    }
    return mapping.get(regime, "SKIP")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="IV Tracker — snapshot and rank options IV")
    parser.add_argument("--snapshot", action="store_true", help="Record today's IV for all tickers")
    parser.add_argument("--rank", type=str, help="Print IVR + IVP for a specific ticker")
    parser.add_argument("--rank-all", action="store_true", help="Print IVR + IVP for all tickers")
    args = parser.parse_args()

    cfg = cfg_module.load()

    if args.snapshot:
        results = snapshot_all_tickers(settings=cfg)
        print(f"[IV] Snapshot complete — {len(results)} tickers recorded")

    elif args.rank:
        if not cfg.database.url:
            print("[IV] DATABASE_URL not set")
            sys.exit(1)
        data = get_iv_rank(args.rank.upper(), cfg.database.url)
        print(f"\nIV Report — {data['ticker']}")
        print(f"  Current IV:    {data['current_iv']:.4f}" if data['current_iv'] else "  Current IV:    N/A")
        print(f"  IV Rank:       {(data['iv_rank'] or 0)*100:.1f}%")
        print(f"  IV Percentile: {(data['iv_percentile'] or 0)*100:.1f}%")
        print(f"  History:       {data['history_days']} days")
        print(f"  IV Regime:     {data['regime']}")
        print(f"  Gate:          {get_strategy_gate(args.rank.upper(), cfg.database.url)}")

    elif args.rank_all:
        if not cfg.database.url:
            print("[IV] DATABASE_URL not set")
            sys.exit(1)
        print(f"\n{'Ticker':8s} {'IVR%':7s} {'IVP%':7s} {'Days':6s} {'Regime':20s} {'Gate'}")
        print("-" * 70)
        for ticker in sorted(set(cfg.wheel.tickers)):
            data = get_iv_rank(ticker, cfg.database.url)
            ivr = f"{(data['iv_rank'] or 0)*100:.1f}%" if data['iv_rank'] is not None else "N/A"
            ivp = f"{(data['iv_percentile'] or 0)*100:.1f}%" if data['iv_percentile'] is not None else "N/A"
            gate = get_strategy_gate(ticker, cfg.database.url)
            print(f"{ticker:8s} {ivr:7s} {ivp:7s} {data['history_days']:6d} {data['regime']:20s} {gate}")
