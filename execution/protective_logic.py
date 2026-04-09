"""
Protective Logic — trailing stops, gap protection, ladder buying.
Applied to all equity positions on each loop tick.
"""

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import settings as cfg_module


@dataclass
class EquityPosition:
    ticker: str
    qty: int
    entry_price: float
    high_water_mark: float
    stop_price: float


class ProtectiveLogic:
    def __init__(self, settings=None, alpaca_client=None, db_logger=None):
        self.cfg = settings or cfg_module.load()
        self._alpaca = alpaca_client
        self._db = db_logger
        self._positions: Dict[str, EquityPosition] = {}
        self._ladder_counts: Dict[str, int] = {}

    def sync_positions(self, alpaca_positions: list):
        """Sync internal state from live Alpaca position data."""
        prot = self.cfg.protection
        for p in alpaca_positions:
            ticker = p["symbol"]
            qty = int(p["qty"])
            current_price = float(p.get("current_price", p.get("avg_entry_price", 0)))
            entry = float(p.get("avg_entry_price", current_price))

            if ticker not in self._positions:
                stop = entry * (1 - prot.trailing_stop_pct / 100)
                self._positions[ticker] = EquityPosition(
                    ticker=ticker,
                    qty=qty,
                    entry_price=entry,
                    high_water_mark=current_price,
                    stop_price=stop,
                )
            else:
                pos = self._positions[ticker]
                if current_price > pos.high_water_mark:
                    pos.high_water_mark = current_price
                    pos.stop_price = current_price * (1 - prot.trailing_stop_pct / 100)

    def check_stops(self, current_prices: Dict[str, float]) -> List[str]:
        """Return list of tickers that have hit their trailing stop."""
        triggered = []
        for ticker, pos in self._positions.items():
            price = current_prices.get(ticker)
            if price is None:
                continue
            if price <= pos.stop_price:
                print(f"[STOP] {ticker} hit trailing stop — price ${price:.2f} <= stop ${pos.stop_price:.2f}")
                triggered.append(ticker)
        return triggered

    def apply_gap_tighten(self, tickers_at_risk: List[str]):
        """Tighten trailing stop on tickers flagged for gap-down risk."""
        prot = self.cfg.protection
        for ticker in tickers_at_risk:
            if ticker in self._positions:
                pos = self._positions[ticker]
                extra = prot.gap_tighten_pct / 100
                pos.stop_price = pos.high_water_mark * (1 - prot.trailing_stop_pct / 100 - extra)
                print(f"[GAP] {ticker} stop tightened to ${pos.stop_price:.2f}")

    def check_ladder(self, ticker: str, current_price: float) -> bool:
        """Returns True if a ladder buy should be triggered."""
        if ticker not in self._positions:
            return False
        pos = self._positions[ticker]
        prot = self.cfg.protection
        drop_pct = (pos.entry_price - current_price) / pos.entry_price * 100
        return drop_pct >= prot.ladder_drop_pct

    def execute_ladder(self, ticker: str) -> Optional[dict]:
        """Submit a ladder buy order."""
        if not self._alpaca:
            return None
        prot = self.cfg.protection
        order = self._alpaca.submit_order(
            ticker=ticker,
            qty=prot.ladder_buy_shares,
            side="buy",
            order_type="market",
        )
        self._ladder_counts[ticker] = self._ladder_counts.get(ticker, 0) + 1
        if self._db:
            self._db.log_decision(
                ticker=ticker,
                action="BUY",
                tier="protection",
                confidence=1.0,
                reasoning=f"Ladder buy #{self._ladder_counts[ticker]} — drawdown >= {prot.ladder_drop_pct}%",
                order_id=order.get("id"),
                status="pending",
            )
        return order

    def execute_stop(self, ticker: str) -> Optional[dict]:
        """Market sell the full position at stop."""
        if not self._alpaca or ticker not in self._positions:
            return None
        pos = self._positions[ticker]
        order = self._alpaca.submit_order(
            ticker=ticker,
            qty=pos.qty,
            side="sell",
            order_type="market",
        )
        del self._positions[ticker]
        if self._db:
            self._db.log_decision(
                ticker=ticker,
                action="SELL",
                tier="protection",
                confidence=1.0,
                reasoning=f"Trailing stop triggered at ${pos.stop_price:.2f}",
                order_id=order.get("id"),
                status="pending",
            )
        return order
