"""
Event Odds — prediction-market probabilities for scheduled macro events.

A 2-week CSP that spans a contested FOMC decision is a binary macro bet, the same
way a CSP spanning earnings is a binary company bet — and the earnings gate already
refuses the second. Kalshi (CFTC-regulated) prices these events continuously, and its
market-data endpoints are public: no account, no key, no wallet. This module only
READS those prices. It never trades on a prediction market.

Two kinds of watched event (config: event_odds.watch):

  window — a scheduled, mutually exclusive event (FOMC decision). Risk is the chance
           the most likely outcome does NOT happen: 1 - P(modal). It only matters to a
           CSP whose expiry is on or after the resolution date.
  level  — a slow-moving condition (recession). Risk is P(yes); it applies to every
           new CSP regardless of expiry, because it is a state, not a date.

Signal modules propose; they don't decide. verdict() returns (ok, reason) and the
wheel treats it like book_health(): checked once per cycle, before any candidate.
In mode "shadow" the wheel only journals what the gate WOULD have blocked, so the
gate can be judged against real outcomes before it is allowed to cost a trade.

The feed is optional and FAILS OPEN: no snapshot, or one older than max_age_hours,
means no macro verdict — the wheel trades on its own gates exactly as before. This
is the opposite of the IV gate on purpose: IV is the wheel's core input, event odds
are an overlay.

Usage:
    python execution/event_odds.py            # fetch now, print odds + verdict for the next expiry
    python execution/event_odds.py --json     # raw snapshot
"""
import argparse
import json
import sys
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import requests

sys.path.insert(0, str(Path(__file__).parent.parent))

KALSHI_API = "https://api.elections.kalshi.com/trade-api/v2"
USER_AGENT = "trading-engine/event-odds (read-only market data)"


@dataclass
class WatchSpec:
    name: str
    series: str
    kind: str              # "window" | "level"
    threshold: float       # window: 1 - P(modal) >= this; level: P(yes) >= this


def _f(x: Any) -> float | None:
    try:
        return None if x in (None, "") else float(x)
    except (TypeError, ValueError):
        return None


def market_prob(m: dict) -> float | None:
    """Mid of the YES bid/ask; last trade when the book is one-sided or empty.

    A wide book says nothing: a 0.01/0.99 quote has a "mid" of 0.50 that no one
    would trade at. Only use the mid when the spread is tight enough to mean it.
    """
    bid = _f(m.get("yes_bid_dollars"))
    ask = _f(m.get("yes_ask_dollars"))
    last = _f(m.get("last_price_dollars"))
    if bid is not None and ask is not None and ask > 0 and (ask - bid) <= 0.10:
        return round((bid + ask) / 2, 4)
    return last


def _prev_prob(m: dict) -> float | None:
    return _f(m.get("previous_price_dollars"))


def summarize_event(ev: dict, spec: WatchSpec) -> dict | None:
    """Reduce one Kalshi event (with nested markets) to what the gate needs."""
    markets = [m for m in ev.get("markets") or [] if m.get("status") in ("active", "open")]
    if not markets:
        return None
    outcomes = []
    for m in markets:
        p = market_prob(m)
        if p is None:
            continue
        outcomes.append({
            "label": m.get("yes_sub_title") or m.get("subtitle") or m.get("ticker"),
            "ticker": m.get("ticker"),
            "prob": p,
            "prev_prob": _prev_prob(m),
            "open_interest": _f(m.get("open_interest_fp")),
        })
    if not outcomes:
        return None
    outcomes.sort(key=lambda o: o["prob"], reverse=True)

    # Resolution time: the event's strike_date when it has one (FOMC), otherwise the
    # earliest market close. Level events resolve far out; their date is informational.
    resolves = ev.get("strike_date") or min(
        (m.get("close_time") for m in markets if m.get("close_time")), default=None)

    if spec.kind == "window":
        # Mutually exclusive outcomes: probabilities should sum to ~1. Normalise so a
        # book quoted 55/45/1/1/1 doesn't read as 103% certain of something.
        total = sum(o["prob"] for o in outcomes) or 1.0
        modal = outcomes[0]["prob"] / total
        risk = round(1 - modal, 4)
    else:
        # Level: single yes/no market per event.
        risk = outcomes[0]["prob"]

    return {
        "name": spec.name,
        "series": spec.series,
        "kind": spec.kind,
        "event_ticker": ev.get("event_ticker"),
        "title": ev.get("title"),
        "resolves_at": resolves,
        "risk": risk,
        "threshold": spec.threshold,
        "outcomes": outcomes[:4],
    }


class EventOdds:
    def __init__(self, settings=None, session: requests.Session | None = None):
        self.cfg = getattr(settings, "event_odds", None) if settings is not None else None
        self._session = session or requests.Session()
        self._session.headers.setdefault("User-Agent", USER_AGENT)

    @property
    def enabled(self) -> bool:
        return bool(self.cfg and getattr(self.cfg, "enabled", False))

    @property
    def mode(self) -> str:
        return (getattr(self.cfg, "mode", "shadow") or "shadow") if self.cfg else "shadow"

    def watch_specs(self) -> list[WatchSpec]:
        out = []
        for w in (getattr(self.cfg, "watch", None) or []):
            try:
                out.append(WatchSpec(name=str(w["name"]), series=str(w["series"]),
                                     kind=str(w.get("kind", "window")),
                                     threshold=float(w["threshold"])))
            except (KeyError, TypeError, ValueError) as e:
                print(f"[EVENT] ignoring malformed watch entry {w!r}: {e}")
        return out

    def _fetch_series(self, series: str) -> list[dict]:
        r = self._session.get(
            f"{KALSHI_API}/events",
            params={"series_ticker": series, "status": "open",
                    "with_nested_markets": "true", "limit": "10"},
            timeout=15,
        )
        r.raise_for_status()
        return r.json().get("events") or []

    def fetch(self) -> dict:
        """One snapshot of every watched series. Per-series failures are recorded,
        not raised, so one dead series can't blank the others."""
        events: list[dict] = []
        errors: dict[str, str] = {}
        for spec in self.watch_specs():
            try:
                for ev in self._fetch_series(spec.series):
                    s = summarize_event(ev, spec)
                    if s:
                        events.append(s)
            except Exception as e:
                errors[spec.series] = str(e)[:200]
        return {
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "source": "kalshi",
            "events": events,
            "errors": errors,
        }


