"""
Market Regime Detector.
Uses SPY intraday % change as a proxy for market regime.
Regimes: BULL, NEUTRAL, BEAR, EXTREME_BEAR

Called each loop cycle. Cheap — one bar fetch.
"""

import sys
from pathlib import Path
from typing import Literal

sys.path.insert(0, str(Path(__file__).parent.parent))

RegimeType = Literal["BULL", "NEUTRAL", "BEAR", "EXTREME_BEAR"]


class RegimeDetector:
    def __init__(self, settings=None, alpaca_client=None):
        self.cfg = settings
        self._alpaca = alpaca_client
        self._current: RegimeType = "NEUTRAL"
        self._spy_change_pct: float = 0.0

    def detect(self) -> RegimeType:
        """Fetch SPY intraday change and return current regime."""
        if not self._alpaca:
            return "NEUTRAL"

        try:
            # Full-day 1-min bars — use first open vs latest close
            bars = self._alpaca.get_bars("SPY", "1Min", 390)
            if len(bars) < 2:
                return self._current

            day_open = bars[0]["o"]
            current = bars[-1]["c"]
            if day_open == 0:
                return self._current

            pct = (current - day_open) / day_open * 100
            self._spy_change_pct = pct

            cfg = getattr(self.cfg, "regime", None)
            bear_thresh = getattr(cfg, "bear_spy_threshold", -2.0)
            extreme_thresh = getattr(cfg, "extreme_spy_threshold", -4.0)

            if pct <= extreme_thresh:
                new_regime: RegimeType = "EXTREME_BEAR"
            elif pct <= bear_thresh:
                new_regime = "BEAR"
            elif pct >= 2.0:
                new_regime = "BULL"
            else:
                new_regime = "NEUTRAL"

            if new_regime != self._current:
                print(
                    f"[REGIME] {self._current} → {new_regime}  "
                    f"(SPY {pct:+.2f}% intraday)"
                )

            self._current = new_regime
            return self._current

        except Exception as e:
            print(f"[REGIME] Detection error: {e}")
            return self._current

    @property
    def current(self) -> RegimeType:
        return self._current

    @property
    def spy_change_pct(self) -> float:
        return self._spy_change_pct

    def allocation_multiplier(self) -> float:
        """
        Returns a scalar to multiply position sizing by based on regime.
        BULL/NEUTRAL = 1.0 (full), BEAR = 0.5 (half), EXTREME_BEAR = 0.0 (no new entries).
        """
        return {
            "BULL": 1.0,
            "NEUTRAL": 1.0,
            "BEAR": 0.5,
            "EXTREME_BEAR": 0.0,
        }.get(self._current, 1.0)

    def target_delta_override(self) -> float | None:
        """
        In BEAR regime, widen OTM to reduce assignment risk.
        Returns override delta or None (use config default).
        """
        if self._current == "BEAR":
            return 0.15       # wider OTM than config's 0.25
        if self._current == "EXTREME_BEAR":
            return None       # no new entries — caller should check allocation_multiplier
        return None
