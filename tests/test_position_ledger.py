"""Tests for the position ledger — ownership, min-hold, sync reconciliation."""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from execution.position_ledger import PositionLedger


def _ledger(tmp_path):
    return PositionLedger(path=tmp_path / "ledger.json")


def test_record_open_and_min_hold_blocks_roll(tmp_path):
    led = _ledger(tmp_path)
    led.record_open("XOM260717P00105000", owner="wheel")
    can, why = led.can_roll("XOM260717P00105000", min_hold_hours=24)
    assert not can
    assert "wheel" in why


def test_old_position_can_roll(tmp_path):
    led = _ledger(tmp_path)
    led.record_open("CCJ260717P00098000", owner="wheel")
    # Backdate the open
    led._data["CCJ260717P00098000"]["opened_at"] = (
        datetime.now(timezone.utc) - timedelta(hours=30)
    ).isoformat()
    can, _ = led.can_roll("CCJ260717P00098000", min_hold_hours=24)
    assert can


def test_pre_ledger_position_manageable(tmp_path):
    led = _ledger(tmp_path)
    led.sync([{"symbol": "CEG260717P00280000"}])
    can, why = led.can_roll("CEG260717P00280000", min_hold_hours=24)
    assert can
    assert "pre-ledger" in why


def test_sync_drops_closed_positions(tmp_path):
    led = _ledger(tmp_path)
    led.record_open("A", owner="wheel")
    led.record_open("B", owner="wheel")
    led.sync([{"symbol": "B"}])
    assert led.get("A") is None
    assert led.get("B") is not None


def test_persistence_across_instances(tmp_path):
    path = tmp_path / "ledger.json"
    led = PositionLedger(path=path)
    led.record_open("XOM260717P00105000", owner="wheel")
    led2 = PositionLedger(path=path)
    entry = led2.get("XOM260717P00105000")
    assert entry and entry["owner"] == "wheel" and entry["state"] == "OPENED"


def test_touch_updates_owner_and_state(tmp_path):
    led = _ledger(tmp_path)
    led.record_open("SYM", owner="wheel")
    led.touch("SYM", owner="position_manager", state="CLOSING")
    entry = led.get("SYM")
    assert entry["owner"] == "position_manager"
    assert entry["state"] == "CLOSING"
