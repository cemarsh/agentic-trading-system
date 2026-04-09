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

        # Parse trade rows — structure may change; anneal if needed
        for row in soup.select("table tbody tr"):
            cells = [td.get_text(strip=True) for td in row.find_all("td")]
            if len(cells) < 6:
                continue

            politician_name = cells[0]
            if not any(t in politician_name.lower() for t in tracked):
                continue

            ticker = cells[2].upper()
            raw_value = cells[4].replace("$", "").replace(",", "").strip()
            trade_type = cells[3].lower()

            try:
                value = float(re.sub(r"[^\d.]", "", raw_value.split("–")[0]))
            except ValueError:
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
