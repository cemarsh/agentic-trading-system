"""
Pre-trade risk gate — the FJET lesson (2026-06-16: one module bought 4,570 shares,
~29% of the book, and nothing stopped it).

Signal modules PROPOSE trades; only this gate SIZES them. Every equity order and
every new CSP passes through check_equity_order() / check_option_collateral()
before submission. A reject here is a hard reject — the caller logs it and skips.

Three checks, all against LIVE broker positions (not module-internal state):
  1. Position cap  — no order may push one ticker's exposure past
     risk.max_position_pct of equity (default 5%).
  2. IPO quarantine — quarantined tickers (config list + protection.no_auto_manage)
     get risk.quarantine_max_position_pct instead (default 1%).
  3. Sector cap    — total exposure in one correlated bucket (risk.sector_map)
     may not exceed risk.sector_cap_pct of equity (default 20%). Exposure counts
     equity market value PLUS short-put collateral (strike × 100 × qty), because
     an assigned CSP becomes the shares.

Fail-safe direction: if equity is unknown (account fetch failed), the gate
REJECTS — an unsized book must not take on more risk.

Usage:
    gate = RiskGate(settings=cfg)
    gate.refresh(positions, equity)          # once per loop cycle
    ok, reason = gate.check_equity_order("FJET", qty * price)
    if not ok:
        print(f"[RISK] blocked: {reason}")
"""

import re
import sys
from pathlib import Path
from typing import Dict, Optional, Tuple

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import settings as cfg_module

# OCC option symbol: TICKER + YYMMDD + C/P + 8-digit strike×1000
_OCC_RE = re.compile(r"^([A-Z]{1,6})(\d{6})([CP])(\d{8})$")


def _occ_parts(symbol: str) -> Optional[Tuple[str, str, float]]:
    """Return (underlying, 'C'|'P', strike) for an OCC symbol, else None."""
    m = _OCC_RE.match(symbol.strip().upper())
    if not m:
        return None
    return m.group(1), m.group(3), int(m.group(4)) / 1000.0


