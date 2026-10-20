"""The crash-loop detector in heartbeat_check: a loop that dies and respawns every
~75s keeps its heartbeat fresh, so only systemd's restart counter sees it."""

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from execution import heartbeat_check as hb


def test_storm_is_a_jump_between_ticks():
    assert hb.restart_storm(10, 13)
    assert not hb.restart_storm(10, 12)
    assert not hb.restart_storm(None, 13)
    assert not hb.restart_storm(13, 0)  # manual restart reset the counter


def test_alert_fires_once_an_hour_then_resumes(tmp_path):
    now = datetime(2026, 10, 20, 14, 0, tzinfo=timezone.utc)
    state = tmp_path / "restarts.json"
    with patch.object(hb, "RESTART_STATE", state), \
         patch.object(hb, "service_restarts", side_effect=[0, 4, 8, 12]), \
         patch.object(hb, "Notifier") as notifier, \
         patch.object(hb.subprocess, "run", return_value=MagicMock(stdout="tail")):
        hb.check_restart_storm(MagicMock(), now)                      # baseline
        hb.check_restart_storm(MagicMock(), now + timedelta(minutes=5))   # +4 → alert
        hb.check_restart_storm(MagicMock(), now + timedelta(minutes=10))  # +4, within the hour
        hb.check_restart_storm(MagicMock(), now + timedelta(minutes=70))  # +4, hour over
    assert notifier.return_value.critical_alert.call_count == 2
    saved = json.loads(state.read_text())
    assert saved["count"] == 12 and saved["last_alert"]
