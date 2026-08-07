"""Tests for the signal-promoted wheel universe (policy -> execution pathway).

The property under test is restraint: promotion widens the CANDIDATE set and
nothing else. It must respect the quarantine list, refuse to grow without bound,
and expire names whose signal stops repeating.
"""

import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from execution import dynamic_universe as du


@pytest.fixture(autouse=True)
def _isolated_store(tmp_path, monkeypatch):
    monkeypatch.setattr(du, "STORE", tmp_path / "dynamic_universe.json")
    yield


def test_promote_adds_new_tickers():
    added = du.promote(["GD", "LMT"], source="policy L1", reason="tariff")
    assert sorted(added) == ["GD", "LMT"]
    assert sorted(du.active()) == ["GD", "LMT"]


def test_promote_never_adds_quarantined_or_existing():
    added = du.promote(["GD", "FJET", "SHLD"], source="policy L1",
                       exclude={"FJET", "SHLD"})
    assert added == ["GD"]
    assert "FJET" not in du.active()
    assert "SHLD" not in du.active()


def test_repeat_signal_refreshes_rather_than_duplicates():
    du.promote(["GD"], source="policy L1")
    added = du.promote(["GD"], source="policy L1")
    assert added == []                      # not re-added
    assert du.active() == ["GD"]
    assert du._load()["GD"]["hits"] == 2    # corroboration counted


def test_promotion_is_capped():
    many = [f"T{i}" for i in range(20)]
    du.promote(many, source="policy L1", max_tickers=3)
    assert len(du.active()) == 3


def test_stale_entries_expire():
    du.promote(["GD"], source="policy L1")
    entries = du._load()
    entries["GD"]["last_seen"] = (date.today() - timedelta(days=45)).isoformat()
    du._save(entries)
    assert du.active(ttl_days=30) == []


def test_fresh_entries_survive_expiry_sweep():
    du.promote(["GD"], source="policy L1")
    entries = du._load()
    entries["GD"]["last_seen"] = (date.today() - timedelta(days=5)).isoformat()
    du._save(entries)
    assert du.active(ttl_days=30) == ["GD"]


def test_active_honours_exclude():
    du.promote(["GD", "LMT"], source="policy L1")
    assert du.active(exclude={"GD"}) == ["LMT"]


def test_corrupt_store_is_survivable():
    du.STORE.parent.mkdir(parents=True, exist_ok=True)
    du.STORE.write_text("{not json")
    assert du.active() == []
    assert du.promote(["GD"], source="policy L1") == ["GD"]
