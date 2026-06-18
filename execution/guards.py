"""
Guards against the recurring "repeat-on-condition without a cap" bug class.

The halt loop, ladder runaway, whale re-buy, and hardware-alert spam all shared one
root flaw: an action fired every loop cycle while a condition held, with no record of
having already acted. Use one of these two primitives whenever you take a side-effect
(order, alert, write) inside the loop, and the bug can't recur by construction.

Idempotency — act on each distinct thing exactly once:

    from execution.guards import has_acted, mark_acted
    if has_acted(state, "whale_acted", fp):
        continue
    do_the_thing()
    mark_acted(state, "whale_acted", fp)
    save_state(state)            # persist so it survives a restart

    # ...or the combined form when you act regardless of the action's outcome:
    from execution.guards import acted_once
    if acted_once(state, "ipo_seen", ticker):   # True only the first time
        do_the_thing()

Rate-limit — act at most once per N seconds per key:

    from execution.guards import Cooldown
    self._cd = Cooldown(3600)                    # in-memory (resets on restart)
    if self._cd.ready("cpu"):
        alert(...)
    # cross-restart cooldown: Cooldown(3600, store=state.setdefault("_cooldowns", {}))

`store` is any plain dict you persist (e.g. the loop's agent_state). Keys must be
JSON-serializable (str/num) so they survive in agent_state.json.
"""
import time
from typing import Optional

DEFAULT_MAXLEN = 500


def has_acted(store: dict, namespace: str, key) -> bool:
    """True if `key` was already recorded under `namespace`. No mutation."""
    return key in store.get(namespace, ())


def mark_acted(store: dict, namespace: str, key, maxlen: int = DEFAULT_MAXLEN) -> None:
    """Record `key` under `namespace`, keeping only the last `maxlen`. Mutates `store`
    in place — persist it afterward so the record survives a restart."""
    seen = store.setdefault(namespace, [])
    if key in seen:
        return
    seen.append(key)
    if len(seen) > maxlen:
        del seen[:-maxlen]


def acted_once(store: dict, namespace: str, key, maxlen: int = DEFAULT_MAXLEN) -> bool:
    """Combined check+record: True the FIRST time `key` is seen (recording it), False
    every time after. Use when you act regardless of the action's outcome."""
    if has_acted(store, namespace, key):
        return False
    mark_acted(store, namespace, key, maxlen)
    return True


class Cooldown:
    """Allow an action at most once per `seconds` per key.

    In-memory by default (monotonic clock; resets on process restart) — right for
    alert de-spam. Pass a persisted `store` dict (wall-clock) for cooldowns that must
    survive restarts; persist that dict yourself after a True.
    """

    def __init__(self, seconds: float, store: Optional[dict] = None):
        self.seconds = seconds
        self._persisted = store is not None
        self._store = store if store is not None else {}
        self._now = time.time if self._persisted else time.monotonic

    def ready(self, key: str = "_") -> bool:
        """True if the cooldown for `key` has elapsed (and resets it); else False."""
        now = self._now()
        last = self._store.get(key)
        if last is not None and (now - last) < self.seconds:
            return False
        self._store[key] = now
        return True
