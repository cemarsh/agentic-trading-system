"""
Derivatives Signals — IV-rank-based premium environment per ticker.

Our Alpaca data tier exposes implied volatility (via iv_tracker -> iv_history)
but NOT options volume / open interest, so this covers the actionable derivatives
input for a premium-selling wheel: IV rank. It classifies each name's premium
environment (rich / normal / cheap), journals it, and persists 'rich' names as
derivatives trading_signals (best CSP/CC candidates right now). It pairs with the
wheel's IV-rank entry gate (wheel.min_iv_rank).

LIMITATION: unusual-options-flow (volume/OI sweeps) needs a paid feed. iv_tracker
already has a Tradier path — add a TRADIER_TOKEN to light up full options-flow.

Usage:
    python execution/derivatives_signals.py --scan
    python execution/derivatives_signals.py --dry
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import settings as cfg_module
from execution.daily_journal import log_insight
from execution.iv_tracker import get_iv_rank

RICH_IVR = 0.50   # IV rank at/above this ⇒ rich premium (favorable to sell)
CHEAP_IVR = 0.20  # at/below this ⇒ cheap premium (unfavorable to sell)


def classify(ivr) -> str:
    if ivr is None:
        return "unknown"
    if ivr >= RICH_IVR:
        return "rich"
    if ivr <= CHEAP_IVR:
        return "cheap"
    return "normal"


class DerivativesSignals:
    def __init__(self, settings=None, db_logger=None):
        self.cfg = settings or cfg_module.load()
        self._db = db_logger

    def scan(self, tickers: list, persist: bool = True) -> dict:
        db_url = self.cfg.database.url if getattr(self.cfg, "database", None) else None
        results = []
        for t in tickers:
            ivr = None
            if db_url:
                try:
                    ivr = get_iv_rank(t, db_url).get("iv_rank")
                except Exception:
                    ivr = None
            results.append({"ticker": t, "iv_rank": ivr, "premium_environment": classify(ivr)})

        rich = [r for r in results if r["premium_environment"] == "rich"]
        cheap = [r for r in results if r["premium_environment"] == "cheap"]
        print(f"[DERIV] scanned {len(tickers)}: {len(rich)} rich, {len(cheap)} cheap premium")

        for r in results:
            if r["premium_environment"] in ("rich", "cheap"):
                ivr_pct = (r["iv_rank"] or 0) * 100
                log_insight(
                    source="derivatives", category="signal",
                    insight=f"{r['ticker']} IV rank {ivr_pct:.0f}% — {r['premium_environment']} premium",
                    metadata=r,
                )

        if persist and self._db and rich:
            try:
                self._db.log_derivatives_signals(rich)
            except Exception as e:
                print(f"[DERIV] persist failed: {e}")

        return {
            "results": results,
            "rich": [r["ticker"] for r in rich],
            "cheap": [r["ticker"] for r in cheap],
        }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--scan", action="store_true")
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()
    cfg = cfg_module.load()
    db = None
    if args.scan and cfg.database.url:
        from execution.db_logger import DBLogger
        db = DBLogger(settings=cfg)
    ds = DerivativesSignals(settings=cfg, db_logger=db)
    out = ds.scan(list(cfg.wheel.tickers), persist=args.scan and not args.dry)
    print("rich:", out["rich"], "| cheap:", out["cheap"])
