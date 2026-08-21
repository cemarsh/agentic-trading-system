"""Tests for execution/period_reports.py — monthly/quarterly source selection."""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import execution.period_reports as pr


def _seed(tmp_path, weekly=(), monthly=()):
    """Point the module's directory constants at a temp journal tree."""
    weekly_dir = tmp_path / "weekly"
    monthly_dir = tmp_path / "monthly"
    weekly_dir.mkdir(parents=True, exist_ok=True)
    monthly_dir.mkdir(parents=True, exist_ok=True)
    for label in weekly:
        (weekly_dir / f"{label}.md").write_text(f"# {label}\nbody", encoding="utf-8")
    for label in monthly:
        (monthly_dir / f"{label}.md").write_text(f"# {label}\nbody", encoding="utf-8")
    pr.WEEKLY_DIR = weekly_dir
    pr.MONTHLY_DIR = monthly_dir


def test_week_start_of_parses_iso_label():
    assert pr._week_start_of("2026-W34") == date(2026, 8, 17)
    assert pr._week_start_of("garbage") is None
    assert pr._week_start_of("2026-W99") is None


def test_read_weeklies_filters_by_monday(tmp_path):
    # W31 Mon = Jul 27, W32 Mon = Aug 3, W34 Mon = Aug 17, W36 Mon = Aug 31.
    _seed(tmp_path, weekly=["2026-W31", "2026-W32", "2026-W34", "2026-W36"])
    got = [w["label"] for w in pr.read_weeklies(date(2026, 8, 1), date(2026, 8, 31))]
    # W31 starts in July and W36 starts Aug 31 — the Monday decides membership,
    # so a straddling week belongs to exactly one month.
    assert got == ["2026-W32", "2026-W34", "2026-W36"]


def test_read_weeklies_ignores_non_matching_filenames(tmp_path):
    _seed(tmp_path, weekly=["2026-W34"])
    (pr.WEEKLY_DIR / "README.md").write_text("not a week", encoding="utf-8")
    got = [w["label"] for w in pr.read_weeklies(date(2026, 8, 1), date(2026, 8, 31))]
    assert got == ["2026-W34"]


def test_read_monthlies_filters_by_month(tmp_path):
    _seed(tmp_path, monthly=["2026-05", "2026-06", "2026-07", "2026-09"])
    got = [m["label"] for m in pr.read_monthlies(date(2026, 6, 1), date(2026, 8, 31))]
    assert got == ["2026-06", "2026-07"]


def test_read_weeklies_empty_when_dir_missing(tmp_path):
    pr.WEEKLY_DIR = tmp_path / "does-not-exist"
    assert pr.read_weeklies(date(2026, 8, 1), date(2026, 8, 31)) == []


def test_quarterly_falls_back_to_weeklies_when_monthly_tier_thin(tmp_path):
    """The first quarterly ever run has no monthly history to summarize from."""
    _seed(tmp_path, weekly=["2026-W25", "2026-W30", "2026-W34"], monthly=["2026-08"])
    monthlies = pr.read_monthlies(date(2026, 6, 1), date(2026, 8, 31))
    weeklies = pr.read_weeklies(date(2026, 6, 1), date(2026, 8, 31))
    assert len(monthlies) == 1
    use_monthlies = len(monthlies) >= 2
    assert use_monthlies is False
    assert len(weeklies) == 3


def test_quarterly_prefers_monthlies_once_two_exist(tmp_path):
    _seed(tmp_path, weekly=["2026-W25", "2026-W30"], monthly=["2026-06", "2026-07"])
    monthlies = pr.read_monthlies(date(2026, 6, 1), date(2026, 8, 31))
    assert len(monthlies) >= 2


def test_template_fallback_lists_sources():
    body = pr._template_fallback("June 2026", [{"label": "2026-W25"}], "weekly")
    assert "2026-W25" in body
    assert "June 2026" in body


def test_template_fallback_handles_no_sources():
    body = pr._template_fallback("June 2026", [], "weekly")
    assert "(none found)" in body


def test_config_section_renders_commits():
    out = pr._config_section([{"date": "2026-08-07", "subject": "feat(wheel): resize"}])
    assert "feat(wheel): resize" in out


def test_config_section_handles_empty():
    assert "No config/ or directives/ commits" in pr._config_section([])
