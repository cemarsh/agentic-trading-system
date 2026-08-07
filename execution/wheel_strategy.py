"""
Wheel Strategy — Automated CSP and Covered Call management.
Stage 1: Sell Cash Secured Put at target delta.
Stage 2: If assigned, sell Covered Call above cost basis.
"""

import json
import re
import sys
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import settings as cfg_module
from execution.daily_journal import log_insight
from execution.guards import Cooldown

# OCC option symbol: TICKER + YYMMDD + C/P + 8-digit strike×1000
_OCC_RE = re.compile(r"^([A-Z]{1,6})(\d{6})([CP])(\d{8})$")


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
        # Quarantined tickers are excluded UPSTREAM, at candidate generation —
        # not just at the risk gate. Without this, run_cycle re-proposed a FJET
        # CSP every ~60s and the gate blocked it every time (~320 wasted
        # evaluations + insight-log entries per day, W28 finding).
        if risk_gate is not None and isinstance(getattr(risk_gate, "quarantined", None), (set, frozenset, list)):
            self._quarantined = set(risk_gate.quarantined)
        else:
            risk = getattr(self.cfg, "risk", None)
            prot = getattr(self.cfg, "protection", None)
            self._quarantined = set(getattr(risk, "quarantined_tickers", None) or []) | set(
                getattr(prot, "no_auto_manage", None) or []
            )
        excluded = self._quarantined & set(self.cfg.wheel.tickers)
        if excluded:
            print(f"[WHEEL] excluding quarantined ticker(s) from CSP candidates: {', '.join(sorted(excluded))}")

        # Skip decisions repeat every cycle by nature — the earnings date doesn't move
        # between 10:00:05 and 10:01:10. Logging each one wrote 150–320 duplicate
        # entries/day and buried real signal in the journal (W32 finding).
        cooldown_min = getattr(self.cfg.wheel, "skip_log_cooldown_minutes", 240) or 240
        self._skip_cd = Cooldown(cooldown_min * 60)
        self._untradeable_logged = False

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _skip(self, ticker: str, reason_code: str, message: str, metadata: Optional[dict] = None,
              journal: bool = False) -> None:
        """Print/journal a skip decision at most once per cooldown per (ticker, reason).

        Skips are steady-state facts, not events: re-emitting them every 65s is the
        same repeat-without-a-cap bug class as the halt loop and the ladder runaway,
        just with log lines instead of orders.
        """
        if not self._skip_cd.ready(f"{ticker}:{reason_code}"):
            return
        print(message)
        if journal:
            meta = {"ticker": ticker, "reason": reason_code}
            meta.update(metadata or {})
            log_insight(source="wheel", category="decision", insight=message, metadata=meta)

    def sync_positions(self, positions: list) -> None:
        """Re-derive per-ticker wheel stage from LIVE broker positions.

        Stage lived only in memory, so every restart reset all 23 tickers to stage 0
        (flat) — after which the wheel would happily sell a SECOND CSP on a name that
        already had one open. The service restarted on 2026-07-31; nothing caught it
        because the sector cap happened to absorb it. Stage is now broker-derived, so
        the process can be restarted at any point in the cycle safely.
        """
        short_puts: Dict[str, float] = {}
        shares: Dict[str, int] = {}
        for p in positions or []:
            symbol = (p.get("symbol") or "").upper()
            try:
                qty = float(p.get("qty", 0) or 0)
            except (TypeError, ValueError):
                continue
            m = _OCC_RE.match(symbol)
            if m:
                underlying, opt_type, strike = m.group(1), m.group(3), int(m.group(4)) / 1000.0
                if opt_type == "P" and qty < 0:
                    short_puts[underlying] = strike
            elif qty > 0:
                shares[symbol] = int(qty)

        for ticker, pos in self._positions.items():
            if ticker in short_puts:
                pos.stage = 1
                pos.csp_strike = short_puts[ticker]
            elif shares.get(ticker, 0) >= 100:
                pos.stage = 2
                pos.shares_held = shares[ticker]
            else:
                pos.stage = 0

    def _report_untradeable_universe(self) -> None:
        """Once per process: name the tickers that can NEVER trade at this account size.

        A CSP needs strike×100 of collateral. When one contract already exceeds the
        per-trade cap, the name is not "waiting for a better setup" — it is permanently
        unreachable until equity grows or the cap changes. Nine of twenty names were in
        that state (CAT alone needs $80k against a $12.9k cap) and nothing said so; they
        just silently never traded. This makes the universe/account mismatch visible
        instead of leaving it to be inferred from an absence of orders.
        """
        if self._untradeable_logged or not self._alpaca:
            return
        self._untradeable_logged = True
        try:
            equity = float(self._alpaca.get_account().get("equity", 0) or 0)
        except Exception:
            return
        if equity <= 0:
            return
        cap = equity * self.cfg.wheel.max_portfolio_pct_per_trade / 100.0

        unreachable = []
        for ticker in self.cfg.wheel.tickers:
            if ticker in self._quarantined:
                continue
            try:
                bars = self._alpaca.get_bars(ticker, "1Day", 1)
                if not bars:
                    continue
                collateral = float(self.select_csp_strike(ticker, float(bars[-1]["c"]))) * 100
            except Exception:
                continue  # a reporting aid must never break the trading cycle
            if collateral > cap:
                unreachable.append((ticker, collateral))

        if not unreachable:
            return
        detail = ", ".join(f"{t} (${c:,.0f})" for t, c in sorted(unreachable, key=lambda x: -x[1]))
        message = (
            f"[WHEEL] {len(unreachable)}/{len(self.cfg.wheel.tickers)} universe tickers are "
            f"UNREACHABLE at ${equity:,.0f} equity — one contract exceeds the "
            f"${cap:,.0f} per-trade cap: {detail}"
        )
        print(message)
        log_insight(source="wheel", category="observation", insight=message,
                    metadata={"unreachable": [t for t, _ in unreachable],
                              "per_trade_cap": round(cap, 2), "equity": round(equity, 2)})

    def _iv_rank(self, ticker: str) -> Optional[float]:
        """IV rank (0.0–1.0) from stored history, or None when unavailable."""
        if not (getattr(self.cfg, "database", None) and self.cfg.database.url):
            return None
        try:
            from execution.iv_tracker import get_iv_rank
            return get_iv_rank(ticker, self.cfg.database.url).get("iv_rank")
        except Exception as e:
            print(f"[WHEEL] {ticker} — IV rank lookup failed ({e})")
            return None

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

    def open_csp(self, ticker: str, ivr: Optional[float] = None) -> Optional[dict]:
        """Sell a Cash Secured Put for the given ticker.

        `ivr` may be passed by run_cycle (which already ranked candidates by IV) to
        avoid a second database round-trip per ticker per cycle.
        """
        if not self._alpaca:
            return None

        pos = self._positions[ticker]
        if pos.stage != 0:
            self._skip(ticker, "stage",
                       f"[WHEEL] {ticker} already in stage {pos.stage}, skipping CSP open")
            return None

        # --- Guard 0: IV-rank gate (only sell premium when it's rich enough) ---
        # Selling a CSP in a low-IV environment collects too little premium for the
        # downside risk. HARD gate by default (iv_gate_fail_open: false): no IV
        # history means NO trade — the correct behavior in a cheap-premium week is
        # sitting in cash, and the system must be allowed to do nothing.
        min_ivr = getattr(self.cfg.wheel, "min_iv_rank", 0.0) or 0.0
        fail_open = bool(getattr(self.cfg.wheel, "iv_gate_fail_open", False))
        if min_ivr:
            if ivr is None:
                ivr = self._iv_rank(ticker)
            if ivr is not None and ivr < min_ivr:
                self._skip(ticker, "iv_rank",
                           f"[WHEEL] {ticker} — IV rank {ivr:.0%} < {min_ivr:.0%} floor, "
                           f"skipping CSP (premium too cheap)")
                return None
            if ivr is None and not fail_open:
                self._skip(ticker, "no_iv_history",
                           f"[WHEEL] {ticker} — no IV history and gate is fail-closed, "
                           f"skipping CSP (run iv_tracker snapshots to build history)")
                return None

        # --- Allocation guards ---
        equity = 0.0
        initial_margin = 0.0
        try:
            account = self._alpaca.get_account()
            equity = float(account.get("equity", 0))
            initial_margin = float(account.get("initial_margin", 0))

            # Guard 1: total wheel allocation cap
            if equity > 0:
                current_allocation_pct = initial_margin / equity * 100
                if current_allocation_pct >= self.cfg.wheel.max_wheel_allocation_pct:
                    self._skip(ticker, "alloc_cap",
                               f"[WHEEL] {ticker} — allocation cap reached "
                               f"({current_allocation_pct:.1f}% >= "
                               f"{self.cfg.wheel.max_wheel_allocation_pct}%), skipping")
                    return None
        except Exception as e:
            print(f"[WHEEL] {ticker} — account check failed: {e}")
            equity = 0

        bars = self._alpaca.get_bars(ticker, "1Min", 1)
        if not bars:
            return None
        current_price = bars[-1]["c"]

        strike = self.select_csp_strike(ticker, current_price)

        # Guard 2: per-trade size limit (CSP collateral = strike × 100 shares).
        # Cheap pre-check on the ESTIMATED strike so we don't pull an options chain
        # for a name that can't fit even one contract. Final sizing happens below
        # against the actual strike.
        if equity > 0:
            max_collateral = equity * self.cfg.wheel.max_portfolio_pct_per_trade / 100
            required_collateral = strike * 100
            if required_collateral > max_collateral:
                # Structural, not transient: at this underlying price ONE contract
                # exceeds the per-trade cap, so the name can never trade at this
                # account size. Surfaced by run_cycle() as a universe problem.
                self._skip(ticker, "too_large",
                           f"[WHEEL] {ticker} — one contract needs ${required_collateral:,.0f} "
                           f"> ${max_collateral:,.0f} per-trade cap "
                           f"({self.cfg.wheel.max_portfolio_pct_per_trade}% of ${equity:,.0f}) — "
                           f"underlying too expensive for this account, skipping")
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
                self._skip(ticker, f"earnings:{expiry}",
                           f"SKIP CSP {ticker} — earnings inside expiry window (exp {expiry})",
                           metadata={"expiry": expiry}, journal=True)
                return None

        # Guard 4: central risk gate — quarantined names and sector-correlation cap.
        # Pre-check at one contract; the final sized order is re-checked before submit.
        if self._risk_gate:
            ok, reason = self._risk_gate.check_option_collateral(ticker, strike * 100)
            if not ok:
                self._skip(ticker, "risk_gate", f"[RISK] CSP blocked — {reason}",
                           metadata={"reason_detail": reason}, journal=True)
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
            self._skip(ticker, "thin_credit",
                       f"[WHEEL] {ticker} — bid ${bid:.2f}/sh < ${min_credit:.2f} credit floor, "
                       f"skipping CSP (premium too thin)")
            return None

        # --- Sizing: fill the authorized capacity instead of always selling one ---
        # qty is the largest number of contracts that satisfies EVERY cap at once.
        # Previously hardcoded to 1, which left up to 75% of a name's authorized
        # collateral unused and kept the book at 13.8% of a 65% allocation budget.
        collateral_per_contract = actual_strike * 100
        qty = 1
        if equity > 0 and collateral_per_contract > 0:
            per_trade_room = equity * self.cfg.wheel.max_portfolio_pct_per_trade / 100.0
            alloc_room = max(
                0.0,
                equity * self.cfg.wheel.max_wheel_allocation_pct / 100.0 - initial_margin,
            )
            sector_room = (
                self._risk_gate.collateral_headroom(ticker)
                if self._risk_gate else float("inf")
            )
            budget = min(per_trade_room, alloc_room, sector_room)
            hard_cap = int(getattr(self.cfg.wheel, "max_contracts_per_trade", 1) or 1)
            qty = min(hard_cap, int(budget // collateral_per_contract))
            if qty < 1:
                self._skip(ticker, "no_headroom",
                           f"[WHEEL] {ticker} — no headroom for even one contract "
                           f"(need ${collateral_per_contract:,.0f}, budget ${budget:,.0f}: "
                           f"per-trade ${per_trade_room:,.0f} / allocation ${alloc_room:,.0f} / "
                           f"sector ${sector_room:,.0f}), skipping")
                return None

        # Final gate check on the SIZED order — the pre-check above only cleared one
        # contract. Without this, sizing could walk straight through the sector cap.
        if self._risk_gate:
            ok, reason = self._risk_gate.check_option_collateral(
                ticker, collateral_per_contract * qty
            )
            if not ok:
                self._skip(ticker, "risk_gate_sized",
                           f"[RISK] CSP blocked at qty={qty} — {reason}",
                           metadata={"qty": qty, "reason_detail": reason}, journal=True)
                return None

        try:
            # Sell LIMIT at the bid — guarantees at least the credit the floor
            # verified, and options market orders are rejected outside RTH anyway.
            order = self._alpaca.submit_option_order(
                symbol=target["symbol"],
                qty=qty,
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
            self._risk_gate.record_fill(ticker, collateral_per_contract * qty)

        pos.stage = 1
        pos.csp_strike = actual_strike
        pos.csp_expiry = expiry

        log_insight(
            source="wheel",
            category="decision",
            insight=(f"SELL CSP {ticker} {qty}x ${actual_strike} exp {expiry} @ ${bid:.2f}/sh "
                     f"credit (${bid * 100 * qty:,.0f} total) — underlying ${current_price:.2f}"
                     + (f", IV rank {ivr:.0%}" if ivr is not None else "")),
            metadata={"ticker": ticker, "strike": actual_strike, "expiry": expiry,
                      "price": current_price, "credit_per_share": bid, "qty": qty,
                      "total_credit": round(bid * 100 * qty, 2), "iv_rank": ivr,
                      "collateral": collateral_per_contract * qty},
        )
        if self._db:
            self._db.log_decision(
                ticker=ticker,
                action="SELL_PUT",
                tier="wheel",
                confidence=0.9,
                reasoning=(f"Wheel Stage 1: {qty}x CSP at ${actual_strike} exp {expiry}, "
                           f"underlying ${current_price:.2f}, "
                           f"collateral ${collateral_per_contract * qty:,.0f}"),
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
        """Run one full Wheel cycle check across all tickers. Returns count of orders placed.

        Candidates are evaluated richest-IV-first. Collateral is a scarce shared
        resource — the sector cap and allocation budget are consumed by whichever
        name is sized first — so file order was silently deciding capital allocation.
        That is how a GEO CSP at IV rank 20% collecting $23 got filled in a week when
        AVAV sat at IV rank 100%: GEO simply appeared earlier in the list.
        """
        candidates = [t for t in self.cfg.wheel.tickers
                      if t not in self._quarantined and self._positions[t].stage == 0]
        self._report_untradeable_universe()

        ranked: List[tuple] = []
        if getattr(self.cfg.wheel, "prioritize_by_iv_rank", False):
            for ticker in candidates:
                ivr = self._iv_rank(ticker)
                # None sorts last: an unknown IV rank can't outrank a measured one,
                # and with the hard gate it will be skipped anyway.
                ranked.append((ticker, ivr, -1.0 if ivr is None else ivr))
            ranked.sort(key=lambda r: r[2], reverse=True)
        else:
            ranked = [(t, None, 0.0) for t in candidates]

        placed = 0
        for ticker, ivr, _sort_key in ranked:
            if self.open_csp(ticker, ivr=ivr) is not None:
                placed += 1
        return placed
