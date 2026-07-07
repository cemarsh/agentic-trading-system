"""
Position ledger — one brain per position.

The 2026-07 XOM open→roll collision: the wheel sold a put, and five minutes later
the position manager re-scanned broker state, didn't know the wheel had just acted,
and rolled it. Both modules were "right" in isolation; neither knew who owned the
position or when it was last touched.

This ledger makes ownership a QUERY, not an inference. It records, per symbol:
  owner        — which module opened / last acted on it
  state        — OPENED → MANAGED → CLOSING (one module authorized per transition)
  opened_at    — when the position was first taken (UTC ISO)
  last_touched — when any module last acted on it

Rules enforced through can_roll():
  - A position may not be ROLLED until position_management.min_hold_hours (24h)
    after it was opened. Rolling a day-old leg for pennies is churn, not management.
  - Stop-loss and profit-close are exempt — risk exits must never be time-gated.
  - Positions that predate the ledger (no opened_at) are manageable immediately
    (fail-open, so existing CEG/VST style legs aren't orphaned).

Persistence is a JSON file (logs/position_ledger.json) written atomically on every
mutation, so it is crash-safe across loop restarts.
"""

import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple

sys.path.insert(0, str(Path(__file__).parent.parent))

LEDGER_PATH = Path("logs/position_ledger.json")

STATE_OPENED = "OPENED"
STATE_MANAGED = "MANAGED"
STATE_CLOSING = "CLOSING"


class PositionLedger:
    def __init__(self, path: Path = LEDGER_PATH):
        self._path = Path(path)
        self._data: dict = {}
        self._load()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load(self) -> None:
        try:
            if self._path.exists():
                self._data = json.loads(self._path.read_text())
        except Exception as e:
            print(f"[LEDGER] load failed ({e}) — starting empty")
            self._data = {}

    def _save(self) -> None:
        """Atomic write — a crash mid-write must not corrupt the ledger."""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=str(self._path.parent), suffix=".tmp")
            with os.fdopen(fd, "w") as f:
                json.dump(self._data, f, indent=2)
            os.replace(tmp, self._path)
        except Exception as e:
            print(f"[LEDGER] save failed: {e}")

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    def record_open(self, symbol: str, owner: str) -> None:
        """Called by the module that OPENS a position, immediately after submit."""
        now = datetime.now(timezone.utc).isoformat()
        self._data[symbol] = {
            "owner": owner,
            "state": STATE_OPENED,
            "opened_at": now,
            "last_touched": now,
        }
        self._save()

    def touch(self, symbol: str, owner: str, state: Optional[str] = None) -> None:
        """Called by a module that ACTS on an existing position (roll, close, stop)."""
        now = datetime.now(timezone.utc).isoformat()
        entry = self._data.setdefault(
            symbol, {"owner": owner, "state": STATE_OPENED, "opened_at": None}
        )
        entry["owner"] = owner
        entry["last_touched"] = now
        if state:
            entry["state"] = state
        self._save()

    def sync(self, positions: list) -> None:
        """Reconcile against live broker positions: drop entries for symbols no
        longer held; register unknown symbols with opened_at=None (pre-ledger)."""
        held = {p.get("symbol") for p in positions or []}
        changed = False
        for symbol in list(self._data):
            if symbol not in held:
                del self._data[symbol]
                changed = True
        for symbol in held:
            if symbol and symbol not in self._data:
                self._data[symbol] = {
                    "owner": "unknown",
                    "state": STATE_MANAGED,   # predates the ledger → manageable now
                    "opened_at": None,
                    "last_touched": None,
                }
                changed = True
        if changed:
            self._save()

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get(self, symbol: str) -> Optional[dict]:
        return self._data.get(symbol)

    def age_hours(self, symbol: str) -> Optional[float]:
        entry = self._data.get(symbol)
        if not entry or not entry.get("opened_at"):
            return None
        try:
            opened = datetime.fromisoformat(entry["opened_at"])
            return (datetime.now(timezone.utc) - opened).total_seconds() / 3600.0
        except Exception:
            return None

    def can_roll(self, symbol: str, min_hold_hours: float) -> Tuple[bool, str]:
        """True if the position is old enough (or old enough to be unknown) to roll.
        Risk exits (stop-loss, profit-close) must NOT consult this — they are exempt."""
        age = self.age_hours(symbol)
        if age is None:
            return True, "no open timestamp (pre-ledger position) — manageable"
        if age < min_hold_hours:
            owner = (self._data.get(symbol) or {}).get("owner", "?")
            return False, (
                f"opened {age:.1f}h ago by '{owner}' — min hold {min_hold_hours:g}h "
                f"before a roll"
            )
        return True, f"held {age:.1f}h"
