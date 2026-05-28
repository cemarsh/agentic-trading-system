"""
Position Manager — Active options position management.

Runs once per loop cycle and enforces two rules:
  1. 50% max-profit close: BTC when (entry_credit - current_mark) / entry_credit >= 0.50
  2. 21 DTE roll: when DTE <= 21 and position is NOT at 50%+ profit, roll to 4-6 weeks out.
     If a net credit cannot be collected on the roll, take the loss and close instead.

OCC symbol format: <TICKER><YYMMDD><C|P><STRIKE×1000 zero-padded to 8 digits>
Example: AAPL260117P00150000 = AAPL Jan 17 2026 $150 Put

Usage (standalone):
    python execution/position_manager.py
"""

import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import settings as cfg_module
from execution.daily_journal import log_insight

# -----------------------------------------------------------------------
# OCC symbol helpers
# -----------------------------------------------------------------------

def _parse_occ(symbol: str) -> Optional[dict]:
    """
    Parse an OCC option symbol into its components.

    OCC format: <ROOT><YYMMDD><C|P><8-digit strike×1000>
    The root (ticker) is variable-length — we find it by scanning backwards
    from the first digit to isolate the date+type+strike suffix (15 chars).

    Returns dict with keys: ticker, expiry_date (date), option_type ('C'|'P'),
    strike (float), dte (int from today).
    Returns None if the symbol does not match the expected format.
    """
    s = symbol.strip().upper()
    # Suffix is always exactly 15 chars: YYMMDD + C/P + 8-digit strike
    if len(s) < 15:
        return None
    suffix = s[-15:]
    ticker = s[:-15]
    if not ticker:
        return None
    try:
        date_str = suffix[:6]           # YYMMDD
        option_type = suffix[6]         # C or P
        strike_raw = suffix[7:]         # 8 digits, divide by 1000
        if option_type not in ("C", "P"):
            return None
        expiry_date = datetime.strptime(date_str, "%y%m%d").date()
        strike = int(strike_raw) / 1000.0
        today = date.today()
        dte = (expiry_date - today).days
        return {
            "ticker": ticker,
            "expiry_date": expiry_date,
            "option_type": option_type,
            "strike": strike,
            "dte": dte,
        }
    except (ValueError, IndexError):
        return None


def _compute_current_mark(position: dict) -> Optional[float]:
    """
    Derive the current mark price from Alpaca position fields.

    Alpaca supplies avg_entry_price (entry credit received, stored as positive
    for short positions) and unrealized_pl (positive when position is profitable
    i.e. mark has declined).

    current_mark = avg_entry_price - (unrealized_pl / (|qty| * 100))
    """
    try:
        avg_entry = float(position.get("avg_entry_price", 0))
        unrealized = float(position.get("unrealized_pl", 0))
        qty = abs(float(position.get("qty", 0)))
        if qty == 0:
            return None
        return avg_entry - (unrealized / (qty * 100))
    except (TypeError, ValueError, ZeroDivisionError):
        return None


# -----------------------------------------------------------------------
# PositionManager
# -----------------------------------------------------------------------

# Minimum roll credit to accept — anything positive (even $0.01/contract) is fine;
# if we can't collect any credit we close instead of rolling for a debit.
MIN_ROLL_NET_CREDIT = 0.0

PROFIT_CLOSE_THRESHOLD = 0.50   # 50% of max profit
DTE_ROLL_THRESHOLD = 21          # calendar days
ROLL_WEEKS_MIN = 4
ROLL_WEEKS_MAX = 6


