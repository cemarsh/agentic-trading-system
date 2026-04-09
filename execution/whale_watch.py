"""
Whale Watch — Smart money surveillance via CapitalTrades.
Scrapes disclosed politician trades, filters by threshold,
cross-references ROC, and scores via confidence heuristic.
"""

import re
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import List, Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import settings as cfg_module


@dataclass
class WhaleTrade:
    politician: str
    ticker: str
    trade_value: float
    trade_date: date
    trade_type: str          # "purchase" | "sale"
    roc_pct: float = 0.0
    confidence: float = 0.0


class WhaleWatcher:
    def __init__(self, settings=None, alpaca_client=None):
        self.cfg = settings or cfg_module.load()
        self._alpaca = alpaca_client

    def fetch_recent_trades(self) -> List[WhaleTrade]:
        """
        Fetch recent disclosures from CapitalTrades.
        Uses requests + BeautifulSoup to parse the page.
        Returns trades matching tracked politician names.
        """
        import requests
        from bs4 import BeautifulSoup

        url = "https://www.capitoltrades.com/trades"
        headers = {"User-Agent": "Mozilla/5.0 (compatible; TradingBot/1.0)"}

        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")
        trades: List[WhaleTrade] = []

        tracked = [n.lower() for n in self.cfg.whale_watch.politician_names]

        def parse_name(raw: str) -> str:
            """Extract name before party affiliation."""
            for party in ("Democrat", "Republican", "Independent", "Libertarian"):
                if party in raw:
                    return raw.split(party)[0].strip()
            return raw.strip()

        def parse_ticker(raw: str) -> Optional[str]:
            """Extract ticker from 'Company NameTICKER:US' format."""
            m = re.search(r"([A-Z]{1,5}):US", raw)
            return m.group(1) if m else None

        def parse_value(raw: str) -> float:
            """Parse range like '1K–15K' or '100K–250K' to midpoint float."""
            def to_num(s: str) -> float:
                s = s.strip().upper().replace(",", "")
                if s.endswith("K"):
                    return float(s[:-1]) * 1_000
                if s.endswith("M"):
                    return float(s[:-1]) * 1_000_000
                return float(re.sub(r"[^\d.]", "", s) or "0")
            parts = re.split(r"[–\-]", raw)
            if len(parts) == 2:
                return (to_num(parts[0]) + to_num(parts[1])) / 2
            return to_num(parts[0])

        # Real layout (verified 2026-04-09):
        # cell[0]: "NamePartyChambeerState"
        # cell[1]: "Company NameTICKER:US"
        # cell[6]: trade type "buy"/"sell"
        # cell[7]: value range "1K–15K"
        for row in soup.select("table tbody tr"):
            cells = [td.get_text(strip=True) for td in row.find_all("td")]
            if len(cells) < 8:
                continue

            politician_name = parse_name(cells[0])
            if not any(t in politician_name.lower() for t in tracked):
                continue

            ticker = parse_ticker(cells[1])
            if not ticker:
                continue  # bonds, treasuries, etc. — skip non-equity

            trade_type = cells[6].lower().strip()
            if trade_type not in ("buy", "sell"):
                continue

            try:
                value = parse_value(cells[7])
            except (ValueError, IndexError):
                continue

            if value < self.cfg.whale_watch.whale_trade_min_value:
                continue

            trades.append(
                WhaleTrade(
                    politician=politician_name,
                    ticker=ticker,
                    trade_value=value,
                    trade_date=date.today(),
                    trade_type=trade_type,
                )
            )

        return trades

    def score_trade(self, trade: WhaleTrade) -> WhaleTrade:
        """Compute ROC and assign confidence score."""
        if self._alpaca:
            try:
                trade.roc_pct = self._alpaca.compute_roc(
                    trade.ticker, self.cfg.whale_watch.roc_lookback_minutes
                )
            except Exception:
                trade.roc_pct = 0.0

        # Confidence heuristic:
        # Base 0.5 + ROC contribution (max 0.3) + value contribution (max 0.2)
        roc_score = min(abs(trade.roc_pct) / 10, 0.3)
        value_score = min(trade.trade_value / 500_000, 0.2)
        direction_match = (trade.trade_type == "purchase" and trade.roc_pct > 0) or (
            trade.trade_type == "sale" and trade.roc_pct < 0
        )
        base = 0.5 if direction_match else 0.3

        trade.confidence = round(base + roc_score + value_score, 4)
        return trade

    def get_actionable_trades(self) -> List[WhaleTrade]:
        """Return trades that pass the minimum confidence threshold."""
        raw = self.fetch_recent_trades()
        scored = [self.score_trade(t) for t in raw]
        return [t for t in scored if t.confidence >= self.cfg.intelligence.min_confidence_score]
