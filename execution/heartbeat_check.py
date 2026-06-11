#!/usr/bin/env python3
"""
Deadman switch for the trading loop.

Run on a systemd timer (every 5 min). If the loop's heartbeat file is stale
*during market hours*, the loop is hung / crashed / silently stopped — fire a
critical alert. This catches every silent-death mode, not just the halt-flag
restart loop (which Item 1's systemd OnFailure= covers).

Always exits 0 — alerting is a side effect, not a failure of this check.
"""
import json
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import settings as cfg_module
from execution.notifier import Notifier

HEARTBEAT_PATH = Path("logs/heartbeat")
ALERT_STATE = Path("logs/heartbeat_alert.json")  # de-dupe so we alert at most once/hour
STALE_SECONDS = 15 * 60


def market_is_open(cfg) -> bool:
    req = urllib.request.Request(
        f"{cfg.alpaca.base_url}/v2/clock",
        headers={
            "APCA-API-KEY-ID": cfg.alpaca.key,
            "APCA-API-SECRET-KEY": cfg.alpaca.secret,
        },
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return bool(json.load(r).get("is_open", False))


def _recently_alerted(now: datetime) -> bool:
    if not ALERT_STATE.exists():
        return False
    try:
        last = datetime.fromisoformat(json.load(open(ALERT_STATE))["last"])
        return (now - last).total_seconds() < 3600
    except Exception:
        return False


def main() -> None:
    cfg = cfg_module.load()

    # Only meaningful during market hours — outside them the loop legitimately
    # sleeps. If we can't determine market state, stay quiet (no false alarms).
    try:
        if not market_is_open(cfg):
            return
    except Exception:
        return

    now = datetime.now(timezone.utc)
    age = None
    if HEARTBEAT_PATH.exists():
        try:
            ts = datetime.fromisoformat(HEARTBEAT_PATH.read_text().strip())
            age = (now - ts).total_seconds()
        except Exception:
            age = None

    # A MISSING heartbeat means the loop just (re)started and hasn't written its
    # first stamp yet, or never ran at all — the latter is already covered by
    # systemd's OnFailure= alert (Item 1). Alerting here would false-positive on
    # every restart that races a timer tick, so we only treat a STALE heartbeat
    # (written, then stopped updating) as a real hang.
    if age is None:
        print("[HEARTBEAT] no heartbeat yet (loop starting or not running) — deferring to systemd OnFailure")
        return

    if age <= STALE_SECONDS:
        if ALERT_STATE.exists():
            ALERT_STATE.unlink()  # recovered → re-arm so the next stall re-alerts
        print(f"[HEARTBEAT] OK — {age / 60:.1f} min old")
        return

    if _recently_alerted(now):
        print("[HEARTBEAT] stale but alerted within the last hour — suppressing")
        return

    agestr = f"{age / 60:.1f} min old"
    try:
        Notifier(cfg).critical_alert(
            f"Trading heartbeat is STALE during market hours (heartbeat {agestr}; "
            f"staleness threshold {STALE_SECONDS // 60} min). The market loop is likely "
            f"hung, crashed, or silently stopped.\n\n"
            f"Check:  ssh workstation 'systemctl status trading; "
            f"journalctl -u trading -n 40 --no-pager'"
        )
        json.dump({"last": now.isoformat()}, open(ALERT_STATE, "w"))
        print(f"[HEARTBEAT] ALERT sent — heartbeat {agestr}")
    except Exception as e:
        print(f"[HEARTBEAT] failed to send alert: {e}")


if __name__ == "__main__":
    main()
