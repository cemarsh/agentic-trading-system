#!/usr/bin/env python3
"""
Fired by systemd `OnFailure=` when trading.service exhausts its start-limit and
enters the `failed` state — i.e. it has stopped trying to restart and the loop
is DOWN. Sends a critical email + Slack alert with the halt reason and a log tail.

Deliberately depends only on config + notifier (present in every code version),
so it can't itself fail to import.
"""
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from execution.notifier import Notifier


def main() -> None:
    state = {}
    try:
        state = json.load(open("logs/agent_state.json"))
    except Exception:
        pass

    try:
        tail = subprocess.run(
            ["journalctl", "-u", "trading", "-n", "20", "--no-pager"],
            capture_output=True, text=True, timeout=15,
        ).stdout or "(journal empty)"
    except Exception as e:
        tail = f"(could not read journal: {e})"

    msg = (
        "trading.service entered FAILED state — systemd has STOPPED restarting it.\n"
        "The trading loop is DOWN and will not trade until manually recovered.\n\n"
        f"halted={state.get('halted')}  "
        f"api_failures={state.get('api_failures')}  "
        f"network_failures={state.get('network_failures')}\n\n"
        "Recover (after confirming connectivity is healthy):\n"
        "  1. Reset logs/agent_state.json -> halted=false, api_failures=0, network_failures=0\n"
        "  2. ssh workstation 'sudo systemctl reset-failed trading && sudo systemctl restart trading'\n\n"
        "--- last 20 journal lines ---\n" + tail
    )

    try:
        Notifier().critical_alert(msg)
        print("[ALERT] failure alert sent")
    except Exception as e:
        print(f"[ALERT] failed to send: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
