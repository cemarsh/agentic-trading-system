"""
Inverse ETF Hedge — allocates a small portfolio slice to inverse ETFs
during BEAR and EXTREME_BEAR regimes, exits when regime normalizes.

Default ticker: SQQQ (3x inverse Nasdaq) — high sensitivity to sell-offs.
Can be swapped for SH (1x S&P) in config for lower volatility.

Config (strategy_params.yaml):
    hedge:
      enabled: true
      tickers: ["SQQQ"]
      allocation_pct: 3.0        # % of equity per ticker in BEAR
      extreme_multiplier: 2.0    # multiply allocation in EXTREME_BEAR
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


class InverseETFHedge:
    def __init__(self, settings=None, alpaca_client=None, db_logger=None):
        self.cfg = settings
        self._alpaca = alpaca_client
        self._db = db_logger

    def _hcfg(self):
        return getattr(self.cfg, "hedge", None)

    def run(self, regime: str, positions: list, equity: float):
        """
        Evaluate hedge state and submit orders as needed.
        Called once per loop cycle after regime detection.
        """
        hcfg = self._hcfg()
        if not hcfg or not hcfg.enabled:
            return
        if not self._alpaca:
            return

        held = {p["symbol"]: int(float(p.get("qty", 0))) for p in positions}

        for ticker in hcfg.tickers:
            if regime in ("BEAR", "EXTREME_BEAR"):
                self._enter_hedge(ticker, regime, held, equity, hcfg)
            else:
                self._exit_hedge(ticker, regime, held)

    def _enter_hedge(self, ticker: str, regime: str, held: dict, equity: float, hcfg):
        alloc_pct = hcfg.allocation_pct / 100
        multiplier = getattr(hcfg, "extreme_multiplier", 2.0) if regime == "EXTREME_BEAR" else 1.0
        target_value = equity * alloc_pct * multiplier

        try:
            bars = self._alpaca.get_bars(ticker, "1Min", 1)
            if not bars:
                return
            price = bars[-1]["c"]
            if price <= 0:
                return

            target_qty = int(target_value / price)
            current_qty = held.get(ticker, 0)

            if target_qty <= current_qty:
                return  # already at or above target

            buy_qty = target_qty - current_qty
            self._alpaca.submit_order(ticker, buy_qty, "buy")
            print(
                f"[HEDGE] BUY {buy_qty}x {ticker} @ ~${price:.2f}  "
                f"regime={regime}  target=${target_value:,.0f}"
            )
            if self._db:
                self._db.log_decision(
                    ticker=ticker,
                    action="BUY",
                    tier="hedge",
                    confidence=0.95,
                    reasoning=f"Inverse ETF hedge entry — regime={regime}",
                    status="submitted",
                )
        except Exception as e:
            print(f"[HEDGE] Entry failed {ticker}: {e}")

    def _exit_hedge(self, ticker: str, regime: str, held: dict):
        qty = held.get(ticker, 0)
        if qty <= 0:
            return
        try:
            self._alpaca.submit_order(ticker, qty, "sell")
            print(f"[HEDGE] SELL {qty}x {ticker} — regime normalized to {regime}")
            if self._db:
                self._db.log_decision(
                    ticker=ticker,
                    action="SELL",
                    tier="hedge",
                    confidence=0.95,
                    reasoning=f"Exiting inverse ETF hedge — regime={regime}",
                    status="submitted",
                )
        except Exception as e:
            print(f"[HEDGE] Exit failed {ticker}: {e}")
