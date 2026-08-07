"""Signal-promoted wheel universe — the policy → execution pathway.

The gap this closes: policy_monitor flagged 19 tickers in a single week and the
system placed zero orders from any of them, because the wheel only ever iterates
a hand-edited list in strategy_params.yaml. Signals were, structurally, unable to
reach execution. The weekly wrap-up called this out; so did the daily journal
("Review whether policy_monitor tier has an execution pathway or is purely
observational" — 2026-08-07).

What this does NOT do is let a signal skip a gate. A promoted ticker becomes a
*candidate*, nothing more: it still has to clear the IV-rank floor, the NBBO
credit floor, the earnings gate, and the risk gate's position/sector caps, and it
still gets sized by the same headroom math. Signals inform selection; gates decide.

The important sequencing detail: the IV gate is hard (no history -> no trade), and
IV history only accrues for tickers that iv_tracker snapshots. So promotion's real
job is to get a ticker INTO the snapshot universe. A freshly promoted name cannot
trade for MIN_HISTORY_DAYS (15) of snapshots — by design. Promotion starts a clock;
it does not open a door.

Entries expire if the signal stops repeating, so one stray headline doesn't
permanently widen the universe.
"""

import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

STORE = Path(__file__).parent.parent / "logs" / "dynamic_universe.json"

DEFAULT_MAX_TICKERS = 8      # ceiling on how far a signal stream may widen the universe
DEFAULT_TTL_DAYS = 30        # drop a name this long after its last supporting signal


def _load() -> Dict[str, dict]:
    if not STORE.exists():
        return {}
    try:
        data = json.loads(STORE.read_text())
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _save(entries: Dict[str, dict]) -> None:
    try:
        STORE.parent.mkdir(parents=True, exist_ok=True)
        STORE.write_text(json.dumps(entries, indent=2, sort_keys=True))
    except OSError as e:
        print(f"[UNIVERSE] could not persist dynamic universe: {e}")


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def promote(tickers: Iterable[str], source: str, reason: str = "",
            exclude: Optional[Iterable[str]] = None,
            max_tickers: int = DEFAULT_MAX_TICKERS) -> List[str]:
    """Record signal-flagged tickers as universe candidates. Returns names newly added.

    `exclude` should carry the static universe plus quarantined names — promoting a
    ticker the wheel already trades is a no-op, and promoting a quarantined one must
    never happen (the risk gate would reject it anyway, but generating the candidate
    at all is the wasted-evaluation bug that was fixed upstream in W28).
    """
    excluded = {t.upper() for t in (exclude or [])}
    entries = _load()
    today = _today()
    added: List[str] = []

    for raw in tickers or []:
        ticker = (raw or "").strip().upper()
        if not ticker or ticker in excluded:
            continue
        if ticker in entries:
            # Re-observed: refresh the TTL and count the corroboration.
            entries[ticker]["last_seen"] = today
            entries[ticker]["hits"] = entries[ticker].get("hits", 1) + 1
            continue
        if len(entries) >= max_tickers:
            continue
        entries[ticker] = {
            "first_seen": today,
            "last_seen": today,
            "source": source,
            "reason": reason[:200],
            "hits": 1,
        }
        added.append(ticker)

    _save(entries)
    return added


def active(ttl_days: int = DEFAULT_TTL_DAYS,
           exclude: Optional[Iterable[str]] = None) -> List[str]:
    """Currently promoted tickers, expiring any whose last signal has gone stale."""
    entries = _load()
    if not entries:
        return []

    cutoff = date.today() - timedelta(days=ttl_days)
    excluded = {t.upper() for t in (exclude or [])}
    live: Dict[str, dict] = {}
    expired: List[str] = []

    for ticker, meta in entries.items():
        try:
            last = date.fromisoformat(meta.get("last_seen", ""))
        except ValueError:
            last = date.today()
        if last < cutoff:
            expired.append(ticker)
        else:
            live[ticker] = meta

    if expired:
        print(f"[UNIVERSE] expiring stale signal candidates: {', '.join(sorted(expired))}")
        _save(live)

    return sorted(t for t in live if t not in excluded)


def describe() -> str:
    """One-line summary for the morning briefing / journal."""
    entries = _load()
    if not entries:
        return "no signal-promoted tickers"
    parts = [f"{t}(x{m.get('hits', 1)}, {m.get('source', '?')})"
             for t, m in sorted(entries.items())]
    return ", ".join(parts)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Inspect the signal-promoted wheel universe")
    parser.add_argument("--list", action="store_true", help="Show active promoted tickers")
    parser.add_argument("--clear", action="store_true", help="Remove all promoted tickers")
    args = parser.parse_args()

    if args.clear:
        _save({})
        print("[UNIVERSE] cleared")
    else:
        print(f"[UNIVERSE] {describe()}")
        print(f"[UNIVERSE] active: {', '.join(active()) or '(none)'}")
