"""
IPO Calendar — broadens the system's senses beyond the fixed wheel universe.

Source: SEC EDGAR full-text search (keyless, official). Nasdaq's IPO calendar API
is IP-blocked from servers, so we detect IPOs from recent 424B4 filings (the final
prospectus filed at/around pricing), filtered to genuine IPOs.

For each fresh IPO we check Alpaca tradability + options availability, persist a
research brief + an (actionable) trading_signal, journal it, and return a
newly-public watchlist the rest of the system can consider.

Usage:
    python execution/ipo_calendar.py --scan        # fetch + persist recent IPOs
    python execution/ipo_calendar.py --dry          # fetch + print, no writes
"""
import argparse
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

import requests

from config import settings as cfg_module
from execution.daily_journal import log_insight

EDGAR_FTS = "https://efts.sec.gov/LATEST/search-index"
# SEC requires a descriptive UA with contact per their fair-access policy.
EDGAR_HEADERS = {"User-Agent": "cmtg-trading-research chris@cloudmagicgroup.com"}
# (Company (TICKER) (CIK 000...))  — TICKER is 1-5 upper-alphanum, optional dots.
_TICKER_RE = re.compile(r"\(([A-Z][A-Z0-9.]{0,5})\)")
# Blank-check / SPAC shells file 424B4 too — flag (not real operating-company IPOs).
_SPAC_RE = re.compile(r"acquisition (corp|co\b|company|holdings)|blank check|\bSPAC\b", re.I)
# A genuinely-new listing has only days of price history; an established company
# filing a secondary (e.g. CEG) has years. This many daily bars ⇒ not a fresh IPO.
ESTABLISHED_BARS = 30


def _is_spac(name: str) -> bool:
    return bool(_SPAC_RE.search(name or ""))


def fetch_recent_ipos(days: int = 14) -> list:
    """Recent IPO prospectus (424B4) filings from EDGAR, newest first.

    Returns list of dicts: {ticker, company, file_date, cik, form}. Tickerless
    filings (true greenfield IPOs not yet assigned a symbol in EDGAR) are dropped
    here — they aren't tradable yet, so they're awareness-only and we skip them.
    """
    end = date.today()
    start = end - timedelta(days=days)
    params = {
        "forms": "424B4",
        "q": '"initial public offering"',
        "startdt": start.isoformat(),
        "enddt": end.isoformat(),
        "dateRange": "custom",
    }
    # EDGAR rate-limits (~10 req/s) and intermittently 403/empties — retry so a
    # transient block doesn't silently masquerade as "0 IPOs today".
    hits = None
    last_err = None
    for attempt in range(3):
        try:
            r = requests.get(EDGAR_FTS, params=params, headers=EDGAR_HEADERS, timeout=20)
            r.raise_for_status()
            hits = r.json().get("hits", {}).get("hits", [])
            break
        except Exception as e:
            last_err = e
            time.sleep(2 * (attempt + 1))
    if hits is None:
        raise RuntimeError(f"EDGAR IPO fetch failed after 3 attempts: {last_err}")

    out, seen = [], set()
    for h in hits:
        src = h.get("_source", {})
        names = src.get("display_names") or []
        if not names:
            continue
        disp = names[0]
        m = _TICKER_RE.search(disp)
        if not m:
            continue  # no ticker → not tradable → skip
        ticker = m.group(1).rstrip(".")
        if ticker in seen:
            continue
        seen.add(ticker)
        company = re.sub(r"\s*\(.*$", "", disp).strip()
        out.append({
            "ticker": ticker,
            "company": company,
            "file_date": src.get("file_date"),
            "cik": (src.get("cik") or [None])[0] if isinstance(src.get("cik"), list) else src.get("cik"),
            "form": src.get("file_type", "424B4"),
        })
    out.sort(key=lambda x: x.get("file_date") or "", reverse=True)
    return out