def _parse_ts(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def snapshot_age_hours(snapshot: dict | None, now: datetime | None = None) -> float | None:
    ts = _parse_ts((snapshot or {}).get("fetched_at"))
    if ts is None:
        return None
    now = now or datetime.now(timezone.utc)
    return (now - ts).total_seconds() / 3600


def _describe(e: dict) -> str:
    top = ", ".join(f"{o['label']} {o['prob']:.0%}" for o in e["outcomes"][:2])
    when = (e.get("resolves_at") or "")[:10]
    if e["kind"] == "window":
        return f"{e['name']} {when} contested ({top}; surprise risk {e['risk']:.0%})"
    return f"{e['name']} at {e['risk']:.0%} ({e.get('title') or e['event_ticker']})"


def verdict(snapshot: dict | None, expiry: date, max_age_hours: float = 6.0,
            now: datetime | None = None) -> tuple[bool, str, list[dict]]:
    """
    (ok, reason, triggers) for opening a new CSP expiring on `expiry`.

    Fails open: no snapshot or a stale one returns ok=True with the reason saying
    why, so the caller can log that the overlay is blind rather than silently pass.
    """
    now = now or datetime.now(timezone.utc)
    age = snapshot_age_hours(snapshot, now)
    if age is None:
        return True, "no event-odds snapshot (overlay inactive)", []
    if age > max_age_hours:
        return True, f"event-odds snapshot is {age:.1f}h old (overlay inactive)", []

    # A CSP is exposed through expiry-day close (16:00 ET ≈ 21:00 UTC) — an FOMC at
    # 18:00 UTC on expiry day is inside the window.
    horizon = datetime(expiry.year, expiry.month, expiry.day, 21, 0, tzinfo=timezone.utc)
    triggers = []
    for e in (snapshot or {}).get("events", []):
        if e.get("risk") is None or e["risk"] < e.get("threshold", 1.0):
            continue
        if e["kind"] == "window":
            when = _parse_ts(e.get("resolves_at"))
            if when is None or when < now or when > horizon:
                continue
        triggers.append(e)
    if not triggers:
        return True, "", []
    return False, "; ".join(_describe(e) for e in triggers), triggers


def big_moves(snapshot: dict, min_move: float = 0.10) -> list[dict]:
    """Outcomes whose probability moved >= min_move since Kalshi's previous-day price.
    These are the journal-worthy signal: the market repricing a macro event."""
    out = []
    for e in (snapshot or {}).get("events", []):
        for o in e.get("outcomes", []):
            prev = o.get("prev_prob")
            if prev is None or o.get("prob") is None:
                continue
            if abs(o["prob"] - prev) >= min_move:
                out.append({"event": e["name"], "event_ticker": e["event_ticker"],
                            "outcome": o["label"], "ticker": o["ticker"],
                            "from": prev, "to": o["prob"],
                            "resolves_at": e.get("resolves_at")})
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true", help="print the raw snapshot")
    args = ap.parse_args()

    from config import settings as cfg_module
    cfg = cfg_module.load()
    eo = EventOdds(settings=cfg)
    if not eo.enabled:
        print("[EVENT] event_odds.enabled is false in strategy_params.yaml")
    snap = eo.fetch()
    if args.json:
        print(json.dumps(snap, indent=2))
        sys.exit(0)

    for e in snap["events"]:
        flag = "!" if e["risk"] >= e["threshold"] else " "
        outs = " | ".join(f"{o['label']} {o['prob']:.0%}" +
                          (f" (prev {o['prev_prob']:.0%})" if o.get("prev_prob") is not None else "")
                          for o in e["outcomes"][:3])
        print(f"{flag} {e['event_ticker']:<22} {(e['resolves_at'] or '')[:10]}  "
              f"risk {e['risk']:.0%} / thr {e['threshold']:.0%}  {outs}")
    for series, err in snap["errors"].items():
        print(f"  ERROR {series}: {err}")

    from execution.wheel_strategy import WheelStrategy
    expiry = date.fromisoformat(WheelStrategy(settings=cfg).target_expiry())
    ok, reason, _ = verdict(snap, expiry,
                            max_age_hours=getattr(cfg.event_odds, "max_age_hours", 6.0))
    print(f"\nNext CSP expiry {expiry}: {'CLEAR' if ok else 'WOULD BLOCK'}"
          f"{' — ' + reason if reason else ''}  (mode: {eo.mode})")
    for mv in big_moves(snap):
        print(f"  MOVE {mv['event_ticker']} {mv['outcome']}: {mv['from']:.0%} -> {mv['to']:.0%}")
