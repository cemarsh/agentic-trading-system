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
from execution.daily_journal import log_insight


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
    def __init__(self, settings=None, alpaca_client=None, db_logger=None,
                 risk_gate=None, ledger=None):
        self.cfg = settings or cfg_module.load()
        self._alpaca = alpaca_client
        self._db = db_logger
        self._risk_gate = risk_gate
        self._ledger = ledger
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

        # --- Guard 0: IV-rank gate (only sell premium when it's rich enough) ---
        # Selling a CSP in a low-IV environment collects too little premium for the
        # downside risk. HARD gate by default (iv_gate_fail_open: false): no IV
        # history means NO trade — the correct behavior in a cheap-premium week is
        # sitting in cash, and the system must be allowed to do nothing.
        min_ivr = getattr(self.cfg.wheel, "min_iv_rank", 0.0) or 0.0
        fail_open = bool(getattr(self.cfg.wheel, "iv_gate_fail_open", False))
        if min_ivr:
            ivr = None
            if getattr(self.cfg, "database", None) and self.cfg.database.url:
                try:
                    from execution.iv_tracker import get_iv_rank
                    ivr = get_iv_rank(ticker, self.cfg.database.url).get("iv_rank")
                except Exception as e:
                    print(f"[WHEEL] {ticker} — IV rank lookup failed ({e})")
            if ivr is not None and ivr < min_ivr:
                print(f"[WHEEL] {ticker} — IV rank {ivr:.0%} < {min_ivr:.0%} floor, "
                      f"skipping CSP (premium too cheap)")
                return None
            if ivr is None and not fail_open:
                print(f"[WHEEL] {ticker} — no IV history and gate is fail-closed, "
                      f"skipping CSP (run iv_tracker snapshots to build history)")
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

        # Guard 3: earnings gate — a short put spanning an earnings date is a binary
        # event bet, not premium selling. Fail-open only when the calendar is
        # unavailable (no FINNHUB_API_KEY), and that is logged loudly.
        if getattr(self.cfg.wheel, "earnings_gate", True):
            try:
                from execution.earnings_calendar import has_earnings_before
                verdict = has_earnings_before(ticker, expiry)
            except Exception as e:
                print(f"[WHEEL] {ticker} — earnings check failed ({e}), proceeding")
                verdict = None
            if verdict:
                print(f"[WHEEL] {ticker} — earnings before {expiry}, skipping CSP")
                log_insight(source="wheel", category="decision",
                            insight=f"SKIP CSP {ticker} — earnings inside expiry window (exp {expiry})",
                            metadata={"ticker": ticker, "expiry": expiry})
                return None

        # Guard 4: central risk gate — quarantined names and sector-correlation cap.
        if self._risk_gate:
            ok, reason = self._risk_gate.check_option_collateral(ticker, strike * 100)
            if not ok:
                print(f"[RISK] CSP blocked — {reason}")
                log_insight(source="risk_gate", category="decision",
                            insight=f"BLOCKED CSP: {reason}", metadata={"ticker": ticker})
                return None

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

        # Guard 5: minimum credit floor off the REAL NBBO. A thin bid is a fee
        # generator with delta risk attached, not a trade. Floor = the larger of
        # the absolute $/share minimum and min_premium_pct of the strike (the
        # 1%-a-month yield bar). No quote → no verifiable credit → no trade.
        quote = self._alpaca.get_option_quote(target["symbol"])
        bid = quote["bid"] if quote and quote.get("bid") else 0.0
        min_credit = max(
            getattr(self.cfg.wheel, "min_credit_per_share", 0.15) or 0.0,
            actual_strike * (self.cfg.wheel.min_premium_pct or 0.0) / 100.0,
        )
        if bid < min_credit:
            print(f"[WHEEL] {ticker} — bid ${bid:.2f}/sh < ${min_credit:.2f} credit floor, "
                  f"skipping CSP (premium too thin)")
            return None

        try:
            # Sell LIMIT at the bid — guarantees at least the credit the floor
            # verified, and options market orders are rejected outside RTH anyway.
            order = self._alpaca.submit_option_order(
                symbol=target["symbol"],
                qty=1,
                side="sell",
                order_type="limit",
                limit_price=round(bid, 2),
            )
        except Exception as e:
            print(f"[WHEEL] {ticker} — order submission failed: {e}")
            return None

        if self._ledger:
            self._ledger.record_open(target["symbol"], owner="wheel")
        if self._risk_gate:
            self._risk_gate.record_fill(ticker, actual_strike * 100)

        pos.stage = 1
        pos.csp_strike = actual_strike
        pos.csp_expiry = expiry

        log_insight(
            source="wheel",
            category="decision",
            insight=f"SELL CSP {ticker} ${actual_strike} exp {expiry} @ ${bid:.2f}/sh credit — underlying ${current_price:.2f}",
            metadata={"ticker": ticker, "strike": actual_strike, "expiry": expiry,
                      "price": current_price, "credit_per_share": bid},
        )
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

        # Sell LIMIT at the bid — never a market order on an options book.
        quote = self._alpaca.get_option_quote(target["symbol"])
        cc_bid = quote["bid"] if quote and quote.get("bid") else 0.0
        if cc_bid <= 0:
            print(f"[WHEEL] {ticker} — no bid on CC {target['symbol']}, skipping")
            return None

        try:
            order = self._alpaca.submit_option_order(
                symbol=target["symbol"],
                qty=1,
                side="sell",
                order_type="limit",
                limit_price=round(cc_bid, 2),
            )
        except Exception as e:
            print(f"[WHEEL] {ticker} — CC order submission failed: {e}")
            return None

        if self._ledger:
            self._ledger.record_open(target["symbol"], owner="wheel")

        pos.cc_strike = actual_cc_strike
        pos.cc_expiry = expiry

        log_insight(
            source="wheel",
            category="decision",
            insight=f"SELL CC {ticker} ${actual_cc_strike} exp {expiry} — cost basis ${pos.cost_basis:.2f}",
            metadata={"ticker": ticker, "strike": actual_cc_strike, "expiry": expiry, "cost_basis": pos.cost_basis},
        )
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
