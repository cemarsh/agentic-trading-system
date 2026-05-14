"""
n8n watchdog — checks OpenClaw n8n health every run and emails if down.
Designed to be invoked by cron every 5 minutes.
Uses a state file to suppress repeat alerts (max 1 alert per hour).
"""
import json
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import settings as cfg_module

N8N_HEALTH_URL = "http://10.1.50.233:5678/healthz"
STATE_FILE = Path(__file__).parent.parent / "logs" / "n8n_watchdog_state.json"
ALERT_COOLDOWN_SECONDS = 3600


def _load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {"last_alert": None, "last_status": "unknown"}


def _save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


def _check_health() -> bool:
    try:
        with urllib.request.urlopen(N8N_HEALTH_URL, timeout=10) as resp:
            return resp.status == 200
    except Exception:
        return False


def _should_alert(state: dict) -> bool:
    last = state.get("last_alert")
    if not last:
        return True
    try:
        elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(last)).total_seconds()
        return elapsed >= ALERT_COOLDOWN_SECONDS
    except Exception:
        return True


def main():
    cfg = cfg_module.load()
    state = _load_state()
    healthy = _check_health()

    if healthy:
        if state.get("last_status") != "healthy":
            print(f"[WATCHDOG] n8n is UP at {N8N_HEALTH_URL}")
            # Send recovery notice if we previously alerted
            if state.get("last_alert"):
                try:
                    from execution.notifier import Notifier
                    Notifier(settings=cfg).send(
                        subject="[RECOVERED] n8n is back online",
                        body=(
                            f"n8n health check PASSED at {datetime.now(timezone.utc).isoformat()}.\n\n"
                            f"URL: {N8N_HEALTH_URL}\n\n"
                            "The NotebookLM intelligence bridge should be operational."
                        ),
                    )
                except Exception as e:
                    print(f"[WATCHDOG] recovery email failed: {e}")
        state["last_status"] = "healthy"
        state["last_alert"] = None  # reset so next outage triggers immediately
    else:
        print(f"[WATCHDOG] n8n UNREACHABLE at {N8N_HEALTH_URL}")
        state["last_status"] = "down"
        if _should_alert(state):
            try:
                from execution.notifier import Notifier
                Notifier(settings=cfg).send(
                    subject="[ALERT] n8n is DOWN — NotebookLM bridge offline",
                    body=(
                        f"n8n health check FAILED at {datetime.now(timezone.utc).isoformat()}.\n\n"
                        f"URL: {N8N_HEALTH_URL}\n\n"
                        "The NotebookLM intelligence bridge is offline. "
                        "Research signals will not be processed until n8n is restarted.\n\n"
                        "To recover on OpenClaw:\n"
                        "  ssh openclaw\n"
                        "  docker start n8n\n\n"
                        "If the container is crash-looping, check logs:\n"
                        "  docker logs --tail 50 n8n"
                    ),
                )
                state["last_alert"] = datetime.now(timezone.utc).isoformat()
                print("[WATCHDOG] alert emailed")
            except Exception as e:
                print(f"[WATCHDOG] alert email failed: {e}")

    _save_state(state)


if __name__ == "__main__":
    main()
