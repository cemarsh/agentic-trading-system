#!/usr/bin/env python3
"""
Deadman switch for the trading loop.

Run on a systemd timer (every 5 min). If the loop's heartbeat file is stale
*during market hours*, the loop is hung / crashed / silently stopped — this
watchdog ACTS, it doesn't just email:
  1. Cancels all open orders (risk.deadman_cancel_orders, default true) — a hung
     loop during a gap-down means unmanaged resting orders in a falling market.
     An alert read 90 minutes later is not risk management.
  2. Fires the critical alert (email + Slack).

Independently of staleness, every run pushes a heartbeat event to Splunk HEC
(SPLUNK_HEC_URL + SPLUNK_HEC_TOKEN in .env, optional) so alerting can also run
off a scheduled Splunk search that does not depend on this process being alive.

Always exits 0 — alerting is a side effect, not a failure of this check.
"""
import json
import os
import ssl
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


def push_splunk_heartbeat(status: str, age_seconds, market_open: bool) -> None:
    """Best-effort heartbeat event to Splunk HEC. Never raises."""
    url = os.environ.get("SPLUNK_HEC_URL", "")
    token = os.environ.get("SPLUNK_HEC_TOKEN", "")
    if not url or not token:
        return
    try:
        payload = json.dumps({
            "event": {
                "app": "trading",
                "type": "heartbeat",
                "status": status,
                "age_seconds": age_seconds,
                "market_open": market_open,
            },
            "sourcetype": "trading:heartbeat",
            "index": os.environ.get("SPLUNK_HEC_INDEX", "application"),
        }).encode()
        req = urllib.request.Request(
            f"{url.rstrip('/')}/services/collector/event",
            data=payload,
            headers={"Authorization": f"Splunk {token}", "Content-Type": "application/json"},
        )
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE  # self-signed HEC cert on the LAN
        urllib.request.urlopen(req, timeout=5, context=ctx)
    except Exception as e:
        print(f"[HEARTBEAT] Splunk HEC push failed: {e}")


def deadman_cancel_orders(cfg) -> str:
    """Cancel all open orders when the loop is dead. Returns a summary line for
    the alert body."""
    risk = getattr(cfg, "risk", None)
    if risk is not None and not getattr(risk, "deadman_cancel_orders", True):
        return "Dead-man order cancellation is DISABLED (risk.deadman_cancel_orders: false)."
    try:
        from execution.alpaca_client import AlpacaClient
        cancelled = AlpacaClient(settings=cfg).cancel_all_orders()
        n = len(cancelled) if isinstance(cancelled, list) else 0
        print(f"[HEARTBEAT] dead-man switch: cancelled {n} open order(s)")
        return f"Dead-man switch: CANCELLED {n} open order(s) so nothing rests unmanaged."
    except Exception as e:
        print(f"[HEARTBEAT] dead-man cancel failed: {e}")
        return f"Dead-man switch FAILED to cancel open orders: {e} — check the account manually."


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
        market_open = market_is_open(cfg)
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

    stale = age is not None and age > STALE_SECONDS
    status = "missing" if age is None else ("stale" if stale else "ok")
    push_splunk_heartbeat(status, age, market_open)

    if not market_open:
        return

    # A MISSING heartbeat means the loop just (re)started and hasn't written its
    # first stamp yet, or never ran at all — the latter is already covered by
    # systemd's OnFailure= alert (Item 1). Alerting here would false-positive on
    # every restart that races a timer tick, so we only treat a STALE heartbeat
    # (written, then stopped updating) as a real hang.
    if age is None:
        print("[HEARTBEAT] no heartbeat yet (loop starting or not running) — deferring to systemd OnFailure")
        return

    if not stale:
        if ALERT_STATE.exists():
            ALERT_STATE.unlink()  # recovered → re-arm so the next stall re-alerts
        print(f"[HEARTBEAT] OK — {age / 60:.1f} min old")
        return

    if _recently_alerted(now):
        print("[HEARTBEAT] stale but alerted within the last hour — suppressing")
        return

    # ACT first (cancel resting orders), then alert — the watchdog has authority,
    # not just a voice.
    cancel_summary = deadman_cancel_orders(cfg)

    agestr = f"{age / 60:.1f} min old"
    try:
        Notifier(cfg).critical_alert(
            f"Trading heartbeat is STALE during market hours (heartbeat {agestr}; "
            f"staleness threshold {STALE_SECONDS // 60} min). The market loop is likely "
            f"hung, crashed, or silently stopped.\n\n"
            f"{cancel_summary}\n\n"
            f"Check:  ssh workstation 'systemctl status trading; "
            f"journalctl -u trading -n 40 --no-pager'"
        )
        json.dump({"last": now.isoformat()}, open(ALERT_STATE, "w"))
        print(f"[HEARTBEAT] ALERT sent — heartbeat {agestr}")
    except Exception as e:
        print(f"[HEARTBEAT] failed to send alert: {e}")


if __name__ == "__main__":
    main()