def enrich_tradability(ipos: list, alpaca) -> list:
    """Annotate each IPO with Alpaca tradability, newly-public verification (price
    history length), options availability, and SPAC flag."""
    for ipo in ipos:
        t = ipo["ticker"]
        tradable = has_options = False
        newly_public = True  # default: assume new unless history proves established
        try:
            asset = alpaca._get(f"/v2/assets/{t}")
            tradable = bool(asset.get("tradable")) and asset.get("status") == "active"
        except Exception:
            tradable = False
        if tradable:
            try:
                # Need an explicit start to get history on the free feed (limit alone
                # returns only the latest bar). 90d lookback: established names return
                # ~60 daily bars, a fresh IPO returns a handful.
                lookback = (date.today() - timedelta(days=90)).isoformat()
                bars = alpaca.get_bars(t, "1Day", 200, start=lookback)
                ipo["trading_days"] = len(bars)
                newly_public = len(bars) < ESTABLISHED_BARS  # CEG (~60) -> False, SPCX (1) -> True
            except Exception:
                ipo["trading_days"] = None
            try:
                has_options = len(alpaca.get_options_contracts(t)) > 0
            except Exception:
                has_options = False
        ipo["alpaca_tradable"] = tradable
        ipo["newly_public"] = newly_public
        ipo["has_options"] = has_options
        ipo["is_spac"] = _is_spac(ipo["company"])
    return ipos


class IPOCalendar:
    def __init__(self, settings=None, alpaca_client=None, db_logger=None, notifier=None):
        self.cfg = settings or cfg_module.load()
        self._alpaca = alpaca_client
        self._db = db_logger
        self._notifier = notifier

    def scan(self, days: int = 14, persist: bool = True) -> dict:
        """Fetch recent IPOs, enrich, persist, journal. Returns a summary +
        watchlist of Alpaca-tradable newly-public names."""
        try:
            ipos = fetch_recent_ipos(days)
        except Exception as e:
            # Loud, not silent: a fetch failure must not look like "no IPOs".
            print(f"[IPO] scan aborted — {e}")
            log_insight(source="ipo", category="error",
                        insight=f"IPO scan failed (EDGAR unreachable): {e}", metadata={})
            return {"error": str(e), "ipos": [], "watchlist": [], "optionable": []}
        if self._alpaca and ipos:
            ipos = enrich_tradability(ipos, self._alpaca)

        # Actionable watchlist: genuinely-new, non-SPAC, tradable operating companies.
        watchlist = [
            i["ticker"] for i in ipos
            if i.get("alpaca_tradable") and i.get("newly_public") and not i.get("is_spac")
        ]
        optionable = [i["ticker"] for i in ipos if i.get("has_options") and i["ticker"] in watchlist]

        print(f"[IPO] {len(ipos)} 424B4 filing(s); watchlist (new, non-SPAC, tradable): "
              f"{len(watchlist)}; with options: {len(optionable)}")
        for i in ipos:
            if i.get("is_spac"):
                flags = "SPAC"
            elif not i.get("alpaca_tradable"):
                flags = "not-listed"
            elif not i.get("newly_public"):
                flags = "established(skip)"
            else:
                flags = "WATCH" + ("+options" if i.get("has_options") else "")
            print(f"[IPO]   {i['ticker']:6s} {i['file_date']}  {i['company'][:38]:38s} [{flags}]")

        if persist:
            self._persist(ipos, watchlist, optionable)
        return {"ipos": ipos, "watchlist": watchlist, "optionable": optionable}

    def _persist(self, ipos: list, watchlist: list, optionable: list) -> None:
        if not ipos:
            return
        # Journal every fresh IPO (awareness); these surface in the daily wrap-up.
        for i in ipos:
            log_insight(
                source="ipo",
                category="signal",
                insight=(f"IPO: {i['company']} ({i['ticker']}) priced {i['file_date']} — "
                         f"{'tradable on Alpaca' if i.get('alpaca_tradable') else 'not yet on Alpaca'}"
                         f"{', options available' if i.get('has_options') else ''}"),
                metadata=i,
            )
        if not self._db:
            return
        # One research_brief summarizing the batch + a trading_signal per ACTIONABLE
        # (tradable) name so the consumer can pick them up.
        try:
            self._db.log_ipo_scan(ipos, watchlist, optionable)
        except Exception as e:
            print(f"[IPO] DB persist failed: {e}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--scan", action="store_true")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--days", type=int, default=14)
    args = ap.parse_args()
    cfg = cfg_module.load()
    alpaca = db = None
    try:
        from execution.alpaca_client import AlpacaClient
        alpaca = AlpacaClient(settings=cfg)
    except Exception as e:
        print(f"[IPO] Alpaca unavailable: {e}")
    if args.scan and cfg.database.url:
        from execution.db_logger import DBLogger
        db = DBLogger(settings=cfg)
    cal = IPOCalendar(settings=cfg, alpaca_client=alpaca, db_logger=db)
    cal.scan(days=args.days, persist=args.scan and not args.dry)