class PositionManager:
    """
    Manages open options positions — applies 50% profit close and 21-DTE roll rules.
    """

    def __init__(self, settings=None, alpaca_client=None, db_logger=None):
        self.cfg = settings or cfg_module.load()
        self._alpaca = alpaca_client
        self._db = db_logger

    # -------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------

    def run_cycle(self, positions: list) -> dict:
        """
        Inspect all option positions and act as needed.

        Args:
            positions: raw list of Alpaca position dicts (from get_positions()).

        Returns:
            {"closed": [<symbol>, ...], "rolled": [<symbol>, ...]}
        """
        result = {"closed": [], "rolled": []}

        option_positions = [
            p for p in positions
            if p.get("asset_class") == "us_option"
            or _parse_occ(p.get("symbol", "")) is not None
        ]

        if not option_positions:
            return result

        print(f"[PM] Checking {len(option_positions)} option position(s)")

        for pos in option_positions:
            symbol = pos.get("symbol", "")
            parsed = _parse_occ(symbol)
            if not parsed:
                print(f"[PM] Cannot parse OCC symbol '{symbol}' — skipping")
                continue

            current_mark = _compute_current_mark(pos)
            if current_mark is None:
                print(f"[PM] Cannot compute mark for {symbol} — skipping")
                continue

            avg_entry = float(pos.get("avg_entry_price", 0))
            dte = parsed["dte"]

            # Skip expired or negative DTE
            if dte < 0:
                print(f"[PM] {symbol} appears expired (DTE={dte}) — skipping")
                continue

            profit_pct = (
                (avg_entry - current_mark) / avg_entry
                if avg_entry > 0 else 0.0
            )
            at_50_pct = profit_pct >= PROFIT_CLOSE_THRESHOLD

            print(
                f"[PM] {symbol}  DTE={dte}  entry={avg_entry:.4f}  "
                f"mark={current_mark:.4f}  profit={profit_pct:.1%}"
            )

            # --- Rule 1: 50% profit close ---
            if at_50_pct:
                closed = self._close_position(pos, parsed, current_mark, profit_pct, reason="50% max profit")
                if closed:
                    result["closed"].append(symbol)
                continue

            # --- Rule 2: 21-DTE roll ---
            if dte <= DTE_ROLL_THRESHOLD:
                rolled = self._roll_position(pos, parsed, current_mark, profit_pct)
                if rolled:
                    result["rolled"].append(symbol)
                else:
                    # Could not collect net credit — close at whatever mark
                    closed = self._close_position(pos, parsed, current_mark, profit_pct, reason="21 DTE, no roll credit available")
                    if closed:
                        result["closed"].append(symbol)

        return result

    # -------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------

    def _close_position(
        self,
        pos: dict,
        parsed: dict,
        current_mark: float,
        profit_pct: float,
        reason: str,
    ) -> bool:
        """Submit a buy-to-close order and log the result."""
        symbol = pos.get("symbol", "")
        qty = abs(int(float(pos.get("qty", 1))))
        avg_entry = float(pos.get("avg_entry_price", 0))
        realized_pnl = (avg_entry - current_mark) * qty * 100

        print(f"[PM] BTC {symbol} — {reason} (realized ~${realized_pnl:+.2f})")

        if not self._alpaca:
            print(f"[PM] (dry-run — no alpaca client)")
            return False

        try:
            self._alpaca.submit_option_order(
                symbol=symbol,
                qty=qty,
                side="buy",
                order_type="market",
            )
        except Exception as e:
            print(f"[PM] BTC order failed for {symbol}: {e}")
            log_insight(
                source="system",
                category="error",
                insight=f"BTC failed for {symbol}: {e}",
                metadata={"symbol": symbol, "reason": reason},
            )
            return False

        log_insight(
            source="system",
            category="decision",
            insight=(
                f"BTC {symbol} — {reason} — entry={avg_entry:.4f} "
                f"mark={current_mark:.4f} profit={profit_pct:.1%} realized~${realized_pnl:+.2f}"
            ),
            metadata={
                "symbol": symbol,
                "ticker": parsed["ticker"],
                "option_type": parsed["option_type"],
                "strike": parsed["strike"],
                "expiry": parsed["expiry_date"].isoformat(),
                "dte": parsed["dte"],
                "avg_entry": avg_entry,
                "current_mark": current_mark,
                "profit_pct": round(profit_pct, 4),
                "realized_pnl": round(realized_pnl, 2),
                "reason": reason,
            },
        )

        if self._db:
            try:
                self._db.log_lesson(
                    ticker=parsed["ticker"],
                    strategy_used="wheel_btc",
                    regime="UNKNOWN",
                    outcome="closed" if realized_pnl >= 0 else "loss_taken",
                    lesson=(
                        f"BTC {symbol} at {profit_pct:.1%} profit ({reason}). "
                        f"Entry {avg_entry:.4f}, exit mark ~{current_mark:.4f}, "
                        f"P&L ~${realized_pnl:+.2f}."
                    ),
                    entry_price=avg_entry,
                    exit_price=current_mark,
                    pnl=round(realized_pnl, 2),
                )
            except Exception as e:
                print(f"[PM] log_lesson failed: {e}")

            try:
                self._db.log_decision(
                    ticker=parsed["ticker"],
                    action="BTC",
                    tier="position_manager",
                    confidence=0.95,
                    reasoning=f"BTC {symbol}: {reason}. profit={profit_pct:.1%}",
                    status="submitted",
                    pnl=round(realized_pnl, 2),
                )
            except Exception as e:
                print(f"[PM] log_decision failed: {e}")

        return True

    def _roll_position(
        self,
        pos: dict,
        parsed: dict,
        current_mark: float,
        profit_pct: float,
    ) -> bool:
        """
        Attempt a roll: BTC current leg + sell new leg 4-6 weeks out, same delta tier.
        Returns True if the roll was executed, False if no net credit is achievable.
        """
        symbol = pos.get("symbol", "")
        ticker = parsed["ticker"]
        option_type = parsed["option_type"]  # 'C' or 'P'
        strike = parsed["strike"]
        qty = abs(int(float(pos.get("qty", 1))))
        avg_entry = float(pos.get("avg_entry_price", 0))

        print(f"[PM] Attempting roll for {symbol} (DTE={parsed['dte']})")

        if not self._alpaca:
            print(f"[PM] (dry-run — no alpaca client)")
            return False

        # --- Find new expiry (4-6 weeks out) ---
        from datetime import timedelta
        today = date.today()
        # Try 4 weeks first, fall back to 5 then 6
        new_expiry_str = None
        new_contracts = []
        for weeks in range(ROLL_WEEKS_MIN, ROLL_WEEKS_MAX + 1):
            target_date = today + timedelta(weeks=weeks)
            # Roll to nearest Friday
            days_to_friday = (4 - target_date.weekday()) % 7
            candidate_friday = target_date + timedelta(days=days_to_friday)
            candidate_str = candidate_friday.isoformat()
            try:
                contracts = self._alpaca.get_options_contracts(ticker, candidate_str)
            except Exception as e:
                print(f"[PM] get_options_contracts failed for {ticker} {candidate_str}: {e}")
                continue
            type_key = "put" if option_type == "P" else "call"
            matching = [c for c in contracts if c.get("type") == type_key]
            if matching:
                new_expiry_str = candidate_str
                new_contracts = matching
                break

        if not new_contracts or not new_expiry_str:
            print(f"[PM] No contracts found for {ticker} roll — cannot roll {symbol}")
            return False

        # Select nearest available strike to the current one
        new_target = min(new_contracts, key=lambda c: abs(float(c.get("strike_price", 0)) - strike))
        new_strike = float(new_target.get("strike_price", 0))
        new_symbol = new_target.get("symbol", "")

        if not new_symbol:
            print(f"[PM] New contract has no symbol — cannot roll {symbol}")
            return False

        # --- Estimate net credit ---
        # We can't fetch a real quote without a quote endpoint, so we estimate:
        # new_mark ≈ current_mark × (new_DTE / current_DTE) if same strike,
        # otherwise use avg_entry as a conservative proxy for what we can collect.
        # The position will only be rolled if new premium >= current BTC cost.
        new_dte = (date.fromisoformat(new_expiry_str) - today).days
        current_dte = max(parsed["dte"], 1)
        estimated_new_credit = current_mark * (new_dte / current_dte)

        # Net credit = estimated new sale - cost to BTC current
        net_credit = estimated_new_credit - current_mark

        if net_credit <= MIN_ROLL_NET_CREDIT:
            print(
                f"[PM] Roll {symbol} → {new_symbol}: estimated net credit "
                f"${net_credit:.4f} <= 0 — closing instead"
            )
            return False

        print(
            f"[PM] Rolling {symbol} → {new_symbol}  "
            f"strike={new_strike}  new_expiry={new_expiry_str}  "
            f"est_net_credit=${net_credit:.4f}"
        )

        # --- Execute BTC on old leg ---
        try:
            self._alpaca.submit_option_order(
                symbol=symbol,
                qty=qty,
                side="buy",
                order_type="market",
            )
        except Exception as e:
            print(f"[PM] Roll BTC leg failed for {symbol}: {e}")
            log_insight(
                source="system",
                category="error",
                insight=f"Roll BTC leg failed {symbol}: {e}",
                metadata={"symbol": symbol},
            )
            return False

        # --- Execute STO on new leg ---
        try:
            self._alpaca.submit_option_order(
                symbol=new_symbol,
                qty=qty,
                side="sell",
                order_type="market",
            )
        except Exception as e:
            print(f"[PM] Roll STO leg failed for {new_symbol}: {e}")
            log_insight(
                source="system",
                category="error",
                insight=f"Roll STO leg failed {new_symbol} (old leg already closed): {e}",
                metadata={"old_symbol": symbol, "new_symbol": new_symbol},
            )
            # Old leg is already closed; log as close and surface the error
            return False

        realized_pnl_btc = (avg_entry - current_mark) * qty * 100
        log_insight(
            source="system",
            category="decision",
            insight=(
                f"ROLL {symbol} → {new_symbol}  "
                f"new_expiry={new_expiry_str} new_strike={new_strike}  "
                f"profit_at_roll={profit_pct:.1%}  est_net_credit=${net_credit:.4f}"
            ),
            metadata={
                "old_symbol": symbol,
                "new_symbol": new_symbol,
                "ticker": ticker,
                "option_type": option_type,
                "old_strike": strike,
                "new_strike": new_strike,
                "old_expiry": parsed["expiry_date"].isoformat(),
                "new_expiry": new_expiry_str,
                "dte_at_roll": parsed["dte"],
                "avg_entry": avg_entry,
                "current_mark": current_mark,
                "profit_pct": round(profit_pct, 4),
                "estimated_net_credit": round(net_credit, 4),
                "realized_pnl_btc_leg": round(realized_pnl_btc, 2),
            },
        )

        if self._db:
            try:
                self._db.log_decision(
                    ticker=ticker,
                    action="ROLL",
                    tier="position_manager",
                    confidence=0.85,
                    reasoning=(
                        f"21-DTE roll: {symbol} → {new_symbol} "
                        f"(DTE was {parsed['dte']}, profit {profit_pct:.1%})"
                    ),
                    status="submitted",
                )
            except Exception as e:
                print(f"[PM] log_decision (roll) failed: {e}")

        return True


# -----------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------

if __name__ == "__main__":
    import json
    cfg = cfg_module.load()
    try:
        from execution.alpaca_client import AlpacaClient
        alpaca = AlpacaClient(settings=cfg)
        positions = alpaca.get_positions()
    except Exception as e:
        print(f"[PM] Alpaca unavailable: {e}")
        positions = []

    pm = PositionManager(settings=cfg, alpaca_client=alpaca if positions else None)
    result = pm.run_cycle(positions)
    print(f"[PM] Cycle complete — closed: {result['closed']}, rolled: {result['rolled']}")
