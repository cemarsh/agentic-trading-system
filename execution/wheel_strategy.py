"""
Wheel Strategy — Automated CSP and Covered Call management.
Stage 1: Sell Cash Secured Put at target delta.
Stage 2: If assigned, sell Covered Call above cost basis.
"""

import json
import sys
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import settings as cfg_module


@dataclass
class WheelPosition:
    ticker: str
    stage: int                    # 1 = CSP open, 2 = CC open, 0 = flat
    cost_basis: float = 0.0
    csp_strike: float = 0.0
    csp_expiry: Optional[str] = None
    cc_strike: float = 0.0
    cc_expiry: Optional[str] = None
    shares_held: int = 0


class WheelStrategy:
    def __init__(self, settings=None, alpaca_client=None, db_logger=None):
        self.cfg = settings or cfg_module.load()
        self._alpaca = alpaca_client
        self._db = db_logger
        self._positions: Dict[str, WheelPosition] = {
            t: WheelPosition(ticker=t, stage=0)
            for t in self.cfg.wheel.tickers
        }

    def target_expiry(self) -> str:
        """Next expiry date N weeks out (Friday)."""
        today = date.today()
        target = today + timedelta(weeks=self.cfg.wheel.expiration_weeks)
        # Roll to nearest Friday
        days_ahead = 4 - target.weekday()
        if days_ahead < 0:
            days_ahead += 7
        return (target + timedelta(days=days_ahead)).isoformat()

    def select_csp_strike(self, ticker: str, current_price: float) -> float:
        """
        Approximate strike at target delta.
        Without full options chain pricing, uses delta ≈ 0.30 → ~5-7% OTM.
        A real implementation should use the options chain from Alpaca.
        """
        otm_factor = self.cfg.wheel.target_delta * 0.15 + 0.90  # 0.25 delta → ~6.25% OTM
        raw = current_price * otm_factor
        # Round to nearest $0.50
        return round(raw * 2) / 2

    def open_csp(self, ticker: str) -> Optional[dict]:
        """Sell a Cash Secured Put for the given ticker."""
        if not self._alpaca:
            return None

        pos = self._positions[ticker]
        if pos.stage != 0:
            print(f"[WHEEL] {ticker} already in stage {pos.stage}, skipping CSP open")
            return None

        # --- Allocation guards ---
        try:
            account = self._alpaca.get_account()
            equity = float(account.get("equity", 0))
            initial_margin = float(account.get("initial_margin", 0))

            # Guard 1: total wheel allocation cap
            if equity > 0:
                current_allocation_pct = initial_margin / equity * 100
                if current_allocation_pct >= self.cfg.wheel.max_wheel_allocation_pct:
                    print(
                        f"[WHEEL] {ticker} — allocation cap reached "
                        f"({current_allocation_pct:.1f}% >= {self.cfg.wheel.max_wheel_allocation_pct}%), skipping"
                    )
                    return None
        except Exception as e:
            print(f"[WHEEL] {ticker} — account check failed: {e}")
            equity = 0

        bars = self._alpaca.get_bars(ticker, "1Min", 1)
        if not bars:
            return None
        current_price = bars[-1]["c"]

        strike = self.select_csp_strike(ticker, current_price)

        # Guard 2: per-trade size limit (CSP collateral = strike × 100 shares)
        if equity > 0:
            max_collateral = equity * self.cfg.wheel.max_portfolio_pct_per_trade / 100
            required_collateral = strike * 100
            if required_collateral > max_collateral:
                print(
                    f"[WHEEL] {ticker} — position too large "
                    f"(${required_collateral:,.0f} > ${max_collateral:,.0f} max), skipping"
                )
                return None

        expiry = self.target_expiry()

        contracts = self._alpaca.get_options_contracts(ticker, expiry)
        puts = [c for c in contracts if c.get("type") == "put"]
        if not puts:
            print(f"[WHEEL] {ticker} — no put contracts available exp {expiry}")
            return None

        # Use nearest available strike rather than exact match
        target = min(puts, key=lambda c: abs(float(c.get("strike_price", 0)) - strike))
        actual_strike = float(target.get("strike_price", 0))
        max_deviation = strike * 0.08  # accept up to 8% off target
        if abs(actual_strike - strike) > max_deviation:
            print(
                f"[WHEEL] {ticker} — nearest strike ${actual_strike} too far from "
                f"target ${strike} (>{max_deviation:.0f}), skipping"
            )
            return None
        if actual_strike != strike:
            print(f"[WHEEL] {ticker} — using nearest strike ${actual_strike} (target was ${strike})")

        try:
            order = self._alpaca.submit_option_order(
                symbol=target["symbol"],
                qty=1,
                side="sell",
                order_type="market",
            )
        except Exception as e:
            print(f"[WHEEL] {ticker} — order submission failed: {e}")
            return None

        pos.stage = 1
        pos.csp_strike = actual_strike
        pos.csp_expiry = expiry

        if self._db:
            self._db.log_decision(
                ticker=ticker,
                action="SELL_PUT",
                tier="wheel",
                confidence=0.9,
                reasoning=f"Wheel Stage 1: CSP at ${actual_strike} exp {expiry}, underlying ${current_price:.2f}",
                order_id=order.get("id"),
                status="pending",
            )

        return order

    def handle_assignment(self, ticker: str, shares: int, cost_basis: float):
        """Called when a CSP is assigned — updates state and opens CC."""
        pos = self._positions[ticker]
        pos.stage = 2
        pos.shares_held = shares
        pos.cost_basis = cost_basis
        print(f"[WHEEL] {ticker} assigned {shares} shares @ ${cost_basis:.2f}")
        return self.open_cc(ticker)

    def open_cc(self, ticker: str) -> Optional[dict]:
        """Sell a Covered Call above cost basis."""
        if not self._alpaca:
            return None

        pos = self._positions[ticker]
        if pos.stage != 2 or pos.shares_held < 100:
            return None

        markup = self.cfg.wheel.cc_strike_markup_pct / 100
        cc_strike = round(pos.cost_basis * (1 + markup) * 2) / 2
        expiry = self.target_expiry()

        contracts = self._alpaca.get_options_contracts(ticker, expiry)
        calls = [c for c in contracts if c.get("type") == "call"]
        if not calls:
            print(f"[WHEEL] {ticker} — no call contracts available exp {expiry}")
            return None

        target = min(calls, key=lambda c: abs(float(c.get("strike_price", 0)) - cc_strike))
        actual_cc_strike = float(target.get("strike_price", 0))
        if actual_cc_strike != cc_strike:
            print(f"[WHEEL] {ticker} — CC using nearest strike ${actual_cc_strike} (target was ${cc_strike})")

        try:
            order = self._alpaca.submit_option_order(
                symbol=target["symbol"],
                qty=1,
                side="sell",
                order_type="market",
            )
        except Exception as e:
            print(f"[WHEEL] {ticker} — CC order submission failed: {e}")
            return None

        pos.cc_strike = actual_cc_strike
        pos.cc_expiry = expiry

        if self._db:
            self._db.log_decision(
                ticker=ticker,
                action="SELL_CALL",
                tier="wheel",
                confidence=0.9,
                reasoning=f"Wheel Stage 2: CC at ${cc_strike} exp {expiry}, cost basis ${pos.cost_basis:.2f}",
                order_id=order.get("id"),
                status="pending",
            )

        return order

    def run_cycle(self) -> int:
        """Run one full Wheel cycle check across all tickers. Returns count of contracts placed."""
        placed = 0
        for ticker in self.cfg.wheel.tickers:
            pos = self._positions[ticker]
            if pos.stage == 0:
                result = self.open_csp(ticker)
                if result is not None:
                    placed += 1
        return placed
