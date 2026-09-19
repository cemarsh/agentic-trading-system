"""
Protective Logic — trailing stops, gap protection, ladder buying.
Applied to all equity positions on each loop tick.
"""

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

# Options symbols follow OCC format: TICKER + YYMMDD + C/P + 8-digit strike
# e.g. PLTR260424P00132000 — skip these in equity protective logic
_OPTIONS_SYMBOL_RE = re.compile(r"^[A-Z]{1,6}\d{6}[CP]\d{8}$")

from config import settings as cfg_module
from execution.daily_journal import log_insight


@dataclass
class EquityPosition:
    ticker: str
    qty: int
    entry_price: float
    high_water_mark: float
    stop_price: float


class ProtectiveLogic:
    def __init__(self, settings=None, alpaca_client=None, db_logger=None, risk_gate=None):
        self.cfg = settings or cfg_module.load()
        self._alpaca = alpaca_client
        self._db = db_logger
        self._risk_gate = risk_gate
        self._positions: Dict[str, EquityPosition] = {}
        self._ladder_counts: Dict[str, int] = {}
        self._ladder_last_price: Dict[str, float] = {}

    def sync_positions(self, alpaca_positions: list):
        """Sync internal state from live Alpaca position data. Skips options contracts."""
        prot = self.cfg.protection
        excluded = set(getattr(prot, "no_auto_manage", None) or [])
        for p in alpaca_positions:
            ticker = p["symbol"]
            if _OPTIONS_SYMBOL_RE.match(ticker):
                continue  # options managed by wheel, not protective logic
            if ticker in excluded:
                continue  # manual-hold (e.g. IPO starters) — no trailing stop / no ladder
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

    def check_catastrophic_loss(
        self, alpaca_positions: list, state: Optional[dict] = None
    ) -> List[dict]:
        """
        Hard loss floor for EVERY equity long — including `no_auto_manage` names.

        `no_auto_manage` was introduced to stop the ladder averaging down into FJET.
        It did that by dropping those tickers out of sync_positions() entirely, which
        also removed their trailing stop, leaving them with no exit at all. FJET then
        fell for six consecutive weeks to -31% unattended.

        This is not a strategy exit — at 25% it sits far outside the 7% trailing stop.
        It is the floor that says the thesis has failed. Returns the positions that
        breached; the caller executes. Reads live broker positions rather than
        self._positions precisely so quarantined names cannot hide from it.

        `state` is the persisted agent state; a breach fires ONCE per ticker
        (guards.acted_once) so a restart loop cannot resubmit the liquidation.
        """
        prot = self.cfg.protection
        limit_pct = getattr(prot, "max_equity_loss_pct", 0.0) or 0.0
        if limit_pct <= 0:
            return []

        # Names held under an explicit manual exit plan. This is NOT the same as
        # no_auto_manage: that list means "don't ladder/trail this", which is how the
        # exit disappeared in the first place. An entry here is a stated decision with
        # its reasoning recorded in strategy_params.yaml, not an absence of one.
        exempt = set(getattr(prot, "catastrophic_exempt", None) or [])

        breached = []
        for p in alpaca_positions or []:
            ticker = p.get("symbol", "")
            if _OPTIONS_SYMBOL_RE.match(ticker):
                continue
            if ticker in exempt:
                continue
            try:
                qty = int(float(p.get("qty", 0)))
                entry = float(p.get("avg_entry_price", 0) or 0)
                price = float(p.get("current_price", 0) or 0)
            except (TypeError, ValueError):
                continue
            # Long positions only. A short equity leg losing money is a different
            # problem with a different exit, and this rule would size it wrong.
            if qty <= 0 or entry <= 0 or price <= 0:
                continue

            loss_pct = (entry - price) / entry * 100
            if loss_pct < limit_pct:
                continue

            if state is not None:
                from execution.guards import acted_once
                if not acted_once(state.setdefault("guards", {}),
                                  "catastrophic_equity_exit", ticker):
                    continue

            breached.append({
                "ticker": ticker, "qty": qty, "entry": entry,
                "price": price, "loss_pct": loss_pct,
                "unrealized": (price - entry) * qty,
            })
        return breached

    def execute_catastrophic_exit(self, breach: dict) -> Optional[dict]:
        """Liquidate a position that breached the hard equity loss floor."""
        ticker = breach["ticker"]
        if not self._alpaca:
            return None

        # Cancel our own resting sells on this name FIRST. Shares committed to a
        # working order are not available to a new one, so a liquidation submitted
        # underneath a resting sell is rejected for insufficient quantity — the exit
        # would appear to fire and quietly do nothing. FJET is the live example:
        # 4,261 of 4,570 shares are locked by a GTC breakeven sell, leaving 309
        # sellable. A hard loss floor outranks a resting hope.
        try:
            for o in self._alpaca.get_open_orders() or []:
                if o.get("symbol") == ticker and (o.get("side") or "").lower() == "sell":
                    if self._alpaca.cancel_order(o.get("id")):
                        print(f"[PROTECT] {ticker} — cancelled resting sell "
                              f"{o.get('qty')} @ {o.get('limit_price')} to free shares")
        except Exception as e:
            print(f"[PROTECT] {ticker} — could not clear resting orders ({e}); "
                  f"liquidation may be rejected for locked shares")

        try:
            order = self._alpaca.submit_order(
                ticker=ticker, qty=breach["qty"], side="sell", order_type="market",
            )
        except Exception as e:
            print(f"[PROTECT] catastrophic exit FAILED for {ticker}: {e}")
            log_insight(
                source="protection", category="error",
                insight=f"catastrophic exit failed for {ticker}: {e}",
                metadata={"ticker": ticker},
            )
            return None

        # Drop any trailing-stop state so check_stops can't fire a second sell.
        self._positions.pop(ticker, None)

        print(f"[PROTECT] CATASTROPHIC EXIT {ticker} — {breach['loss_pct']:.1f}% "
              f"below entry (${breach['unrealized']:+,.0f})")
        log_insight(
            source="protection", category="decision",
            insight=(f"CATASTROPHIC EXIT {breach['qty']}x {ticker} — "
                     f"{breach['loss_pct']:.1f}% below entry ${breach['entry']:.2f} "
                     f"(now ${breach['price']:.2f}, unrealized ${breach['unrealized']:+,.0f})"),
            metadata=breach,
        )
        if self._db:
            try:
                self._db.log_decision(
                    ticker=ticker, action="SELL", tier="protection", confidence=1.0,
                    reasoning=(f"Catastrophic equity loss floor: {breach['loss_pct']:.1f}% "
                               f"below entry ${breach['entry']:.2f}"),
                    order_id=order.get("id"), status="pending",
                )
                self._db.log_lesson(
                    ticker=ticker, strategy_used="catastrophic_equity_stop",
                    regime="unknown", outcome="loss_taken",
                    lesson=(f"Hard loss floor exit at {breach['loss_pct']:.1f}% below entry. "
                            f"Entry ${breach['entry']:.2f}, exit ~${breach['price']:.2f}."),
                    entry_price=breach["entry"], exit_price=breach["price"],
                    pnl=round(breach["unrealized"], 2),
                )
            except Exception as e:
                print(f"[PROTECT] logging failed for {ticker}: {e}")
        return order

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
        """Returns True if a ladder buy should be triggered.

        Bounded two ways so it can never run away (the FJET 2026-06-16 incident):
          1. Hard cap on rungs per ticker (max_ladder_rungs).
          2. Each rung must be a *further* step down — drop is measured from the
             LAST ladder buy (or original entry for the first rung), not from a
             fixed reference that stays True every cycle.
        """
        if ticker not in self._positions:
            return False
        prot = self.cfg.protection
        if self._ladder_counts.get(ticker, 0) >= getattr(prot, "max_ladder_rungs", 3):
            return False
        pos = self._positions[ticker]
        reference = self._ladder_last_price.get(ticker, pos.entry_price)
        drop_pct = (reference - current_price) / reference * 100
        return drop_pct >= prot.ladder_drop_pct

    def execute_ladder(self, ticker: str, current_price: Optional[float] = None) -> Optional[dict]:
        """Submit a ladder buy order and record the rung price (next rung needs a
        further step down from here)."""
        if not self._alpaca:
            return None
        prot = self.cfg.protection
        # Hard pre-trade gate — averaging down must respect the same position/sector
        # caps as any other buy (the FJET runaway was exactly this path).
        if self._risk_gate and current_price:
            ok, reason = self._risk_gate.check_equity_order(
                ticker, prot.ladder_buy_shares * current_price
            )
            if not ok:
                print(f"[RISK] Ladder buy blocked — {reason}")
                log_insight(source="risk_gate", category="decision",
                            insight=f"BLOCKED ladder buy: {reason}",
                            metadata={"ticker": ticker, "qty": prot.ladder_buy_shares})
                return None
        order = self._alpaca.submit_order(
            ticker=ticker,
            qty=prot.ladder_buy_shares,
            side="buy",
            order_type="market",
        )
        if self._risk_gate and current_price:
            self._risk_gate.record_fill(ticker, prot.ladder_buy_shares * current_price)
        self._ladder_counts[ticker] = self._ladder_counts.get(ticker, 0) + 1
        if current_price is not None:
            self._ladder_last_price[ticker] = current_price
        pos = self._positions.get(ticker)
        log_insight(
            source="protection",
            category="decision",
            insight=f"LADDER BUY {prot.ladder_buy_shares}x {ticker} — drawdown #{self._ladder_counts[ticker]} >= {prot.ladder_drop_pct}%",
            metadata={"ticker": ticker, "qty": prot.ladder_buy_shares, "ladder_count": self._ladder_counts[ticker],
                      "entry_price": pos.entry_price if pos else None},
        )
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
        log_insight(
            source="protection",
            category="decision",
            insight=f"STOP SELL {pos.qty}x {ticker} — trailing stop ${pos.stop_price:.2f} (entry ${pos.entry_price:.2f})",
            metadata={"ticker": ticker, "qty": pos.qty, "entry_price": pos.entry_price, "stop_price": pos.stop_price},
        )
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
            estimated_pnl = (pos.stop_price - pos.entry_price) * pos.qty
            try:
                self._db.log_lesson(
                    ticker=ticker,
                    strategy_used="trailing_stop",
                    regime="unknown",
                    outcome="stop_exit",
                    lesson=f"Trailing stop exit — entry ${pos.entry_price:.2f}, stop ${pos.stop_price:.2f}, est PnL ${estimated_pnl:+,.2f}",
                    entry_price=pos.entry_price,
                    exit_price=pos.stop_price,
                    pnl=estimated_pnl,
                )
            except Exception:
                pass
        return order