class RiskGate:
    def __init__(self, settings=None):
        self.cfg = settings or cfg_module.load()
        risk = getattr(self.cfg, "risk", None)
        self.max_position_pct = getattr(risk, "max_position_pct", 5.0) if risk else 5.0
        self.quarantine_pct = getattr(risk, "quarantine_max_position_pct", 1.0) if risk else 1.0
        self.sector_cap_pct = getattr(risk, "sector_cap_pct", 20.0) if risk else 20.0

        quarantined = set(getattr(risk, "quarantined_tickers", None) or [])
        # IPO starters excluded from auto-management are speculative by definition —
        # they are quarantined whether or not the risk list was kept in sync.
        prot = getattr(self.cfg, "protection", None)
        quarantined |= set(getattr(prot, "no_auto_manage", None) or [])
        self.quarantined = quarantined

        # ticker → sector bucket
        self._sector_of: Dict[str, str] = {}
        for sector, tickers in (getattr(risk, "sector_map", None) or {}).items():
            for t in tickers or []:
                self._sector_of[t.upper()] = sector

        self._equity: float = 0.0
        self._exposure: Dict[str, float] = {}       # ticker → $ exposure
        self._sector_exposure: Dict[str, float] = {}  # sector → $ exposure
        self._synced = False

    # ------------------------------------------------------------------
    # State sync
    # ------------------------------------------------------------------

    def refresh(self, positions: list, equity: float) -> None:
        """Rebuild exposure from live broker positions. Call once per loop cycle."""
        self._equity = float(equity or 0)
        self._exposure = {}
        for p in positions or []:
            symbol = (p.get("symbol") or "").upper()
            occ = _occ_parts(symbol)
            if occ:
                underlying, opt_type, strike = occ
                qty = float(p.get("qty", 0) or 0)
                # Short puts carry assignment exposure = collateral. Short calls are
                # covered by shares already counted; long options risk only premium.
                if opt_type == "P" and qty < 0:
                    self._add(underlying, strike * 100 * abs(qty))
            else:
                try:
                    self._add(symbol, abs(float(p.get("market_value", 0) or 0)))
                except (TypeError, ValueError):
                    pass
        self._sector_exposure = {}
        for ticker, dollars in self._exposure.items():
            sector = self._sector_of.get(ticker)
            if sector:
                self._sector_exposure[sector] = self._sector_exposure.get(sector, 0.0) + dollars
        self._synced = True

    def _add(self, ticker: str, dollars: float) -> None:
        self._exposure[ticker] = self._exposure.get(ticker, 0.0) + dollars

    # ------------------------------------------------------------------
    # Checks
    # ------------------------------------------------------------------

    def _position_cap_pct(self, ticker: str) -> float:
        return self.quarantine_pct if ticker.upper() in self.quarantined else self.max_position_pct

    def _check(self, ticker: str, added_exposure: float, kind: str) -> Tuple[bool, str]:
        ticker = ticker.upper()
        if not self._synced or self._equity <= 0:
            return False, f"{kind} {ticker}: equity unknown — gate fails closed"
        if added_exposure <= 0:
            return True, "no added exposure"

        # 1+2. Position cap (quarantine-aware)
        cap_pct = self._position_cap_pct(ticker)
        cap_dollars = self._equity * cap_pct / 100.0
        new_total = self._exposure.get(ticker, 0.0) + added_exposure
        if new_total > cap_dollars:
            label = "quarantined " if ticker in self.quarantined else ""
            return False, (
                f"{kind} {ticker}: would hold ${new_total:,.0f} "
                f"> {cap_pct:g}% cap (${cap_dollars:,.0f}) of ${self._equity:,.0f} equity"
                f" [{label}position cap]"
            )

        # 3. Sector correlation cap
        sector = self._sector_of.get(ticker)
        if sector:
            sector_cap = self._equity * self.sector_cap_pct / 100.0
            new_sector = self._sector_exposure.get(sector, 0.0) + added_exposure
            if new_sector > sector_cap:
                return False, (
                    f"{kind} {ticker}: sector '{sector}' would hold ${new_sector:,.0f} "
                    f"> {self.sector_cap_pct:g}% cap (${sector_cap:,.0f}) [sector cap]"
                )

        return True, "ok"

    def check_equity_order(self, ticker: str, notional: float) -> Tuple[bool, str]:
        """Gate a share purchase of `notional` dollars. Hard 5%/1% position cap."""
        return self._check(ticker, notional, "equity buy")

    def check_option_collateral(self, ticker: str, collateral: float) -> Tuple[bool, str]:
        """Gate a new short put by its assignment collateral (strike × 100 × qty).
        The per-trade size cap for CSPs lives in the wheel (15%); this adds the
        quarantine and sector-correlation caps on top."""
        ticker = ticker.upper()
        if ticker in self.quarantined:
            # Quarantined names don't belong in a premium-selling book at all.
            return False, f"CSP {ticker}: ticker is quarantined — no options exposure allowed"
        if not self._synced or self._equity <= 0:
            return False, f"CSP {ticker}: equity unknown — gate fails closed"
        sector = self._sector_of.get(ticker)
        if sector:
            sector_cap = self._equity * self.sector_cap_pct / 100.0
            new_sector = self._sector_exposure.get(sector, 0.0) + collateral
            if new_sector > sector_cap:
                return False, (
                    f"CSP {ticker}: sector '{sector}' would hold ${new_sector:,.0f} "
                    f"> {self.sector_cap_pct:g}% cap (${sector_cap:,.0f}) [sector cap]"
                )
        return True, "ok"

    def record_fill(self, ticker: str, added_exposure: float) -> None:
        """Optimistically add just-submitted exposure so multiple orders in the SAME
        cycle can't each pass a cap that only fits one of them."""
        ticker = ticker.upper()
        self._add(ticker, added_exposure)
        sector = self._sector_of.get(ticker)
        if sector:
            self._sector_exposure[sector] = self._sector_exposure.get(sector, 0.0) + added_exposure
